"""PAGDOC private API prototype.

Security-first development backend. It is intentionally NOT deployed and must not
be used with real personal/company documents until the production security gates
in ROADMAP.md are completed.
"""
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from password_policy import valid_password, MESSAGE
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, create_engine, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DB_URL = os.getenv("PAGDOC_DATABASE_URL", "sqlite:///./pagdoc_dev.sqlite3")
SECRET = os.getenv("PAGDOC_SECRET_KEY", "")
ENCRYPTION_KEY = os.getenv("PAGDOC_ENCRYPTION_KEY", "")
if not SECRET or len(SECRET) < 32:
    raise RuntimeError("Set PAGDOC_SECRET_KEY to a random value of at least 32 characters")

SESSION_SECONDS = int(os.getenv("PAGDOC_SESSION_SECONDS", "3600"))
LOGIN_WINDOW_MINUTES = int(os.getenv("PAGDOC_LOGIN_WINDOW_MINUTES", "15"))
LOGIN_MAX_FAILURES = int(os.getenv("PAGDOC_LOGIN_MAX_FAILURES", "5"))

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine)
hasher = PasswordHash.recommended()


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    active: Mapped[int] = mapped_column(Integer, default=1)
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mfa_enabled: Mapped[int] = mapped_column(Integer, default=0)
    password_change_required: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    temporary_password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    active: Mapped[int] = mapped_column(Integer, default=1)


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    identifier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[int] = mapped_column(Integer, default=1)


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    plate: Mapped[str | None] = mapped_column(String(30), nullable=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[int] = mapped_column(Integer, default=1)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(1024))
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_name: Mapped[str] = mapped_column(String(150))
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40), default="unknown")
    target_id: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("PAGDOC_ENVIRONMENT", "development") in {"staging", "production"}:
        from sqlalchemy import text
        from ops_api import EXPECTED_SCHEMA_REVISION
        from sqlalchemy.exc import SQLAlchemyError
        try:
            with engine.connect() as connection:
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                if revision != EXPECTED_SCHEMA_REVISION:
                    raise RuntimeError("Apply reviewed migrations before starting the private server")
        except SQLAlchemyError as exc:
            raise RuntimeError("Apply reviewed migrations before starting the private server") from exc
    else:
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title="PAGDOC Private API Prototype", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error_without_secret_inputs(request: Request, error: RequestValidationError):
    # Validation responses must not echo password/token input values.
    return JSONResponse(status_code=422, content={'detail':[{'loc':item['loc'],'msg':item['msg'],'type':item['type']} for item in error.errors()]})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def db_session():
    with SessionLocal() as db:
        yield db


