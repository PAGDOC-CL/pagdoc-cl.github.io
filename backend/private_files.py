"""Private runtime factory and fictitious storage/real antivirus diagnostic.

No HTTP upload or download route is registered here. Passing this diagnostic does
not approve actual documents or complete the backup and recovery requirements.
"""
import os
from pathlib import Path

from clamav_scanner import ClamAVScanner
from file_gateway import SecureDocumentGateway
from storage import EncryptedLocalStore


def configured_gateway() -> SecureDocumentGateway:
    root = Path(os.environ.get('PAGDOC_STORAGE_ROOT', ''))
    if not root.is_absolute():
        raise ValueError('Private absolute PAGDOC_STORAGE_ROOT is required')
    source_root = Path(__file__).resolve().parent.parent
    if root.resolve() == source_root or source_root in root.resolve().parents:
        raise ValueError('Private file storage must be outside the source repository')
    scanner = ClamAVScanner(os.environ.get('PAGDOC_CLAMAV_HOST', 'antimalware'))
    return SecureDocumentGateway(EncryptedLocalStore(root, os.environ['PAGDOC_ENCRYPTION_KEY']), scanner)


def self_test() -> None:
    gateway = configured_gateway()
    payload = b'%PDF-1.7\n% PAGDOC fictitious storage diagnostic\n%%EOF'
    result = gateway.ingest(1, 'diagnostico-ficticio.pdf', 'application/pdf', payload)
    try:
        assert gateway.store.get(1, result.stored.object_key) == payload
        stored = gateway.store.root / '1' / (result.stored.object_key + '.bin')
        assert stored.read_bytes() != payload
        assert stored.stat().st_mode & 0o777 == 0o600
        # Standard, inert antivirus test string; never executed or written to disk.
        eicar = b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$' + b'EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
        assert gateway.scanner.scan(eicar, 'application/octet-stream').clean is False
    finally:
        gateway.store.delete(1, result.stored.object_key)
    print('OK: real antimalware clean/reject checks and encrypted private storage round trip. Fictitious object removed. HTTP uploads require explicit private enablement.')


if __name__ == '__main__':
    self_test()
