"""PostgreSQL-only concurrency checks for PAGDOC serialization invariants."""
import os
import threading
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select

DB_URL = os.getenv("PAGDOC_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DB_URL.startswith(("postgresql://", "postgresql+psycopg://")),
    reason="PostgreSQL-only concurrency test",
)

import app as core
import audit_integrity as integrity
from file_gateway import ScanVerdict, SecureDocumentGateway
from file_records import DocumentFileVersion, store_new_file_version
from storage import EncryptedLocalStore
import file_api
import password_api


TENANT_ID = 990001
USER_ID = 990001
DOCUMENT_ID = 990001


class CleanScanner:
    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        return ScanVerdict(clean=True, engine="postgres-concurrency-ci")


def _seed():
    with core.SessionLocal() as db:
        db.execute(delete(integrity.AuditSeal).where(integrity.AuditSeal.tenant_id == TENANT_ID))
        db.execute(delete(core.Audit).where(core.Audit.tenant_id == TENANT_ID))
        db.execute(delete(DocumentFileVersion).where(DocumentFileVersion.tenant_id == TENANT_ID))
        db.execute(delete(file_api.FileDestination).where(file_api.FileDestination.tenant_id == TENANT_ID))
        db.execute(delete(file_api.FileSubject).where(file_api.FileSubject.tenant_id == TENANT_ID))
        db.execute(delete(core.Document).where(core.Document.tenant_id == TENANT_ID))
        db.execute(delete(password_api.PasswordRecovery).where(password_api.PasswordRecovery.tenant_id == TENANT_ID))
        db.execute(delete(core.User).where(core.User.tenant_id == TENANT_ID))
        db.execute(delete(core.Tenant).where(core.Tenant.id == TENANT_ID))
        db.commit()

        db.add(core.Tenant(id=TENANT_ID, name="PostgreSQL Concurrency CI Tenant"))
        db.commit()

        db.add(
            core.User(
                id=USER_ID,
                tenant_id=TENANT_ID,
                email="pg-concurrency@example.invalid",
                password_hash=core.hasher.hash("not-used-in-test"),
                role="admin",
            )
        )
        db.add(
            core.Document(
                id=DOCUMENT_ID,
                tenant_id=TENANT_ID,
                title="Concurrency document",
                subject_type="company",
                subject_name="Fictitious CI Tenant",
            )
        )
        db.commit()


def test_postgres_serializes_document_file_versions(tmp_path):
    _seed()
    gateway = SecureDocumentGateway(
        EncryptedLocalStore(Path(tmp_path) / "objects", Fernet.generate_key().decode()),
        CleanScanner(),
    )
    workers = 6
    barrier = threading.Barrier(workers)
    versions: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def write_version(index: int):
        try:
            barrier.wait(timeout=10)
            with core.SessionLocal() as db:
                user = db.get(core.User, USER_ID)
                row = store_new_file_version(
                    db,
                    user,
                    DOCUMENT_ID,
                    gateway,
                    f"concurrent-{index}.pdf",
                    "application/pdf",
                    f"%PDF-1.7\nconcurrent version {index}\n%%EOF".encode(),
                )
                with lock:
                    versions.append(row.version)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=write_version, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(versions) == list(range(1, workers + 1))
    with core.SessionLocal() as db:
        rows = db.scalars(
            select(DocumentFileVersion)
            .where(
                DocumentFileVersion.tenant_id == TENANT_ID,
                DocumentFileVersion.document_id == DOCUMENT_ID,
            )
            .order_by(DocumentFileVersion.version)
        ).all()
        assert [row.version for row in rows] == list(range(1, workers + 1))
        assert len({row.object_key for row in rows}) == workers


def test_postgres_serializes_tenant_audit_chain():
    _seed()
    workers = 8
    barrier = threading.Barrier(workers)
    errors: list[Exception] = []
    lock = threading.Lock()

    def append_event(index: int):
        try:
            barrier.wait(timeout=10)
            with core.SessionLocal() as db:
                user = db.get(core.User, USER_ID)
                integrity.signed_add_audit(db, user, "concurrency.event", "tenant", index)
                db.commit()
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=append_event, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    with core.SessionLocal() as db:
        result = integrity.verify_tenant_chain(db, TENANT_ID)
        assert result["valid"] is True
        assert result["sealed_events"] == workers
        seals = db.scalars(
            select(integrity.AuditSeal)
            .where(integrity.AuditSeal.tenant_id == TENANT_ID)
            .order_by(integrity.AuditSeal.audit_id)
        ).all()
        assert len(seals) == workers
        assert seals[0].previous_hash is None
        for previous, current in zip(seals[:-1], seals[1:], strict=True):
            assert current.previous_hash == previous.event_hash

