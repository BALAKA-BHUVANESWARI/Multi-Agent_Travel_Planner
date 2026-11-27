"""Explore any place by name: its top sights, with pictures."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, Request

from app.api.dependencies import bearer, client_of
from app.services.trip_service import PlannerService


def create_router(service: PlannerService) -> APIRouter:
    router = APIRouter(tags=["explore"])

    @router.post("/explore")
    def explore(request: Request, body: Optional[dict] = Body(None),
                authorization: Optional[str] = Header(None)):
        return service.explore(body, bearer(authorization), client_of(request))

    return router
