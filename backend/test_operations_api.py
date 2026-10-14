import os
from datetime import date,timedelta
os.environ.setdefault('PAGDOC_SECRET_KEY','test-only-not-for-production-secret-at-least-32-characters')
os.environ.setdefault('PAGDOC_ENCRYPTION_KEY','mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=')
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import app as core
import server
import operations_api as ops

@pytest.fixture()
def client(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'ops.sqlite3'),connect_args={'check_same_thread':False});core.Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine);monkeypatch.setattr(core,'SessionLocal',factory)
    with factory() as db:
        db.add_all([core.Tenant(id=1,name='Demo One'),core.Tenant(id=2,name='Demo Two')]);db.flush()
        for id,tenant,role in [(1,1,'admin'),(2,2,'admin'),(3,1,'planner'),(4,1,'editor'),(5,1,'viewer'),(6,1,'reviewer')]:db.add(core.User(id=id,tenant_id=tenant,email=f'u{id}@example.invalid',password_hash=core.hasher.hash('test-password-demo'),role=role,active=1))
        db.add_all([core.Project(id=1,tenant_id=1,name='Demo Project'),core.Project(id=2,tenant_id=2,name='Other Project'),core.Worker(id=1,tenant_id=1,full_name='Demo Worker'),core.Worker(id=2,tenant_id=2,full_name='Other Worker')]);db.commit()
    with TestClient(server.app,base_url='https://testserver') as c:yield c

def login(c,id=1):
    r=c.post('/auth/login',json={'email':f'u{id}@example.invalid','password':'test-password-demo'});assert r.status_code==200;c.headers['X-PAGDOC-CSRF']=r.json()['csrf_token']

def service(c,code='DEMO-001',project_id=1):
    return c.post('/ops/services',json={'project_id':project_id,'code':code,'name':'Demo service','client':'Fictitious Client','location':'Fictitious Place','supervisor':'Demo Supervisor','starts_on':str(date.today()-timedelta(days=5)),'ends_on':str(date.today()+timedelta(days=30))})

def plan(sid=None,state='terrain',**kw):
    d={'worker_id':1,'service_id':sid,'starts_on':str(date.today()),'ends_on':str(date.today()),'state':state,'reason':'Demo planning'};d.update(kw);return d

def document(c):
    r=c.post('/documents',json={'project_id':1,'title':'Demo examination','subject_type':'worker','subject_name':'Demo Worker','expires_on':str(date.today()+timedelta(days=60))});assert r.status_code==201;return r.json()['id']

def transition(c,id,state,version,reason=''):
    return c.post(f'/ops/documents/{id}/review',json={'state':state,'expected_version':version,'reason':reason})

def test_services_auth_isolation_duplicates(client):
    assert client.get('/ops/services').status_code==401
    login(client);assert service(client).status_code==201;assert service(client).status_code==409
    assert service(client,code='OTHER',project_id=2).status_code==404
    login(client,2);assert client.get('/ops/services').json()==[]

def test_planner_has_no_document_access(client):
    login(client,3)
    for path in ['/documents','/search/documents','/requirements','/ops/reviews','/audit','/workers']:assert client.get(path).status_code==403,path
    assert client.get('/ops/bootstrap').status_code==200;assert service(client).status_code==201

def test_viewer_cannot_write(client):
    login(client,5);assert service(client).status_code==403;assert client.post('/ops/assignments',json=plan(state='rest')).status_code==403

def test_csrf(client):
    login(client);client.headers.pop('X-PAGDOC-CSRF');assert service(client).status_code==403

def test_overlap_and_stale_preview(client):
    login(client);sid=service(client).json()['id'];assert client.post('/ops/assignments',json=plan(sid)).status_code==200
    second=service(client,'DEMO-002').json()['id'];payload=plan(second);assert client.post('/ops/assignments',json=payload).status_code==409
    preview=client.post('/ops/assignments/preview',json=payload).json();assert len(preview['conflicts'])==1;assert not preview['readiness']['ready']
    payload.update(replace_existing=True,expected_versions=preview['expected_versions']);assert client.post('/ops/assignments',json=payload).status_code==200
    assert client.post('/ops/assignments',json=payload).status_code==409
    day=str(date.today());rows=client.get(f'/ops/assignments?starts_on={day}&ends_on={day}').json();assert len(rows)==1 and rows[0]['service_id']==second
    assert len(client.get(f"/ops/assignments/{rows[0]['id']}/history").json())==2

def test_rest_and_unassign(client):
    login(client);assert client.post('/ops/assignments',json=plan(state='rest')).status_code==200
    payload=plan(state='unassigned');preview=client.post('/ops/assignments/preview',json=payload).json();assert len(preview['conflicts'])==1
    payload.update(replace_existing=True,expected_versions=preview['expected_versions']);assert client.post('/ops/assignments',json=payload).status_code==200

def test_invalid_dates_and_cross_tenant_worker(client):
    login(client);sid=service(client).json()['id']
    for payload,status in [(plan(sid,worker_id=2),404),(plan(sid,starts_on=str(date.today()+timedelta(days=31)),ends_on=str(date.today()+timedelta(days=31))),409),(plan(sid,ends_on=str(date.today()-timedelta(days=1))),422),(plan(sid,state='rest'),422)]:assert client.post('/ops/assignments',json=payload).status_code==status

