"""Tools: look up a place by name and find help (hospitals, pharmacies) nearby."""
from __future__ import annotations

from app.core import config
from app.integrations import openstreetmap as osm
from app.services import geo_service as geo_mod
from app.services.trip_toolkit import emergency
from app.tools.errors import ToolError


def resolve_place(query: str) -> dict:
    """Any place name -> coordinates, country and price level (curated -> offline list -> live geocoding)."""
    try:
        g = geo_mod.resolve(query)
    except geo_mod.PlaceError as e:
        # "no such place" is an answer; only a lookup service that could not be reached is a failed tool
        raise ToolError(str(e), retryable=e.retryable, not_possible=not e.retryable)
    attribution = [geo_mod.ATTRIBUTION] if g["source"] == "open-meteo-geocoding" else []
    return {"geo": g, "attribution": attribution}


def find_help_nearby(lat: float, lon: float, remember: bool = True) -> dict:
    """Hospitals, clinics, pharmacies and police near a point, from OpenStreetMap. Never raises for a map outage:
    ``ok`` is false and ``reason`` says why, so the emergency numbers are still shown. ``remember=False`` keeps no
    copy of the position or the result (used for the traveller's own location)."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ToolError("invalid coordinates", retryable=False)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ToolError("invalid coordinates", retryable=False)
    if not config.real_data_enabled():
        return {"ok": False, "reason": "Live map data is switched off (REAL_DATA=0).", "country_code": "",
                "places": emergency.build_places([], lat, lon), "attribution": []}
    found = osm.help_places(lat, lon, remember=remember)
    if found is None:
        return {"ok": False, "reason": "The free map service did not answer. Try again in a minute.",
                "country_code": "", "places": emergency.build_places([], lat, lon), "attribution": []}
    return {"ok": True, "reason": "", "country_code": found["cc"],
            "places": emergency.build_places(found["elements"], lat, lon), "attribution": [osm.ATTRIBUTION]}
