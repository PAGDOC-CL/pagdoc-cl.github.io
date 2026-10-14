import os
from datetime import date, timedelta

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app as core
import query_api  # noqa: F401


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "query.sqlite3"), connect_args={"check_same_thread": False})
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core, "SessionLocal", factory)
    today = date.today()
    with factory() as db:
        db.add_all([core.Tenant(id=1, name="Tenant Uno"), core.Tenant(id=2, name="Tenant Dos")])
        db.add_all([
            core.User(id=1, tenant_id=1, email="viewer1@example.invalid", password_hash=core.hasher.hash("testpass-one"), role="viewer"),
            core.User(id=2, tenant_id=2, email="viewer2@example.invalid", password_hash=core.hasher.hash("testpass-two"), role="viewer"),
        ])
        db.add_all([
            core.Document(id=10, tenant_id=1, title="Examen altura", subject_type="worker", subject_name="Persona Alfa", expires_on=today + timedelta(days=5)),
            core.Document(id=11, tenant_id=1, title="Licencia conducir", subject_type="worker", subject_name="Persona Beta", expires_on=today - timedelta(days=1)),
            core.Document(id=12, tenant_id=1, title="Permiso vehículo", subject_type="vehicle", subject_name="Camioneta Alfa", expires_on=today + timedelta(days=80)),
            core.Document(id=13, tenant_id=1, title="Documento sin fecha", subject_type="company", subject_name="Empresa Ficticia", expires_on=None),
            core.Document(id=20, tenant_id=2, title="Examen altura secreto", subject_type="worker", subject_name="Otro Tenant", expires_on=today + timedelta(days=3)),
        ])
        db.commit()
    with TestClient(core.app, base_url="https://testserver") as test_client:
        yield test_client, factory


def auth(client):
    response = client.post("/auth/login", json={"email": "viewer1@example.invalid", "password": "testpass-one"})
    assert response.status_code == 200


def test_search_is_tenant_scoped_and_audited(client):
    test_client, factory = client
    auth(test_client)
    response = test_client.get("/search/documents?q=altura")
    assert response.status_code == 200
    payload = response.json()
    assert [row["id"] for row in payload["items"]] == [10]
    assert payload["page"]["total"] == 1
    with factory() as db:
        event = db.scalar(select(core.Audit).where(core.Audit.tenant_id == 1, core.Audit.action == "document.search"))
        assert event is not None


def test_status_and_subject_filters(client):
    test_client, _ = client
    auth(test_client)
    expiring = test_client.get("/search/documents?status=expiring&subject_type=worker").json()
    assert [row["id"] for row in expiring["items"]] == [10]
    expired = test_client.get("/search/documents?status=expired").json()
    assert [row["id"] for row in expired["items"]] == [11]
    valid = test_client.get("/search/documents?status=valid").json()
    assert [row["id"] for row in valid["items"]] == [12]
    no_date = test_client.get("/search/documents?status=no_date").json()
    assert [row["id"] for row in no_date["items"]] == [13]


def test_pagination_returns_total_independent_of_page_size(client):
    test_client, _ = client
    auth(test_client)
    first = test_client.get("/search/documents?limit=2&offset=0").json()
    second = test_client.get("/search/documents?limit=2&offset=2").json()
    assert first["page"] == {"limit": 2, "offset": 0, "total": 4}
    assert second["page"] == {"limit": 2, "offset": 2, "total": 4}
    assert [row["id"] for row in first["items"]] == [10, 11]
    assert [row["id"] for row in second["items"]] == [12, 13]


def test_invalid_filters_are_rejected(client):
    test_client, _ = client
    auth(test_client)
    assert test_client.get("/search/documents?status=unknown").status_code == 422
    assert test_client.get("/search/documents?subject_type=person").status_code == 422
    assert test_client.get("/search/documents?limit=101").status_code == 422
