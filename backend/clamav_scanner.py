"""Bounded ClamD INSTREAM client; unexpected, stale or unavailable scans fail closed."""
from __future__ import annotations

import re
import socket
import struct
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from file_gateway import ScanVerdict
from storage import MAX_BYTES


class ScannerUnavailable(ValueError):
    pass


class ClamAVScanner:
    def __init__(self, host: str, port: int = 3310, *, timeout: float = 60):
        if not host or not 1 <= port <= 65535 or not 0 < timeout <= 120:
            raise ValueError("Invalid scanner configuration")
        self.host, self.port, self.timeout = host, port, timeout

    def _exchange(self, command: bytes, payload: bytes | None = None) -> str:
        deadline = time.monotonic() + self.timeout
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                def send(data):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ScannerUnavailable("Antimalware deadline exceeded")
                    conn.settimeout(remaining)
                    conn.sendall(data)
                send(command)
                if payload is not None:
                    for offset in range(0, len(payload), 65536):
                        chunk = payload[offset:offset + 65536]
                        send(struct.pack('!I', len(chunk)) + chunk)
                    send(struct.pack('!I', 0))
                reply = bytearray()
                while b'\0' not in reply:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ScannerUnavailable("Antimalware deadline exceeded")
                    conn.settimeout(remaining)
                    block = conn.recv(1024)
                    if not block:
                        raise ScannerUnavailable("Incomplete antimalware response")
                    reply.extend(block)
                    if len(reply) > 4096:
                        raise ScannerUnavailable("Antimalware response exceeds limit")
                value, extra = bytes(reply).split(b'\0', 1)
                if extra:
                    raise ScannerUnavailable("Unexpected antimalware response")
                return value.decode('ascii', errors='strict')
        except (OSError, UnicodeError) as exc:
            raise ScannerUnavailable("Antimalware unavailable") from exc

    def engine(self) -> str:
        version = self._exchange(b'zVERSION\0')
        # VERSION contains the loaded daily database serial and build date.
        match = re.fullmatch(r'ClamAV ([0-9]+\.[0-9]+\.[0-9]+[^/]*)/([0-9]+)/(.+)', version)
        if not match:
            raise ScannerUnavailable("Antimalware signature database not verified")
        try:
            timestamp = parsedate_to_datetime(match[3])
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ScannerUnavailable("Invalid antimalware signature date") from exc
        age = datetime.now(timezone.utc) - timestamp
        if age > timedelta(days=7) or age < -timedelta(days=1):
            raise ScannerUnavailable("Antimalware signatures are stale or clock is incorrect")
        return version[:120]

    def scan(self, data: bytes, media_type: str) -> ScanVerdict:
        if not data or len(data) > MAX_BYTES:
            raise ScannerUnavailable("Invalid antimalware payload size")
        engine = self.engine()
        reply = self._exchange(b'zINSTREAM\0', data)
        if reply == 'stream: OK':
            return ScanVerdict(clean=True, engine=engine)
        if re.fullmatch(r'stream: [^\r\n]+ FOUND', reply):
            return ScanVerdict(clean=False, engine=engine, detail="Archivo rechazado por el análisis antimalware")
        raise ScannerUnavailable("Antimalware did not confirm a complete clean scan")
