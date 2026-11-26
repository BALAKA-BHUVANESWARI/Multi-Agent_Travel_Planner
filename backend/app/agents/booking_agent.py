"""Booking agent: mock booking, safe to repeat."""
from __future__ import annotations

import hashlib

from app.graph.state import entry
from app.tools.client import call_with_retry
from app.tools.errors import ToolError


def booking_key(state: dict) -> str:
    c, br = state["constraints"], state["budget_report"]
    raw = f"{state['thread_id']}|{c['destination']}|{c['start_date']}|{c['days']}|{c['travelers']}|{br['total']}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def book_node(state: dict, deps) -> dict:
    key = booking_key(state)
    existing = deps.store.get_booking(key)
    if existing:
        return {"booking": existing, "status": "booked",
                "log": [entry("book", f"idempotent: reused booking {existing['booking_id']}")]}
    c, br = state["constraints"], state["budget_report"]
    summary = {"destination": c["destination"], "start_date": c["start_date"], "days": c["days"],
               "travelers": c["travelers"], "total_estimated_inr": br["total"]}
    try:
        res = call_with_retry(deps.tools, "book_trip", sleep=deps.sleep, idempotency_key=key, summary=summary)
    except ToolError as e:
        return {"approved": False, "status": "awaiting_approval",
                "warnings": [f"Booking failed ({e}). Nothing was booked; you can approve again."],
                "log": [entry("book", f"FAILED: {e}")]}
    stored = deps.store.save_booking(key, state["thread_id"], res)
    return {"booking": stored, "status": "booked", "log": [entry("book", f"booked {stored['booking_id']} (MOCK)")]}
