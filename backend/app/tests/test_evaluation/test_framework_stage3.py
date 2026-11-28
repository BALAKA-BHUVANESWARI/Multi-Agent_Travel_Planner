"""The source and change-request evaluators: their planted mistakes are real ones, and breaking the planner on
purpose is caught."""
import copy

import pytest

from app.agents import itinerary_agent
from app.graph import nodes
from app.graph import runner as runner_module
from app.integrations import live_prices
from app.services import ai_guard
from evaluation import cases as datasets
from evaluation import harness
from evaluation import run_evaluation as runner

NEW = ("grounding", "replanning")
# problems each one reproduced by hand against the application; a fix removes its line here
KNOWN_FAILURES = [
    "rp-cheaper-flight-agents", "rp-cheaper-flight-result", "rp-cheaper-hotel-agents", "rp-cheaper-hotel-result",
    "rp-flight-to-train-result", "rp-more-history-agents", "rp-no-adventure-agents", "rp-one-more-person-agents",
    "rp-to-train-agents"]
NOT_SUPPORTED = [
    "grd-full-hotel", "grd-full-live-fare", "grd-full-places", "grd-full-travel", "grd-full-weather",
    "rp-indoor-only-result", "rp-named-member-result", "rp-new-preferences-result", "rp-version"]


def load(agent):
    return datasets.load(datasets.DATASETS / runner.EVALUATORS[agent][0])


def run_one(agent, case_id):
    case = next(c for c in load(agent) if c["id"] == case_id)
    return runner.run_case(agent, case, runner.EVALUATORS[agent][1])


def codes(row):
    return sorted({f.split(":")[0] for f in row["failures"]})


@pytest.fixture(scope="module")
def results():
    return {r["id"]: r for r in runner.run(list(NEW))["cases"]}


def test_only_the_known_problems_fail(results):
    assert sorted(i for i, r in results.items() if r["status"] in ("failed", "error")) == KNOWN_FAILURES


def test_what_the_planner_cannot_do_is_never_counted_as_passed(results):
    assert sorted(i for i, r in results.items() if r["status"] == "not_supported") == NOT_SUPPORTED


SELF_CHECKS = [(agent, c) for agent in NEW for c in load(agent) if c["target"] == "self_check"]


@pytest.mark.parametrize("agent,case", [pytest.param(a, c, id=c["id"]) for a, c in SELF_CHECKS])
def test_without_the_planted_mistake_nothing_is_reported(agent, case):
    clean = copy.deepcopy(case)
    del clean["input"]["damage"]
    clean["target"] = "planner"
    row = runner.run_case(agent, clean, runner.EVALUATORS[agent][1])
    assert row["status"] in ("passed", "not_supported"), row["failures"]


def test_every_change_in_the_request_list_has_a_case():
    categories = {c["category"] for c in load("replanning")}
    assert {"cheaper_hotel", "budget_change", "more_days", "destination", "indoor", "remove_activities",
            "add_traveller", "preferences", "transport", "versions"} <= categories
    agent_cases = [c for c in load("replanning") if c["category"] == "affected_agents"]
    assert all("agents" in c["expected"] for c in agent_cases)


def test_the_pretend_ai_and_recorded_pages_are_switched_off_afterwards():
    page = live_prices.get_page
    run = harness.run_trip("Plan a 4 day trip from Delhi to Goa", ai={"intake": {"budget_inr": 50000}},
                           live={"pages": {}, "fetched_at": "2026-11-24T08:00:00+00:00"})
    assert "intake" in run["ai_asked"] and live_prices.get_page is page


# ---------------------------------------------------------------- breaking the planner on purpose
def broken(monkeypatch, node, change):
    original = nodes.NODES[node]

    def wrapped(state, deps, *extra):
        update = copy.deepcopy(original(state, deps, *extra))
        change(state, update)
        return update

    monkeypatch.setitem(nodes.NODES, node, wrapped)


