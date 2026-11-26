"""All graph nodes. Each node is ``fn(state, deps) -> update dict`` and never mutates state.

Principle: hard constraints (money, dates, overlaps) are deterministic code.
The LLM (if configured) only touches language and soft preferences, always with a
rule-based fallback and schema/number validation.
"""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import checks, config, group as group_mod, guardrails, guide, intake as intake_mod
from .feedback import matches_excluded, parse_feedback
from .itinerary import build_itinerary
from .state import RESET, entry
from .toolkit import footprint
from .tools import geo as geo_mod
from .tools.catalog import place_name
from .tools.client import call_with_retry
from .tools import transport
from .tools.errors import ToolError
from .utils import clip, fmt_inr, next_strategy

WORKERS = ["flight", "hotel", "weather", "activities"]
FLIGHT_BY_STRATEGY = {"normal": "best", "cheaper": "early_late", "cheapest": "one_stop"}
HOTEL_BY_STRATEGY = {"normal": "3star", "cheaper": "2star", "cheapest": "budget"}
RANK_COST_SCALE = {"normal": 3000.0, "cheaper": 800.0, "cheapest": 300.0}
_SLOTS = {"morning", "afternoon", "evening", "any"}


# --------------------------------------------------------------- guardrail
def input_guardrail_node(state: dict, deps) -> dict:
    g = guardrails.check_input(state.get("request", ""))
    if not g["allowed"]:
        return {"guardrail": g, "status": "blocked", "message": g["message"],
                "log": [entry("guardrail", f"blocked: {g['code']}")]}
    return {"guardrail": g, "log": [entry("guardrail", "input allowed")]}


# ------------------------------------------------------------------ intake
_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "origin": {"type": "string"}, "destination": {"type": "string"},
        "days": {"type": "integer", "minimum": config.MIN_DAYS, "maximum": config.MAX_DAYS},
        "budget_inr": {"type": "integer", "minimum": config.MIN_BUDGET, "maximum": config.MAX_BUDGET},
        "travelers": {"type": "integer", "minimum": 1, "maximum": config.MAX_TRAVELERS},
        "preferences": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
}


_PLACE_TEXT = re.compile(r"^[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f .'\u2019-]{1,59}$")
_WANTS_IDEAS = re.compile(r"\b(suggest|recommend|somewhere|anywhere|any place|where (?:should|can|could|do) "
                          r"(?:i|we))\b", re.I)


def _llm_fill_gaps(parsed: dict, text: str, deps) -> list[str]:
    """Let the LLM fill ONLY missing fields. Returns names of fields it filled.
    Place names stay candidates: the place lookup must confirm them before they are used."""
    if not deps.llm or not deps.llm.available("intake"):
        return []
    system = ("Extract trip constraints from the request. 'origin' and 'destination' are place names (a city "
              "or town, as written by the user). Omit any field you are not sure about. Budget is total INR.")
    obj = deps.llm.complete_json("intake", system, text, _INTAKE_SCHEMA)
    if not obj:
        return []
    c, filled = parsed["constraints"], []
    texts = parsed.setdefault("texts", {})
    alts = parsed.setdefault("alts", {})
    for role in ("origin", "destination"):
        v = obj.get(role)
        if role == "destination" and isinstance(v, str) and _WANTS_IDEAS.search(text) \
                and v.strip().lower() not in text.lower():
            continue                        # asked for ideas and never named it: offer suggestions instead
        if c[role] is None and isinstance(v, str) and _PLACE_TEXT.match(v.strip()):
            if role not in texts:
                texts[role] = v.strip()
            elif v.strip().lower() != texts[role].lower():
                alts[role] = v.strip()          # keep the rule-based candidate; try this one as a second choice
            else:
                continue
            filled.append(role)
    if c["days"] is None and isinstance(obj.get("days"), int):
        c["days"] = obj["days"]; filled.append("days")
    if c["budget"] is None and isinstance(obj.get("budget_inr"), int):
        c["budget"] = obj["budget_inr"]; filled.append("budget")
    if not c["preferences"] and obj.get("preferences"):
        known = set(intake_mod.PREF_WORDS)
        c["preferences"] = [p for p in obj["preferences"] if p in known]
        if c["preferences"]:
            filled.append("preferences")
    parsed["missing"] = [k for k in ("origin", "destination", "days", "budget")
                         if c[k] is None and k not in texts]
    return filled


def _set_place(parsed: dict, role: str, geo: dict) -> None:
    c = parsed["constraints"]
    c[role], c[f"{role}_geo"] = geo["slug"], geo
    parsed["texts"].pop(role, None)
    parsed.get("alts", {}).pop(role, None)
    parsed["invalid"].pop(role, None)


def _place_candidates(parsed: dict, role: str) -> list[str]:
    """Names to try for a role, best first (rule-based text, then the LLM's reading), without repeats."""
    out: list[str] = []
    for q in (parsed["constraints"][role], parsed["texts"].get(role), parsed.get("alts", {}).get(role)):
        if q and q.lower() not in (x.lower() for x in out):
            out.append(q)
    return out


def _resolve_places(parsed: dict, deps, logs: list) -> None:
    """Turn place names into resolved places (coordinates, country, price level).
    Known places (curated + offline list) are resolved locally; anything else needs the live
    place-lookup tool, which is only called once nothing else is missing."""
    c, texts = parsed["constraints"], parsed.setdefault("texts", {})
    for role in ("origin", "destination"):
        for q in _place_candidates(parsed, role):
            try:
                _set_place(parsed, role, geo_mod.resolve(q, live=False))
                break
            except geo_mod.PlaceError:
                continue                                 # not a known place: may need the live lookup
    if set(parsed["missing"]) - {"destination"} or any(k not in ("origin", "destination") for k in parsed["invalid"]):
        return
    for role in ("origin", "destination"):
        if c[role] is not None:
            continue
        error = None
        for q in _place_candidates(parsed, role):
            try:
                res = call_with_retry(deps.tools, "resolve_place", sleep=deps.sleep, query=q)
            except ToolError as e:
                error = error or str(e)
                logs.append(entry("intake", f"could not resolve {role} '{q}'"))
                continue
            _set_place(parsed, role, res["geo"])
            logs.append(entry("intake", f"resolved {role} '{q}' -> {res['geo']['name']}, "
                                        f"{res['geo']['country']} ({res['geo']['source']})"))
            break
        else:
            if error:
                parsed["invalid"][role] = error


MODE_LABEL = {"flight": "Flight", "train": "Train", "bus": "Bus", "car": "Car", "bike": "Bike"}
ROAD_NOTE = ("Road and rail times and prices are estimated from the straight-line distance: check that a direct "
             "route exists and book real tickets before you go.")


