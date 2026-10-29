"""Configure and verify an existing SMTP account locally, without sending mail."""
import getpass
import os
from pathlib import Path
import smtplib
import ssl
import tempfile
from email.headerregistry import Address


def save_values(path,values):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or path.parent.stat().st_mode&0o077:raise ValueError('La configuración debe existir y tener permisos 600.')
    for key,value in values.items():
        if any(c in value for c in '\r\n\x00'):raise ValueError('Valor de configuración inválido.')
    existing=path.read_text().splitlines()
    filtered=[line for line in existing if line.split('=',1)[0] not in values]
    filtered += [key+"="+(value if key=="PAGDOC_EMAIL_DELIVERY_ENABLED" else "'"+value.replace("'","\\'")+"'") for key,value in values.items()]
    fd,name=tempfile.mkstemp(prefix='.email-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as file:file.write('\n'.join(filtered)+'\n');file.flush();os.fsync(file.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def main():
    path=Path(os.environ.get('PAGDOC_RUNTIME_ENV',str(Path.home()/'.config/pagdoc-private/runtime.env'))).expanduser()
    print('Usa una cuenta SMTP existente autorizada por tu proveedor. Este asistente prueba la conexión y no envía mensajes.')
    host=input('Servidor SMTP: ').strip();port=input('Puerto seguro [587 o 465]: ').strip();username=input('Usuario SMTP: ').strip();sender=input('Correo remitente: ').strip();password=getpass.getpass('Credencial SMTP autorizada (oculta): ')
    if not host or port not in {'465','587'} or not username or not password:raise SystemExit('Revisa los datos del proveedor.')
    try:
        Address(addr_spec=sender)
        context=ssl.create_default_context()
        connection=smtplib.SMTP_SSL(host,int(port),timeout=30,context=context) if port=='465' else smtplib.SMTP(host,int(port),timeout=30)
        with connection as smtp:
            if port=='587':smtp.starttls(context=context)
            smtp.login(username,password)
    except Exception:raise SystemExit('No se verificó la cuenta. No se guardaron cambios. Revisa el método de autenticación admitido por tu proveedor.')
    save_values(path,{'PAGDOC_EMAIL_DELIVERY_ENABLED':'1','PAGDOC_SMTP_AUTH_MODE':'password','PAGDOC_SMTP_HOST':host,'PAGDOC_SMTP_PORT':port,'PAGDOC_SMTP_USERNAME':username,'PAGDOC_SMTP_PASSWORD':password,'PAGDOC_SMTP_FROM':sender})
    print('Cuenta verificada y guardada de forma privada. Inicia PAGDOC para activar el servicio. No se envió ningún mensaje de prueba.')


if __name__=='__main__':main()
