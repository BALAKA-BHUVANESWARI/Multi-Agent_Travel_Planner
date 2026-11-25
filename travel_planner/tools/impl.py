"""Tool implementations. Pure functions with JSON-friendly arguments and results.

The same functions are served in-process and through the MCP server.
Flights and hotels are SYNTHETIC ESTIMATES (no free real API exists); every result
carries ``estimated: True`` so the UI/README can label it.
"""
from __future__ import annotations

import hashlib
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .. import config
from ..rag import wikivoyage
from ..rag.store import KnowledgeBase
from ..utils import hash01, round_to, to_hhmm
from . import dining, dynamic, geo as geo_mod, openmeteo, osm, wikipedia
from .catalog import CITIES, DESTINATIONS, SUPPORTED_DESTINATIONS
from .errors import ToolError


def _clean_geo(geo) -> dict | None:
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


def _dest(slug: str, geo=None) -> dict:
    """Curated destination profile, or a generated profile for any resolved place."""
    d = DESTINATIONS.get(slug)
    if d:
        return d
    g = _clean_geo(geo)
    if g:
        return dynamic.profile(g)
    raise ToolError(f"unsupported destination '{slug}': resolve the place first (resolve_place) or pass "
                    f"destination_geo. Curated destinations: {', '.join(SUPPORTED_DESTINATIONS)}",
                    retryable=False)


def _origin_point(origin: str, origin_geo=None) -> tuple[float, float, str, float]:
    """(lat, lon, country code, price level) of the departure place."""
    if origin in CITIES:
        _, lat, lon = CITIES[origin]
        return lat, lon, "IN", 1.0
    g = _clean_geo(origin_geo)
    if g:
        return g["lat"], g["lon"], g["cc"], g["cost_factor"]
    raise ToolError(f"unknown origin '{origin}'", retryable=False)


def _country(slug: str, geo) -> str:
    if slug in DESTINATIONS:
        return "IN"
    g = _clean_geo(geo)
    return g["cc"] if g else ""


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise ToolError(f"invalid date '{s}' (expected YYYY-MM-DD)", retryable=False)


def _season(d: dict, month: int, peak: float, low: float) -> float:
    if month in d["peak"]:
        return peak
    if month in d["low"]:
        return low
    return 1.0


def _haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------------------------ flights
GROUND_KM = 300          # below this a flight makes no sense: price a train/bus journey instead
LONG_HAUL_KM = 9000      # beyond this the estimator offers one-stop itineraries only