def _travel_heading(sel: dict | None) -> str:
    mode = (sel or {}).get("mode")
    return {"ground": "Train/bus", "train": "Train", "bus": "Bus", "car": "Car", "bike": "Bike"}.get(mode, "Flight")


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b}"


def _journey(c: dict, option: dict, today: date) -> dict | None:
    """When an overland journey really starts and ends, with a warning when it is long or can no longer be made."""
    if option.get("mode") not in ("train", "bus", "car", "bike"):
        return None
    start = date.fromisoformat(c["start_date"])
    before, after = option.get("leave_days_before", 0), option.get("return_days_after", 0)
    leave, home = start - timedelta(days=before), start + timedelta(days=c["days"] - 1 + after)
    notes = [transport.long_journey_warning(option["mode"], option["duration_h"], before + after, c["days"])]
    if leave < today:
        notes.append(f"You would have had to leave on {_day(leave.isoformat())}, which has passed: "
                     "choose a later start date.")
    return {"leave_date": leave.isoformat(), "home_date": home.isoformat(), "extra_days": before + after,
            "warning": " ".join(n for n in notes if n)}


def _travel_options(c: dict, deps, usual: str | None = None) -> list[dict]:
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
                        **(_journey(c, best, deps.today) or {})})
        except (ToolError, KeyError, ValueError) as e:
            out.append({"mode": mode, "label": MODE_LABEL[mode], "available": False, "reason": str(e),
                        "estimated": True})
    known = [o["co2_kg_pp"] for o in out if o.get("co2_kg_pp") is not None]
    for o in out:
        o["greenest"] = len(known) > 1 and o.get("co2_kg_pp") == min(known)
    return out


def _options_message(c: dict, options: list[dict]) -> str:
    lines = [f"How would you like to travel from {place_name(c, 'origin')} to {place_name(c, 'destination')}? "
             "Reply with one of these (add it to your request, e.g. 'by train'):"]
    for o in options:
        if o["available"]:
            line = (f"- {o['label']}: about {fmt_inr(o['price_pp'])} per person round trip, "
                    f"{o['duration_h']:g} h each way (estimated)")
            if o.get("co2_kg_pp") is not None:
                line += f"; about {o['co2_kg_pp']:g} kg CO2e per person" + (" (lowest)" if o["greenest"] else "")
            if o.get("extra_days"):
                line += f"; leave {_day(o['leave_date'])}, home {_day(o['home_date'])}"
            if o.get("warning"):
                line += f". {o['warning']}"
            lines.append(line + (" [your usual]" if o.get("usual") else ""))
        else:
            lines.append(f"- {o['label']}: not available ({o['reason']})")
    lines.append("Or say 'any mode' and I will pick the best value.")
    return "\n".join(lines)


def _apply_group(parsed: dict, group: list) -> None:
    c = parsed["constraints"]
    if group:
        c["preferences"] = list(dict.fromkeys(c["preferences"] + group_mod.shared_preferences(group)))


def _apply_memory(parsed: dict, memory: dict, text: str, group: list, ask_mode: bool = False) -> list[str]:
    """Fill ONLY what the request does not say from a signed-in traveller's saved defaults, and say so."""
    if not memory:
        return []
    c, texts, used = parsed["constraints"], parsed.setdefault("texts", {}), []
    home = memory.get("home_city")
    if home and c["origin"] is None and "origin" not in texts:
        texts["origin"] = home
        parsed["missing"] = [k for k in parsed["missing"] if k != "origin"]
        used.append(f"starting from {home}")
    if memory.get("preferences") and not c["preferences"] and not group:
        c["preferences"] = [p for p in memory["preferences"] if p in intake_mod.PREF_WORDS]
        if c["preferences"]:
            used.append("interests: " + ", ".join(c["preferences"]))
    # when the planner asks how to travel, the saved mode is only highlighted among the choices
    if memory.get("travel_mode") and c.get("travel_mode") is None and not ask_mode:
        c["travel_mode"] = memory["travel_mode"]
        used.append(f"travel by {memory['travel_mode']}")
    if memory.get("pace") == "relaxed" and c.get("pace") == "normal" and not re.search(
            r"\b(pace|busy|packed|fuller)\b", text, re.I):
        c["pace"] = "relaxed"
        used.append("relaxed pace")
    if not used:
        return []
    return ["From your saved profile: " + "; ".join(used) + ". Say otherwise in your request to override."]


def _suggestions(c: dict, text: str, deps) -> list[dict]:
    """Destinations to offer when the request names none. Never raises: no suggestions just means we ask."""
    try:
        res = call_with_retry(deps.tools, "recommend_destinations", retries=1, sleep=deps.sleep,
                              origin=c["origin"], start_date=c["start_date"], days=c["days"],
                              travelers=c["travelers"], budget=c["budget"], preferences=c["preferences"],
                              origin_geo=c.get("origin_geo"), scope=intake_mod.parse_scope(text),
                              mode=c.get("travel_mode"))
        return res["suggestions"]
    except (ToolError, KeyError, ValueError):
        return []


def _suggestion_message(c: dict, items: list[dict], any_fit: bool) -> str:
    lines = [f"You didn't name a destination, so here are some that suit a {c['days']}-day trip from "
             f"{place_name(c, 'origin')} (all prices estimated, for {c['travelers']} traveler(s)):"]
    if not any_fit:
        lines.append(f"None of my suggestions fits {fmt_inr(c['budget'])}; these are the closest.")
    for s in items:
        season = "good season" if s["in_season"] else "off season"
        lines.append(f"- {s['name']}, {s['country']}: from about {fmt_inr(s['estimate_from'])} ({season}; "
                     f"{', '.join(s['tags'][:3])})")
    lines.append("Add one to your request (e.g. 'to Goa'), or name any other city or town.")
    return "\n".join(lines)


def _trip_warnings(c: dict) -> list[str]:
    """Warnings that follow from where and how the trip goes (used at intake and after such a change)."""
    out = []
    if c.get("travel_mode") in ("train", "bus", "car", "bike"):
        out.append(ROAD_NOTE)
    og, dg = c.get("origin_geo") or {}, c.get("destination_geo") or {}
    if og.get("cc") and dg.get("cc") and og["cc"] != dg["cc"]:
        out.append(f"International trip ({og['country']} to {dg['country']}): passport, visa or entry rules, "
                   "travel insurance and currency-exchange costs are not included in this estimate.")
    return out


