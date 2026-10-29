import json
import os
import time
from unittest.mock import Mock

from cryptography.fernet import Fernet
import pytest
import smtp_oauth as oauth

TENANT='00000000-0000-4000-8000-000000000001'
CLIENT='00000000-0000-4000-8000-000000000002'
USER='sender@example.invalid'


@pytest.fixture
def storage(tmp_path,monkeypatch):
    monkeypatch.setenv('PAGDOC_STORAGE_ROOT',str(tmp_path))
    monkeypatch.setenv('PAGDOC_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('PAGDOC_SMTP_USERNAME',USER)
    return tmp_path


def cache(**changes):
    return dict(tenant=TENANT,client=CLIENT,username=USER,access_token='fictitious-access',
                refresh_token='fictitious-refresh',expires_at=time.time()+3600,**changes)


def test_encrypted_atomic_cache_and_fail_closed_permissions(storage):
    with oauth.locked() as path:
        oauth.save_cache(path,cache())
        assert path.stat().st_mode&0o777==0o600
        assert b'fictitious' not in path.read_bytes()
        assert oauth.read_cache(path)['username']==USER
    assert oauth.configured()
    path.chmod(0o644)
    assert not oauth.configured()


def test_refuses_symlink_and_other_mailbox(storage,monkeypatch):
    with oauth.locked() as path:oauth.save_cache(path,cache())
    with pytest.raises(oauth.OAuthError,match='otra cuenta'):oauth.access_token('other@example.invalid')
    path.unlink();target=storage/'target';target.write_text('keep');path.symlink_to(target)
    assert not oauth.configured()
    assert target.read_text()=='keep'


def test_refresh_rotates_tokens_and_keeps_valid_grant(storage,monkeypatch):
    data=cache();data['expires_at']=0
    with oauth.locked() as path:oauth.save_cache(path,data)
    post=Mock(return_value={'access_token':'new-access','refresh_token':'new-refresh','scope':oauth.SCOPE,'expires_in':3600})
    monkeypatch.setattr(oauth,'post',post)
    assert oauth.access_token(USER)=='new-access'
    assert post.call_args.args[2]['refresh_token']=='fictitious-refresh'
    with oauth.locked() as path:assert oauth.read_cache(path)['refresh_token']=='new-refresh'
    assert oauth.access_token(USER)=='new-access' and post.call_count==1


def test_refresh_denial_preserves_previous_encrypted_cache(storage,monkeypatch):
    data=cache();data['expires_at']=0
    with oauth.locked() as path:oauth.save_cache(path,data)
    before=path.read_bytes();monkeypatch.setattr(oauth,'post',lambda *a:{'error':'invalid_grant','error_description':'secret-text'})
    with pytest.raises(oauth.OAuthError) as exc:oauth.access_token(USER)
    assert 'secret-text' not in str(exc.value) and path.read_bytes()==before


def test_device_pending_slowdown_and_success_without_printing_token(capsys):
    responses=iter([{'device_code':'private-device-code','user_code':'DEMO-CODE','verification_uri':'https://microsoft.com/devicelogin','expires_in':900,'interval':5},
                    {'error':'authorization_pending'},{'error':'slow_down'},
                    {'access_token':'secret-access','refresh_token':'secret-refresh','scope':oauth.SCOPE,'expires_in':3600}])
    waits=[]
    data=oauth.device_login(TENANT,CLIENT,USER,request=lambda *a:next(responses),sleep=waits.append,clock=lambda:0)
    assert data['access_token']=='secret-access' and waits==[5,5,10]
    output=capsys.readouterr().out
    assert 'DEMO-CODE' in output and 'private-device-code' not in output and 'secret-access' not in output


@pytest.mark.parametrize('error',['authorization_declined','access_denied','expired_token','invalid_client'])
def test_device_denials_do_not_loop_or_store_tokens(error,storage):
    responses=iter([{'device_code':'private','user_code':'DEMO','verification_uri':'https://microsoft.com/devicelogin','expires_in':60},
                    {'error':error,'error_codes':[65001],'error_description':'do-not-print'}])
    with pytest.raises(oauth.OAuthError) as exc:
        oauth.device_login(TENANT,CLIENT,USER,request=lambda *a:next(responses),sleep=lambda n:None,clock=lambda:0)
    assert error in str(exc.value) and 'do-not-print' not in str(exc.value)
    assert not (storage/'.pagdoc-mail/tokens.enc').exists()


def test_device_flow_expiration_and_untrusted_uri():
    flow={'device_code':'private','user_code':'DEMO','verification_uri':'https://microsoft.com/devicelogin','expires_in':1}
    ticks=iter([0,0,5])
    with pytest.raises(oauth.OAuthError,match='venció'):
        oauth.device_login(TENANT,CLIENT,USER,request=lambda *a:flow,sleep=lambda n:None,clock=lambda:next(ticks))
    with pytest.raises(oauth.OAuthError,match='inesperada'):
        oauth.device_login(TENANT,CLIENT,USER,request=lambda *a:{**flow,'verification_uri':'https://example.invalid/phish'})


def test_authentication_uses_xoauth2_without_resending_secret():
    smtp=Mock();oauth.authenticate(smtp,USER,'fictitious-token')
    mechanism,callback=smtp.auth.call_args.args
    assert mechanism=='XOAUTH2'
    assert callback()==f'user={USER}\x01auth=Bearer fictitious-token\x01\x01'
    assert callback(b'failure')==''
    smtp.send_message.assert_not_called()


def test_smtp_check_requires_tls_before_authentication(monkeypatch):
    calls=[]
    class SMTP:
        def __init__(self,host,port,timeout):assert host==oauth.HOST and port==587
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def ehlo(self):calls.append('ehlo')
        def starttls(self,context):assert context.verify_mode==2;calls.append('tls')
        def auth(self,*args):calls.append('auth')
    monkeypatch.setattr(oauth.smtplib,'SMTP',SMTP)
    oauth.check_login(USER,'fictitious-token')
    assert calls==['ehlo','tls','ehlo','auth']


def test_email_alerts_oauth_and_existing_password_paths(monkeypatch,storage):
    import email_alerts as alerts
    calls=[]
    class SMTP:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def starttls(self,context):calls.append('tls')
        def ehlo(self):calls.append('ehlo')
        def auth(self,*args):calls.append('oauth')
        def login(self,*args):calls.append('password')
        def send_message(self,*args,**kwargs):calls.append('send')
    with oauth.locked() as path:oauth.save_cache(path,cache())
    for key,value in {'PAGDOC_SMTP_AUTH_MODE':'microsoft_oauth','PAGDOC_SMTP_HOST':oauth.HOST,'PAGDOC_SMTP_PORT':'587','PAGDOC_SMTP_FROM':USER,'PAGDOC_EMAIL_DELIVERY_ENABLED':'1'}.items():monkeypatch.setenv(key,value)
    monkeypatch.setattr(alerts.smtplib,'SMTP',SMTP)
    assert alerts.smtp_configured()
    from email.message import EmailMessage
    alerts.send_message(EmailMessage(),'recipient@example.invalid')
    assert calls==['tls','ehlo','oauth','send']
    calls.clear();monkeypatch.setenv('PAGDOC_SMTP_AUTH_MODE','password');monkeypatch.setenv('PAGDOC_SMTP_PASSWORD','fictitious-password')
    alerts.send_message(EmailMessage(),'recipient@example.invalid')
    assert calls==['tls','password','send']
    monkeypatch.setenv('PAGDOC_SMTP_AUTH_MODE','bad');assert not alerts.smtp_configured()
    with pytest.raises(ValueError):alerts.send_message(EmailMessage(),'recipient@example.invalid')
