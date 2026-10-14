"""Additional response hardening for the PAGDOC private API."""
from fastapi import Request

import app as core
from runtime_config import load_runtime_config


@core.app.middleware("http")
async def hardened_api_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    if load_runtime_config().environment in {"staging", "production"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
