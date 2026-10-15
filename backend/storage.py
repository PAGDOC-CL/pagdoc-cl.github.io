"""Encrypted private storage with bounded type validation, isolated from public Pages."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
import io
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

MAX_BYTES = int(os.getenv("PAGDOC_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
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
OFFICE_TYPES = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ('word/document.xml', '.docx'),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ('xl/workbook.xml', '.xlsx'),
}
for _media, (_part, _extension) in OFFICE_TYPES.items():
    SIGNATURES[_media] = (b'PK\x03\x04',)
    EXTENSIONS[_media] = _extension


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
    if media_type in OFFICE_TYPES:
        validate_office(data, media_type)


def validate_office(data: bytes, media_type: str) -> None:
    """Bound expansion; reject encrypted packages, macros and embedded active content."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            required = {'[Content_Types].xml', '_rels/.rels', OFFICE_TYPES[media_type][0]}
            if len(entries) > 2000 or len(names) != len(entries) or not required <= names:
                raise StorageError('Invalid Word/Excel package')
            if sum(e.file_size for e in entries) > 64 * 1024 * 1024:
                raise StorageError('Word/Excel expansion exceeds limit')
            for entry in entries:
                name = entry.filename.replace('\\', '/').lower()
                parts = name.split('/')
                if name.startswith('/') or '..' in parts or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                    raise StorageError('Unsafe Word/Excel package')
                if entry.file_size > 32 * 1024 * 1024 or entry.file_size > max(entry.compress_size, 1) * 200:
                    raise StorageError('Word/Excel compression limit exceeded')
                if any(p in {'embeddings', 'activex'} for p in parts) or 'vbaproject' in name or name.endswith(('.exe','.dll','.js','.vbs','.ps1','.docm','.xlsm')):
                    raise StorageError('Macros or embedded active content are not accepted')
                if not entry.is_dir():
                    body = archive.read(entry)  # CRC and encrypted-member validation.
                    if name.endswith(('.xml', '.rels')) and (b'<!doctype' in body.lower() or b'<!entity' in body.lower() or b'macroenabled' in body.lower()):
                        raise StorageError('Unsafe XML or macro-enabled content')
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError) as exc:
        raise StorageError('Invalid Word/Excel package') from exc


class EncryptedLocalStore:
    def __init__(self, root: Path, encryption_key: str):
        if root.is_symlink():
            raise StorageError("Storage root must not be a symbolic link")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_mode & 0o077:
            raise StorageError("Storage root must have private permissions")
        try:
            self.cipher = Fernet(encryption_key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise StorageError("Invalid encryption key") from exc

    def _path(self, tenant_id: int, object_key: str) -> Path:
        if tenant_id <= 0 or not re.fullmatch(r"[0-9a-f]{32}", object_key):
            raise StorageError("Invalid storage identifier")
        tenant = self.root / str(tenant_id)
        path = tenant / f"{object_key}.bin"
        if tenant.is_symlink() or path.is_symlink():
            raise StorageError("Symbolic links are not allowed in private storage")
        path = path.resolve()
        if self.root not in path.parents:
            raise StorageError("Unsafe storage path")
        return path

    def put(self, tenant_id: int, original_name: str, media_type: str, data: bytes) -> StoredObject:
        validate_payload(data, media_type)
        object_key = uuid.uuid4().hex
        path = self._path(tenant_id, object_key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.stat().st_mode & 0o077:
            raise StorageError("Tenant storage must have private permissions")
        encrypted = self.cipher.encrypt(data)
        tmp = path.with_suffix(".tmp")
        created = False
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created = True
            with os.fdopen(fd, 'wb') as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            os.replace(tmp, path)
        finally:
            if created and tmp.exists() and not tmp.is_symlink():
                tmp.unlink()
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
