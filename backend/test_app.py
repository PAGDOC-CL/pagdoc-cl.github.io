"""Regression tests for PAGDOC tenant isolation, authorization and security controls."""
import os
from datetime import date, timedelta

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

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
            api.User(id=3, tenant_id=1, email="viewer@example.invalid", password_hash=api.hasher.hash("testpass-viewer"), role="viewer"),
            api.User(id=4, tenant_id=1, email="editor@example.invalid", password_hash=api.hasher.hash("testpass-editor"), role="editor"),
        ])
        db.add_all([
            api.Project(id=10, tenant_id=1, name="Proyecto Uno", code="P-UNO"),
            api.Project(id=20, tenant_id=2, name="Proyecto Dos", code="P-DOS"),
            api.Worker(id=11, tenant_id=1, full_name="Trabajador Uno"),
            api.Worker(id=21, tenant_id=2, full_name="Trabajador Dos"),
            api.Vehicle(id=12, tenant_id=1, label="Vehículo Uno", plate="DEMO01"),
            api.Vehicle(id=22, tenant_id=2, label="Vehículo Dos", plate="DEMO02"),
            api.Document(id=100, tenant_id=1, project_id=10, title="Documento Uno", subject_type="project", subject_name="Proyecto Uno", expires_on=date.today() + timedelta(days=90)),
            api.Document(id=200, tenant_id=2, project_id=20, title="Documento Dos", subject_type="project", subject_name="Proyecto Dos", expires_on=date.today() - timedelta(days=1)),
        ])
        db.commit()
    with TestClient(api.app, base_url="https://testserver") as test_client:
        yield test_client


def auth(client, email="uno@example.invalid", password="testpass-one", otp=None):
    payload = {"email": email, "password": password}
    if otp is not None:
        payload["otp"] = otp
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 200
    client.headers["X-PAGDOC-CSRF"] = response.json()["csrf_token"]
    return response


def test_health_and_security_headers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "camera=()" in response.headers["permissions-policy"]


def test_requires_authentication(client):
    for path in ("/me", "/users", "/projects", "/workers", "/vehicles", "/documents", "/dashboard", "/audit"):
        assert client.get(path).status_code == 401


def test_wrong_password_is_rejected(client):
    response = client.post("/auth/login", json={"email": "uno@example.invalid", "password": "incorrect"})
    assert response.status_code == 401
    assert "pagdoc_session" not in response.cookies


def test_login_rate_limit(client):
    for _ in range(api.LOGIN_MAX_FAILURES):
        response = client.post("/auth/login", json={"email": "uno@example.invalid", "password": "incorrect"})
        assert response.status_code == 401
    blocked = client.post("/auth/login", json={"email": "uno@example.invalid", "password": "testpass-one"})
    assert blocked.status_code == 429


