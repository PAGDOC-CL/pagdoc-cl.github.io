import os
from datetime import date, timedelta

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as core
import requirements_api as reqapi
import server


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "req.sqlite3"), connect_args={"check_same_thread": False})
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core, "SessionLocal", factory)
    with factory() as db:
        db.add_all([core.Tenant(id=1, name="Ficticia Uno"), core.Tenant(id=2, name="Ficticia Dos")])
        db.add_all([
            core.User(id=1, tenant_id=1, email="admin1@example.invalid", password_hash=core.hasher.hash("test-password-1"), role="admin"),
            core.User(id=2, tenant_id=2, email="admin2@example.invalid", password_hash=core.hasher.hash("test-password-2"), role="admin"),
            core.User(id=3, tenant_id=1, email="viewer1@example.invalid", password_hash=core.hasher.hash("test-password-3"), role="viewer"),
        ])
        db.add_all([
            core.Project(id=10, tenant_id=1, name="Proyecto Uno"),
            core.Project(id=20, tenant_id=2, name="Proyecto Dos"),
            core.Document(id=100, tenant_id=1, project_id=10, title="Examen Demo", subject_type="worker", subject_name="Persona Uno"),
            core.Document(id=200, tenant_id=2, project_id=20, title="Examen Demo", subject_type="worker", subject_name="Persona Dos"),
            core.Document(id=101, tenant_id=1, project_id=10, title="Seguro Demo", subject_type="vehicle", subject_name="Vehículo Uno"),
        ])
        db.commit()
    with TestClient(server.app, base_url="https://testserver") as c:
        yield c


def login(client, email="admin1@example.invalid", password="test-password-1"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["X-PAGDOC-CSRF"] = response.json()["csrf_token"]


def create_requirement(client, **overrides):
    payload = {
        "name": "Examen ocupacional",
        "subject_type": "worker",
        "warning_days": 30,
        "validity_days": 365,
        "required": True,
    }
    payload.update(overrides)
    return client.post("/requirements", json=payload)


def test_requirements_require_authentication(client):
    assert client.get("/requirements").status_code == 401
    assert client.get("/alerts").status_code == 401


def test_admin_can_create_and_list_requirement(client):
    login(client)
    created = create_requirement(client)
    assert created.status_code == 201
    rows = client.get("/requirements").json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Examen ocupacional"
    assert rows[0]["warning_days"] == 30


def test_viewer_can_read_but_cannot_create_requirement(client):
    login(client, "viewer1@example.invalid", "test-password-3")
    assert client.get("/requirements").status_code == 200
    assert create_requirement(client).status_code == 403


def test_requirements_are_tenant_isolated(client):
    login(client)
    first = create_requirement(client)
    assert first.status_code == 201
    login(client, "admin2@example.invalid", "test-password-2")
    assert client.get("/requirements").json() == []


def test_cross_tenant_requirement_cannot_be_linked(client):
    login(client, "admin2@example.invalid", "test-password-2")
    req = create_requirement(client)
    requirement_id = req.json()["id"]
    login(client)
    response = client.post("/documents/100/policy", json={"requirement_id": requirement_id, "issued_on": "2026-01-01"})
    assert response.status_code == 404


def test_cross_tenant_document_cannot_be_linked(client):
    login(client)
    req = create_requirement(client)
    response = client.post("/documents/200/policy", json={"requirement_id": req.json()["id"]})
    assert response.status_code == 404


def test_subject_type_mismatch_is_rejected(client):
    login(client)
    req = create_requirement(client)
    response = client.post("/documents/101/policy", json={"requirement_id": req.json()["id"]})
    assert response.status_code == 422


def test_policy_derives_expiry_from_issue_date(client):
    login(client)
    req = create_requirement(client, validity_days=90, warning_days=15)
    response = client.post("/documents/100/policy", json={"requirement_id": req.json()["id"], "issued_on": "2026-10-01"})
    assert response.status_code == 200
    assert response.json()["expires_on"] == "2026-12-30"
    docs = client.get("/documents").json()
    assert next(d for d in docs if d["id"] == 100)["expires_on"] == "2026-12-30"


def test_alerts_use_requirement_warning_window(client):
    login(client)
    req = create_requirement(client, validity_days=None, warning_days=20)
    requirement_id = req.json()["id"]
    with core.SessionLocal() as db:
        doc = db.get(core.Document, 100)
        doc.expires_on = date.today() + timedelta(days=15)
        db.commit()
    assert client.post("/documents/100/policy", json={"requirement_id": requirement_id}).status_code == 200
    alerts = client.get("/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["document_id"] == 100
    assert alerts[0]["status"] == "expiring"


def test_expired_alert_is_returned(client):
    login(client)
    req = create_requirement(client, validity_days=None, warning_days=7)
    with core.SessionLocal() as db:
        doc = db.get(core.Document, 100)
        doc.expires_on = date.today() - timedelta(days=1)
        db.commit()
    client.post("/documents/100/policy", json={"requirement_id": req.json()["id"]})
    alert = client.get("/alerts").json()[0]
    assert alert["status"] == "expired"
    assert alert["days_remaining"] == -1


def test_deactivated_requirement_is_excluded_from_alerts(client):
    login(client)
    req = create_requirement(client, validity_days=None, warning_days=30)
    rid = req.json()["id"]
    with core.SessionLocal() as db:
        doc = db.get(core.Document, 100)
        doc.expires_on = date.today() + timedelta(days=5)
        db.commit()
    client.post("/documents/100/policy", json={"requirement_id": rid})
    assert len(client.get("/alerts").json()) == 1
    assert client.patch(f"/requirements/{rid}/active", json={"active": False}).status_code == 200
    assert client.get("/alerts").json() == []


def test_other_tenant_alerts_are_not_visible(client):
    login(client)
    req1 = create_requirement(client, validity_days=None, warning_days=30)
    with core.SessionLocal() as db:
        doc = db.get(core.Document, 100)
        doc.expires_on = date.today() + timedelta(days=2)
        db.commit()
    client.post("/documents/100/policy", json={"requirement_id": req1.json()["id"]})
    login(client, "admin2@example.invalid", "test-password-2")
    assert client.get("/alerts").json() == []
