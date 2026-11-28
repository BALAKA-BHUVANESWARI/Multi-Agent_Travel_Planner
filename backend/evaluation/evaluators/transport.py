"""Transport: the search that was made, and whether the plan repeats the provider's answer faithfully.

"Provider data" is what the search tool returned. Offline that is the application's price **estimator**: these
checks never treat it as real availability, and they fail if the plan presents it as anything but an estimate.
"""
from __future__ import annotations

from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.results import Result

COPIED = ("label", "mode", "price_pp", "duration_h", "stops", "depart_out", "arrive_out", "depart_back",
          "arrive_back")
ESTIMATE_SOURCES = ("synthetic-estimator",)


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def check_label(checks: Checks, block: dict, selected: dict, what: str) -> None:
    """An estimate must be labelled as one everywhere; a live price must say where and when it came from."""
    source = block.get("source")
    checks.need(bool(source), "source_missing", f"the {what} has no source")
    if source in ESTIMATE_SOURCES:
        checks.need(block.get("estimated") is True and not block.get("live") and selected.get("estimated") is True
                    and not selected.get("live"), "mock_labelled_real",
                    f"the {what} comes from the price estimator but is not labelled as an estimate")
    elif block.get("estimated") is False:
        checks.need(bool(block.get("fetched_at")), "retrieval_time_missing",
                    f"the live {what} price has no retrieval time")


def check_traceable(checks: Checks, block: dict, result: dict, selected: dict, fields, what: str) -> None:
    offered = next((o for o in result["options"] if o["id"] == selected.get("id")), None)
    if not checks.need(offered is not None, "not_from_provider",
                       f"the chosen {what} option '{selected.get('id')}' is not one the provider offered"):
        return
    for key in fields:
        if key in offered:
            checks.need(selected.get(key) == offered[key], f"{key}_mismatch",
                        f"{what} {key}: the provider gave {offered[key]!r}, the plan shows {selected.get(key)!r}")


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    state = run["state"]
    c = state.get("constraints") or {}
    if expected.get("status", "awaiting_approval") != "awaiting_approval":
        checks.same("workflow_status", "status", state.get("status"), expected["status"])
        for words in expected.get("says", []):
            checks.need(words.lower() in str(state.get("message", "")).lower(), "missing_explanation",
                        f"the message does not say '{words}': {state.get('message', '')!r}")
        checks.need(not state.get("itinerary"), "plan_despite_problem",
                    "a plan was made although this journey is not possible")
        return
    if not checks.need(common.plan_made(state), "no_plan", f"no plan was made: {state.get('message', '')}"):
        return
    common.expect_requirements(checks, state, expected)
    searches = common.calls(run, "search_flights")
    if not checks.need(bool(searches), "no_search", "no travel search was made"):
        return
    start, end = common.trip_dates(c)
    asked = searches[-1]["args"]
    for key, value in (("origin", c["origin"]), ("destination", c["destination"])):
        checks.same("wrong_route", f"searched {key}", asked.get(key), value)
    checks.same("wrong_dates", "searched travel dates", [asked.get("depart_date"), asked.get("return_date")],
                [start, end])
    checks.same("wrong_travellers", "searched traveller count", asked.get("travelers"), c["travelers"])

    block = state.get("flight") or {}
    selected = block.get("selected")
    answer = common.answered(run, "search_flights")
    if expected.get("data") == "missing":
        checks.need(selected is None and bool(block.get("error")), "invented_data",
                    "the travel search failed, but the plan still shows a travel option")
        checks.same("invented_price", "travel cost without any provider data",
                    state["budget_report"]["lines"]["flight"], 0)
        checks.need("flight" in state["budget_report"]["incomplete"], "missing_not_marked",
                    "the budget is not marked as incomplete")
        checks.need(common.warned(state, "partial"), "missing_not_told",
                    "the traveller is not told that the plan is partial")
        return
    if not checks.need(bool(selected) and answer is not None, "no_option", "no travel option was chosen"):
        return
    result = answer["result"]
    for key in ("origin", "destination", "travelers"):
        checks.same("wrong_route" if key != "travelers" else "wrong_travellers", f"provider answer {key}",
                    result.get(key), c[key])
    checks.same("wrong_dates", "provider answer dates", [result.get("depart_date"), result.get("return_date")],
                [start, end])
    check_traceable(checks, block, result, selected, COPIED, "travel")
    checks.same("currency", "currency of the travel prices", result.get("currency"), "INR")
    checks.same("total_mismatch", "travel total (price per person x travellers)", selected.get("total"),
                selected.get("price_pp", 0) * c["travelers"])
    checks.same("total_mismatch", "travel line in the budget", state["budget_report"]["lines"]["flight"],
                selected.get("price_pp", 0) * c["travelers"])
    stops, hours = selected.get("stops"), selected.get("duration_h") or 0
    checks.need(isinstance(stops, int) and stops >= 0, "stops_invalid", f"the number of stops is {stops!r}")
    checks.need(hours > 0, "duration_invalid", f"the journey time is {hours!r} hours")
    if selected.get("mode") in ("flight", "ground"):
        # arrival minus departure (over midnight) must be the stated duration, to within rounding
        gap = (_minutes(selected["arrive_out"]) - _minutes(selected["depart_out"])) % 1440
        apart = abs(gap - hours * 60 % 1440)
        checks.need(min(apart, 1440 - apart) <= 4, "duration_mismatch",
                    f"leaves {selected['depart_out']}, arrives {selected['arrive_out']}, but says {hours} h")
    if "mode" in expected:
        checks.same("wrong_mode", "way of travelling", selected.get("mode"), expected["mode"])
    check_label(checks, block, selected, "travel")
    checks.need("estimated" in str(state.get("summary", "")).lower() if block.get("estimated") else True,
                "estimate_not_shown", "the written plan does not say that the travel price is estimated")
    if block.get("estimated"):
        checks.unchecked("availability_unknown", "prices are estimates: real seats and fares were not checked")
        checks.unchecked("no_booking_link", "the offline estimator gives no source link")
    if expected.get("needs_live_availability") and block.get("estimated"):
        checks.unsupported("live_availability", "offline, the planner cannot show real availability: it only "
                                                "has estimates")
    if expected.get("needs_source_link") and not selected.get("url"):
        checks.unsupported("source_link", "travel options carry no source link")
    checks.measured.update(mode=selected.get("mode"), price_pp=selected.get("price_pp"),
                           source=block.get("source"), estimated=block.get("estimated"))


def evaluate(case: dict) -> Result:
    return common.judge(case, check)
