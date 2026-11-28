"""Budget evaluator. It works every amount out again with ``Decimal`` and compares that with the application.

It deliberately does not import the application's budget code or its price settings: the formulas here are
written again, and food rates come from the test case. No AI is used.

An expense is ``{"category", "amount", "basis", "currency"?, "cost_factor"?}``. ``basis`` says what the amount
is for: group, per_person, per_day, per_person_per_day, per_room_per_night or percent_of_rest (contingency).
``amount`` null means the price is not known.
"""
from __future__ import annotations

import math
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation

from evaluation.results import NOT_SUPPORTED, Result, outcome

CATEGORIES = ("transport", "accommodation", "food", "local_transport", "activities", "miscellaneous",
              "contingency")
APP_LINES = {"transport": "flight", "accommodation": "hotel", "food": "food", "activities": "activities"}
RUPEE, PAISA = Decimal("1"), Decimal("0.01")


class BudgetError(ValueError):
    pass


def money(value) -> Decimal:
    if isinstance(value, float):
        raise BudgetError("money must not be a floating-point number")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise BudgetError(f"'{value}' is not an amount") from None
    if not amount.is_finite() or amount < 0:
        raise BudgetError(f"'{value}' is not an amount of money")
    return amount


def rupees(value: Decimal) -> Decimal:
    return value.quantize(RUPEE, rounding=ROUND_HALF_EVEN)


def to_inr(amount: Decimal, currency: str, rates: dict) -> Decimal:
    if currency == "INR":
        return amount
    if currency not in rates:
        raise BudgetError(f"no exchange rate for {currency}: it is not guessed")
    return amount * money(rates[currency])


def split_shares(total: Decimal, travelers: int) -> list[Decimal]:
    """Equal shares to the paisa that add up to the total exactly; leftover paise go to the first travellers."""
    total = total.quantize(PAISA, rounding=ROUND_HALF_EVEN)
    base = (total / travelers).quantize(PAISA, rounding=ROUND_DOWN)
    extra = int((total - base * travelers) / PAISA)
    return [base + (PAISA if i < extra else Decimal("0")) for i in range(travelers)]


def calculate(trip: dict) -> dict:
    """The expected budget for ``trip``: travelers, days, nights, rooms, budget, expenses, rates_to_inr."""
    travelers, days = int(trip["travelers"]), int(trip["days"])
    nights, rooms = int(trip.get("nights", days - 1)), int(trip.get("rooms", math.ceil(travelers / 2)))
    if travelers < 1 or days < 1 or nights < 0 or rooms < 1:
        raise BudgetError("travelers, days, nights and rooms must make sense")
    times = {"group": 1, "per_person": travelers, "per_day": days, "per_person_per_day": travelers * days,
             "per_room_per_night": rooms * nights}
    rates = trip.get("rates_to_inr") or {}
    lines = {c: Decimal("0") for c in CATEGORIES}
    missing, percents = [], []
    for item in trip.get("expenses") or []:
        category = item.get("category")
        if category not in CATEGORIES:
            raise BudgetError(f"unknown expense category '{category}'")
        if item.get("amount") is None:
            missing.append(category)
            continue
        if item.get("basis") == "percent_of_rest":
            percents.append((category, money(item["amount"])))
            continue
        if item.get("basis") not in times:
            raise BudgetError(f"unknown basis '{item.get('basis')}'")
        amount = to_inr(money(item["amount"]), item.get("currency", "INR"), rates)
        lines[category] += rupees(amount * times[item["basis"]] * money(item.get("cost_factor", 1)))
    rest = sum(lines.values())
    for category, percent in percents:
        lines[category] += rupees(rest * percent / 100)
    total = sum(lines.values())
    budget = money(trip["budget"])
    return {"lines": lines, "total": total, "budget": budget, "remaining": budget - total,
            "over_budget": total > budget, "overspend": max(total - budget, Decimal("0")),
            "per_person": rupees(total / travelers), "shares": split_shares(total, travelers),
            "missing": sorted(set(missing)), "complete": not missing, "travelers": travelers,
            "nights": nights, "rooms": rooms}


