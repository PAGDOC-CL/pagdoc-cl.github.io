from datetime import date,timedelta
import os
os.environ.setdefault('PAGDOC_SECRET_KEY','test-only-not-for-production-secret-at-least-32-characters')
os.environ.setdefault('PAGDOC_ENCRYPTION_KEY','mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=')
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select,create_engine
from sqlalchemy.orm import Session
import app as core
import email_alerts as alerts
from operations_api import Task
from test_operations_api import client,login


def setup_user(c):
    login(c)
    return c.put('/ops/email-alerts',json={'enabled':True,'days_before':7}).json()


def test_preferences_are_opt_in_self_scoped_and_require_csrf(client):
    login(client)
    first=client.get('/ops/email-alerts').json()
    assert first['enabled'] is False and first['recipient']=='u1@example.invalid' and not first['delivery_configured']
    assert setup_user(client)['enabled'] is True
    assert client.put('/ops/email-alerts',json={'enabled':True,'recipient':'other@example.invalid'}).status_code==422
    assert client.put('/ops/email-alerts',json={'days_before':0}).status_code==422
    login(client,2);assert client.get('/ops/email-alerts').json()['enabled'] is False
    login(client,3);assert client.get('/ops/email-alerts').status_code==200
    del client.headers['X-PAGDOC-CSRF']
    assert client.put('/ops/email-alerts',json={'enabled':True}).status_code==403


def test_digest_respects_scope_role_dates_and_assigned_tasks(client):
    today=date(2026,10,15)
    with core.SessionLocal() as db:
        for tenant,title,expiry in [(1,'Soon',today+timedelta(days=5)),(1,'Expired',today-timedelta(days=1)),(1,'Unknown',None),(1,'Later',today+timedelta(days=40)),(2,'Other tenant',today-timedelta(days=1))]:db.add(core.Document(tenant_id=tenant,title=title,subject_type='company',subject_name='Fictitious',expires_on=expiry))
        db.add_all([Task(tenant_id=1,title='Fictitious overdue own',assignee_id=3,due_on=today-timedelta(days=2)),Task(tenant_id=1,title='Fictitious overdue other',assignee_id=1,due_on=today-timedelta(days=2))]);db.commit()
        pref=alerts.EmailPreference(days_before=7,include_expiring=1,include_expired=1,include_overdue=1)
        admin=alerts.digest_counts(db,db.get(core.User,1),pref,today)
        assert admin=={'expiring':1,'expired':1,'overdue_tasks':2,'missing_dates':1}
        planner=alerts.digest_counts(db,db.get(core.User,3),pref,today)
        assert planner=={'expiring':0,'expired':0,'overdue_tasks':1,'missing_dates':0}


def test_daily_delivery_is_disabled_until_configured_and_never_retried_blindly(client,monkeypatch):
    setup_user(client);today=date(2026,10,15);sent=[]
    with core.SessionLocal() as db:
        db.add(core.Document(tenant_id=1,title='Fictitious overdue',subject_type='company',subject_name='Fictitious',expires_on=today-timedelta(days=1)));db.commit()
        assert alerts.dispatch_one(db,1,today,lambda *args:sent.append(args))=='disabled'
        monkeypatch.setattr(alerts,'smtp_configured',lambda:True)
        assert alerts.dispatch_one(db,1,today,lambda *args:sent.append(args))=='sent'
        assert alerts.dispatch_one(db,1,today,lambda *args:sent.append(args))=='already_attempted'
        assert len(sent)==1 and sent[0][0]=='u1@example.invalid'
        def interrupted(*args):raise OSError('Fictitious uncertain SMTP response')
        assert alerts.dispatch_one(db,1,today+timedelta(days=1),interrupted)=='unknown'
        assert alerts.dispatch_one(db,1,today+timedelta(days=1),lambda *args:sent.append(args))=='already_attempted'
        user=db.get(core.User,1);user.active=0;db.commit()
        assert alerts.dispatch_one(db,1,today+timedelta(days=2),lambda *args:sent.append(args))=='disabled'
        assert len(sent)==1


