"""Support for destinations that are not hand-curated (any place the user names).

* ``profile``: a destination profile with the same shape as the curated catalog entries, with a rough
  latitude-based climate used only when live weather is unreachable.
* ``build_candidates``: turn OpenStreetMap elements into the same place records the curated list uses.
  Names come from OSM (untrusted text: sanitised). OSM has no prices, so entry costs are ESTIMATES from
  the kind of place and the country's price level, and the plan labels everything as estimated.
* Generic suggestions (walking tour, market, dinner...) guarantee a usable plan when OSM is unreachable;
  they never carry a place name that could be invented.
"""
from __future__ import annotations

import math
import re

from ..guardrails import sanitize_untrusted
from ..rag.wikivoyage import FAR_KM
from ..utils import round_to
from .geo import distance_km

MAX_CANDIDATES = 30
# kind -> (tags, outdoor, base cost INR pp (India price level), hours, slot, label)
KINDS = {
    "museum": (["culture", "history"], False, 300, 2, "any", "Museum"),
    "gallery": (["culture"], False, 250, 1.5, "afternoon", "Gallery"),
    "fort": (["history", "culture"], True, 400, 2.5, "morning", "Fort, castle or palace"),
    "monument": (["history", "culture"], True, 100, 1.5, "morning", "Historic site"),
    "worship": (["spiritual", "culture"], False, 0, 1, "morning", "Place of worship"),
    "viewpoint": (["nature", "relaxation"], True, 0, 1, "evening", "Viewpoint"),
    "park": (["nature", "relaxation", "family"], True, 0, 1.5, "any", "Park or garden"),
    "reserve": (["nature", "adventure"], True, 150, 3, "morning", "Nature reserve"),
    "beach": (["beach", "nature", "relaxation"], True, 0, 2.5, "any", "Beach"),
    "peak": (["nature", "adventure"], True, 0, 3, "morning", "Peak or hill"),
    "waterfall": (["nature", "adventure"], True, 0, 2, "morning", "Waterfall"),
    "spring": (["relaxation", "nature"], True, 200, 2, "any", "Hot spring"),
    "cave": (["adventure", "nature"], True, 150, 1.5, "morning", "Cave"),
    "zoo": (["family", "nature"], True, 600, 3, "morning", "Zoo"),
    "aquarium": (["family"], False, 900, 2, "afternoon", "Aquarium"),
    "theme_park": (["family", "adventure"], True, 1800, 4, "morning", "Theme park"),
    "adventure": (["adventure", "nature"], True, 1200, 3, "morning", "Adventure activity"),
    "market": (["shopping", "food", "culture"], True, 0, 2, "afternoon", "Market"),
    "attraction": (["culture"], True, 100, 1.5, "any", "Attraction"),
}
KIND_CAP = {"worship": 4, "park": 3, "viewpoint": 3, "monument": 4, "peak": 2, "waterfall": 2, "market": 2,
            "attraction": 8, "museum": 5, "beach": 3, "gallery": 2, "adventure": 4}
_GENERIC_NAME = re.compile(r"^(park|garden|temple|church|mosque|monument|statue|memorial|fountain|viewpoint|"
                           r"view point|lookout|square|beach|market|museum)$", re.I)

# (id, name, tags, outdoor, base cost, hours, slot, desc)
GENERIC = [
    ("gen-walk", "Old town and city-centre walking tour", ["culture", "history"], True, 0, 2.5, "morning",
     "Wander the historic centre on foot; ask your hotel for the best route."),
    ("gen-market", "Local market and street-food stroll", ["food", "shopping", "culture"], True, 0, 2,
     "afternoon", "Browse a local market and try regional street food (food is covered by the food allowance)."),
    ("gen-dinner", "Dinner at a well-reviewed local restaurant", ["food"], False, 700, 1.5, "evening",
     "Try the regional specialities; check recent reviews or ask your hotel."),
    ("gen-sunset", "Sunset at a park, waterfront or viewpoint", ["nature", "relaxation"], True, 0, 1.5,
     "evening", "A free, relaxed way to end the day."),
    ("gen-cafe", "Cafe time and relaxed downtime", ["relaxation", "food"], False, 300, 1.5, "afternoon",
     "Slow down with a local coffee or tea."),
    ("gen-museum", "Visit the main local museum", ["culture", "history"], False, 300, 2, "afternoon",
     "Check opening days before you go."),
]


