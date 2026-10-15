import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

spec = importlib.util.spec_from_file_location('private_backup', Path(__file__).resolve().parent.parent / 'deployment/local/backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
PASSWORD = 'fictitious-only-backup-password'


def test_authenticated_encryption_roundtrip_and_randomness(tmp_path):
    source = tmp_path / 'plain'
    source.write_bytes(b'fictitious database and private configuration' * 30000)
    first, second = tmp_path / 'first.enc', tmp_path / 'second.enc'
    backup.encrypt_file(source, first, PASSWORD)
    backup.encrypt_file(source, second, PASSWORD)
    assert first.read_bytes() != second.read_bytes()
    assert source.read_bytes() not in first.read_bytes()
    assert first.stat().st_mode & 0o777 == 0o600
    restored = tmp_path / 'restored'
    backup.decrypt_file(first, restored, PASSWORD)
    assert restored.read_bytes() == source.read_bytes()


@pytest.mark.parametrize('damage', ['password', 'header', 'ciphertext', 'tag', 'truncate'])
def test_wrong_password_or_tamper_never_leaves_plaintext(tmp_path, damage):
    source, encrypted, restored = tmp_path / 'source', tmp_path / 'encrypted', tmp_path / 'restored'
    source.write_bytes(b'fictitious private content')
    backup.encrypt_file(source, encrypted, PASSWORD)
    raw = bytearray(encrypted.read_bytes())
    if damage == 'header':
        raw[len(backup.MAGIC)] ^= 1
    elif damage == 'ciphertext':
        raw[backup.HEADER_SIZE] ^= 1
    elif damage == 'tag':
        raw[-1] ^= 1
    elif damage == 'truncate':
        del raw[-20:]
    encrypted.write_bytes(raw)
    with pytest.raises(backup.BackupError):
        backup.decrypt_file(encrypted, restored, PASSWORD + '-wrong' if damage == 'password' else PASSWORD)
    assert not restored.exists()


def test_existing_backup_is_never_overwritten(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'existing'
    source.write_bytes(b'fictitious')
    target.write_bytes(b'existing backup')
    with pytest.raises(FileExistsError):
        backup.encrypt_file(source, target, PASSWORD)
    assert target.read_bytes() == b'existing backup'


def object_tar(path, entries):
    with tarfile.open(path, 'w:') as tar:
        for name, kind in entries:
            entry = tarfile.TarInfo(name)
            if kind == 'link':
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/etc/passwd'
                tar.addfile(entry)
            else:
                entry.size = 1
                tar.addfile(entry, io.BytesIO(b'x'))


@pytest.mark.parametrize('name,kind', [('../secret','file'), ('/absolute','file'), ('1/a','file'), ('1/'+'a'*32+'.bin','link')])
def test_object_paths_and_links_are_rejected(tmp_path, name, kind):
    archive = tmp_path / 'objects.tar'
    object_tar(archive, [(name, kind)])
    with pytest.raises(backup.BackupError):
        backup.validate_objects(archive)


def test_docker_archive_normalized_without_extraction(tmp_path):
    archive = tmp_path / 'objects.tar'
    object_tar(archive, [('./1/'+'a'*32+'.bin', 'file')])
    assert list(backup.validate_objects(archive)) == ['1/'+'a'*32+'.bin']


def test_fixed_bundle_members_and_hashes_checked(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for name in backup.PARTS:
        (source / name).write_bytes(b'fictitious')
    object_tar(source / 'objects.tar', [('./1/'+'a'*32+'.bin', 'file')])
    manifest = {'format': 1, 'counts': {name: 0 for name in backup.TABLES}, 'sha256': {name: backup.digest(source / name) for name in backup.PARTS}}
    (source / 'manifest.json').write_text(json.dumps(manifest))
    bundle = tmp_path / 'bundle.tar'
    with tarfile.open(bundle, 'w:') as tar:
        for file in source.iterdir():
            tar.add(file, arcname=file.name)
    destination = tmp_path / 'restored'
    destination.mkdir()
    assert backup.unpack_verified(bundle, destination) == manifest
    manifest['sha256']['runtime.env'] = '0' * 64
    (source / 'manifest.json').write_text(json.dumps(manifest))
    with tarfile.open(bundle, 'w:') as tar:
        for file in source.iterdir():
            tar.add(file, arcname=file.name)
    failed = tmp_path / 'failed'
    failed.mkdir()
    with pytest.raises(backup.BackupError, match='integridad'):
        backup.unpack_verified(bundle, failed)


def test_unsafe_configuration_and_concurrent_backups_rejected(tmp_path):
    config = tmp_path / 'private' / 'runtime.env'
    config.parent.mkdir(mode=0o700)
    config.write_text('fictitious')
    config.chmod(0o600)
    with backup.exclusive_operation(config):
        with pytest.raises(BlockingIOError):
            with backup.exclusive_operation(config):
                pass
    config.chmod(0o644)
    with pytest.raises(backup.BackupError, match='privados'):
        with backup.exclusive_operation(config):
            pass


def test_failed_dump_restarts_original_services_without_deleting_data(tmp_path):
    config = tmp_path / 'private' / 'runtime.env'
    config.parent.mkdir(mode=0o700)
    config.write_text('fictitious')
    config.chmod(0o600)
    class FailedDump:
        def __init__(self):
            self.calls = []
        def compose(self, config, args, **kwargs):
            self.calls.append(args)
            if args == ['ps', '--status', 'running', '--services']:
                return b'api\ndatabase\nproxy\n'
            if args[:2] == ['ps', '-q']:
                return ('fictitious-' + args[-1]).encode()
            return b''
        def query(self, *args, **kwargs):
            return json.dumps({name: 0 for name in backup.TABLES})
        def run(self, *args, **kwargs):
            raise backup.BackupError('fictitious dump failure')
    docker = FailedDump()
    with pytest.raises(backup.BackupError, match='dump failure'):
        backup.create_backup(config, tmp_path / 'backups', PASSWORD, docker)
    assert docker.calls[-1] == ['start', '--wait', 'api', 'proxy']
    assert not list((tmp_path / 'backups').iterdir())
