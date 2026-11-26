"""Emergency Travel Assistant: emergency numbers (offline, instant) and nearby help from OpenStreetMap."""
from __future__ import annotations

import re
import urllib.parse

from ..guardrails import sanitize_untrusted
from ..tools.geo import distance_km
from . import emergency_numbers

CALL_FIRST = ("In an emergency, call first. The operator can send help and direct you to the nearest hospital. "
              "Do not rely on the list below to be complete or up to date.")
MAP_NOTE = ("Places come from OpenStreetMap, which volunteers maintain: details can be missing or out of date. "
            "Distances are straight lines. Phone before you travel there if you can.")
NO_NUMBERS = ("This app has no checked emergency numbers for this country. Ask your hotel, or check your "
              "government's travel advice. Many mobile networks connect 112 to emergency services, but do not "
              "count on it.")
KINDS = ("hospital", "clinic", "pharmacy", "police")
LIMITS = {"hospital": 6, "clinic": 4, "pharmacy": 6, "police": 3}
_PHONE = re.compile(r"^\+?[0-9][0-9 ()./-]{2,24}$")


def numbers_for(cc: str) -> dict:
    """The checked numbers for a country, or ``verified: False`` with no number at all."""
    cc = (cc or "").upper()
    entry = emergency_numbers.NUMBERS.get(cc)
    if not entry:
        return {"verified": False, "cc": cc, "message": NO_NUMBERS, "calls": []}
    calls = []
    if entry["any"]:
        calls.append({"label": "All emergencies", "number": entry["any"], "primary": True})
    services = [("Police", entry["police"]), ("Ambulance", entry["ambulance"]), ("Fire", entry["fire"])]
    grouped: dict[str, list[str]] = {}
    for label, number in services:
        if number:
            grouped.setdefault(number, []).append(label)
    for number, labels in grouped.items():
        calls.append({"label": " and ".join(labels), "number": number, "primary": not entry["any"]})
    calls += [{"label": label, "number": number, "primary": False} for label, number in entry["extra"]]
    return {"verified": True, "cc": cc, "calls": calls, "note": entry["note"],
            "sources": [{"title": t, "url": u} for t, u in entry["sources"]],
            "checked_on": emergency_numbers.CHECKED_ON}


def _phone(tags: dict) -> str:
    for key in ("emergency:phone", "phone", "contact:phone", "contact:mobile"):
        value = str(tags.get(key) or "").split(";")[0].strip()
        if _PHONE.match(value):
            return value
    return ""


def _address(tags: dict) -> str:
    parts = [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:suburb"), tags.get("addr:city"),
             tags.get("addr:postcode")]
    return sanitize_untrusted(", ".join(str(p) for p in parts if p) or str(tags.get("addr:full") or ""), 140)


def build_places(elements: list[dict], lat: float, lon: float) -> dict:
    """OSM elements -> nearest hospitals, clinics, pharmacies and police stations. Untrusted text is sanitised."""
    out: dict[str, list] = {k: [] for k in KINDS}
    seen: set[tuple] = set()
    for el in elements:
        tags = el.get("tags") or {}
        kind = tags.get("amenity")
        if kind not in out:
            continue
        centre = el.get("center") or el
        try:
            plat, plon = float(centre["lat"]), float(centre["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        name = sanitize_untrusted(str(tags.get("name:en") or tags.get("name") or ""), 90)
        if not name or (kind, name.lower()) in seen:
            continue
        seen.add((kind, name.lower()))
        km = distance_km({"lat": lat, "lon": lon}, {"lat": plat, "lon": plon})
        hours = sanitize_untrusted(str(tags.get("opening_hours") or ""), 80)
        out[kind].append({
            "name": name, "kind": kind, "distance_km": round(km, 1), "phone": _phone(tags),
            "address": _address(tags), "hours": hours, "open_24h": hours.strip() == "24/7",
            "emergency_dept": kind == "hospital" and tags.get("emergency") == "yes",
            "map_url": f"https://www.openstreetmap.org/?mlat={plat:.5f}&mlon={plon:.5f}#map=17/{plat:.5f}/{plon:.5f}",
        })
    for kind in out:
        out[kind] = sorted(out[kind], key=lambda p: p["distance_km"])[:LIMITS[kind]]
    return out


def search_links(near: str = "") -> list[dict]:
    """Map searches the traveller can open when the lookup fails. ``near`` is a place name, never coordinates."""
    suffix = f" near {near}" if near else " near me"
    return [{"title": f"Search maps for {what}{suffix}",
             "url": "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(what + suffix)}
            for what in ("hospital", "pharmacy")]
