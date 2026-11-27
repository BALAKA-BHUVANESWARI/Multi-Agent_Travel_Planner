"""The chatbot and its voice input."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, Request
from fastapi.concurrency import run_in_threadpool

from app.api.dependencies import bearer, client_of
from app.services.speech_service import MAX_AUDIO_BYTES
from app.services.trip_service import ApiError, PlannerService


def create_router(service: PlannerService) -> APIRouter:
    router = APIRouter(tags=["chat"])

    @router.post("/chat")
    def chat(request: Request, body: Optional[dict] = Body(None), authorization: Optional[str] = Header(None)):
        return service.chat(body, bearer(authorization), client_of(request))

    @router.post("/transcribe")
    async def transcribe(request: Request, authorization: Optional[str] = Header(None)):
        audio = bytearray()
        async for chunk in request.stream():          # stop reading as soon as it is too big
            audio.extend(chunk)
            if len(audio) > MAX_AUDIO_BYTES:
                raise ApiError(413, "That recording is too long. Keep it under a minute.")
        return await run_in_threadpool(service.transcribe, bytes(audio), request.headers.get("content-type", ""),
                                       bearer(authorization), client_of(request))

    return router
