"""Nearby sights from Wikipedia's geosearch (free, no key, fast CDN-backed API).

Why: the free Overpass servers are often at capacity, so this is a reliable second source of named sights.
Each nearby article has a short Wikidata description ("Fort in Rajasthan", "Museum in Paris"); keywords in
it decide whether the article is a visitable sight and what kind. Schools, stations, villages, constituencies and
defunct places match nothing and are dropped. Results are returned in the same tag shape as OpenStreetMap
elements so one builder handles every source. Article length is a rough notability signal (stubs are ignored).
Geosearch returns the nearest pages first, so for a huge city it covers the centre best: that is what the
other sources are for. Text is untrusted and sanitised downstream.
"""
from __future__ import annotations

import re
from typing import Callable

from app.core import cache
from app.integrations import openmeteo
from app.observability import recorder as observe

API = "https://en.wikipedia.org/w/api.php"
ATTRIBUTION = "Nearby sights from Wikipedia (CC BY-SA 4.0)"
MIN_ARTICLE_CHARS = 2500            # shorter pages are stubs: rarely worth a slot in an itinerary
MAX_PAGES = 500                     # the API's limit for anonymous clients

# (pattern on lower-cased text, OSM-style tags). First match wins: order matters.
_KINDS: list[tuple[re.Pattern, dict]] = [(re.compile(p), t) for p, t in [
    (r"\bmuseums?\b", {"tourism": "museum"}),
    (r"\b(art )?galler(y|ies)\b", {"tourism": "gallery"}),
    (r"\b(zoo|zoological)\b", {"tourism": "zoo"}),
    (r"\baquarium\b", {"tourism": "aquarium"}),
    (r"\b(theme|amusement) park\b", {"tourism": "theme_park"}),
    (r"\b(rafting|kayaking|canoeing|bungee|paragliding|parasailing|zip[- ]?lin(e|ing)|trekking|trek|hiking|"
     r"canyoning|rappelling|mountaineering|rock climbing|climbing|skiing|snowboarding|surfing|scuba|snorkell?ing|"
     r"diving|camping|safari|jungle|white[- ]water)\b", {"tourism": "adventure"}),
    (r"\b(fort|fortress|castle|citadel)\b", {"historic": "fort"}),
    (r"\bpalace\b", {"historic": "palace"}),
    (r"\b(temple|shrine|gurudwara|gurdwara|mosque|church|cathedral|basilica|monastery|synagogue|pagoda|"
     r"stupa|mandir|dargah|chapel|abbey|priory|ashram|cloister)\b", {"historic": "temple"}),
    (r"\b(monument|memorial|tomb|mausoleum|ruins?|archaeological|heritage site|stepwell|baoli|observatory|"
     r"gate|lighthouse)\b", {"historic": "monument"}),
    (r"\bwaterfalls?\b|\bfalls\b", {"natural": "waterfall"}),
    (r"\bbeach\b", {"natural": "beach"}),
    (r"\b(peak|summit|viewpoint|lookout|view point)\b", {"natural": "peak"}),
    (r"\b(national park|wildlife sanctuary|nature reserve|bird sanctuary|sanctuary|tiger reserve)\b",
     {"leisure": "nature_reserve"}),
    (r"\b(park|gardens?|botanical)\b", {"leisure": "park"}),
    (r"\b(market|bazaar|souk)\b", {"amenity": "marketplace"}),
    (r"\b(lake|dam|reservoir|\w*bridge|caves?|hot springs?|tourist attraction|landmark|plaza|square|statue|"
     r"sculpture|fountain|art installation|tower|historic (district|centre|center|quarter|town)|old town|"
     r"old city|old quarter)\b", {"tourism": "attraction"}),
]]
_NOT_A_SIGHT = re.compile(r"\b(school|college|university|railway|station|airport|village|town|city|district|"
                          r"tehsil|municipality|neighbou?rhood|suburb|hospital|company|cricket|football|"
                          r"stadium|constituency|river|highway|road|high school|campus)\b")
_GONE = re.compile(r"\b(defunct|demolished|destroyed|former|dissolved|abolished|disused|closed)\b")


def classify_text(text: str) -> dict | None:
    """Sight kind for a name or a short phrase, by keyword; None when it names no kind of sight."""
    t = (text or "").lower()
    for pat, tags in _KINDS:
        if pat.search(t):
            return dict(tags)
    return None


