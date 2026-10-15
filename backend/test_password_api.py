"""Fictitious-only password lifecycle and recovery tests."""
import re
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_operations_api import client,login
import app as core
import password_api as passwords
import email_alerts
from password_policy import valid_password
NEW='Fictitious-New-Password42!'

@pytest.fixture
def delivery(monkeypatch):
    sent=[]
    monkeypatch.setattr(email_alerts,'smtp_configured',lambda:True)
    monkeypatch.setenv('PAGDOC_SMTP_FROM','sender@example.invalid')
    monkeypatch.setenv('PAGDOC_PASSWORD_RESET_URL','https://localhost:8443/app')
    monkeypatch.setattr(email_alerts,'send_message',lambda message,recipient:sent.append((message,recipient)))
    return sent

def request_token(c,delivery,email='u1@example.invalid'):
    result=c.post('/auth/password/forgot',json={'email':email})
    assert result.status_code==202,result.text
    assert 'token' not in result.text and 'localhost' not in result.text
    message,recipient=delivery[-1]
    assert recipient==email.lower().strip()
    return re.search(r'#restablecer=([A-Za-z0-9_-]+)',message.get_content()).group(1)

@pytest.mark.parametrize('value',['shortA1!','only-lowercase-42!','NoNumbersHere!','NoSpecialChar42','invalid\nPassword42!'])
def test_policy_rejects_missing_requirements(value):assert not valid_password(value)

@pytest.mark.parametrize('id',[1,3,5])
def test_change_is_self_scoped_requires_current_password_csrf_and_revokes_all(client,id):
    login(client,id)
    other=TestClient(core.app,base_url='https://testserver');login(other,id)
    payload={'current_password':'wrong','new_password':NEW}
    assert client.post('/auth/password/change',json=payload).status_code==400
    payload['current_password']='test-password-demo'
    assert client.post('/auth/password/change',json={**payload,'new_password':'weak-password'}).status_code==422
    csrf=client.headers.pop('X-PAGDOC-CSRF')
    assert client.post('/auth/password/change',json=payload).status_code==403
    client.headers['X-PAGDOC-CSRF']=csrf
    result=client.post('/auth/password/change',json=payload)
    assert result.status_code==200,result.text
    assert result.json()['sessions_revoked'] and result.json()['sign_in_required']
    assert client.get('/me').status_code==401 and other.get('/me').status_code==401
    assert client.post('/auth/login',json={'email':f'u{id}@example.invalid','password':NEW}).status_code==200
    with core.SessionLocal() as db:assert core.hasher.verify('test-password-demo',db.get(core.User,2).password_hash)
    other.close()

def test_recovery_registered_email_hashes_token_and_single_use(client,delivery):
    login(client);old_cookie=client.cookies.get('pagdoc_session')
    token=request_token(client,delivery,' U1@EXAMPLE.INVALID ')
    assert 'https://localhost:8443/app#restablecer=' in delivery[0][0].get_content()
    with core.SessionLocal() as db:
        row=db.scalar(select(passwords.PasswordRecovery));assert row.token_hash==core._sha256(token) and token not in row.token_hash
        assert row.delivery_status=='sent'
        assert token not in str([(a.action,a.target_id) for a in db.scalars(select(core.Audit)).all()])
    assert client.post('/auth/password/reset',json={'token':token,'new_password':NEW}).status_code==200
    client.cookies.set('pagdoc_session',old_cookie)
    assert client.get('/me').status_code==401
    assert client.post('/auth/password/reset',json={'token':token,'new_password':'Other-Fictitious42!'}).status_code==400
    assert client.post('/auth/login',json={'email':'u1@example.invalid','password':NEW}).status_code==200

def test_recovery_does_not_disclose_unknown_or_inactive_accounts(client,delivery):
    known=client.post('/auth/password/forgot',json={'email':'u1@example.invalid'})
    unknown=client.post('/auth/password/forgot',json={'email':'unknown@example.invalid'})
    with core.SessionLocal() as db:db.get(core.User,2).active=0;db.commit()
    inactive=client.post('/auth/password/forgot',json={'email':'u2@example.invalid'})
    assert known.status_code==unknown.status_code==inactive.status_code==202
    assert known.json()==unknown.json()==inactive.json() and len(delivery)==1

