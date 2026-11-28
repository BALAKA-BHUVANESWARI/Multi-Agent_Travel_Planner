"""Destination agent: finds the places named in a request, suggests destinations
and offers alternatives."""
from __future__ import annotations

import re

from app.core.utils import fmt_inr
from app.data import gazetteer
from app.data.curated_destinations import place_name
from app.graph.state import entry
from app.services import geo_service as geo_mod
from app.services import request_parser as intake_mod
from app.tools.client import call_with_retry
from app.tools.errors import ToolError
from app.observability import recorder as observe

_PLACE_TEXT = re.compile(r"^[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f .'\u2019-]{1,59}$")


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


def _answered(parsed: dict, q: str) -> tuple[str, bool]:
    """The name to look up for ``q`` after the traveller's "Did you mean" answer, and whether they insisted on
    the name they typed."""
    chosen = (parsed.get("place_answers") or {}).get(gazetteer.normalize(q))
    if not chosen:
        return q, False
    return chosen, gazetteer.normalize(chosen) == gazetteer.normalize(q)


def doubt_message(check: dict) -> str:
    return (f"I only found “{check['typed']}” as a very small place: {check['found_label']}. "
            f"Did you mean {check['suggested_label']}? Reply “{check['suggested']}” or “{check['typed']}”.")


def resolve_places(parsed: dict, deps, logs: list) -> None:
    """Turn place names into resolved places (coordinates, country, price level).
    Known places (curated + offline list) are resolved locally; anything else needs the live
    place-lookup tool, which is only called once nothing else is missing."""
    c = parsed["constraints"]
    parsed.setdefault("texts", {})
    for role in ("origin", "destination"):
        for q in _place_candidates(parsed, role):
            try:
                _set_place(parsed, role, geo_mod.resolve(_answered(parsed, q)[0], live=False))
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
            name, insisted = _answered(parsed, q)
            try:
                res = call_with_retry(deps.tools, "resolve_place", sleep=deps.sleep, query=name)
            except ToolError as e:
                error = error or str(e)
                logs.append(entry("intake", f"could not resolve {role} '{name}'"))
                continue
            meant = None if insisted else geo_mod.meant_instead(name, res["geo"])
            if meant:                                    # probably misspelled or misheard: ask, never guess
                parsed["place_check"] = {"role": role, "typed": name, "suggested": meant["name"],
                                         "suggested_label": geo_mod.full_label(meant),
                                         "found_label": geo_mod.full_label(res["geo"])}
                observe.event("guardrail", "place_check", "warnings", role=role)
                logs.append(entry("intake", f"asked whether {role} meant a better-known place"))
                return
            _set_place(parsed, role, res["geo"])
            logs.append(entry("intake", f"resolved {role} '{q}' -> {res['geo']['name']}, "
                                        f"{res['geo']['country']} ({res['geo']['source']})"))
            break
        else:
            if error:
                parsed["invalid"][role] = error


ROAD_NOTE = ("Road and rail times and prices are estimated from the straight-line distance: check that a direct "
             "route exists and book real tickets before you go.")


def find_suggestions(c: dict, text: str, deps) -> list[dict]:
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


def suggestion_message(c: dict, items: list[dict], any_fit: bool) -> str:
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


def trip_warnings(c: dict) -> list[str]:
    """Warnings that follow from where and how the trip goes (used at intake and after such a change)."""
    out = []
    if c.get("travel_mode") in ("train", "bus", "car", "bike"):
        out.append(ROAD_NOTE)
    og, dg = c.get("origin_geo") or {}, c.get("destination_geo") or {}
    if og.get("cc") and dg.get("cc") and og["cc"] != dg["cc"]:
        out.append(f"International trip ({og['country']} to {dg['country']}): passport, visa or entry rules, "
                   "travel insurance and currency-exchange costs are not included in this estimate.")
    return out


def find_alternatives(state: dict, deps) -> dict:
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


def find_place(name: str, deps) -> tuple[dict | None, str]:
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
