"""Regression tests for PAGDOC tamper-evident audit seals."""
import os

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app as core
import audit_integrity as integrity


@pytest.fixture()
def client(tmp_path, monkeypatch):
    integrity.install()
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "audit.sqlite3"),
        connect_args={"check_same_thread": False},
    )
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core, "SessionLocal", factory)
    with factory() as db:
        db.add_all([core.Tenant(id=1, name="Tenant Uno"), core.Tenant(id=2, name="Tenant Dos")])
        db.add_all([
            core.User(id=1, tenant_id=1, email="admin1@example.invalid", password_hash=core.hasher.hash("testpass-one"), role="admin"),
            core.User(id=2, tenant_id=2, email="admin2@example.invalid", password_hash=core.hasher.hash("testpass-two"), role="admin"),
            core.User(id=3, tenant_id=1, email="viewer@example.invalid", password_hash=core.hasher.hash("testpass-viewer"), role="viewer"),
        ])
        # Legacy event created before the signed range; verification reports it but
        # does not pretend it was retroactively sealed.
        db.add(core.Audit(tenant_id=1, user_id=1, action="legacy.event", target_type="tenant", target_id=1))
        db.commit()
    with TestClient(core.app, base_url="https://testserver") as test_client:
        yield test_client, factory


def auth(client, email="admin1@example.invalid", password="testpass-one"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["X-PAGDOC-CSRF"] = response.json()["csrf_token"]
    return response


def test_signed_chain_verifies_and_reports_legacy_events(client):
    test_client, factory = client
    auth(test_client)
    created = test_client.post("/projects", json={"name": "Proyecto firmado"})
    assert created.status_code == 201

    check = test_client.get("/audit-integrity")
    assert check.status_code == 200
    payload = check.json()
    assert payload["valid"] is True
    assert payload["reason"] == "ok"
    assert payload["legacy_events"] == 1
    assert payload["sealed_events"] >= 3  # login, project create, verification

    with factory() as db:
        seals = db.scalars(select(integrity.AuditSeal).where(integrity.AuditSeal.tenant_id == 1)).all()
        assert len(seals) == payload["sealed_events"]
        assert all(len(row.event_hash) == 64 for row in seals)


def test_tampered_audit_row_breaks_verification(client):
    test_client, factory = client
    auth(test_client)
    assert test_client.post("/projects", json={"name": "Proyecto uno"}).status_code == 201

    with factory() as db:
        signed = db.scalar(
            select(core.Audit)
            .where(core.Audit.tenant_id == 1, core.Audit.action == "project.create")
        )
        signed.action = "project.tampered"
        db.commit()

    check = test_client.get("/audit-integrity")
    assert check.status_code == 200
    assert check.json()["valid"] is False
    assert check.json()["reason"] == "event_hash_mismatch"


def test_unsealed_insertion_inside_signed_range_is_detected(client):
    test_client, factory = client
    auth(test_client)
    assert test_client.get("/audit-integrity").json()["valid"] is True

    with factory() as db:
        db.add(core.Audit(tenant_id=1, user_id=1, action="injected.event", target_type="tenant", target_id=1))
        db.commit()

    check = test_client.get("/audit-integrity")
    assert check.status_code == 200
    assert check.json()["valid"] is False
    assert check.json()["reason"] == "audit_seal_gap"


def test_integrity_endpoint_is_admin_only(client):
    test_client, _ = client
    auth(test_client, "viewer@example.invalid", "testpass-viewer")
    assert test_client.get("/audit-integrity").status_code == 403


def test_tenant_chains_are_independent(client):
    test_client, factory = client
    auth(test_client)
    assert test_client.get("/audit-integrity").json()["valid"] is True

    other = TestClient(core.app, base_url="https://testserver")
    try:
        auth(other, "admin2@example.invalid", "testpass-two")
        result = other.get("/audit-integrity")
        assert result.status_code == 200
        assert result.json()["valid"] is True
        assert result.json()["legacy_events"] == 0
    finally:
        other.close()

    with factory() as db:
        tenant1 = db.scalars(select(integrity.AuditSeal).where(integrity.AuditSeal.tenant_id == 1)).all()
        tenant2 = db.scalars(select(integrity.AuditSeal).where(integrity.AuditSeal.tenant_id == 2)).all()
        assert tenant1 and tenant2
        assert {row.event_hash for row in tenant1}.isdisjoint({row.event_hash for row in tenant2})
