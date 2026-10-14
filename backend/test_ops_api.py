import os

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app as core
import ops_api


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "ready.sqlite3"), connect_args={"check_same_thread": False})
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core, "SessionLocal", factory)
    with TestClient(core.app, base_url="https://testserver") as test_client:
        yield test_client, factory


def test_development_readiness_checks_database_without_requiring_alembic_table(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setenv("PAGDOC_ENVIRONMENT", "development")
    response = test_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_production_readiness_fails_closed_when_schema_revision_is_unavailable(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setenv("PAGDOC_ENVIRONMENT", "production")
    response = test_client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_production_readiness_accepts_expected_schema_revision(client, monkeypatch):
    test_client, factory = client
    monkeypatch.setenv("PAGDOC_ENVIRONMENT", "production")
    with factory() as db:
        db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        db.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": ops_api.EXPECTED_SCHEMA_REVISION})
        db.commit()
    response = test_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_production_readiness_rejects_stale_schema_revision(client, monkeypatch):
    test_client, factory = client
    monkeypatch.setenv("PAGDOC_ENVIRONMENT", "production")
    with factory() as db:
        db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        db.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0001_initial')"))
        db.commit()
    response = test_client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
