"""Helpers shared by the agents."""
from __future__ import annotations

from app.graph.state import entry

WORKERS = ["flight", "hotel", "weather", "activities"]


def in_fanout(state: dict, name: str) -> bool:
    return name in state.get("fanout", WORKERS)


def agent_failure(agent: str, key: str, e: Exception, what: str) -> dict:
    return {key: {"error": str(e), "selected": None, "estimated": True},
            "warnings": [f"{what} failed after retries ({e}); the plan is partial and totals exclude it."],
            "log": [entry(agent, f"FAILED: {e}")]}


def llm_note(deps, role: str, used: bool) -> str:
    """' (LLM unavailable: why)' when a provider was configured for the role but gave no usable answer."""
    llm = getattr(deps, "llm", None)
    if used or not llm or not llm.available(role) or not llm.last_failure:
        return ""
    return f" (LLM unavailable, rule-based used: {llm.last_failure})"
