"""Encrypted document storage prototype for PAGDOC.

This component is deliberately NOT wired to the public API. It is intended for
local/CI validation with fictitious files until private object storage and an
antimalware scanner are available.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

MAX_BYTES = int(os.getenv("PAGDOC_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")

SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}
EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


class StorageError(ValueError):
    pass


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    original_name: str
    media_type: str
    size: int
    sha256: str


def clean_display_name(name: str) -> str:
    value = Path(name).name.strip()
    value = SAFE_NAME.sub("_", value)
    value = value[:160]
    return value or "document"


def validate_payload(data: bytes, media_type: str) -> None:
    if not data:
        raise StorageError("Empty files are not allowed")
    if len(data) > MAX_BYTES:
        raise StorageError("File exceeds size limit")
    signatures = SIGNATURES.get(media_type)
    if not signatures:
        raise StorageError("Unsupported file type")
    if not any(data.startswith(signature) for signature in signatures):
        raise StorageError("File signature does not match media type")
    lowered = data[:4096].lower()
    if b"<script" in lowered or b"javascript:" in lowered:
        raise StorageError("Active content marker rejected")


class EncryptedLocalStore:
    def __init__(self, root: Path, encryption_key: str):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.cipher = Fernet(encryption_key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise StorageError("Invalid encryption key") from exc

    def _path(self, tenant_id: int, object_key: str) -> Path:
        if tenant_id <= 0 or not re.fullmatch(r"[0-9a-f]{32}", object_key):
            raise StorageError("Invalid storage identifier")
        path = (self.root / str(tenant_id) / f"{object_key}.bin").resolve()
        if self.root not in path.parents:
            raise StorageError("Unsafe storage path")
        return path

    def put(self, tenant_id: int, original_name: str, media_type: str, data: bytes) -> StoredObject:
        validate_payload(data, media_type)
        object_key = uuid.uuid4().hex
        path = self._path(tenant_id, object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self.cipher.encrypt(data)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(encrypted)
        os.replace(tmp, path)
        return StoredObject(
            object_key=object_key,
            original_name=clean_display_name(original_name),
            media_type=media_type,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def get(self, tenant_id: int, object_key: str) -> bytes:
        path = self._path(tenant_id, object_key)
        if not path.is_file():
            raise StorageError("Object not found")
        try:
            return self.cipher.decrypt(path.read_bytes())
        except InvalidToken as exc:
            raise StorageError("Stored object integrity check failed") from exc

    def delete(self, tenant_id: int, object_key: str) -> None:
        path = self._path(tenant_id, object_key)
        if path.exists():
            path.unlink()

    def exists(self, tenant_id: int, object_key: str) -> bool:
        return self._path(tenant_id, object_key).is_file()
