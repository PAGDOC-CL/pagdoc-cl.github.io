"""PAGDOC private application entrypoint.

Importing feature modules registers tenant-scoped routes on the core FastAPI
application before the server starts.
"""
import app as core
import document_history  # noqa: F401
import requirements_api  # noqa: F401
import alerts_api  # noqa: F401

app = core.app