def search_flights(origin: str, destination: str, depart_date: str, return_date: str, travelers: int,
                   origin_geo: dict | None = None, destination_geo: dict | None = None) -> dict:
    d = _dest(destination, destination_geo)
    olat, olon, o_cc, o_cf = _origin_point(origin, origin_geo)
    if origin == destination:
        raise ToolError("origin and destination are the same", retryable=False)
    dep, ret = _date(depart_date), _date(return_date)
    if ret <= dep:
        raise ToolError("return date must be after departure date", retryable=False)
    km = _haversine(olat, olon, d["lat"], d["lon"])
    if km < 15:
        raise ToolError("origin and destination are the same place", retryable=False)
    d_cc = _country(destination, destination_geo)
    international = bool(d_cc) and bool(o_cc) and d_cc != o_cc
    jitter = 1 + (hash01("flight", origin, destination, depart_date) - 0.5) * 0.10

    def opt(id_, label, dep_out, dep_back, price, stops, dur, mode):
        return {
            "id": id_, "label": label, "stops": stops, "duration_h": round(dur, 1), "mode": mode,
            "depart_out": to_hhmm(dep_out), "arrive_out": to_hhmm(dep_out + dur * 60),
            "depart_back": to_hhmm(dep_back), "arrive_back": to_hhmm(dep_back + dur * 60),
            "price_pp": round_to(price), "estimated": True,
        }

    if km < GROUND_KM:                                            # short hop: train / bus
        rate = 2.5 * (((o_cf + d["cost_factor"]) / 2) ** 0.7)       # INR per km one way, per person (comfortable seat)
        base = max(300.0, rate * km) * 2 * jitter
        dur = km / 55.0 + 0.5
        options = [
            opt("best", "Train/bus, comfortable seat, mid-morning out / late-afternoon back", 9 * 60,
                16 * 60 + 30, base, 0, dur, "ground"),
            opt("early_late", "Train/bus, early start out / evening back", 5 * 60 + 45, 19 * 60 + 45,
                base * 0.88, 0, dur, "ground"),
            opt("one_stop", "Cheapest bus or train (basic class)", 6 * 60 + 30, 15 * 60 + 30, base * 0.65, 1,
                dur * 1.15, "ground"),
        ]
        mode, basis = "ground", "round trip by train/bus, per person"
    else:
        if international:
            one_way = (3000 + 4.5 * km) * (0.75 + 0.25 * o_cf)
        else:
            one_way = max(2500.0, 1900 + 2.9 * km) * (0.6 + 0.4 * o_cf)
        base = one_way * 2 * 0.92 * _season(d, dep.month, 1.2, 0.9) * jitter
        nonstop_h = 1.0 + km / 700.0
        stop_h = nonstop_h * 1.4 + 1.5
        if km > LONG_HAUL_KM:
            options = [
                opt("best", "1 stop, comfortable timings, mid-morning out / late-afternoon back", 9 * 60,
                    16 * 60 + 30, base, 1, stop_h, "flight"),
                opt("early_late", "1 stop, early-morning out / evening back", 5 * 60 + 45, 19 * 60 + 45,
                    base * 0.88, 1, stop_h, "flight"),
                opt("one_stop", "1 stop, cheapest fare", 6 * 60 + 30, 15 * 60 + 30, base * 0.72, 1, stop_h * 1.1,
                    "flight"),
            ]
        else:
            options = [
                opt("best", "Nonstop, mid-morning out / late-afternoon back", 9 * 60, 16 * 60 + 30, base, 0,
                    nonstop_h, "flight"),
                opt("early_late", "Nonstop, early-morning out / evening back", 5 * 60 + 45, 19 * 60 + 45,
                    base * 0.88, 0, nonstop_h, "flight"),
                opt("one_stop", "1 stop, cheapest fare", 6 * 60 + 30, 15 * 60 + 30, base * 0.72, 1, stop_h,
                    "flight"),
            ]
        mode, basis = "flight", "round trip, per person"
    return {"source": "synthetic-estimator", "estimated": True, "origin": origin, "destination": destination,
            "depart_date": depart_date, "return_date": return_date, "travelers": travelers,
            "distance_km": round(km), "currency": "INR", "price_basis": basis, "mode": mode,
            "international": international, "options": options}


# ------------------------------------------------------------------- hotels
HOTEL_TIERS = [
    ("3star", "3-star hotel", 3400),
    ("2star", "2-star / budget hotel", 1900),
    ("budget", "Homestay / hostel private room", 1000),
]


def search_hotels(destination: str, checkin: str, nights: int, travelers: int,
                  destination_geo: dict | None = None) -> dict:
    d = _dest(destination, destination_geo)
    ci = _date(checkin)
    if nights < 1:
        raise ToolError("nights must be >= 1", retryable=False)
    season = _season(d, ci.month, 1.3, 0.75)
    rooms = max(1, math.ceil(travelers / 2))
    options = []
    for tier, label, base in HOTEL_TIERS:
        jitter = 1 + (hash01("hotel", destination, tier, checkin) - 0.5) * 0.10
        options.append({"id": tier, "tier": tier, "label": f"{label} ({d['hotel_area']})",
                        "price_night_per_room": round_to(base * d["cost_factor"] * season * jitter),
                        "estimated": True})
    return {"source": "synthetic-estimator", "estimated": True, "destination": destination, "checkin": checkin,
            "nights": nights, "rooms": rooms, "currency": "INR", "options": options}


# ------------------------------------------------------------------ weather
def _climate_estimate(slug: str, d: dict, start: date, days: int) -> list[dict]:
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        m = day.month - 1
        base = d["rain"][m]
        jitter = (hash01("wx", slug, day.isoformat()) - 0.5) * 30
        prob = int(max(0, min(100, round(base + jitter))))
        tj = (hash01("wxt", slug, day.isoformat()) - 0.5) * 3
        out.append({"date": day.isoformat(), "tmax": round(d["tmax"][m] + tj, 1),
                    "tmin": round(d["tmin"][m] + tj, 1), "precip_prob": prob,
                    "rainy": prob >= config.RAIN_THRESHOLD})
    return out


