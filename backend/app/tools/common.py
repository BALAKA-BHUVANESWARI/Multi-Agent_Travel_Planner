"""Helpers shared by the tools."""
from __future__ import annotations

import math
from datetime import date

from app.data.curated_destinations import CITIES, DESTINATIONS, SUPPORTED_DESTINATIONS
from app.services.pricing import price_estimator as dynamic
from app.tools.errors import ToolError


def clean_geo(geo) -> dict | None:
    """Validate a place record passed in by the caller (never trust shapes or ranges)."""
    if not isinstance(geo, dict):
        return None
    try:
        lat, lon = float(geo["lat"]), float(geo["lon"])
        name = " ".join(str(geo["name"]).split())[:80]
        cf = float(geo.get("cost_factor", 1.0))
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not name:
        return None
    pop = geo.get("population") or 0
    return {"slug": str(geo.get("slug", ""))[:60], "name": name, "lat": lat, "lon": lon,
            "cc": str(geo.get("cc") or "")[:2].upper(), "cost_factor": min(8.0, max(0.3, cf)),
            "population": int(pop) if isinstance(pop, (int, float)) else 0}


def destination_info(slug: str, geo=None) -> dict:
    """Curated destination profile, or a generated profile for any resolved place."""
    d = DESTINATIONS.get(slug)
    if d:
        return d
    g = clean_geo(geo)
    if g:
        return dynamic.profile(g)
    raise ToolError(f"unsupported destination '{slug}': resolve the place first (resolve_place) or pass "
                    f"destination_geo. Curated destinations: {', '.join(SUPPORTED_DESTINATIONS)}",
                    retryable=False)


def origin_point(origin: str, origin_geo=None) -> tuple[float, float, str, float]:
    """(lat, lon, country code, price level) of the departure place."""
    if origin in CITIES:
        _, lat, lon = CITIES[origin]
        return lat, lon, "IN", 1.0
    g = clean_geo(origin_geo)
    if g:
        return g["lat"], g["lon"], g["cc"], g["cost_factor"]
    raise ToolError(f"unknown origin '{origin}'", retryable=False)


def origin_name(origin: str, origin_geo=None) -> str:
    if origin in CITIES:
        return CITIES[origin][0]
    g = clean_geo(origin_geo)
    return g["name"] if g else origin


def country_of(slug: str, geo) -> str:
    if slug in DESTINATIONS:
        return "IN"
    g = clean_geo(geo)
    return g["cc"] if g else ""


def parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise ToolError(f"invalid date '{s}' (expected YYYY-MM-DD)", retryable=False)


def season_factor(d: dict, month: int, peak: float, low: float) -> float:
    if month in d["peak"]:
        return peak
    if month in d["low"]:
        return low
    return 1.0


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def safe_result(future, default, timeout=None):
    try:
        return future.result(timeout=timeout)
    except Exception:                                   # noqa: BLE001 - every free service may fail; plan anyway
        return default
