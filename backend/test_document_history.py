"""Regression tests for PAGDOC document metadata revision history and access audit."""
import os
from datetime import date, timedelta

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app as core
import document_history  # noqa: F401


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "history.sqlite3"), connect_args={"check_same_thread": False})
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core, "SessionLocal", factory)
    with factory() as db:
        db.add_all([core.Tenant(id=1, name="Empresa Ficticia Uno"), core.Tenant(id=2, name="Empresa Ficticia Dos")])
        db.add_all([
            core.User(id=1, tenant_id=1, email="admin1@example.invalid", password_hash=core.hasher.hash("testpass-one"), role="admin"),
            core.User(id=2, tenant_id=2, email="admin2@example.invalid", password_hash=core.hasher.hash("testpass-two"), role="admin"),
            core.User(id=3, tenant_id=1, email="viewer1@example.invalid", password_hash=core.hasher.hash("testpass-viewer"), role="viewer"),
        ])
        db.add_all([
            core.Project(id=10, tenant_id=1, name="Proyecto Uno", code="P-UNO"),
            core.Project(id=20, tenant_id=2, name="Proyecto Dos", code="P-DOS"),
            core.Document(id=100, tenant_id=1, project_id=10, title="Documento Uno", subject_type="project", subject_name="Proyecto Uno", expires_on=date.today() + timedelta(days=60)),
            core.Document(id=200, tenant_id=2, project_id=20, title="Documento Dos", subject_type="project", subject_name="Proyecto Dos", expires_on=date.today() + timedelta(days=90)),
        ])
        db.commit()
    with TestClient(core.app, base_url="https://testserver") as test_client:
        yield test_client, factory


def auth(client, email="admin1@example.invalid", password="testpass-one"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["X-PAGDOC-CSRF"] = response.json()["csrf_token"]
    return response


def test_document_detail_is_tenant_scoped_and_audited(client):
    test_client, factory = client
    auth(test_client)
    own = test_client.get("/documents/100")
    assert own.status_code == 200
    assert own.json()["title"] == "Documento Uno"
    assert own.json()["revision"] == 0
    assert test_client.get("/documents/200").status_code == 404

    with factory() as db:
        actions = [row.action for row in db.scalars(select(core.Audit).where(core.Audit.tenant_id == 1)).all()]
        assert "document.read" in actions


def test_document_patch_creates_before_change_revisions(client):
    test_client, factory = client
    auth(test_client)

    first = test_client.patch("/documents/100", json={"title": "Documento Uno Actualizado"})
    assert first.status_code == 200
    assert first.json()["revision"] == 1
    assert first.json()["title"] == "Documento Uno Actualizado"

    new_expiry = (date.today() + timedelta(days=10)).isoformat()
    second = test_client.patch("/documents/100", json={"expires_on": new_expiry})
    assert second.status_code == 200
    assert second.json()["revision"] == 2
    assert second.json()["status"] == "expiring"

    history = test_client.get("/documents/100/history")
    assert history.status_code == 200
    rows = history.json()
    assert [row["revision"] for row in rows] == [2, 1]
    assert rows[0]["title"] == "Documento Uno Actualizado"
    assert rows[1]["title"] == "Documento Uno"

    with factory() as db:
        update_events = db.scalars(
            select(core.Audit).where(core.Audit.tenant_id == 1, core.Audit.action == "document.update")
        ).all()
        assert len(update_events) == 2


def test_viewer_can_read_history_but_cannot_modify(client):
    test_client, _ = client
    auth(test_client, "viewer1@example.invalid", "testpass-viewer")
    assert test_client.get("/documents/100/history").status_code == 200
    denied = test_client.patch("/documents/100", json={"title": "No autorizado"})
    assert denied.status_code == 403


def test_cross_tenant_project_link_is_rejected(client):
    test_client, _ = client
    auth(test_client)
    response = test_client.patch("/documents/100", json={"project_id": 20})
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_empty_patch_is_rejected_without_revision(client):
    test_client, _ = client
    auth(test_client)
    response = test_client.patch("/documents/100", json={})
    assert response.status_code == 422
    history = test_client.get("/documents/100/history")
    assert history.status_code == 200
    assert history.json() == []
