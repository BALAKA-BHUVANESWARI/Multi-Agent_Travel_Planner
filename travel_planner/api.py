"""FastAPI app.

    uvicorn travel_planner.api:create_app --factory --reload

Endpoints (the stdlib devserver exposes the identical API if FastAPI is not installed):
POST /api/plan, POST /api/approve/{thread_id}, GET /api/plan/{thread_id}, GET /api/health,
POST /api/booking/{thread_id}/cancel, POST /api/auth/register|login|logout, GET|DELETE /api/me,
PUT|DELETE /api/me/memory, GET /api/trips,
POST /api/emergency, GET|POST|DELETE /api/trip/{thread_id}/{companion|emergency|documents|footprint|expenses}.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import config
from .engine import make_planner
from .ratelimit import RateLimiter
from .service import ApiError, PlannerService

STATIC = Path(__file__).parent / "static"


class PlanRequest(BaseModel):
    request: str = Field(..., max_length=5000)
    group: Optional[list] = Field(None, max_length=config.MAX_TRAVELERS)


class ApproveRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|revise|cancel)$")
    feedback: str = Field("", max_length=config.MAX_REQUEST_CHARS)


class CancelRequest(BaseModel):
    confirm: bool = False


def bearer(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def client_of(request: Request) -> str:
    return request.client.host if request.client else ""     # X-Forwarded-For is not trusted: it can be faked


def create_app(service: PlannerService | None = None) -> FastAPI:
    config.load_env()
    service = service or PlannerService(make_planner(),
                                        limiter=RateLimiter() if config.rate_limits_enabled() else None)
    app = FastAPI(title="AI Multi-Agent Travel Planner", version="1.1")

    @app.exception_handler(ApiError)
    async def _api_error(_, exc: ApiError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(status_code=exc.status, content={"error": exc.message}, headers=headers)

    @app.get("/api/health")
    def health():
        return service.health()

    @app.post("/api/plan")
    def plan(body: PlanRequest, request: Request, authorization: Optional[str] = Header(None)):
        return service.plan(body.request, body.group, bearer(authorization), client_of(request))

    @app.post("/api/approve/{thread_id}")
    def approve(thread_id: str, body: ApproveRequest, request: Request,
                authorization: Optional[str] = Header(None)):
        return service.approve(thread_id, body.model_dump(), bearer(authorization), client_of(request))

    @app.get("/api/plan/{thread_id}")
    def get_plan(thread_id: str, request: Request, authorization: Optional[str] = Header(None)):
        return service.get(thread_id, bearer(authorization), client_of(request))

    @app.post("/api/booking/{thread_id}/cancel")
    def cancel_booking(thread_id: str, body: CancelRequest, request: Request,
                       authorization: Optional[str] = Header(None)):
        return service.cancel_booking(thread_id, body.model_dump(), bearer(authorization), client_of(request))

    @app.post("/api/emergency")
    def emergency(request: Request, body: Optional[dict] = Body(None),
                  authorization: Optional[str] = Header(None)):
        return service.emergency(body, bearer(authorization), client_of(request))

    def trip_route(method: str):
        def handler(request: Request, thread_id: str, tool: str, body: Optional[dict] = Body(None),
                    authorization: Optional[str] = Header(None)):
            return service.trip_tool(method, thread_id, tool, None, body, bearer(authorization),
                                     client_of(request))

        def item_handler(request: Request, thread_id: str, tool: str, item_id: str,
                         body: Optional[dict] = Body(None), authorization: Optional[str] = Header(None)):
            return service.trip_tool(method, thread_id, tool, item_id, body, bearer(authorization),
                                     client_of(request))
        app.add_api_route("/api/trip/{thread_id}/{tool}", handler, methods=[method],
                          name=f"{method.lower()}_trip_tool")
        app.add_api_route("/api/trip/{thread_id}/{tool}/{item_id}", item_handler, methods=[method],
                          name=f"{method.lower()}_trip_item")

    for method in ("GET", "POST", "DELETE"):
        trip_route(method)

    def account_route(method: str, path: str):
        def handler(request: Request, body: Optional[dict] = Body(None),
                    authorization: Optional[str] = Header(None)):
            return service.account(method, path, body, bearer(authorization), client_of(request))
        app.add_api_route(f"/api/{path}", handler, methods=[method], name=f"{method.lower()}_{path}")

    for method, path in (("POST", "auth/register"), ("POST", "auth/login"), ("POST", "auth/logout"),
                         ("GET", "me"), ("DELETE", "me"), ("PUT", "me/memory"), ("DELETE", "me/memory"),
                         ("GET", "trips")):
        account_route(method, path)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
