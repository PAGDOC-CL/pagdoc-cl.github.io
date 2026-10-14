"""Regression tests for non-destructive PAGDOC retention policy planning."""
import os
from datetime import date, timedelta

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app as core
import retention_api as retention


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "retention.sqlite3"),
        connect_args={"check_same_thread": False},
    )
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core, "SessionLocal", factory)
    today = date.today()
    with factory() as db:
        db.add_all([core.Tenant(id=1, name="Tenant Uno"), core.Tenant(id=2, name="Tenant Dos")])
        db.add_all([
            core.User(id=1, tenant_id=1, email="admin1@example.invalid", password_hash=core.hasher.hash("testpass-one"), role="admin"),
            core.User(id=2, tenant_id=2, email="admin2@example.invalid", password_hash=core.hasher.hash("testpass-two"), role="admin"),
            core.User(id=3, tenant_id=1, email="viewer1@example.invalid", password_hash=core.hasher.hash("testpass-viewer"), role="viewer"),
        ])
        db.commit()
        db.add_all([
            core.Document(id=100, tenant_id=1, title="Antiguo trabajador", subject_type="worker", subject_name="Persona Ficticia A", expires_on=today - timedelta(days=400)),
            core.Document(id=101, tenant_id=1, title="Trabajador con hold", subject_type="worker", subject_name="Persona Ficticia B", expires_on=today - timedelta(days=500)),
            core.Document(id=102, tenant_id=1, title="Vehículo reciente", subject_type="vehicle", subject_name="Camioneta Ficticia", expires_on=today - timedelta(days=10)),
            core.Document(id=103, tenant_id=1, title="Sin fecha", subject_type="company", subject_name="Empresa Ficticia", expires_on=None),
            core.Document(id=200, tenant_id=2, title="Otro tenant", subject_type="worker", subject_name="Persona Otro Tenant", expires_on=today - timedelta(days=800)),
        ])
        db.commit()
    with TestClient(core.app, base_url="https://testserver") as test_client:
        yield test_client, factory


def auth(client, email="admin1@example.invalid", password="testpass-one"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["X-PAGDOC-CSRF"] = response.json()["csrf_token"]
    return response


def put_rule(client, subject_type, days, active=True):
    response = client.put(
        f"/retention/rules/{subject_type}",
        json={"days_after_expiry": days, "active": active},
    )
    assert response.status_code == 200
    return response.json()


def test_preview_is_non_destructive_and_tenant_scoped(client):
    test_client, factory = client
    auth(test_client)
    put_rule(test_client, "worker", 365)
    put_rule(test_client, "vehicle", 30)

    preview = test_client.get("/retention/preview")
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["mode"] == "preview_only"
    assert payload["destructive_actions_enabled"] is False
    assert {row["document_id"] for row in payload["items"]} == {100, 101}
    assert payload["page"]["total"] == 2

    with factory() as db:
        # Preview must never remove the underlying records.
        assert db.get(core.Document, 100) is not None
        assert db.get(core.Document, 101) is not None
        assert db.get(core.Document, 200) is not None
        event = db.scalar(select(core.Audit).where(core.Audit.tenant_id == 1, core.Audit.action == "retention.preview"))
        assert event is not None


def test_legal_hold_excludes_candidate_and_release_restores_preview(client):
    test_client, _ = client
    auth(test_client)
    put_rule(test_client, "worker", 365)

    hold = test_client.put(
        "/retention/documents/101/legal-hold",
        json={"enabled": True, "note": "Conservación ficticia por revisión"},
    )
    assert hold.status_code == 200
    assert hold.json()["legal_hold"] is True

    preview = test_client.get("/retention/preview").json()
    assert {row["document_id"] for row in preview["items"]} == {100}

    status = test_client.get("/retention/documents/101")
    assert status.status_code == 200
    assert status.json()["legal_hold"] is True
    assert status.json()["hold_note"] == "Conservación ficticia por revisión"

    release = test_client.put(
        "/retention/documents/101/legal-hold",
        json={"enabled": False, "note": "ignored"},
    )
    assert release.status_code == 200
    assert release.json()["legal_hold"] is False
    assert release.json()["hold_note"] is None
    preview = test_client.get("/retention/preview").json()
    assert {row["document_id"] for row in preview["items"]} == {100, 101}


def test_inactive_rule_produces_no_candidates(client):
    test_client, _ = client
    auth(test_client)
    put_rule(test_client, "worker", 0, active=False)
    payload = test_client.get("/retention/preview").json()
    assert payload["items"] == []
    assert payload["page"]["total"] == 0


def test_rule_window_and_pagination(client):
    test_client, _ = client
    auth(test_client)
    put_rule(test_client, "worker", 365)
    first = test_client.get("/retention/preview?limit=1&offset=0").json()
    second = test_client.get("/retention/preview?limit=1&offset=1").json()
    assert first["page"] == {"limit": 1, "offset": 0, "total": 2}
    assert second["page"] == {"limit": 1, "offset": 1, "total": 2}
    assert first["items"][0]["document_id"] != second["items"][0]["document_id"]


def test_cross_tenant_legal_hold_is_hidden(client):
    test_client, _ = client
    auth(test_client)
    response = test_client.put(
        "/retention/documents/200/legal-hold",
        json={"enabled": True, "note": "should not cross tenant"},
    )
    assert response.status_code == 404
    assert test_client.get("/retention/documents/200").status_code == 404


def test_retention_management_is_admin_only_and_csrf_protected(client):
    test_client, _ = client
    auth(test_client, "viewer1@example.invalid", "testpass-viewer")
    assert test_client.get("/retention/rules").status_code == 403
    assert test_client.get("/retention/preview").status_code == 403

    # Re-authenticate as admin then deliberately remove the CSRF header.
    test_client.headers.pop("X-PAGDOC-CSRF", None)
    auth(test_client)
    test_client.headers.pop("X-PAGDOC-CSRF", None)
    response = test_client.put(
        "/retention/rules/worker",
        json={"days_after_expiry": 365, "active": True},
    )
    assert response.status_code == 403


def test_invalid_rule_inputs_are_rejected(client):
    test_client, _ = client
    auth(test_client)
    assert test_client.put("/retention/rules/person", json={"days_after_expiry": 10, "active": True}).status_code == 422
    assert test_client.put("/retention/rules/worker", json={"days_after_expiry": 5000, "active": True}).status_code == 422