def intake_node(state: dict, deps) -> dict:
    group = state.get("group") or []
    parsed = intake_mod.parse_request(state["request"], deps.today, len(group))
    _apply_group(parsed, group)
    logs = []
    if parsed["missing"] or parsed["invalid"]:
        filled = _llm_fill_gaps(parsed, state["request"], deps)
        if filled:
            logs.append(entry("intake", f"LLM filled: {', '.join(filled)}"))
    memory = state.get("memory") or {}
    remembered = _apply_memory(parsed, memory, state["request"], group, getattr(deps, "ask_travel_mode", False))
    parsed["assumptions"] = parsed["assumptions"] + remembered
    _resolve_places(parsed, deps, logs)
    c = parsed["constraints"]
    for role in ("origin", "destination"):                 # a place that is still unresolved is "missing"
        if c[role] is None and role not in parsed["invalid"] and role not in parsed["missing"]:
            parsed["missing"].append(role)
    if c["days"] is not None and "days" not in parsed["invalid"] and not (config.MIN_DAYS <= c["days"] <= config.MAX_DAYS):
        parsed["invalid"]["days"] = f"I can plan trips of {config.MIN_DAYS} to {config.MAX_DAYS} days."
    if parsed["missing"] or parsed["invalid"]:
        msg = intake_mod.build_question(parsed["missing"], parsed["invalid"])
        if parsed["missing"] == ["destination"] and not parsed["invalid"] and c.get("origin_geo"):
            items = _suggestions(c, state["request"], deps)
            if items:
                return {"constraints": c, "status": "needs_info", "suggestions": items,
                        "message": _suggestion_message(c, items, any(s["fits_budget"] for s in items)),
                        "log": logs + [entry("intake", "no destination: suggested "
                                             + ", ".join(s["name"] for s in items))]}
        return {"constraints": c, "status": "needs_info", "message": msg,
                "log": logs + [entry("intake", f"needs info: {parsed['missing'] or list(parsed['invalid'])}")]}
    og, dg = c["origin_geo"], c["destination_geo"]
    if c["origin"] == c["destination"] or geo_mod.distance_km(og, dg) < 15:
        return {"constraints": c, "status": "needs_info", "message": "Origin and destination are the same place.",
                "log": logs + [entry("intake", "origin == destination")]}
    if c.get("travel_mode") is None and getattr(deps, "ask_travel_mode", False):
        options = _travel_options(c, deps, memory.get("travel_mode"))
        return {"constraints": c, "status": "needs_info", "message": _options_message(c, options),
                "travel_options": options,
                "log": logs + [entry("intake", "asked how to travel: " + ", ".join(
                    o["mode"] for o in options if o["available"]))]}
    warnings = list(parsed["assumptions"])
    if c.get("travel_mode") in ("train", "bus", "car", "bike"):
        start = date.fromisoformat(c["start_date"])
        try:                                                    # is the chosen mode possible for this distance?
            call_with_retry(deps.tools, "search_flights", retries=1, sleep=deps.sleep, origin=c["origin"],
                            destination=c["destination"], depart_date=start.isoformat(),
                            return_date=(start + timedelta(days=c["days"] - 1)).isoformat(),
                            travelers=c["travelers"], origin_geo=c.get("origin_geo"),
                            destination_geo=c.get("destination_geo"), mode=c["travel_mode"])
        except ToolError as e:
            options = _travel_options(c, deps)
            return {"constraints": {**c, "travel_mode": None}, "status": "needs_info", "travel_options": options,
                    "message": f"{e} " + _options_message(c, options),
                    "log": logs + [entry("intake", f"{c['travel_mode']} not possible: {e}")]}
    warnings += _trip_warnings(c)
    return {"constraints": c, "status": "running", "message": "", "warnings": warnings,
            "log": logs + [entry("intake", f"parsed: {c['days']}d {og['name']}->{dg['name']} "
                                           f"budget {fmt_inr(c['budget'])} x{c['travelers']}")]}


# -------------------------------------------------------------- supervisor
def supervisor_node(state: dict, deps) -> dict:
    reason = state.get("replan_reason")
    retries = state.get("retries", 0)
    strategy = state.get("strategy", "normal")
    upd: dict = {"status": "running", "replan_reason": None}
    if reason is None:
        upd["fanout"] = list(WORKERS)
        msg = f"first pass: strategy={strategy}, workers={WORKERS}"
    else:
        upd.update(flight=None, hotel=None, activities=None, itinerary=None, budget_report=None,
                   critic_issues=[], group_report=[], alternatives={})
        if reason == "over_budget":
            strategy = next_strategy(strategy)
            upd.update(strategy=strategy, retries=retries + 1, fanout=["flight", "hotel", "activities"])
            msg = f"replan (over budget): strategy -> {strategy}, retry {retries + 1}/{config.MAX_AUTO_REPLANS}"
        elif reason == "critic":
            upd.update(retries=retries + 1, fanout=list(WORKERS), weather=None)
            msg = f"replan (critic blocking issue): retry {retries + 1}/{config.MAX_AUTO_REPLANS}"
        else:                                                     # feedback
            fan = ["flight", "hotel", "activities"] + (["weather"] if not state.get("weather") else [])
            upd.update(retries=0, fanout=fan)
            msg = f"replan (user feedback): strategy={strategy}"
    upd["log"] = [entry("supervisor", msg, reason=reason)]
    return upd


# ----------------------------------------------------------------- workers
def _in_fanout(state: dict, name: str) -> bool:
    return name in state.get("fanout", WORKERS)


def _fail(agent: str, key: str, e: Exception, what: str) -> dict:
    return {key: {"error": str(e), "selected": None, "estimated": True},
            "warnings": [f"{what} failed after retries ({e}); the plan is partial and totals exclude it."],
            "log": [entry(agent, f"FAILED: {e}")]}


def _price_tag(block: dict | None) -> str:
    """'live: Google Flights via Tavily, fetched 25 Nov 10:45 UTC' for a live result, else 'estimated'."""
    block = block or {}
    if block.get("estimated", True):
        return "estimated"
    when = ""
    try:
        when = ", fetched " + datetime.fromisoformat(block["fetched_at"]).strftime("%d %b %H:%M UTC")
    except (KeyError, TypeError, ValueError):
        pass
    return f"live: {block.get('source', 'web')}{when}"


def pick_flight(options: list[dict], strategy: str) -> dict:
    want = FLIGHT_BY_STRATEGY[strategy]
    return next((o for o in options if o["id"] == want), min(options, key=lambda o: o["price_pp"]))


def pick_hotel(options: list[dict], strategy: str) -> dict:
    want = HOTEL_BY_STRATEGY[strategy]
    return next((o for o in options if o["id"] == want), min(options, key=lambda o: o["price_night_per_room"]))


