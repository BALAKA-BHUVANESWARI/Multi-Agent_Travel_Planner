"""Small helpers every router needs."""
from __future__ import annotations

from fastapi import Request


def bearer(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def client_of(request: Request) -> str:
    return request.client.host if request.client else ""     # X-Forwarded-For is not trusted: it can be faked
