"""Regression tests for PAGDOC tenant isolation, authorization and core modules."""
import os
from datetime import date, timedelta

os.environ.setdefault(
    "PAGDOC_SECRET_KEY",
    "test-only-not-for-production-secret-at-least-32-characters",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as api


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "test.sqlite3"),
        connect_args={"check_same_thread": False},
    )
    api.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(api, "SessionLocal", factory)

    with factory() as db:
        db.add_all(
            [
                api.Tenant(id=1, name="Ficticia Uno"),
                api.Tenant(id=2, name="Ficticia Dos"),
            ]
        )
        db.add_all(
            [
                api.User(
                    id=1,
                    tenant_id=1,
                    email="uno@example.invalid",
                    password_hash=api.hasher.hash("testpass-one"),
                    role="admin",
                ),
                api.User(
                    id=2,
                    tenant_id=2,
                    email="dos@example.invalid",
                    password_hash=api.hasher.hash("testpass-two"),
                    role="admin",
                ),
                api.User(
                    id=3,
                    tenant_id=1,
                    email="viewer@example.invalid",
                    password_hash=api.hasher.hash("testpass-viewer"),
                    role="viewer",
                ),
                api.User(
                    id=4,
                    tenant_id=1,
                    email="editor@example.invalid",
                    password_hash=api.hasher.hash("testpass-editor"),
                    role="editor",
                ),
            ]
        )
        db.add_all(
            [
                api.Project(id=10, tenant_id=1, name="Proyecto Uno", code="P-UNO"),
                api.Project(id=20, tenant_id=2, name="Proyecto Dos", code="P-DOS"),
                api.Worker(id=11, tenant_id=1, full_name="Trabajador Uno"),
                api.Worker(id=21, tenant_id=2, full_name="Trabajador Dos"),
                api.Vehicle(id=12, tenant_id=1, label="Vehículo Uno", plate="DEMO01"),
                api.Vehicle(id=22, tenant_id=2, label="Vehículo Dos", plate="DEMO02"),
                api.Document(
                    id=100,
                    tenant_id=1,
                    project_id=10,
                    title="Documento Uno",
                    subject_type="project",
                    subject_name="Proyecto Uno",
                    expires_on=date.today() + timedelta(days=90),
                ),
                api.Document(
                    id=200,
                    tenant_id=2,
                    project_id=20,
                    title="Documento Dos",
                    subject_type="project",
                    subject_name="Proyecto Dos",
                    expires_on=date.today() - timedelta(days=1),
                ),
            ]
        )
        db.commit()

    with TestClient(api.app, base_url="https://testserver") as test_client:
        yield test_client


def auth(client, user_id, tenant_id):
    client.cookies.set(
        "pagdoc_session",
        api.signer.dumps({"uid": user_id, "tid": tenant_id}),
    )


def test_health_and_security_headers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_requires_authentication(client):
    for path in (
        "/me",
        "/users",
        "/projects",
        "/workers",
        "/vehicles",
        "/documents",
        "/dashboard",
        "/audit",
    ):
        assert client.get(path).status_code == 401


def test_wrong_password_is_rejected(client):
    response = client.post(
        "/auth/login",
        json={"email": "uno@example.invalid", "password": "incorrect"},
    )
    assert response.status_code == 401
    assert "pagdoc_session" not in response.cookies


