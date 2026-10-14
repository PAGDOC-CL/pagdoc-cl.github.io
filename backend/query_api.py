"""Tenant-scoped document search for PAGDOC private clients."""
from datetime import date, timedelta

from fastapi import Query
from sqlalchemy import func, or_, select

import app as core


VALID_STATES = {"valid", "expiring", "expired", "no_date"}
VALID_SUBJECT_TYPES = {"worker", "vehicle", "company", "project"}


def _apply_document_filters(statement, *, tenant_id: int, q: str | None, status: str | None, subject_type: str | None, project_id: int | None):
    statement = statement.where(core.Document.tenant_id == tenant_id)
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                core.Document.title.ilike(term),
                core.Document.subject_name.ilike(term),
            )
        )
    if subject_type:
        statement = statement.where(core.Document.subject_type == subject_type)
    if project_id is not None:
        statement = statement.where(core.Document.project_id == project_id)
    if status:
        today = date.today()
        warning_end = today + timedelta(days=30)
        if status == "expired":
            statement = statement.where(core.Document.expires_on < today)
        elif status == "expiring":
            statement = statement.where(core.Document.expires_on >= today, core.Document.expires_on <= warning_end)
        elif status == "valid":
            statement = statement.where(core.Document.expires_on > warning_end)
        elif status == "no_date":
            statement = statement.where(core.Document.expires_on.is_(None))
    return statement


@core.app.get("/search/documents")
def search_documents(
    user: core.Auth,
    db: core.Db,
    q: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None),
    subject_type: str | None = Query(default=None),
    project_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    if status is not None and status not in VALID_STATES:
        from fastapi import HTTPException
        raise HTTPException(422, "Invalid document status")
    if subject_type is not None and subject_type not in VALID_SUBJECT_TYPES:
        from fastapi import HTTPException
        raise HTTPException(422, "Invalid subject type")

    base = _apply_document_filters(
        select(core.Document),
        tenant_id=user.tenant_id,
        q=q,
        status=status,
        subject_type=subject_type,
        project_id=project_id,
    )
    count_stmt = _apply_document_filters(
        select(func.count(core.Document.id)),
        tenant_id=user.tenant_id,
        q=q,
        status=status,
        subject_type=subject_type,
        project_id=project_id,
    )
    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(base.order_by(core.Document.id).offset(offset).limit(limit)).all()
    core.add_audit(db, user, "document.search", "tenant", user.tenant_id)
    db.commit()
    return {
        "items": [
            {
                "id": row.id,
                "project_id": row.project_id,
                "title": row.title,
                "subject_type": row.subject_type,
                "subject_name": row.subject_name,
                "expires_on": row.expires_on,
                "status": core.doc_state(row),
            }
            for row in rows
        ],
        "page": {"limit": limit, "offset": offset, "total": total},
    }
