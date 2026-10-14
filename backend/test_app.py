"""Tenant isolation regression tests for PAGDOC prototype."""
import os
os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-32-character-secret")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import app as api

@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "test.sqlite3"), connect_args={"check_same_thread": False})
    api.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(api, "SessionLocal", factory)
    with factory() as db:
        db.add_all([api.Tenant(id=1, name="Ficticia Uno"), api.Tenant(id=2, name="Ficticia Dos")])
        db.add_all([
            api.User(id=1, tenant_id=1, email="uno@example.invalid", password_hash=api.hasher.hash("testpass-one"), role="admin"),
            api.User(id=2, tenant_id=2, email="dos@example.invalid", password_hash=api.hasher.hash("testpass-two"), role="admin"),
            api.Project(id=10, tenant_id=1, name="Proyecto Uno"),
            api.Project(id=20, tenant_id=2, name="Proyecto Dos"),
            api.Document(id=100, tenant_id=1, project_id=10, title="Documento Uno", subject_type="project", subject_name="Proyecto Uno"),
            api.Document(id=200, tenant_id=2, project_id=20, title="Documento Dos", subject_type="project", subject_name="Proyecto Dos")
        ])
        db.commit()
    with TestClient(api.app) as test_client:
        yield test_client

def auth(client, user_id, tenant_id):
    client.cookies.set("pagdoc_session", api.signer.dumps({"uid": user_id, "tid": tenant_id}))

def test_requires_authentication(client):
    assert client.get("/projects").status_code == 401
    assert client.get("/documents").status_code == 401

def test_tenant_one_cannot_read_tenant_two(client):
    auth(client, 1, 1)
    assert [p["id"] for p in client.get("/projects").json()] == [10]
    assert [d["id"] for d in client.get("/documents").json()] == [100]
    assert client.get("/dashboard").json()["total"] == 1

def test_tenant_two_cannot_read_tenant_one(client):
    auth(client, 2, 2)
    assert [p["id"] for p in client.get("/projects").json()] == [20]
    assert [d["id"] for d in client.get("/documents").json()] == [200]

def test_cannot_add_document_to_other_tenant_project(client):
    auth(client, 1, 1)
    response = client.post("/documents", json={"project_id": 20, "title": "Intento", "subject_type": "project", "subject_name": "Ejemplo"})
    assert response.status_code == 404

def test_reject_forged_tenant_cookie(client):
    auth(client, 1, 2)
    assert client.get("/projects").status_code == 401

def test_viewer_cannot_write(client):
    with api.SessionLocal() as db:
        db.add(api.User(id=3, tenant_id=1, email="visor@example.invalid", password_hash=api.hasher.hash("testpass-three"), role="viewer"))
        db.commit()
    auth(client, 3, 1)
    assert client.post("/projects", json={"name": "No autorizado"}).status_code == 403
