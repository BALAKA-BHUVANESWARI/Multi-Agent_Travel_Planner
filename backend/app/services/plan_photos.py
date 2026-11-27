"""Pictures for the day-by-day plan: for each sight in a saved plan, the article its photos can be taken from.

Only real, named sights are looked up. Flexible suggestions ("Dinner at a local restaurant") are not a particular
place, so they get no pictures. The article is accepted only when its location matches the sight (see
tools/explore_tools.py); the page then loads that article's photos in the visitor's browser.
"""
from __future__ import annotations

from app.tools.client import call_with_retry
from app.tools.errors import ToolError
from app.tools.explore_tools import MAX_ITEMS

MAX_SIGHTS = 60        # more than a 14-day plan can hold


def plan_sights(state: dict) -> list[dict]:
    """The real sights of the itinerary, once each, as {id, name, lat?, lon?}."""
    found: dict[str, dict] = {}
    for day in (state.get("itinerary") or {}).get("days") or []:
        for item in day.get("items") or []:
            pid = str(item.get("id") or "")
            if item.get("type") != "activity" or not pid or pid.startswith("gen") or pid in found:
                continue
            found[pid] = {"id": pid, "name": item.get("name", ""),
                          **{k: item[k] for k in ("lat", "lon") if k in item}}
    return list(found.values())[:MAX_SIGHTS]


def plan_photos(state: dict, deps) -> dict:
    """{"photos": {sight id: article title}, "checked": bool, "attribution": [...]}. ``checked`` is false when
    nothing could be confirmed because the lookup did not run (offline, or the free service did not answer)."""
    sights = plan_sights(state)
    geo = (state.get("constraints") or {}).get("destination_geo") or {}
    result = {"photos": {}, "checked": True, "attribution": []}
    if not sights or "lat" not in geo:
        return result
    place = {"name": geo["name"], "lat": geo["lat"], "lon": geo["lon"], "region": geo.get("admin1") or "",
             "country": geo.get("country") or ""}
    for start in range(0, len(sights), MAX_ITEMS):
        try:
            found = call_with_retry(deps.tools, "find_place_photos", retries=2, sleep=deps.sleep, place=place,
                                    sights=sights[start:start + MAX_ITEMS])
        except ToolError:
            result["checked"] = False
            continue
        result["photos"].update(found["sights"])
        result["checked"] = result["checked"] and found["checked"]
        result["attribution"] = list(dict.fromkeys(result["attribution"] + found["attribution"]))
    return result
