"""Opt-in NetBird-only listener. Configuration contains no account credentials."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import ProxyHandler,HTTPSHandler,build_opener

NETWORK=ipaddress.ip_network('100.64.0.0/10')


def private_ip(value):
    address=ipaddress.ip_interface(value).ip
    if address.version!=4 or address not in NETWORK:raise ValueError('Se requiere una dirección IPv4 de NetBird (100.64.0.0/10).')
    return str(address)


def connected_ip(status,interfaces):
    if status.get('management',{}).get('connected') is not True:raise ValueError('NetBird no está conectado. Ejecuta remote-connect primero.')
    address=private_ip(status.get('netbirdIp',''))
    assigned={entry.get('local') for interface in interfaces for entry in interface.get('addr_info',[]) if entry.get('family')=='inet'}
    if address not in assigned:raise ValueError('La dirección NetBird no está asignada a Ubuntu. No se abre ningún puerto.')
    return address


def live_ip():
    try:
        status=json.loads(subprocess.run(['sudo','netbird','status','--json'],capture_output=True,text=True,check=True,timeout=20).stdout)
        interfaces=json.loads(subprocess.run(['ip','-j','address','show'],capture_output=True,text=True,check=True,timeout=10).stdout)
        return connected_ip(status,interfaces)
    except (FileNotFoundError,subprocess.SubprocessError,json.JSONDecodeError) as error:raise ValueError('No se pudo comprobar NetBird. Instala el cliente y conecta tu cuenta Free en este computador.') from error


def check_file(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or path.parent.stat().st_mode&0o077:raise ValueError('La configuración remota debe ser un archivo privado (600), en un directorio privado (700).')
    lines=path.read_text().splitlines()
    if len(lines)!=1 or not lines[0].startswith('PAGDOC_NETBIRD_IP='):raise ValueError('Configuración remota inesperada. No se carga su contenido.')
    value=lines[0].split('=',1)[1]
    address=private_ip(value)
    if address!=value:raise ValueError('Usa únicamente la dirección IP de NetBird, sin máscara ni otros datos.')
    return address


def enable(path,address):
    address=private_ip(address)
    if not path.parent.is_dir() or path.parent.stat().st_mode&0o077:raise ValueError('Genera primero la configuración privada con control.sh start.')
    if path.exists() or path.is_symlink():check_file(path)
    fd,name=tempfile.mkstemp(prefix='.remote-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as output:output.write('PAGDOC_NETBIRD_IP='+address+'\n');output.flush();os.fsync(output.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def verify(path,runtime):
    address=check_file(path)
    if live_ip()!=address:raise ValueError('Cambió la IP privada. Ejecuta remote-enable para actualizarla.')
    base=Path(__file__).resolve().parent
    command=['sudo','docker','compose','--project-name','pagdoc-private','--env-file',str(runtime),'--env-file',str(path),'-f',str(base/'compose.local.yml'),'-f',str(base/'compose.remote.yml')]
    certificate=subprocess.run(command+['exec','-T','proxy','cat','/data/caddy/pki/authorities/local/root.crt'],capture_output=True,text=True,check=True,timeout=20).stdout
    if len(certificate)>65536 or 'PRIVATE KEY' in certificate:raise ValueError('Respuesta de certificado inesperada.')
    context=ssl.create_default_context(cadata=certificate)
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
    origin='https://'+address+':8443'
    with opener.open(origin+'/app',timeout=15) as response:
        if response.status!=200:raise ValueError('La interfaz HTTPS no está disponible.')
    try:
        with opener.open(origin+'/ops/bootstrap',timeout=15):raise ValueError('El servidor permitió consultar datos sin sesión.')
    except HTTPError as error:
        if error.code!=401:raise ValueError('La comprobación de autenticación no devolvió el resultado esperado.') from error
    output=path.parent/'pagdoc-ca-publica.crt'
    if output.is_symlink():raise ValueError('Destino de certificado inesperado.')
    with output.open('w') as file:file.write(certificate)
    os.chmod(output,0o600)
    fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest()
    print('HTTPS y bloqueo de datos sin sesión comprobados desde el servidor.')
    print('Enlace privado: '+origin+'/app')
    print('Certificado público para los equipos autorizados: '+str(output))
    print('Huella SHA-256 del certificado: '+fingerprint)
    print('Falta comprobar el enlace desde otro equipo conectado a tu red NetBird. No es un enlace público.')


def main():
    task=sys.argv[1]
    runtime=Path(os.environ.get('PAGDOC_RUNTIME_ENV',str(Path.home()/'.config/pagdoc-private/runtime.env'))).expanduser()
    path=Path(os.environ.get('PAGDOC_REMOTE_ENV',str(runtime.parent/'remote.env'))).expanduser()
    if task=='check-config':check_file(path)
    elif task=='enable':enable(path,live_ip());print('Configuración privada preparada; se conservará el acceso local.')
    elif task=='check-live':
        if check_file(path)!=live_ip():raise ValueError('La dirección de NetBird cambió. Ejecuta remote-enable.')
    elif task=='disable':
        if path.exists() or path.is_symlink():check_file(path);path.unlink()
        print('Entrada remota desactivada; se conserva el servidor local y sus datos.')
    elif task=='verify':verify(path,runtime)
    elif task=='status':
        if not path.exists():print('Acceso remoto aún no activado.');return
        address=check_file(path)
        print('Entrada configurada: https://'+address+':8443/app')
        print('NetBird conectado y dirección verificada.' if live_ip()==address else 'La dirección de NetBird cambió; ejecuta remote-enable.')
    else:raise ValueError('Operación remota desconocida.')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.SubprocessError) as error:raise SystemExit(str(error))
