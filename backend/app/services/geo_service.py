"""Place resolution: any place name -> coordinates, country and a rough price level.

Order: curated destinations/origin cities -> offline gazetteer -> Open-Meteo geocoding (free, no key).
Nothing here is invented: a name that none of the three sources knows is rejected so the planner
asks the user instead of guessing.
"""
from __future__ import annotations

import difflib

from app.core import config
from app.data import gazetteer
from app.data.curated_destinations import ALIASES, CITIES, DESTINATIONS
from app.integrations import openmeteo
from app.observability import recorder as observe

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ATTRIBUTION = "Place lookup by Open-Meteo.com geocoding (GeoNames, CC BY 4.0)"
MIN_NAME_SIMILARITY = 0.72
TINY_PLACE = 5000          # fewer people than this (or no figure at all): worth checking a near-miss spelling

# Rough price level relative to India = 1.0 (hotels, food, entry fees). Estimates only.
COUNTRY_COST = {
    "IN": 1.0, "NP": 0.8, "LK": 1.0, "BD": 0.8, "BT": 1.4, "MV": 4.5, "PK": 0.8,
    "TH": 1.5, "VN": 1.1, "ID": 1.2, "MY": 1.4, "KH": 1.1, "LA": 1.0, "MM": 1.1, "PH": 1.4,
    "SG": 4.2, "HK": 3.5, "MO": 3.2, "CN": 1.9, "TW": 2.4, "JP": 3.0, "KR": 2.7,
    "AE": 3.2, "QA": 3.4, "OM": 2.6, "SA": 2.8, "JO": 2.2, "TR": 1.9, "EG": 1.3, "MA": 1.6,
    "ZA": 1.9, "KE": 2.0, "TZ": 2.0, "MU": 3.0,
    "GB": 4.5, "IE": 4.2, "FR": 4.2, "DE": 3.8, "NL": 4.2, "BE": 3.9, "AT": 3.9, "CH": 6.0, "IT": 3.8,
    "ES": 3.2, "PT": 2.9, "GR": 3.0, "HR": 3.0, "CZ": 2.6, "HU": 2.3, "PL": 2.2, "DK": 5.0, "SE": 4.4,
    "NO": 5.2, "IS": 5.5, "FI": 4.4,
    "US": 4.8, "CA": 3.8, "MX": 2.2, "BR": 2.2, "AR": 2.0, "PE": 1.8, "CL": 2.4, "CO": 1.8, "CU": 2.0,
    "AU": 4.2, "NZ": 4.0,
}
DEFAULT_COUNTRY_COST = 2.5


def distance_km(a: dict, b: dict) -> float:
    """Great-circle distance between two geo dicts."""
    import math
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


class PlaceError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def cost_factor(cc: str, population: int | None = 0) -> float:
    """Country price level adjusted for city size (big cities cost more, small towns less)."""
    base = COUNTRY_COST.get((cc or "").upper(), DEFAULT_COUNTRY_COST)
    pop = population or 0
    size = 1.15 if pop >= 5_000_000 else 1.07 if pop >= 1_000_000 else 1.0 if pop >= 200_000 else \
        0.92 if pop > 0 else 1.0
    return round(base * size, 2)


def _geo(slug, name, lat, lon, cc, country, population, cf, curated, source, admin1=None, tz=None) -> dict:
    return {"slug": slug, "name": name, "lat": round(float(lat), 4), "lon": round(float(lon), 4), "cc": cc,
            "country": country, "admin1": admin1, "population": population or 0, "timezone": tz,
            "cost_factor": cf, "curated": curated, "source": source}


def from_catalog(slug: str) -> dict | None:
    """Geo for a curated destination or one of the 14 origin cities."""
    if slug not in CITIES:
        return None
    name, lat, lon = CITIES[slug]
    d = DESTINATIONS.get(slug)
    return _geo(slug, name, lat, lon, "IN", "India", 0, d["cost_factor"] if d else 1.0, bool(d), "curated")


def _from_gazetteer(e: dict) -> dict:
    return _geo(e["slug"], e["name"], e["lat"], e["lon"], e["cc"], e["country"], e["population"],
                cost_factor(e["cc"], e["population"]), False, "gazetteer")


def _curated_slug(query: str) -> str | None:
    key = gazetteer.normalize(query)
    for slug, aliases in ALIASES.items():
        if key == slug or key in (gazetteer.normalize(a) for a in aliases):
            return slug
    return None


def _from_result(r: dict) -> dict:
    name = r["name"]
    cc = (r.get("country_code") or "").upper()
    slug = gazetteer.normalize(name).replace(" ", "-") + (f"-{cc.lower()}" if cc else "")
    return _geo(slug, name, r["latitude"], r["longitude"], cc, r.get("country") or cc, r.get("population"),
                cost_factor(cc, r.get("population")), False, "open-meteo-geocoding",
                admin1=r.get("admin1"), tz=r.get("timezone"))


