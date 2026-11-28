"""Whole trips through the workflow: did it finish, was each requirement met, did it take the right route, was
data passed on unchanged, did it cope with failures, and does the final response have the declared shape?

The route is read from the plan's own log. The offline runner (not LangGraph) runs these cases; both use the
same agents and routing functions.
"""
from __future__ import annotations

import json

from evaluation import harness
from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.evaluators.response import problems
from evaluation.results import Result

WORKERS = {"flight", "hotel", "weather", "activities"}
# the order of the steps for one planning pass; the four workers run together
PASS = ["supervisor", "workers", "merge", "budget", "critic"]


def route(log: list) -> list[str]:
    """The steps in order, with the parallel workers shown as one step and repeated entries joined."""
    out: list[str] = []
    for line in log:
        name = "workers" if line.get("agent") in WORKERS else line.get("agent")
        if not out or out[-1] != name:
            out.append(name)
    return out


def route_problem(steps: list[str], status: str, approved: bool) -> str:
    """'' when the steps are a legal path through the workflow."""
    expected_end = {"blocked": ["guardrail"], "needs_info": ["guardrail", "intake"]}.get(status)
    if expected_end is not None:
        return "" if steps == expected_end else f"expected only {expected_end}"
    if steps[:2] != ["guardrail", "intake"]:
        return "a trip must start with the input check and then reading the request"
    rest = steps[2:]
    if approved:
        tail = ["approval", "book", "writer"]
        if rest[-3:] != tail:
            return f"an approved trip must end with {tail}"
        rest = rest[:-3]
    if not rest or rest[-1] != "present":
        return "the plan must be shown to the traveller before anything else happens"
    rest = rest[:-1]
    passes = 0
    while rest:
        if rest[:4] != PASS[:4]:
            return f"a planning pass must be {PASS}, found {rest[:5]}"
        rest = rest[4:]
        if rest[:1] == ["critic"]:                       # the critic is skipped only to re-plan for the budget
            rest = rest[1:]
        elif not rest:
            return "the last planning pass was never checked by the critic"
        passes += 1
    return "" if passes else "no planning pass ran"


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def check_handover(checks: Checks, run: dict) -> None:
    """What one agent produced is what the next one used."""
    state = run["state"]
    c, plan = state["constraints"], state["itinerary"]
    flight = (state.get("flight") or {}).get("selected")
    hotel = (state.get("hotel") or {}).get("selected")
    weather = {r["date"]: r for r in (state.get("weather") or {}).get("days", [])}
    checks.same("data_passing", "destination used for the day plan", plan["destination"], c["destination"])
    checks.same("data_passing", "first day of the day plan", plan["start_date"], c["start_date"])
    checks.same("data_passing", "number of days in the day plan", len(plan["days"]), c["days"])
    items = [i for d in plan["days"] for i in d["items"]]
    arrive = next((i for i in items if i.get("leg") == "arrival"), None)
    leave = next((i for i in items if i.get("leg") == "departure"), None)
    if flight:
        checks.same("data_passing", "arrival time used by the day plan",
                    arrive and _clock(arrive["start_min"] % 1440), flight["arrive_out"])
        checks.same("data_passing", "departure time used by the day plan",
                    leave and _clock(leave["end_min"] % 1440), flight["depart_back"])
    if hotel:
        checks.need(any(i["type"] == "hotel" and hotel["label"] in i["name"] for i in items), "data_passing",
                    f"the day plan does not check in at the chosen hotel '{hotel['label']}'")
    for day in plan["days"]:
        checks.need(day["weather"] == weather.get(day["date"]), "data_passing",
                    f"day {day['day']} does not carry the weather agent's figures")
    offered = {p["id"] for call in common.calls(run, "search_places") if call["result"]
               for p in call["result"]["candidates"]}
    unknown = [i["name"] for i in items if i["type"] == "activity" and i["id"] != "generic-indoor"
               and i["id"] not in offered]
    checks.need(not unknown, "data_passing", f"activities that the activity agent never found: {unknown}")
    report = state["budget_report"]
    spent = sum(i["cost_total"] for i in items if i["type"] == "activity")
    checks.same("data_passing", "activity costs in the budget", report["lines"]["activities"], spent)
    checks.same("data_passing", "budget given to the budget step", report["budget"], c["budget"])
    checks.same("data_passing", "price level used by the budget step", report["strategy"], state["strategy"])