def compare_expected(found: dict, expected: dict) -> list[str]:
    """The evaluator's figures against the ones written in the test case."""
    wrong = []
    for key in ("total", "per_person", "remaining", "overspend", "budget"):
        if key in expected and found[key] != Decimal(str(expected[key])):
            wrong.append(f"{key}: the case expects {expected[key]}, the evaluator works out {found[key]}")
    for key in ("over_budget", "complete", "missing", "rooms", "nights"):
        if key in expected and found[key] != expected[key]:
            wrong.append(f"{key}: the case expects {expected[key]}, the evaluator works out {found[key]}")
    for name, value in (expected.get("lines") or {}).items():
        if found["lines"][name] != Decimal(str(value)):
            wrong.append(f"{name}: the case expects {value}, the evaluator works out {found['lines'][name]}")
    if "shares" in expected and found["shares"] != [Decimal(str(s)) for s in expected["shares"]]:
        wrong.append(f"shares: the case expects {expected['shares']}, the evaluator works out "
                     f"{[str(s) for s in found['shares']]}")
    if sum(found["shares"]) != found["total"]:
        wrong.append("the shares do not add up to the total")
    return wrong


def compare_report(found: dict, report: dict, label: str = "the application") -> list[str]:
    """The application's budget report against the evaluator's figures."""
    wrong = []

    def check(what, app_value, expected):
        if Decimal(str(app_value)) != expected:
            wrong.append(f"{what}: {label} says {app_value}, the correct figure is {expected}")

    for category, line in APP_LINES.items():
        check(f"{category} cost", report["lines"].get(line, 0), found["lines"][category])
    extra = set(report["lines"]) - set(APP_LINES.values())
    if extra:
        wrong.append(f"{label} has budget lines the evaluator does not check: {', '.join(sorted(extra))}")
    check("total", report["total"], found["total"])
    check("remaining budget", report["remaining"], found["remaining"])
    check("per-person cost", report["per_person"], found["per_person"])
    if sum(Decimal(str(v)) for v in report["lines"].values()) != Decimal(str(report["total"])):
        wrong.append(f"{label}'s lines do not add up to its total")
    if bool(report["over_budget"]) != found["over_budget"]:
        wrong.append(f"overspending: {label} says {report['over_budget']}, the correct answer is "
                     f"{found['over_budget']}")
    # whole-rupee per-person figures can differ from the total by at most half a rupee a person
    gap = abs(Decimal(str(report["per_person"])) * found["travelers"] - found["total"])
    if gap > Decimal(found["travelers"]) / 2:
        wrong.append(f"the per-person figures do not cover the group total (difference {gap})")
    if report.get("currency") != "INR":
        wrong.append(f"{label} reports the currency as {report.get('currency')}, not INR")
    return wrong


# ------------------------------------------------------------- the application
def unsupported(trip: dict) -> list[str]:
    """What this case needs that the application's budget cannot do."""
    out = []
    items = trip.get("expenses") or []
    lacking = sorted({i["category"] for i in items if i["category"] not in APP_LINES})
    if lacking:
        out.append(f"the application has no budget line for: {', '.join(lacking)}")
    foreign = sorted({i["currency"] for i in items if i.get("currency", "INR") != "INR"})
    if foreign:
        out.append(f"the application's budget takes rupees only, not {', '.join(foreign)}")
    return out


def app_report(trip: dict, strategy: str) -> dict:
    """The application's own budget code, given the case's prices."""
    from app.services.budget_service import build_budget_report

    travelers, days = int(trip["travelers"]), int(trip["days"])
    nights, rooms = int(trip.get("nights", days - 1)), int(trip.get("rooms", math.ceil(travelers / 2)))
    by = {}
    for item in trip.get("expenses") or []:
        by.setdefault(item["category"], []).append(item)

    def price(category, basis):
        items = by.get(category, [])
        if not items or items[0].get("amount") is None:
            return None
        if len(items) != 1 or items[0]["basis"] != basis:
            raise BudgetError(f"a planner case needs one {category} expense with basis {basis}")
        return int(items[0]["amount"])

    ticket, room = price("transport", "per_person"), price("accommodation", "per_room_per_night")
    food = by.get("food", [{}])[0]
    activities = []
    for item in by.get("activities", []):
        if item["basis"] != "per_person":
            raise BudgetError("a planner case gives activity prices per person")
        activities.append({"type": "activity", "cost_total": int(item["amount"]) * travelers})
    state = {"constraints": {"travelers": travelers, "days": days, "budget": int(trip["budget"]),
                             "destination": "test", "destination_geo": {
                                 "cost_factor": float(food.get("cost_factor", 1))}},
             "strategy": strategy,
             "flight": {"selected": None if ticket is None else {"price_pp": ticket}},
             "hotel": {"selected": None if room is None else {"price_night_per_room": room, "nights": nights,
                                                              "rooms": rooms}},
             "itinerary": {"days": [{"items": activities}]}}
    return build_budget_report(state)


