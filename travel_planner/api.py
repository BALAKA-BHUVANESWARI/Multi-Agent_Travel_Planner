"""FastAPI app.

    uvicorn travel_planner.api:create_app --factory --reload

Endpoints: POST /api/plan, POST /api/approve/{thread_id}, GET /api/plan/{thread_id}, GET /api/health
(the stdlib devserver exposes the identical API if FastAPI is not installed).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import config
from .engine import make_planner
from .service import ApiError, PlannerService

STATIC = Path(__file__).parent / "static"


class PlanRequest(BaseModel):
    request: str = Field(..., max_length=5000)


class ApproveRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|revise|cancel)$")
    feedback: str = Field("", max_length=config.MAX_REQUEST_CHARS)


def create_app(service: PlannerService | None = None) -> FastAPI:
    config.load_env()
    service = service or PlannerService(make_planner())
    app = FastAPI(title="AI Multi-Agent Travel Planner", version="1.0")

    @app.exception_handler(ApiError)
    async def _api_error(_, exc: ApiError):
        return JSONResponse(status_code=exc.status, content={"error": exc.message})

    @app.get("/api/health")
    def health():
        return service.health()

    @app.post("/api/plan")
    def plan(body: PlanRequest):
        return service.plan(body.request)

    @app.post("/api/approve/{thread_id}")
    def approve(thread_id: str, body: ApproveRequest):
        return service.approve(thread_id, body.model_dump())

    @app.get("/api/plan/{thread_id}")
    def get_plan(thread_id: str):
        return service.get(thread_id)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app

