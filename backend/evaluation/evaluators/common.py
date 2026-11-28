"""What the agent and trip evaluators share.

Each of them is a function ``check(run, constraints, expected) -> findings`` over a *run*: the finished state
plus every tool call with what was asked and answered. The same function is used twice:

* ``planner`` cases run the real planner and fail on any hard finding.
* ``self_check`` cases run the planner, then **damage** its output on purpose (``input.damage``). The evaluator
  must report exactly the codes in ``expected.finds``: no mistake missed, nothing extra.
"""
from __future__ import annotations

import copy

from evaluation import harness
from evaluation.results import FAIL, INFO, NOT_SUPPORTED, UNSUPPORTED, WARN, Finding, Result, outcome


class Checks:
    """Collects findings and counts the checks that were made."""

    def __init__(self):
        self.findings: list[Finding] = []
        self.made = 0
        self.measured: dict = {}

    def need(self, ok, code: str, message: str) -> bool:
        """A rule that must hold; ``message`` says what is wrong when it does not."""
        self.made += 1
        if not ok:
            self.findings.append(Finding(code, FAIL, message))
        return bool(ok)

    def same(self, code: str, what: str, found, expected) -> bool:
        return self.need(found == expected, code, f"{what}: expected {expected!r}, found {found!r}")

    def warn(self, code: str, message: str) -> None:
        self.findings.append(Finding(code, WARN, message))

    def unchecked(self, code: str, message: str) -> None:
        self.findings.append(Finding(code, INFO, message))

    def unsupported(self, code: str, message: str) -> None:
        self.findings.append(Finding(code, UNSUPPORTED, message))


def make_run(given: dict) -> dict:
    run = harness.run_trip(given["request"], group=given.get("group"), failures=given.get("failures"),
                           changes=given.get("changes"), approve=bool(given.get("approve")),
                           ask_travel_mode=bool(given.get("ask_travel_mode")))
    for change in given.get("damage", []):
        damage(run, change)
    return run


def damage(run, change: dict) -> None:
    """Plant one mistake. ``path`` is dotted ("state.flight.selected.price_pp"); list positions are numbers.
    The change is {"set": value}, {"delete": true}, {"append": value} or {"copy_from": path} (append a copy of
    what is at another path to the list at ``path``). A path that does not exist is an error:
    a self-check must never pass because its mistake was not planted."""
    if "copy_from" in change:
        found = run
        for part in change["copy_from"].split("."):
            found = found[int(part)] if isinstance(found, list) else found[part]
        change = {"path": change["path"], "append": copy.deepcopy(found)}
    *parents, last = change["path"].split(".")
    node = run
    for part in parents:
        node = node[int(part)] if isinstance(node, list) else node[part]
    key = int(last) if isinstance(node, list) else last
    if "append" in change:
        node[key].append(copy.deepcopy(change["append"]))
        return
    if isinstance(node, dict) and key not in node and not change.get("new"):
        raise KeyError(f"nothing to damage at {change['path']}")
    if change.get("delete"):
        del node[key]
    else:
        node[key] = change["set"]


def judge(case: dict, check, make=make_run) -> Result:
    checks = Checks()
    run = make(case["input"])
    check(checks, run, case["expected_constraints"], case["expected"])
    measured = {"checks_made": checks.made, **checks.measured}
    hard = [f for f in checks.findings if f.severity == FAIL]
    if case["target"] == "self_check":
        wanted = sorted(case["expected"]["finds"])
        found = sorted({f.code for f in hard})
        wrong = [] if found == wanted else [f"planted mistakes: expected the checks {wanted} to fail, "
                                            f"but these failed: {found}"]
        return outcome(wrong, checks.findings, measured)
    if hard:
        return outcome([f"{f.code}: {f.message}" for f in hard], checks.findings, measured)
    missing = [f.message for f in checks.findings if f.severity == UNSUPPORTED]
    if missing:
        return Result(NOT_SUPPORTED, missing, checks.findings, measured)
    return outcome([], checks.findings, measured)


def warned(state: dict, *words: str) -> bool:
    """True when one of the plan's warnings contains all the words (any case)."""
    return any(all(w.lower() in str(text).lower() for w in words) for text in state.get("warnings", []))


def plan_made(state: dict) -> bool:
    return bool(state.get("itinerary") and state.get("budget_report"))


def planned_activities(state: dict) -> list[tuple[dict, dict]]:
    return [(day, item) for day in (state.get("itinerary") or {}).get("days", [])
            for item in day["items"] if item["type"] == "activity"]


def calls(run: dict, tool: str) -> list[dict]:
    return run["calls"].get(tool, [])


def answered(run: dict, tool: str) -> dict | None:
    """The last successful call of a tool."""
    return next((c for c in reversed(calls(run, tool)) if c["result"] is not None), None)


def trip_dates(constraints: dict) -> tuple[str, str]:
    from datetime import date, timedelta
    start = date.fromisoformat(constraints["start_date"])
    return start.isoformat(), (start + timedelta(days=constraints["days"] - 1)).isoformat()


def expect_requirements(checks: Checks, state: dict, expected: dict) -> None:
    """The requirements the planner understood, as listed in the case."""
    got = state.get("constraints") or {}
    for key, value in (expected.get("requirements") or {}).items():
        found = got.get(key)
        if key == "preferences":
            checks.same("requirement", "preferences", sorted(found or []), sorted(value))
        else:
            checks.same("requirement", key, found, value)