def latitude_climate(lat: float) -> tuple[list[int], list[float], list[float]]:
    """(rain %, tmax, tmin) per month from latitude alone. A rough offline stand-in, never preferred
    over live weather."""
    a = abs(lat)
    mean = 28.0 - 0.0075 * a * a
    amp = min(14.0, 0.26 * a)
    north = lat >= 0
    rain, tmax, tmin = [], [], []
    for m in range(1, 13):
        t = mean + amp * math.cos(2 * math.pi * (m - (7 if north else 1)) / 12.0)
        spread = 5.5 if a > 20 else 4.5
        tmax.append(round(t + spread, 1))
        tmin.append(round(t - spread, 1))
        if a < 23:
            wet = (m in (6, 7, 8, 9)) if north else (m in (12, 1, 2, 3))
            rain.append(45 if wet else 18)
        else:
            rain.append(30)
    return rain, tmax, tmin


def profile(geo: dict) -> dict:
    """Destination profile shaped like a catalog entry (name, coordinates, price level, climate)."""
    rain, tmax, tmin = latitude_climate(geo["lat"])
    n = geo["name"]
    return {"name": n, "lat": geo["lat"], "lon": geo["lon"], "cost_factor": geo["cost_factor"],
            "airport": f"{n} (nearest airport or station)", "hotel_area": f"central {n}",
            "peak": [], "low": [], "rain": rain, "tmax": tmax, "tmin": tmin, "wikivoyage": n,
            "places": [], "dynamic": True}


def search_radius_m(population: int | None) -> int:
    pop = population or 0
    return 6000 if pop >= 2_000_000 else 8000 if pop >= 500_000 else 10000 if pop >= 100_000 else 14000


def _classify(tags: dict) -> str | None:
    t, h, a, leisure, nat = (tags.get(k) for k in ("tourism", "historic", "amenity", "leisure", "natural"))
    if t == "museum":
        return "museum"
    if t in ("gallery", "zoo", "aquarium", "theme_park", "viewpoint", "adventure"):
        return t
    if h in ("castle", "fort", "palace", "manor"):
        return "fort"
    if h in ("temple", "church") or a == "place_of_worship":
        return "worship"
    if h in ("monument", "memorial", "ruins", "archaeological_site", "city_gate"):
        return "monument"
    if a == "marketplace":
        return "market"
    if leisure in ("park", "garden"):
        return "park"
    if leisure == "nature_reserve":
        return "reserve"
    if nat in ("beach", "peak", "waterfall", "cave_entrance", "hot_spring"):
        return {"cave_entrance": "cave", "hot_spring": "spring"}.get(nat, nat)
    if t == "attraction":
        return "attraction"
    return None


def _score(tags: dict) -> float:
    s = 0.0
    s += 4 if "wikidata" in tags else 0
    s += 2 if "wikipedia" in tags else 0
    s += 2 if tags.get("heritage") or tags.get("ref:whc") else 0
    s += 1 if tags.get("tourism") == "attraction" else 0
    s += 1 if ("website" in tags or "contact:website" in tags) else 0
    s += 1 if "name:en" in tags else 0
    s += 0.5 if "opening_hours" in tags else 0
    s -= 2.5 if tags.get("x_far") else 0                              # a day trip: only if nothing closer fits
    try:
        s += min(3.0, max(0.0, float(tags.get("x_notable", 0))))      # notability from Wikipedia/Wikivoyage
    except (TypeError, ValueError):
        pass
    return s


def _cost(base: int, factor: float, tags: dict) -> int:
    fee = str(tags.get("fee", "")).lower()
    if fee == "no":
        return 0
    if fee == "yes" and base == 0:
        base = 150
    return int(round_to(base * (factor ** 0.8), 10)) if base else 0


