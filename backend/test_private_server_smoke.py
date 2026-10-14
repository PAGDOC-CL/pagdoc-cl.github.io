"""Fictitious end-to-end smoke test for the assembled PAGDOC private server.

This test uses only example.invalid identities and a temporary local SQLite file.
It deliberately does not exercise binary upload because production malware scanning
and private object storage remain deployment gates.
"""
import os
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path("/tmp/pagdoc_private_server_smoke.sqlite3")
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["PAGDOC_ENVIRONMENT"] = "test"
os.environ["PAGDOC_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["PAGDOC_SECRET_KEY"] = "private-server-smoke-secret-at-least-32-characters"
os.environ["PAGDOC_ENCRYPTION_KEY"] = "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4="

from fastapi.testclient import TestClient

import app as core
import server


def test_fictitious_private_server_workflow():
    try:
        with TestClient(server.app, base_url="https://testserver") as client:
            with core.SessionLocal() as db:
                tenant = core.Tenant(name="PAGDOC Smoke Fictitious Tenant")
                db.add(tenant)
                db.flush()
                user = core.User(
                    tenant_id=tenant.id,
                    email="admin-smoke@example.invalid",
                    password_hash=core.hasher.hash("smoke-test-password"),
                    role="admin",
                    active=1,
                )
                db.add(user)
                db.commit()

            login = client.post(
                "/auth/login",
                json={"email": "admin-smoke@example.invalid", "password": "smoke-test-password"},
            )
            assert login.status_code == 200
            client.headers["X-PAGDOC-CSRF"] = login.json()["csrf_token"]

            project = client.post("/projects", json={"name": "Proyecto Ficticio Piloto", "code": "PILOTO-001"})
            assert project.status_code == 201
            project_id = project.json()["id"]

            document = client.post(
                "/documents",
                json={
                    "project_id": project_id,
                    "title": "Examen ficticio",
                    "subject_type": "worker",
                    "subject_name": "Persona Ficticia",
                    "expires_on": (date.today() + timedelta(days=8)).isoformat(),
                },
            )
            assert document.status_code == 201
            document_id = document.json()["id"]

            requirement = client.post(
                "/requirements",
                json={
                    "name": "Examen médico ficticio",
                    "subject_type": "worker",
                    "warning_days": 30,
                    "required": True,
                },
            )
            assert requirement.status_code == 201
            requirement_id = requirement.json()["id"]

            link = client.post(
                f"/requirements/{requirement_id}/documents/{document_id}",
                json={"issued_on": date.today().isoformat()},
            )
            assert link.status_code == 200

            search = client.get("/search/documents?status=expiring&q=ficticio")
            assert search.status_code == 200
            assert search.json()["page"]["total"] == 1

            inbox = client.get("/alerts/inbox")
            assert inbox.status_code == 200
            assert len(inbox.json()) == 1
            assert inbox.json()[0]["document_id"] == document_id

            acknowledge = client.post(f"/alerts/{requirement_id}/{document_id}/acknowledge")
            assert acknowledge.status_code == 200
            assert acknowledge.json()["acknowledged"] is True

            update = client.patch(
                f"/documents/{document_id}",
                json={"title": "Examen ficticio actualizado"},
            )
            assert update.status_code == 200
            assert update.json()["revision"] == 1

            history = client.get(f"/documents/{document_id}/history")
            assert history.status_code == 200
            assert len(history.json()) == 1
            assert history.json()[0]["title"] == "Examen ficticio"

            dashboard = client.get("/dashboard")
            assert dashboard.status_code == 200
            assert dashboard.json()["documents"]["total"] == 1

            integrity = client.get("/audit-integrity")
            assert integrity.status_code == 200
            assert integrity.json()["valid"] is True
            assert integrity.json()["sealed_events"] >= 8

            ready = client.get("/ready")
            assert ready.status_code == 200
            assert ready.json() == {"status": "ready"}
    finally:
        if DB_PATH.exists():
            DB_PATH.unlink()
