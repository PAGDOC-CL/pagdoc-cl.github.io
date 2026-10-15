"""Local operator provisioning for explicitly requested administrators; no mail sent."""
import argparse
from email.headerregistry import Address
import os
import secrets
from sqlalchemy import delete,select

import server
import app as core
from email_alerts import EmailPreference,preference


def provision_members(db,emails,enable_alerts=False):
    tenants=list(db.scalars(select(core.Tenant).limit(2)))
    if len(tenants)!=1:raise ValueError('El asistente requiere una sola empresa configurada; revisa los destinos con el administrador.')
    tenant=tenants[0]
    actor=db.scalar(select(core.User).where(core.User.tenant_id==tenant.id,core.User.role=='admin',core.User.active==1).order_by(core.User.id).limit(1))
    if actor is None:raise ValueError('Primero debe existir el administrador inicial de esta empresa.')
    addresses=[]
    for value in emails:
        email=value.strip().lower();address=Address(addr_spec=email)
        if '@' not in email or not address.domain or len(email)>255:raise ValueError('Revisa los correos registrados.')
        if email not in addresses:addresses.append(email)
    results=[]
    for email in addresses:
        user=db.scalar(select(core.User).where(core.User.email==email));password=None
        if user is not None and user.tenant_id!=tenant.id:raise ValueError('Un correo pertenece a otra empresa; no se modificó su acceso.')
        if user is None:
            password=secrets.token_urlsafe(24)
            user=core.User(tenant_id=tenant.id,email=email,password_hash=core.hasher.hash(password),role='admin',active=1);db.add(user);db.flush()
        else:
            db.execute(delete(core.UserSession).where(core.UserSession.user_id==user.id));user.role='admin';user.active=1
        if enable_alerts:
            pref=preference(db,user)
            if pref is None:pref=EmailPreference(tenant_id=tenant.id,user_id=user.id);db.add(pref)
            pref.enabled=1
        core.add_audit(db,actor,'user.local_admin_grant','user',user.id)
        results.append({'email':email,'new_password':password})
    db.commit()
    return results


def main():
    if os.getenv('PAGDOC_ALLOW_MEMBER_PROVISIONING')!='YES':raise SystemExit('Usa el controlador local autorizado del servidor.')
    parser=argparse.ArgumentParser();parser.add_argument('--emails',nargs='+',required=True);parser.add_argument('--enable-alerts',action='store_true');args=parser.parse_args()
    try:
        with core.SessionLocal() as db:results=provision_members(db,args.emails,args.enable_alerts)
    except (ValueError,TypeError):raise SystemExit('No se completó el alta. Revisa los correos y la empresa. No se enviaron mensajes.')
    for row in results:
        print('Administrador: '+row['email'])
        if row['new_password']:print('Contraseña inicial (solo en esta terminal): '+row['new_password'])
        else:print('Se conserva la contraseña existente; las sesiones anteriores fueron revocadas.')
    print('Accesos guardados. Los avisos requieren SMTP configurado y el servicio de notificaciones activo.')


if __name__=='__main__':main()