def flight_node(state: dict, deps) -> dict:
    if not _in_fanout(state, "flight"):
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
        sel = dict(pick_flight(res["options"], state["strategy"]))
        sel["total"] = sel["price_pp"] * c["travelers"]
    except (ToolError, KeyError, ValueError) as e:
        return _fail("flight", "flight", e, MODE_LABEL.get(c.get("travel_mode"), "Travel") + " search")
    live = res.get("estimated") is False
    out = {"flight": {"selected": sel, "options": res["options"], "estimated": not live, "live": live,
                      "strategy": state["strategy"], "source": res.get("source"),
                      "fetched_at": res.get("fetched_at"), "price_basis": res.get("price_basis")},
           "log": [entry("flight", f"picked '{sel['id']}' {fmt_inr(sel['price_pp'])} pp "
                                   f"({_price_tag(res) if live else 'estimated'})")]}
    journey = _journey(c, sel, deps.today)
    if journey:
        out["flight"]["journey"] = journey                 # always describes the option that is selected now
    emissions = footprint.for_trip(c, sel.get("mode"))
    if emissions:
        out["flight"]["footprint"] = emissions
    if res.get("live_note"):
        out["warnings"] = [res["live_note"]]
    return out


def hotel_node(state: dict, deps) -> dict:
    if not _in_fanout(state, "hotel"):
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
        return _fail("hotel", "hotel", e, "Hotel search")
    live = res.get("estimated") is False
    out = {"hotel": {"selected": sel, "options": res["options"], "estimated": not live, "live": live,
                     "strategy": state["strategy"], "source": res.get("source"), "fetched_at": res.get("fetched_at"),
                     "price_basis": res.get("price_basis"), "fx_note": res.get("fx_note", "")},
           "log": [entry("hotel", f"picked '{sel['id']}' {fmt_inr(sel['price_night_per_room'])}/room/night x "
                                  f"{nights}n x {res['rooms']} room(s) ({_price_tag(res) if live else 'estimated'})")]}
    if res.get("live_note"):
        out["warnings"] = [res["live_note"]]
    return out


def weather_node(state: dict, deps) -> dict:
    if not _in_fanout(state, "weather"):
        return {}
    c = state["constraints"]
    try:
        res = call_with_retry(deps.tools, "get_weather", sleep=deps.sleep, destination=c["destination"],
                              start_date=c["start_date"], days=c["days"], today=deps.today.isoformat(),
                              destination_geo=c.get("destination_geo"))
        if len(res["days"]) != c["days"]:
            raise ValueError("weather returned the wrong number of days")
    except (ToolError, KeyError, ValueError) as e:
        out = _fail("weather", "weather", e, "Weather lookup")
        out["weather"] = {"error": str(e), "days": []}
        return out
    rainy = sum(1 for d in res["days"] if d["rainy"])
    return {"weather": res, "log": [entry("weather", f"{res['source']}: {rainy}/{c['days']} rainy days")]}


def _position(p: dict) -> dict:
    lat, lon = p.get("lat"), p.get("lon")
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)) \
            and -90 <= lat <= 90 and -180 <= lon <= 180:
        return {"lat": float(lat), "lon": float(lon)}
    return {}


def _clean_candidate(p: dict) -> dict | None:
    try:
        cost, hours = int(p["cost"]), float(p["hours"])
        if cost < 0 or hours <= 0 or p["slot"] not in _SLOTS:
            return None
        return {"id": str(p["id"])[:40], "name": guardrails.sanitize_untrusted(p["name"], 90),
                "tags": [str(t) for t in p.get("tags", [])][:6], "outdoor": bool(p["outdoor"]),
                "cost": cost, "hours": hours, "slot": p["slot"],
                "desc": guardrails.sanitize_untrusted(p.get("desc", ""), 160),
                **({"far": True} if p.get("far") is True else {}),
                **_position(p),
                **({"kind": str(p["kind"])[:20]} if isinstance(p.get("kind"), str) else {}),
                **({"fame": float(p["fame"])} if isinstance(p.get("fame"), (int, float)) else {})}
    except (KeyError, TypeError, ValueError):
        return None


def rank_candidates(cands: list[dict], prefs: list[str], strategy: str, food_boost: bool = False) -> list[dict]:
    """Hard filter by the strategy's per-person cost cap, then score by preference match,
    popularity (catalog order) and cost."""
    cap = config.ACTIVITY_COST_CAP[strategy]
    pool = [c for c in cands if cap is None or c["cost"] <= cap]
    n = max(1, len(cands))
    scored = []
    for idx, c in enumerate(pool):
        match = sum(1 for t in c["tags"] if t in prefs)
        if food_boost and "food" in c["tags"]:
            match += 1
        score = 3 * match + (n - idx) / n * 2 - c["cost"] / RANK_COST_SCALE[strategy] - (2.5 if c.get("far") else 0)
        scored.append((score, idx, {**c, "score": round(score, 3)}))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [s[2] for s in scored]


_RERANK_SCHEMA = {"type": "object", "required": ["order"],
                  "properties": {"order": {"type": "array", "items": {"type": "string"}, "maxItems": 40}}}


def _llm_rerank(ranked: list[dict], c: dict, deps) -> tuple[list[dict], bool]:
    if not deps.llm or not deps.llm.available("activities") or len(ranked) < 3:
        return ranked, False
    import json
    system = ("You re-rank candidate travel activities for a traveler, best first, using their stated "
              "preferences. Candidates marked far are day trips several km out of town: rank them after "
              "the nearby sights unless nothing nearby fits. Return only ids that appear in the candidates list.")
    user = json.dumps({"preferences": c["preferences"], "travelers": c["travelers"],
                       "candidates": [{"id": r["id"], "name": r["name"], "tags": r["tags"], "cost": r["cost"],
                                       **({"far": True} if r.get("far") else {})} for r in ranked]})
    obj = deps.llm.complete_json("activities", system, user, _RERANK_SCHEMA)
    if not obj:
        return ranked, False
    by_id = {r["id"]: r for r in ranked}
    seen, order = set(), []
    for i in obj["order"]:
        if i in by_id and i not in seen:
            seen.add(i); order.append(by_id[i])
    if not order:
        return ranked, False
    full = order + [r for r in ranked if r["id"] not in seen]
    # Hard rule stays in code: whatever order the LLM chose, far day trips come after nearby sights.
    return [r for r in full if not r.get("far")] + [r for r in full if r.get("far")], True


DINING_WAIT = 25.0          # seconds the activities agent waits for the restaurant lookup


