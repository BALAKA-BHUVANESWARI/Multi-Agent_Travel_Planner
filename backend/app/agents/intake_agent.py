"""Intake agent: turns a plain-language request into structured trip constraints,
and asks when something is missing."""
from __future__ import annotations

import re
from datetime import date, timedelta

from app.agents.destination_agent import (
    _PLACE_TEXT,
    _WANTS_IDEAS,
    doubt_message,
    find_suggestions,
    resolve_places,
    suggestion_message,
    trip_warnings,
)
from app.agents.transport_agent import build_travel_options, travel_options_message
from app.core import config
from app.core.utils import fmt_inr
from app.graph.state import entry
from app.services import ai_guard, fact_checks
from app.services import geo_service as geo_mod
from app.services import group_service as group_mod
from app.services import request_parser as intake_mod
from app.tools.client import call_with_retry
from app.tools.errors import ToolError
from app.observability import recorder as observe

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
            observe.event("guardrail", "ai_invented_destination", "rejected", detail=v)
            continue                        # asked for ideas and never named it: offer suggestions instead
        if c[role] is None and isinstance(v, str) and _PLACE_TEXT.match(v.strip()):
            if role not in texts:
                texts[role] = v.strip()
            elif v.strip().lower() != texts[role].lower():
                alts[role] = v.strip()          # keep the rule-based candidate; try this one as a second choice
            else:
                continue
            filled.append(role)
    refused = {}                            # a trip length or budget the traveller's words do not state
    for field, key in (("days", "days"), ("budget", "budget_inr")):
        if c[field] is None and isinstance(obj.get(key), int):
            if ai_guard.typed_value(field, obj[key], text):
                c[field] = obj[key]; filled.append(field)
            else:
                refused[field] = obj[key]
                observe.event("guardrail", "ai_filled_value", "rejected", field=field)
    if not c["preferences"] and obj.get("preferences"):
        known = set(intake_mod.PREF_WORDS)
        c["preferences"] = [p for p in obj["preferences"] if p in known]
        if c["preferences"]:
            filled.append("preferences")
    parsed["missing"] = [k for k in ("origin", "destination", "days", "budget")
                         if c[k] is None and k not in texts]
    values = {k: obj.get("budget_inr" if k == "budget" else k) for k in filled}
    if "preferences" in values:
        values["preferences"] = c["preferences"]                # only the interests that were kept
    fact_checks.record_request_values(text, {**values, **refused}, used=not refused)
    return filled


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
    resolve_places(parsed, deps, logs)
    c = parsed["constraints"]
    if parsed.get("place_check"):
        check = parsed["place_check"]
        return {"constraints": c, "status": "needs_info", "message": doubt_message(check), "place_check": check,
                "log": logs}
    for role in ("origin", "destination"):                 # a place that is still unresolved is "missing"
        if c[role] is None and role not in parsed["invalid"] and role not in parsed["missing"]:
            parsed["missing"].append(role)
    if c["days"] is not None and "days" not in parsed["invalid"] and not (config.MIN_DAYS <= c["days"] <= config.MAX_DAYS):
        parsed["invalid"]["days"] = f"I can plan trips of {config.MIN_DAYS} to {config.MAX_DAYS} days."
    if parsed["missing"] or parsed["invalid"]:
        msg = intake_mod.build_question(parsed["missing"], parsed["invalid"])
        if parsed["missing"] == ["destination"] and not parsed["invalid"] and c.get("origin_geo"):
            items = find_suggestions(c, state["request"], deps)
            if items:
                return {"constraints": c, "status": "needs_info", "suggestions": items,
                        "message": suggestion_message(c, items, any(s["fits_budget"] for s in items)),
                        "log": logs + [entry("intake", "no destination: suggested "
                                             + ", ".join(s["name"] for s in items))]}
        return {"constraints": c, "status": "needs_info", "message": msg,
                "log": logs + [entry("intake", f"needs info: {parsed['missing'] or list(parsed['invalid'])}")]}
    og, dg = c["origin_geo"], c["destination_geo"]
    if c["origin"] == c["destination"] or geo_mod.distance_km(og, dg) < 15:
        return {"constraints": c, "status": "needs_info", "message": "Origin and destination are the same place.",
                "log": logs + [entry("intake", "origin == destination")]}
    if c.get("travel_mode") is None and getattr(deps, "ask_travel_mode", False):
        options = build_travel_options(c, deps, memory.get("travel_mode"))
        return {"constraints": c, "status": "needs_info", "message": travel_options_message(c, options),
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
            options = build_travel_options(c, deps)
            return {"constraints": {**c, "travel_mode": None}, "status": "needs_info", "travel_options": options,
                    "message": f"{e} " + travel_options_message(c, options),
                    "log": logs + [entry("intake", f"{c['travel_mode']} not possible: {e}")]}
    warnings += trip_warnings(c)
    return {"constraints": c, "status": "running", "message": "", "warnings": warnings,
            "log": logs + [entry("intake", f"parsed: {c['days']}d {og['name']}->{dg['name']} "
                                           f"budget {fmt_inr(c['budget'])} x{c['travelers']}")]}
