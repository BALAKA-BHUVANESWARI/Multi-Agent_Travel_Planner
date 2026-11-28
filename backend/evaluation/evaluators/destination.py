"""Destination: suggestions when no place is named, and the alternatives shown next to a plan.

The case says what the traveller asked for; the checks hold the suggestions to it. Tags, best months and price
estimates are the application's own hand-entered data, so their truth is **not** checked here (there is no
outside source to compare them with).
"""
from __future__ import annotations

from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.results import Result


def _check_list(checks: Checks, items: list, state: dict, limits: dict) -> None:
    c = state.get("constraints") or {}
    names = [i["name"] for i in items]
    checks.need(len(names) == len(set(names)), "duplicate", f"a place is suggested twice: {names}")
    checks.need(all(i.get("estimated") is True for i in items), "estimate_not_marked",
                "a suggested price is not marked as an estimate")
    wanted = set(c.get("preferences") or [])
    for item in items:
        checks.need(set(item["matched"]) <= set(item["tags"]), "wrong_match",
                    f"{item['name']}: says it matches {item['matched']}, but is only tagged {item['tags']}")
        if c.get("budget"):
            checks.need(item["fits_budget"] == (item["estimate_from"] <= c["budget"]), "budget_flag",
                        f"{item['name']}: costs from {item['estimate_from']}, budget {c['budget']}, "
                        f"but 'fits budget' is {item['fits_budget']}")
        checks.need(0 < item["estimate_from"] <= item["estimate_comfortable"], "price_order",
                    f"{item['name']}: the lowest estimate is above the comfortable one")
    if any(i["fits_budget"] for i in items):
        over = [i["name"] for i in items if not i["fits_budget"]]
        checks.need(not over, "over_budget_suggested",
                    f"places over the budget are suggested although others fit it: {over}")
    abroad = [i["country"] for i in items if i["country"] != "India"]
    checks.need(len(abroad) == len(set(abroad)), "same_country", f"two suggestions in one country abroad: {abroad}")
    if wanted:
        share = sum(bool(wanted & set(i["tags"])) for i in items) / len(items)
        checks.measured["preference_match_share"] = round(share, 2)
        checks.need(share >= limits.get("min_preference_share", 0.75), "not_relevant",
                    f"only {share:.0%} of the suggestions match any of {sorted(wanted)}")
    checks.measured["in_season_share"] = round(sum(i["in_season"] for i in items) / len(items), 2)


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    state = run["state"]
    common.expect_requirements(checks, state, expected)
    if expected.get("kind") == "alternatives":
        if not checks.need(common.plan_made(state), "no_plan", f"no plan was made: {state.get('message', '')}"):
            return
        block = state.get("alternatives") or {}
        items = block.get("items") or []
        if not checks.need(bool(items), "no_alternatives", "no other destination was offered"):
            return
        c = state["constraints"]
        checks.need(c["destination"] not in [i["slug"] for i in items], "current_offered",
                    "the planned destination is offered as its own alternative")
        checks.need(block.get("estimated") is True, "estimate_not_marked", "the alternatives are not marked "
                    "as estimates")
        checks.need(bool(block.get("baseline")), "no_baseline", "the planned destination is not priced the same "
                    "way, so the alternatives cannot be compared with it")
    else:
        checks.same("workflow_status", "status", state.get("status"), "needs_info")
        items = state.get("suggestions") or []
        if not checks.need(bool(items), "no_suggestions", f"no destination was suggested: "
                           f"{state.get('message', '')}"):
            return
        message = str(state.get("message", ""))
        for item in items:
            checks.need(item["name"] in message, "not_shown", f"{item['name']} is not named in the message")
        if not any(i["fits_budget"] for i in items):
            checks.need("none of my suggestions fits" in message.lower(), "budget_not_told",
                        "nothing fits the budget and the message does not say so")
        if any(not i["in_season"] for i in items):
            checks.need("off season" in message.lower(), "season_not_told",
                        "an off-season place is not labelled as off season")
        checks.need(not common.calls(run, "search_flights") and not common.calls(run, "search_hotels"),
                    "unnecessary_run", "trip searches ran before a destination was chosen")
    _check_list(checks, items, state, limits)
    countries = {i["country"] for i in items}
    if expected.get("scope") == "india":
        checks.same("wrong_scope", "countries suggested", sorted(countries), ["India"])
    if expected.get("scope") == "abroad":
        checks.need("India" not in countries, "wrong_scope", f"asked for abroad, got {sorted(countries)}")
    if "includes_any" in expected:
        names = [i["name"] for i in items]
        checks.need(bool(set(names) & set(expected["includes_any"])), "expected_place_missing",
                    f"none of {expected['includes_any']} is among {names}")
    for name in expected.get("excludes", []):
        checks.need(name not in [i["name"] for i in items], "unsuitable_place", f"{name} should not be suggested")
    if limits.get("min_in_season_share") is not None:
        checks.need(checks.measured["in_season_share"] >= limits["min_in_season_share"], "off_season",
                    f"only {checks.measured['in_season_share']:.0%} of the suggestions are in season")
    checks.unchecked("facts_not_verified", "tags, best months and price levels have no outside source to check")
    if expected.get("needs_sources"):
        checks.unsupported("sources", "suggestions carry no source for their season and interest information")
    checks.measured["suggested"] = [i["name"] for i in items]


def evaluate(case: dict) -> Result:
    return common.judge(case, check)
