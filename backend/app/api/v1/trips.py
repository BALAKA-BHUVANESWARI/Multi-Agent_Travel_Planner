"""Planning, approving, reading and cancelling trips."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Request

from app.api.dependencies import bearer, client_of
from app.schemas.requests import ApproveRequest, CancelRequest, PlanRequest
from app.services.trip_service import PlannerService


def create_router(service: PlannerService) -> APIRouter:
    router = APIRouter(tags=["trips"])

    @router.post("/plan")
    def plan(body: PlanRequest, request: Request, authorization: Optional[str] = Header(None)):
        return service.plan(body.request, body.group, bearer(authorization), client_of(request))

    @router.post("/approve/{thread_id}")
    def approve(thread_id: str, body: ApproveRequest, request: Request,
                authorization: Optional[str] = Header(None)):
        return service.approve(thread_id, body.model_dump(), bearer(authorization), client_of(request))

    @router.get("/plan/{thread_id}")
    def get_plan(thread_id: str, request: Request, authorization: Optional[str] = Header(None)):
        return service.get(thread_id, bearer(authorization), client_of(request))

    @router.post("/booking/{thread_id}/cancel")
    def cancel_booking(thread_id: str, body: CancelRequest, request: Request,
                       authorization: Optional[str] = Header(None)):
        return service.cancel_booking(thread_id, body.model_dump(), bearer(authorization), client_of(request))

    return router
