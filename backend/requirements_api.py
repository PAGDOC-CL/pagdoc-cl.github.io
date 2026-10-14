"""Tenant-scoped requirements and internal alert API for PAGDOC.

Imported by server.py after the core app is initialized. No email or external
notification is sent; /alerts only returns internal events to authenticated users.
"""
from datetime import date

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

import app as core
from requirements_engine import DocumentFact, RequirementPolicy, evaluate


class Requirement(core.Base):
    __tablename__ = "requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    subject_type: Mapped[str] = mapped_column(String(30))
    warning_days: Mapped[int] = mapped_column(Integer, default=30)
    validity_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[int] = mapped_column(Integer, default=1)


class DocumentPolicy(core.Base):
    __tablename__ = "document_policies"
    __table_args__ = (UniqueConstraint("document_id", name="uq_document_policies_document"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class RequirementIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    subject_type: str = Field(pattern="^(worker|vehicle|company|project)$")
    warning_days: int = Field(default=30, ge=0, le=3650)
    validity_days: int | None = Field(default=None, ge=1, le=36500)
    required: bool = True


class ActiveIn(BaseModel):
    active: bool


class PolicyLinkIn(BaseModel):
    requirement_id: int = Field(gt=0)
    issued_on: date | None = None


def _policy(req: Requirement) -> RequirementPolicy:
    return RequirementPolicy(
        name=req.name,
        subject_type=req.subject_type,
        warning_days=req.warning_days,
        validity_days=req.validity_days,
        required=bool(req.required),
    )


@core.app.get("/requirements")
def list_requirements(user: core.Auth, db: core.Db):
    rows = db.scalars(
        select(Requirement)
        .where(Requirement.tenant_id == user.tenant_id)
        .order_by(Requirement.id)
    ).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "subject_type": r.subject_type,
            "warning_days": r.warning_days,
            "validity_days": r.validity_days,
            "required": bool(r.required),
            "active": bool(r.active),
        }
        for r in rows
    ]


@core.app.post("/requirements", status_code=201)
def create_requirement(data: RequirementIn, user: core.Editor, db: core.Db):
    req = Requirement(
        tenant_id=user.tenant_id,
        name=data.name.strip(),
        subject_type=data.subject_type,
        warning_days=data.warning_days,
        validity_days=data.validity_days,
        required=1 if data.required else 0,
        active=1,
    )
    db.add(req)
    db.flush()
    core.add_audit(db, user, "requirement.create", "requirement", req.id)
    db.commit()
    return {"id": req.id, "name": req.name, "active": True}


@core.app.patch("/requirements/{requirement_id}/active")
def set_requirement_active(requirement_id: int, data: ActiveIn, user: core.Editor, db: core.Db):
    req = db.scalar(
        select(Requirement).where(
            Requirement.id == requirement_id,
            Requirement.tenant_id == user.tenant_id,
        )
    )
    if req is None:
        raise HTTPException(404, "Requirement not found")
    req.active = 1 if data.active else 0
    core.add_audit(
        db,
        user,
        "requirement.activate" if data.active else "requirement.deactivate",
        "requirement",
        req.id,
    )
    db.commit()
    return {"id": req.id, "active": bool(req.active)}


@core.app.post("/documents/{document_id}/policy")
def link_document_policy(document_id: int, data: PolicyLinkIn, user: core.Editor, db: core.Db):
    doc = db.scalar(
        select(core.Document).where(
            core.Document.id == document_id,
            core.Document.tenant_id == user.tenant_id,
        ).with_for_update()
    )
    if doc is None:
        raise HTTPException(404, "Document not found")
    req = db.scalar(
        select(Requirement).where(
            Requirement.id == data.requirement_id,
            Requirement.tenant_id == user.tenant_id,
            Requirement.active == 1,
        )
    )
    if req is None:
        raise HTTPException(404, "Requirement not found")
    if req.subject_type != doc.subject_type:
        raise HTTPException(422, "Requirement subject type does not match document")

    link = db.scalar(
        select(DocumentPolicy).where(
            DocumentPolicy.document_id == doc.id,
            DocumentPolicy.tenant_id == user.tenant_id,
        )
    )
    if link is None:
        link = DocumentPolicy(
            tenant_id=user.tenant_id,
            document_id=doc.id,
            requirement_id=req.id,
            issued_on=data.issued_on,
        )
        db.add(link)
    else:
        link.requirement_id = req.id
        link.issued_on = data.issued_on

    result = evaluate(
        _policy(req),
        DocumentFact(
            document_id=doc.id,
            subject_type=doc.subject_type,
            subject_name=doc.subject_name,
            issued_on=data.issued_on,
            expires_on=doc.expires_on,
        ),
    )
    if doc.expires_on is None and result.expires_on is not None:
        doc.expires_on = result.expires_on

    db.flush()
    core.add_audit(db, user, "document.policy_link", "document", doc.id)
    db.commit()
    return {
        "document_id": doc.id,
        "requirement_id": req.id,
        "expires_on": doc.expires_on,
        "status": result.state,
        "warning_days": req.warning_days,
    }


@core.app.get("/alerts")
def internal_alerts(user: core.Auth, db: core.Db):
    rows = db.execute(
        select(DocumentPolicy, Requirement, core.Document)
        .join(Requirement, Requirement.id == DocumentPolicy.requirement_id)
        .join(core.Document, core.Document.id == DocumentPolicy.document_id)
        .where(
            DocumentPolicy.tenant_id == user.tenant_id,
            Requirement.tenant_id == user.tenant_id,
            core.Document.tenant_id == user.tenant_id,
            Requirement.active == 1,
        )
    ).all()
    alerts = []
    for link, req, doc in rows:
        result = evaluate(
            _policy(req),
            DocumentFact(
                document_id=doc.id,
                subject_type=doc.subject_type,
                subject_name=doc.subject_name,
                issued_on=link.issued_on,
                expires_on=doc.expires_on,
            ),
        )
        if result.state not in {"expiring", "expired"}:
            continue
        alerts.append(
            {
                "document_id": doc.id,
                "requirement_id": req.id,
                "requirement": req.name,
                "subject_name": doc.subject_name,
                "status": result.state,
                "expires_on": result.expires_on,
                "days_remaining": result.days_remaining,
            }
        )
    return sorted(alerts, key=lambda x: (x["expires_on"], x["document_id"]))
