"""Local-operator bootstrap of the first private company administrator.

No HTTP route, email delivery, mailbox verification or document enablement.
The company and account are supplied interactively on the private host only.
"""
import getpass
import os
import re
from sqlalchemy import select, text


def validate_identity(tenant_name, email):
    name=tenant_name.strip();address=email.strip().lower()
    if not name or len(name)>150 or any(ord(c)<32 for c in name):
        raise ValueError('Ingresa un nombre de empresa de 1 a 150 caracteres.')
    local,separator,domain=address.partition('@')
    if len(address)>255 or not separator or not re.fullmatch(r'[a-z0-9][a-z0-9._+\-]*',local) or local.endswith('.') or '..' in local or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',domain):
        raise ValueError('Ingresa un correo con formato válido. No se enviarán mensajes.')
    return name,address


def provision(db,tenant_name,email,password):
    import app as core
    name,address=validate_identity(tenant_name,email)
    if not 12<=len(password)<=1024:
        raise ValueError('La contraseña debe tener entre 12 y 1024 caracteres.')
    # Serialize first-account creation across concurrent PostgreSQL operators.
    if db.get_bind().dialect.name=='postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(70724001)'))
    if db.scalar(select(core.User.id).where(core.User.email==address)) is not None:
        raise ValueError('La cuenta ya existe. No se modificó su acceso.')
    tenants=db.scalars(select(core.Tenant).where(core.Tenant.name==name).with_for_update()).all()
    if len(tenants)>1:
        raise ValueError('Hay empresas con nombres repetidos. Requiere revisión antes de continuar.')
    tenant=tenants[0] if tenants else None
    if tenant is not None and db.scalar(select(core.User.id).where(core.User.tenant_id==tenant.id)) is not None:
        raise ValueError('La empresa ya tiene usuarios. Usa su administrador para gestionar accesos.')
    if tenant is None:
        tenant=core.Tenant(name=name);db.add(tenant);db.flush()
    user=core.User(tenant_id=tenant.id,email=address,password_hash=core.hasher.hash(password),role='admin',active=1)
    db.add(user);db.flush()
    core.add_audit(db,user,'admin.initial_provision','user',user.id)
    return user.id


def main():
    if os.getenv('PAGDOC_ALLOW_ADMIN_PROVISIONING')!='YES':
        raise SystemExit('Ejecuta el aprovisionamiento autorizado desde el controlador local.')
    if os.getenv('PAGDOC_ENVIRONMENT') not in {'staging','production'}:
        raise SystemExit('El registro corporativo requiere un entorno privado configurado.')
    import server
    import app as core
    from ops_api import readiness_ok
    with core.SessionLocal() as db:
        if not readiness_ok(db,os.environ['PAGDOC_ENVIRONMENT']):
            raise SystemExit('Aplica y verifica las migraciones antes de crear la cuenta.')
        print('Registro del primer administrador de la empresa en esta instancia privada.')
        print('El correo identifica el acceso local. No conecta ni verifica Microsoft 365.')
        while True:
            name=input('Nombre de la empresa: ');email=input('Correo del administrador: ')
            try:name,email=validate_identity(name,email);break
            except ValueError as exc:print(str(exc))
        while True:
            password=getpass.getpass('Contraseña de PAGDOC (mínimo 12 caracteres): ')
            if not 12<=len(password)<=1024:print('La contraseña debe tener entre 12 y 1024 caracteres.');continue
            if password!=getpass.getpass('Repite la contraseña de PAGDOC: '):print('Las contraseñas no coinciden. Intenta nuevamente.');continue
            break
        try:provision(db,name,email,password);db.commit()
        except ValueError as exc:db.rollback();raise SystemExit(str(exc))
    print('Administrador de empresa creado. Configura MFA después del primer ingreso.')
    print('Los documentos y SharePoint siguen pendientes de habilitación y verificación.')


if __name__=='__main__':main()