Db = Annotated[Session, Depends(db_session)]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client_hash(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return _sha256(f"{SECRET}|{host}")


def _fernet() -> Fernet:
    if not ENCRYPTION_KEY:
        raise HTTPException(503, "MFA encryption key is not configured")
    try:
        return Fernet(ENCRYPTION_KEY.encode("utf-8"))
    except (ValueError, TypeError):
        raise HTTPException(503, "MFA encryption key is invalid")


def _encrypt_mfa(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def _decrypt_mfa(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise HTTPException(503, "MFA secret cannot be decrypted")


def _active_session(request: Request, db: Session) -> UserSession | None:
    token = request.cookies.get("pagdoc_session")
    if not token:
        return None
    now = datetime.now(timezone.utc)
    return db.scalar(select(UserSession).where(UserSession.token_hash == _sha256(token), UserSession.revoked_at.is_(None), UserSession.expires_at > now))


def current_user(request: Request, db: Db) -> User:
    session = _active_session(request, db)
    if session is None:
        raise HTTPException(401, "Authentication required")
    user = db.get(User, session.user_id)
    if not user or not user.active or user.tenant_id != session.tenant_id:
        raise HTTPException(401, "Invalid or expired session")
    if user.password_change_required:
        if user.temporary_password_expires_at and user.temporary_password_expires_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc):raise HTTPException(401,'La clave temporal venció. Solicita una nueva o recupera tu acceso por correo.')
        if request.url.path not in {'/me','/auth/password/change','/auth/logout','/auth/logout-all'}:raise HTTPException(403,{'code':'password_change_required','message':'Debes cambiar tu clave temporal antes de entrar a la plataforma.'})
    from access_policy import planner_path_allowed
    if user.role == "planner" and not planner_path_allowed(request.url.path):
        raise HTTPException(403, "This account is limited to personnel planning")
    request.state.pagdoc_session_id = session.id
    return user


Auth = Annotated[User, Depends(current_user)]


def csrf_guard(request: Request, db: Db):
    cookie = request.cookies.get("pagdoc_csrf")
    header = request.headers.get("X-PAGDOC-CSRF")
    session = _active_session(request, db)
    if not cookie or not header or session is None or not secrets.compare_digest(cookie, header) or not secrets.compare_digest(session.csrf_hash, _sha256(header)):
        raise HTTPException(403, "CSRF validation failed")


Csrf = Annotated[None, Depends(csrf_guard)]


def editor(user: Auth, _: Csrf) -> User:
    if user.role not in ("admin", "editor"):
        raise HTTPException(403, "Insufficient permissions")
    return user


Editor = Annotated[User, Depends(editor)]


def admin(user: Auth) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    return user


Admin = Annotated[User, Depends(admin)]


def admin_write(user: Admin, _: Csrf) -> User:
    return user


AdminWrite = Annotated[User, Depends(admin_write)]


def add_audit(db: Session, user: User, action: str, target_type: str, target_id: int):
    db.add(Audit(tenant_id=user.tenant_id, user_id=user.id, action=action, target_type=target_type, target_id=target_id))


def revoke_user_sessions(db: Session, user_id: int):
    now = datetime.now(timezone.utc)
    sessions = db.scalars(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))).all()
    for session in sessions:
        session.revoked_at = now


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    otp: str | None = Field(default=None, min_length=6, max_length=8)


class MfaCodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class PasswordResetIn(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str | None = Field(default=None, max_length=60)


class WorkerIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    identifier: str | None = Field(default=None, max_length=80)
    job_title: str | None = Field(default=None, max_length=120)


class VehicleIn(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    plate: str | None = Field(default=None, max_length=30)
    vehicle_type: str | None = Field(default=None, max_length=80)


class ActiveIn(BaseModel):
    active: bool


class DocumentIn(BaseModel):
    project_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=2, max_length=200)
    subject_type: str = Field(pattern="^(worker|vehicle|company|project)$")
    subject_name: str = Field(min_length=2, max_length=150)
    expires_on: date | None = None


class UserIn(BaseModel):
    temporary_password: bool = False
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=1024)
    role: str = Field(pattern="^(admin|editor|viewer|planner|reviewer)$")


@app.get("/health")
def health():
    return {"status": "ok", "environment": "prototype"}


@app.post("/auth/login")
def login(data: Credentials, response: Response, request: Request, db: Db):
    email = data.email.strip().lower()
    ip_hash = _client_hash(request)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOGIN_WINDOW_MINUTES)
    failures = db.scalar(select(func.count(LoginAttempt.id)).where(LoginAttempt.email == email, LoginAttempt.ip_hash == ip_hash, LoginAttempt.occurred_at >= cutoff)) or 0
    if failures >= LOGIN_MAX_FAILURES:
        raise HTTPException(429, "Too many login attempts. Try again later")

    user = db.scalar(select(User).where(User.email == email, User.active == 1))
    valid_password = bool(user and hasher.verify(data.password, user.password_hash))
    valid_mfa = True
    if valid_password and user and user.mfa_enabled:
        if not data.otp:
            raise HTTPException(401, "MFA required")
        if not user.mfa_secret_enc:
            raise HTTPException(503, "MFA configuration is invalid")
        valid_mfa = pyotp.TOTP(_decrypt_mfa(user.mfa_secret_enc)).verify(data.otp, valid_window=1)

    if not valid_password or not valid_mfa:
        db.add(LoginAttempt(email=email, ip_hash=ip_hash))
        db.commit()
        raise HTTPException(401, "Invalid credentials")

    if user.password_change_required and user.temporary_password_expires_at and user.temporary_password_expires_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc):raise HTTPException(401,'La clave temporal venció. Solicita una nueva o recupera tu acceso por correo.')
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == email, LoginAttempt.ip_hash == ip_hash))
    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    db_session_row = UserSession(tenant_id=user.tenant_id, user_id=user.id, token_hash=_sha256(session_token), csrf_hash=_sha256(csrf_token), expires_at=datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS))
    db.add(db_session_row)
    db.flush()
    add_audit(db, user, "auth.login", "session", db_session_row.id)
    db.commit()

    response.set_cookie("pagdoc_session", session_token, httponly=True, secure=True, samesite="strict", max_age=SESSION_SECONDS, path="/")
    response.set_cookie("pagdoc_csrf", csrf_token, httponly=False, secure=True, samesite="strict", max_age=SESSION_SECONDS, path="/")
    return {"authenticated": True, "role": user.role, "csrf_token": csrf_token,"password_change_required":bool(user.password_change_required)}