def get_weather(destination: str, start_date: str, days: int, today: str,
                destination_geo: dict | None = None) -> dict:
    d = _dest(destination, destination_geo)
    start, tdy = _date(start_date), _date(today)
    mode = openmeteo.choose_mode(start, days, tdy)
    tz = {"timezone": "auto"} if d.get("dynamic") else {}
    if config.real_data_enabled():
        try:
            rows = (openmeteo.forecast(d["lat"], d["lon"], start, days, **tz) if mode == "forecast"
                    else openmeteo.climate(d["lat"], d["lon"], start, days, **tz))
            return {"mode": mode, "source": "open-meteo " + ("forecast" if mode == "forecast"
                    else "historical climate (last 3 years)"), "estimated": mode == "climate",
                    "attribution": openmeteo.ATTRIBUTION, "days": rows}
        except Exception:                      # network / parse failure -> offline estimate
            pass
    note = ("Offline estimate from curated monthly climate averages" if not d.get("dynamic")
            else "Rough offline estimate from latitude and month (live weather was unreachable)")
    return {"mode": mode, "source": "offline climate estimate", "estimated": True, "offline_fallback": True,
            "attribution": note, "days": _climate_estimate(destination, d, start, days)}


# ------------------------------------------------------------------- places
ENOUGH_FAST_SIGHTS = 6        # Wikivoyage + Wikipedia sights that make waiting for OpenStreetMap optional
OSM_GRACE = 4.0               # seconds to wait for OpenStreetMap in that case


def _safe(future, default, timeout=None):
    try:
        return future.result(timeout=timeout)
    except Exception:                                   # noqa: BLE001 - every free service may fail; plan anyway
        return default


def _search_places_generated(destination: str, d: dict, geo: dict, prefs: list[str]) -> dict:
    """Any place that is not hand-curated: OpenStreetMap places + Wikivoyage tips + generic suggestions."""
    g = _clean_geo(geo)
    elements, chunks = [], []
    if config.real_data_enabled():
        radius = dynamic.search_radius_m(g["population"])
        pool = ThreadPoolExecutor(max_workers=4)               # four free services, asked at the same time
        f_osm = pool.submit(osm.place_elements, d["lat"], d["lon"], radius)
        f_wp = pool.submit(wikipedia.nearby_sights, d["lat"], d["lon"], radius)
        f_wv = pool.submit(lambda: wikivoyage.add_coordinates(wikivoyage.listings(d["wikivoyage"]), d))
        f_tips = pool.submit(wikivoyage.load_chunks, d["wikivoyage"])
        wp_elements, wv_elements, chunks = _safe(f_wp, []), _safe(f_wv, []), _safe(f_tips, [])
        # Overpass is the slow, often overloaded one. If the fast sources already found enough, give it only a
        # short grace period; it keeps running in the background and fills the cache for next time.
        enough = len(wp_elements) + len(wv_elements) >= ENOUGH_FAST_SIGHTS
        osm_elements = _safe(f_osm, [], timeout=OSM_GRACE if enough else None)
        pool.shutdown(wait=False)
        elements = osm_elements + wv_elements + wp_elements       # first source wins when names repeat
    candidates, nearby, quality = dynamic.build_candidates(g, elements)
    attributions = []
    if quality == "osm":
        types = {e.get("type") for e in elements}
        if types - {"wp", "wv"}:
            attributions.append(osm.ATTRIBUTION)
        if "wp" in types:
            attributions.append(wikipedia.ATTRIBUTION)
    kb = KnowledgeBase()
    for c in chunks:
        kb.add(c, source="wikivoyage")
    if chunks or any(e.get("type") == "wv" for e in elements):
        attributions.append(wikivoyage.ATTRIBUTION)
    query = " ".join(prefs) or "popular sights food culture"
    ranked = [t for t in (kb.query(query, k=len(kb.docs)) if kb.docs else []) if t["source"] == "wikivoyage"]
    tips = [{"text": t["text"], "source": "wikivoyage"} for t in (ranked or [{"text": c} for c in chunks])][:3]
    return {"source": "osm+wikivoyage" if quality == "osm" else "generic", "estimated": True,
            "destination": destination, "currency": "INR", "candidates": candidates, "tips": tips,
            "nearby": nearby, "data_quality": quality,
            "attribution": attributions or ["Generic suggestions (no detailed place data was available)"]}