def test_expired_replaced_tokens_and_admin_reset_invalidate_links(client,delivery):
    first=request_token(client,delivery);second=request_token(client,delivery)
    assert client.post('/auth/password/reset',json={'token':first,'new_password':NEW}).status_code==400
    with core.SessionLocal() as db:
        row=db.scalar(select(passwords.PasswordRecovery).where(passwords.PasswordRecovery.token_hash==core._sha256(second)));row.expires_at=passwords.now()-timedelta(seconds=1);db.commit()
    assert client.post('/auth/password/reset',json={'token':second,'new_password':NEW}).status_code==400
    third=request_token(client,delivery);login(client)
    assert client.post('/users/1/reset-password',json={'password':NEW}).status_code==200
    assert client.post('/auth/password/reset',json={'token':third,'new_password':'Another-Fictitious42!'}).status_code==400

def test_recovery_preserves_mfa_and_change_requires_mfa(client,delivery):
    secret=core.pyotp.random_base32();login(client)
    with core.SessionLocal() as db:
        user=db.get(core.User,1);user.mfa_enabled=1;user.mfa_secret_enc=core._encrypt_mfa(secret);db.commit()
    payload={'current_password':'test-password-demo','new_password':NEW}
    assert client.post('/auth/password/change',json=payload).status_code==400
    token=request_token(client,delivery)
    assert client.post('/auth/password/reset',json={'token':token,'new_password':NEW}).status_code==200
    assert client.post('/auth/login',json={'email':'u1@example.invalid','password':NEW}).status_code==401
    assert client.post('/auth/login',json={'email':'u1@example.invalid','password':NEW,'otp':core.pyotp.TOTP(secret).now()}).status_code==200

def test_rate_limits_and_disabled_delivery_are_explicit(client,monkeypatch,delivery):
    for attempt in range(5):assert client.post('/auth/password/forgot',json={'email':'unknown@example.invalid'}).status_code==202
    assert client.post('/auth/password/forgot',json={'email':'unknown@example.invalid'}).status_code==429
    monkeypatch.setattr(email_alerts,'smtp_configured',lambda:False)
    result=client.post('/auth/password/forgot',json={'email':'u1@example.invalid'})
    assert result.status_code==503 and 'pendiente' in result.json()['detail'] and not delivery

def test_failed_mail_status_and_trusted_link_origin(client,monkeypatch,delivery):
    def fail(*args):raise OSError('Fictitious delivery failure')
    monkeypatch.setattr(email_alerts,'send_message',fail)
    result=client.post('/auth/password/forgot',json={'email':'u1@example.invalid'},headers={'Origin':'https://attacker.example.invalid'})
    assert result.status_code==202
    with core.SessionLocal() as db:assert db.scalar(select(passwords.PasswordRecovery)).delivery_status=='failed'
    monkeypatch.setenv('PAGDOC_PASSWORD_RESET_URL','http://attacker.example.invalid/app')
    assert client.post('/auth/password/forgot',json={'email':'u2@example.invalid'}).status_code==503


def test_change_invalidates_recovery_and_api_account_creation_enforces_policy(client,delivery):
    token=request_token(client,delivery);login(client)
    assert client.post('/users',json={'email':'new@example.invalid','password':'weak-password','role':'viewer'}).status_code==422
    assert client.post('/users',json={'email':'new@example.invalid','password':NEW,'role':'viewer'}).status_code==201
    assert client.post('/auth/password/change',json={'current_password':'test-password-demo','new_password':NEW}).status_code==200
    assert client.post('/auth/password/reset',json={'token':token,'new_password':'Another-Fictitious42!'}).status_code==400


@pytest.mark.parametrize('field,value',[('active',0),('tenant_id',2),('email','changed@example.invalid')])
def test_account_changes_invalidate_previously_issued_link(client,delivery,field,value):
    token=request_token(client,delivery)
    with core.SessionLocal() as db:setattr(db.get(core.User,1),field,value);db.commit()
    assert client.post('/auth/password/reset',json={'token':token,'new_password':NEW}).status_code==400


def test_invalid_payload_does_not_echo_secret_inputs(client):
    marker='short-fictitious-only'
    result=client.post('/auth/password/reset',json={'token':marker,'new_password':'x'})
    assert result.status_code==422 and marker not in result.text