def _dining_result(future) -> dict:
    """The restaurant lookup, cleaned. Never raises: a failed lookup just means no restaurant section."""
    empty = {"veg": [], "nonveg": [], "other": [], "data_quality": "none", "attribution": [], "note": ""}
    try:
        res = future.result(timeout=DINING_WAIT)
    except Exception as e:                                       # noqa: BLE001 - dining must never break a plan
        return {**empty, "note": f"Restaurant lookup unavailable ({guardrails.sanitize_untrusted(str(e), 80)})."}
    if not isinstance(res, dict):
        return empty

    def clean(items, n):
        out = []
        for it in (items or [])[:n]:
            if not isinstance(it, dict) or not it.get("name"):
                continue
            out.append({"name": guardrails.sanitize_untrusted(str(it["name"]), 70),
                        "serves": it.get("serves") if it.get("serves") in ("veg", "both", "nonveg", "unknown") else "unknown",
                        "cuisine": guardrails.sanitize_untrusted(str(it.get("cuisine") or ""), 50),
                        "hours": guardrails.sanitize_untrusted(str(it.get("hours") or ""), 90),
                        "hours_known": bool(it.get("hours_known")),
                        "best_time": guardrails.sanitize_untrusted(str(it.get("best_time") or ""), 90),
                        "desc": guardrails.sanitize_untrusted(str(it.get("desc") or ""), 140),
                        "source": it.get("source") if it.get("source") in ("osm", "wikivoyage") else ""})
        return out
    return {"veg": clean(res.get("veg"), 6), "nonveg": clean(res.get("nonveg"), 6), "other": clean(res.get("other"), 4),
            "data_quality": str(res.get("data_quality") or "none")[:30],
            "attribution": [str(a)[:120] for a in (res.get("attribution") or [])][:4],
            "note": guardrails.sanitize_untrusted(str(res.get("note") or ""), 400)}


def _data_quality_warning(quality: str | None, name: str) -> list[str]:
    if quality == "osm":
        return [f"Sights for {name} come from open data (OpenStreetMap, Wikipedia, Wikivoyage). Entry fees are rough estimates based on "
                "the type of place and the country's price level; check opening times and prices before you go."]
    if quality == "generic":
        return [f"Detailed place data for {name} could not be loaded, so the day plans use generic suggestions "
                "(walking tour, market, dinner). Try again later to get named sights."]
    return []


def _llm_note(deps, role: str, used: bool) -> str:
    """' (LLM unavailable: why)' when a provider was configured for the role but gave no usable answer."""
    llm = getattr(deps, "llm", None)
    if used or not llm or not llm.available(role) or not llm.last_failure:
        return ""
    return f" (LLM unavailable, rule-based used: {llm.last_failure})"


def activities_node(state: dict, deps) -> dict:
    if not _in_fanout(state, "activities"):
        return {}
    c = state["constraints"]
    pool = ThreadPoolExecutor(max_workers=1)                    # restaurants are looked up while the sights are
    f_dine = pool.submit(call_with_retry, deps.tools, "search_dining", retries=1, sleep=deps.sleep,
                         destination=c["destination"], destination_geo=c.get("destination_geo"))
    pool.shutdown(wait=False)
    try:
        res = call_with_retry(deps.tools, "search_places", sleep=deps.sleep, destination=c["destination"],
                              preferences=c["preferences"], destination_geo=c.get("destination_geo"))
        cands = [x for x in (_clean_candidate(p) for p in res["candidates"]) if x]
        if not cands:
            raise ValueError("no usable places returned")
    except (ToolError, KeyError, ValueError) as e:
        out = _fail("activities", "activities", e, "Places lookup")
        out["activities"] = {"error": str(e), "candidates": [], "tips": [], "nearby": []}
        return out
    excluded = state.get("excluded") or []
    if excluded:                                                 # "skip water sports" is a hard rule
        cands = [x for x in cands if not any(matches_excluded(x, t) for t in excluded)]
    ranked = rank_candidates(cands, c["preferences"], state["strategy"], state.get("food_boost", False))
    ranked, used_llm = _llm_rerank(ranked, c, deps)
    ranked = group_mod.fair_order(ranked, state.get("group") or [])
    tips = [{"text": clip(guardrails.sanitize_untrusted(t["text"], 600), 300), "source": t.get("source", "")}
            for t in res.get("tips", [])]
    nearby = [{"name": guardrails.sanitize_untrusted(n["name"], 80), "kind": n.get("kind", "")}
              for n in res.get("nearby", [])]
    quality = res.get("data_quality")
    notes = _data_quality_warning(quality, place_name(c, "destination"))
    dine = _dining_result(f_dine)
    attribution = list(dict.fromkeys(list(res.get("attribution", [])) + dine["attribution"]))
    out = {"activities": {"candidates": ranked, "tips": tips, "nearby": nearby, "estimated": True,
                          "attribution": attribution, "llm_reranked": used_llm,
                          "data_quality": quality, "top_sights": guide.top_sights(cands),
                          "top_sights_note": guide.NOTE, "dining": dine}, "warnings": notes,
            "log": [entry("activities", f"{len(ranked)} candidates for strategy '{state['strategy']}'"
                                        + (" (LLM re-ranked)" if used_llm else "")
                                        + _llm_note(deps, "activities", used_llm)
                                        + (f" [{quality} data]" if quality and quality != "curated" else ""))]}
    return out


# ------------------------------------------------------------------- merge
def merge_node(state: dict, deps) -> dict:
    c = state["constraints"]
    flight = (state.get("flight") or {}).get("selected")
    hotel = (state.get("hotel") or {}).get("selected")
    cands = (state.get("activities") or {}).get("candidates", [])
    itin, warns = build_itinerary(c, flight, hotel, state.get("weather"), cands)
    nact = sum(1 for d in itin["days"] for it in d["items"] if it["type"] == "activity")
    log = [entry("merge", f"{len(itin['days'])} days, {nact} activities, {len(itin['swaps'])} rain swaps")]
    group = state.get("group") or []
    report = group_mod.satisfaction(group, itin) if group else []
    for m in report:
        if m["likes"] and not m["matched"]:
            warns.append(f"Group: nothing planned matches what {m['name']} likes ({', '.join(m['likes'])}). "
                         "No suitable place fitted the dates and budget tier.")
    return {"itinerary": itin, "group_report": report, "warnings": warns, "log": log}


# ------------------------------------------------------------------ budget
def budget_node(state: dict, deps) -> dict:
    c = state["constraints"]
    strategy = state.get("strategy", "normal")
    fl = (state.get("flight") or {}).get("selected")
    ho = (state.get("hotel") or {}).get("selected")
    lines = {
        "flight": fl["price_pp"] * c["travelers"] if fl else 0,
        "hotel": ho["price_night_per_room"] * ho["nights"] * ho["rooms"] if ho else 0,
        "activities": sum(it["cost_total"] for d in (state.get("itinerary") or {}).get("days", [])
                          for it in d["items"] if it["type"] == "activity"),
        "food": checks.food_line(c, strategy, state.get("food_boost", False)),
    }
    total = sum(lines.values())
    over = total > c["budget"]
    incomplete = [k for k, v in (("flight", fl), ("hotel", ho)) if v is None]
    report = {"currency": "INR", "lines": lines, "total": total, "budget": c["budget"], "over_budget": over,
              "remaining": c["budget"] - total, "per_person": round(total / c["travelers"]),
              "strategy": strategy, "estimated": True, "incomplete": incomplete,
              "live": [k for k, blk in (("flight", state.get("flight")), ("hotel", state.get("hotel")))
                       if (blk or {}).get("live") and (blk or {}).get("selected")]}
    replan = "over_budget" if over and state.get("retries", 0) < config.MAX_AUTO_REPLANS else None
    msg = f"total {fmt_inr(total)} vs budget {fmt_inr(c['budget'])} ({'OVER' if over else 'ok'})"
    return {"budget_report": report, "replan_reason": replan, "log": [entry("budget", msg)]}


