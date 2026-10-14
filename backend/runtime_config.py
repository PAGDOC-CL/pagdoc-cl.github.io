"""Runtime configuration validation for PAGDOC private deployments.

The public demo never imports this module. The private server calls
``assert_safe_runtime`` before registering feature routes so an unsafe production
configuration fails closed instead of silently using development defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.fernet import Fernet


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    database_url: str
    secret_key: str
    encryption_key: str
    public_origin: str


def load_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        environment=os.getenv("PAGDOC_ENVIRONMENT", "development").strip().lower(),
        database_url=os.getenv("PAGDOC_DATABASE_URL", "sqlite:///./pagdoc_dev.sqlite3").strip(),
        secret_key=os.getenv("PAGDOC_SECRET_KEY", ""),
        encryption_key=os.getenv("PAGDOC_ENCRYPTION_KEY", ""),
        public_origin=os.getenv("PAGDOC_PUBLIC_ORIGIN", "").strip(),
    )


def validate_runtime_config(config: RuntimeConfig) -> None:
    if config.environment not in {"development", "test", "staging", "production"}:
        raise RuntimeError("Invalid PAGDOC_ENVIRONMENT")
    if len(config.secret_key) < 32:
        raise RuntimeError("PAGDOC_SECRET_KEY must contain at least 32 characters")
    if not config.encryption_key:
        raise RuntimeError("PAGDOC_ENCRYPTION_KEY is required")
    try:
        Fernet(config.encryption_key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PAGDOC_ENCRYPTION_KEY is invalid") from exc

    if config.environment in {"staging", "production"}:
        if not config.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("Staging and production require PostgreSQL")
        parsed = urlparse(config.public_origin)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("Staging and production require an HTTPS PAGDOC_PUBLIC_ORIGIN")
        if parsed.username or parsed.password:
            raise RuntimeError("PAGDOC_PUBLIC_ORIGIN must not contain credentials")


def assert_safe_runtime() -> RuntimeConfig:
    config = load_runtime_config()
    validate_runtime_config(config)
    return config