def search_places(destination: str, preferences: list | None = None, destination_geo: dict | None = None) -> dict:
    d = _dest(destination, destination_geo)
    prefs = [p for p in (preferences or []) if isinstance(p, str)]
    if d.get("dynamic"):
        return _search_places_generated(destination, d, destination_geo, prefs)
    kb = KnowledgeBase()
    for p in d["places"]:
        kb.add(f"{p['name']}: {p['desc']}", source="curated")
    attributions = ["Curated list (hand-entered estimates)"]
    nearby: list[dict] = []
    if config.real_data_enabled():
        chunks = wikivoyage.load_chunks(d["wikivoyage"])
        for c in chunks:
            kb.add(c, source="wikivoyage")
        if chunks:
            attributions.append(wikivoyage.ATTRIBUTION)
        nearby = osm.nearby(d["lat"], d["lon"])
        if nearby:
            attributions.append(osm.ATTRIBUTION)
    curated_names = {p["name"].lower() for p in d["places"]}
    nearby = [n for n in nearby if n["name"].lower() not in curated_names]
    query = " ".join(prefs) or "popular sights food culture"
    hits = kb.query(query, k=3)
    wiki = [t for t in kb.query(query, k=len(kb.docs)) if t["source"] == "wikivoyage"][:3]
    # Prefer real travel text; the curated one-liners only repeat the place list, so use them as an offline fallback.
    tips = [{"text": t["text"], "source": t["source"]} for t in (wiki or hits)]
    return {"source": "curated+rag", "estimated": True, "destination": destination, "currency": "INR",
            "candidates": [dict(p) for p in d["places"]], "tips": tips, "nearby": nearby,
            "attribution": attributions, "data_quality": "curated"}


# ------------------------------------------------------------------ dining
DINING_GRACE = 25.0          # seconds to wait for the (often slow) OSM restaurant lookup


def search_dining(destination: str, destination_geo: dict | None = None) -> dict:
    """Top restaurants split into vegetarian and non-vegetarian, with hours and when to go. Needs live data
    (Wikivoyage and OpenStreetMap); offline it returns empty lists and says why."""
    d = _dest(destination, destination_geo)
    g = _clean_geo(destination_geo) or {"population": 0}
    empty = {"veg": [], "nonveg": [], "other": [], "estimated": True, "note": dining.NOTE,
             "attribution": [], "data_quality": "none"}
    if not config.real_data_enabled():
        return {**empty, "note": "Restaurant suggestions need live data (set REAL_DATA=1); none were loaded."}
    radius = 1500 if (g.get("population") or 0) >= 500_000 else 3500
    pool = ThreadPoolExecutor(max_workers=2)
    f_wv = pool.submit(wikivoyage.eat_listings, d["wikivoyage"])
    f_osm = pool.submit(osm.restaurant_elements, d["lat"], d["lon"], radius)
    wv, osm_els = _safe(f_wv, []), _safe(f_osm, [], timeout=DINING_GRACE)
    pool.shutdown(wait=False)
    result = dining.build_dining(wv + osm_els, {"lat": d["lat"], "lon": d["lon"]})
    if not (result["veg"] or result["nonveg"] or result["other"]):
        return {**empty, "note": "No restaurant data could be loaded for this place right now; try again later."}
    attribution = ([wikivoyage.ATTRIBUTION] if wv else []) + ([osm.ATTRIBUTION] if osm_els else [])
    return {**result, "estimated": True, "note": dining.NOTE, "attribution": attribution,
            "data_quality": "+".join(x for x, ok in (("wikivoyage", bool(wv)), ("osm", bool(osm_els))) if ok)}


# ------------------------------------------------------------ place lookup
def resolve_place(query: str) -> dict:
    """Any place name -> coordinates, country and price level (curated -> offline list -> live geocoding)."""
    try:
        g = geo_mod.resolve(query)
    except geo_mod.PlaceError as e:
        raise ToolError(str(e), retryable=e.retryable)
    attribution = [geo_mod.ATTRIBUTION] if g["source"] == "open-meteo-geocoding" else []
    return {"geo": g, "attribution": attribution}


# ------------------------------------------------------------------ booking
def book_trip(idempotency_key: str, summary: dict | None = None) -> dict:
    """MOCK booking. Nothing is purchased. Deterministic for a given key."""
    if not idempotency_key:
        raise ToolError("idempotency_key required", retryable=False)
    bid = "MOCK-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:8].upper()
    return {"booking_id": bid, "idempotency_key": idempotency_key,
            "status": "confirmed (MOCK - nothing was actually booked or charged)",
            "summary": summary or {}}


TOOLS = {
    "resolve_place": resolve_place,
    "search_flights": search_flights,
    "search_hotels": search_hotels,
    "get_weather": get_weather,
    "search_places": search_places,
    "search_dining": search_dining,
    "book_trip": book_trip,
}