def test_login_sets_protected_cookie_and_me_works(client):
    response = client.post(
        "/auth/login",
        json={"email": "uno@example.invalid", "password": "testpass-one"},
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["tenant_id"] == 1
    assert me.json()["role"] == "admin"


def test_logout_clears_cookie(client):
    auth(client, 1, 1)
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_tenant_one_reads_only_own_entities(client):
    auth(client, 1, 1)
    assert [p["id"] for p in client.get("/projects").json()] == [10]
    assert [w["id"] for w in client.get("/workers").json()] == [11]
    assert [v["id"] for v in client.get("/vehicles").json()] == [12]
    assert [d["id"] for d in client.get("/documents").json()] == [100]
    dash = client.get("/dashboard").json()
    assert dash["documents"]["total"] == 1
    assert dash["documents"]["valid"] == 1
    assert dash["entities"] == {"projects": 1, "workers": 1, "vehicles": 1}


def test_tenant_two_reads_only_own_entities(client):
    auth(client, 2, 2)
    assert [p["id"] for p in client.get("/projects").json()] == [20]
    assert [w["id"] for w in client.get("/workers").json()] == [21]
    assert [v["id"] for v in client.get("/vehicles").json()] == [22]
    assert [d["id"] for d in client.get("/documents").json()] == [200]
    assert client.get("/dashboard").json()["documents"]["expired"] == 1


def test_reject_forged_tenant_cookie(client):
    auth(client, 1, 2)
    assert client.get("/projects").status_code == 401


def test_viewer_can_read_but_cannot_write(client):
    auth(client, 3, 1)
    assert client.get("/workers").status_code == 200
    assert client.post("/projects", json={"name": "No autorizado"}).status_code == 403
    assert client.post("/workers", json={"full_name": "No autorizado"}).status_code == 403
    assert client.post("/vehicles", json={"label": "No autorizado"}).status_code == 403
    assert (
        client.post(
            "/documents",
            json={
                "project_id": 10,
                "title": "No autorizado",
                "subject_type": "project",
                "subject_name": "Demo",
            },
        ).status_code
        == 403
    )


def test_viewer_cannot_read_admin_resources(client):
    auth(client, 3, 1)
    assert client.get("/users").status_code == 403
    assert client.get("/audit").status_code == 403


def test_editor_can_create_core_entities(client):
    auth(client, 4, 1)
    p = client.post("/projects", json={"name": "Proyecto nuevo", "code": "PN-01"})
    w = client.post(
        "/workers",
        json={"full_name": "Persona Ficticia", "identifier": "DEMO", "job_title": "Técnico"},
    )
    v = client.post(
        "/vehicles",
        json={"label": "Camioneta ficticia", "plate": "demo99", "vehicle_type": "Camioneta"},
    )
    assert p.status_code == w.status_code == v.status_code == 201
    assert v.json()["plate"] == "DEMO99"


def test_document_creation_is_tenant_scoped_and_audited(client):
    auth(client, 1, 1)
    response = client.post(
        "/documents",
        json={
            "project_id": 10,
            "title": "Registro de ejemplo",
            "subject_type": "vehicle",
            "subject_name": "VEH-DEMO",
            "expires_on": "2099-12-31",
        },
    )
    assert response.status_code == 201
    document_id = response.json()["id"]
    assert any(d["id"] == document_id for d in client.get("/documents").json())
    assert any(
        a["action"] == "document.create"
        and a["target_type"] == "document"
        and a["target_id"] == document_id
        for a in client.get("/audit").json()
    )
    auth(client, 2, 2)
    assert all(d["id"] != document_id for d in client.get("/documents").json())
    assert all(a["target_id"] != document_id for a in client.get("/audit").json())


def test_company_document_can_have_no_project(client):
    auth(client, 1, 1)
    response = client.post(
        "/documents",
        json={
            "title": "Documento empresa",
            "subject_type": "company",
            "subject_name": "Ficticia Uno",
        },
    )
    assert response.status_code == 201


def test_cannot_add_document_to_other_tenant_project(client):
    auth(client, 1, 1)
    response = client.post(
        "/documents",
        json={
            "project_id": 20,
            "title": "Intento",
            "subject_type": "project",
            "subject_name": "Ejemplo",
        },
    )
    assert response.status_code == 404


def test_invalid_document_type_rejected(client):
    auth(client, 1, 1)
    response = client.post(
        "/documents",
        json={
            "project_id": 10,
            "title": "Prueba",
            "subject_type": "unknown",
            "subject_name": "Demo",
        },
    )
    assert response.status_code == 422


def test_document_requires_positive_project_identifier(client):
    auth(client, 1, 1)
    response = client.post(
        "/documents",
        json={
            "project_id": -1,
            "title": "Registro",
            "subject_type": "project",
            "subject_name": "Ejemplo",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/projects/20/active", {"active": False}),
        ("/workers/21/active", {"active": False}),
        ("/vehicles/22/active", {"active": False}),
        ("/users/2/active", {"active": False}),
    ],
)
def test_cannot_modify_other_tenant_entities(client, path, payload):
    auth(client, 1, 1)
    assert client.patch(path, json=payload).status_code == 404


def test_admin_cannot_deactivate_self(client):
    auth(client, 1, 1)
    assert client.patch("/users/1/active", json={"active": False}).status_code == 400


def test_admin_can_create_user_and_it_is_tenant_scoped(client):
    auth(client, 1, 1)
    response = client.post(
        "/users",
        json={
            "email": "newuser@example.invalid",
            "password": "long-demo-password",
            "role": "viewer",
        },
    )
    assert response.status_code == 201
    users = client.get("/users").json()
    assert any(u["email"] == "newuser@example.invalid" for u in users)
    auth(client, 2, 2)
    assert all(u["email"] != "newuser@example.invalid" for u in client.get("/users").json())


def test_duplicate_email_rejected(client):
    auth(client, 1, 1)
    response = client.post(
        "/users",
        json={
            "email": "dos@example.invalid",
            "password": "long-demo-password",
            "role": "viewer",
        },
    )
    assert response.status_code == 409


def test_audit_is_tenant_isolated(client):
    auth(client, 1, 1)
    client.post("/projects", json={"name": "Registro de auditoría Uno"})
    assert len(client.get("/audit").json()) == 1
    auth(client, 2, 2)
    assert client.get("/audit").json() == []


def test_deactivation_removes_entity_from_dashboard_count(client):
    auth(client, 1, 1)
    assert client.patch("/workers/11/active", json={"active": False}).status_code == 200
    assert client.get("/dashboard").json()["entities"]["workers"] == 0