def test_postgres_prevents_double_personnel_assignment():
    import server
    import operations_api as ops
    from datetime import date,timedelta
    from fastapi import HTTPException
    identity=990100
    with core.SessionLocal() as db:
        db.add(core.Tenant(id=identity,name='Fictitious assignment race tenant'));db.flush()
        db.add(core.User(id=identity,tenant_id=identity,email='assignment-race@example.invalid',password_hash=core.hasher.hash('test-only-password'),role='admin'))
        db.add(core.Project(id=identity,tenant_id=identity,name='Fictitious race project'))
        db.add(core.Worker(id=identity,tenant_id=identity,full_name='Fictitious race worker'));db.flush()
        for sid in [identity,identity+1]:db.add(ops.Service(id=sid,tenant_id=identity,project_id=identity,code=f'RACE-{sid}',name='Fictitious service',client='Fictitious client',location='Fictitious site',supervisor='Fictitious supervisor',starts_on=date.today(),ends_on=date.today()+timedelta(days=1)))
        db.commit()
    barrier=threading.Barrier(2);results=[];lock=threading.Lock()
    def assign(sid):
        try:
            with core.SessionLocal() as db:
                user=db.get(core.User,identity);payload=ops.AssignmentIn(worker_id=identity,service_id=sid,starts_on=date.today(),ends_on=date.today(),state='terrain',reason='Fictitious race test')
                barrier.wait(timeout=10);ops.save_assignment(payload,user,None,db);status=200
        except HTTPException as exc:status=exc.status_code
        except Exception as exc:status=type(exc).__name__
        with lock:results.append(status)
    try:
        threads=[threading.Thread(target=assign,args=(sid,)) for sid in [identity,identity+1]]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=30)
        assert sorted(results)==[200,409]
        with core.SessionLocal() as db:assert len(db.scalars(select(ops.Assignment).where(ops.Assignment.tenant_id==identity)).all())==1
    finally:
        with core.SessionLocal() as db:
            for model in [ops.AssignmentChange,ops.Assignment,ops.Service,integrity.AuditSeal,core.Audit,core.Worker,core.Project,core.User]:db.execute(delete(model).where(model.tenant_id==identity))
            db.execute(delete(core.Tenant).where(core.Tenant.id==identity));db.commit()


def test_postgres_rejects_concurrent_upload_with_stale_expected_version(tmp_path,monkeypatch):
    from fastapi import HTTPException
    _seed()
    with core.SessionLocal() as db:
        db.add(file_api.FileSubject(document_id=DOCUMENT_ID,tenant_id=TENANT_ID,subject_kind='company'))
        db.commit()
    gateway=SecureDocumentGateway(EncryptedLocalStore(tmp_path/'guarded',Fernet.generate_key().decode()),CleanScanner())
    monkeypatch.setattr(file_api,'configured_gateway',lambda:gateway)
    barrier=threading.Barrier(2);results=[];lock=threading.Lock()
    def upload(index):
        try:
            with core.SessionLocal() as db:
                user=db.get(core.User,USER_ID)
                barrier.wait(timeout=10)
                file_api.store_upload(db,user,DOCUMENT_ID,0,f'fictitious-{index}.pdf','application/pdf',b'%PDF-1.7\n% fictitious concurrent upload\n%%EOF')
                status=201
        except HTTPException as exc:status=exc.status_code
        except Exception as exc:status=type(exc).__name__
        with lock:results.append(status)
    threads=[threading.Thread(target=upload,args=(i,)) for i in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=30)
    assert sorted(results)==[201,409]
    assert len(list(gateway.store.root.rglob('*.bin')))==1


