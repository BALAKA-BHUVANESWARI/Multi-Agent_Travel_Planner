"""The graph's nodes, by name. Both engines (LangGraph and the built-in runner) are built from this one list,
so they always run the same agents. Each node is ``fn(state, deps) -> update`` and never mutates the state."""
from __future__ import annotations

from app.agents.accommodation_agent import hotel_node
from app.agents.activity_agent import activities_node
from app.agents.approval_agent import approval_node, present_node
from app.agents.booking_agent import book_node
from app.agents.budget_agent import budget_node
from app.agents.common import WORKERS
from app.agents.critic_agent import critic_node
from app.agents.guardrail_agent import input_guardrail_node
from app.agents.intake_agent import intake_node
from app.agents.itinerary_agent import merge_node, writer_node
from app.agents.supervisor import supervisor_node
from app.agents.transport_agent import flight_node
from app.agents.weather_agent import weather_node

NODES = {
    "guardrail": input_guardrail_node,
    "intake": intake_node,
    "supervisor": supervisor_node,
    "flight": flight_node,           # the four workers below run in parallel
    "hotel": hotel_node,
    "weather": weather_node,
    "activities": activities_node,
    "merge": merge_node,
    "budget": budget_node,
    "critic": critic_node,
    "present": present_node,
    "book": book_node,
    "writer": writer_node,
}

__all__ = ["NODES", "WORKERS", "approval_node"]     # "approval" pauses for a person, so each engine wires it itself
