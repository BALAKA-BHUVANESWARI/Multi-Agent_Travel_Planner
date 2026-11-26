"""Optional local accounts: sign in, saved preferences and "my trips"."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, Request

from app.api.dependencies import bearer, client_of
from app.services.trip_service import PlannerService

ROUTES = (("POST", "auth/register"), ("POST", "auth/login"), ("POST", "auth/logout"), ("GET", "me"),
          ("DELETE", "me"), ("PUT", "me/memory"), ("DELETE", "me/memory"), ("GET", "trips"))


def create_router(service: PlannerService) -> APIRouter:
    router = APIRouter(tags=["accounts"])

    def add_route(method: str, path: str) -> None:
        def handler(request: Request, body: Optional[dict] = Body(None),
                    authorization: Optional[str] = Header(None)):
            return service.account(method, path, body, bearer(authorization), client_of(request))
        router.add_api_route(f"/{path}", handler, methods=[method], name=f"{method.lower()}_{path}")

    for method, path in ROUTES:
        add_route(method, path)
    return router