def test_smtp_uses_verified_tls_registered_recipient_and_counts_only(monkeypatch):
    observed={}
    class SMTP:
        def __init__(self,host,port,timeout):observed.update(host=host,port=port)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def starttls(self,context):assert context.verify_mode==2;observed['tls']=True
        def login(self,user,password):assert observed['tls'];observed['login']=user
        def send_message(self,message,from_addr,to_addrs):observed.update(message=message,recipients=to_addrs)
    monkeypatch.setattr(alerts.smtplib,'SMTP',SMTP)
    for key,value in {'PAGDOC_SMTP_HOST':'smtp.example.invalid','PAGDOC_SMTP_PORT':'587','PAGDOC_SMTP_FROM':'sender@example.invalid','PAGDOC_SMTP_USERNAME':'sender@example.invalid','PAGDOC_SMTP_PASSWORD':'fictitious-only'}.items():monkeypatch.setenv(key,value)
    alerts.smtp_send('recipient@example.invalid',{'expiring':2,'expired':1,'overdue_tasks':3},date(2026,10,15))
    assert observed['recipients']==['recipient@example.invalid']
    assert not list(observed['message'].iter_attachments())
    assert 'Documentos próximos a vencer: 2' in observed['message'].get_content()


def test_local_admin_members_are_explicit_idempotent_and_enable_only_requested_profiles(tmp_path):
    from provision_members import provision_members
    engine=create_engine('sqlite:///'+str(tmp_path/'members.sqlite3'));core.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(core.Tenant(id=1,name='Fictitious Contractor'));db.flush()
        db.add(core.User(id=1,tenant_id=1,email='owner@example.invalid',password_hash=core.hasher.hash('fictitious-owner-password'),role='admin',active=1));db.commit()
        result=provision_members(db,['first@example.invalid','second@example.invalid'],True)
        assert len(result)==2 and all(len(item['new_password'])>=24 for item in result)
        for item in result:
            user=db.scalar(select(core.User).where(core.User.email==item['email']))
            assert user.role=='admin' and core.hasher.verify(item['new_password'],user.password_hash)
            assert alerts.preference(db,user).enabled==1
        again=provision_members(db,['first@example.invalid','second@example.invalid'],True)
        assert all(item['new_password'] is None for item in again)
        assert alerts.preference(db,db.get(core.User,1)) is None


def test_local_admin_members_cannot_run_without_operator_gate(monkeypatch):
    from provision_members import main
    monkeypatch.delenv('PAGDOC_ALLOW_MEMBER_PROVISIONING',raising=False)
    with pytest.raises(SystemExit,match='controlador local'):main()


def test_email_configuration_retains_existing_keys_and_uses_private_permissions(tmp_path):
    spec=importlib.util.spec_from_file_location('email_configuration',Path(__file__).resolve().parent.parent/'deployment/local/configure_email.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    tmp_path.chmod(0o700)
    path=tmp_path/'runtime.env';path.write_text('PAGDOC_SECRET_KEY=fictitious-existing-secret\nPAGDOC_ENCRYPTION_KEY=fictitious-existing-key\n');path.chmod(0o600)
    values={'PAGDOC_EMAIL_DELIVERY_ENABLED':'1','PAGDOC_SMTP_PASSWORD':"fictitious-$-quote'password"}
    module.save_values(path,values);module.save_values(path,values)
    assert path.stat().st_mode&0o777==0o600
    assert 'PAGDOC_ENCRYPTION_KEY=fictitious-existing-key' in path.read_text()
    assert path.read_text().count('PAGDOC_EMAIL_DELIVERY_ENABLED=1')==1
    with pytest.raises(ValueError):module.save_values(path,{'PAGDOC_SMTP_PASSWORD':'bad\nvalue'})
