from cryptography.fernet import Fernet
import pytest

from file_gateway import GatewayError, ScanVerdict, SecureDocumentGateway
from storage import EncryptedLocalStore


class CleanScanner:
    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        return ScanVerdict(clean=True, engine="fake-ci-scanner")


class BlockScanner:
    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        return ScanVerdict(clean=False, engine="fake-ci-scanner", detail="Fictitious malware signature")


class BrokenScanner:
    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        raise RuntimeError("scanner offline")


class InvalidScanner:
    def scan(self, data: bytes, media_type: str):
        return {"clean": True}


def make_store(tmp_path):
    return EncryptedLocalStore(tmp_path / "objects", Fernet.generate_key().decode())


def test_clean_file_is_stored_only_after_scan(tmp_path):
    store = make_store(tmp_path)
    gateway = SecureDocumentGateway(store, CleanScanner())
    payload = b"%PDF-1.7\n% fictitious clean file\n%%EOF"
    obj = gateway.ingest(1, "demo.pdf", "application/pdf", payload)
    assert store.exists(1, obj.object_key)
    assert store.get(1, obj.object_key) == payload


def test_blocked_file_is_never_written(tmp_path):
    store = make_store(tmp_path)
    gateway = SecureDocumentGateway(store, BlockScanner())
    with pytest.raises(GatewayError, match="Fictitious malware signature"):
        gateway.ingest(1, "demo.pdf", "application/pdf", b"%PDF-1.7\nDEMO")
    assert list(store.root.rglob("*.bin")) == []


def test_scanner_failure_fails_closed_without_storage(tmp_path):
    store = make_store(tmp_path)
    gateway = SecureDocumentGateway(store, BrokenScanner())
    with pytest.raises(GatewayError, match="scanner unavailable"):
        gateway.ingest(1, "demo.pdf", "application/pdf", b"%PDF-1.7\nDEMO")
    assert list(store.root.rglob("*.bin")) == []


def test_invalid_scanner_response_fails_closed(tmp_path):
    store = make_store(tmp_path)
    gateway = SecureDocumentGateway(store, InvalidScanner())
    with pytest.raises(GatewayError, match="Invalid malware scanner response"):
        gateway.ingest(1, "demo.pdf", "application/pdf", b"%PDF-1.7\nDEMO")
    assert list(store.root.rglob("*.bin")) == []


def test_payload_validation_happens_before_scanner(tmp_path):
    class CountingScanner:
        calls = 0
        def scan(self, data: bytes, media_type: str) -> ScanVerdict:
            self.calls += 1
            return ScanVerdict(clean=True, engine="fake")

    scanner = CountingScanner()
    gateway = SecureDocumentGateway(make_store(tmp_path), scanner)
    with pytest.raises(GatewayError, match="signature"):
        gateway.ingest(1, "fake.pdf", "application/pdf", b"not-a-pdf")
    assert scanner.calls == 0


def test_invalid_tenant_is_rejected_before_scan(tmp_path):
    gateway = SecureDocumentGateway(make_store(tmp_path), CleanScanner())
    with pytest.raises(GatewayError, match="Invalid tenant"):
        gateway.ingest(0, "demo.pdf", "application/pdf", b"%PDF-1.7\nDEMO")
