import socketserver
import struct
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from clamav_scanner import ClamAVScanner, ScannerUnavailable
from file_gateway import GatewayError, SecureDocumentGateway
from storage import EncryptedLocalStore


@contextmanager
def daemon(*, verdict=b'stream: OK\0', age_days=0, version=None):
    streams, commands = [], []
    date = datetime.now(timezone.utc) - timedelta(days=age_days)
    version = version if version is not None else ('ClamAV 1.4.9/99999/' + date.strftime('%a %b %d %H:%M:%S %Y')).encode() + b'\0'
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            command = bytearray()
            while not command.endswith(b'\0'):
                chunk = self.rfile.read(1)
                if not chunk:
                    return
                command.extend(chunk)
            commands.append(bytes(command))
            if command == b'zVERSION\0':
                self.wfile.write(version)
            elif command == b'zINSTREAM\0':
                data = bytearray()
                while True:
                    size = struct.unpack('!I', self.rfile.read(4))[0]
                    if not size:
                        break
                    data.extend(self.rfile.read(size))
                streams.append(bytes(data))
                self.wfile.write(verdict)
    with socketserver.TCPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield ClamAVScanner('127.0.0.1', server.server_address[1], timeout=1), streams, commands
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_streams_exact_chunks_and_requires_clean_verdict():
    payload = b'%PDF-1.7\n' + b'fictitious-data' * 10000
    with daemon() as (scanner, streams, commands):
        verdict = scanner.scan(payload, 'application/pdf')
        assert verdict.clean
        assert verdict.engine.startswith('ClamAV ')
        assert streams == [payload]
        assert commands == [b'zVERSION\0', b'zINSTREAM\0']


def test_detected_content_is_never_written(tmp_path):
    store = EncryptedLocalStore(tmp_path / 'private', Fernet.generate_key().decode())
    with daemon(verdict=b'stream: Fictitious.Test FOUND\0') as (scanner, _, _):
        with pytest.raises(GatewayError, match='rechazado'):
            SecureDocumentGateway(store, scanner).ingest(1, 'ficticio.pdf', 'application/pdf', b'%PDF-1.7\nfictional')
    assert not list(store.root.rglob('*.bin'))


@pytest.mark.parametrize('reply', [b'stream: ERROR\0', b'OK\0', b'', b'stream: OK', b'x' * 5000 + b'\0', b'stream: OK\0extra'])
def test_unknown_truncated_and_oversized_responses_never_pass(reply):
    with daemon(verdict=reply) as (scanner, _, _):
        with pytest.raises(ScannerUnavailable):
            scanner.scan(b'%PDF-1.7\nfictional', 'application/pdf')


@pytest.mark.parametrize('age', [8, -2])
def test_stale_or_future_signatures_rejected_before_streaming(age):
    with daemon(age_days=age) as (scanner, streams, _):
        with pytest.raises(ScannerUnavailable, match='stale or clock'):
            scanner.scan(b'fictional', 'application/pdf')
        assert streams == []


@pytest.mark.parametrize('version', [b'ClamAV 1.4.9\0', b'ClamAV 1.4.9/1/not-a-date\0', b'UNKNOWN COMMAND\0'])
def test_missing_or_invalid_loaded_signature_database_rejected(version):
    with daemon(version=version) as (scanner, streams, _):
        with pytest.raises(ScannerUnavailable):
            scanner.scan(b'fictional', 'application/pdf')
        assert streams == []


def test_disconnected_scanner_never_stores(tmp_path):
    store = EncryptedLocalStore(tmp_path / 'private', Fernet.generate_key().decode())
    with socketserver.TCPServer(('127.0.0.1', 0), socketserver.BaseRequestHandler) as server:
        port = server.server_address[1]
    scanner = ClamAVScanner('127.0.0.1', port, timeout=0.1)
    with pytest.raises(GatewayError, match='scanner unavailable'):
        SecureDocumentGateway(store, scanner).ingest(1, 'ficticio.pdf', 'application/pdf', b'%PDF-1.7\nfictional')
    assert not list(store.root.rglob('*.bin'))


def test_runtime_factory_requires_private_location(tmp_path, monkeypatch):
    from private_files import configured_gateway
    monkeypatch.setenv('PAGDOC_STORAGE_ROOT', 'relative')
    with pytest.raises(ValueError, match='absolute'):
        configured_gateway()
    monkeypatch.setenv('PAGDOC_STORAGE_ROOT', str(__import__('pathlib').Path(__file__).resolve().parent))
    with pytest.raises(ValueError, match='outside'):
        configured_gateway()
