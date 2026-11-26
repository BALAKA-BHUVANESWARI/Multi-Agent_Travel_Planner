"""OpenStreetMap (Overpass) lookup for *nearby suggestions*.

OSM has no prices, so these never enter the itinerary or budget; they are shown as
"also nearby" ideas only. Failure is silent (returns []).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Callable

from ..guardrails import sanitize_untrusted
from . import cache

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = [OVERPASS_URL, "https://overpass.kumi.systems/api/interpreter",
                    "https://overpass.private.coffee/api/interpreter"]
ATTRIBUTION = "Place data (c) OpenStreetMap contributors (ODbL)"
MIRROR_TIMEOUT = 8.0        # seconds per server
TOTAL_BUDGET = 16.0         # give up on Overpass after this long overall (it is a shared free service)
FAILURE_MEMORY = 120.0      # after a total failure, don't make the user wait again for this long


def _post(query: str, timeout: float = 8.0) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data, headers={"User-Agent": "travel-planner-demo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _post_with_mirrors(query: str, timeout: float = MIRROR_TIMEOUT, budget: float = TOTAL_BUDGET) -> dict:
    """Overpass is shared and often at capacity (502/504, or minutes of queueing): try each server briefly,
    in turn, and stop when the overall time budget is spent."""
    last: Exception = OSError("no Overpass server answered")
    deadline = time.monotonic() + budget
    for url in OVERPASS_MIRRORS:
        left = deadline - time.monotonic()
        if left <= 1:
            break
        try:
            data = urllib.parse.urlencode({"data": query}).encode()
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "travel-planner-demo/1.0"})
            with urllib.request.urlopen(req, timeout=min(timeout, left)) as r:      # noqa: S310
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                                           # noqa: BLE001 - try the next server
            last = e
    raise last


_PLACES_CACHE: dict[tuple, list] = {}
_FAILED: dict[tuple, float] = {}


def places_query(lat: float, lon: float, radius_m: int) -> str:
    """Tag filters first, then the radius: Overpass answers far faster that way than around-first."""
    a = f"(around:{radius_m},{lat},{lon})"
    return ("[out:json][timeout:12];("
            f'nwr["tourism"~"^(attraction|museum|gallery|viewpoint|zoo|aquarium|theme_park)$"]["name"]{a};'
            f'nwr["historic"~"^(castle|fort|palace|monument|memorial|ruins|archaeological_site|city_gate|'
            f'temple|church|manor)$"]["name"]{a};'
            f'nwr["amenity"~"^(place_of_worship|marketplace)$"]["name"]["wikidata"]{a};'
            f'nwr["leisure"~"^(park|garden|nature_reserve)$"]["name"]["wikidata"]{a};'
            f'nwr["natural"~"^(beach|peak|waterfall|hot_spring|cave_entrance)$"]["name"]{a};'
            ");out tags center 400;")


def place_elements(lat: float, lon: float, radius_m: int, post: Callable[[str], dict] | None = None) -> list[dict]:
    """Raw OSM elements (tags + centre) for notable places around a point.
    Cached in memory and on disk (30 days). Any failure returns [] so the caller can use other sources."""
    key = (round(lat, 2), round(lon, 2), radius_m)
    if key in _PLACES_CACHE:
        return _PLACES_CACHE[key]
    disk_key = f"osm:{key[0]},{key[1]},{radius_m}"
    cached = cache.get(disk_key)
    if cached:
        _PLACES_CACHE[key] = cached
        return cached
    if time.monotonic() - _FAILED.get(key, -1e9) < FAILURE_MEMORY:
        return []
    try:
        elements = (post or _post_with_mirrors)(places_query(lat, lon, radius_m)).get("elements", [])
    except Exception:
        _FAILED[key] = time.monotonic()
        return []
    if elements:
        _PLACES_CACHE[key] = elements
        cache.put(disk_key, elements)
    return elements


def nearby(lat: float, lon: float, radius_m: int = 8000, limit: int = 8,
           post: Callable[[str], dict] = _post) -> list[dict]:
    q = (f'[out:json][timeout:8];(node(around:{radius_m},{lat},{lon})["tourism"~"attraction|museum|viewpoint"]'
         f'["name"];way(around:{radius_m},{lat},{lon})["tourism"~"attraction|museum|viewpoint"]["name"];);'
         f"out center {limit * 3};")
    try:
        data = post(q)
    except Exception:
        return []
    seen, out = set(), []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = sanitize_untrusted(tags.get("name", ""), 80)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"name": name, "kind": tags.get("tourism", "attraction"), "source": "osm"})
        if len(out) >= limit:
            break
    return out


_RESTAURANTS_CACHE: dict[tuple, list] = {}


def restaurants_query(lat: float, lon: float, radius_m: int) -> str:
    """Restaurants worth listing: named, with at least one sign of prominence or a diet/cuisine tag."""
    a = f"(around:{radius_m},{lat},{lon})"
    base = 'nwr["amenity"~"^(restaurant|cafe)$"]["name"]'
    if radius_m <= 1500:                                       # dense city centre: the light, fast-to-scan filters only
        return ("[out:json][timeout:60];("
                f'{base}["wikidata"]{a};{base}["diet:vegetarian"]{a};{base}["diet:vegan"]{a};'
                ");out tags center 100;")
    return ("[out:json][timeout:25];("
            f'{base}["wikidata"]{a};{base}["diet:vegetarian"]{a};{base}["diet:vegan"]{a};'
            f'{base}["cuisine"]["website"]{a};{base}["cuisine"]["opening_hours"]{a};'
            ");out tags center 300;")


def restaurants_query_relaxed(lat: float, lon: float, radius_m: int) -> str:
    """Second try for small places: any named restaurant with a cuisine or a diet tag."""
    a = f"(around:{radius_m},{lat},{lon})"
    base = 'nwr["amenity"="restaurant"]["name"]'
    return ("[out:json][timeout:25];("
            f'{base}["cuisine"]{a};{base}["diet:vegetarian"]{a};{base}["diet:vegan"]{a};'
            ");out tags center 200;")


def restaurant_elements(lat: float, lon: float, radius_m: int, post: Callable[[str], dict] | None = None) -> list[dict]:
    """Raw OSM restaurant elements around a point. Cached in memory and on disk (30 days); [] on any failure."""
    key = (round(lat, 2), round(lon, 2), radius_m)
    if key in _RESTAURANTS_CACHE:
        return _RESTAURANTS_CACHE[key]
    disk_key = f"osm-restaurants:v1:{key[0]},{key[1]},{radius_m}"
    cached = cache.get(disk_key)
    if cached:
        _RESTAURANTS_CACHE[key] = cached
        return cached
    if time.monotonic() - _FAILED.get(("r",) + key, -1e9) < FAILURE_MEMORY:
        return []
    run = post or (lambda q: _post_with_mirrors(q, timeout=60.0, budget=60.0))   # slow but off the critical path
    try:
        elements = run(restaurants_query(lat, lon, radius_m)).get("elements", [])
        if len(elements) < 8:                                  # a small place: the strict filter finds too few
            more = run(restaurants_query_relaxed(lat, lon, radius_m)).get("elements", [])
            have = {(e.get("type"), e.get("id")) for e in elements}
            elements = elements + [e for e in more if (e.get("type"), e.get("id")) not in have]
    except Exception:
        _FAILED[("r",) + key] = time.monotonic()
        return []
    if elements:
        _RESTAURANTS_CACHE[key] = elements
        cache.put(disk_key, elements)
    return elements


live_restaurant_elements = restaurant_elements          # tests replace the name above; this stays the real one


# ---------------------------------------------------------------- emergency help
HELP_TTL = 7 * 24 * 3600                    # hospitals and pharmacies change more often than sights
_HELP_CACHE: dict[tuple, dict] = {}
WIDE_RADIUS = 20_000


def help_query(lat: float, lon: float, radius_m: int) -> str:
    """The country the point is in, then each kind of place with its own limit, so that a city with hundreds of
    pharmacies cannot crowd the hospitals out of the answer. Pharmacies and clinics use a smaller circle."""
    wide, near = f"(around:{radius_m},{lat},{lon})", f"(around:{radius_m // 2},{lat},{lon})"
    return ("[out:json][timeout:20];"
            f'is_in({lat},{lon})->.here;area.here["admin_level"="2"]["ISO3166-1:alpha2"];out tags;'
            f'nwr["amenity"="hospital"]["name"]{wide};out tags center 200;'
            f'nwr["amenity"="police"]["name"]{wide};out tags center 60;'
            f'nwr["amenity"="pharmacy"]["name"]{near};out tags center 200;'
            f'nwr["amenity"="clinic"]["name"]{near};out tags center 100;')


def _split_help(data: dict) -> tuple[list, str]:
    elements, cc = [], ""
    for el in data.get("elements", []):
        if el.get("type") == "area":
            code = str((el.get("tags") or {}).get("ISO3166-1:alpha2") or "").upper()
            cc = code if len(code) == 2 and code.isalpha() else cc
        else:
            elements.append(el)
    if not elements and data.get("remark"):                    # Overpass reports its own time-outs this way
        raise OSError("the map server could not finish the search")
    return elements, cc


def help_places(lat: float, lon: float, radius_m: int = 5000, remember: bool = True,
                post: Callable[[str], dict] | None = None) -> dict | None:
    """{"elements": [...], "cc": "IN"} around a point, or None when no map server answered.
    ``remember=False`` (the traveller's own position) keeps nothing in memory or on disk."""
    key = (round(lat, 3), round(lon, 3), radius_m)
    disk_key = f"osm-help:v1:{key[0]},{key[1]},{radius_m}"
    if remember:
        found = _HELP_CACHE.get(key) or cache.get(disk_key, ttl=HELP_TTL)
        if found:
            return found
    run = post or (lambda q: _post_with_mirrors(q, timeout=15.0, budget=25.0))
    try:
        elements, cc = _split_help(run(help_query(lat, lon, radius_m)))
    except Exception:                                          # noqa: BLE001 - the numbers still work offline
        return None
    kinds = [(e.get("tags") or {}).get("amenity") for e in elements]
    if radius_m < WIDE_RADIUS and (kinds.count("hospital") < 3 or "pharmacy" not in kinds):
        try:                                                   # a rural spot: look further out
            more, cc2 = _split_help(run(help_query(lat, lon, WIDE_RADIUS)))
            have = {(e.get("type"), e.get("id")) for e in elements}
            elements += [e for e in more if (e.get("type"), e.get("id")) not in have]
            cc = cc or cc2
        except Exception:                                      # noqa: BLE001 - keep what the first search found
            pass
    result = {"elements": elements, "cc": cc}
    if remember and elements:
        _HELP_CACHE[key] = result
        cache.put(disk_key, result)
    return result
