"""PAGDOC private API prototype.

Security-first development backend. It is intentionally NOT deployed and must not
be used with real personal/company documents until the production security gates
in ROADMAP.md are completed.
"""
import os
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

DB_URL = os.getenv("PAGDOC_DATABASE_URL", "sqlite:///./pagdoc_dev.sqlite3")
SECRET = os.getenv("PAGDOC_SECRET_KEY", "")
if not SECRET or len(SECRET) < 32:
    raise RuntimeError("Set PAGDOC_SECRET_KEY to a random value of at least 32 characters")

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine)
signer = URLSafeTimedSerializer(SECRET, salt="pagdoc-session-v1")
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
    title: Mapped[str] = mapped_column(String(200))
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
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


app = FastAPI(title="PAGDOC Private API Prototype", docs_url=None, redoc_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)


def db_session():
    with SessionLocal() as db:
        yield db


Db = Annotated[Session, Depends(db_session)]


def current_user(request: Request, db: Db) -> User:
    token = request.cookies.get("pagdoc_session")
    if not token:
        raise HTTPException(401, "Authentication required")
    try:
        payload = signer.loads(token, max_age=3600)
        user = db.get(User, int(payload["uid"]))
        if not user or not user.active or user.tenant_id != int(payload["tid"]):
            raise ValueError("Invalid user")
        return user
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        raise HTTPException(401, "Invalid or expired session")


Auth = Annotated[User, Depends(current_user)]


def editor(user: Auth) -> User:
    if user.role not in ("admin", "editor"):
        raise HTTPException(403, "Insufficient permissions")
    return user


Editor = Annotated[User, Depends(editor)]


def admin(user: Auth) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    return user


Admin = Annotated[User, Depends(admin)]


def add_audit(db: Session, user: User, action: str, target_type: str, target_id: int):
    db.add(
        Audit(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
        )
    )


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


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
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=1024)
    role: str = Field(pattern="^(admin|editor|viewer)$")


@app.get("/health")
def health():
    return {"status": "ok", "environment": "prototype"}


@app.post("/auth/login")
def login(data: Credentials, response: Response, db: Db):
    user = db.scalar(
        select(User).where(
            User.email == data.email.strip().lower(),
            User.active == 1,
        )
    )
    if not user or not hasher.verify(data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    response.set_cookie(
        "pagdoc_session",
        signer.dumps({"uid": user.id, "tid": user.tenant_id}),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=3600,
        path="/",
    )
    return {"authenticated": True, "role": user.role}


@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("pagdoc_session", path="/", secure=True, httponly=True, samesite="strict")
    return {"authenticated": False}


@app.get("/me")
def me(user: Auth):
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "role": user.role,
    }


@app.get("/users")
def users(user: Admin, db: Db):
    return [
        {"id": u.id, "email": u.email, "role": u.role, "active": bool(u.active)}
        for u in db.scalars(
            select(User).where(User.tenant_id == user.tenant_id).order_by(User.id)
        ).all()
    ]


@app.post("/users", status_code=201)
def add_user(data: UserIn, user: Admin, db: Db):
    email = data.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    created = User(
        tenant_id=user.tenant_id,
        email=email,
        password_hash=hasher.hash(data.password),
        role=data.role,
        active=1,
    )
    db.add(created)
    db.flush()
    add_audit(db, user, "user.create", "user", created.id)
    db.commit()
    return {"id": created.id, "email": created.email, "role": created.role}


@app.patch("/users/{user_id}/active")
def set_user_active(user_id: int, data: ActiveIn, user: Admin, db: Db):
    target = db.scalar(
        select(User).where(User.id == user_id, User.tenant_id == user.tenant_id)
    )
    if target is None:
        raise HTTPException(404, "User not found")
    if target.id == user.id and not data.active:
        raise HTTPException(400, "Cannot deactivate your own account")
    target.active = 1 if data.active else 0
    add_audit(db, user, "user.activate" if data.active else "user.deactivate", "user", target.id)
    db.commit()
    return {"id": target.id, "active": bool(target.active)}


@app.get("/projects")
def projects(user: Auth, db: Db):
    return [
        {"id": p.id, "name": p.name, "code": p.code, "active": bool(p.active)}
        for p in db.scalars(
            select(Project).where(Project.tenant_id == user.tenant_id).order_by(Project.id)
        ).all()
    ]


@app.post("/projects", status_code=201)
def add_project(data: ProjectIn, user: Editor, db: Db):
    p = Project(tenant_id=user.tenant_id, name=data.name.strip(), code=data.code, active=1)
    db.add(p)
    db.flush()
    add_audit(db, user, "project.create", "project", p.id)
    db.commit()
    return {"id": p.id, "name": p.name, "code": p.code, "active": True}


@app.patch("/projects/{project_id}/active")
def set_project_active(project_id: int, data: ActiveIn, user: Editor, db: Db):
    p = db.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == user.tenant_id)
    )
    if p is None:
        raise HTTPException(404, "Project not found")
    p.active = 1 if data.active else 0
    add_audit(db, user, "project.activate" if data.active else "project.deactivate", "project", p.id)
    db.commit()
    return {"id": p.id, "active": bool(p.active)}


