"""The itinerary validator."""
import copy

import pytest

from app.services import itinerary_builder
from evaluation import cases as datasets
from evaluation import run_evaluation as runner
from evaluation.evaluators import itinerary

CASES = {c["id"]: c for c in datasets.load(datasets.DATASETS / "itinerary_cases.json")}


@pytest.mark.parametrize("case_id", [i for i, c in CASES.items() if c["target"] == "self_check"])
def test_planted_mistakes_are_found_and_nothing_else(case_id):
    result = itinerary.evaluate(CASES[case_id])
    assert result.status == "passed", result.failures


def test_every_itinerary_case_passes():
    rows = runner.run(["itinerary"])["cases"]
    assert [r["id"] for r in rows if r["status"] != "passed"] == []


def test_dropping_an_interest_without_saying_so_still_fails(monkeypatch):
    monkeypatch.setattr("app.services.itinerary_builder._lost_to_rain", lambda *a: None)
    result = runner.run_case("itinerary", CASES["plan-goa-monsoon"], itinerary.evaluate)
    assert any("preferences_ignored" in why for why in result["failures"]), result["failures"]


def test_no_route_data_means_not_checked_not_a_guess():
    clean = CASES["check-clean"]["input"]
    found = itinerary.validate(clean["itinerary"], clean["constraints"], clean["context"])
    assert {f.code for f in found} == {"travel_time_not_checked"}
    assert all(f.severity == "not_checked" for f in found)


def test_a_misspelled_rule_is_refused():
    clean = CASES["check-clean"]["input"]
    with pytest.raises(ValueError):
        itinerary.validate(clean["itinerary"], clean["constraints"], rules={"max_activites_per_day": 2})


def test_the_input_is_not_changed():
    clean = CASES["check-clean"]["input"]
    before = copy.deepcopy(clean)
    itinerary.validate(clean["itinerary"], clean["constraints"], clean["context"])
    assert clean == before


def _drop_day(plan):
    plan["days"].pop(1)


def _same_time(plan):
    day = plan["days"][1]["items"]
    day.append(dict(next(i for i in day if i["type"] == "activity"), id="copy", name="Another stop"))


def _repeat(plan):
    first = next(i for i in plan["days"][1]["items"] if i["type"] == "activity")
    last = [i for i in plan["days"][2]["items"] if i["type"] == "activity"]
    last[0].update(id=first["id"], name=first["name"])


def _wrong_dates(plan):
    for day in plan["days"]:
        day["date"] = "2030-01-0" + str(day["day"])


@pytest.mark.parametrize("damage, code", [(_drop_day, "missing_day"), (_same_time, "time_conflict"),
                                          (_repeat, "duplicate_activity"), (_wrong_dates, "outside_dates")])
def test_a_wrong_planner_itinerary_is_caught(monkeypatch, damage, code):
    real = itinerary_builder.build_itinerary

    def broken(*args):
        plan, warnings = real(*args)
        damage(plan)
        return plan, warnings

    monkeypatch.setattr("app.agents.itinerary_agent.build_itinerary", broken)
    result = runner.run_case("itinerary", CASES["plan-goa"], itinerary.evaluate)
    assert result["status"] == "failed" and any(code in why for why in result["failures"]), result["failures"]


def test_switching_off_the_rain_swap_is_caught(monkeypatch):
    real = itinerary_builder.build_itinerary

    def no_weather_rule(constraints, flight, hotel, weather, candidates):
        dry = {**weather, "days": [{**d, "rainy": False} for d in weather["days"]]}
        return real(constraints, flight, hotel, dry, candidates)

    monkeypatch.setattr("app.agents.itinerary_agent.build_itinerary", no_weather_rule)
    result = runner.run_case("itinerary", CASES["plan-goa-monsoon"], itinerary.evaluate)
    assert any("outdoor_in_rain" in why for why in result["failures"]), result["failures"]
