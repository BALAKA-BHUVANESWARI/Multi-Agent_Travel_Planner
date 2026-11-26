"""GET /health: which engine, data mode and AI providers are in use."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.trip_service import PlannerService


def create_router(service: PlannerService) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health")
    def health():
        return service.health()

    return router