def check_schema(checks: Checks, state: dict) -> None:
    from app.schemas.accommodation import AccommodationResult
    from app.schemas.activity import ActivityResult
    from app.schemas.budget import BudgetReport
    from app.schemas.itinerary import Itinerary
    from app.schemas.transport import TransportResult
    from app.schemas.traveller import GroupMemberReport
    from app.schemas.trip import Booking, TripConstraints
    from app.services.trip_service import public_view

    view = public_view(state, "runner")
    try:
        json.dumps(view, allow_nan=False)
    except (TypeError, ValueError) as e:
        checks.need(False, "response_schema", f"the response cannot be sent as JSON: {e}")
    wrong = [f"{key}: missing" for key in ("thread_id", "status", "message", "warnings", "log", "attributions")
             if key not in view]
    if common.plan_made(state):
        activities = view.get("activities")
        if isinstance(activities, dict):
            activities = {**activities, "candidates": []}      # the response shortens this list on purpose
        for key, shape, value in (("constraints", TripConstraints, view.get("constraints")),
                                  ("flight", TransportResult, view.get("flight")),
                                  ("hotel", AccommodationResult, view.get("hotel")),
                                  ("activities", ActivityResult, activities),
                                  ("itinerary", Itinerary, view.get("itinerary")),
                                  ("budget_report", BudgetReport, view.get("budget_report"))):
            wrong += problems(value, shape, key) if not (value or {}).get("error") else []
        wrong += [p for i, m in enumerate(view.get("group_report") or [])
                  for p in problems(m, GroupMemberReport, f"group_report[{i}]")]
    if view.get("booking"):
        wrong += problems(view["booking"], Booking, "booking")
    checks.need(not wrong, "response_schema", "the response does not fit the declared shape: " + "; ".join(wrong[:6]))


def _check_choice(checks: Checks, run: dict, request: str) -> None:
    """Choose the first suggestion. If it was said to fit the budget, the finished plan must fit or warn."""
    suggestions = run["state"].get("suggestions") or []
    if not checks.need(bool(suggestions), "no_suggestions", "there is no suggestion to choose"):
        return
    pick = suggestions[0]
    state = harness.run_trip(f"{request} | destination: {pick['name']}")["state"]
    if not checks.need(common.plan_made(state), "choice_not_planned",
                       f"choosing {pick['name']} did not give a plan: {state.get('message', '')}"):
        return
    checks.same("wrong_destination", "chosen destination", state["constraints"]["destination"], pick["slug"])
    total, budget = state["budget_report"]["total"], state["budget_report"]["budget"]
    if pick["fits_budget"]:
        checks.need(total <= budget, "suggestion_over_budget",
                    f"{pick['name']} was said to fit {budget}, but the plan costs {total}")
    checks.measured.update(chosen=pick["name"], chosen_estimate=pick["estimate_from"], chosen_total=total)


