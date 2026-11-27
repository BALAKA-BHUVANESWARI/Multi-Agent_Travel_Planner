"""Tool: hotel search. Live prices when configured, otherwise labelled estimates."""
from __future__ import annotations

import math

from app.core import config
from app.core.utils import hash01, round_to
from app.integrations import live_prices as live
from app.observability import recorder as observe
from app.tools.common import destination_info, parse_date, season_factor
from app.tools.errors import ToolError

HOTEL_TIERS = [
    ("3star", "3-star hotel", 3400),
    ("2star", "2-star / budget hotel", 1900),
    ("budget", "Homestay / hostel private room", 1000),
]


def search_hotels(destination: str, checkin: str, nights: int, travelers: int,
                  destination_geo: dict | None = None, live_prices: bool = True) -> dict:
    d = destination_info(destination, destination_geo)
    ci = parse_date(checkin)
    if nights < 1:
        raise ToolError("nights must be >= 1", retryable=False)
    season = season_factor(d, ci.month, 1.3, 0.75)
    rooms = max(1, math.ceil(travelers / 2))
    options = []
    for tier, label, base in HOTEL_TIERS:
        jitter = 1 + (hash01("hotel", destination, tier, checkin) - 0.5) * 0.10
        options.append({"id": tier, "tier": tier, "label": f"{label} ({d['hotel_area']})",
                        "price_night_per_room": round_to(base * d["cost_factor"] * season * jitter),
                        "estimated": True})
    result = {"source": "synthetic-estimator", "estimated": True, "destination": destination, "checkin": checkin,
              "nights": nights, "rooms": rooms, "currency": "INR", "options": options}
    if live_prices and config.live_prices_enabled():
        try:
            result.update(live.hotels(d["name"], ci, nights))
        except live.LiveUnavailable as e:
            observe.event("retrieval", "live_prices.hotels", "fallback", detail=str(e))
            result["live_note"] = f"Live hotel prices were unavailable ({e}); the hotel price is an estimate."
        except Exception as e:                                       # noqa: BLE001 - never let this break a plan
            observe.event("retrieval", "live_prices.hotels", "fallback", error=type(e).__name__)
            result["live_note"] = (f"Live hotel prices were unavailable ({type(e).__name__}); the hotel price is "
                                   "an estimate.")
    return result
