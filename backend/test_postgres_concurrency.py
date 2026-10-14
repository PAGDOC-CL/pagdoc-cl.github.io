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
        db.execute(delete(core.Document).where(core.Document.tenant_id == TENANT_ID))
        db.execute(delete(core.User).where(core.User.tenant_id == TENANT_ID))
        db.execute(delete(core.Tenant).where(core.Tenant.id == TENANT_ID))
        db.commit()
        db.add(core.Tenant(id=TENANT_ID, name="PostgreSQL Concurrency CI Tenant"))
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
        except Exception as exc:  # collected so the main thread can assert cleanly
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
        for previous, current in zip(seals, seals[1:], strict=True):
            assert current.previous_hash == previous.event_hash
