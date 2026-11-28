"""Itinerary evaluator: fixed rules, no AI.

Every finding is a hard failure (``fail``), a warning (``warn``) or something that could not be checked
(``not_checked``). It never works out a route or a travel time: those are checked only when the case supplies
them. The distance between two stops is a straight line between their coordinates, and is called that.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

from evaluation.results import FAIL, INFO, WARN, Finding, Result, outcome

DEFAULT_RULES = {
    "max_activities_per_day": 4,
    "min_activity_minutes": 30,
    "max_activity_minutes": 360,
    "lunch_from": "12:00", "lunch_to": "15:00", "lunch_minutes": 45, "meal_break_severity": FAIL,
    "max_minutes_without_break": 300, "break_minutes": 30,
    "max_straight_line_km": 30, "distance_severity": WARN,
    "weather_severity": FAIL,
    "daily_budget_severity": FAIL,
}


def minutes(clock: str) -> int:
    if not re.fullmatch(r"\d{2}:\d{2}", str(clock)):
        raise ValueError(f"'{clock}' is not a time")
    h, m = int(clock[:2]), int(clock[3:])
    if h > 47 or m > 59:
        raise ValueError(f"'{clock}' is not a time")
    return h * 60 + m


def straight_km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = (math.radians(float(v)) for v in (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _dates(itinerary: dict, constraints: dict) -> list[Finding]:
    out = []
    start, count = date.fromisoformat(constraints["start_date"]), int(constraints["days"])
    wanted = [(start + timedelta(days=i)).isoformat() for i in range(count)]
    got = [d.get("date") for d in itinerary.get("days", [])]
    for day in wanted:
        if day not in got:
            out.append(Finding("missing_day", FAIL, f"{day} is not in the plan"))
    for day in got:
        if day not in wanted:
            out.append(Finding("outside_dates", FAIL, f"{day} is outside the trip dates"))
    if len(set(got)) != len(got):
        out.append(Finding("repeated_day", FAIL, "a date appears twice"))
    if not out and got != wanted:
        out.append(Finding("day_order", FAIL, "the days are not in date order"))
    for key, value in (("start_date", wanted[0]), ("end_date", wanted[-1])):
        if key in itinerary and itinerary[key] != value:
            out.append(Finding("date_range", FAIL, f"{key} is {itinerary[key]}, expected {value}"))
    return out


def _times(day: dict, rules: dict) -> tuple[list[Finding], list[dict]]:
    """Findings about one day's times, and the items that have usable times, in order."""
    out, usable = [], []
    for item in day.get("items", []):
        try:
            start, end = minutes(item["start"]), minutes(item["end"])
        except (KeyError, ValueError):
            out.append(Finding("bad_time", FAIL, f"{day['date']}: '{item.get('name')}' has no valid time"))
            continue
        length = end - start
        if length <= 0:
            out.append(Finding("bad_duration", FAIL, f"{day['date']}: '{item['name']}' ends before it starts"))
            continue
        if item.get("type") == "activity":
            if length < rules["min_activity_minutes"] or length > rules["max_activity_minutes"]:
                out.append(Finding("bad_duration", FAIL, f"{day['date']}: '{item['name']}' lasts {length} minutes"))
        usable.append({**item, "_from": start, "_to": end})
    usable.sort(key=lambda i: (i["_from"], i["_to"]))
    latest = None
    for item in usable:
        if latest and item["_from"] < latest["_to"]:
            out.append(Finding("time_conflict", FAIL,
                               f"{day['date']}: '{latest['name']}' and '{item['name']}' are at the same time"))
        if latest is None or item["_to"] > latest["_to"]:
            latest = item
    activities = [i for i in usable if i.get("type") == "activity"]
    if len(activities) > rules["max_activities_per_day"]:
        out.append(Finding("too_many_activities", FAIL, f"{day['date']}: {len(activities)} activities"))
    arrive = next((i for i in usable if i.get("leg") == "arrival"), None)
    leave = next((i for i in usable if i.get("leg") == "departure"), None)
    for item in activities:
        if arrive and item["_from"] < arrive["_to"]:
            out.append(Finding("before_arrival", FAIL, f"{day['date']}: '{item['name']}' starts before arrival"))
        if leave and item["_to"] > leave["_from"]:
            out.append(Finding("after_departure", FAIL, f"{day['date']}: '{item['name']}' ends after departure"))
    return out, usable