def _record(pid: str, name: str, kind: str, factor: float, city: str, osm_tags: dict) -> dict:
    t, outdoor, base, hours, slot, label = KINDS[kind]
    desc = sanitize_untrusted(osm_tags.get("description:en") or osm_tags.get("description") or "", 140)
    rec = {"id": pid, "name": name, "tags": list(t), "outdoor": outdoor, "cost": _cost(base, factor, osm_tags),
           "hours": hours, "slot": slot, "desc": desc or f"{label} in {city}.", "kind": kind,
           "fame": round(_score(osm_tags), 1)}
    if osm_tags.get("x_far"):                              # several km out of town: a day trip, ranked lower
        rec["far"] = True
        rec["desc"] = ("Day trip from town. " + rec["desc"])[:160]
    return rec


def generic_candidates(factor: float, have_museum: bool) -> list[dict]:
    out = []
    for pid, name, tags, outdoor, base, hours, slot, desc in GENERIC:
        if pid == "gen-museum" and have_museum:
            continue
        out.append({"id": pid, "name": name, "tags": list(tags), "outdoor": outdoor,
                    "cost": int(round_to(base * (factor ** 0.8), 10)) if base else 0, "hours": hours,
                    "slot": slot, "desc": desc})
    return out


def _is_far(geo: dict, el: dict, tags: dict) -> bool:
    """True when a sight with known coordinates is a day trip from the town centre. Wikivoyage and Wikipedia put
    them in the tags (x_lat/x_lon), OpenStreetMap on the element (lat/lon, or center for ways)."""
    try:
        c = el.get("center") or el
        lat = float(tags.get("x_lat", c.get("lat")))
        lon = float(tags.get("x_lon", c.get("lon")))
        limit = FAR_KM if (geo.get("population") or 0) < 100_000 else 14.0      # a big city's own sights spread out
        return distance_km(geo, {"lat": lat, "lon": lon}) >= limit
    except (TypeError, ValueError, KeyError):
        return False


def build_candidates(geo: dict, elements: list[dict]) -> tuple[list[dict], list[dict], str]:
    """Return (candidates, nearby, quality) where quality is 'osm' (named sights found, from OpenStreetMap and/or Wikipedia) or 'generic'."""
    factor, city = geo["cost_factor"], geo["name"]
    found: list[tuple[float, str, str, str, dict, str]] = []
    seen: set[str] = set()
    for el in elements:
        tags = el.get("tags") or {}
        kind = _classify(tags)
        name = sanitize_untrusted(tags.get("name:en") or tags.get("name") or "", 80)
        if not kind or len(name) < 3 or _GENERIC_NAME.match(name) or name.lower() in seen or name.lower() == city.lower():
            continue
        seen.add(name.lower())
        if "x_far" not in tags and _is_far(geo, el, tags):    # measured, not guessed
            tags = {**tags, "x_far": "yes"}
        src = {"wp": "wikipedia", "wv": "wikivoyage"}.get(el.get("type"), "osm")
        prefix = {"wikipedia": "wp", "wikivoyage": "wv"}.get(src, "osm")
        pid = f"{prefix}-{el.get('id', len(found))}" if src != "osm" else \
            f"osm-{str(el.get('type', 'x'))[:1]}{el.get('id', len(found))}"
        found.append((_score(tags), name, kind, pid, tags, src))
    found.sort(key=lambda x: (-x[0], x[1]))
    chosen: list[dict] = []
    per_kind: dict[str, int] = {}
    rest: list[tuple] = []
    for score, name, kind, pid, tags, src in found:
        if len(chosen) < MAX_CANDIDATES and per_kind.get(kind, 0) < KIND_CAP.get(kind, 3):
            per_kind[kind] = per_kind.get(kind, 0) + 1
            chosen.append(_record(pid, name, kind, factor, city, tags))
        else:
            rest.append((score, name, kind, src))
    have_museum = any(c["id"].startswith(("osm-", "wp-", "wv-")) and "culture" in c["tags"] and not c["outdoor"]
                      and c["slot"] in ("any", "afternoon") and c["cost"] > 0 for c in chosen)
    candidates = chosen + generic_candidates(factor, have_museum)
    nearby = [{"name": n, "kind": k, "source": src} for _, n, k, src in rest[:8]]
    quality = "osm" if len(chosen) >= 4 else "generic"
    return candidates, nearby, quality
