"""Conditional-edge functions. Pure: they read state and return the next node name.

The nodes that precede a router (budget, critic, approval) set ``replan_reason``;
routers only look at it, so the same functions drive both the LangGraph graph
and the dependency-free runner.
"""
from __future__ import annotations


def after_guardrail(state: dict) -> str:
    return "intake" if state.get("guardrail", {}).get("allowed") else "end"


def after_intake(state: dict) -> str:
    return "supervisor" if state.get("status") == "running" else "end"


def after_budget(state: dict) -> str:
    return "supervisor" if state.get("replan_reason") == "over_budget" else "critic"


def after_critic(state: dict) -> str:
    return "supervisor" if state.get("replan_reason") == "critic" else "present"


def after_approval(state: dict) -> str:
    if state.get("approved"):
        return "book"
    if state.get("status") == "cancelled":
        return "end"
    if state.get("replan_reason") == "feedback":
        return "supervisor"
    return "present"          # nothing changed / feedback not understood: ask again


def after_book(state: dict) -> str:
    return "writer" if state.get("booking") else "present"