def test_postgres_batch_creation_rejects_a_competing_stale_plan(tmp_path,monkeypatch):
    from fastapi import HTTPException
    _seed()
    gateway=SecureDocumentGateway(EncryptedLocalStore(Path(tmp_path)/'batch-objects',Fernet.generate_key().decode()),CleanScanner())
    monkeypatch.setattr(file_api,'configured_gateway',lambda:gateway)
    entry=file_api.BatchEntry(path='Fictitious/new.pdf',subject_kind='company',sha256='0'*64)
    barrier=threading.Barrier(2);outcomes=[];lock=threading.Lock()
    def run():
        with core.SessionLocal() as db:
            user=db.get(core.User,USER_ID);barrier.wait(timeout=10)
            try:
                file_api.store_batch_item(db,user,entry,None,0,False,'application/pdf',b'%PDF-1.7\nfictitious concurrent batch\n%%EOF')
                outcome=201
            except HTTPException as exc:db.rollback();outcome=exc.status_code
            with lock:outcomes.append(outcome)
    threads=[threading.Thread(target=run) for _ in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=20)
    assert sorted(outcomes)==[201,409]
    assert len(list(gateway.store.root.rglob('*.bin')))==1


def test_postgres_batch_and_attachment_share_safe_lock_order(tmp_path,monkeypatch):
    from fastapi import HTTPException
    _seed()
    with core.SessionLocal() as db:
        db.add(file_api.FileSubject(document_id=DOCUMENT_ID,tenant_id=TENANT_ID,subject_kind='company'));db.commit()
    scanning=threading.Event();batch_lock=threading.Event();outcomes=[]
    class PausedScanner(CleanScanner):
        def scan(self,data,media_type):
            if threading.current_thread().name=='ordinary-attachment':
                scanning.set();assert batch_lock.wait(10)
            return super().scan(data,media_type)
    gateway=SecureDocumentGateway(EncryptedLocalStore(tmp_path/'mixed',Fernet.generate_key().decode()),PausedScanner())
    monkeypatch.setattr(file_api,'configured_gateway',lambda:gateway)
    original=file_api.scoped_document
    def scoped(db,user,document_id,lock=False):
        if lock and threading.current_thread().name=='batch-update':batch_lock.set()
        return original(db,user,document_id,lock=lock)
    monkeypatch.setattr(file_api,'scoped_document',scoped)
    def run(batch):
        try:
            with core.SessionLocal() as db:
                user=db.get(core.User,USER_ID)
                if batch:
                    assert scanning.wait(10)
                    entry=file_api.BatchEntry(path='Concurrency document',subject_kind='company',sha256='0'*64)
                    file_api.store_batch_item(db,user,entry,DOCUMENT_ID,0,False,'application/pdf',b'%PDF-1.7\nfictitious batch\n%%EOF')
                else:file_api.store_upload(db,user,DOCUMENT_ID,0,'fictitious.pdf','application/pdf',b'%PDF-1.7\nfictitious attachment\n%%EOF')
                outcomes.append(201)
        except HTTPException as error:outcomes.append(error.status_code)
        except Exception as error:outcomes.append(type(error).__name__)
    threads=[threading.Thread(target=run,args=(False,),name='ordinary-attachment'),threading.Thread(target=run,args=(True,),name='batch-update')]
    for thread in threads:thread.start()
    for thread in threads:thread.join(20)
    assert sorted(outcomes,key=str)==[201,409]
    assert len(list(gateway.store.root.rglob('*.bin')))==1



def test_postgres_recovery_link_can_only_be_consumed_once():
    from fastapi import HTTPException,Response
    from starlette.requests import Request
    _seed()
    token='fictitious-postgres-recovery-token-2026-only'
    with core.SessionLocal() as db:
        user=db.get(core.User,USER_ID)
        db.add(password_api.PasswordRecovery(tenant_id=TENANT_ID,user_id=USER_ID,token_hash=core._sha256(token),credential_hash=core._sha256(user.password_hash),email_hash=core._sha256(user.email),created_at=password_api.now(),expires_at=password_api.now()+password_api.timedelta(minutes=30)))
        db.commit()
    barrier=threading.Barrier(2);outcomes=[]
    def run():
        with core.SessionLocal() as db:
            try:
                barrier.wait(10)
                request=Request({'type':'http','client':('192.0.2.1',1234),'headers':[],'method':'POST','path':'/auth/password/reset'})
                password_api.recover(password_api.RecoverIn(token=token,new_password='Fictitious-Pg-Password42!'),request,Response(),db)
                outcomes.append(200)
            except HTTPException as error:db.rollback();outcomes.append(error.status_code)
            except Exception as error:db.rollback();outcomes.append(type(error).__name__)
    threads=[threading.Thread(target=run) for _ in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(20)
    assert sorted(outcomes,key=str)==[200,400]