def _is_region(r: dict) -> bool:
    fc = str(r.get("feature_code") or "")
    return fc.startswith("PCL") or fc.startswith("ADM")


def _one_slip(a: str, b: str) -> bool:
    """One letter added, left out or changed, or two neighbouring letters swapped."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        swapped = i + 1 < len(a) and a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:]
        return swapped or a[i + 1:] == b[i + 1:]
    short, long = sorted((a, b), key=len)
    return short[i:] == long[i + 1:]


def _known_names():
    for slug, aliases in ALIASES.items():
        for name in (slug, *aliases):
            yield gazetteer.normalize(name), slug
    for name, entry in gazetteer.scan_names():
        yield name, entry["slug"]


def meant_instead(query: str, geo: dict) -> dict | None:
    """The well-known place that was probably meant, when a typed or spoken name only matched a tiny place online
    and is one slip away from it ("Gova" matches a hamlet in Italy; "Goa" was meant). None: no reason to ask."""
    if geo.get("source") != "open-meteo-geocoding" or (geo.get("population") or 0) >= TINY_PLACE:
        return None
    typed = gazetteer.normalize(query)
    found: dict[str, dict] = {}
    for name, slug in _known_names():
        if len(name) < 4 and name != slug:        # three-letter aliases are airport codes ("blr" is not "Bir")
            continue
        if len(name) >= 3 and _one_slip(typed, name):
            entry = gazetteer.lookup(slug)
            known = from_catalog(slug) if _curated_slug(slug) else _from_gazetteer(entry) if entry else None
            if known:
                found[known["slug"]] = known
    if not found:
        return None
    return max(found.values(), key=lambda g: (g["curated"], g["population"]))


def full_label(geo: dict) -> str:
    """'Gova, Emilia-Romagna, Italy'."""
    return ", ".join(dict.fromkeys(p for p in (geo.get("name"), geo.get("admin1"), geo.get("country")) if p))


_CACHE: dict[str, dict] = {}


def _live(query: str, fetch) -> dict:
    key = gazetteer.normalize(query)
    if key in _CACHE:
        observe.event("retrieval", "open-meteo.place_lookup", memory_cache_hits=1, results=1)
        return _CACHE[key]
    try:
        with observe.span("retrieval", "open-meteo.place_lookup") as step:
            data = fetch(GEOCODE_URL, {"name": query, "count": 8, "language": "en", "format": "json"})
            found = len((data or {}).get("results") or [])
            step.set(results=found)
            if not found:
                step.status = "empty"
    except Exception as e:                                           # network / parse failure
        raise PlaceError(f"I couldn't reach the place-lookup service to find '{query}' ({type(e).__name__}). "
                         "Please try again in a moment.", retryable=True)
    scored = []
    for r in (data or {}).get("results") or []:
        try:
            rn = gazetteer.normalize(r["name"])
            sim = difflib.SequenceMatcher(None, key, rn).ratio()
            if rn.startswith(key + " ") or key.startswith(rn + " "):      # "Himachal" ~ "Himachal Pradesh"
                sim = max(sim, 0.9)
            r["latitude"], r["longitude"]
        except (KeyError, TypeError):
            continue
        if sim >= MIN_NAME_SIMILARITY:
            scored.append((sim, r))
    if not scored:
        raise PlaceError(f"I couldn't find a place called '{query}'. Please give a city or town name "
                         "(for example: Shimla, Bangkok or Paris).")
    places = [(s, r) for s, r in scored if not _is_region(r)]
    if not places:
        raise PlaceError(f"'{query}' is a region or country. Please name a specific city or town in it "
                         "(for example the main city you want to stay in).")
    places.sort(key=lambda sr: (-round(sr[0], 1), -(sr[1].get("population") or 0)))
    geo = _from_result(places[0][1])
    _CACHE[key] = geo
    return geo


def resolve(query: str, fetch=None, live: bool | None = None) -> dict:
    """Return a geo dict for ``query`` or raise PlaceError."""
    q = " ".join(str(query or "").split())
    if not q or len(q) > 80:
        raise PlaceError("Please give a city or town name.")
    slug = _curated_slug(q)
    if slug:
        observe.event("retrieval", "built_in_place_list", results=1)
        return from_catalog(slug)
    entry = gazetteer.lookup(q)
    if entry:
        observe.event("retrieval", "built_in_place_list", results=1)
        return _from_gazetteer(entry)
    if not (config.real_data_enabled() if live is None else live):
        raise PlaceError(f"I don't have '{q}' in my offline list and live place lookup is switched off.")
    return _live(q, fetch or openmeteo.fetch_json)
