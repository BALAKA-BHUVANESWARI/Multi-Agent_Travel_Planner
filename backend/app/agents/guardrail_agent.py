"""Guardrail agent: checks the request before anything else runs."""
from __future__ import annotations

from app.core import security as guardrails
from app.graph.state import entry


def input_guardrail_node(state: dict, deps) -> dict:
    g = guardrails.check_input(state.get("request", ""))
    if not g["allowed"]:
        return {"guardrail": g, "status": "blocked", "message": g["message"],
                "log": [entry("guardrail", f"blocked: {g['code']}")]}
    return {"guardrail": g, "log": [entry("guardrail", "input allowed")]}
