"""Deterministic verification used by the Critic (feasibility) and the output check
(prices trace back to tool results; totals add up). No LLM involved."""
from __future__ import annotations

from datetime import date, timedelta

from app.core import config
from app.services.budget_service import food_line


def issue(severity: str, code: str, message: str) -> dict:
    return {"severity": severity, "code": code, "message": message}


def check_dates(state: dict) -> list[dict]:
    c, it = state["constraints"], state.get("itinerary")
    out = []
    try:
        start = date.fromisoformat(c["start_date"])
    except (KeyError, ValueError):
        return [issue("blocking", "bad_date", "Trip start date is invalid.")]
    today = date.fromisoformat(c["today"])
    if start <= today:
        out.append(issue("blocking", "date_in_past", "Trip start date is not in the future."))
    if not (config.MIN_DAYS <= c["days"] <= config.MAX_DAYS):
        out.append(issue("blocking", "bad_duration", "Trip length is outside the supported range."))
    if it:
        if len(it["days"]) != c["days"]:
            out.append(issue("blocking", "day_count", "Itinerary day count does not match the request."))
        for i, d in enumerate(it["days"]):
            if d["date"] != (start + timedelta(days=i)).isoformat():
                out.append(issue("blocking", "date_sequence", f"Day {i + 1} has the wrong date."))
                break
    return out


def check_hotel_nights(state: dict) -> list[dict]:
    h = (state.get("hotel") or {}).get("selected")
    if h and h["nights"] != state["constraints"]["days"] - 1:
        return [issue("blocking", "hotel_nights",
                      f"Hotel booked for {h['nights']} nights but the trip needs {state['constraints']['days'] - 1}.")]
    return []


def check_itinerary(state: dict) -> list[dict]:
    it = state.get("itinerary")
    if not it:
        return [issue("blocking", "no_itinerary", "No itinerary was produced.")]
    out = []
    for d in it["days"]:
        items = sorted(d["items"], key=lambda x: x["start_min"])
        for a, b in zip(items, items[1:]):
            if b["start_min"] < a["end_min"]:
                out.append(issue("blocking", "overlap",
                                 f"Day {d['day']}: '{a['name']}' overlaps '{b['name']}'."))
        n_act = sum(1 for x in items if x["type"] == "activity")
        if n_act > config.MAX_ACTIVITIES_PER_DAY:
            out.append(issue("blocking", "too_many_items",
                             f"Day {d['day']} has {n_act} activities (max {config.MAX_ACTIVITIES_PER_DAY})."))
        arrive = next((x for x in items if x.get("leg") == "arrival"), None)
        depart = next((x for x in items if x.get("leg") == "departure"), None)
        for x in items:
            if x["type"] != "activity":
                continue
            if arrive and x["start_min"] < arrive["end_min"]:
                out.append(issue("blocking", "before_arrival", f"Day {d['day']}: '{x['name']}' starts before you arrive."))
            if depart and x["end_min"] > depart["start_min"] - 30:
                out.append(issue("blocking", "after_departure",
                                 f"Day {d['day']}: '{x['name']}' leaves under 30 min before the transfer home."))
        if d.get("rainy"):
            for x in items:
                if x["type"] == "activity" and x.get("outdoor"):
                    out.append(issue("warning", "rain_outdoor",
                                     f"Day {d['day']}: outdoor activity '{x['name']}' on a rainy day."))
    return out


def verify_prices_and_totals(state: dict) -> list[dict]:
    """Every price must come from a tool result; the report must add up."""
    out = []
    c = state["constraints"]
    br = state.get("budget_report")
    if not br:
        return [issue("blocking", "no_budget", "Budget report missing.")]
    lines = br["lines"]
    t = c["travelers"]

    fl = (state.get("flight") or {}).get("selected")
    if fl:
        src = {o["id"]: o["price_pp"] for o in (state["flight"].get("options") or [])}
        if src.get(fl["id"]) != fl["price_pp"]:
            out.append(issue("blocking", "price_untraceable", "Flight price does not match the tool result."))
        if lines["flight"] != fl["price_pp"] * t:
            out.append(issue("blocking", "total_mismatch", "Flight line does not equal price x travelers."))
    elif lines["flight"] != 0:
        out.append(issue("blocking", "total_mismatch", "Flight line is non-zero but no flight is selected."))

    ho = (state.get("hotel") or {}).get("selected")
    if ho:
        src = {o["id"]: o["price_night_per_room"] for o in (state["hotel"].get("options") or [])}
        if src.get(ho["id"]) != ho["price_night_per_room"]:
            out.append(issue("blocking", "price_untraceable", "Hotel price does not match the tool result."))
        if lines["hotel"] != ho["price_night_per_room"] * ho["nights"] * ho["rooms"]:
            out.append(issue("blocking", "total_mismatch", "Hotel line does not equal rate x nights x rooms."))
    elif lines["hotel"] != 0:
        out.append(issue("blocking", "total_mismatch", "Hotel line is non-zero but no hotel is selected."))

    cands = {x["id"]: x["cost"] for x in (state.get("activities") or {}).get("candidates", [])}
    act_sum = 0
    for d in (state.get("itinerary") or {}).get("days", []):
        for it in d["items"]:
            if it["type"] != "activity":
                continue
            if it["id"] == "generic-indoor":
                if it["cost_pp"] != 0:
                    out.append(issue("blocking", "price_untraceable", "Generic block must be free."))
            elif cands.get(it["id"]) != it["cost_pp"]:
                out.append(issue("blocking", "price_untraceable",
                                 f"Price of '{it['name']}' does not match the places tool."))
            if it["cost_total"] != it["cost_pp"] * t:
                out.append(issue("blocking", "total_mismatch", f"Cost of '{it['name']}' is not price x travelers."))
            act_sum += it["cost_total"]
    if lines["activities"] != act_sum:
        out.append(issue("blocking", "total_mismatch", "Activities line does not equal the sum of items."))
    if lines["food"] != food_line(c, br["strategy"], bool(state.get("food_boost"))):
        out.append(issue("blocking", "total_mismatch", "Food line does not match the food allowance formula."))
    if br["total"] != sum(lines.values()):
        out.append(issue("blocking", "total_mismatch", "Total does not equal the sum of its lines."))
    return out
