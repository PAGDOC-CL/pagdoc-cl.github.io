"""PAGDOC private application entrypoint.

Importing requirements_api registers tenant-scoped requirement and alert routes
on the core FastAPI application before the server starts.
"""
import app as core
import requirements_api  # noqa: F401

app = core.app
