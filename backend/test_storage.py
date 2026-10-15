from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import storage


@pytest.fixture()
def store(tmp_path):
    return storage.EncryptedLocalStore(tmp_path / "objects", Fernet.generate_key().decode())


def test_pdf_round_trip_is_encrypted_on_disk(store):
    data = b"%PDF-1.7\n% fictitious CI document\n%%EOF"
    obj = store.put(1, "../Contrato DEMO.pdf", "application/pdf", data)
    assert obj.original_name == "Contrato DEMO.pdf"
    assert obj.size == len(data)
    assert obj.sha256
    raw_path = store.root / "1" / f"{obj.object_key}.bin"
    assert raw_path.exists()
    assert raw_path.read_bytes() != data
    assert store.get(1, obj.object_key) == data


def test_png_and_jpeg_signatures_are_accepted(store):
    png = store.put(1, "foto.png", "image/png", b"\x89PNG\r\n\x1a\nFAKE")
    jpg = store.put(1, "foto.jpg", "image/jpeg", b"\xff\xd8\xffFAKE")
    assert store.get(1, png.object_key).startswith(b"\x89PNG")
    assert store.get(1, jpg.object_key).startswith(b"\xff\xd8\xff")


def test_unsupported_type_is_rejected(store):
    with pytest.raises(storage.StorageError):
        store.put(1, "macro.docm", "application/vnd.ms-word", b"MZ")


def test_mismatched_signature_is_rejected(store):
    with pytest.raises(storage.StorageError):
        store.put(1, "fake.pdf", "application/pdf", b"not-a-pdf")


def test_empty_file_is_rejected(store):
    with pytest.raises(storage.StorageError):
        store.put(1, "empty.pdf", "application/pdf", b"")


def test_active_content_marker_is_rejected(store):
    with pytest.raises(storage.StorageError):
        store.put(1, "bad.pdf", "application/pdf", b"%PDF-1.7\n<script>alert(1)</script>")


def test_size_limit_is_enforced(store, monkeypatch):
    monkeypatch.setattr(storage, "MAX_BYTES", 10)
    with pytest.raises(storage.StorageError):
        store.put(1, "large.pdf", "application/pdf", b"%PDF-" + b"x" * 20)


def test_tenant_cannot_read_other_tenant_object(store):
    obj = store.put(1, "demo.pdf", "application/pdf", b"%PDF-1.7\nDEMO")
    with pytest.raises(storage.StorageError):
        store.get(2, obj.object_key)


def test_invalid_object_identifier_is_rejected(store):
    with pytest.raises(storage.StorageError):
        store.get(1, "../../secret")


def test_delete_removes_object(store):
    obj = store.put(1, "demo.pdf", "application/pdf", b"%PDF-1.7\nDEMO")
    assert store.exists(1, obj.object_key)
    store.delete(1, obj.object_key)
    assert not store.exists(1, obj.object_key)


def test_private_file_and_directory_permissions(store):
    obj = store.put(1, 'ficticio.pdf', 'application/pdf', b'%PDF-1.7\nfictional')
    assert store.root.stat().st_mode & 0o777 == 0o700
    assert (store.root / '1').stat().st_mode & 0o777 == 0o700
    assert (store.root / '1' / (obj.object_key + '.bin')).stat().st_mode & 0o777 == 0o600


def test_shared_storage_directory_is_rejected(tmp_path):
    root = tmp_path / 'shared'
    root.mkdir(mode=0o755)
    with pytest.raises(storage.StorageError, match='private permissions'):
        storage.EncryptedLocalStore(root, Fernet.generate_key().decode())


def test_tenant_symlink_cannot_alias_another_tenant(store):
    obj = store.put(1, 'ficticio.pdf', 'application/pdf', b'%PDF-1.7\nfictional')
    (store.root / '2').symlink_to(store.root / '1', target_is_directory=True)
    with pytest.raises(storage.StorageError, match='Symbolic links'):
        store.get(2, obj.object_key)


def test_object_symlinks_are_rejected(store):
    obj = store.put(1, 'ficticio.pdf', 'application/pdf', b'%PDF-1.7\nfictional')
    alias = 'a' * 32
    (store.root / '1' / (alias + '.bin')).symlink_to(store.root / '1' / (obj.object_key + '.bin'))
    with pytest.raises(storage.StorageError, match='Symbolic links'):
        store.get(1, alias)
