"""Tools: sights, restaurants and local travel tips."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.core import config
from app.data import gazetteer
from app.data.curated_destinations import coordinates
from app.integrations import openstreetmap as osm
from app.integrations import wikipedia, wikivoyage
from app.rag.vector_store import KnowledgeBase
from app.services import dining_service as dining
from app.services.pricing import price_estimator as dynamic
from app.tools.common import clean_geo, country_of, destination_info, safe_result

ENOUGH_FAST_SIGHTS = 6        # Wikivoyage + Wikipedia sights that make waiting for OpenStreetMap optional
OSM_GRACE = 4.0               # seconds to wait for OpenStreetMap in that case


def _search_places_generated(destination: str, d: dict, geo: dict, prefs: list[str]) -> dict:
    """Any place that is not hand-curated: OpenStreetMap places + Wikivoyage tips + generic suggestions."""
    g = clean_geo(geo)
    elements, chunks = [], []
    if config.real_data_enabled():
        radius = dynamic.search_radius_m(g["population"])
        pool = ThreadPoolExecutor(max_workers=4)               # four free services, asked at the same time
        f_osm = pool.submit(osm.place_elements, d["lat"], d["lon"], radius)
        f_wp = pool.submit(wikipedia.nearby_sights, d["lat"], d["lon"], radius)
        f_wv = pool.submit(lambda: wikivoyage.add_coordinates(wikivoyage.listings(d["wikivoyage"]), d))
        f_tips = pool.submit(wikivoyage.load_chunks, d["wikivoyage"])
        wp_elements, wv_elements, chunks = safe_result(f_wp, []), safe_result(f_wv, []), safe_result(f_tips, [])
        # Overpass is the slow, often overloaded one. If the fast sources already found enough, give it only a
        # short grace period; it keeps running in the background and fills the cache for next time.
        enough = len(wp_elements) + len(wv_elements) >= ENOUGH_FAST_SIGHTS
        osm_elements = safe_result(f_osm, [], timeout=OSM_GRACE if enough else None)
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
    d = destination_info(destination, destination_geo)
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
            "candidates": [{**p, **coordinates(p["id"])} for p in d["places"]], "tips": tips, "nearby": nearby,
            "attribution": attributions, "data_quality": "curated"}


DINING_GRACE = 25.0          # seconds to wait for the (often slow) OSM restaurant lookup


def search_dining(destination: str, destination_geo: dict | None = None) -> dict:
    """Top restaurants split into vegetarian and non-vegetarian, with hours and when to go. Needs live data
    (Wikivoyage and OpenStreetMap); offline it returns empty lists and says why."""
    d = destination_info(destination, destination_geo)
    g = clean_geo(destination_geo) or {"population": 0}
    empty = {"veg": [], "nonveg": [], "other": [], "estimated": True, "note": dining.NOTE,
             "attribution": [], "data_quality": "none"}
    if not config.real_data_enabled():
        return {**empty, "note": "Restaurant suggestions need live data (set REAL_DATA=1); none were loaded."}
    radius = 1500 if (g.get("population") or 0) >= 500_000 else 3500
    pool = ThreadPoolExecutor(max_workers=2)
    f_wv = pool.submit(wikivoyage.eat_listings, d["wikivoyage"])
    f_osm = pool.submit(osm.restaurant_elements, d["lat"], d["lon"], radius)
    wv, osm_els = safe_result(f_wv, []), safe_result(f_osm, [], timeout=DINING_GRACE)
    pool.shutdown(wait=False)
    result = dining.build_dining(wv + osm_els, {"lat": d["lat"], "lon": d["lon"]})
    if not (result["veg"] or result["nonveg"] or result["other"]):
        return {**empty, "note": "No restaurant data could be loaded for this place right now; try again later."}
    attribution = ([wikivoyage.ATTRIBUTION] if wv else []) + ([osm.ATTRIBUTION] if osm_els else [])
    return {**result, "estimated": True, "note": dining.NOTE, "attribution": attribution,
            "data_quality": "+".join(x for x, ok in (("wikivoyage", bool(wv)), ("osm", bool(osm_els))) if ok)}


def local_tips(destination: str, destination_geo: dict | None = None) -> dict:
    """Etiquette and safety text about the destination from Wikivoyage; empty when offline or none exists."""
    d = destination_info(destination, destination_geo)
    cc = country_of(destination, destination_geo)
    if not config.real_data_enabled():
        return {"sections": [], "attribution": []}
    given = destination_geo.get("country") if isinstance(destination_geo, dict) else ""
    country = gazetteer.COUNTRY_NAMES.get(cc) or " ".join(str(given or "").split())[:60]
    sections = wikivoyage.culture_sections(d["wikivoyage"], country)
    return {"sections": sections, "attribution": [wikivoyage.ATTRIBUTION] if sections else []}
