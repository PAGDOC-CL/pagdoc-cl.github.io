"""Local-only bootstrap for fictitious PAGDOC tenants and test accounts.

Run from backend/: python bootstrap_demo.py
Never run with real personnel, real passwords, or production databases.
"""
import getpass
import os
import sys
from urllib.parse import urlparse

if os.getenv("PAGDOC_ALLOW_DEMO_BOOTSTRAP") != "YES":
    sys.exit("Blocked: set PAGDOC_ALLOW_DEMO_BOOTSTRAP=YES for an explicit local demo.")
if os.getenv("PAGDOC_DATABASE_URL", "sqlite:///./pagdoc_dev.sqlite3").startswith("sqlite:///") is False:
    sys.exit("Blocked: demo bootstrap supports local SQLite only.")
if not os.getenv("PAGDOC_SECRET_KEY") or len(os.environ["PAGDOC_SECRET_KEY"]) < 32:
    sys.exit("Set a local PAGDOC_SECRET_KEY (at least 32 characters).")

from sqlalchemy import select
from app import Base, SessionLocal, Tenant, User, engine, hasher

Base.metadata.create_all(engine)
print("PAGDOC | CREACIÓN DE DATOS FICTICIOS (SOLO PRUEBAS LOCALES)")
print("Use exclusively invented company names and email addresses ending in .invalid.")
tenant_name = input("Nombre de empresa ficticia: ").strip()
email = input("Correo ficticio (example.invalid): ").strip().lower()
if not tenant_name or len(tenant_name) > 150 or not email.endswith("@example.invalid"):
    sys.exit("Use a fictitious company name and an email ending in @example.invalid.")
password = getpass.getpass("Contraseña de prueba (mínimo 12 caracteres): ")
confirm = getpass.getpass("Confirmar contraseña: ")
if len(password) < 12 or password != confirm:
    sys.exit("Passwords must match and contain at least 12 characters.")

with SessionLocal.begin() as db:
    if db.scalar(select(User).where(User.email == email)):
        sys.exit("That demo email is already registered.")
    tenant = db.scalar(select(Tenant).where(Tenant.name == tenant_name))
    if tenant is None:
        tenant = Tenant(name=tenant_name)
        db.add(tenant)
        db.flush()
    user = User(tenant_id=tenant.id, email=email,
                password_hash=hasher.hash(password), role="admin")
    db.add(user)
print("Demo tenant and local administrator created. No emails were sent.")
