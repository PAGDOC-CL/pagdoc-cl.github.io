"""Microsoft 365 delegated SMTP OAuth. Tokens stay encrypted in private storage.

Login is explicit and interactive; workers only refresh an existing grant.
No device code, token or SMTP reply is included in error messages.
"""
import argparse
from contextlib import contextmanager
from email.headerregistry import Address
import fcntl
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import stat
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import UUID

from cryptography.fernet import Fernet

SCOPE = 'https://outlook.office.com/SMTP.Send'
HOST = 'smtp.office365.com'


class OAuthError(RuntimeError):
    pass


def identifier(value):
    return str(UUID(value))


def mailbox(value):
    if any(c in value for c in '\r\n\x00\x01') or Address(addr_spec=value).addr_spec != value or '@' not in value:
        raise OAuthError('Correo remitente inválido.')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def post(tenant, endpoint, values):
    if endpoint not in {'devicecode', 'token'}:
        raise OAuthError('Endpoint OAuth inválido.')
    url = f'https://login.microsoftonline.com/{identifier(tenant)}/oauth2/v2.0/{endpoint}'
    request = Request(url, data=urlencode(values).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        response = build_opener(NoRedirect).open(request, timeout=30)
    except HTTPError as exc:
        if exc.code != 400:
            raise OAuthError('Microsoft no pudo completar la solicitud OAuth.') from None
        response = exc
    with response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise OAuthError('Respuesta OAuth demasiado grande.')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise OAuthError('Respuesta OAuth inválida.')
    return result


def fail(result):
    code = result.get('error', 'invalid_response')
    if not isinstance(code, str) or not re.fullmatch(r'[a-zA-Z0-9_]{1,80}', code):
        code = 'invalid_response'
    numbers = result.get('error_codes', [])
    aad = ', '.join('AADSTS' + str(n) for n in numbers if type(n) is int) if isinstance(numbers, list) else ''
    raise OAuthError(f'Microsoft rechazó la autorización: {code} {aad}. Revisa consentimiento, permisos y políticas de la organización.')


def token_result(result):
    if not isinstance(result.get('access_token'), str) or not result['access_token']:
        fail(result)
    scopes = result.get('scope', '').split()
    if not any(scope in {'SMTP.Send', SCOPE, 'https://outlook.office365.com/SMTP.Send'} for scope in scopes):
        raise OAuthError('El token no contiene el permiso SMTP.Send.')
    expires = int(result.get('expires_in', 0))
    if not 0 < expires <= 86400:
        raise OAuthError('Duración de token inválida.')
    return {'access_token': result['access_token'], 'expires_at': time.time() + expires,
            'refresh_token': result.get('refresh_token')}


def device_login(tenant, client, username, request=post, sleep=time.sleep, clock=time.monotonic):
    tenant, client, username = identifier(tenant), identifier(client), mailbox(username)
    flow = request(tenant, 'devicecode', {'client_id': client, 'scope': SCOPE + ' offline_access'})
    if 'device_code' not in flow:
        fail(flow)
    uri = flow.get('verification_uri', '')
    parsed = urlsplit(uri)
    if parsed.scheme != 'https' or parsed.hostname not in {'microsoft.com', 'www.microsoft.com', 'login.microsoftonline.com'} or parsed.username or parsed.fragment:
        raise OAuthError('Dirección de autorización inesperada.')
    interval = max(5, min(int(flow.get('interval', 5)), 60))
    deadline = clock() + min(max(int(flow.get('expires_in', 900)), 1), 1800)
    print('Autoriza únicamente la aplicación PAGDOC Notificaciones y la cuenta ' + username, flush=True)
    print('Abre ' + uri + ' e introduce este código: ' + str(flow['user_code']), flush=True)
    print('No compartas el código ni los tokens. Si Microsoft exige aprobación del administrador, detente en esa pantalla.', flush=True)
    while clock() < deadline:
        sleep(interval)
        if clock() >= deadline:
            break
        result = request(tenant, 'token', {'client_id': client, 'device_code': flow['device_code'],
                         'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'})
        if result.get('error') == 'authorization_pending':
            continue
        if result.get('error') == 'slow_down':
            interval = min(interval + 5, 120)
            continue
        tokens = token_result(result)
        if not tokens.get('refresh_token'):
            raise OAuthError('No se concedió renovación. No se guardó la conexión.')
        return {'tenant': tenant, 'client': client, 'username': username, **tokens}
    raise OAuthError('El código de autorización venció. Ejecuta nuevamente el asistente cuando estés listo.')


def private_dir():
    root = Path(os.getenv('PAGDOC_STORAGE_ROOT', '/var/lib/pagdoc-files'))
    directory = root / '.pagdoc-mail'
    if root.is_symlink() or directory.is_symlink():
        raise OAuthError('Almacenamiento OAuth inválido.')
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise OAuthError('El directorio OAuth debe ser privado y pertenecer al servicio.')
    return directory


@contextmanager
def locked():
    directory = private_dir()
    fd = os.open(directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OAuthError('Bloqueo OAuth no privado.')
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield directory / 'tokens.enc'


def read_cache(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OAuthError('El archivo OAuth no es privado.')
        return json.loads(Fernet(os.environ['PAGDOC_ENCRYPTION_KEY'].encode()).decrypt(handle.read(1024 * 1024)))


def save_cache(path, data):
    encrypted = Fernet(os.environ['PAGDOC_ENCRYPTION_KEY'].encode()).encrypt(json.dumps(data).encode())
    fd, name = tempfile.mkstemp(prefix='.tokens-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(encrypted); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def configured():
    try:
        with locked() as path:
            data = read_cache(path)
            return data['username'] == os.getenv('PAGDOC_SMTP_USERNAME') and bool(data['refresh_token'])
    except Exception:
        return False


def access_token(username):
    with locked() as path:
        data = read_cache(path)
        if data['username'] != mailbox(username):
            raise OAuthError('La autorización OAuth corresponde a otra cuenta.')
        if data['expires_at'] > time.time() + 120:
            return data['access_token']
        refreshed = token_result(post(data['tenant'], 'token', {
            'client_id': identifier(data['client']), 'grant_type': 'refresh_token',
            'refresh_token': data['refresh_token'], 'scope': SCOPE + ' offline_access'}))
        if not refreshed.get('refresh_token'):
            refreshed['refresh_token'] = data['refresh_token']
        data.update(refreshed)
        save_cache(path, data)
        return data['access_token']


def authenticate(smtp, username, token):
    mailbox(username)
    # smtplib base64 encodes this string; a challenge gets an empty response.
    auth = f'user={username}\x01auth=Bearer {token}\x01\x01'
    smtp.auth('XOAUTH2', lambda challenge=None: auth if challenge is None else '')


def check_login(username, token):
    with smtplib.SMTP(HOST, 587, timeout=30) as smtp:
        smtp.ehlo(); smtp.starttls(context=ssl.create_default_context()); smtp.ehlo()
        authenticate(smtp, username, token)


def main():
    parser = argparse.ArgumentParser(description='Autoriza SMTP Microsoft 365 sin enviar correo.')
    parser.add_argument('--tenant', required=True, type=identifier)
    parser.add_argument('--client', required=True, type=identifier)
    parser.add_argument('--username', required=True, type=mailbox)
    args = parser.parse_args()
    try:
        data = device_login(args.tenant, args.client, args.username)
        check_login(args.username, data['access_token'])
        with locked() as path:
            save_cache(path, data)
    except KeyboardInterrupt:
        raise SystemExit('Autorización cancelada. No se activó el envío.') from None
    except OAuthError as exc:
        raise SystemExit(str(exc)) from None
    except smtplib.SMTPAuthenticationError:
        raise SystemExit('OAuth autorizado, pero Exchange rechazó SMTP AUTH. El administrador debe revisar la habilitación del buzón y sus políticas. No se guardó la nueva conexión.') from None
    except Exception:
        raise SystemExit('No se verificó la conexión OAuth/SMTP. No se guardó la nueva autorización ni se envió correo.') from None
    print('Autorización y SMTP verificados. Credenciales cifradas en almacenamiento privado. No se envió correo.', flush=True)


if __name__ == '__main__':
    main()