def classify(description: str) -> dict | None:
    """Sight kind for a Wikidata description such as 'Museum in Paris'; None for anything else."""
    d = (description or "").lower()
    if _GONE.search(d):
        return None
    for pat, tags in _KINDS:
        if pat.search(d):
            head = d.split(" in ")[0]
            # "X in Y": the kind comes first; a description that names a settlement or school first is not a sight
            if _NOT_A_SIGHT.search(head) and not pat.search(head):
                return None
            return dict(tags)
    return None


def _tags(page: dict, tags: dict) -> dict:
    out = {**tags, "name": page["title"], "name:en": page["title"], "wikipedia": f"en:{page['title']}"}
    qid = (page.get("pageprops") or {}).get("wikibase_item")
    if qid:
        out["wikidata"] = qid
    length = int(page.get("length") or 0)
    out["x_notable"] = 3 if length >= 40000 else 2 if length >= 12000 else 1 if length >= 5000 else 0
    desc = (page.get("description") or "")
    if "heritage" in desc.lower() or "unesco" in desc.lower():
        out["heritage"] = "yes"
    out["description:en"] = desc[:140]
    co = (page.get("coordinates") or [None])[0]
    if co and "lat" in co and "lon" in co:                 # lets the place builder measure the distance from town
        out["x_lat"], out["x_lon"] = round(float(co["lat"]), 5), round(float(co["lon"]), 5)
    return out


@observe.retrieval("wikipedia.nearby_sights")
def nearby_sights(lat: float, lon: float, radius_m: int, fetch: Callable | None = None) -> list[dict]:
    """OSM-shaped elements for visitable sights near a point; [] on any failure."""
    key = f"wikipedia:v2:{lat:.2f},{lon:.2f},{radius_m}"   # v2: entries carry coordinates
    cached = cache.get(key)
    if cached is not None:
        return cached
    fetch = fetch or openmeteo.fetch_json
    try:
        data = fetch(API, {"action": "query", "generator": "geosearch", "ggscoord": f"{lat}|{lon}",
                           "ggsradius": min(int(radius_m), 10000), "ggslimit": MAX_PAGES,
                           "prop": "coordinates|description|info|pageprops", "ppprop": "wikibase_item", "colimit": "max",
                           "format": "json", "formatversion": 2}, 8.0)
        pages = data.get("query", {}).get("pages", [])
    except Exception as e:                                   # noqa: BLE001 - a free service may be down
        observe.problem(e)
        return []
    elements = []
    for p in pages:
        try:
            if int(p.get("length") or 0) < MIN_ARTICLE_CHARS:
                continue
            tags = classify(p.get("description", ""))
            if tags and p.get("title"):
                elements.append({"type": "wp", "id": p["pageid"], "tags": _tags(p, tags)})
        except (KeyError, TypeError, ValueError):
            continue
    if elements:
        cache.put(key, elements)
    return elements


PHOTO_BATCH = 50                    # the most titles one query accepts


@observe.retrieval("wikipedia.photo_articles")
def article_info(titles: list[str], fetch: Callable | None = None) -> dict | None:
    """What Wikipedia knows about each title: {asked title: {title, lat, lon, image}} for the articles that exist
    (``lat``/``lon`` are None when the article has no coordinates). None when Wikipedia could not be asked."""
    asked = sorted({t for t in titles if t})[:PHOTO_BATCH]
    if not asked:
        return {}
    key = "wikipedia-article-info:v1:" + "|".join(asked)
    cached = cache.get(key)
    if cached is not None:
        return cached
    fetch = fetch or openmeteo.fetch_json
    try:
        data = fetch(API, {"action": "query", "titles": "|".join(asked), "redirects": 1,
                           "prop": "coordinates|pageimages", "piprop": "name", "pilimit": PHOTO_BATCH,
                           "colimit": "max", "format": "json", "formatversion": 2}, 8.0)
        query = data["query"]
        pages = {p["title"]: p for p in query.get("pages", []) if not p.get("missing") and not p.get("invalid")}
        renamed = {r["from"]: r["to"] for r in query.get("normalized", [])}
        moved = {r["from"]: r["to"] for r in query.get("redirects", [])}
    except Exception as e:                                   # noqa: BLE001 - a free service may be down
        observe.problem(e)
        return None
    found = {}
    for title in asked:
        final = renamed.get(title, title)
        final = moved.get(final, final)
        page = pages.get(final)
        if page is None:
            continue
        co = (page.get("coordinates") or [{}])[0]
        found[title] = {"title": final, "lat": co.get("lat"), "lon": co.get("lon"),
                        "image": bool(page.get("pageimage"))}
    cache.put(key, found)
    return found
