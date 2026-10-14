"""Opt-in internal alert inbox for PAGDOC.

No email, SMS, push or third-party message is sent by this module. Preferences and
acknowledgements are scoped to the authenticated user and tenant.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column

import app as core
import requirements_api as reqs
from requirements_engine import DocumentFact, evaluate


class AlertPreference(core.Base):
    __tablename__ = "alert_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_alert_preference_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    include_expiring: Mapped[int] = mapped_column(Integer, default=1)
    include_expired: Mapped[int] = mapped_column(Integer, default=1)


class AlertAcknowledgement(core.Base):
    __tablename__ = "alert_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "document_id",
            "requirement_id",
            name="uq_alert_ack_user_document_requirement",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class AlertPreferenceIn(BaseModel):
    enabled: bool = True
    include_expiring: bool = True
    include_expired: bool = True


def _preference(db: core.Session, user: core.User) -> AlertPreference | None:
    return db.scalar(
        select(AlertPreference).where(
            AlertPreference.tenant_id == user.tenant_id,
            AlertPreference.user_id == user.id,
        )
    )


def _preference_payload(pref: AlertPreference | None) -> dict:
    if pref is None:
        return {"enabled": True, "include_expiring": True, "include_expired": True}
    return {
        "enabled": bool(pref.enabled),
        "include_expiring": bool(pref.include_expiring),
        "include_expired": bool(pref.include_expired),
    }


def _linked_alert(db: core.Session, tenant_id: int, document_id: int, requirement_id: int):
    row = db.execute(
        select(reqs.DocumentPolicy, reqs.Requirement, core.Document)
        .join(reqs.Requirement, reqs.Requirement.id == reqs.DocumentPolicy.requirement_id)
        .join(core.Document, core.Document.id == reqs.DocumentPolicy.document_id)
        .where(
            reqs.DocumentPolicy.tenant_id == tenant_id,
            reqs.DocumentPolicy.document_id == document_id,
            reqs.DocumentPolicy.requirement_id == requirement_id,
            reqs.Requirement.tenant_id == tenant_id,
            reqs.Requirement.active == 1,
            core.Document.tenant_id == tenant_id,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Alert source not found")
    link, requirement, document = row
    result = evaluate(
        reqs._policy(requirement),
        DocumentFact(
            document_id=document.id,
            subject_type=document.subject_type,
            subject_name=document.subject_name,
            issued_on=link.issued_on,
            expires_on=document.expires_on,
        ),
    )
    if result.state not in {"expiring", "expired"}:
        raise HTTPException(409, "Document is not currently alertable")
    return link, requirement, document, result


@core.app.get("/alert-preferences")
def get_alert_preferences(user: core.Auth, db: core.Db):
    return _preference_payload(_preference(db, user))


@core.app.put("/alert-preferences")
def set_alert_preferences(data: AlertPreferenceIn, user: core.Auth, _: core.Csrf, db: core.Db):
    pref = _preference(db, user)
    if pref is None:
        pref = AlertPreference(tenant_id=user.tenant_id, user_id=user.id)
        db.add(pref)
    pref.enabled = 1 if data.enabled else 0
    pref.include_expiring = 1 if data.include_expiring else 0
    pref.include_expired = 1 if data.include_expired else 0
    db.flush()
    core.add_audit(db, user, "alerts.preference_update", "user", user.id)
    db.commit()
    return _preference_payload(pref)


@core.app.get("/alerts/inbox")
def alert_inbox(user: core.Auth, db: core.Db):
    pref = _preference_payload(_preference(db, user))
    if not pref["enabled"]:
        return []

    acknowledged = {
        (row.document_id, row.requirement_id): row.acknowledged_at
        for row in db.scalars(
            select(AlertAcknowledgement).where(
                AlertAcknowledgement.tenant_id == user.tenant_id,
                AlertAcknowledgement.user_id == user.id,
            )
        ).all()
    }
    rows = db.execute(
        select(reqs.DocumentPolicy, reqs.Requirement, core.Document)
        .join(reqs.Requirement, reqs.Requirement.id == reqs.DocumentPolicy.requirement_id)
        .join(core.Document, core.Document.id == reqs.DocumentPolicy.document_id)
        .where(
            reqs.DocumentPolicy.tenant_id == user.tenant_id,
            reqs.Requirement.tenant_id == user.tenant_id,
            core.Document.tenant_id == user.tenant_id,
            reqs.Requirement.active == 1,
        )
    ).all()

    items = []
    for link, requirement, document in rows:
        result = evaluate(
            reqs._policy(requirement),
            DocumentFact(
                document_id=document.id,
                subject_type=document.subject_type,
                subject_name=document.subject_name,
                issued_on=link.issued_on,
                expires_on=document.expires_on,
            ),
        )
        if result.state == "expiring" and not pref["include_expiring"]:
            continue
        if result.state == "expired" and not pref["include_expired"]:
            continue
        if result.state not in {"expiring", "expired"}:
            continue
        ack_at = acknowledged.get((document.id, requirement.id))
        items.append(
            {
                "document_id": document.id,
                "requirement_id": requirement.id,
                "requirement": requirement.name,
                "subject_name": document.subject_name,
                "status": result.state,
                "expires_on": result.expires_on,
                "days_remaining": result.days_remaining,
                "acknowledged": ack_at is not None,
                "acknowledged_at": ack_at,
            }
        )
    return sorted(items, key=lambda x: (x["acknowledged"], x["expires_on"], x["document_id"]))


@core.app.post("/alerts/{requirement_id}/{document_id}/acknowledge")
def acknowledge_alert(requirement_id: int, document_id: int, user: core.Auth, _: core.Csrf, db: core.Db):
    _linked_alert(db, user.tenant_id, document_id, requirement_id)
    existing = db.scalar(
        select(AlertAcknowledgement).where(
            AlertAcknowledgement.tenant_id == user.tenant_id,
            AlertAcknowledgement.user_id == user.id,
            AlertAcknowledgement.document_id == document_id,
            AlertAcknowledgement.requirement_id == requirement_id,
        )
    )
    if existing is None:
        existing = AlertAcknowledgement(
            tenant_id=user.tenant_id,
            user_id=user.id,
            document_id=document_id,
            requirement_id=requirement_id,
        )
        db.add(existing)
    else:
        existing.acknowledged_at = datetime.now(timezone.utc)
    db.flush()
    core.add_audit(db, user, "alerts.acknowledge", "document", document_id)
    db.commit()
    return {
        "document_id": document_id,
        "requirement_id": requirement_id,
        "acknowledged": True,
        "acknowledged_at": existing.acknowledged_at,
    }


@core.app.delete("/alerts/{requirement_id}/{document_id}/acknowledgement")
def clear_alert_acknowledgement(requirement_id: int, document_id: int, user: core.Auth, _: core.Csrf, db: core.Db):
    _linked_alert(db, user.tenant_id, document_id, requirement_id)
    db.execute(
        delete(AlertAcknowledgement).where(
            AlertAcknowledgement.tenant_id == user.tenant_id,
            AlertAcknowledgement.user_id == user.id,
            AlertAcknowledgement.document_id == document_id,
            AlertAcknowledgement.requirement_id == requirement_id,
        )
    )
    core.add_audit(db, user, "alerts.unacknowledge", "document", document_id)
    db.commit()
    return {"document_id": document_id, "requirement_id": requirement_id, "acknowledged": False}
