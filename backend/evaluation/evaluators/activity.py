"""Activities: do they come from the places data, are they where the trip is, do they match what was asked,
suit the weather, and appear only once.

Entry costs offline are rough **estimates** and there are no opening hours, so neither is verified.
"""
from __future__ import annotations

import math
import re

from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.results import Result

FILLER = "generic-indoor"          # the planner's free "indoor downtime" block, not a place


def _km(a: tuple, b: tuple) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(h))


def _is_filler(item: dict) -> bool:
    return str(item.get("id", "")).startswith("gen")


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    state = run["state"]
    if not checks.need(common.plan_made(state), "no_plan", f"no plan was made: {state.get('message', '')}"):
        return
    c = state["constraints"]
    common.expect_requirements(checks, state, expected)
    planned = common.planned_activities(state)
    if expected.get("data") == "missing":
        checks.need(bool((state.get("activities") or {}).get("error")), "failure_not_recorded",
                    "the places failure is not recorded")
        checks.need(not planned, "invented_data", f"the places lookup failed, but {len(planned)} activities "
                    "are planned")
        checks.need(common.warned(state, "places"), "missing_not_told",
                    "the traveller is not told that places are missing")
        return
    answer = common.answered(run, "search_places")
    if not checks.need(answer is not None, "no_search", "no places search succeeded"):
        return
    checks.same("wrong_location", "searched destination", answer["args"].get("destination"), c["destination"])
    offered = {p["id"]: p for p in answer["result"]["candidates"]}
    if not checks.need(bool(planned) or not expected.get("min_activities", 1), "nothing_planned",
                       "no activity was planned"):
        return
    geo = c.get("destination_geo") or {}
    seen_ids, seen_names, located, costs_checked = {}, {}, 0, 0
    for day, item in planned:
        if item["id"] == FILLER:
            continue
        source = offered.get(item["id"])
        if not checks.need(source is not None, "not_from_places_data",
                           f"day {day['day']}: '{item['name']}' is not in the places data"):
            continue
        checks.need(item["name"] == source["name"], "name_changed",
                    f"'{item['name']}' is called '{source['name']}' in the places data")
        checks.need(item["cost_pp"] == source["cost"], "cost_changed",
                    f"'{item['name']}': the places data says {source['cost']} per person, the plan "
                    f"{item['cost_pp']}")
        costs_checked += 1
        checks.need(bool(item.get("outdoor")) == bool(source["outdoor"]), "setting_changed",
                    f"'{item['name']}': indoor or outdoor differs from the places data")
        if "lat" in item and geo.get("lat") is not None:
            located += 1
            away = _km((geo["lat"], geo["lon"]), (item["lat"], item["lon"]))
            checks.need(away <= limits.get("max_km_from_centre", 100), "wrong_location",
                        f"'{item['name']}' is about {away:.0f} km from the destination")
        key = re.sub(r"\W+", "", item["name"].lower())
        seen_ids[item["id"]] = seen_ids.get(item["id"], 0) + 1
        seen_names[key] = seen_names.get(key, 0) + 1
    twice = [k for k, n in {**seen_ids, **seen_names}.items() if n > 1]
    checks.need(not twice, "duplicate", f"planned more than once: {twice}")

    named = [(d, i) for d, i in planned if not _is_filler(i)]
    filler = len(planned) - len(named)
    checks.measured.update(activities=len(planned), general_suggestions=filler, with_coordinates=located)
    if planned:
        share = filler / len(planned)
        checks.measured["general_share"] = round(share, 2)
        if "max_general_share" in limits:
            checks.need(share <= limits["max_general_share"], "too_much_filler",
                        f"{share:.0%} of the activities are general suggestions rather than named places")
        elif filler:
            checks.warn("general_suggestions", f"{filler} of {len(planned)} activities are general suggestions, "
                                               "not named places")
    wanted = c.get("preferences") or []
    if wanted and planned:
        matching = [i for _, i in planned if set(i.get("tags", [])) & set(wanted)]
        checks.measured["preference_match_share"] = round(len(matching) / len(planned), 2)
        if "min_preference_share" in limits:
            checks.need(len(matching) / len(planned) >= limits["min_preference_share"], "not_relevant",
                        f"only {len(matching)} of {len(planned)} activities match {sorted(wanted)}")
        for pref in wanted:
            if any(pref in i.get("tags", []) for _, i in planned):
                continue
            if pref in expected.get("may_drop", []):          # the traveller's own change removed what matched
                checks.warn("interest_dropped_by_request", f"after the change nothing matches '{pref}', and no "
                                                           "warning says so")
            else:
                checks.need(common.warned(state, pref), "preference_dropped",
                            f"nothing planned matches '{pref}' and no warning says so")
    for tag in expected.get("includes_tags", []):
        checks.need(any(tag in i.get("tags", []) for _, i in planned), "expected_kind_missing",
                    f"no '{tag}' activity is planned")
    for word in expected.get("left_out", []):
        found = [i["name"] for _, i in planned if word.lower() in i["name"].lower()]
        checks.need(not found, "excluded_still_planned", f"asked to leave out '{word}', still planned: {found}")
    wet = [f"{i['name']} (day {d['day']})" for d, i in planned if d.get("rainy") and i.get("outdoor")]
    checks.need(not wet, "outdoor_in_rain", f"outdoor activities on rainy days: {wet}")
    checks.unchecked("opening_hours_unknown", "the places data has no opening hours")
    checks.unchecked("entry_fees_estimated", f"{costs_checked} entry costs match the places data, but they are "
                                             "estimates: no verified fee exists")
    for key, message in (("needs_opening_hours", "activities carry no opening hours, so visits cannot be "
                          "checked against them"),
                         ("needs_verified_fees", "entry costs are estimates; no verified fee is available")):
        if expected.get(key):
            checks.unsupported(key[6:], message)


def evaluate(case: dict) -> Result:
    return common.judge(case, check)
