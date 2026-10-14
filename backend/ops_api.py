"""Minimal operational probes for the PAGDOC private API.

The readiness endpoint intentionally exposes no database URL, secrets, tenant data
or migration details. Staging/production are considered ready only when the
expected Alembic revision is applied.
"""
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app as core
from runtime_config import load_runtime_config


EXPECTED_SCHEMA_REVISION = "0009_operations"


def readiness_ok(db: core.Session, environment: str) -> bool:
    try:
        db.execute(text("SELECT 1")).scalar_one()
        if environment in {"staging", "production"}:
            revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != EXPECTED_SCHEMA_REVISION:
                return False
        return True
    except (SQLAlchemyError, RuntimeError, ValueError):
        db.rollback()
        return False


@core.app.get("/ready", include_in_schema=False)
def ready(db: core.Db):
    environment = load_runtime_config().environment
    if not readiness_ok(db, environment):
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}