# ------------------------------------------------------------------ critic
def critic_node(state: dict, deps) -> dict:
    issues = (checks.check_dates(state) + checks.check_hotel_nights(state) + checks.check_itinerary(state)
              + checks.verify_prices_and_totals(state))
    br = state["budget_report"]
    new_warnings: list[str] = []
    if br["incomplete"]:
        issues.append(checks.issue("warning", "partial_plan",
                                   f"Plan is incomplete: no {', '.join(br['incomplete'])} data."))
    blocking = [i for i in issues if i["severity"] == "blocking"]
    replan = "critic" if blocking and state.get("retries", 0) < config.MAX_AUTO_REPLANS else None
    if blocking and replan is None:
        new_warnings.append("Unresolved issue(s) after the retry limit: " + "; ".join(i["message"] for i in blocking))
    if br["over_budget"]:
        new_warnings.append(
            f"Estimated total {fmt_inr(br['total'])} is {fmt_inr(br['total'] - br['budget'])} over your "
            f"{fmt_inr(br['budget'])} budget" + (" even on the cheapest options." if state["strategy"] == "cheapest"
                                                 else " after the automatic retries."))
    if br["incomplete"]:
        new_warnings.append(f"Partial plan: {', '.join(br['incomplete'])} unavailable; totals understate the cost.")
    return {"critic_issues": issues, "replan_reason": replan, "warnings": new_warnings,
            "log": [entry("critic", f"{len(blocking)} blocking, {len(issues) - len(blocking)} warning issue(s)")]}


# ------------------------------------------------------------ alternatives
def _alternatives(state: dict, deps) -> dict:
    """Other destinations for the same dates, group and budget, with the current one priced the same way."""
    c = state.get("constraints") or {}
    if not c.get("destination") or not c.get("budget"):
        return {}
    try:
        res = call_with_retry(deps.tools, "recommend_destinations", retries=1, sleep=deps.sleep,
                              origin=c["origin"], start_date=c["start_date"], days=c["days"],
                              travelers=c["travelers"], budget=c["budget"], preferences=c.get("preferences") or [],
                              exclude=c["destination"], origin_geo=c.get("origin_geo"),
                              exclude_geo=c.get("destination_geo"), limit=3)
        return {"items": res["suggestions"], "baseline": res.get("baseline"), "estimated": True}
    except (ToolError, KeyError, ValueError):
        return {}


# ----------------------------------------------------- present / approval
def present_node(state: dict, deps) -> dict:
    br = state.get("budget_report") or {}
    left = config.MAX_REVISIONS - state.get("revisions", 0)
    msg = (f"Plan ready: {fmt_inr(br.get('total', 0))} estimated of {fmt_inr(br.get('budget', 0))} budget. "
           f"Approve to book (mock), or request changes ({max(left, 0)} revision(s) left).")
    if state.get("notice"):
        msg = f"{state['notice']} {msg}"
    alternatives = _alternatives(state, deps)
    return {"status": "awaiting_approval", "approved": False, "message": msg, "notice": "",
            "alternatives": alternatives,
            "pending_approval": {"can_revise": left > 0, "revisions_left": max(left, 0),
                                 "auto_replans_used": state.get("retries", 0)},
            "summary": render_summary({**state, "alternatives": alternatives}),
            "log": [entry("present", "awaiting human approval")]}


def _find_place(name: str, deps) -> tuple[dict | None, str]:
    try:
        return geo_mod.resolve(name, live=False), ""
    except geo_mod.PlaceError as e:
        reason = str(e)
    if deps is None:
        return None, reason
    try:
        return call_with_retry(deps.tools, "resolve_place", sleep=deps.sleep, query=name)["geo"], ""
    except (ToolError, KeyError) as e:
        return None, str(e)


def _mode_problem(c: dict, deps) -> str:
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


def _apply_changes(state: dict, ch: dict, notes: list[str], deps) -> tuple[dict, dict, list[str]]:
    """Check each requested change and apply the possible ones.
    Returns (state update, applied changes, plain-language notes)."""
    c = dict(state["constraints"])
    ch = dict(ch)
    notes = list(notes)

    def reject(key: str, word: str, why: str) -> None:
        ch.pop(key, None)
        notes[:] = [n for n in notes if word not in n]
        notes.append(why)

    if "days" in ch and not config.MIN_DAYS <= ch["days"] <= config.MAX_DAYS:
        reject("days", " days.", f"I can plan trips of {config.MIN_DAYS} to {config.MAX_DAYS} days.")
    if "travelers" in ch and not 1 <= ch["travelers"] <= config.MAX_TRAVELERS:
        reject("travelers", " travelers.", f"I can plan for 1 to {config.MAX_TRAVELERS} travelers.")
    if "travelers" in ch and state.get("group") and ch["travelers"] < len(state["group"]):
        reject("travelers", " travelers.", f"Your group list has {len(state['group'])} people. Start a new plan "
                                           "to change who is in the group.")
    for key in ("budget", "pace", "days", "travelers"):
        if key in ch:
            c[key] = ch[key]
    if "month_day" in ch:
        month, day = ch["month_day"]
        start, _ = intake_mod.compute_start_date(month, day, date.fromisoformat(c["today"]))
        if start.isoformat() == c["start_date"]:
            reject("month_day", "travel dates", "The trip already starts on that date.")
        else:
            c.update(start_date=start.isoformat(), month=month)
            notes[:] = [f"Trip now starts {start.isoformat()}." if "travel dates" in n else n for n in notes]
    if "destination" in ch:
        geo, why = _find_place(ch["destination"], deps)
        if geo is None:
            reject("destination", "destination to", why)
        elif geo["slug"] == c["destination"]:
            reject("destination", "destination to", f"The trip already goes to {geo['name']}.")
        elif geo["slug"] == c["origin"] or (c.get("origin_geo")
                                            and geo_mod.distance_km(c["origin_geo"], geo) < 15):
            reject("destination", "destination to", "Origin and destination are the same place.")
        else:
            c.update(destination=geo["slug"], destination_geo=geo)
    if "travel_mode" in ch:
        c["travel_mode"] = ch["travel_mode"]
    if "destination" in ch or "travel_mode" in ch:
        why = _mode_problem(c, deps)
        if why:
            old = state["constraints"]
            if "destination" in ch:
                c.update(destination=old["destination"], destination_geo=old.get("destination_geo"))
                reject("destination", "destination to", why + " Add 'go by flight' to change both together.")
            if "travel_mode" in ch:
                c["travel_mode"] = old.get("travel_mode")
                reject("travel_mode", "Travelling by", "" if why in " ".join(notes) else why)

    excluded = list(state.get("excluded") or [])
    if "exclude" in ch:
        cands = (state.get("activities") or {}).get("candidates", [])
        found = []
        for term in ch["exclude"]:
            if any(matches_excluded(x, term) for x in cands):
                found.append(term)
                notes.append(f"Leaving out: {term}.")
                c["preferences"] = [p for p in c.get("preferences", []) if p != term]
            else:
                notes.append(f"Nothing in this plan matches '{term}'.")
        excluded = list(dict.fromkeys(excluded + found))
        if found:
            ch["exclude"] = found
        else:
            ch.pop("exclude")
    if ch.get("preferences_add"):
        c["preferences"] = list(dict.fromkeys(list(c["preferences"]) + ch["preferences_add"]))
    if "travelers" in ch and "budget" not in ch:
        notes.append(f"The total budget stays {fmt_inr(c['budget'])}.")

    update: dict = {"constraints": c, "excluded": excluded}
    if {"destination", "days", "month_day"} & set(ch):
        update["weather"] = None                                   # dates or place moved: fetch weather again
    if "destination" in ch:
        update.update(activities=None, excluded=[])
    if {"destination", "days", "month_day", "travel_mode"} & set(ch):
        update["warnings"] = [RESET] + _trip_warnings(c)           # old trip warnings no longer apply
    return update, ch, [n for n in notes if n]


