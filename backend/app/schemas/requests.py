"""Bodies of the API requests that have a fixed shape (checked by FastAPI)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.core import config


class PlanRequest(BaseModel):
    request: str = Field(..., max_length=5000)
    group: Optional[list] = Field(None, max_length=config.MAX_TRAVELERS)


class ApproveRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|revise|cancel)$")
    feedback: str = Field("", max_length=config.MAX_REQUEST_CHARS)


class CancelRequest(BaseModel):
    confirm: bool = False