def _breaks(day: dict, items: list[dict], rules: dict) -> list[Finding]:
    """A free gap at lunch time on full days, and no very long stretch without a pause."""
    out = []
    if not items:
        return out
    if day.get("kind", "full") == "full":
        low, high = minutes(rules["lunch_from"]), minutes(rules["lunch_to"])
        free, cursor = 0, low
        for item in items:
            if item.get("meal"):                               # a planned meal counts as the break
                if item["_from"] < high and item["_to"] > low:
                    free = rules["lunch_minutes"]
                continue
            free = max(free, min(item["_from"], high) - cursor)
            cursor = max(cursor, min(item["_to"], high))
        free = max(free, high - cursor)
        if free < rules["lunch_minutes"]:
            out.append(Finding("no_meal_break", rules["meal_break_severity"],
                               f"{day['date']}: no {rules['lunch_minutes']}-minute gap for lunch between "
                               f"{rules['lunch_from']} and {rules['lunch_to']}"))
    begin = end = None
    for item in items:
        if item.get("meal"):                                   # sitting down to eat is a rest
            begin = end = None
            continue
        if begin is None or item["_from"] - end >= rules["break_minutes"]:
            begin = item["_from"]
        end = max(end or 0, item["_to"])
        if end - begin > rules["max_minutes_without_break"]:
            out.append(Finding("no_rest_break", WARN, f"{day['date']}: more than "
                               f"{rules['max_minutes_without_break']} minutes without a "
                               f"{rules['break_minutes']}-minute break"))
            break
    return out


def _places(day: dict, items: list[dict], rules: dict, routes: dict) -> list[Finding]:
    """Opening hours, travel time and distance between stops, each only as far as there is data."""
    out = []
    stops = [i for i in items if i.get("type") == "activity"]
    for item in stops:
        hours = item.get("opening_hours")
        if not hours:
            out.append(Finding("opening_hours_unknown", WARN, f"'{item['name']}': no opening hours to check"))
        elif item["_from"] < minutes(hours["open"]) or item["_to"] > minutes(hours["close"]):
            out.append(Finding("closed", FAIL, f"{day['date']}: '{item['name']}' is planned outside "
                               f"{hours['open']}-{hours['close']}"))
    for a, b in zip(stops, stops[1:]):
        pair = f"'{a['name']}' to '{b['name']}'"
        if (a["name"], b["name"]) in routes:
            need, gap = routes[(a["name"], b["name"])], b["_from"] - a["_to"]
            if gap < need:
                out.append(Finding("travel_time", FAIL, f"{day['date']}: {pair} takes {need} minutes by the "
                                   f"route data and only {gap} are free"))
        else:
            out.append(Finding("travel_time_not_checked", INFO, f"{pair}: no route data"))
        if all(k in x for x in (a, b) for k in ("lat", "lon")):
            km = straight_km(a, b)
            if km > rules["max_straight_line_km"]:
                out.append(Finding("far_apart", rules["distance_severity"], f"{day['date']}: {pair} is "
                                   f"{km:.0f} km apart in a straight line (not a route distance)"))
        else:
            out.append(Finding("distance_not_checked", INFO, f"{pair}: a stop has no coordinates"))
    return out


