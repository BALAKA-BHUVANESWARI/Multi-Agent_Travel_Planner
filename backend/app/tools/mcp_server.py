"""MCP tool server (stdio). Run with:  python -m app.tools.mcp_server

Works with both the v1 (``FastMCP``) and v2 (``MCPServer``) Python SDKs.
"""
from __future__ import annotations

from typing import Any

try:                                            # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                             # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from app.tools import registry
from app.tools.errors import ToolError


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
    return _run(registry.resolve_place, query)


@mcp.tool()
def search_flights(origin: str, destination: str, depart_date: str, return_date: str, travelers: int,
                   origin_geo: dict[str, Any] | None = None,
                   destination_geo: dict[str, Any] | None = None,
                   mode: str | None = None, live_prices: bool = True) -> dict[str, Any]:
    """Round-trip travel options, INR per person: LIVE Google Flights fares when a Tavily key is set and the
    lookup works (``estimated`` is then false), otherwise a synthetic estimate. ``mode``: flight, train, bus, car
    or bike (None or "auto": a flight, or train/bus for short distances). ``*_geo`` is the record returned by
    resolve_place for non-curated places. ``live_prices=False`` skips the live lookup."""
    return _run(registry.search_flights, origin, destination, depart_date, return_date, travelers,
                origin_geo, destination_geo, mode, live_prices)


@mcp.tool()
def search_hotels(destination: str, checkin: str, nights: int, travelers: int,
                  destination_geo: dict[str, Any] | None = None, live_prices: bool = True) -> dict[str, Any]:
    """Hotel options by tier, INR per room per night: LIVE Google Hotels prices when a Tavily key is set and the
    lookup works (``estimated`` is then false), otherwise a synthetic estimate."""
    return _run(registry.search_hotels, destination, checkin, nights, travelers, destination_geo, live_prices)


@mcp.tool()
def get_weather(destination: str, start_date: str, days: int, today: str,
                destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Day-by-day weather: Open-Meteo forecast within 16 days, otherwise climate estimate."""
    return _run(registry.get_weather, destination, start_date, days, today, destination_geo)


@mcp.tool()
def search_places(destination: str, preferences: list[str] | None = None,
                  destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Candidate places: curated list, or OpenStreetMap places (any destination), plus Wikivoyage tips."""
    return _run(registry.search_places, destination, preferences, destination_geo)


@mcp.tool()
def search_dining(destination: str, destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Top restaurants split into vegetarian and non-vegetarian, with hours and best time to go (live data)."""
    return _run(registry.search_dining, destination, destination_geo)


@mcp.tool()
def recommend_destinations(origin: str, start_date: str, days: int, travelers: int, budget: int,
                           preferences: list[str] | None = None, exclude: str | None = None,
                           origin_geo: dict[str, Any] | None = None, exclude_geo: dict[str, Any] | None = None,
                           scope: str = "any", mode: str | None = None, limit: int = 4) -> dict[str, Any]:
    """Destinations that suit the interests, month and budget, priced with the estimator (never live fares)."""
    return _run(registry.recommend_destinations, origin, start_date, days, travelers, budget, preferences,
                exclude, origin_geo, exclude_geo, scope, mode, limit)


@mcp.tool()
def find_help_nearby(lat: float, lon: float, remember: bool = True) -> dict[str, Any]:
    """Hospitals, clinics, pharmacies and police stations near a point (OpenStreetMap), with phone numbers where
    mapped. ``remember=False`` keeps no copy of the position."""
    return _run(registry.find_help_nearby, lat, lon, remember)


@mcp.tool()
def local_tips(destination: str, destination_geo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Etiquette and safety paragraphs about a destination from Wikivoyage (live data)."""
    return _run(registry.local_tips, destination, destination_geo)


@mcp.tool()
def cancel_booking(booking_id: str, idempotency_key: str, start_date: str, today: str,
                   total: int) -> dict[str, Any]:
    """MOCK cancellation of a MOCK booking. Nothing was charged or refunded."""
    return _run(registry.cancel_booking, booking_id, idempotency_key, start_date, today, total)


@mcp.tool()
def book_trip(idempotency_key: str, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """MOCK booking with an idempotency key. Nothing is purchased."""
    return _run(registry.book_trip, idempotency_key, summary)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
