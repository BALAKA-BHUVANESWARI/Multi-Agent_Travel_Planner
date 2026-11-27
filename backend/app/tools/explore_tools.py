"""Tool: find the right Wikipedia article to take a place's photo from.

A name alone is not enough: "City Palace" or "Springfield" exist in many places, and the wrong article would show
the wrong picture. An article is accepted only when it has a picture and its own coordinates are close to the
place that was asked for. Anything unconfirmed gets no photo (the page then shows a drawing).
"""
from __future__ import annotations

import re

from app.core import config
from app.integrations import wikipedia
from app.services.geo_service import distance_km
from app.tools.errors import ToolError

PLACE_KM = 75.0        # the destination itself: islands and wide areas have a centre far from the main town
NEAR_TOWN_KM = 40.0    # a sight with no known position must at least be around the destination
SAME_SPOT_KM = 5.0     # a sight with a known position must match it
MAX_ITEMS = 12
_BAD_IN_TITLE = re.compile(r"[|#<>\[\]{}]")


def _clean(text) -> str:
    return " ".join(_BAD_IN_TITLE.sub(" ", str(text or "")).split())[:120]


def _position(thing) -> dict | None:
    try:
        lat, lon = float(thing["lat"]), float(thing["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"lat": lat, "lon": lon} if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _titles(name: str, extras: list[str]) -> list[str]:
    """Titles to try, most specific wording last: "City Palace", then "City Palace, Udaipur"."""
    out = [name]
    for extra in extras:
        if extra and extra.lower() not in name.lower():
            out.append(f"{name}, {extra}")
    return out


def _shorter(name: str) -> list[str]:
    """Plan names can say more than the article title: "Fort Aguada and lighthouse" -> "Fort Aguada". Only used
    for sights with a known position, where an article must be on that very spot to be accepted."""
    cut = re.split(r"\s+(?:and|with|&)\s+|\s+\(", name)[0].strip()
    cut = re.sub(r"\s+(?:walk|walking tour|tour|visit)$", "", cut, flags=re.I)
    return [cut] if cut != name and len(cut.split()) >= 2 else []


def find_place_photos(place: dict, sights: list | None = None) -> dict:
    """``place`` is {name, lat, lon, region?, country?}; each sight is {id, name, lat?, lon?}.
    Returns {"place": title or None, "sights": {id: title}, "checked": bool, "attribution": []}."""
    centre = _position(place)
    name = _clean((place or {}).get("name"))
    if not centre or not name:
        raise ToolError("invalid place", retryable=False)
    nothing = {"place": None, "sights": {}, "checked": False, "attribution": []}
    if not config.real_data_enabled():
        return nothing
    wanted = {"": (_titles(name, [_clean(place.get("region")), _clean(place.get("country"))]), centre, PLACE_KM)}
    for s in (sights or [])[:MAX_ITEMS]:
        if not isinstance(s, dict) or not _clean(s.get("name")) or not s.get("id"):
            continue
        spot = _position(s)
        label = _clean(s["name"])
        titles = _titles(label, [name]) + (_shorter(label) if spot else [])
        wanted[str(s["id"])] = (titles, spot or centre, SAME_SPOT_KM if spot else NEAR_TOWN_KM)
    # plain names first, so they are never the ones cut off if there are more titles than one query takes
    every = [t[0] for t, _, _ in wanted.values()] + [x for t, _, _ in wanted.values() for x in t[1:]]
    info = {}
    for start in range(0, len(every), wikipedia.PHOTO_BATCH):
        batch = wikipedia.article_info(every[start:start + wikipedia.PHOTO_BATCH])
        if batch is None:
            return nothing
        info.update(batch)
    found: dict[str, str] = {}
    for key, (titles, spot, limit) in wanted.items():
        for title in titles:
            page = info.get(title)
            if not page or not page["image"] or page["lat"] is None or page["lon"] is None:
                continue
            if key and page["title"].lower() == name.lower():    # a sight must not borrow the town's own picture
                continue
            if distance_km(spot, {"lat": page["lat"], "lon": page["lon"]}) <= limit:
                found[key] = page["title"]
                break
    return {"place": found.pop("", None), "sights": found, "checked": True,
            "attribution": [wikipedia.ATTRIBUTION] if found else []}