def test_attendance_prevents_overwrite(client):
    login(client);sid=service(client).json()['id'];payload=plan(sid);assert client.post('/ops/assignments',json=payload).status_code==200
    day=str(date.today());r=client.get(f'/ops/assignments?starts_on={day}&ends_on={day}').json()[0]
    assert client.patch(f"/ops/assignments/{r['id']}/actual",json={'actual':'attended','expected_version':r['version'],'reason':'Attendance confirmed'}).status_code==200
    payload['expected_versions']=client.post('/ops/assignments/preview',json=payload).json()['expected_versions'];assert client.post('/ops/assignments',json=payload).status_code==409

def test_review_permissions_transitions_and_history(client):
    login(client);doc=document(client);assert transition(client,doc,'approved',0).status_code==409
    assert transition(client,doc,'received',0).status_code==200;assert transition(client,doc,'in_review',1).status_code==200
    login(client,4);assert transition(client,doc,'approved',2).status_code==403
    login(client,6);assert transition(client,doc,'observed',2).status_code==422;assert transition(client,doc,'observed',2,'Missing signature').status_code==200
    login(client);assert transition(client,doc,'received',3).status_code==200;assert transition(client,doc,'in_review',4).status_code==200
    login(client,6);assert transition(client,doc,'approved',5).status_code==200;assert len(client.get(f'/ops/documents/{doc}/reviews').json())==6

def test_document_edit_invalidates_approval(client):
    login(client);doc=document(client)
    for state,v in [('received',0),('in_review',1),('approved',2)]:assert transition(client,doc,state,v).status_code==200
    assert client.patch(f'/documents/{doc}',json={'title':'Changed metadata'}).status_code==200
    row=next(r for r in client.get('/ops/reviews').json() if r['id']==doc);assert row['state']=='pending' and row['version']==3

def test_cross_tenant_review_and_tasks(client):
    login(client);doc=document(client);login(client,2);assert transition(client,doc,'received',0).status_code==404
    assert client.post('/ops/tasks',json={'title':'Fictitious task','assignee_id':1,'due_on':str(date.today())}).status_code==404

def test_tasks_are_scoped_and_versioned(client):
    login(client);r=client.post('/ops/tasks',json={'title':'Check personnel','assignee_id':3,'due_on':str(date.today())});assert r.status_code==201;tid=r.json()['id']
    login(client,3);assert len(client.get('/ops/tasks').json())==1
    assert client.patch(f'/ops/tasks/{tid}',json={'status':'done','expected_version':1}).status_code==200
    assert client.patch(f'/ops/tasks/{tid}',json={'status':'open','expected_version':1}).status_code==409
    login(client,4);assert client.get('/ops/tasks').json()==[]

def test_closeout_fails_closed(client):
    login(client);sid=service(client).json()['id'];assert client.post('/ops/assignments',json=plan(sid)).status_code==200
    r=client.get(f'/ops/services/{sid}/closeout').json();assert not r['ready_to_close'];assert r['binary_evidence_required'];assert r['pending_attendance']==1
    assert client.post(f'/ops/services/{sid}/close',json={'expected_version':1}).status_code==409

def test_approved_metadata_without_file_is_not_accredited(client):
    login(client);doc=document(client);req=client.post('/requirements',json={'name':'Demo examination','subject_type':'worker','required':True}).json()['id']
    assert client.post('/ops/projects/1/requirements',json={'requirement_id':req}).status_code==201
    assert client.post(f'/documents/{doc}/policy',json={'requirement_id':req}).status_code==200
    assert client.post(f'/ops/documents/{doc}/worker',json={'worker_id':1}).status_code==200
    for state,v in [('received',0),('in_review',1),('approved',2)]:assert transition(client,doc,state,v).status_code==200
    sid=service(client).json()['id'];r=client.post('/ops/assignments/preview',json=plan(sid)).json()['readiness'];assert r['configured'] and not r['ready']

def test_atomic_document_registration_and_cross_tenant_requirement(client):
    login(client,2);foreign=client.post('/requirements',json={'name':'Other requirement','subject_type':'worker'}).json()['id']
    login(client);payload={'project_id':1,'worker_id':1,'requirement_id':foreign,'title':'Fictitious registration','expires_on':str(date.today()+timedelta(days=30))}
    assert client.post('/ops/documents',json=payload).status_code==404
    assert client.get('/documents').json()==[]
    own=client.post('/requirements',json={'name':'Own requirement','subject_type':'worker'}).json()['id'];payload['requirement_id']=own
    r=client.post('/ops/documents',json=payload);assert r.status_code==201;assert r.json()['file_upload_enabled'] is False

def test_role_change_revokes_sessions_and_blocks_self_change(client):
    login(client,4);token=client.cookies.get('pagdoc_session')
    login(client);assert client.patch('/users/1/role',json={'role':'planner'}).status_code==409
    r=client.patch('/users/4/role',json={'role':'planner'});assert r.status_code==200 and r.json()['sessions_revoked']
    client.cookies.set('pagdoc_session',token,domain='testserver.local',path='/');assert client.get('/me').status_code==401