def approval_node(state: dict, decision: dict, deps=None) -> dict:
    """Apply the human's decision. A function of (state, decision); ``deps`` is only used to check that a new
    destination or travel mode is possible."""
    action = (decision or {}).get("action")
    base = {"decision": decision}
    if action == "approve":
        return {**base, "approved": True, "replan_reason": None, "log": [entry("approval", "approved")]}
    if action == "cancel":
        return {**base, "status": "cancelled", "approved": False, "replan_reason": None,
                "message": "Trip cancelled. Nothing was booked.", "log": [entry("approval", "cancelled")]}
    if action != "revise":
        return {**base, "replan_reason": None, "notice": "Unknown action. Use approve, revise or cancel.",
                "log": [entry("approval", f"unknown action {action!r}")]}
    text = (decision.get("feedback") or "").strip()
    g = guardrails.check_input(text, require_topic=False)
    if not g["allowed"]:
        return {**base, "replan_reason": None, "notice": g["message"],
                "log": [entry("approval", f"feedback blocked: {g['code']}")]}
    if state.get("revisions", 0) >= config.MAX_REVISIONS:
        return {**base, "replan_reason": None, "pending_approval": {"can_revise": False, "revisions_left": 0,
                                                                     "auto_replans_used": state.get("retries", 0)},
                "warnings": ["Revision limit reached: approve this plan or cancel."],
                "notice": "Revision limit reached: approve this plan or cancel.",
                "log": [entry("approval", "revision cap reached")]}
    fb = parse_feedback(text, state["constraints"], state.get("strategy", "normal"))
    if not fb["recognized"]:
        return {**base, "replan_reason": None,
                "notice": "I couldn't tell what to change. Try: 'make it cheaper', 'budget 80000', 'make it 4 "
                          "days', 'add 1 person', 'move it to January', 'go by train', 'change destination to "
                          "Jaipur', 'skip water sports', 'more food' or 'relaxed pace'.",
                "log": [entry("approval", "feedback not understood")]}
    update, ch, notes = _apply_changes(state, fb["changes"], fb["notes"], deps) if fb["changes"] \
        else ({}, {}, fb["notes"])
    if not ch:                      # recognised but nothing to do (e.g. already cheapest, or not possible)
        return {**base, "replan_reason": None, "notice": " ".join(notes),
                "log": [entry("approval", "no-op feedback: " + " ".join(notes))]}
    return {**base, **update, "strategy": ch.get("strategy", state.get("strategy", "normal")),
            "food_boost": ch.get("food_boost", state.get("food_boost", False)),
            "revisions": state.get("revisions", 0) + 1, "replan_reason": "feedback", "approved": False,
            "status": "running", "notice": " ".join(notes),
            "log": [entry("approval", "revise: " + " ".join(notes))]}


# -------------------------------------------------------------------- book
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


# ------------------------------------------------------------------ writer
def _fmt_day(d: dict) -> str:
    dt = date.fromisoformat(d["date"])
    w = d.get("weather")
    wx = f" - {w['tmax']}°/{w['tmin']}°C, {w['precip_prob']}% rain{' (RAINY)' if w['rainy'] else ''}" if w else ""
    return f"**Day {d['day']} - {dt.strftime('%a %d %b')} ({d['kind']}){wx}**"


