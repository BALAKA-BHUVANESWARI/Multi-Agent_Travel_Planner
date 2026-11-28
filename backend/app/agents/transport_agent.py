"""Transport agent: searches and picks the flight, train, bus, car or bike option."""
from __future__ import annotations

from datetime import date, timedelta

from app.agents.common import agent_failure, in_fanout
from app.core.utils import fmt_inr, part_level
from app.data.curated_destinations import place_name
from app.graph.state import entry
from app.services.export_service import price_tag, short_date
from app.services.pricing import transport_estimator as transport
from app.services.trip_toolkit import footprint
from app.tools.client import call_with_retry
from app.tools.errors import ToolError

FLIGHT_BY_STRATEGY = {"normal": "best", "cheaper": "early_late", "cheapest": "one_stop"}
MODE_LABEL = {"flight": "Flight", "train": "Train", "bus": "Bus", "car": "Car", "bike": "Bike"}


def _journey(c: dict, option: dict, today: date, border_warning: str = "") -> dict | None:
    """When an overland journey really starts and ends, with a warning when it crosses a doubtful border, is long
    or can no longer be made."""
    if option.get("mode") not in ("train", "bus", "car", "bike"):
        return None
    start = date.fromisoformat(c["start_date"])
    before, after = option.get("leave_days_before", 0), option.get("return_days_after", 0)
    leave, home = start - timedelta(days=before), start + timedelta(days=c["days"] - 1 + after)
    notes = [border_warning,
             transport.long_journey_warning(option["mode"], option["duration_h"], before + after, c["days"])]
    if leave < today:
        notes.append(f"You would have had to leave on {short_date(leave.isoformat())}, which has passed: "
                     "choose a later start date.")
    return {"leave_date": leave.isoformat(), "home_date": home.isoformat(), "extra_days": before + after,
            "warning": " ".join(n for n in notes if n)}


def build_travel_options(c: dict, deps, usual: str | None = None) -> list[dict]:
    """What each way of travelling would cost and take for this trip (the 'best' option of each mode)."""
    start = date.fromisoformat(c["start_date"])
    out = []
    for mode in ("flight", "train", "bus", "car", "bike"):
        try:
            res = call_with_retry(deps.tools, "search_flights", retries=1, sleep=deps.sleep, origin=c["origin"],
                                  destination=c["destination"], depart_date=start.isoformat(),
                                  return_date=(start + timedelta(days=c["days"] - 1)).isoformat(),
                                  travelers=c["travelers"], origin_geo=c.get("origin_geo"),
                                  destination_geo=c.get("destination_geo"), mode=mode, live_prices=False)
            best = next((o for o in res["options"] if o["id"] == "best"), res["options"][0])
            cheapest = min(o["price_pp"] for o in res["options"])
            out.append({"mode": mode, "label": MODE_LABEL[mode], "available": True, "price_pp": best["price_pp"],
                        "cheapest_pp": cheapest, "duration_h": best["duration_h"], "detail": best["label"],
                        "note": best.get("note", ""), "estimated": True, "usual": mode == usual,
                        "co2_kg_pp": (footprint.for_trip(c, mode) or {}).get("kg_pp"),
                        **(_journey(c, best, deps.today, res.get("border_warning", "")) or {})})
        except (ToolError, KeyError, ValueError) as e:
            out.append({"mode": mode, "label": MODE_LABEL[mode], "available": False, "reason": str(e),
                        "estimated": True})
    known = [o["co2_kg_pp"] for o in out if o.get("co2_kg_pp") is not None]
    for o in out:
        o["greenest"] = len(known) > 1 and o.get("co2_kg_pp") == min(known)
    return out


def travel_options_message(c: dict, options: list[dict]) -> str:
    lines = [f"How would you like to travel from {place_name(c, 'origin')} to {place_name(c, 'destination')}? "
             "Reply with one of these (add it to your request, e.g. 'by train'):"]
    for o in options:
        if o["available"]:
            line = (f"- {o['label']}: about {fmt_inr(o['price_pp'])} per person round trip, "
                    f"{o['duration_h']:g} h each way (estimated)")
            if o.get("co2_kg_pp") is not None:
                line += f"; about {o['co2_kg_pp']:g} kg CO2e per person" + (" (lowest)" if o["greenest"] else "")
            if o.get("extra_days"):
                line += f"; leave {short_date(o['leave_date'])}, home {short_date(o['home_date'])}"
            if o.get("warning"):
                line += f". {o['warning']}"
            lines.append(line + (" [your usual]" if o.get("usual") else ""))
        else:
            lines.append(f"- {o['label']}: not available ({o['reason']})")
    lines.append("Or say 'any mode' and I will pick the best value.")
    return "\n".join(lines)


def pick_flight(options: list[dict], strategy: str) -> dict:
    want = FLIGHT_BY_STRATEGY[strategy]
    return next((o for o in options if o["id"] == want), min(options, key=lambda o: o["price_pp"]))


def flight_node(state: dict, deps) -> dict:
    if not in_fanout(state, "flight"):
        return {}
    c = state["constraints"]
    start = date.fromisoformat(c["start_date"])
    try:
        res = call_with_retry(deps.tools, "search_flights", sleep=deps.sleep, origin=c["origin"],
                              destination=c["destination"], depart_date=start.isoformat(),
                              return_date=(start + timedelta(days=c["days"] - 1)).isoformat(),
                              travelers=c["travelers"], origin_geo=c.get("origin_geo"),
                              destination_geo=c.get("destination_geo"),
                              mode=(c.get("travel_mode") if c.get("travel_mode") not in (None, "auto") else None))
        level = part_level(state, "flight")
        sel = dict(pick_flight(res["options"], level))
        sel["total"] = sel["price_pp"] * c["travelers"]
    except (ToolError, KeyError, ValueError) as e:
        return agent_failure("flight", "flight", e, MODE_LABEL.get(c.get("travel_mode"), "Travel") + " search")
    live = res.get("estimated") is False
    out = {"flight": {"selected": sel, "options": res["options"], "estimated": not live, "live": live,
                      "strategy": level, "source": res.get("source"),
                      "fetched_at": res.get("fetched_at"), "price_basis": res.get("price_basis")},
           "log": [entry("flight", f"picked '{sel['id']}' {fmt_inr(sel['price_pp'])} pp "
                                   f"({price_tag(res) if live else 'estimated'})")]}
    journey = _journey(c, sel, deps.today, res.get("border_warning", ""))
    if journey:
        out["flight"]["journey"] = journey                 # always describes the option that is selected now
    emissions = footprint.for_trip(c, sel.get("mode"))
    if emissions:
        out["flight"]["footprint"] = emissions
    if res.get("live_note"):
        out["warnings"] = [res["live_note"]]
        out["flight"]["notices"] = out["warnings"]         # said again if a later change keeps this result
    return out


def travel_mode_problem(c: dict, deps) -> str:
    """'' when the chosen overland mode can cover this route, otherwise why not."""
    if deps is None or c.get("travel_mode") not in ("train", "bus", "car", "bike"):
        return ""
    start = date.fromisoformat(c["start_date"])
    try:
        call_with_retry(deps.tools, "search_flights", retries=1, sleep=deps.sleep, origin=c["origin"],
                        destination=c["destination"], depart_date=start.isoformat(),
                        return_date=(start + timedelta(days=c["days"] - 1)).isoformat(),
                        travelers=c["travelers"], origin_geo=c.get("origin_geo"),
                        destination_geo=c.get("destination_geo"), mode=c["travel_mode"], live_prices=False)
    except ToolError as e:
        return str(e)
    return ""
