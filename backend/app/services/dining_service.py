"""Where to eat: top restaurants split into vegetarian and non-vegetarian, with when to go.

Sources (free, no key): Wikivoyage "Eat" listings (travellers' picks, often with hours and a note on the menu)
and OpenStreetMap restaurants (diet and cuisine tags, opening hours). Neither has star ratings, so places are
ranked by how prominent they are (editor-listed, Wikidata/Wikipedia entry, website, stated hours, a praise word in
the listing). That is a proxy, and the result says so. Restaurants are never priced and never enter the budget:
the food allowance already covers meals. All text from the web is untrusted and sanitised.
"""
from __future__ import annotations

import re

from app.core.security import sanitize_untrusted

MAX_PER_LIST = 6
MAX_OTHER = 4
FAR_KM = 7.0

_PURE_VEG = re.compile(r"\b(pure[- ]?veg(etarian)?s?|purely vegetarian|vegetarian[- ]only|only vegetarian|"
                       r"100\s?% ?veg(etarian)?|strictly vegetarian|jain food|vegan[- ]only|all[- ]vegan)\b", re.I)
_VEG_FRIENDLY = re.compile(r"\b(vegetarians?|vegans?|veggies?|veg options?|veg dishes|veg food)\b", re.I)
_MEAT = re.compile(r"\b(non[- ]?veg(etarian)?|seafood|fish|prawns?|shrimp|crab|lobster|chicken|mutton|lamb|goat|"
                   r"beef|pork|bacon|ham|steaks?|kebabs?|tandoori|barbecue|bbq|grill(ed)?|meat|sausages?|"
                   r"burgers?|ribs|duck|turkey|oysters?|sushi|sashimi|ramen|butcher)\b", re.I)
_PRAISE = re.compile(r"\b(famous|famed|best|popular|legendary|iconic|institution|must[- ]try|well[- ]known|"
                     r"renowned|favou?rite|local favou?rite|acclaimed|traditional|authentic)\b", re.I)
_MEAT_CUISINES = {"steak_house", "seafood", "barbecue", "kebab", "chicken", "burger", "grill", "fish", "bbq",
                  "sushi", "ramen", "fish_and_chips", "meat"}
_VEG_CUISINES = {"vegetarian", "vegan", "jain", "udupi"}

# stated hours kept short; typical meal windows only when the listing gives none
_TYPICAL = {
    "restaurant": "Typical hours: lunch 12:00-15:00, dinner 19:00-22:30 (not stated: check before you go)",
    "cafe": "Typical hours: 08:00-21:00 (not stated: check before you go)",
    "fast_food": "Typical hours: 11:00-23:00 (not stated: check before you go)",
}
_BEST = {
    "restaurant": "Lunch 12:30-14:00 or early dinner 19:00-20:00 avoids the queues",
    "cafe": "Mid-morning (9:00-11:00) or late afternoon (16:00-18:00)",
    "fast_food": "Off-peak: 15:00-18:00",
}


def classify(name: str, text: str = "", tags: dict | None = None) -> str:
    """'veg' (vegetarian only), 'both' (serves vegetarian and meat), 'nonveg' or 'unknown'."""
    tags = tags or {}
    veg = (tags.get("diet:vegetarian") or "").lower()
    vegan = (tags.get("diet:vegan") or "").lower()
    cuisines = {c.strip().lower() for c in re.split(r"[;,]", tags.get("cuisine") or "") if c.strip()}
    blob = f"{name} {text}"
    if veg == "only" or vegan == "only" or _PURE_VEG.search(blob):
        return "veg"
    if cuisines & _VEG_CUISINES and not cuisines & _MEAT_CUISINES:
        return "veg"
    meat = bool(_MEAT.search(blob)) or bool(cuisines & _MEAT_CUISINES)
    friendly = veg == "yes" or vegan == "yes" or bool(_VEG_FRIENDLY.search(blob))
    if friendly and meat:
        return "both"
    if friendly:
        return "both"                    # veg-friendly but says nothing about meat: safe for vegetarians
    if meat:
        return "nonveg"
    return "unknown"


def _score(tags: dict, from_wikivoyage: bool, text: str) -> float:
    s = 3.0 if from_wikivoyage else 0.0
    s += 4 if "wikidata" in tags else 0
    s += 2 if "wikipedia" in tags else 0
    s += 1 if ("website" in tags or "contact:website" in tags or tags.get("x_url")) else 0
    s += 1 if tags.get("opening_hours") or tags.get("x_hours") else 0
    s += 0.5 if tags.get("cuisine") else 0
    s += 0.5 if any(k.startswith("diet:") for k in tags) else 0
    s += 1 if _PRAISE.search(text) else 0
    return s


def _hours(tags: dict, amenity: str) -> tuple[str, bool]:
    raw = tags.get("x_hours") or tags.get("opening_hours") or ""
    raw = sanitize_untrusted(raw, 90)
    if raw:
        return raw, True
    return _TYPICAL.get(amenity, _TYPICAL["restaurant"]), False


def _far(center: dict | None, tags: dict, el: dict) -> bool:
    if not center:
        return False
    try:
        from app.services.geo_service import distance_km
        c = el.get("center") or el
        lat = float(tags.get("x_lat", c.get("lat")))
        lon = float(tags.get("x_lon", c.get("lon")))
        return distance_km(center, {"lat": lat, "lon": lon}) >= FAR_KM
    except (TypeError, ValueError, KeyError):
        return False


def build_dining(elements: list[dict], center: dict | None = None) -> dict:
    """OSM-shaped elements (OSM nodes/ways and Wikivoyage 'eat' entries) -> ranked veg / non-veg / other lists."""
    seen: set[str] = set()
    items: list[dict] = []
    for el in elements:
        tags = el.get("tags") or {}
        name = sanitize_untrusted(tags.get("name:en") or tags.get("name") or "", 70)
        if len(name) < 3 or name.lower() in seen or _far(center, tags, el):
            continue
        seen.add(name.lower())
        wv = el.get("type") == "wv"
        text = sanitize_untrusted(tags.get("description:en") or "", 200)
        amenity = tags.get("amenity") if tags.get("amenity") in _TYPICAL else "restaurant"
        hours, known = _hours(tags, amenity)
        serves = classify(name, text, tags)
        cuisine = sanitize_untrusted((tags.get("cuisine") or "").replace("_", " ").replace(";", ", "), 50)
        items.append({"name": name, "serves": serves, "cuisine": cuisine, "hours": hours, "hours_known": known,
                      "best_time": _BEST[amenity], "desc": text[:140],
                      "source": "wikivoyage" if wv else "osm", "kind": amenity,
                      "_score": _score(tags, wv, f"{name} {text}")})
    items.sort(key=lambda x: (-x["_score"], x["name"]))

    def top(pred, n):
        out = []
        for it in items:
            if pred(it) and len(out) < n:
                out.append({k: v for k, v in it.items() if k != "_score"})
        return out
    return {"veg": top(lambda i: i["serves"] in ("veg", "both"), MAX_PER_LIST),
            "nonveg": top(lambda i: i["serves"] in ("nonveg", "both"), MAX_PER_LIST),
            "other": top(lambda i: i["serves"] == "unknown", MAX_OTHER)}


NOTE = ("Ranked by how prominent each place is (traveller-listed on Wikivoyage, Wikidata/Wikipedia entry, website, "
        "stated hours), because free sources have no live star ratings. Hours are as listed; where none are "
        "listed a typical window is shown. Prices are not available, so meals are covered by the food allowance.")