@app.post("/auth/logout")
def logout(response: Response, request: Request, user: Auth, _: Csrf, db: Db):
    session = _active_session(request, db)
    if session is not None:
        session.revoked_at = datetime.now(timezone.utc)
        add_audit(db, user, "auth.logout", "session", session.id)
        db.commit()
    response.delete_cookie("pagdoc_session", path="/", secure=True, httponly=True, samesite="strict")
    response.delete_cookie("pagdoc_csrf", path="/", secure=True, samesite="strict")
    return {"authenticated": False}


@app.post("/auth/logout-all")
def logout_all(response: Response, user: Auth, _: Csrf, db: Db):
    revoke_user_sessions(db, user.id)
    add_audit(db, user, "auth.logout_all", "user", user.id)
    db.commit()
    response.delete_cookie("pagdoc_session", path="/", secure=True, httponly=True, samesite="strict")
    response.delete_cookie("pagdoc_csrf", path="/", secure=True, samesite="strict")
    return {"authenticated": False, "all_sessions_revoked": True}


@app.post("/auth/mfa/setup")
def mfa_setup(user: Auth, _: Csrf, db: Db):
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")
    secret = pyotp.random_base32()
    user.mfa_secret_enc = _encrypt_mfa(secret)
    add_audit(db, user, "mfa.setup", "user", user.id)
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="PAGDOC")
    return {"secret": secret, "otpauth_uri": uri, "enabled": False}


@app.post("/auth/mfa/confirm")
def mfa_confirm(data: MfaCodeIn, user: Auth, _: Csrf, db: Db):
    if not user.mfa_secret_enc:
        raise HTTPException(400, "MFA setup has not been started")
    secret = _decrypt_mfa(user.mfa_secret_enc)
    if not pyotp.TOTP(secret).verify(data.code, valid_window=1):
        raise HTTPException(400, "Invalid MFA code")
    user.mfa_enabled = 1
    add_audit(db, user, "mfa.enable", "user", user.id)
    db.commit()
    return {"enabled": True}


@app.get("/me")
def me(user: Auth):
    return {"id": user.id, "tenant_id": user.tenant_id, "email": user.email, "role": user.role, "mfa_enabled": bool(user.mfa_enabled), "password_change_required":bool(user.password_change_required),"capabilities": __import__("access_policy").capabilities(user.role)}


@app.get("/users")
def users(user: Admin, db: Db):
    return [{"id": u.id, "email": u.email, "role": u.role, "active": bool(u.active), "mfa_enabled": bool(u.mfa_enabled),"password_change_required":bool(u.password_change_required),"temporary_password_expires_at":u.temporary_password_expires_at} for u in db.scalars(select(User).where(User.tenant_id == user.tenant_id).order_by(User.id)).all()]


@app.post("/users", status_code=201)
def add_user(data: UserIn, user: AdminWrite, db: Db):
    email = data.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    if not valid_password(data.password):raise HTTPException(422,MESSAGE)
    created = User(tenant_id=user.tenant_id, email=email, password_hash=hasher.hash(data.password), role=data.role, active=1,password_change_required=int(data.temporary_password),temporary_password_expires_at=datetime.now(timezone.utc)+timedelta(hours=24) if data.temporary_password else None)
    db.add(created)
    db.flush()
    add_audit(db, user, "user.create", "user", created.id)
    db.commit()
    return {"id": created.id, "email": created.email, "role": created.role}


