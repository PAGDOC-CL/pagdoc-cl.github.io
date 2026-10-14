"""Tenant-scoped retention policy groundwork for PAGDOC.

This module is deliberately non-destructive: it can configure retention windows,
place/release legal holds and preview documents that would be eligible for a
future purge. It never deletes document metadata or binary objects.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

import app as core


VALID_SUBJECT_TYPES = {"worker", "vehicle", "company", "project"}


class RetentionRule(core.Base):
    __tablename__ = "retention_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject_type", name="uq_retention_rule_subject_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)
    days_after_expiry: Mapped[int] = mapped_column(Integer, default=365)
    active: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class DocumentRetentionState(core.Base):
    __tablename__ = "document_retention_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", name="uq_document_retention_state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    legal_hold: Mapped[int] = mapped_column(Integer, default=0)
    hold_note: Mapped[str | None] = mapped_column(String(250), nullable=True)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class RetentionRuleIn(BaseModel):
    days_after_expiry: int = Field(ge=0, le=3650)
    active: bool = True


class LegalHoldIn(BaseModel):
    enabled: bool
    note: str | None = Field(default=None, max_length=250)


def _document(db: core.Session, tenant_id: int, document_id: int) -> core.Document:
    row = db.scalar(
        select(core.Document).where(
            core.Document.id == document_id,
            core.Document.tenant_id == tenant_id,
        )
    )
    if row is None:
        raise HTTPException(404, "Document not found")
    return row


def _rule_payload(row: RetentionRule) -> dict:
    return {
        "subject_type": row.subject_type,
        "days_after_expiry": row.days_after_expiry,
        "active": bool(row.active),
        "updated_at": row.updated_at,
    }


@core.app.get("/retention/rules")
def list_retention_rules(user: core.Admin, db: core.Db):
    rows = db.scalars(
        select(RetentionRule)
        .where(RetentionRule.tenant_id == user.tenant_id)
        .order_by(RetentionRule.subject_type)
    ).all()
    return [_rule_payload(row) for row in rows]


@core.app.put("/retention/rules/{subject_type}")
def upsert_retention_rule(
    subject_type: str,
    data: RetentionRuleIn,
    user: core.AdminWrite,
    db: core.Db,
):
    if subject_type not in VALID_SUBJECT_TYPES:
        raise HTTPException(422, "Invalid subject type")
    row = db.scalar(
        select(RetentionRule).where(
            RetentionRule.tenant_id == user.tenant_id,
            RetentionRule.subject_type == subject_type,
        )
    )
    if row is None:
        row = RetentionRule(
            tenant_id=user.tenant_id,
            subject_type=subject_type,
            updated_by_user_id=user.id,
        )
        db.add(row)
    row.days_after_expiry = data.days_after_expiry
    row.active = 1 if data.active else 0
    row.updated_by_user_id = user.id
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    core.add_audit(db, user, "retention.rule_update", "retention_rule", row.id)
    db.commit()
    return _rule_payload(row)


@core.app.get("/retention/documents/{document_id}")
def get_document_retention(document_id: int, user: core.Admin, db: core.Db):
    doc = _document(db, user.tenant_id, document_id)
    state = db.scalar(
        select(DocumentRetentionState).where(
            DocumentRetentionState.tenant_id == user.tenant_id,
            DocumentRetentionState.document_id == document_id,
        )
    )
    rule = db.scalar(
        select(RetentionRule).where(
            RetentionRule.tenant_id == user.tenant_id,
            RetentionRule.subject_type == doc.subject_type,
        )
    )
    return {
        "document_id": doc.id,
        "subject_type": doc.subject_type,
        "expires_on": doc.expires_on,
        "legal_hold": bool(state and state.legal_hold),
        "hold_note": state.hold_note if state else None,
        "rule": _rule_payload(rule) if rule else None,
    }


@core.app.put("/retention/documents/{document_id}/legal-hold")
def set_legal_hold(
    document_id: int,
    data: LegalHoldIn,
    user: core.AdminWrite,
    db: core.Db,
):
    _document(db, user.tenant_id, document_id)
    state = db.scalar(
        select(DocumentRetentionState).where(
            DocumentRetentionState.tenant_id == user.tenant_id,
            DocumentRetentionState.document_id == document_id,
        )
    )
    if state is None:
        state = DocumentRetentionState(
            tenant_id=user.tenant_id,
            document_id=document_id,
            updated_by_user_id=user.id,
        )
        db.add(state)
    state.legal_hold = 1 if data.enabled else 0
    state.hold_note = data.note.strip() if data.note and data.enabled else None
    state.updated_by_user_id = user.id
    state.updated_at = datetime.now(timezone.utc)
    db.flush()
    core.add_audit(
        db,
        user,
        "retention.legal_hold_set" if data.enabled else "retention.legal_hold_release",
        "document",
        document_id,
    )
    db.commit()
    return {
        "document_id": document_id,
        "legal_hold": bool(state.legal_hold),
        "hold_note": state.hold_note,
        "updated_at": state.updated_at,
    }


@core.app.get("/retention/preview")
def retention_preview(
    user: core.Admin,
    db: core.Db,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    today = date.today()
    rules = {
        row.subject_type: row
        for row in db.scalars(
            select(RetentionRule).where(
                RetentionRule.tenant_id == user.tenant_id,
                RetentionRule.active == 1,
            )
        ).all()
    }
    holds = {
        row.document_id
        for row in db.scalars(
            select(DocumentRetentionState).where(
                DocumentRetentionState.tenant_id == user.tenant_id,
                DocumentRetentionState.legal_hold == 1,
            )
        ).all()
    }
    documents = db.scalars(
        select(core.Document)
        .where(
            core.Document.tenant_id == user.tenant_id,
            core.Document.expires_on.is_not(None),
        )
        .order_by(core.Document.expires_on, core.Document.id)
    ).all()

    candidates: list[dict] = []
    for doc in documents:
        rule = rules.get(doc.subject_type)
        if rule is None or doc.id in holds or doc.expires_on is None:
            continue
        eligible_on = doc.expires_on + timedelta(days=rule.days_after_expiry)
        if eligible_on > today:
            continue
        candidates.append(
            {
                "document_id": doc.id,
                "title": doc.title,
                "subject_type": doc.subject_type,
                "subject_name": doc.subject_name,
                "expires_on": doc.expires_on,
                "eligible_on": eligible_on,
                "days_after_expiry": rule.days_after_expiry,
                "legal_hold": False,
            }
        )

    total = len(candidates)
    page = candidates[offset : offset + limit]
    core.add_audit(db, user, "retention.preview", "tenant", user.tenant_id)
    db.commit()
    return {
        "mode": "preview_only",
        "destructive_actions_enabled": False,
        "items": page,
        "page": {"limit": limit, "offset": offset, "total": total},
    }