def check(checks: Checks, run: dict, limits: dict, expected: dict, request: str = "") -> None:
    state = run["state"]
    status = expected.get("status", "awaiting_approval")
    if not checks.same("workflow_completion", "final status", state.get("status"), status):
        return
    common.expect_requirements(checks, state, expected)
    steps = route(state.get("log", []))
    problem = route_problem(steps, status if status in ("blocked", "needs_info") else "plan", status == "booked")
    checks.need(not problem, "routing", f"{problem}; the steps were {steps}")
    retries = state.get("retries", 0)
    passes = sum(1 for line in state.get("log", []) if line.get("agent") == "supervisor")
    if common.plan_made(state):
        checks.same("conditional_routing", "planning passes (1 + automatic re-plans)", passes, 1 + retries)
        check_handover(checks, run)
        report = state["budget_report"]
        if report["over_budget"]:
            checks.need(state["strategy"] == "cheapest" and retries >= 1, "conditional_routing",
                        "over budget, but the cheaper options were not all tried")
            checks.need(common.warned(state, "over your"), "over_budget_not_told", "over budget without a warning")
        if "over_budget" in expected:
            checks.same("requirement", "over budget", report["over_budget"], expected["over_budget"])
        for part in report["incomplete"]:
            checks.need(common.warned(state, "partial", part), "missing_not_told",
                        f"the budget misses {part} and no warning says so")
        checks.same("error_recovery", "parts missing from the budget", sorted(report["incomplete"]),
                    sorted(expected.get("incomplete", [])))
    else:
        for tool in ("search_flights", "search_hotels", "search_places", "get_weather"):
            if not (status == "needs_info" and tool == "search_flights" and expected.get("may_price_travel")):
                checks.need(not common.calls(run, tool), "unnecessary_run",
                            f"{tool} ran although no plan could be made yet")
    if "retries" in expected:
        checks.same("conditional_routing", "automatic re-plans", retries, expected["retries"])
    for words in expected.get("asks_about", []):
        checks.need(words.lower() in str(state.get("message", "")).lower(), "missing_information",
                    f"the question does not mention '{words}': {state.get('message', '')!r}")
    for words in expected.get("warns", []):
        checks.need(common.warned(state, words), "expected_warning_missing", f"no warning mentions '{words}'")
    for tool in expected.get("failed_tools", []):
        made = common.calls(run, tool)
        checks.need(bool(made) and all(c["result"] is None for c in made), "case_setup",
                    f"the case should make {tool} fail")
        checks.need(len(made) <= limits.get("max_attempts", 3), "retry_limit",
                    f"{tool} was tried {len(made)} times")
        checks.need(common.warned(state, "failed"), "error_recovery", f"no warning about the failed {tool}")
    if expected.get("date_must_be_questioned"):
        said = " ".join([str(state.get("message", ""))] + [str(w) for w in state.get("warnings", [])]).lower()
        checks.need(any(w.lower() in said for w in expected["date_must_be_questioned"]), "invalid_date_silent",
                    "the date in the request does not exist, and the traveller is not told; the plan starts on "
                    f"{(state.get('constraints') or {}).get('start_date')}")
    wanted = expected.get("destinations")
    if wanted and common.plan_made(state):
        planned = state["constraints"]["destination"]
        left_out = [d for d in wanted if d != planned]
        if left_out:
            told = any(common.warned(state, d) for d in left_out)
            checks.unsupported("multi_destination", f"the planner plans one destination only: '{planned}' was "
                               f"planned and {left_out} left out" + ("" if told else ", without telling the "
                                                                     "traveller"))
    if expected.get("flexible_dates") and common.plan_made(state):
        told = common.warned(state, "flexible")
        checks.unsupported("flexible_dates", "the planner cannot compare dates: it fixed the start on "
                           f"{state['constraints']['start_date']}" + ("" if told else ", without saying that "
                                                                      "flexibility was not used"))
    check_schema(checks, state)
    if expected.get("choose_a_suggestion"):
        _check_choice(checks, run, request)
    checks.measured.update(status=state.get("status"), automatic_replans=retries,
                           tool_calls=sum(len(v) for v in run["calls"].values()),
                           warnings=len(state.get("warnings", [])))


def evaluate(case: dict) -> Result:
    request = case["input"]["request"]
    return common.judge(case, lambda ch, run, limits, expected: check(ch, run, limits, expected, request))
