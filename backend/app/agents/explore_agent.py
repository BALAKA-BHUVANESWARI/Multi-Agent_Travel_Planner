"""Explore agent: for any place the traveller names, show the place and its top sights, with pictures.

It runs outside the trip graph (there is no trip yet): look the place up, ask the sights agent's tool for places
to see, rank them, then find a picture for each. A step that fails leaves a note; the rest is still shown.
"""
from __future__ import annotations

from app.services import sights_guide
from app.tools.client import call_with_retry
from app.tools.errors import ToolError

NO_SIGHTS = ("I couldn't load named sights for this place right now. The free map and travel sources may be busy "
             "or have little about it: try again in a minute.")
NO_PHOTOS = "Photos couldn't be checked just now, so drawings are shown instead."
SOME_PHOTOS = ("A drawing is shown where I couldn't confirm that a photo really is of that place.")


def explore_place(name: str, deps) -> dict:
    """Raises ToolError when the name is not a place that can be looked up."""
    log, notes, attribution = [], [], []
    res = call_with_retry(deps.tools, "resolve_place", sleep=deps.sleep, query=name)
    geo = res["geo"]
    attribution += res.get("attribution") or []
    country = geo.get("country") or ""
    log.append({"agent": "Place agent", "text": f"Found {geo['name']}" + (f", {country}" if country else "")})

    sights = []
    try:
        places = call_with_retry(deps.tools, "search_places", retries=2, sleep=deps.sleep,
                                 destination=geo["slug"], preferences=[], destination_geo=geo)
        candidates = places.get("candidates") or []
        by_id = {c["id"]: c for c in candidates}
        for s in sights_guide.top_sights(candidates):
            c = by_id[s["id"]]
            sights.append({**{k: s[k] for k in ("id", "rank", "name", "label", "best_time", "season", "desc")},
                           **{k: c[k] for k in ("lat", "lon") if k in c}})
        if sights:
            attribution += places.get("attribution") or []
    except ToolError:
        pass
    log.append({"agent": "Sights agent", "text": f"Picked {len(sights)} place(s) to see"})
    if not sights:
        notes.append(NO_SIGHTS)

    photos = {"place": None, "sights": {}, "checked": False}
    try:
        photos = call_with_retry(deps.tools, "find_place_photos", retries=2, sleep=deps.sleep,
                                 place={"name": geo["name"], "lat": geo["lat"], "lon": geo["lon"],
                                        "region": geo.get("admin1") or "", "country": country},
                                 sights=[{k: s[k] for k in ("id", "name", "lat", "lon") if k in s}
                                         for s in sights])
        attribution += photos.get("attribution") or []
    except ToolError:
        pass
    matched = len(photos["sights"]) + (1 if photos["place"] else 0)
    log.append({"agent": "Photo agent", "text": f"Confirmed {matched} photo(s)"})
    if not photos["checked"]:
        notes.append(NO_PHOTOS)
    elif matched < len(sights) + 1:
        notes.append(SOME_PHOTOS)

    return {"place": {"name": geo["name"], "region": geo.get("admin1") or "", "country": country,
                      "photo": photos["place"]},
            "sights": [{**{k: s[k] for k in ("rank", "name", "label", "best_time", "season", "desc")},
                        "photo": photos["sights"].get(s["id"])} for s in sights],
            "notes": notes + ([sights_guide.NOTE] if sights else []),
            "attribution": list(dict.fromkeys(attribution)), "log": log}