@app.get("/workers")
def workers(user: Auth, db: Db):
    return [
        {
            "id": w.id,
            "full_name": w.full_name,
            "identifier": w.identifier,
            "job_title": w.job_title,
            "active": bool(w.active),
        }
        for w in db.scalars(
            select(Worker).where(Worker.tenant_id == user.tenant_id).order_by(Worker.id)
        ).all()
    ]


@app.post("/workers", status_code=201)
def add_worker(data: WorkerIn, user: Editor, db: Db):
    w = Worker(
        tenant_id=user.tenant_id,
        full_name=data.full_name.strip(),
        identifier=data.identifier,
        job_title=data.job_title,
        active=1,
    )
    db.add(w)
    db.flush()
    add_audit(db, user, "worker.create", "worker", w.id)
    db.commit()
    return {"id": w.id, "full_name": w.full_name, "active": True}


@app.patch("/workers/{worker_id}/active")
def set_worker_active(worker_id: int, data: ActiveIn, user: Editor, db: Db):
    w = db.scalar(
        select(Worker).where(Worker.id == worker_id, Worker.tenant_id == user.tenant_id)
    )
    if w is None:
        raise HTTPException(404, "Worker not found")
    w.active = 1 if data.active else 0
    add_audit(db, user, "worker.activate" if data.active else "worker.deactivate", "worker", w.id)
    db.commit()
    return {"id": w.id, "active": bool(w.active)}


@app.get("/vehicles")
def vehicles(user: Auth, db: Db):
    return [
        {
            "id": v.id,
            "label": v.label,
            "plate": v.plate,
            "vehicle_type": v.vehicle_type,
            "active": bool(v.active),
        }
        for v in db.scalars(
            select(Vehicle).where(Vehicle.tenant_id == user.tenant_id).order_by(Vehicle.id)
        ).all()
    ]


@app.post("/vehicles", status_code=201)
def add_vehicle(data: VehicleIn, user: Editor, db: Db):
    v = Vehicle(
        tenant_id=user.tenant_id,
        label=data.label.strip(),
        plate=data.plate.strip().upper() if data.plate else None,
        vehicle_type=data.vehicle_type,
        active=1,
    )
    db.add(v)
    db.flush()
    add_audit(db, user, "vehicle.create", "vehicle", v.id)
    db.commit()
    return {"id": v.id, "label": v.label, "plate": v.plate, "active": True}


@app.patch("/vehicles/{vehicle_id}/active")
def set_vehicle_active(vehicle_id: int, data: ActiveIn, user: Editor, db: Db):
    v = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.tenant_id == user.tenant_id)
    )
    if v is None:
        raise HTTPException(404, "Vehicle not found")
    v.active = 1 if data.active else 0
    add_audit(db, user, "vehicle.activate" if data.active else "vehicle.deactivate", "vehicle", v.id)
    db.commit()
    return {"id": v.id, "active": bool(v.active)}


def doc_state(d: Document):
    if d.expires_on is None:
        return "no_date"
    remaining = (d.expires_on - date.today()).days
    return "expired" if remaining < 0 else "expiring" if remaining <= 30 else "valid"


@app.get("/documents")
def documents(user: Auth, db: Db):
    return [
        {
            "id": d.id,
            "project_id": d.project_id,
            "title": d.title,
            "subject_type": d.subject_type,
            "subject_name": d.subject_name,
            "expires_on": d.expires_on,
            "status": doc_state(d),
        }
        for d in db.scalars(
            select(Document).where(Document.tenant_id == user.tenant_id).order_by(Document.id)
        ).all()
    ]


@app.post("/documents", status_code=201)
def add_document(data: DocumentIn, user: Editor, db: Db):
    if data.project_id is not None:
        project = db.scalar(
            select(Project).where(
                Project.id == data.project_id,
                Project.tenant_id == user.tenant_id,
            )
        )
        if project is None:
            raise HTTPException(404, "Project not found")
    d = Document(tenant_id=user.tenant_id, **data.model_dump())
    db.add(d)
    db.flush()
    add_audit(db, user, "document.create", "document", d.id)
    db.commit()
    return {"id": d.id, "status": doc_state(d)}


@app.get("/dashboard")
def dashboard(user: Auth, db: Db):
    docs = db.scalars(select(Document).where(Document.tenant_id == user.tenant_id)).all()
    return {
        "documents": {
            "total": len(docs),
            **{
                status: sum(doc_state(d) == status for d in docs)
                for status in ("valid", "expiring", "expired", "no_date")
            },
        },
        "entities": {
            "projects": len(
                db.scalars(select(Project).where(Project.tenant_id == user.tenant_id, Project.active == 1)).all()
            ),
            "workers": len(
                db.scalars(select(Worker).where(Worker.tenant_id == user.tenant_id, Worker.active == 1)).all()
            ),
            "vehicles": len(
                db.scalars(select(Vehicle).where(Vehicle.tenant_id == user.tenant_id, Vehicle.active == 1)).all()
            ),
        },
    }


@app.get("/audit")
def audit(user: Admin, db: Db):
    return [
        {
            "action": a.action,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "user_id": a.user_id,
            "at": a.at,
        }
        for a in db.scalars(
            select(Audit)
            .where(Audit.tenant_id == user.tenant_id)
            .order_by(Audit.id.desc())
            .limit(100)
        ).all()
    ]
