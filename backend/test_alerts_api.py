"""Regression tests for PAGDOC internal alert preferences and acknowledgements."""
import os
from datetime import date, timedelta

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as core
import requirements_api as reqs
import alerts_api  # noqa: F401


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "alerts.sqlite3"), connect_args={"check_same_thread": False})
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core, "SessionLocal", factory)
    with factory() as db:
        db.add_all([core.Tenant(id=1, name="Tenant Uno"), core.Tenant(id=2, name="Tenant Dos")])
        db.add_all([
            core.User(id=1, tenant_id=1, email="admin1@example.invalid", password_hash=core.hasher.hash("testpass-one"), role="admin"),
            core.User(id=2, tenant_id=2, email="admin2@example.invalid", password_hash=core.hasher.hash("testpass-two"), role="admin"),
            core.User(id=3, tenant_id=1, email="viewer1@example.invalid", password_hash=core.hasher.hash("testpass-viewer"), role="viewer"),
        ])
        db.add_all([
            core.Document(id=100, tenant_id=1, title="Por vencer", subject_type="worker", subject_name="Persona Ficticia", expires_on=date.today() + timedelta(days=5)),
            core.Document(id=101, tenant_id=1, title="Vencido", subject_type="worker", subject_name="Persona Ficticia", expires_on=date.today() - timedelta(days=2)),
            core.Document(id=200, tenant_id=2, title="Otro tenant", subject_type="worker", subject_name="Otra Persona", expires_on=date.today() - timedelta(days=1)),
        ])
        db.add_all([
            reqs.Requirement(id=10, tenant_id=1, name="Examen ficticio", subject_type="worker", warning_days=30, required=1, active=1),
            reqs.Requirement(id=20, tenant_id=2, name="Examen otro tenant", subject_type="worker", warning_days=30, required=1, active=1),
        ])
        db.add_all([
            reqs.DocumentPolicy(id=1000, tenant_id=1, document_id=100, requirement_id=10),
            reqs.DocumentPolicy(id=1001, tenant_id=1, document_id=101, requirement_id=10),
            reqs.DocumentPolicy(id=2000, tenant_id=2, document_id=200, requirement_id=20),
        ])
        db.commit()
    with TestClient(core.app, base_url="https://testserver") as test_client:
        yield test_client


def auth(client, email="admin1@example.invalid", password="testpass-one"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["X-PAGDOC-CSRF"] = response.json()["csrf_token"]
    return response


def test_default_preferences_and_inbox_are_tenant_scoped(client):
    auth(client)
    pref = client.get("/alert-preferences")
    assert pref.status_code == 200
    assert pref.json() == {"enabled": True, "include_expiring": True, "include_expired": True}

    inbox = client.get("/alerts/inbox")
    assert inbox.status_code == 200
    rows = inbox.json()
    assert {row["document_id"] for row in rows} == {100, 101}
    assert all(row["requirement_id"] == 10 for row in rows)
    assert {row["status"] for row in rows} == {"expiring", "expired"}


def test_preferences_can_opt_out_or_filter_states(client):
    auth(client)
    only_expired = client.put(
        "/alert-preferences",
        json={"enabled": True, "include_expiring": False, "include_expired": True},
    )
    assert only_expired.status_code == 200
    rows = client.get("/alerts/inbox").json()
    assert [row["document_id"] for row in rows] == [101]

    disabled = client.put(
        "/alert-preferences",
        json={"enabled": False, "include_expiring": True, "include_expired": True},
    )
    assert disabled.status_code == 200
    assert client.get("/alerts/inbox").json() == []


def test_acknowledgement_is_user_scoped_and_reversible(client):
    auth(client)
    ack = client.post("/alerts/10/100/acknowledge")
    assert ack.status_code == 200
    assert ack.json()["acknowledged"] is True

    admin_rows = client.get("/alerts/inbox").json()
    admin_item = next(row for row in admin_rows if row["document_id"] == 100)
    assert admin_item["acknowledged"] is True

    viewer = TestClient(core.app, base_url="https://testserver")
    try:
        auth(viewer, "viewer1@example.invalid", "testpass-viewer")
        viewer_item = next(row for row in viewer.get("/alerts/inbox").json() if row["document_id"] == 100)
        assert viewer_item["acknowledged"] is False
    finally:
        viewer.close()

    cleared = client.delete("/alerts/10/100/acknowledgement")
    assert cleared.status_code == 200
    assert cleared.json()["acknowledged"] is False
    item = next(row for row in client.get("/alerts/inbox").json() if row["document_id"] == 100)
    assert item["acknowledged"] is False


def test_cross_tenant_alert_cannot_be_acknowledged(client):
    auth(client)
    response = client.post("/alerts/20/200/acknowledge")
    assert response.status_code == 404


def test_preference_write_requires_csrf(client):
    auth(client)
    del client.headers["X-PAGDOC-CSRF"]
    response = client.put(
        "/alert-preferences",
        json={"enabled": False, "include_expiring": True, "include_expired": True},
    )
    assert response.status_code == 403