def test_login_sets_protected_cookie_and_me_works(client):
    response = auth(client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert response.json()["csrf_token"] and "pagdoc_csrf" in response.cookies
    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["tenant_id"] == 1 and me.json()["role"] == "admin"
    assert me.json()["mfa_enabled"] is False


def test_tampered_session_cookie_is_rejected(client):
    auth(client)
    client.cookies.set("pagdoc_session", "forged-token")
    assert client.get("/me").status_code == 401


def test_write_requires_csrf(client):
    auth(client)
    del client.headers["X-PAGDOC-CSRF"]
    assert client.post("/projects", json={"name": "Sin CSRF"}).status_code == 403


def test_wrong_csrf_is_rejected(client):
    auth(client)
    client.headers["X-PAGDOC-CSRF"] = "wrong-token"
    assert client.post("/projects", json={"name": "CSRF inválido"}).status_code == 403


def test_logout_revokes_server_session(client):
    response = auth(client)
    old_session = client.cookies.get("pagdoc_session")
    old_csrf = response.json()["csrf_token"]
    assert client.post("/auth/logout").status_code == 200
    client.cookies.set("pagdoc_session", old_session)
    client.cookies.set("pagdoc_csrf", old_csrf)
    client.headers["X-PAGDOC-CSRF"] = old_csrf
    assert client.get("/me").status_code == 401


def test_logout_all_revokes_parallel_sessions(client):
    auth(client)
    other = TestClient(api.app, base_url="https://testserver")
    try:
        auth(other)
        assert other.get("/me").status_code == 200
        assert client.post("/auth/logout-all").status_code == 200
        assert other.get("/me").status_code == 401
    finally:
        other.close()


def test_mfa_setup_confirm_and_login(client):
    auth(client)
    setup = client.post("/auth/mfa/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    code = api.pyotp.TOTP(secret).now()
    confirm = client.post("/auth/mfa/confirm", json={"code": code})
    assert confirm.status_code == 200 and confirm.json()["enabled"] is True
    other = TestClient(api.app, base_url="https://testserver")
    try:
        missing = other.post("/auth/login", json={"email": "uno@example.invalid", "password": "testpass-one"})
        assert missing.status_code == 401 and missing.json()["detail"] == "MFA required"
        good = other.post("/auth/login", json={"email": "uno@example.invalid", "password": "testpass-one", "otp": api.pyotp.TOTP(secret).now()})
        assert good.status_code == 200
    finally:
        other.close()


def test_admin_password_reset_revokes_sessions(client):
    viewer = TestClient(api.app, base_url="https://testserver")
    try:
        auth(viewer, "viewer@example.invalid", "testpass-viewer")
        auth(client)
        reset = client.post("/users/3/reset-password", json={"password": "New-long-viewer-password-42!"})
        assert reset.status_code == 200 and reset.json()["sessions_revoked"] is True
        assert viewer.get("/me").status_code == 401
        assert viewer.post("/auth/login", json={"email": "viewer@example.invalid", "password": "testpass-viewer"}).status_code == 401
        assert viewer.post("/auth/login", json={"email": "viewer@example.invalid", "password": "New-long-viewer-password-42!"}).status_code == 200
    finally:
        viewer.close()


def test_admin_can_reset_user_mfa_and_sessions(client):
    viewer = TestClient(api.app, base_url="https://testserver")
    try:
        auth(viewer, "viewer@example.invalid", "testpass-viewer")
        setup = viewer.post("/auth/mfa/setup")
        secret = setup.json()["secret"]
        assert viewer.post("/auth/mfa/confirm", json={"code": api.pyotp.TOTP(secret).now()}).status_code == 200
        auth(client)
        reset = client.post("/users/3/reset-mfa")
        assert reset.status_code == 200 and reset.json()["mfa_enabled"] is False
        assert viewer.get("/me").status_code == 401
    finally:
        viewer.close()


def test_tenant_one_reads_only_own_entities(client):
    auth(client)
    assert [p["id"] for p in client.get("/projects").json()] == [10]
    assert [w["id"] for w in client.get("/workers").json()] == [11]
    assert [v["id"] for v in client.get("/vehicles").json()] == [12]
    assert [d["id"] for d in client.get("/documents").json()] == [100]
    dash = client.get("/dashboard").json()
    assert dash["documents"]["total"] == 1 and dash["documents"]["valid"] == 1
    assert dash["entities"] == {"projects": 1, "workers": 1, "vehicles": 1}


def test_tenant_two_reads_only_own_entities(client):
    auth(client, "dos@example.invalid", "testpass-two")
    assert [p["id"] for p in client.get("/projects").json()] == [20]
    assert [w["id"] for w in client.get("/workers").json()] == [21]
    assert [v["id"] for v in client.get("/vehicles").json()] == [22]
    assert [d["id"] for d in client.get("/documents").json()] == [200]
    assert client.get("/dashboard").json()["documents"]["expired"] == 1


def test_viewer_can_read_but_cannot_write(client):
    auth(client, "viewer@example.invalid", "testpass-viewer")
    assert client.get("/workers").status_code == 200
    assert client.post("/projects", json={"name": "No autorizado"}).status_code == 403
    assert client.post("/workers", json={"full_name": "No autorizado"}).status_code == 403
    assert client.post("/vehicles", json={"label": "No autorizado"}).status_code == 403
    assert client.post("/documents", json={"project_id": 10, "title": "No autorizado", "subject_type": "project", "subject_name": "Demo"}).status_code == 403


def test_viewer_cannot_read_admin_resources(client):
    auth(client, "viewer@example.invalid", "testpass-viewer")
    assert client.get("/users").status_code == 403 and client.get("/audit").status_code == 403


def test_editor_can_create_core_entities(client):
    auth(client, "editor@example.invalid", "testpass-editor")
    p = client.post("/projects", json={"name": "Proyecto nuevo", "code": "PN-01"})
    w = client.post("/workers", json={"full_name": "Persona Ficticia", "identifier": "DEMO", "job_title": "Técnico"})
    v = client.post("/vehicles", json={"label": "Camioneta ficticia", "plate": "demo99", "vehicle_type": "Camioneta"})
    assert p.status_code == w.status_code == v.status_code == 201 and v.json()["plate"] == "DEMO99"


def test_document_creation_is_tenant_scoped_and_audited(client):
    auth(client)
    response = client.post("/documents", json={"project_id": 10, "title": "Registro de ejemplo", "subject_type": "vehicle", "subject_name": "VEH-DEMO", "expires_on": "2099-12-31"})
    assert response.status_code == 201
    document_id = response.json()["id"]
    assert any(d["id"] == document_id for d in client.get("/documents").json())
    assert any(a["action"] == "document.create" and a["target_type"] == "document" and a["target_id"] == document_id for a in client.get("/audit").json())
    auth(client, "dos@example.invalid", "testpass-two")
    assert all(d["id"] != document_id for d in client.get("/documents").json())
    assert all(not (a["target_type"] == "document" and a["target_id"] == document_id) for a in client.get("/audit").json())


def test_company_document_can_have_no_project(client):
    auth(client)
    assert client.post("/documents", json={"title": "Documento empresa", "subject_type": "company", "subject_name": "Ficticia Uno"}).status_code == 201


def test_cannot_add_document_to_other_tenant_project(client):
    auth(client)
    assert client.post("/documents", json={"project_id": 20, "title": "Intento", "subject_type": "project", "subject_name": "Ejemplo"}).status_code == 404


def test_invalid_document_type_rejected(client):
    auth(client)
    assert client.post("/documents", json={"project_id": 10, "title": "Prueba", "subject_type": "unknown", "subject_name": "Demo"}).status_code == 422


def test_document_requires_positive_project_identifier(client):
    auth(client)
    assert client.post("/documents", json={"project_id": -1, "title": "Registro", "subject_type": "project", "subject_name": "Ejemplo"}).status_code == 422


@pytest.mark.parametrize("path", ["/projects/20/active", "/workers/21/active", "/vehicles/22/active", "/users/2/active"])
def test_cannot_modify_other_tenant_entities(client, path):
    auth(client)
    assert client.patch(path, json={"active": False}).status_code == 404


def test_admin_cannot_deactivate_self(client):
    auth(client)
    assert client.patch("/users/1/active", json={"active": False}).status_code == 400


def test_deactivating_user_revokes_their_sessions(client):
    viewer = TestClient(api.app, base_url="https://testserver")
    try:
        auth(viewer, "viewer@example.invalid", "testpass-viewer")
        assert viewer.get("/me").status_code == 200
        auth(client)
        assert client.patch("/users/3/active", json={"active": False}).status_code == 200
        assert viewer.get("/me").status_code == 401
    finally:
        viewer.close()


def test_admin_can_create_user_and_it_is_tenant_scoped(client):
    auth(client)
    response = client.post("/users", json={"email": "newuser@example.invalid", "password": "Long-demo-password-42!", "role": "viewer"})
    assert response.status_code == 201
    assert any(u["email"] == "newuser@example.invalid" for u in client.get("/users").json())
    auth(client, "dos@example.invalid", "testpass-two")
    assert all(u["email"] != "newuser@example.invalid" for u in client.get("/users").json())


def test_duplicate_email_rejected(client):
    auth(client)
    assert client.post("/users", json={"email": "dos@example.invalid", "password": "Long-demo-password-42!", "role": "viewer"}).status_code == 409


def test_audit_is_tenant_isolated(client):
    auth(client)
    client.post("/projects", json={"name": "Registro de auditoría Uno"})
    one_actions = [a["action"] for a in client.get("/audit").json()]
    assert "project.create" in one_actions and "auth.login" in one_actions
    auth(client, "dos@example.invalid", "testpass-two")
    two_actions = [a["action"] for a in client.get("/audit").json()]
    assert "project.create" not in two_actions and "auth.login" in two_actions


def test_deactivation_removes_entity_from_dashboard_count(client):
    auth(client)
    assert client.patch("/workers/11/active", json={"active": False}).status_code == 200
    assert client.get("/dashboard").json()["entities"]["workers"] == 0
