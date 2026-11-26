"""The trip toolkit (companion, emergency, documents, footprint, expenses) and emergency help."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, Request

from app.api.dependencies import bearer, client_of
from app.services.trip_service import PlannerService


def create_router(service: PlannerService) -> APIRouter:
    router = APIRouter(tags=["toolkit"])

    @router.post("/emergency")
    def emergency(request: Request, body: Optional[dict] = Body(None),
                  authorization: Optional[str] = Header(None)):
        return service.emergency(body, bearer(authorization), client_of(request))

    def add_trip_routes(method: str) -> None:
        def tool_view(request: Request, thread_id: str, tool: str, body: Optional[dict] = Body(None),
                      authorization: Optional[str] = Header(None)):
            return service.trip_tool(method, thread_id, tool, None, body, bearer(authorization),
                                     client_of(request))

        def tool_item(request: Request, thread_id: str, tool: str, item_id: str,
                      body: Optional[dict] = Body(None), authorization: Optional[str] = Header(None)):
            return service.trip_tool(method, thread_id, tool, item_id, body, bearer(authorization),
                                     client_of(request))

        router.add_api_route("/trip/{thread_id}/{tool}", tool_view, methods=[method],
                             name=f"{method.lower()}_trip_tool")
        router.add_api_route("/trip/{thread_id}/{tool}/{item_id}", tool_item, methods=[method],
                             name=f"{method.lower()}_trip_item")

    for method in ("GET", "POST", "DELETE"):
        add_trip_routes(method)
    return router
