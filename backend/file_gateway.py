"""Fail-closed document ingestion gateway for PAGDOC.

The gateway is intentionally not exposed as an HTTP endpoint. A file is written
to encrypted storage only after payload validation and an injected malware scanner
returns a clean verdict. Production must provide a real scanner implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from storage import EncryptedLocalStore, StoredObject, StorageError, validate_payload


class GatewayError(ValueError):
    pass


@dataclass(frozen=True)
class ScanVerdict:
    clean: bool
    engine: str
    detail: str = ""


@dataclass(frozen=True)
class IngestResult:
    stored: StoredObject
    scan: ScanVerdict


class MalwareScanner(Protocol):
    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        """Return a verdict for the exact bytes that would be stored."""
        ...


class SecureDocumentGateway:
    def __init__(self, store: EncryptedLocalStore, scanner: MalwareScanner):
        self.store = store
        self.scanner = scanner

    def ingest(
        self,
        tenant_id: int,
        original_name: str,
        media_type: str,
        data: bytes,
    ) -> IngestResult:
        if tenant_id <= 0:
            raise GatewayError("Invalid tenant")

        try:
            validate_payload(data, media_type)
        except StorageError as exc:
            raise GatewayError(str(exc)) from exc

        try:
            verdict = self.scanner.scan(data, media_type)
        except Exception as exc:  # scanner failures must never fail open
            raise GatewayError("Malware scanner unavailable") from exc

        if not isinstance(verdict, ScanVerdict):
            raise GatewayError("Invalid malware scanner response")
        if not verdict.clean:
            detail = verdict.detail.strip() or "File rejected by malware scanner"
            raise GatewayError(detail)

        try:
            stored = self.store.put(tenant_id, original_name, media_type, data)
        except StorageError as exc:
            raise GatewayError(str(exc)) from exc
        return IngestResult(stored=stored, scan=verdict)