@app.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, data: PasswordResetIn, user: AdminWrite, db: Db):
    target = db.scalar(select(User).where(User.id == user_id, User.tenant_id == user.tenant_id).with_for_update())
    if target is None:
        raise HTTPException(404, "User not found")
    if not valid_password(data.password):raise HTTPException(422,MESSAGE)
    target.password_hash = hasher.hash(data.password)
    target.password_change_required=1
    target.temporary_password_expires_at=datetime.now(timezone.utc)+timedelta(hours=24)
    revoke_user_sessions(db, target.id)
    add_audit(db, user, "user.password_reset", "user", target.id)
    db.commit()
    return {"id": target.id, "password_reset": True, "sessions_revoked": True}


@app.post("/users/{user_id}/reset-mfa")
def reset_user_mfa(user_id: int, user: AdminWrite, db: Db):
    target = db.scalar(select(User).where(User.id == user_id, User.tenant_id == user.tenant_id))
    if target is None:
        raise HTTPException(404, "User not found")
    target.mfa_secret_enc = None
    target.mfa_enabled = 0
    revoke_user_sessions(db, target.id)
    add_audit(db, user, "user.mfa_reset", "user", target.id)
    db.commit()
    return {"id": target.id, "mfa_enabled": False, "sessions_revoked": True}


@app.patch("/users/{user_id}/active")
def set_user_active(user_id: int, data: ActiveIn, user: AdminWrite, db: Db):
    target = db.scalar(select(User).where(User.id == user_id, User.tenant_id == user.tenant_id))
    if target is None:
        raise HTTPException(404, "User not found")
    if target.id == user.id and not data.active:
        raise HTTPException(400, "Cannot deactivate your own account")
    target.active = 1 if data.active else 0
    if not data.active:
        revoke_user_sessions(db, target.id)
    add_audit(db, user, "user.activate" if data.active else "user.deactivate", "user", target.id)
    db.commit()
    return {"id": target.id, "active": bool(target.active)}


@app.get("/projects")
def projects(user: Auth, db: Db):
    return [{"id": p.id, "name": p.name, "code": p.code, "active": bool(p.active)} for p in db.scalars(select(Project).where(Project.tenant_id == user.tenant_id).order_by(Project.id)).all()]


@app.post("/projects", status_code=201)
def add_project(data: ProjectIn, user: Editor, db: Db):
    p = Project(tenant_id=user.tenant_id, name=data.name.strip(), code=data.code, active=1)
    db.add(p); db.flush(); add_audit(db, user, "project.create", "project", p.id); db.commit()
    return {"id": p.id, "name": p.name, "code": p.code, "active": True}


@app.patch("/projects/{project_id}/active")
def set_project_active(project_id: int, data: ActiveIn, user: Editor, db: Db):
    p = db.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == user.tenant_id))
    if p is None: raise HTTPException(404, "Project not found")
    p.active = 1 if data.active else 0; add_audit(db, user, "project.activate" if data.active else "project.deactivate", "project", p.id); db.commit()
    return {"id": p.id, "active": bool(p.active)}


@app.get("/workers")
def workers(user: Auth, db: Db):
    return [{"id": w.id, "full_name": w.full_name, "identifier": w.identifier, "job_title": w.job_title, "active": bool(w.active)} for w in db.scalars(select(Worker).where(Worker.tenant_id == user.tenant_id).order_by(Worker.id)).all()]


@app.post("/workers", status_code=201)
def add_worker(data: WorkerIn, user: Editor, db: Db):
    db.scalar(select(Tenant).where(Tenant.id==user.tenant_id).with_for_update())
    w = Worker(tenant_id=user.tenant_id, full_name=data.full_name.strip(), identifier=data.identifier, job_title=data.job_title, active=1)
    db.add(w); db.flush(); add_audit(db, user, "worker.create", "worker", w.id); db.commit()
    return {"id": w.id, "full_name": w.full_name, "active": True}


