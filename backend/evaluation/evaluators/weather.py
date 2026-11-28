"""Weather: where the figures came from, which days they cover, how they were read, and what the plan did with
them. The rain limit and the forecast window come from the case, not from the application's settings.

``input.tool`` calls the weather tool alone (to test forecast or climate by date); ``input.request`` runs a trip.
"""
from __future__ import annotations

from datetime import date, timedelta

from evaluation import harness
from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.results import Result


def _make(given: dict) -> dict:
    if "tool" not in given:
        return common.make_run(given)
    from app.tools.weather_tools import get_weather

    with harness.offline():
        run = {"state": {}, "calls": {}, "tool": dict(given["tool"]), "weather": get_weather(**given["tool"])}
    for change in given.get("damage", []):
        common.damage(run, change)
    return run


def check_rows(checks: Checks, weather: dict, start: str, days: int, today: str, limits: dict) -> None:
    rain_limit = limits.get("rain_limit", 60)
    window = limits.get("forecast_window_days", 16)
    first = date.fromisoformat(start)
    wanted = [(first + timedelta(days=i)).isoformat() for i in range(days)]
    rows = weather.get("days") or []
    checks.same("date_coverage", "days with weather", [r.get("date") for r in rows], wanted)
    inside = first >= date.fromisoformat(today) and \
        (first + timedelta(days=days - 1) - date.fromisoformat(today)).days <= window
    checks.same("wrong_source_type", "kind of weather data for these dates", weather.get("mode"),
                "forecast" if inside else "climate")
    source = str(weather.get("source") or "")
    checks.need(bool(source), "source_missing", "the weather has no source")
    if weather.get("mode") == "climate" or "climate" in source.lower() or "estimate" in source.lower():
        checks.need(weather.get("estimated") is True, "estimate_not_marked",
                    f"'{source}' is not marked as an estimate")
        checks.need("forecast" not in source.lower(), "climate_called_forecast",
                    f"climate or estimated figures are described as a forecast: '{source}'")
    if weather.get("mode") == "forecast" and weather.get("offline_fallback"):
        checks.warn("mode_says_forecast", "the data says mode 'forecast', but no forecast was fetched: the figures "
                    f"are an '{source}' (the page shows the source, not the mode)")
    for row in rows:
        day = row.get("date")
        chance, low, high = row.get("precip_prob"), row.get("tmin"), row.get("tmax")
        checks.need(isinstance(chance, (int, float)) and 0 <= chance <= 100, "value_invalid",
                    f"{day}: chance of rain is {chance!r}")
        checks.need(low is None or high is None or -60 <= low <= high <= 60, "value_invalid",
                    f"{day}: temperatures {low!r} to {high!r} are not possible")
        checks.need(row.get("rainy") == (isinstance(chance, (int, float)) and chance >= rain_limit),
                    "rain_misread", f"{day}: {chance}% chance of rain is marked rainy={row.get('rainy')} "
                    f"(rainy from {rain_limit}%)")


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    if "tool" in run:
        asked = run["tool"]
        check_rows(checks, run["weather"], asked["start_date"], asked["days"], asked["today"], limits)
        if "mode" in expected:
            checks.same("wrong_source_type", "kind of weather data", run["weather"].get("mode"), expected["mode"])
    else:
        state = run["state"]
        if not checks.need(common.plan_made(state), "no_plan", f"no plan was made: {state.get('message', '')}"):
            return
        c = state["constraints"]
        weather = state.get("weather") or {}
        if expected.get("data") == "missing":
            checks.need(bool(weather.get("error")) and not weather.get("days"), "invented_data",
                        "the weather lookup failed, but the plan still shows weather")
            checks.need(all(d["weather"] is None and not d["rainy"] for d in state["itinerary"]["days"]),
                        "invented_data", "the day plan shows weather although none was fetched")
            checks.need(not state["itinerary"]["swaps"], "invented_data", "rain changes were made without weather")
            checks.need(common.warned(state, "weather"), "missing_not_told",
                        "the traveller is not told that weather is missing")
            return
        asked = (common.answered(run, "get_weather") or {"args": {}})["args"]
        checks.same("wrong_search", "place, first day and length asked for",
                    [asked.get("destination"), asked.get("start_date"), asked.get("days")],
                    [c["destination"], c["start_date"], c["days"]])
        check_rows(checks, weather, c["start_date"], c["days"], c["today"], limits)
        by_date = {r["date"]: r for r in weather.get("days") or []}
        wet_days = 0
        for day in state["itinerary"]["days"]:
            row = by_date.get(day["date"])
            checks.need(day["weather"] == row and day["rainy"] == bool(row and row["rainy"]), "plan_weather_mismatch",
                        f"day {day['day']} does not show the weather fetched for {day['date']}")
            if day["rainy"]:
                wet_days += 1
                outside = [i["name"] for i in day["items"] if i["type"] == "activity" and i.get("outdoor")]
                checks.need(not outside, "outdoor_in_rain", f"day {day['day']} is rainy but plans outdoors: "
                            f"{outside}")
        for swap in state["itinerary"]["swaps"]:
            day = state["itinerary"]["days"][swap["day"] - 1]
            checks.need(day["rainy"], "swap_on_dry_day", f"an activity was moved for rain on dry day {swap['day']}")
            checks.need(any("rain" in n.lower() and swap["from"] in n for n in day["notes"]), "swap_not_explained",
                        f"day {swap['day']} does not say why '{swap['from']}' was replaced")
        if "min_rainy_days" in expected:
            checks.need(wet_days >= expected["min_rainy_days"], "case_has_no_rain",
                        f"the case needs {expected['min_rainy_days']} rainy day(s), the data has {wet_days}")
        checks.measured.update(rainy_days=wet_days, activities_moved=len(state["itinerary"]["swaps"]),
                               source=weather.get("source"))
        weather_data = weather
        run = {**run, "weather": weather_data}
    if not run["weather"].get("fetched_at"):
        checks.unchecked("no_retrieval_time", "the weather has no retrieval time, so its age cannot be checked")
        if expected.get("needs_freshness"):
            checks.unsupported("freshness", "weather results carry no retrieval time, so freshness cannot be "
                                            "judged")


def evaluate(case: dict) -> Result:
    return common.judge(case, check, _make)
