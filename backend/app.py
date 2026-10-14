"""PAGDOC private API prototype. Not production ready. Never use real company data."""
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
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
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
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    active: Mapped[int] = mapped_column(Integer, default=1)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
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
    target_id: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

app = FastAPI(title="PAGDOC Private API Prototype", docs_url=None, redoc_url=None)
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

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)

class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)

class DocumentIn(BaseModel):
    project_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=200)
    subject_type: str = Field(pattern="^(worker|vehicle|company|project)$")
    subject_name: str = Field(min_length=2, max_length=150)
    expires_on: date | None = None

@app.get("/health")
def health():
    return {"status": "ok", "environment": "prototype"}

@app.post("/auth/login")
def login(data: Credentials, response: Response, db: Db):
    # Do not disclose whether email exists.
    user = db.scalar(select(User).where(User.email == data.email.strip().lower(), User.active == 1))
    if not user or not hasher.verify(data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    response.set_cookie("pagdoc_session", signer.dumps({"uid": user.id, "tid": user.tenant_id}),
                        httponly=True, secure=True, samesite="strict", max_age=3600, path="/")
    return {"authenticated": True, "role": user.role}

@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("pagdoc_session", path="/")
    return {"authenticated": False}

@app.get("/me")
def me(user: Auth):
    return {"id": user.id, "tenant_id": user.tenant_id, "role": user.role}

@app.get("/projects")
def projects(user: Auth, db: Db):
    return [{"id": p.id, "name": p.name} for p in db.scalars(
        select(Project).where(Project.tenant_id == user.tenant_id).order_by(Project.id)).all()]

@app.post("/projects", status_code=201)
def add_project(data: ProjectIn, user: Editor, db: Db):
    p = Project(tenant_id=user.tenant_id, name=data.name)
    db.add(p)
    db.flush()
    db.add(Audit(tenant_id=user.tenant_id, user_id=user.id, action="project.create", target_id=p.id))
    db.commit()
    return {"id": p.id, "name": p.name}

def doc_state(d: Document):
    if d.expires_on is None:
        return "no_date"
    remaining = (d.expires_on - date.today()).days
    return "expired" if remaining < 0 else "expiring" if remaining <= 30 else "valid"

@app.get("/documents")
def documents(user: Auth, db: Db):
    return [{"id": d.id, "project_id": d.project_id, "title": d.title,
             "subject_type": d.subject_type, "subject_name": d.subject_name,
             "expires_on": d.expires_on, "status": doc_state(d)}
            for d in db.scalars(select(Document).where(Document.tenant_id == user.tenant_id).order_by(Document.id)).all()]

@app.post("/documents", status_code=201)
def add_document(data: DocumentIn, user: Editor, db: Db):
    project = db.scalar(select(Project).where(Project.id == data.project_id, Project.tenant_id == user.tenant_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    d = Document(tenant_id=user.tenant_id, **data.model_dump())
    db.add(d)
    db.flush()
    db.add(Audit(tenant_id=user.tenant_id, user_id=user.id, action="document.create", target_id=d.id))
    db.commit()
    return {"id": d.id, "status": doc_state(d)}

@app.get("/dashboard")
def dashboard(user: Auth, db: Db):
    docs = db.scalars(select(Document).where(Document.tenant_id == user.tenant_id)).all()
    return {"total": len(docs), **{status: sum(doc_state(d) == status for d in docs)
                                   for status in ("valid", "expiring", "expired", "no_date")}}

@app.get("/audit")
def audit(user: Auth, db: Db):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    return [{"action": a.action, "target_id": a.target_id, "user_id": a.user_id, "at": a.at}
            for a in db.scalars(select(Audit).where(Audit.tenant_id == user.tenant_id)
                                .order_by(Audit.id.desc()).limit(100)).all()]
