"""Accommodation agent: searches and picks the hotel."""
from __future__ import annotations

from app.agents.common import agent_failure, in_fanout
from app.core.utils import fmt_inr
from app.graph.state import entry
from app.services.export_service import price_tag
from app.tools.client import call_with_retry
from app.tools.errors import ToolError

HOTEL_BY_STRATEGY = {"normal": "3star", "cheaper": "2star", "cheapest": "budget"}


def pick_hotel(options: list[dict], strategy: str) -> dict:
    want = HOTEL_BY_STRATEGY[strategy]
    return next((o for o in options if o["id"] == want), min(options, key=lambda o: o["price_night_per_room"]))


def hotel_node(state: dict, deps) -> dict:
    if not in_fanout(state, "hotel"):
        return {}
    c = state["constraints"]
    nights = c["days"] - 1
    try:
        res = call_with_retry(deps.tools, "search_hotels", sleep=deps.sleep, destination=c["destination"],
                              checkin=c["start_date"], nights=nights, travelers=c["travelers"],
                              destination_geo=c.get("destination_geo"))
        sel = dict(pick_hotel(res["options"], state["strategy"]))
        sel.update(nights=nights, rooms=res["rooms"])
        sel["total"] = sel["price_night_per_room"] * nights * res["rooms"]
    except (ToolError, KeyError, ValueError) as e:
        return agent_failure("hotel", "hotel", e, "Hotel search")
    live = res.get("estimated") is False
    out = {"hotel": {"selected": sel, "options": res["options"], "estimated": not live, "live": live,
                     "strategy": state["strategy"], "source": res.get("source"), "fetched_at": res.get("fetched_at"),
                     "price_basis": res.get("price_basis"), "fx_note": res.get("fx_note", "")},
           "log": [entry("hotel", f"picked '{sel['id']}' {fmt_inr(sel['price_night_per_room'])}/room/night x "
                                  f"{nights}n x {res['rooms']} room(s) ({price_tag(res) if live else 'estimated'})")]}
    if res.get("live_note"):
        out["warnings"] = [res["live_note"]]
    return out