@app.patch("/workers/{worker_id}/active")
def set_worker_active(worker_id: int, data: ActiveIn, user: Editor, db: Db):
    w = db.scalar(select(Worker).where(Worker.id == worker_id, Worker.tenant_id == user.tenant_id))
    if w is None: raise HTTPException(404, "Worker not found")
    w.active = 1 if data.active else 0; add_audit(db, user, "worker.activate" if data.active else "worker.deactivate", "worker", w.id); db.commit()
    return {"id": w.id, "active": bool(w.active)}


@app.get("/vehicles")
def vehicles(user: Auth, db: Db):
    return [{"id": v.id, "label": v.label, "plate": v.plate, "vehicle_type": v.vehicle_type, "active": bool(v.active)} for v in db.scalars(select(Vehicle).where(Vehicle.tenant_id == user.tenant_id).order_by(Vehicle.id)).all()]


@app.post("/vehicles", status_code=201)
def add_vehicle(data: VehicleIn, user: Editor, db: Db):
    v = Vehicle(tenant_id=user.tenant_id, label=data.label.strip(), plate=data.plate.strip().upper() if data.plate else None, vehicle_type=data.vehicle_type, active=1)
    db.add(v); db.flush(); add_audit(db, user, "vehicle.create", "vehicle", v.id); db.commit()
    return {"id": v.id, "label": v.label, "plate": v.plate, "active": True}


@app.patch("/vehicles/{vehicle_id}/active")
def set_vehicle_active(vehicle_id: int, data: ActiveIn, user: Editor, db: Db):
    v = db.scalar(select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.tenant_id == user.tenant_id))
    if v is None: raise HTTPException(404, "Vehicle not found")
    v.active = 1 if data.active else 0; add_audit(db, user, "vehicle.activate" if data.active else "vehicle.deactivate", "vehicle", v.id); db.commit()
    return {"id": v.id, "active": bool(v.active)}


def doc_state(d: Document):
    if d.expires_on is None: return "no_date"
    remaining = (d.expires_on - date.today()).days
    return "expired" if remaining < 0 else "expiring" if remaining <= 30 else "valid"


@app.get("/documents")
def documents(user: Auth, db: Db):
    return [{"id": d.id, "project_id": d.project_id, "title": d.title, "subject_type": d.subject_type, "subject_name": d.subject_name, "expires_on": d.expires_on, "status": doc_state(d)} for d in db.scalars(select(Document).where(Document.tenant_id == user.tenant_id).order_by(Document.id)).all()]


@app.post("/documents", status_code=201)
def add_document(data: DocumentIn, user: Editor, db: Db):
    if data.project_id is not None:
        project = db.scalar(select(Project).where(Project.id == data.project_id, Project.tenant_id == user.tenant_id))
        if project is None: raise HTTPException(404, "Project not found")
    d = Document(tenant_id=user.tenant_id, **data.model_dump()); db.add(d); db.flush(); add_audit(db, user, "document.create", "document", d.id); db.commit()
    return {"id": d.id, "status": doc_state(d)}


@app.get("/dashboard")
def dashboard(user: Auth, db: Db):
    docs = db.scalars(select(Document).where(Document.tenant_id == user.tenant_id)).all()
    return {"documents": {"total": len(docs), **{status: sum(doc_state(d) == status for d in docs) for status in ("valid", "expiring", "expired", "no_date")}}, "entities": {"projects": len(db.scalars(select(Project).where(Project.tenant_id == user.tenant_id, Project.active == 1)).all()), "workers": len(db.scalars(select(Worker).where(Worker.tenant_id == user.tenant_id, Worker.active == 1)).all()), "vehicles": len(db.scalars(select(Vehicle).where(Vehicle.tenant_id == user.tenant_id, Vehicle.active == 1)).all())}}


@app.get("/audit")
def audit(user: Admin, db: Db):
    return [{"action": a.action, "target_type": a.target_type, "target_id": a.target_id, "user_id": a.user_id, "at": a.at} for a in db.scalars(select(Audit).where(Audit.tenant_id == user.tenant_id).order_by(Audit.id.desc()).limit(100)).all()]
