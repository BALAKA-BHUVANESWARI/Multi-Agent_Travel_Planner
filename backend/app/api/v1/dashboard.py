"""The evaluation dashboard (read-only, behind its own password)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import bearer, client_of
from app.services.dashboard_service import DashboardService
from app.services.trip_service import PlannerService

NO_STORE = {"Cache-Control": "no-store"}


def create_router(service: PlannerService) -> APIRouter:
    router = APIRouter(prefix="/dashboard", tags=["dashboard"])
    board = DashboardService(service)

    @router.get("/status")
    def status():
        return JSONResponse(board.status(), headers=NO_STORE)

    @router.post("/login")
    def login(request: Request, body: Optional[dict] = Body(None)):
        return JSONResponse(board.login(body, client_of(request)), headers=NO_STORE)

    @router.post("/logout")
    def logout(authorization: Optional[str] = Header(None)):
        return board.logout(bearer(authorization))

    @router.get("/export")
    def export(request: Request, authorization: Optional[str] = Header(None)):
        body, kind, name = board.export(dict(request.query_params), bearer(authorization))
        return Response(content=body, media_type=kind,
                        headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{name}"'})

    @router.get("/{view:path}")
    def view(view: str, request: Request, authorization: Optional[str] = Header(None)):
        return JSONResponse(board.get(view, dict(request.query_params), bearer(authorization)), headers=NO_STORE)

    return router
