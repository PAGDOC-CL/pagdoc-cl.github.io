"""Database-backed encrypted document file version registry for PAGDOC.

The private HTTP adapter combines this service with explicit company/vehicle
bindings and upload version guards. It maintains tenant-scoped metadata,
document-level serialization and audit events after a clean scan.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

import app as core
from file_gateway import GatewayError, SecureDocumentGateway
from storage import StorageError


class DocumentFileVersion(core.Base):
    __tablename__ = "document_file_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", "version", name="uq_document_file_version"),
        UniqueConstraint("tenant_id", "object_key", name="uq_document_file_object_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(32))
    original_name: Mapped[str] = mapped_column(String(160))
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    scan_engine: Mapped[str] = mapped_column(String(120))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def _locked_document(db: core.Session, tenant_id: int, document_id: int) -> core.Document:
    doc = db.scalar(
        select(core.Document)
        .where(core.Document.id == document_id, core.Document.tenant_id == tenant_id)
        .with_for_update()
    )
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


def _version_row(db: core.Session, tenant_id: int, document_id: int, version: int) -> DocumentFileVersion:
    row = db.scalar(
        select(DocumentFileVersion).where(
            DocumentFileVersion.tenant_id == tenant_id,
            DocumentFileVersion.document_id == document_id,
            DocumentFileVersion.version == version,
        )
    )
    if row is None:
        raise HTTPException(404, "Document file version not found")
    return row


def store_new_file_version(
    db: core.Session,
    user: core.User,
    document_id: int,
    gateway: SecureDocumentGateway,
    original_name: str,
    media_type: str,
    data: bytes,
) -> DocumentFileVersion:
    """Scan, encrypt and register a new immutable binary version.

    The encrypted object is deleted if database persistence fails so the local
    prototype does not leave an orphaned blob behind.
    """
    result = gateway.ingest(user.tenant_id, original_name, media_type, data)
    stored = result.stored
    try:
        _locked_document(db, user.tenant_id, document_id)
        latest = db.scalar(
            select(func.max(DocumentFileVersion.version)).where(
                DocumentFileVersion.tenant_id == user.tenant_id,
                DocumentFileVersion.document_id == document_id,
            )
        )
        row = DocumentFileVersion(
            tenant_id=user.tenant_id,
            document_id=document_id,
            version=int(latest or 0) + 1,
            object_key=stored.object_key,
            original_name=stored.original_name,
            media_type=stored.media_type,
            size_bytes=stored.size,
            sha256=stored.sha256,
            scan_engine=result.scan.engine[:120],
            created_by_user_id=user.id,
        )
        db.add(row)
        db.flush()
        core.add_audit(db, user, "document.file_version_create", "document", document_id)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        gateway.store.delete(user.tenant_id, stored.object_key)
        raise


def read_file_version(
    db: core.Session,
    user: core.User,
    document_id: int,
    version: int,
    gateway: SecureDocumentGateway,
) -> bytes:
    _locked_document(db, user.tenant_id, document_id)
    row = _version_row(db, user.tenant_id, document_id, version)
    try:
        data = gateway.store.get(user.tenant_id, row.object_key)
    except StorageError as exc:
        db.rollback()
        raise GatewayError(str(exc)) from exc

    digest = hashlib.sha256(data).hexdigest()
    if len(data) != row.size_bytes or digest != row.sha256:
        db.rollback()
        raise GatewayError("Stored object metadata integrity check failed")

    core.add_audit(db, user, "document.file_version_read", "document", document_id)
    db.commit()
    return data


def list_file_versions(db: core.Session, user: core.User, document_id: int) -> list[dict]:
    _locked_document(db, user.tenant_id, document_id)
    rows = db.scalars(
        select(DocumentFileVersion)
        .where(
            DocumentFileVersion.tenant_id == user.tenant_id,
            DocumentFileVersion.document_id == document_id,
        )
        .order_by(DocumentFileVersion.version.desc())
    ).all()
    core.add_audit(db, user, "document.file_history_read", "document", document_id)
    db.commit()
    return [
        {
            "version": row.version,
            "original_name": row.original_name,
            "media_type": row.media_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "scan_engine": row.scan_engine,
            "created_by_user_id": row.created_by_user_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]
