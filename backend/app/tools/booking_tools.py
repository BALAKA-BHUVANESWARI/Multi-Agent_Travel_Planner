"""Tools: mock booking and cancellation. Nothing real is ever purchased."""
from __future__ import annotations

import hashlib

from app.tools.common import parse_date
from app.tools.errors import ToolError


def book_trip(idempotency_key: str, summary: dict | None = None) -> dict:
    """MOCK booking. Nothing is purchased. Deterministic for a given key."""
    if not idempotency_key:
        raise ToolError("idempotency_key required", retryable=False)
    bid = "MOCK-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:8].upper()
    return {"booking_id": bid, "idempotency_key": idempotency_key,
            "status": "confirmed (MOCK - nothing was actually booked or charged)",
            "summary": summary or {}}


# MOCK cancellation policy: (at least this many days before the start, percent refunded)
REFUND_STEPS = ((7, 100), (2, 50), (0, 0))


def cancellation_terms(start_date: str, today: str, total: int) -> dict:
    """What cancelling would refund under the MOCK policy."""
    days_left = (parse_date(start_date) - parse_date(today)).days
    pct = next((p for floor, p in REFUND_STEPS if days_left >= floor), 0)
    return {"days_before_start": days_left, "refund_pct": pct, "refund_inr": int(round(total * pct / 100)),
            "total_inr": int(total),
            "policy": "MOCK policy: full refund 7 or more days before the trip, 50% from 2 to 6 days, "
                      "nothing after that. No money was ever taken."}


def cancel_booking(booking_id: str, idempotency_key: str, start_date: str, today: str, total: int) -> dict:
    """MOCK cancellation. Nothing was charged, so nothing is really refunded. Deterministic for a given key."""
    if not booking_id or not idempotency_key:
        raise ToolError("booking_id and idempotency_key required", retryable=False)
    cid = "CANCEL-" + hashlib.sha256(f"cancel|{idempotency_key}".encode()).hexdigest()[:8].upper()
    return {"cancellation_id": cid, "booking_id": booking_id,
            "status": "cancelled (MOCK - nothing was actually booked, charged or refunded)",
            **cancellation_terms(start_date, today, total)}
