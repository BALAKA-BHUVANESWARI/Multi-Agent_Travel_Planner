"""The web application. Start it from the backend folder:

    python -m uvicorn app.main:create_app --factory --port 8000

Every API route is under /api/v1 (see app/api/v1/). The built React app is served at /.
Without FastAPI installed, ``python -m app.api.stdlib_server`` offers the same API and page.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from app.api import frontend
from app.api.v1 import auth, explore, health, toolkit, trips
from app.core import config
from app.core.rate_limit import RateLimiter
from app.graph.engine import make_planner
from app.services.trip_service import ApiError, PlannerService

API_PREFIX = "/api/v1"


def create_app(service: PlannerService | None = None) -> FastAPI:
    config.load_env()
    service = service or PlannerService(make_planner(),
                                        limiter=RateLimiter() if config.rate_limits_enabled() else None)
    app = FastAPI(title="AI Multi-Agent Travel Planner", version="1.1")

    @app.exception_handler(ApiError)
    async def _api_error(_, exc: ApiError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(status_code=exc.status, content={"error": exc.message}, headers=headers)

    for module in (health, trips, explore, toolkit, auth):
        app.include_router(module.create_router(service), prefix=API_PREFIX)

    def serve_asset(name: str) -> Response:
        found = frontend.asset(name)
        if found is None:
            raise HTTPException(status_code=404, detail="not found")
        return Response(content=found[0], media_type=found[1])

    @app.get("/", include_in_schema=False)
    def index():
        return serve_asset("index.html")

    @app.get("/{name}", include_in_schema=False)
    def built_file(name: str):
        return serve_asset(name)

    return app
