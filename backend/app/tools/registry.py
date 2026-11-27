"""Every tool the agents may call. The same set is served over MCP (mcp_server.py)."""
from __future__ import annotations

from app.tools.accommodation_tools import search_hotels
from app.tools.booking_tools import book_trip, cancel_booking
from app.tools.destination_tools import recommend_destinations
from app.tools.explore_tools import find_place_photos
from app.tools.flight_tools import search_flights
from app.tools.maps_tools import find_help_nearby, resolve_place
from app.tools.places_tools import local_tips, search_dining, search_places
from app.tools.weather_tools import get_weather

TOOLS = {
    "resolve_place": resolve_place,
    "recommend_destinations": recommend_destinations,
    "cancel_booking": cancel_booking,
    "search_flights": search_flights,
    "search_hotels": search_hotels,
    "get_weather": get_weather,
    "search_places": search_places,
    "find_place_photos": find_place_photos,
    "search_dining": search_dining,
    "find_help_nearby": find_help_nearby,
    "local_tips": local_tips,
    "book_trip": book_trip,
}