def render_summary(state: dict) -> str:
    c = state["constraints"]
    it, br = state.get("itinerary"), state.get("budget_report")
    if not it or not br:
        return ""
    name = place_name(c, "destination")
    fl = (state.get("flight") or {}).get("selected")
    ho = (state.get("hotel") or {}).get("selected")
    L = [f"# {c['days']}-day trip to {name} ({it['start_date']} to {it['end_date']})",
         f"{c['travelers']} traveler(s) from {place_name(c, 'origin')} - strategy: {state.get('strategy', 'normal')}", ""]
    heading = _travel_heading(fl)
    L.append(f"## {heading} ({_price_tag(state.get('flight'))})")
    L.append(f"{fl['label']}: out {fl['depart_out']} (arrive {fl['arrive_out']}), back {fl['depart_back']} - "
             f"{fmt_inr(fl['price_pp'])} per person round trip" if fl else "Not available (tool failure).")
    if fl and fl.get("note"):
        L.append(fl["note"])
    journey = (state.get("flight") or {}).get("journey") if fl else None
    if journey and journey["extra_days"]:
        L.append(f"Leave home on {_day(journey['leave_date'])}; back home on {_day(journey['home_date'])}.")
    if journey and journey["warning"]:
        L.append(journey["warning"])
    emissions = (state.get("flight") or {}).get("footprint") if fl else None
    if emissions:
        L.append(f"Travel emissions, there and back: about {emissions['kg_pp']:g} kg CO2e per person (estimate).")
    L.append(f"\n## Hotel ({_price_tag(state.get('hotel'))})")
    L.append(f"{ho['label']}: {fmt_inr(ho['price_night_per_room'])}/room/night x {ho['nights']} nights x "
             f"{ho['rooms']} room(s)" if ho else "Not available (tool failure).")
    if ho and (state.get("hotel") or {}).get("fx_note"):
        L.append(state["hotel"]["fx_note"])
    wsrc = (state.get("weather") or {}).get("source")
    L.append(f"\n## Day by day (weather: {wsrc or 'unavailable'})")
    for d in it["days"]:
        L.append(_fmt_day(d))
        for x in d["items"]:
            cost = f" - {fmt_inr(x['cost_total'])}" if x["type"] == "activity" and x["cost_total"] else ""
            L.append(f"- {x['start']}-{x['end']} {x['name']}{cost}")
        for n in d["notes"]:
            L.append(f"  - {n}")
    acts = state.get("activities") or {}
    top = acts.get("top_sights") or []
    if top:
        planned = {x["name"]: f"Day {d['day']} {x['start']}" for d in it["days"] for x in d["items"]
                   if x["type"] == "activity"}
        L.append("\n## Top sights (most prominent first)")
        for t in top:
            extra = f" - planned {planned[t['name']]}" if t["name"] in planned else ""
            L.append(f"{t['rank']}. {t['name']} ({t['label']}): best {t['best_time'][0].lower() + t['best_time'][1:]}"
                     + (f". {t['season']}" if t.get("season") else "") + extra)
        L.append(f"  - {acts.get('top_sights_note', '')}")
    dn = acts.get("dining") or {}
    if dn.get("veg") or dn.get("nonveg") or dn.get("other"):
        L.append("\n## Where to eat")
        for title, key in (("Vegetarian", "veg"), ("Non-vegetarian", "nonveg"), ("Restaurants (menu not specified)" if not (dn.get("veg") or dn.get("nonveg")) else "More places (menu not specified)", "other")):
            if dn.get(key):
                L.append(f"**{title}**")
                for i, r in enumerate(dn[key], 1):
                    cu = f" - {r['cuisine']}" if r.get("cuisine") else ""
                    L.append(f"{i}. {r['name']}{cu}: {r['hours']}. Best: {r['best_time']}")
        L.append(f"  - {dn.get('note', '')}")
    if state.get("group_report"):
        L.append("\n## Group fit")
        for m in state["group_report"]:
            wants = f" (likes {', '.join(m['likes'])})" if m["likes"] else ""
            L.append(f"- {m['name']}{wants}: {len(m['matched'])} of {m['activities']} activities match"
                     + (f"; {len(m['conflicts'])} touch something they wanted to avoid" if m["conflicts"] else ""))
    L.append("\n## Budget (estimated)")
    for k, v in br["lines"].items():
        L.append(f"- {k.title()}: {fmt_inr(v)}")
    status = "OVER budget" if br["over_budget"] else "within budget"
    L.append(f"- **Total: {fmt_inr(br['total'])}** of {fmt_inr(br['budget'])} ({status}); "
             f"{fmt_inr(br['per_person'])} per person")
    alts = (state.get("alternatives") or {}).get("items") or []
    if alts and br["over_budget"]:
        L.append("\n## Other places to consider (estimated cheapest totals)")
        L += [f"- {a['name']}, {a['country']}: from about {fmt_inr(a['estimate_from'])}" for a in alts]
    if state.get("warnings"):
        L.append("\n## Warnings")
        L += [f"- {w}" for w in dict.fromkeys(state["warnings"])]
    live_flight, live_hotel = (bool((state.get(k) or {}).get("live") and (state.get(k) or {}).get("selected"))
                               for k in ("flight", "hotel"))
    if live_flight and live_hotel:
        L.append("\nFlight and hotel prices are live listings read from Google Flights and Google Hotels; they can "
                 "change and are not a booking. Activities and food are estimates.")
    elif live_flight or live_hotel:
        L.append(f"\nThe {'flight' if live_flight else 'hotel'} price is a live Google listing and can change; the "
                 f"{'hotel' if live_flight else heading.lower()} price is a synthetic ESTIMATE, as are activities and "
                 "food.")
    else:
        L.append(f"\n{heading} and hotel prices are synthetic ESTIMATES, not live fares.")
    if state.get("booking"):
        L.append(f"\n## Booking\n{state['booking']['booking_id']}: {state['booking']['status']}")
    return "\n".join(L)


_WRITER_SCHEMA = {"type": "object", "required": ["overview"],
                  "properties": {"overview": {"type": "string"}}}


def numbers_are_grounded(text: str, allowed: set[int]) -> bool:
    """Every rupee amount in LLM text must be one of the plan's own figures."""
    for m in re.finditer(r"₹\s?([\d,]+)", text):
        try:
            if int(m.group(1).replace(",", "")) not in allowed:
                return False
        except ValueError:
            return False
    return not re.search(r"\b(?:rs\.?|inr)\s?\d", text, re.I)


def _allowed_amounts(state: dict) -> set[int]:
    br = state["budget_report"]
    vals = set(br["lines"].values()) | {br["total"], br["budget"], br["per_person"], abs(br["remaining"])}
    fl = (state.get("flight") or {}).get("selected")
    ho = (state.get("hotel") or {}).get("selected")
    if fl:
        vals.add(fl["price_pp"])
    if ho:
        vals.add(ho["price_night_per_room"])
    for d in state["itinerary"]["days"]:
        for it in d["items"]:
            if it["type"] == "activity":
                vals.update({it["cost_pp"], it["cost_total"]})
    return vals


def writer_node(state: dict, deps) -> dict:
    template = render_summary(state)
    overview, used = "", False
    if deps.llm and deps.llm.available("writer"):
        import json
        facts = {"destination": place_name(state["constraints"], "destination"),
                 "days": [{"day": d["day"], "date": d["date"],
                           "highlights": [x["name"] for x in d["items"] if x["type"] == "activity"],
                           "rainy": d["rainy"]} for d in state["itinerary"]["days"]],
                 "total_inr": state["budget_report"]["total"], "budget_inr": state["budget_report"]["budget"],
                 "over_budget": state["budget_report"]["over_budget"],
                 "warnings": list(dict.fromkeys(state.get("warnings", [])))}
        system = ("Write a friendly 80-120 word overview of this trip plan. Use ONLY the facts given. Do not "
                  "invent places, prices or times. If you mention money, use the exact rupee figures provided "
                  "with the symbol ₹. Return {\"overview\": \"...\"}.")
        obj = deps.llm.complete_json("writer", system, json.dumps(facts), _WRITER_SCHEMA)
        if obj and numbers_are_grounded(obj["overview"], _allowed_amounts(state)):
            overview, used = guardrails.sanitize_untrusted(obj["overview"], 900), True
    text = (f"{overview}\n\n---\n\n{template}" if overview else template)
    return {"summary": text, "log": [entry("writer", ("LLM overview + template" if used else "template summary")
                                           + _llm_note(deps, "writer", used))]}
