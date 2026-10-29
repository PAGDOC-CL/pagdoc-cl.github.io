"""Authorize inside the running private container; never handle tokens on host."""
import argparse
import os
from pathlib import Path
import subprocess
from uuid import UUID

from configure_email import save_values


def main():
    parser=argparse.ArgumentParser(description='Configura Microsoft OAuth sin contraseña ni envío de prueba.')
    parser.add_argument('--tenant',required=True,type=lambda value:str(UUID(value)))
    parser.add_argument('--client',required=True,type=lambda value:str(UUID(value)))
    parser.add_argument('--username',required=True)
    args=parser.parse_args()
    if any(c in args.username for c in '\r\n\x00\x01') or '@' not in args.username:
        raise SystemExit('Correo inválido.')
    path=Path(os.environ.get('PAGDOC_RUNTIME_ENV',str(Path.home()/'.config/pagdoc-private/runtime.env'))).expanduser()
    # Validate file permissions before the user starts granting access.
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or path.parent.stat().st_mode&0o077:
        raise SystemExit('La configuración privada debe existir y tener permisos 600 en directorio 700.')
    command=['bash',str(Path(__file__).with_name('control.sh')),'email-oauth-login',
             '--tenant',args.tenant,'--client',args.client,'--username',args.username]
    result=subprocess.run(command,check=False)
    if result.returncode:
        raise SystemExit('No se activó el envío. Revisa el resultado de Microsoft mostrado arriba.')
    values={'PAGDOC_EMAIL_DELIVERY_ENABLED':'1','PAGDOC_SMTP_AUTH_MODE':'microsoft_oauth',
            'PAGDOC_SMTP_HOST':'smtp.office365.com','PAGDOC_SMTP_PORT':'587',
            'PAGDOC_SMTP_USERNAME':args.username,'PAGDOC_SMTP_FROM':args.username,
            'PAGDOC_SMTP_PASSWORD':''}
    remote=Path(os.environ.get('PAGDOC_REMOTE_ENV',str(path.with_name('remote.env'))))
    if remote.exists():
        from remote_access import check_file
        values['PAGDOC_PASSWORD_RESET_URL']='https://'+check_file(remote)+':8443/app'
    save_values(path,values)
    print('Configuración guardada. Ejecuta control.sh start para activar el servicio. Aún no se envió ningún correo.')


if __name__=='__main__':main()
