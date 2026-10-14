import os

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

from fastapi.testclient import TestClient

import app as core
import security_hardening  # noqa: F401


def test_restrictive_headers_are_present(monkeypatch):
    monkeypatch.setenv("PAGDOC_ENVIRONMENT", "test")
    with TestClient(core.app, base_url="https://testserver") as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["x-permitted-cross-domain-policies"] == "none"
    assert "strict-transport-security" not in response.headers


def test_hsts_is_enabled_for_production(monkeypatch):
    monkeypatch.setenv("PAGDOC_ENVIRONMENT", "test")
    with TestClient(core.app, base_url="https://testserver") as client:
        # This isolates the response-header policy from the separate startup gate.
        monkeypatch.setenv("PAGDOC_ENVIRONMENT", "production")
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
