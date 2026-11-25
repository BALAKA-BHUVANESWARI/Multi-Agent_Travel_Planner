"""MCP tool server (stdio). Run with:  python -m travel_planner.mcp_server

Works with both the v1 (``FastMCP``) and v2 (``MCPServer``) Python SDKs.
"""
from __future__ import annotations

from typing import Any

try:                                            # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                             # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .tools import impl
from .tools.errors import ToolError


def _run(fn, *args) -> dict[str, Any]:
    """Return tool errors as data so the client keeps the message and retryable flag."""
    try:
        return fn(*args)
    except ToolError as e:
        return {"error": str(e), "retryable": e.retryable}

mcp = _Server("travel-planner-tools")


@mcp.tool()
def resolve_place(query: str) -> dict[str, Any]:
    """Any place name -> coordinates, country and price level (curated, offline list, then live geocoding)."""
    return _run(impl.resolve_place, query)


@mcp.tool()
def search_flights(origin: str, destination: str, depart_date: str, return_date: str, travelers: int,
                   origin_geo: dict[str, Any] | None = None,
                   destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estimated round-trip travel options (synthetic estimator, INR per person): flights, or train/bus
    for short distances. ``*_geo`` is the record returned by resolve_place for non-curated places."""
    return _run(impl.search_flights, origin, destination, depart_date, return_date, travelers,
                origin_geo, destination_geo)


@mcp.tool()
def search_hotels(destination: str, checkin: str, nights: int, travelers: int,
                  destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estimated hotel options by tier (synthetic estimator, INR per room per night)."""
    return _run(impl.search_hotels, destination, checkin, nights, travelers, destination_geo)


@mcp.tool()
def get_weather(destination: str, start_date: str, days: int, today: str,
                destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Day-by-day weather: Open-Meteo forecast within 16 days, otherwise climate estimate."""
    return _run(impl.get_weather, destination, start_date, days, today, destination_geo)


@mcp.tool()
def search_places(destination: str, preferences: list[str] | None = None,
                  destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Candidate places: curated list, or OpenStreetMap places (any destination), plus Wikivoyage tips."""
    return _run(impl.search_places, destination, preferences, destination_geo)


@mcp.tool()
def search_dining(destination: str, destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Top restaurants split into vegetarian and non-vegetarian, with hours and best time to go (live data)."""
    return _run(impl.search_dining, destination, destination_geo)


@mcp.tool()
def book_trip(idempotency_key: str, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """MOCK booking with an idempotency key. Nothing is purchased."""
    return _run(impl.book_trip, idempotency_key, summary)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