def test_a_dropped_price_guard_is_caught(monkeypatch):
    assert run_one("grounding", "grd-ai-amount")["status"] == "passed"
    monkeypatch.setattr(itinerary_agent, "numbers_are_grounded", lambda text, allowed: True)
    monkeypatch.setattr(ai_guard, "unsupported", lambda *args, **kwargs: [])        # the second guard
    assert "ai_invented_shown" in codes(run_one("grounding", "grd-ai-amount"))


@pytest.mark.parametrize("case_id", ["grd-ai-budget", "grd-ai-days"])
def test_taking_the_ai_value_again_is_caught(monkeypatch, case_id):
    assert run_one("grounding", case_id)["status"] == "passed"
    monkeypatch.setattr(ai_guard, "typed_value", lambda *args: True)
    assert "ai_filled_missing_value" in codes(run_one("grounding", case_id))


def test_taking_the_ai_starting_city_again_is_caught(monkeypatch):
    assert run_one("grounding", "grd-ai-origin")["status"] == "passed"
    monkeypatch.setattr(ai_guard, "typed_place", lambda *args: True)
    assert "ai_filled_missing_value" in codes(run_one("grounding", "grd-ai-origin"))


@pytest.mark.parametrize("case_id", ["grd-ai-destination", "grd-ai-destination-unnamed"])
def test_taking_the_ai_destination_again_is_caught(monkeypatch, case_id):
    assert run_one("grounding", case_id)["status"] == "passed"
    monkeypatch.setattr(ai_guard, "typed_place", lambda *args: True)
    assert "ai_filled_missing_value" in codes(run_one("grounding", case_id))


@pytest.mark.parametrize("case_id", ["grd-ai-amount-words", "grd-ai-place", "grd-ai-chat"])
def test_showing_unchecked_ai_text_again_is_caught(monkeypatch, case_id):
    assert run_one("grounding", case_id)["status"] == "passed"
    monkeypatch.setattr(ai_guard, "unsupported", lambda *args, **kwargs: [])
    assert "ai_invented_shown" in codes(run_one("grounding", case_id))


def test_a_provider_name_that_gets_lost_is_caught(monkeypatch):
    broken(monkeypatch, "hotel", lambda state, update: update["hotel"].pop("source"))
    assert "provider_missing" in codes(run_one("grounding", "grd-domestic"))


def test_a_price_changed_after_the_source_answered_is_caught(monkeypatch):
    broken(monkeypatch, "hotel",
           lambda state, update: update["hotel"]["selected"].__setitem__("price_night_per_room", 1))
    assert "price_night_per_room_mismatch" in codes(run_one("grounding", "grd-domestic"))


def test_a_change_that_loses_an_earlier_requirement_is_caught(monkeypatch):
    assert run_one("replanning", "rp-two-more-days-result")["status"] == "passed"

    original = runner_module.approval_node

    def forget(state, decision, deps):
        update = copy.deepcopy(original(state, decision, deps))
        update["constraints"]["preferences"] = []
        return update

    monkeypatch.setattr(runner_module, "approval_node", forget)
    assert "unintended_change" in codes(run_one("replanning", "rp-two-more-days-result"))


def test_rooms_that_are_not_worked_out_again_are_caught(monkeypatch):
    def keep_old_rooms(state, update):
        if state.get("revisions"):
            update["hotel"]["selected"]["rooms"] = 1

    broken(monkeypatch, "hotel", keep_old_rooms)
    assert "not_recalculated" in codes(run_one("replanning", "rp-one-more-person-result"))


def test_weather_fetched_again_for_nothing_is_caught(monkeypatch):
    assert "weather" not in str(run_one("replanning", "rp-to-train-agents")["failures"])

    def also_weather(state, update):
        if state.get("revisions"):
            update["fanout"] = [*update["fanout"], "weather"]

    broken(monkeypatch, "supervisor", also_weather)
    assert "weather" in str(run_one("replanning", "rp-to-train-agents")["failures"])
