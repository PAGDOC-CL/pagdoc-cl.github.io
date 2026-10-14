"""Tenant-scoped document detail, revision history and access audit routes.

This module does not expose binary file upload/download. It only versions document
metadata and records sensitive document reads in the existing audit log.
"""
from datetime import date, datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

import app as core


class DocumentRevision(core.Base):
    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", "revision", name="uq_document_revision_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40), default="metadata.update")
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_name: Mapped[str] = mapped_column(String(150))
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class DocumentPatch(BaseModel):
    project_id: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    subject_type: str | None = Field(default=None, pattern="^(worker|vehicle|company|project)$")
    subject_name: str | None = Field(default=None, min_length=2, max_length=150)
    expires_on: date | None = None


def _document_for_tenant(db: core.Session, tenant_id: int, document_id: int, lock: bool = False) -> core.Document:
    query = select(core.Document).where(
        core.Document.id == document_id,
        core.Document.tenant_id == tenant_id,
    )
    if lock:
        query = query.with_for_update()
    doc = db.scalar(query)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


def _latest_revision_number(db: core.Session, tenant_id: int, document_id: int) -> int:
    value = db.scalar(
        select(func.max(DocumentRevision.revision)).where(
            DocumentRevision.tenant_id == tenant_id,
            DocumentRevision.document_id == document_id,
        )
    )
    return int(value or 0)


def _serialize_document(doc: core.Document, latest_revision: int) -> dict:
    return {
        "id": doc.id,
        "project_id": doc.project_id,
        "title": doc.title,
        "subject_type": doc.subject_type,
        "subject_name": doc.subject_name,
        "expires_on": doc.expires_on,
        "status": core.doc_state(doc),
        "revision": latest_revision,
    }


@core.app.get("/documents/{document_id}")
def document_detail(document_id: int, user: core.Auth, db: core.Db):
    doc = _document_for_tenant(db, user.tenant_id, document_id)
    revision = _latest_revision_number(db, user.tenant_id, doc.id)
    core.add_audit(db, user, "document.read", "document", doc.id)
    db.commit()
    return _serialize_document(doc, revision)


@core.app.patch("/documents/{document_id}")
def update_document(document_id: int, data: DocumentPatch, user: core.Editor, db: core.Db):
    if not data.model_fields_set:
        raise HTTPException(422, "At least one field must be supplied")

    doc = _document_for_tenant(db, user.tenant_id, document_id, True)

    if "project_id" in data.model_fields_set and data.project_id is not None:
        project = db.scalar(
            select(core.Project).where(
                core.Project.id == data.project_id,
                core.Project.tenant_id == user.tenant_id,
            )
        )
        if project is None:
            raise HTTPException(404, "Project not found")

    next_revision = _latest_revision_number(db, user.tenant_id, doc.id) + 1
    db.add(
        DocumentRevision(
            tenant_id=user.tenant_id,
            document_id=doc.id,
            revision=next_revision,
            action="metadata.update",
            project_id=doc.project_id,
            title=doc.title,
            subject_type=doc.subject_type,
            subject_name=doc.subject_name,
            expires_on=doc.expires_on,
            changed_by_user_id=user.id,
        )
    )

    if "project_id" in data.model_fields_set:
        doc.project_id = data.project_id
    if "title" in data.model_fields_set:
        if data.title is None:
            raise HTTPException(422, "Title cannot be null")
        doc.title = data.title.strip()
    if "subject_type" in data.model_fields_set:
        if data.subject_type is None:
            raise HTTPException(422, "Subject type cannot be null")
        doc.subject_type = data.subject_type
    if "subject_name" in data.model_fields_set:
        if data.subject_name is None:
            raise HTTPException(422, "Subject name cannot be null")
        doc.subject_name = data.subject_name.strip()
    if "expires_on" in data.model_fields_set:
        doc.expires_on = data.expires_on

    core.add_audit(db, user, "document.update", "document", doc.id)
    db.commit()
    return _serialize_document(doc, next_revision)


@core.app.get("/documents/{document_id}/history")
def document_history(document_id: int, user: core.Auth, db: core.Db):
    doc = _document_for_tenant(db, user.tenant_id, document_id)
    rows = db.scalars(
        select(DocumentRevision)
        .where(
            DocumentRevision.tenant_id == user.tenant_id,
            DocumentRevision.document_id == doc.id,
        )
        .order_by(DocumentRevision.revision.desc())
    ).all()
    core.add_audit(db, user, "document.history_read", "document", doc.id)
    db.commit()
    return [
        {
            "revision": row.revision,
            "action": row.action,
            "project_id": row.project_id,
            "title": row.title,
            "subject_type": row.subject_type,
            "subject_name": row.subject_name,
            "expires_on": row.expires_on,
            "changed_by_user_id": row.changed_by_user_id,
            "changed_at": row.changed_at,
        }
        for row in rows
    ]
