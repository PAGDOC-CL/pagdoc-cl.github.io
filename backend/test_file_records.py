import os
from datetime import date

os.environ.setdefault("PAGDOC_SECRET_KEY", "test-only-not-for-production-secret-at-least-32-characters")
os.environ.setdefault("PAGDOC_ENCRYPTION_KEY", "mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=")

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app as core
from file_gateway import GatewayError, ScanVerdict, SecureDocumentGateway
from file_records import DocumentFileVersion, list_file_versions, read_file_version, store_new_file_version
from storage import EncryptedLocalStore


class CleanScanner:
    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        return ScanVerdict(clean=True, engine="fake-ci-scanner")


class BlockScanner:
    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        return ScanVerdict(clean=False, engine="fake-ci-scanner", detail="blocked in CI")


@pytest.fixture()
def db_factory(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "files.sqlite3"), connect_args={"check_same_thread": False})
    core.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([core.Tenant(id=1, name="Tenant Uno"), core.Tenant(id=2, name="Tenant Dos")])
        db.add_all([
            core.User(id=1, tenant_id=1, email="admin1@example.invalid", password_hash=core.hasher.hash("testpass-one"), role="admin"),
            core.User(id=2, tenant_id=2, email="admin2@example.invalid", password_hash=core.hasher.hash("testpass-two"), role="admin"),
        ])
        db.add_all([
            core.Document(id=100, tenant_id=1, title="Documento Uno", subject_type="company", subject_name="Empresa Uno", expires_on=date.today()),
            core.Document(id=200, tenant_id=2, title="Documento Dos", subject_type="company", subject_name="Empresa Dos", expires_on=date.today()),
        ])
        db.commit()
    return factory


def make_gateway(tmp_path, scanner=None):
    store = EncryptedLocalStore(tmp_path / "objects", Fernet.generate_key().decode())
    return SecureDocumentGateway(store, scanner or CleanScanner())


def test_file_versions_are_immutable_numbered_and_audited(db_factory, tmp_path):
    gateway = make_gateway(tmp_path)
    with db_factory() as db:
        user = db.get(core.User, 1)
        first = store_new_file_version(
            db, user, 100, gateway, "demo-v1.pdf", "application/pdf", b"%PDF-1.7\nversion one"
        )
        second = store_new_file_version(
            db, user, 100, gateway, "demo-v2.pdf", "application/pdf", b"%PDF-1.7\nversion two"
        )
        assert first.version == 1
        assert second.version == 2
        assert first.object_key != second.object_key
        assert first.scan_engine == "fake-ci-scanner"

        history = list_file_versions(db, user, 100)
        assert [row["version"] for row in history] == [2, 1]
        assert history[0]["original_name"] == "demo-v2.pdf"

        data = read_file_version(db, user, 100, 1, gateway)
        assert data == b"%PDF-1.7\nversion one"

        actions = [row.action for row in db.scalars(select(core.Audit).where(core.Audit.tenant_id == 1)).all()]
        assert actions.count("document.file_version_create") == 2
        assert "document.file_history_read" in actions
        assert "document.file_version_read" in actions


def test_other_tenant_cannot_list_or_read_versions(db_factory, tmp_path):
    gateway = make_gateway(tmp_path)
    with db_factory() as db:
        owner = db.get(core.User, 1)
        other = db.get(core.User, 2)
        store_new_file_version(
            db, owner, 100, gateway, "demo.pdf", "application/pdf", b"%PDF-1.7\nsecret fictitious bytes"
        )
        with pytest.raises(Exception) as list_error:
            list_file_versions(db, other, 100)
        assert getattr(list_error.value, "status_code", None) == 404
        with pytest.raises(Exception) as read_error:
            read_file_version(db, other, 100, 1, gateway)
        assert getattr(read_error.value, "status_code", None) == 404


def test_blocked_scan_creates_no_database_record_or_object(db_factory, tmp_path):
    gateway = make_gateway(tmp_path, BlockScanner())
    with db_factory() as db:
        user = db.get(core.User, 1)
        with pytest.raises(GatewayError, match="blocked in CI"):
            store_new_file_version(
                db, user, 100, gateway, "blocked.pdf", "application/pdf", b"%PDF-1.7\nblocked"
            )
        assert db.scalars(select(DocumentFileVersion)).all() == []
        assert list(gateway.store.root.rglob("*.bin")) == []


def test_metadata_integrity_mismatch_blocks_read(db_factory, tmp_path):
    gateway = make_gateway(tmp_path)
    with db_factory() as db:
        user = db.get(core.User, 1)
        row = store_new_file_version(
            db, user, 100, gateway, "demo.pdf", "application/pdf", b"%PDF-1.7\nintegrity"
        )
        row.sha256 = "0" * 64
        db.commit()
        with pytest.raises(GatewayError, match="metadata integrity"):
            read_file_version(db, user, 100, 1, gateway)


def test_unknown_document_does_not_leave_orphaned_object(db_factory, tmp_path):
    gateway = make_gateway(tmp_path)
    with db_factory() as db:
        user = db.get(core.User, 1)
        with pytest.raises(Exception) as exc:
            store_new_file_version(
                db, user, 999, gateway, "demo.pdf", "application/pdf", b"%PDF-1.7\nunknown doc"
            )
        assert getattr(exc.value, "status_code", None) == 404
        assert list(gateway.store.root.rglob("*.bin")) == []