def trip_from_state(state: dict, food_rates: dict, food_boost: Decimal) -> dict:
    """A finished plan turned back into unit prices, so that every total can be worked out again."""
    c = state["constraints"]
    flight, hotel = state["flight"]["selected"], state["hotel"]["selected"]
    factor = Decimal(str((c.get("destination_geo") or {}).get("cost_factor", state.get("_cost_factor", 1))))
    rate = money(food_rates[state["budget_report"]["strategy"]]) * (food_boost if state.get("food_boost") else 1)
    expenses = [{"category": "food", "basis": "per_person_per_day", "amount": rate, "cost_factor": factor},
                {"category": "transport", "basis": "per_person",
                 "amount": None if flight is None else flight["price_pp"]},
                {"category": "accommodation", "basis": "per_room_per_night",
                 "amount": None if hotel is None else hotel["price_night_per_room"]}]
    expenses += [{"category": "activities", "basis": "per_person", "amount": item["cost_pp"]}
                 for day in state["itinerary"]["days"] for item in day["items"] if item["type"] == "activity"]
    return {"travelers": c["travelers"], "days": c["days"], "nights": c["days"] - 1,
            "rooms": math.ceil(c["travelers"] / 2), "budget": c["budget"], "expenses": expenses}


def evaluate(case: dict) -> Result:
    given, expected = case["input"], case["expected"]
    if "request" in given:
        return _evaluate_plan(case)
    found = calculate(given)
    wrong = compare_expected(found, expected)
    measured = {"total": str(found["total"]), "per_person": str(found["per_person"]),
                "remaining": str(found["remaining"])}
    if case["target"] == "self_check":
        if "report" in given:                                # a planted wrong report must be caught
            caught = compare_report(found, given["report"], "the sample report")
            for text in expected["reports_problem"]:
                if not any(text in line for line in caught):
                    wrong.append(f"the planted mistake in '{text}' was not found")
            if not expected["reports_problem"]:
                wrong += caught
        return outcome(wrong, measured=measured)
    reasons = unsupported(given)
    if reasons and not wrong:
        return Result(NOT_SUPPORTED, reasons, measured=measured)
    if not reasons:
        report = app_report(given, case["expected_constraints"].get("strategy", "normal"))
        wrong += compare_report(found, report)
        if sorted(APP_LINES[c] for c in found["missing"] if c in ("transport", "accommodation")) \
                != sorted(report["incomplete"]):
            wrong.append(f"missing prices: the application marks {report['incomplete']} as incomplete, "
                         f"the case is missing {found['missing']}")
    return outcome(wrong, measured=measured)


def _evaluate_plan(case: dict) -> Result:
    """A whole plan (with change requests, if any): does the application's budget match its own prices?"""
    from app.data.curated_destinations import DESTINATIONS
    from evaluation.harness import run_planner

    given, limits = case["input"], case["expected_constraints"]
    state = run_planner(given["request"], given.get("changes"))
    c = state["constraints"]
    if not c.get("destination_geo"):
        state = {**state, "_cost_factor": DESTINATIONS[c["destination"]]["cost_factor"]}
    trip = trip_from_state(state, given["food_per_person_day"], money(given.get("food_boost", "1.25")))
    found = calculate(trip)
    report = state["budget_report"]
    wrong = compare_report(found, report)
    for key in ("travelers", "days", "budget"):
        if key in limits and c[key] != limits[key]:
            wrong.append(f"{key}: expected {limits[key]}, the plan used {c[key]}")
    hotel = state["hotel"]["selected"]
    if hotel and (hotel["rooms"], hotel["nights"]) != (found["rooms"], found["nights"]):
        wrong.append(f"rooms and nights: the plan has {hotel['rooms']} and {hotel['nights']}, expected "
                     f"{found['rooms']} and {found['nights']}")
    if "over_budget" in case["expected"] and found["over_budget"] != case["expected"]["over_budget"]:
        wrong.append(f"expected over_budget to be {case['expected']['over_budget']}")
    if found["over_budget"] and not any("over your" in w for w in state.get("warnings", [])):
        wrong.append("the plan is over budget and does not warn about it")
    return outcome(wrong, measured={"total": str(found["total"]), "app_total": report["total"],
                                    "strategy": report["strategy"]})
