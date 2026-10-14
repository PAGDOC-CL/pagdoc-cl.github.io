"""Explicit interactive provisioning for an isolated fictitious beta tenant.

Supports staging PostgreSQL after migrations. Never logs a password, never sends
messages, never resets an existing account and rejects real email domains.
"""
import getpass
import os
import re
from sqlalchemy import select


def provision(db,tenant_name,email,password):
    import app as core
    name=tenant_name.strip();address=email.strip().lower()
    if not name or len(name)>150 or not re.fullmatch(r'[a-z0-9._+-]+@example\.invalid',address):
        raise ValueError('Use a fictitious tenant and an @example.invalid identity')
    if len(password)<12:raise ValueError('Use at least 12 characters')
    if db.scalar(select(core.User.id).where(core.User.email==address)) is not None:raise ValueError('Account already exists; nothing changed')
    tenant=db.scalar(select(core.Tenant).where(core.Tenant.name==name))
    if tenant is None:tenant=core.Tenant(name=name);db.add(tenant);db.flush()
    user=core.User(tenant_id=tenant.id,email=address,password_hash=core.hasher.hash(password),role='admin',active=1);db.add(user);db.flush()
    core.add_audit(db,user,'beta.admin_provision','user',user.id)
    return user.id


def main():
    if os.getenv('PAGDOC_ALLOW_BETA_PROVISIONING')!='YES':raise SystemExit('Blocked: explicitly authorize fictitious beta provisioning')
    if os.getenv('PAGDOC_ENVIRONMENT','development') not in {'development','test','staging'}:raise SystemExit('Blocked outside isolated beta environments')
    import server
    import app as core
    from ops_api import readiness_ok
    with core.SessionLocal() as db:
        if not readiness_ok(db,'staging'):raise SystemExit('Apply migrations before provisioning')
        name=input('Fictitious tenant name: ');email=input('Fictitious administrator @example.invalid: ')
        password=getpass.getpass('Private beta password (at least 12 characters): ')
        if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords do not match')
        try:provision(db,name,email,password);db.commit()
        except ValueError as exc:db.rollback();raise SystemExit(str(exc))
    print('Fictitious beta administrator created. No messages were sent.')

if __name__=='__main__':main()
