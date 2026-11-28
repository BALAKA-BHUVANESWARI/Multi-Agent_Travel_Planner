"""The agent and whole-trip evaluators: their planted mistakes are real ones, and breaking the planner on
purpose is caught."""
import copy

import pytest

from app.graph import nodes
from evaluation import cases as datasets
from evaluation import run_evaluation as runner
from evaluation.evaluators import common, response
from evaluation.evaluators.end_to_end import route, route_problem
from evaluation.results import FAIL

NEW = ("supervisor", "destination", "transport", "accommodation", "weather", "activity", "group", "end_to_end")


def load(agent):
    return datasets.load(datasets.DATASETS / runner.EVALUATORS[agent][0])


def run_one(agent, case_id):
    case = next(c for c in load(agent) if c["id"] == case_id)
    return runner.run_case(agent, case, runner.EVALUATORS[agent][1])


@pytest.fixture(scope="module")
def results():
    return {r["id"]: r for r in runner.run(list(NEW))["cases"]}


def test_only_the_known_problems_fail(results):
    assert sorted(i for i, r in results.items() if r["status"] in ("failed", "error")) == []


def test_what_the_planner_cannot_do_is_never_counted_as_passed(results):
    assert sorted(i for i, r in results.items() if r["status"] == "not_supported") == [
        "ac-amenities", "ac-rating", "ac-source-link", "act-entry-fees", "act-opening-hours", "dst-sources",
        "e2e-flexible-dates", "e2e-multi-destination", "tr-live-availability", "tr-source-link", "wx-freshness"]
    assert "without telling" in results["e2e-multi-destination"]["failures"][0]


# (a few self-checks plant their mistake in the expectation, so they have no damage to remove)
SELF_CHECKS = [(agent, c) for agent in NEW for c in load(agent)
               if c["target"] == "self_check" and c["input"].get("damage")]


@pytest.mark.parametrize("agent,case", [pytest.param(a, c, id=c["id"]) for a, c in SELF_CHECKS])
def test_without_the_planted_mistake_nothing_is_reported(agent, case):
    """Otherwise a self-check could pass without noticing its mistake."""
    clean = copy.deepcopy(case)
    del clean["input"]["damage"]
    clean["target"] = "planner"
    row = runner.run_case(agent, clean, runner.EVALUATORS[agent][1])
    assert row["status"] in ("passed", "not_supported"), row["failures"]


def test_damage_that_misses_its_target_is_an_error():
    with pytest.raises(KeyError):
        common.damage({"a": {}}, {"path": "a.nothing", "set": 1})


def test_a_missing_requirement_is_a_hard_failure():
    checks = common.Checks()
    common.expect_requirements(checks, {"constraints": {"days": 3}}, {"requirements": {"days": 4}})
    assert [(f.code, f.severity) for f in checks.findings] == [("requirement", FAIL)]


# ---------------------------------------------------------------- breaking the planner on purpose
def broken(monkeypatch, node, change):
    original = nodes.NODES[node]

    def run(state, deps):
        update = copy.deepcopy(original(state, deps))
        change(state, update)
        return update

    monkeypatch.setitem(nodes.NODES, node, run)


def failures(agent, case_id):
    row = run_one(agent, case_id)
    assert row["status"] == "failed", row
    return " | ".join(row["failures"])


def test_a_supervisor_that_refetches_the_weather_is_caught(monkeypatch):
    def change(state, update):
        if state.get("replan_reason") == "over_budget":
            update.update(fanout=["flight", "hotel", "activities", "weather"], weather=None)
    broken(monkeypatch, "supervisor", change)
    from app.agents import supervisor                     # the routing cases call the supervisor directly
    monkeypatch.setattr(supervisor, "supervisor_node", lambda state, deps: nodes.NODES["supervisor"](state, deps))
    assert "agent_selection" in failures("supervisor", "sup-replan-budget")
    assert "unnecessary_run" in failures("supervisor", "sup-over-budget-keeps-weather")


