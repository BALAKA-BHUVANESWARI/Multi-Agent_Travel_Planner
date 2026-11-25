"""Shared typed state.

Parallel workers write *separate keys*, so there are no write conflicts.
Only ``log`` and ``warnings`` use (append) reducers.
"""
from __future__ import annotations

import operator
import uuid
from typing import Annotated, Any, Optional, TypedDict

from .utils import now_iso


class TripState(TypedDict, total=False):
    thread_id: str
    request: str
    guardrail: dict
    constraints: dict
    strategy: str               # normal | cheaper | cheapest
    retries: int                # automatic replans used (budget + critic)
    revisions: int              # human change-request rounds used
    replan_reason: Optional[str]  # None | over_budget | critic | feedback
    fanout: list                # which workers run this pass
    flight: Optional[dict]
    hotel: Optional[dict]
    weather: Optional[dict]
    activities: Optional[dict]
    itinerary: Optional[dict]
    budget_report: Optional[dict]
    critic_issues: list
    warnings: Annotated[list, operator.add]   # append-only
    log: Annotated[list, operator.add]        # append-only
    decision: Optional[dict]
    approved: bool
    booking: Optional[dict]
    status: str     # new|blocked|needs_info|running|awaiting_approval|booked|cancelled
    message: str
    notice: str                 # one-shot note shown with the next plan presentation
    summary: str
    pending_approval: Optional[dict]
    food_boost: bool


APPEND_KEYS = ("warnings", "log")


def initial_state(request: str, thread_id: str | None = None) -> TripState:
    return TripState(
        thread_id=thread_id or uuid.uuid4().hex[:12],
        request=request,
        strategy="normal",
        retries=0,
        revisions=0,
        replan_reason=None,
        fanout=[],
        critic_issues=[],
        warnings=[],
        log=[],
        approved=False,
        status="new",
        food_boost=False,
    )


def apply_update(state: dict, update: dict | None) -> dict:
    """Merge a node's update into state, applying the append reducers."""
    new = dict(state)
    for k, v in (update or {}).items():
        if k in APPEND_KEYS:
            new[k] = list(new.get(k, [])) + list(v)
        else:
            new[k] = v
    return new


def entry(agent: str, msg: str, **extra: Any) -> dict:
    return {"t": now_iso(), "agent": agent, "msg": msg, **extra}
