"""Encrypted local SSD backup and isolated recovery verification. Never restores over live data."""
from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b'PAGDOC_BACKUP_V1\0'
HEADER_SIZE = len(MAGIC) + 16 + 12
CHUNK = 1024 * 1024
PARTS = {'runtime.env', 'database.dump', 'objects.tar', 'proxy-data.tar'}
TABLES = ('tenants', 'users', 'workers', 'vehicles', 'documents', 'document_file_versions', 'audit', 'user_sessions')
REPO = Path(__file__).resolve().parents[2]


class BackupError(ValueError):
    pass


def key(password: str, salt: bytes) -> bytes:
    if len(password) < 16:
        raise BackupError('Usa una contraseña de respaldo de al menos 16 caracteres.')
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode('utf-8'))


def encrypt_file(source: Path, destination: Path, password: str) -> None:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    cipher = Cipher(algorithms.AES(key(password, salt)), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(header)
    created = False
    try:
        with source.open('rb') as src, destination.open('xb') as dst:
            created = True
            os.chmod(destination, 0o600)
            dst.write(header)
            while block := src.read(CHUNK):
                dst.write(cipher.update(block))
            dst.write(cipher.finalize())
            dst.write(cipher.tag)
            dst.flush()
            os.fsync(dst.fileno())
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def decrypt_file(source: Path, destination: Path, password: str) -> None:
    created = False
    try:
        with source.open('rb') as src:
            size = source.stat().st_size
            header = src.read(HEADER_SIZE)
            if size < HEADER_SIZE + 16 or not header.startswith(MAGIC) or len(header) != HEADER_SIZE:
                raise BackupError('Formato de respaldo inválido o incompleto.')
            src.seek(-16, os.SEEK_END)
            tag = src.read(16)
            salt, nonce = header[len(MAGIC):len(MAGIC)+16], header[-12:]
            cipher = Cipher(algorithms.AES(key(password, salt)), modes.GCM(nonce, tag)).decryptor()
            cipher.authenticate_additional_data(header)
            src.seek(HEADER_SIZE)
            remaining = size - HEADER_SIZE - 16
            with destination.open('xb') as dst:
                created = True
                os.chmod(destination, 0o600)
                while remaining:
                    block = src.read(min(CHUNK, remaining))
                    if not block:
                        raise BackupError('Respaldo incompleto.')
                    dst.write(cipher.update(block))
                    remaining -= len(block)
                dst.write(cipher.finalize())
        # Consumers may only open the plaintext archive after GCM authentication.
    except BaseException as exc:
        if created:
            destination.unlink(missing_ok=True)
        if isinstance(exc, InvalidTag):
            raise BackupError('Contraseña incorrecta o respaldo alterado. No se restauró ningún dato.') from exc
        raise


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as src:
        while block := src.read(CHUNK):
            result.update(block)
    return result.hexdigest()


def validate_objects(archive: Path) -> dict[str, tarfile.TarInfo]:
    result = {}
    with tarfile.open(archive, 'r:') as tar:
        for entry in tar:
            path = PurePosixPath(entry.name)
            if path.is_absolute() or '..' in path.parts or entry.issym() or entry.islnk():
                raise BackupError('Ruta no segura en archivo de objetos.')
            parts = list(path.parts)
            if parts and parts[0] == 'pagdoc-files':
                parts.pop(0)
            if entry.isdir():
                continue
            if not entry.isfile() or len(parts) != 2 or not re.fullmatch(r'[1-9][0-9]*', parts[0]) or not re.fullmatch(r'[0-9a-f]{32}\.bin', parts[1]):
                raise BackupError('Objeto no reconocido en el respaldo privado.')
            name = '/'.join(parts)
            if name in result:
                raise BackupError('Objeto duplicado en el respaldo.')
            result[name] = entry
    return result


def unpack_verified(source: Path, destination: Path) -> dict:
    # Only four fixed files are copied; never use extractall on a backup.
    with tarfile.open(source, 'r:') as archive:
        entries = archive.getmembers()
        if len(entries) != 5 or {e.name for e in entries} != PARTS | {'manifest.json'} or not all(e.isfile() for e in entries):
            raise BackupError('Contenido de respaldo inválido.')
        if archive.getmember('manifest.json').size > 65536:
            raise BackupError('Manifest demasiado grande.')
        manifest = json.load(archive.extractfile('manifest.json'))
        if manifest.get('format') != 1 or set(manifest.get('sha256', {})) != PARTS:
            raise BackupError('Manifest inválido.')
        if not isinstance(manifest.get('counts'), dict) or set(manifest['counts']) != set(TABLES):
            raise BackupError('Recuento de tablas inválido.')
        for name in PARTS:
            target = destination / name
            with target.open('xb') as dst, archive.extractfile(name) as src:
                os.chmod(target, 0o600)
                shutil.copyfileobj(src, dst, CHUNK)
            if digest(target) != manifest['sha256'][name]:
                raise BackupError('La integridad del respaldo no coincide.')
    validate_objects(destination / 'objects.tar')
    return manifest


class Docker:
    prefix = ['sudo', 'docker']

    def run(self, args, *, stdout=None, stdin=None, timeout=600):
        result = subprocess.run(self.prefix + list(args), stdin=stdin, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            error = BackupError('Falló una operación de respaldo en Docker. La base original no se reemplazó.')
            error.diagnostic = result.stderr.decode('utf-8', errors='replace')
            raise error
        return result.stdout

    def compose(self, config: Path, args, **kwargs):
        return self.run(['compose', '--project-name', 'pagdoc-private', '--env-file', str(config), '-f', str(REPO / 'deployment/local/compose.local.yml')] + list(args), **kwargs)

    def query(self, container, sql, *, live=False):
        user, database = ('pagdoc', 'pagdoc') if live else ('postgres', 'postgres')
        return self.run(['exec', container, 'psql', '-U', user, '-d', database, '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql]).decode().strip()


def counts_query() -> str:
    return 'SELECT json_build_object(' + ','.join("'%s',(SELECT count(*) FROM %s)" % (name, name) for name in TABLES) + ')::text;'


def verify_recovery(docker: Docker, folder: Path, manifest: dict) -> None:
    name = 'pagdoc-restorecheck-' + uuid.uuid4().hex
    created = False
    try:
        docker.run(['run', '--detach', '--pull', 'never', '--name', name, '--network', 'none', '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', 'postgres:17'])
        created = True
        for attempt in range(60):
            try:
                docker.run(['exec', name, 'pg_isready', '-U', 'postgres'], timeout=5)
                break
            except BackupError:
                time.sleep(0.5)
        else:
            raise BackupError('La base aislada de verificación no inició.')
        with (folder / 'database.dump').open('rb') as dump:
            docker.run(['exec', '-i', name, 'pg_restore', '--exit-on-error', '--no-owner', '-U', 'postgres', '-d', 'postgres'], stdin=dump)
        if json.loads(docker.query(name, counts_query())) != manifest['counts']:
            raise BackupError('Los recuentos de la restauración no coinciden.')
        rows = json.loads(docker.query(name, "SELECT coalesce(json_agg(json_build_object('tenant_id',tenant_id,'object_key',object_key,'size_bytes',size_bytes,'sha256',sha256)),'[]'::json) FROM document_file_versions;"))
        config = dict(line.split('=', 1) for line in (folder / 'runtime.env').read_text().splitlines() if line and not line.startswith('#'))
        cipher = Fernet(config['PAGDOC_ENCRYPTION_KEY'].encode())
        members = validate_objects(folder / 'objects.tar')
        with tarfile.open(folder / 'objects.tar', 'r:') as objects:
            for row in rows:
                member = members.get(str(row['tenant_id']) + '/' + row['object_key'] + '.bin')
                if member is None or member.size > 32 * 1024 * 1024:
                    raise BackupError('Falta un archivo o excede el límite de verificación.')
                data = cipher.decrypt(objects.extractfile(member).read())
                if len(data) != row['size_bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                    raise BackupError('Un archivo restaurado no coincide con su registro.')
    finally:
        if created:
            docker.run(['rm', '--force', name])


@contextmanager
def exclusive_operation(config: Path):
    if config.is_symlink() or not config.is_file() or config.stat().st_mode & 0o077 or config.parent.stat().st_mode & 0o077:
        raise BackupError('La configuración de origen debe tener permisos privados.')
    lock = config.parent / 'backup.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def create_backup(config: Path, destination: Path, password: str, docker=None) -> Path:
    key(password, b'0' * 16)  # Validate before pausing any services.
    docker = docker or Docker()
    destination = destination.expanduser().resolve()
    if destination == REPO or REPO in destination.parents:
        raise BackupError('El destino debe estar fuera del repositorio.')
    destination.mkdir(parents=True, exist_ok=True)
    filename = 'PAGDOC-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12] + '.pagdoc.enc'
    output = destination / filename
    partial = destination / (filename + '.partial')
    with exclusive_operation(config), tempfile.TemporaryDirectory(prefix='pagdoc-backup-', dir='/tmp') as work:
        folder = Path(work)
        running = docker.compose(config, ['ps', '--status', 'running', '--services']).decode().split()
        if not {'api', 'database', 'proxy'} <= set(running):
            raise BackupError('Inicia PAGDOC y comprueba su estado antes de respaldar.')
        ids = {service: docker.compose(config, ['ps', '-q', service]).decode().strip() for service in ('api', 'database', 'proxy')}
        print('Preparando una copia consistente: pausa breve de la aplicación.', flush=True)
        try:
            docker.compose(config, ['stop', 'proxy', 'api'])
            counts = json.loads(docker.query(ids['database'], counts_query(), live=True))
            with (folder / 'database.dump').open('xb') as dump:
                os.chmod(folder / 'database.dump', 0o600)
                docker.run(['exec', ids['database'], 'pg_dump', '-U', 'pagdoc', '-d', 'pagdoc', '--format=custom'], stdout=dump)
            for member, container, source in [('objects.tar', ids['api'], '/var/lib/pagdoc-files/.'), ('proxy-data.tar', ids['proxy'], '/data/.')]:
                with (folder / member).open('xb') as dst:
                    os.chmod(folder / member, 0o600)
                    docker.run(['cp', container + ':' + source, '-'], stdout=dst)
            shutil.copyfile(config, folder / 'runtime.env')
            os.chmod(folder / 'runtime.env', 0o600)
        finally:
            docker.compose(config, ['start', '--wait', 'api', 'proxy'], timeout=300)
        manifest = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'counts': counts, 'sha256': {name: digest(folder / name) for name in PARTS}}
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        with tarfile.open(folder / 'bundle.tar', 'w:') as archive:
            for name in sorted(PARTS | {'manifest.json'}):
                archive.add(folder / name, arcname=name, recursive=False)
        try:
            encrypt_file(folder / 'bundle.tar', partial, password)
            decrypt_file(partial, folder / 'verified.tar', password)
            restored = folder / 'verified'
            restored.mkdir(mode=0o700)
            recovered_manifest = unpack_verified(folder / 'verified.tar', restored)
            print('Comprobando restauración en una base temporal sin red.', flush=True)
            verify_recovery(docker, restored, recovered_manifest)
            if output.exists():
                raise BackupError('El nombre de respaldo ya existe; no se sobrescribirá.')
            partial.rename(output)
        finally:
            partial.unlink(missing_ok=True)
    print('OK: respaldo cifrado y restauración aislada verificados. Origen conservado.')
    return output


def main():
    parser = argparse.ArgumentParser(description='Respaldo cifrado local de PAGDOC con comprobación de recuperación.')
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('path', type=Path, help='Carpeta de destino para create o archivo cifrado para verify')
    args = parser.parse_args()
    os.umask(0o077)
    if subprocess.run(['sudo', '-v']).returncode:
        raise BackupError('No se pudo autorizar Docker con sudo.')
    if args.action == 'verify':
        password = getpass.getpass('Contraseña del respaldo existente: ')
        with tempfile.TemporaryDirectory(prefix='pagdoc-verify-', dir='/tmp') as work:
            folder = Path(work)
            decrypt_file(args.path.expanduser().resolve(), folder / 'bundle.tar', password)
            restored = folder / 'verified'
            restored.mkdir(mode=0o700)
            manifest = unpack_verified(folder / 'bundle.tar', restored)
            verify_recovery(Docker(), restored, manifest)
        print('OK: contraseña, integridad y restauración aislada verificadas. No se modificó el servidor original.')
        return
    password = getpass.getpass('Crea una contraseña para el respaldo (mínimo 16 caracteres): ')
    if password != getpass.getpass('Repite la contraseña del respaldo: '):
        raise BackupError('Las contraseñas no coinciden. No se creó el respaldo.')
    config = Path(os.environ.get('PAGDOC_RUNTIME_ENV', str(Path.home() / '.config/pagdoc-private/runtime.env'))).expanduser()
    output = create_backup(config, args.path, password)
    print('Archivo: ' + str(output))
    print('Guarda la contraseña por separado. Esta copia en el mismo SSD no protege frente a la pérdida o falla del disco.')


if __name__ == '__main__':
    try:
        main()
    except (BackupError, OSError, subprocess.SubprocessError, ValueError) as exc:
        raise SystemExit('No se completó el respaldo: ' + str(exc))
