"""The Decimal budget evaluator."""
from decimal import Decimal

import pytest

from app.services import budget_service
from evaluation import cases as datasets
from evaluation import run_evaluation as runner
from evaluation.evaluators import budget

TRIP = {"travelers": 3, "days": 3, "nights": 2, "rooms": 2, "budget": "10000", "expenses": [
    {"category": "transport", "basis": "per_person", "amount": "1000"},
    {"category": "accommodation", "basis": "per_room_per_night", "amount": "500"}]}


def test_every_basis_and_the_totals():
    found = budget.calculate(TRIP)
    assert (found["lines"]["transport"], found["lines"]["accommodation"]) == (3000, 2000)
    assert (found["total"], found["remaining"], found["over_budget"], found["per_person"]) == (5000, 5000, False, 1667)
    assert found["shares"] == [Decimal("1666.67"), Decimal("1666.67"), Decimal("1666.66")]


@pytest.mark.parametrize("total, travelers", [("100", 3), ("0", 4), ("88000.01", 7), ("1", 10)])
def test_shares_always_add_up(total, travelers):
    shares = budget.split_shares(Decimal(total), travelers)
    assert sum(shares) == Decimal(total) and max(shares) - min(shares) <= Decimal("0.01")


def test_decimal_amounts_stay_exact():
    trip = {"travelers": 1, "days": 1, "budget": "1", "expenses": [
        {"category": "miscellaneous", "basis": "group", "amount": "0.5", "currency": "USD"}],
        "rates_to_inr": {"USD": "3.00"}}
    assert budget.calculate(trip)["total"] == Decimal("2")          # 1.50 rounds to the even rupee


@pytest.mark.parametrize("change", [
    {"amount": 10.5}, {"amount": "-1"}, {"amount": "lots"}, {"amount": "NaN"}, {"basis": "per_week"},
    {"category": "souvenirs"}, {"currency": "GBP"}])
def test_bad_money_is_refused_and_no_rate_is_guessed(change):
    item = {"category": "miscellaneous", "basis": "group", "amount": "10", **change}
    with pytest.raises(budget.BudgetError):
        budget.calculate({"travelers": 1, "days": 2, "budget": "100", "expenses": [item]})


def test_the_evaluator_does_not_use_the_applications_formulas_or_prices():
    source = open(budget.__file__, encoding="utf-8").read()
    assert "food_line" not in source and "app.core" not in source


def test_what_the_planner_lacks_is_not_supported_never_passed():
    rows = {r["id"]: r for r in runner.run(["budget"])["cases"]}
    assert {i for i, r in rows.items() if r["status"] == "not_supported"} \
        == {"budget-extra-lines", "budget-two-currencies"}
    assert all(r["status"] == "passed" for i, r in rows.items() if r["status"] != "not_supported"), rows


def _failed(monkeypatch, damage) -> set:
    """Ids of the cases that fail when the application's budget report is damaged."""
    real = budget_service.build_budget_report

    def broken(state):
        report = real(state)
        damage(report, state)
        return report

    monkeypatch.setattr(budget_service, "build_budget_report", broken)
    monkeypatch.setattr("app.agents.budget_agent.build_budget_report", broken)
    return {r["id"] for r in runner.run(["budget"])["cases"] if r["status"] in ("failed", "error")}


def _retotal(report, key, value):
    report["lines"][key] = value
    report["total"] = sum(report["lines"].values())
    report["remaining"] = report["budget"] - report["total"]
    report["over_budget"] = report["total"] > report["budget"]
    report["per_person"] = round(report["total"] / 2)


@pytest.mark.parametrize("damage, must_fail", [
    (lambda r, s: r.update(total=r["total"] + 1), {"budget-exact", "plan-budget-couple"}),
    (lambda r, s: _retotal(r, "hotel", r["lines"]["hotel"] // 2), {"budget-exact", "plan-budget-couple"}),
    (lambda r, s: _retotal(r, "food", r["lines"]["food"] + 100), {"budget-exact", "plan-budget-longer"}),
    (lambda r, s: r.update(over_budget=False), {"budget-one-short", "plan-budget-impossible"}),
    (lambda r, s: r.update(per_person=r["total"]), {"budget-exact", "plan-budget-five"}),
    (lambda r, s: r.update(incomplete=[]), {"budget-missing-fare"}),
])
def test_a_wrong_application_budget_is_caught(monkeypatch, damage, must_fail):
    assert must_fail <= _failed(monkeypatch, damage)


def test_dataset_money_is_never_read_as_floating_point(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"synthetic": true, "label": "SYNTHETIC", "cases": [{"id": "a", "description": "d", '
                    '"category": "c", "target": "planner", "input": {"v": 0.1}, "expected_constraints": {}, '
                    '"expected": {}}]}', encoding="utf-8")
    assert datasets.load(path)[0]["input"]["v"] == Decimal("0.1")
