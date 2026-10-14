"""Fail CI if high-risk private artifacts or common secret formats enter the public repo.

This is a guardrail, not a complete secret scanner. It intentionally uses precise
patterns to avoid treating ordinary test data as credentials.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BLOCKED_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".sqlite", ".sqlite3", ".db",
    ".pem", ".p12", ".pfx", ".key", ".keystore", ".jks",
}
BLOCKED_FILENAMES = {".env", "id_rsa", "id_ed25519"}
CONTENT_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root)
        if path.name in BLOCKED_FILENAMES or path.suffix.lower() in BLOCKED_SUFFIXES:
            findings.append(f"blocked artifact: {rel}")
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in CONTENT_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"possible {label}: {rel}")
    return findings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    findings = scan(root)
    if findings:
        print("PAGDOC public repository guard failed:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("PAGDOC public repository guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
