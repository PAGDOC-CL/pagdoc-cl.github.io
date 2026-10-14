"""Tamper-evident audit sealing for PAGDOC.

New audit events can be sealed with an HMAC chain without changing the legacy
``audit`` table. The chain detects edits, removals or unsealed insertions inside
the sealed range. Detecting deletion of the final chain tail still requires an
external anchor in a production logging service, so this module must not be
represented as immutable/WORM logging.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

import app as core


class AuditSeal(core.Base):
    __tablename__ = "audit_seals"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audit.id"), unique=True, index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)


def _canonical(audit: core.Audit, previous_hash: str | None) -> bytes:
    timestamp = audit.at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    fields = (
        str(audit.id),
        str(audit.tenant_id),
        str(audit.user_id),
        audit.action,
        audit.target_type,
        str(audit.target_id),
        timestamp.isoformat(timespec="microseconds"),
        previous_hash or "",
    )
    return "\x1f".join(fields).encode("utf-8")


def _event_hash(audit: core.Audit, previous_hash: str | None) -> str:
    return hmac.new(
        core.SECRET.encode("utf-8"),
        _canonical(audit, previous_hash),
        hashlib.sha256,
    ).hexdigest()


def signed_add_audit(
    db: core.Session,
    user: core.User,
    action: str,
    target_type: str,
    target_id: int,
):
    """Append one audit row and its chained HMAC seal in the same transaction."""
    tenant = db.scalar(
        select(core.Tenant)
        .where(core.Tenant.id == user.tenant_id)
        .with_for_update()
    )
    if tenant is None:
        raise RuntimeError("Audit tenant not found")

    previous = db.scalar(
        select(AuditSeal)
        .where(AuditSeal.tenant_id == user.tenant_id)
        .order_by(AuditSeal.audit_id.desc())
        .limit(1)
    )
    previous_hash = previous.event_hash if previous else None

    audit = core.Audit(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
    )
    db.add(audit)
    db.flush()
    seal = AuditSeal(
        tenant_id=user.tenant_id,
        audit_id=audit.id,
        previous_hash=previous_hash,
        event_hash=_event_hash(audit, previous_hash),
    )
    db.add(seal)
    db.flush()
    return audit


def install() -> None:
    """Install the signed audit writer once for all core and feature routes."""
    if getattr(core.add_audit, "_pagdoc_integrity_installed", False):
        return
    signed_add_audit._pagdoc_integrity_installed = True  # type: ignore[attr-defined]
    core.add_audit = signed_add_audit


def verify_tenant_chain(db: core.Session, tenant_id: int) -> dict:
    seals = db.scalars(
        select(AuditSeal)
        .where(AuditSeal.tenant_id == tenant_id)
        .order_by(AuditSeal.audit_id)
    ).all()
    if not seals:
        return {"valid": True, "sealed_events": 0, "legacy_events": 0, "reason": "no_sealed_events"}

    first_id = seals[0].audit_id
    legacy_count = len(
        db.scalars(
            select(core.Audit).where(
                core.Audit.tenant_id == tenant_id,
                core.Audit.id < first_id,
            )
        ).all()
    )
    audits = db.scalars(
        select(core.Audit)
        .where(core.Audit.tenant_id == tenant_id, core.Audit.id >= first_id)
        .order_by(core.Audit.id)
    ).all()

    seal_ids = [seal.audit_id for seal in seals]
    audit_ids = [audit.id for audit in audits]
    if seal_ids != audit_ids:
        return {
            "valid": False,
            "sealed_events": len(seals),
            "legacy_events": legacy_count,
            "reason": "audit_seal_gap",
        }

    previous_hash: str | None = None
    for audit, seal in zip(audits, seals, strict=True):
        if seal.previous_hash != previous_hash:
            return {
                "valid": False,
                "sealed_events": len(seals),
                "legacy_events": legacy_count,
                "reason": "chain_link_mismatch",
                "audit_id": audit.id,
            }
        expected = _event_hash(audit, previous_hash)
        if not hmac.compare_digest(expected, seal.event_hash):
            return {
                "valid": False,
                "sealed_events": len(seals),
                "legacy_events": legacy_count,
                "reason": "event_hash_mismatch",
                "audit_id": audit.id,
            }
        previous_hash = seal.event_hash

    return {
        "valid": True,
        "sealed_events": len(seals),
        "legacy_events": legacy_count,
        "reason": "ok",
    }


@core.app.get("/audit-integrity")
def audit_integrity(user: core.Admin, db: core.Db):
    # Seal the verification attempt itself before evaluating the chain.
    core.add_audit(db, user, "audit.verify", "tenant", user.tenant_id)
    result = verify_tenant_chain(db, user.tenant_id)
    db.commit()
    return result
