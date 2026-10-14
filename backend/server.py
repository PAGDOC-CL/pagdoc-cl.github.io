"""PAGDOC private application entrypoint.

The private server validates its runtime configuration before importing the core
application. Feature modules then register tenant-scoped routes.
"""
from runtime_config import assert_safe_runtime

RUNTIME_CONFIG = assert_safe_runtime()

import app as core  # noqa: E402
import document_history  # noqa: E402,F401
import requirements_api  # noqa: E402,F401
import alerts_api  # noqa: E402,F401

app = core.app