def test_whitespace_service_rejected(client):
    login(client);r=client.post('/ops/services',json={'project_id':1,'code':'   ','name':'  ','client':'   ','location':'   ','supervisor':'  ','starts_on':str(date.today()),'ends_on':str(date.today())});assert r.status_code==422

def test_integration_and_metrics_do_not_expose_private_settings(client):
    login(client);r=client.get('/ops/integrations');assert r.status_code==200;assert r.json()['sharepoint']['configured'] is False
    assert client.get('/ops/metrics').json()['scope']=='current_process'
    assert client.get('/ops/audit-checkpoint').json()['externally_anchored'] is False
    login(client,3);assert client.get('/ops/metrics').status_code==403

def test_nonadmin_cannot_assign_or_view_other_users_task(client):
    login(client,4);assert client.post('/ops/tasks',json={'title':'Demo task','assignee_id':3,'due_on':str(date.today())}).status_code==403

def test_future_attendance_rejected(client):
    login(client);sid=service(client).json()['id'];tomorrow=str(date.today()+timedelta(days=1));assert client.post('/ops/assignments',json=plan(sid,starts_on=tomorrow,ends_on=tomorrow)).status_code==200
    row=client.get(f'/ops/assignments?starts_on={tomorrow}&ends_on={tomorrow}').json()[0]
    assert client.patch(f"/ops/assignments/{row['id']}/actual",json={'actual':'attended','expected_version':row['version'],'reason':'Demo attendance'}).status_code==409

def test_complete_private_service_workflow_with_fictitious_binary(client,tmp_path):
    from file_gateway import SecureDocumentGateway,ScanVerdict
    from file_records import store_new_file_version
    from storage import EncryptedLocalStore
    from cryptography.fernet import Fernet
    class TestScanner:
        def scan(self,data,media_type):return ScanVerdict(clean=True,engine='test-only-fictitious-scanner')
    login(client)
    req=client.post('/requirements',json={'name':'Demo requirement','subject_type':'worker','required':True}).json()['id']
    assert client.post('/ops/projects/1/requirements',json={'requirement_id':req}).status_code==201
    doc=client.post('/ops/documents',json={'project_id':1,'worker_id':1,'requirement_id':req,'title':'Fictitious evidence','expires_on':str(date.today()+timedelta(days=1))}).json()['id']
    gateway=SecureDocumentGateway(EncryptedLocalStore(tmp_path/'objects',Fernet.generate_key().decode()),TestScanner())
    with core.SessionLocal() as db:store_new_file_version(db,db.get(core.User,1),doc,gateway,'fictitious.pdf','application/pdf',b'%PDF-1.7\nfictitious\n%%EOF')
    for state,v in [('received',0),('in_review',1),('approved',2)]:assert transition(client,doc,state,v).status_code==200
    sid=client.post('/ops/services',json={'project_id':1,'code':'CLOSE-DEMO','name':'Fictitious service','client':'Fictitious Client','location':'Fictitious Place','supervisor':'Fictitious Supervisor','starts_on':str(date.today()-timedelta(days=1)),'ends_on':str(date.today())}).json()['id']
    assert client.post('/ops/assignments/preview',json=plan(sid)).json()['readiness']['ready']
    assert client.post('/ops/assignments',json=plan(sid)).status_code==200
    day=str(date.today());assignment=client.get(f'/ops/assignments?starts_on={day}&ends_on={day}').json()[0]
    assert client.patch(f"/ops/assignments/{assignment['id']}/actual",json={'actual':'attended','expected_version':1,'reason':'Fictitious confirmed attendance'}).status_code==200
    report=client.get(f'/ops/services/{sid}/closeout').json();assert report['ready_to_close']
    assert client.post(f'/ops/services/{sid}/close',json={'expected_version':1}).json()['status']=='completed'
    # Approval today must not certify a future period after expiry.
    future=service(client,'FUTURE-DEMO').json()['id'];day=str(date.today()+timedelta(days=3))
    assert not client.post('/ops/assignments/preview',json=plan(future,starts_on=day,ends_on=day)).json()['readiness']['ready']

def test_metadata_dates_are_consistent(client):
    login(client);req=client.post('/requirements',json={'name':'Demo requirement','subject_type':'worker'}).json()['id']
    assert client.post('/ops/documents',json={'project_id':1,'worker_id':1,'requirement_id':req,'title':'Demo document','issued_on':'2026-10-10','expires_on':'2026-10-01'}).status_code==422

def test_beta_provisioning_rejects_real_email_and_existing_identity(client):
    from provision_beta import provision
    login(client)
    with core.SessionLocal() as db:
        import pytest
        with pytest.raises(ValueError,match='fictitious'):provision(db,'Fictitious Tenant','user@real-domain.example','test-only-password')
        with pytest.raises(ValueError,match='already exists'):provision(db,'Fictitious Tenant','u1@example.invalid','test-only-password')
