"""PAGDOC private application entrypoint.

The private server validates its runtime configuration before importing the core
application. Audit sealing is installed before feature modules register routes.
"""
from runtime_config import assert_safe_runtime

RUNTIME_CONFIG = assert_safe_runtime()

import app as core  # noqa: E402
import audit_integrity  # noqa: E402

audit_integrity.install()

import document_history  # noqa: E402,F401
import requirements_api  # noqa: E402,F401
import alerts_api  # noqa: E402,F401
import ops_api  # noqa: E402,F401
import query_api  # noqa: E402,F401
import retention_api  # noqa: E402,F401
import operations_api  # noqa: E402,F401
import file_api  # noqa: E402,F401
import document_analysis  # noqa: E402,F401
import document_preview  # noqa: E402,F401
import email_alerts  # noqa: E402,F401
import password_api  # noqa: E402,F401
import onboarding_api  # noqa: E402,F401
import integration_status  # noqa: E402,F401
import private_ui  # noqa: E402,F401
import telemetry  # noqa: E402,F401
import security_hardening  # noqa: E402,F401

app = core.app
