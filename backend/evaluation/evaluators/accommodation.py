"""Accommodation: the hotel search that was made, and whether the plan repeats the provider's answer faithfully.

Offline the provider is the application's price estimator: room types by price level, not real hotels.
"""
from __future__ import annotations

from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.evaluators.transport import check_label, check_traceable
from evaluation.results import Result

COPIED = ("label", "tier", "price_night_per_room", "rating", "amenities", "url", "lat", "lon", "address")


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    state = run["state"]
    if not checks.need(common.plan_made(state), "no_plan", f"no plan was made: {state.get('message', '')}"):
        return
    c = state["constraints"]
    common.expect_requirements(checks, state, expected)
    searches = common.calls(run, "search_hotels")
    if not checks.need(bool(searches), "no_search", "no hotel search was made"):
        return
    start, end = common.trip_dates(c)
    nights = c["days"] - 1
    guests_per_room = limits.get("guests_per_room", 2)
    rooms = -(-c["travelers"] // guests_per_room)
    asked = searches[-1]["args"]
    checks.same("wrong_location", "searched destination", asked.get("destination"), c["destination"])
    checks.same("wrong_dates", "searched check-in date", asked.get("checkin"), start)
    checks.same("wrong_dates", "searched nights", asked.get("nights"), nights)
    checks.same("wrong_guests", "searched guest count", asked.get("travelers"), c["travelers"])

    block = state.get("hotel") or {}
    selected = block.get("selected")
    answer = common.answered(run, "search_hotels")
    if expected.get("data") == "missing":
        checks.need(selected is None and bool(block.get("error")), "invented_data",
                    "the hotel search failed, but the plan still shows a hotel")
        checks.same("invented_price", "hotel cost without any provider data",
                    state["budget_report"]["lines"]["hotel"], 0)
        checks.need("hotel" in state["budget_report"]["incomplete"], "missing_not_marked",
                    "the budget is not marked as incomplete")
        checks.need(common.warned(state, "partial"), "missing_not_told",
                    "the traveller is not told that the plan is partial")
        return
    if not checks.need(bool(selected) and answer is not None, "no_option", "no hotel was chosen"):
        return
    result = answer["result"]
    checks.same("wrong_location", "provider answer destination", result.get("destination"), c["destination"])
    checks.same("wrong_dates", "provider answer check-in and nights",
                [result.get("checkin"), result.get("nights")], [start, nights])
    check_traceable(checks, block, result, selected, COPIED, "hotel")
    checks.same("wrong_dates", "nights in the plan", selected.get("nights"), nights)
    last = state["itinerary"]["days"][-1]["date"]
    checks.same("wrong_dates", "check-out day (last day of the plan)", last, end)
    checks.same("wrong_guests", "rooms for the group", selected.get("rooms"), rooms)
    checks.same("currency", "currency of the hotel prices", result.get("currency"), "INR")
    total = selected.get("price_night_per_room", 0) * nights * rooms
    checks.same("total_mismatch", "hotel total (rate x nights x rooms)", selected.get("total"), total)
    checks.same("total_mismatch", "hotel line in the budget", state["budget_report"]["lines"]["hotel"], total)
    check_label(checks, block, selected, "hotel")

    cheapest = min(o["price_night_per_room"] for o in result["options"])
    report = state["budget_report"]
    if report["over_budget"]:
        checks.need(selected.get("price_night_per_room") == cheapest, "not_cheapest_when_over_budget",
                    "the trip is over budget, but a cheaper room type was offered and not chosen")
    if expected.get("tier"):
        checks.same("wrong_room_type", "room type", selected.get("tier"), expected["tier"])
    for key, words in (("rating", "ratings"), ("amenities", "amenities")):
        if key not in selected:
            checks.unchecked(f"no_{key}", f"the provider gave no {words}, so none were checked")
    if not selected.get("url"):
        checks.unchecked("no_booking_link", "the offline estimator gives no source link")
    if block.get("estimated"):
        checks.unchecked("availability_unknown", "prices are estimates: real rooms and rates were not checked")
    for key, name in (("needs_amenities", "amenities"), ("needs_rating", "rating"), ("needs_source_link", "url")):
        if expected.get(key) and not selected.get(name):
            checks.unsupported(name, f"hotel results carry no {'source link' if name == 'url' else name}")
    checks.measured.update(tier=selected.get("tier"), price_night_per_room=selected.get("price_night_per_room"),
                           source=block.get("source"), estimated=block.get("estimated"))


def evaluate(case: dict) -> Result:
    return common.judge(case, check)
