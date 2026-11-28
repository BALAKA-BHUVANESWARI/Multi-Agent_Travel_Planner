"""Supervisor: what was understood, which agents ran, and what happens when something is missing or fails.

There are two kinds of input. ``{"request": ...}`` runs a whole trip. ``{"state": ...}`` hands one made-up state
to the supervisor and looks at its decision, which is how each re-planning reason is tested on its own.
"""
from __future__ import annotations

from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.results import Result

WORKERS = ("flight", "hotel", "weather", "activities")
# the tool each worker agent cannot do without
WORKER_TOOLS = {"flight": "search_flights", "hotel": "search_hotels", "weather": "get_weather",
                "activities": "search_places"}


def _make(given: dict) -> dict:
    if "state" not in given:
        return common.make_run(given)
    from app.agents.supervisor import supervisor_node

    run = {"state": dict(given["state"]), "calls": {}, "decision": supervisor_node(dict(given["state"]), None)}
    for change in given.get("damage", []):
        common.damage(run, change)
    return run


def _check_decision(checks: Checks, run: dict, expected: dict) -> None:
    decision = run["decision"]
    checks.same("agent_selection", "agents chosen to run", sorted(decision["fanout"]), sorted(expected["agents"]))
    if "strategy" in expected:
        checks.same("strategy", "price level", decision.get("strategy", run["state"].get("strategy", "normal")),
                    expected["strategy"])
    if "retries" in expected:
        checks.same("retry_count", "automatic re-plans used",
                    decision.get("retries", run["state"].get("retries", 0)), expected["retries"])
    for key in expected.get("cleared", []):
        checks.need(key in decision and decision[key] in (None, [], {}), "stale_result",
                    f"the old {key} was not cleared before the agents run again")
    for key in expected.get("kept", []):
        checks.need(key not in decision, "kept_result_lost", f"{key} should be kept, but the supervisor replaced it")


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    if "decision" in run:
        _check_decision(checks, run, expected)
        return
    state = run["state"]
    checks.same("workflow_status", "status", state.get("status"), expected["status"])
    common.expect_requirements(checks, state, expected)
    ran = sorted(w for w, tool in WORKER_TOOLS.items() if common.calls(run, tool))
    if "agents" in expected:
        checks.same("agent_selection", "worker agents that ran", ran, sorted(expected["agents"]))
    # the trip tools are only used by the agents (the travel-choice question may price each way of travelling)
    for tool in expected.get("tools_not_used", []):
        checks.need(not common.calls(run, tool), "unnecessary_run", f"{tool} was called although it was not needed")
    for tool, most in (limits.get("max_calls") or {}).items():
        checks.need(len(common.calls(run, tool)) <= most, "unnecessary_run",
                    f"{tool} was called {len(common.calls(run, tool))} times; at most {most} expected")
    for words in expected.get("asks_about", []):
        checks.need(words.lower() in str(state.get("message", "")).lower(), "missing_information",
                    f"the question to the traveller does not mention '{words}': {state.get('message', '')!r}")
    for agent in expected.get("failed_agents", []):
        key = agent
        block = state.get(key) or {}
        checks.need(bool(block.get("error")), "failure_handling", f"the {agent} failure is not recorded in the plan")
        checks.need(common.warned(state, "failed"), "failure_handling",
                    f"no warning tells the traveller that the {agent} step failed")
    if expected.get("failed_agents"):
        others = [w for w in WORKERS if w not in expected["failed_agents"]]
        for other in others:
            checks.need(bool(state.get(other)) and not state[other].get("error"), "failure_spread",
                        f"the {other} agent gave no result when another agent failed")
        checks.need(common.plan_made(state), "failure_spread", "no partial plan was made after the failure")
    repeats = {}
    for tool, made in run["calls"].items():
        same = [str(sorted(c["args"].items())) for c in made if c["result"] is not None]
        if len(same) > len(set(same)):
            repeats[tool] = len(same) - len(set(same))
    if repeats:
        checks.warn("repeated_lookup", "asked more than once with the same details: "
                    + ", ".join(f"{t} ({n} more)" for t, n in sorted(repeats.items())))
    checks.measured.update(agents_run=ran, tool_calls=sum(len(v) for v in run["calls"].values()),
                           automatic_replans=state.get("retries", 0))


def evaluate(case: dict) -> Result:
    return common.judge(case, check, _make)