def test_a_changed_travel_price_is_caught(monkeypatch):
    def change(state, update):
        update["flight"]["selected"]["price_pp"] -= 100
    broken(monkeypatch, "flight", change)
    assert "price_pp_mismatch" in failures("transport", "tr-domestic")


def test_too_few_rooms_are_caught(monkeypatch):
    def change(state, update):
        update["hotel"]["selected"]["rooms"] = 1
    broken(monkeypatch, "hotel", change)
    assert "wrong_guests" in failures("accommodation", "ac-seven")


def test_ignoring_rain_is_caught(monkeypatch):
    from app.agents import itinerary_agent
    original = itinerary_agent.build_itinerary

    def dry(constraints, flight, hotel, weather, candidates):
        pretend = {**weather, "days": [{**d, "rainy": False} for d in weather["days"]]}
        itinerary, warnings = original(constraints, flight, hotel, pretend, candidates)
        for day, row in zip(itinerary["days"], weather["days"]):
            day.update(weather=row, rainy=row["rainy"])
        return itinerary, warnings

    monkeypatch.setattr(itinerary_agent, "build_itinerary", dry)
    assert "outdoor_in_rain" in failures("weather", "wx-plan-monsoon")


def test_planning_the_same_place_every_day_is_caught(monkeypatch):
    def change(state, update):
        days = update["itinerary"]["days"]
        first = next(i for i in days[1]["items"] if i["type"] == "activity")
        days[2]["items"].append(dict(first))
    broken(monkeypatch, "merge", change)
    assert "duplicate" in failures("activity", "act-goa-beach")


def test_suggestions_that_claim_to_fit_the_budget_are_caught(monkeypatch):
    from app.tools import destination_tools
    from app.tools.registry import TOOLS
    original = TOOLS["recommend_destinations"]

    def generous(**kwargs):
        out = original(**kwargs)
        for item in out["suggestions"]:
            item["fits_budget"] = True
        return out

    monkeypatch.setitem(TOOLS, "recommend_destinations", generous)
    assert destination_tools.recommend_destinations is not generous
    assert "budget_flag" in failures("destination", "dst-low-budget")


def test_a_group_report_that_flatters_is_caught(monkeypatch):
    def change(state, update):
        for member in update["group_report"]:
            member["conflicts"] = []
    broken(monkeypatch, "merge", change)
    assert "report_wrong" in failures("group", "grp-conflict")


def test_a_plan_shown_without_the_critic_is_caught(monkeypatch):
    broken(monkeypatch, "critic", lambda state, update: update.update(log=[]))
    assert "routing" in failures("end_to_end", "e2e-domestic")


# ---------------------------------------------------------------- the helpers
def test_the_route_joins_the_parallel_workers():
    log = [{"agent": a} for a in ["guardrail", "intake", "supervisor", "hotel", "flight", "merge", "budget",
                                  "supervisor", "weather", "merge", "budget", "critic", "present"]]
    steps = route(log)
    assert steps.count("workers") == 2 and route_problem(steps, "plan", False) == ""


@pytest.mark.parametrize("steps", [["intake", "supervisor"], ["guardrail", "intake", "present"],
                                   ["guardrail", "intake", "supervisor", "workers", "merge", "budget", "present"],
                                   ["guardrail", "intake", "supervisor", "workers", "budget", "critic", "present"]])
def test_illegal_routes_are_refused(steps):
    assert route_problem(steps, "plan", False)


def test_shapes_are_checked_all_the_way_down():
    from app.schemas.budget import BudgetReport
    good = {"currency": "INR", "lines": {"flight": 1, "hotel": 1, "activities": 1, "food": 1}, "total": 4,
            "budget": 5, "over_budget": False, "remaining": 1, "per_person": 4, "strategy": "normal",
            "estimated": True, "incomplete": [], "live": []}
    assert response.problems(good, BudgetReport, "r") == []
    bad = {**good, "lines": {**good["lines"], "food": "much"}, "total": True}
    assert len(response.problems(bad, BudgetReport, "r")) == 2
    del bad["currency"]
    assert "r.currency: missing" in response.problems(bad, BudgetReport, "r")
