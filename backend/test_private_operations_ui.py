import os
os.environ.setdefault('PAGDOC_SECRET_KEY','test-only-not-for-production-secret-at-least-32-characters')
os.environ.setdefault('PAGDOC_ENCRYPTION_KEY','mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=')
from fastapi.testclient import TestClient
import server

def test_private_ui_uses_same_origin_assets_and_no_inline_scripts():
    c=TestClient(server.app,base_url='https://testserver')
    r=c.get('/app');assert r.status_code==200;assert 'data-runtime="private"' in r.text;assert 'src="/app/assets/operations.js"' in r.text
    assert 'La demo simula estos procesos' not in r.text
    assert "script-src 'self'" in r.headers['content-security-policy'];assert '<script>' not in r.text
    assert c.get('/app/assets/operations.js').status_code==200
    assert c.get('/app/assets/app.py').status_code==404
    assert "media-src 'self'" in r.headers['content-security-policy']
    assert 'id="login-film"' in r.text
    assert '<strong>MUFAS CHILE</strong>' in r.text

def test_private_operations_require_auth_even_with_public_ui():
    c=TestClient(server.app,base_url='https://testserver')
    assert c.get('/ops/bootstrap').status_code==401
    assert c.get('/ops/integrations').status_code==401
    assert c.get('/ops/metrics').status_code==401

def test_private_startup_rejects_database_without_migrations(tmp_path,monkeypatch):
    import pytest
    from sqlalchemy import create_engine
    import app as core
    monkeypatch.setattr(core,'engine',create_engine('sqlite:///'+str(tmp_path/'unmigrated.sqlite3')))
    monkeypatch.setenv('PAGDOC_ENVIRONMENT','production')
    with pytest.raises(RuntimeError,match='Apply reviewed migrations'):
        with TestClient(server.app,base_url='https://testserver'):pass