def validate(itinerary: dict, constraints: dict, context: dict | None = None, rules: dict | None = None) -> list[Finding]:
    """``constraints``: start_date, days, preferences, max_daily_activity_cost (optional).
    ``context``: weather {date: rainy}, routes [{from, to, minutes}], budget {total, budget, warned},
    rain_explained [interests the plan says it dropped because of rain]."""
    context = context or {}
    rules = {**DEFAULT_RULES, **{k: v for k, v in (rules or {}).items()}}
    unknown = set(rules) - set(DEFAULT_RULES)
    if unknown:
        raise ValueError(f"unknown itinerary rule: {', '.join(sorted(unknown))}")
    routes = {(r["from"], r["to"]): int(r["minutes"]) for r in context.get("routes") or []}
    weather = context.get("weather")
    out = _dates(itinerary, constraints)
    seen, tags, placeholders = {}, set(), 0
    for day in itinerary.get("days", []):
        found, items = _times(day, rules)
        out += found + _breaks(day, items, rules) + _places(day, items, rules, routes)
        activities = [i for i in items if i.get("type") == "activity"]
        for item in activities:
            tags.update(item.get("tags") or [])
            if item.get("id") == "generic-indoor":
                placeholders += 1
                continue
            keys = {" ".join(re.findall(r"\w+", item["name"].lower()))}
            if item.get("id"):
                keys.add(f"id:{item['id']}")
            if any(k in seen for k in keys):
                out.append(Finding("duplicate_activity", FAIL, f"'{item['name']}' is planned more than once"))
            seen.update(dict.fromkeys(keys, day["date"]))
        if weather is not None:
            if day["date"] not in weather:
                out.append(Finding("weather_unknown", WARN, f"{day['date']}: no weather to check against"))
            elif weather[day["date"]]:
                for item in activities:
                    if item.get("outdoor"):
                        out.append(Finding("outdoor_in_rain", rules["weather_severity"],
                                           f"{day['date']}: '{item['name']}' is outdoors on a rainy day"))
        limit = constraints.get("max_daily_activity_cost")
        if limit is not None:
            spent = sum(i.get("cost_total", 0) for i in activities)
            if spent > limit:
                out.append(Finding("over_daily_budget", rules["daily_budget_severity"],
                                   f"{day['date']}: activities cost {spent}, the daily limit is {limit}"))
    if weather is None:
        out.append(Finding("weather_not_checked", INFO, "no weather data for this plan"))
    if placeholders:
        out.append(Finding("placeholder_activity", WARN,
                           f"{placeholders} slot(s) hold a general indoor suggestion, not a named place"))
    money_ = context.get("budget")
    if money_ is None:
        out.append(Finding("total_budget_not_checked", INFO, "no total cost for this plan"))
    elif money_["total"] > money_["budget"]:
        severity = WARN if money_.get("warned") else FAIL
        told = "the plan warns about it" if money_.get("warned") else "the plan gives no warning"
        out.append(Finding("over_budget", severity,
                           f"total {money_['total']} is over the budget {money_['budget']}; {told}"))
    wanted = constraints.get("preferences") or []
    unmet = [p for p in wanted if p not in tags]
    # like the budget: an interest the weather rules out is a warning only when the plan says so itself
    explained = set(context.get("rain_explained") or []) if weather and any(weather.values()) else set()
    if wanted and len(unmet) == len(wanted):
        told = all(p in explained for p in unmet)
        out.append(Finding("preferences_ignored", WARN if told else FAIL,
                           f"nothing matches any of: {', '.join(wanted)}"
                           + ("; the plan says rain is why" if told else "")))
    else:
        out += [Finding("preference_unmet", WARN, f"nothing matches '{p}'") for p in unmet]
    return out


def evaluate(case: dict) -> Result:
    given, expected = case["input"], case["expected"]
    rules = case["expected_constraints"].get("rules")
    if case["target"] == "self_check":                       # planted mistakes: exactly these must be found
        found = validate(given["itinerary"], given["constraints"], given.get("context"), rules)
        got = sorted({(f.code, f.severity) for f in found if f.severity != INFO})
        want = sorted((f["code"], f["severity"]) for f in expected["findings"])
        wrong = [f"not found: {c} ({s})" for c, s in want if (c, s) not in got]
        wrong += [f"reported by mistake: {c} ({s})" for c, s in got if (c, s) not in want]
        for code in expected.get("not_checked", []):
            if not any(f.code == code and f.severity == INFO for f in found):
                wrong.append(f"should say it could not check: {code}")
        return outcome(wrong, found)

    from evaluation.harness import run_planner

    state = run_planner(given["request"], given.get("changes"))
    c, report = state["constraints"], state["budget_report"]
    limits = case["expected_constraints"]
    wrong = [f"{k}: expected {limits[k]}, the plan used {c.get(k)}"
             for k in ("start_date", "days", "travelers", "budget", "destination") if k in limits and c.get(k) != limits[k]]
    weather = state.get("weather")
    rain_notes = [str(w) for w in state.get("warnings", []) if str(w).startswith("Rain: ") and "interest in " in w]
    context = {"rain_explained": [p.strip() for w in rain_notes
                                  for p in w.split("interest in ", 1)[1].split(".", 1)[0].split(",")],
               "weather": {d["date"]: bool(d["rainy"]) for d in weather["days"]} if weather else None,
               "budget": {"total": report["total"], "budget": c["budget"],
                          "warned": any("over your" in w for w in state.get("warnings", []))}}
    needs = {"start_date": limits.get("start_date", c["start_date"]), "days": limits.get("days", c["days"]),
             "preferences": limits.get("preferences", c.get("preferences") or []),
             "max_daily_activity_cost": limits.get("max_daily_activity_cost")}
    found = validate(state["itinerary"], needs, context, rules)
    wrong += [f"{f.code}: {f.message}" for f in found if f.severity == FAIL]
    rainy = sum(bool(v) for v in (context["weather"] or {}).values())
    if rainy < expected.get("min_rainy_days", 0):
        wrong.append(f"the case needs {expected['min_rainy_days']} rainy day(s) and the offline weather has {rainy}")
    return outcome(wrong, found, {"days": len(state["itinerary"]["days"]), "rainy_days": rainy})
