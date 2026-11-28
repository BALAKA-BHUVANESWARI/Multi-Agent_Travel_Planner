"""Source grounding: can every external detail in the plan be traced to what a source really answered, is it
labelled truthfully, and is it fresh?

The *source records* are the tool answers kept while the plan was made. The plan and its written summary are
compared with them. Where an AI model is involved, a scripted pretend AI makes things up on purpose: nothing it
invents may reach the traveller or stand in for missing data.

Offline the sources are the application's own price estimator and curated lists. These checks do not say whether
a source is right about the world.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.evaluators.transport import check_label, check_traceable
from evaluation.results import Result

_URL = re.compile(r"(?:https?:|www\.)[^\s\"'<>)\]]+", re.I)
_MONEY = re.compile(r"₹\s?(\d[\d,]*)")
_LINE = re.compile(r"^- (\d\d:\d\d)-(\d\d:\d\d) (.+?)(?: - ₹[\d,]+)?$", re.M)
# which provenance fields can be asked for, and what carries each one
PROVENANCE = {"source": ("source", "attribution"), "reference": ("url", "reference"),
              "retrieved_at": ("fetched_at", "retrieved_at"), "currency": ("currency",),
              "status": ("estimated", "live")}
KINDS = {"flight": "travel", "hotel": "hotel", "weather": "weather", "activities": "places"}


def _numbers(value) -> set:
    """Every number in nested data."""
    if isinstance(value, dict):
        return set().union(*map(_numbers, value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*map(_numbers, value)) if value else set()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return set()
    return {round(value)}


def _strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _sources(run: dict, tool: str) -> list[dict]:
    return [c["result"] for c in common.calls(run, tool) if c["result"] is not None]


def check_provenance(checks: Checks, run: dict) -> None:
    """Every block that holds outside data names its source and says whether it is an estimate."""
    state = run["state"]
    for key, what in KINDS.items():
        block = state.get(key) or {}
        if block.get("error"):
            empty = not block.get("selected") and not block.get("days") and not block.get("candidates")
            checks.need(empty, "unavailable_with_data", f"the {what} lookup failed, but data is still shown")
            continue
        checks.need(bool(block.get("source") or block.get("attribution")), "provider_missing",
                    f"the {what} data names no source")
        checks.need(isinstance(block.get("estimated"), bool), "status_missing",
                    f"the {what} data does not say whether it is an estimate")
    for key, tool in (("flight", "search_flights"), ("hotel", "search_hotels")):
        if (state.get(key) or {}).get("selected"):
            used = _sources(run, tool)
            checks.need(bool(used) and used[-1].get("currency") == state["budget_report"]["currency"],
                        "currency_missing", f"the {KINDS[key]} prices have no currency that matches the budget")


def check_claims(checks: Checks, run: dict) -> None:
    """Travel, hotel, weather and place details in the plan exist in what the sources answered."""
    state = run["state"]
    for key, tool, what, fields in (
            ("flight", "search_flights", "travel", ("label", "mode", "price_pp", "duration_h", "stops",
                                                   "airline", "route", "url")),
            ("hotel", "search_hotels", "hotel", ("label", "price_night_per_room", "rating", "stars",
                                                "amenities", "url"))):
        selected = (state.get(key) or {}).get("selected")
        if not selected:
            continue
        answers = _sources(run, tool)
        if checks.need(bool(answers), "unsupported_claim", f"a {what} is shown, but no source ever answered"):
            check_traceable(checks, state[key], answers[-1], selected, fields, what)
            for extra in ("airline", "route", "rating", "stars", "amenities", "url"):
                checks.need(extra not in selected or any(extra in o for o in answers[-1]["options"]),
                            "unsupported_claim", f"the {what} shows '{extra}', which no source gave")
    weather = (state.get("weather") or {}).get("days") or []
    if weather:
        given = [r for a in _sources(run, "get_weather") for r in a["days"]]
        checks.need(all(row in given for row in weather), "unsupported_weather",
                    "weather figures are shown that no source gave")
    places = [p for a in _sources(run, "search_places") for p in a["candidates"]]
    by_id = {p["id"]: p for p in places}
    for _, item in common.planned_activities(state):
        if item["id"] == "generic-indoor":
            continue
        source = by_id.get(item["id"])
        if not checks.need(source is not None, "unsupported_attraction",
                           f"'{item['name']}' is not in any places answer"):
            continue
        said = " ".join(str(item.get("desc") or "").split())
        checks.need(" ".join(str(source.get("desc") or "").split()).startswith(said.rstrip("…. ")),
                    "unsupported_detail", f"'{item['name']}': the description is not the source's: {said!r}")
        checks.need(set(item.get("tags", [])) <= set(source.get("tags", [])), "unsupported_detail",
                    f"'{item['name']}' is given kinds the source does not list")
        checks.need(item["cost_pp"] == source["cost"], "unsupported_price",
                    f"'{item['name']}': the plan says {item['cost_pp']}, the source {source['cost']}")
    names = {p["name"] for p in places}
    for sight in (state.get("activities") or {}).get("top_sights") or []:
        checks.need(sight["name"] in names, "unsupported_attraction", f"top sight '{sight['name']}' has no source")
    eateries = {e["name"] for a in _sources(run, "search_dining") for key in ("veg", "nonveg", "other")
                for e in a.get(key, [])}
    dining = (state.get("activities") or {}).get("dining") or {}
    for key in ("veg", "nonveg", "other"):
        for eatery in dining.get(key) or []:
            checks.need(eatery["name"] in eateries, "unsupported_eatery",
                        f"restaurant '{eatery['name']}' is not in any restaurant answer")


def check_summary(checks: Checks, run: dict) -> None:
    """The written plan states only prices and day-plan lines that the plan data backs."""
    state = run["state"]
    summary = str(state.get("summary") or "")
    if not checks.need(bool(summary), "no_summary", "there is no written plan to check"):
        return
    report = state["budget_report"]
    allowed = _numbers([c["result"] for calls in run["calls"].values() for c in calls if c["result"]])
    allowed |= _numbers(report) | {abs(report["remaining"])}
    for key in ("flight", "hotel"):
        allowed |= _numbers((state.get(key) or {}).get("selected") or {})
    allowed |= {i["cost_total"] for _, i in common.planned_activities(state)}
    unknown = sorted({m.group(0) for m in _MONEY.finditer(summary)
                      if int(m.group(1).replace(",", "")) not in allowed})
    checks.need(not unknown, "unsupported_price", f"the written plan states amounts that no data backs: {unknown}")
    items = {(i["start"], i["end"], i["name"]) for d in state["itinerary"]["days"] for i in d["items"]}
    strange = [name for start, end, name in _LINE.findall(summary) if (start, end, name) not in items]
    checks.need(not strange, "unsupported_attraction",
                f"the written plan lists things that are not in the day plan: {strange[:4]}")
    for key, title in (("flight", None), ("hotel", "Hotel")):
        block = state.get(key) or {}
        if not block.get("selected"):
            continue
        heading = re.search(rf"^## {title or '[A-Za-z/]+'} \((.*)\)$", summary, re.M)
        said = heading.group(1) if heading else ""
        if block.get("estimated"):
            checks.need(said == "estimated", "mock_labelled_real",
                        f"the written plan does not label the {KINDS[key]} price as estimated: {said!r}")
        else:
            checks.need(said.startswith("live: ") and str(block.get("source")) in said, "live_not_shown",
                        f"the written plan does not say where the live {KINDS[key]} price came from: {said!r}")


def check_links(checks: Checks, run: dict) -> None:
    """Any link in the plan is well formed and was given by a source."""
    given = json.dumps([c["result"] for calls in run["calls"].values() for c in calls if c["result"]],
                       ensure_ascii=False)
    plan = {k: v for k, v in run["state"].items() if k not in ("request", "log")}
    links = sorted({m.group(0).rstrip(".,;") for text in _strings(plan) for m in _URL.finditer(text)})
    for link in links:
        parts = urlsplit(link)
        checks.need(parts.scheme in ("http", "https") and "." in parts.netloc, "link_invalid",
                    f"not a usable web link: {link}")
        checks.need(link in given, "link_not_from_source", f"no source gave this link: {link}")
    checks.measured["links"] = len(links)
    if not links:
        checks.unchecked("no_links", "the plan has no source links, so none could be checked")


def check_freshness(checks: Checks, run: dict, limits: dict) -> None:
    """Live data says when it was fetched, and is not older than the case allows."""
    live = [k for k in ("flight", "hotel") if (run["state"].get(k) or {}).get("live")]
    checks.measured["live_parts"] = live
    for key in live:
        block = run["state"][key]
        checks.need(bool(block.get("source")), "provider_missing", f"the live {KINDS[key]} price names no source")
        try:
            fetched = datetime.fromisoformat(block["fetched_at"])
            age = (datetime.fromisoformat(limits["now"]) - fetched).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            checks.need(False, "retrieval_time_missing", f"the live {KINDS[key]} price has no usable fetch time")
            continue
        checks.need(age >= 0, "retrieval_time_invalid", f"the {KINDS[key]} fetch time is in the future")
        checks.need(age <= limits.get("max_age_hours", 3), "stale_data",
                    f"the live {KINDS[key]} price is {age:.1f} hours old")


def check_ai(checks: Checks, run: dict, expected: dict) -> None:
    """What the pretend AI invented must not reach the traveller or fill a gap."""
    for job in expected.get("ai_asked", []):
        if not checks.need(job in run.get("ai_asked", []), "case_setup", f"the AI was never asked to do '{job}'"):
            return
    shown = " ".join([str(run["state"].get("summary") or ""), str(run["state"].get("message") or ""),
                      str(run.get("chat_answer") or ""),
                      json.dumps(run["state"].get("itinerary") or {}, ensure_ascii=False)])
    for words in expected.get("must_not_show", []):
        checks.need(words.lower() not in shown.lower(), "ai_invented_shown",
                    f"the traveller is shown something the AI made up: '{words}'")
    if "ai_must_not_fill" in expected:
        field = expected["ai_must_not_fill"]
        value = (run["state"].get("constraints") or {}).get(field)
        checks.need(run["state"].get("status") == "needs_info", "ai_filled_missing_value",
                    f"the traveller never gave the {field}, yet the planner used the AI's '{value}' and made a "
                    "plan instead of asking")


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    state = run["state"]
    if "ai_must_not_fill" in expected:
        check_ai(checks, run, expected)
        return
    if not checks.need(common.plan_made(state), "no_plan", f"no plan was made: {state.get('message', '')}"):
        return
    check_provenance(checks, run)
    check_claims(checks, run)
    # an AI overview comes before the template; the template part is what the summary checks read
    check_summary(checks, run)
    check_links(checks, run)
    check_freshness(checks, run, limits)
    for key in ("flight", "hotel"):
        if (state.get(key) or {}).get("selected"):
            check_label(checks, state[key], state[key]["selected"], KINDS[key])
    for key in expected.get("live", []):
        checks.need(bool((state.get(key) or {}).get("live")), "case_setup",
                    f"the case expects a live {KINDS[key]} price")
    for key in expected.get("fallback", []):
        block = state.get(key) or {}
        checks.need(block.get("estimated") is True and not block.get("live"), "mock_labelled_real",
                    f"the failed live {KINDS[key]} lookup was not replaced by a labelled estimate")
        checks.need(common.warned(state, "live", "estimate"), "fallback_not_told",
                    f"the traveller is not told that the live {KINDS[key]} price was unavailable")
    for key in expected.get("unavailable", []):
        checks.need(bool((state.get(key) or {}).get("error")), "case_setup",
                    f"the case expects the {KINDS[key]} data to be unavailable")
        checks.need(common.warned(state, "failed"), "missing_not_told",
                    f"the traveller is not told that {KINDS[key]} data is unavailable")
    if any(k in expected for k in ("must_not_show", "ai_asked")):
        check_ai(checks, run, expected)
    for kind in expected.get("full_provenance", []):
        block = state.get(kind) or {}
        where = [block, block.get("selected") or {}]
        missing = [field for field in expected["fields"]
                   if not any(part.get(name) not in (None, "") for part in where for name in PROVENANCE[field])]
        if missing:
            checks.unsupported("full_provenance", f"the {KINDS[kind]} data keeps no {', '.join(missing)}")


def evaluate(case: dict) -> Result:
    return common.judge(case, check)
