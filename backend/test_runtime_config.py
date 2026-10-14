import pytest
from cryptography.fernet import Fernet

from runtime_config import RuntimeConfig, validate_runtime_config


KEY = Fernet.generate_key().decode()
SECRET = "x" * 40


def cfg(**overrides):
    values = {
        "environment": "development",
        "database_url": "sqlite:///./pagdoc_dev.sqlite3",
        "secret_key": SECRET,
        "encryption_key": KEY,
        "public_origin": "",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


def test_development_allows_local_sqlite():
    validate_runtime_config(cfg())


def test_unknown_environment_is_rejected():
    with pytest.raises(RuntimeError, match="Invalid PAGDOC_ENVIRONMENT"):
        validate_runtime_config(cfg(environment="prod-ish"))


def test_short_secret_is_rejected():
    with pytest.raises(RuntimeError, match="at least 32"):
        validate_runtime_config(cfg(secret_key="short"))


def test_invalid_encryption_key_is_rejected():
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is invalid"):
        validate_runtime_config(cfg(encryption_key="not-a-fernet-key"))


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_non_postgres_database_is_rejected_for_private_deployment(environment):
    with pytest.raises(RuntimeError, match="require PostgreSQL"):
        validate_runtime_config(
            cfg(environment=environment, public_origin="https://pagdoc.example.invalid")
        )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_https_origin_is_required_for_private_deployment(environment):
    with pytest.raises(RuntimeError, match="HTTPS"):
        validate_runtime_config(
            cfg(
                environment=environment,
                database_url="postgresql+psycopg://user:pass@db/pagdoc",
                public_origin="http://pagdoc.example.invalid",
            )
        )


def test_safe_production_shape_is_accepted():
    validate_runtime_config(
        cfg(
            environment="production",
            database_url="postgresql+psycopg://user:pass@db/pagdoc",
            public_origin="https://pagdoc.example.invalid",
        )
    )


def test_origin_must_not_embed_credentials():
    with pytest.raises(RuntimeError, match="must not contain credentials"):
        validate_runtime_config(
            cfg(
                environment="production",
                database_url="postgresql+psycopg://user:pass@db/pagdoc",
                public_origin="https://user:pass@pagdoc.example.invalid",
            )
        )
