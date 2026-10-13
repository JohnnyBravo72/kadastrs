"""Optional Bearer-token gate (Phase 10, D3).

When ``KADASTRS_AUTH_TOKEN`` is unset or empty, the API stays open (local Docker
default). When set, every request except ``GET /health`` must send
``Authorization: Bearer <token>``. Required before any shared hosting.
"""

from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def auth_token() -> str | None:
    value = (os.environ.get("KADASTRS_AUTH_TOKEN") or "").strip()
    return value or None


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        token = auth_token()
        if token is None:
            return await call_next(request)
        if request.url.path == "/health" and request.method in ("GET", "HEAD"):
            return await call_next(request)
        header = request.headers.get("authorization") or ""
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not presented:
            return JSONResponse(
                {"detail": "nepieciešama autentifikācija (Authorization: Bearer …)"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(presented.strip(), token):
            return JSONResponse(
                {"detail": "nederīgs autentifikācijas tokens"},
                status_code=403,
            )
        return await call_next(request)
