"""Wikivoyage ingestion for the local knowledge base (text is CC BY-SA, attribution shown).

Fetched text is untrusted: every chunk is sanitised before it is stored or shown.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Callable

from ..guardrails import sanitize_untrusted

API = "https://en.wikivoyage.org/w/api.php"
ATTRIBUTION = "Travel text from Wikivoyage (CC BY-SA 4.0)"
_CACHE: dict[str, list[str]] = {}


def _fetch(title: str, timeout: float = 8.0) -> str:
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "titles": title,
                                "redirects": 1, "format": "json"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "travel-planner-demo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    pages = data.get("query", {}).get("pages", {})
    return next(iter(pages.values()), {}).get("extract", "") if pages else ""


def chunk(text: str, max_chars: int = 420, max_chunks: int = 40) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n(?==)", text):
        para = sanitize_untrusted(para, 2000)
        if len(para) < 60 or para.startswith("="):
            continue
        while len(para) > max_chars:
            cut = para.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > 80 else max_chars
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if len(para) >= 60:
            out.append(para)
        if len(out) >= max_chunks:
            break
    return out[:max_chunks]


def load_chunks(title: str, fetch: Callable[[str], str] = _fetch) -> list[str]:
    if title in _CACHE:
        return _CACHE[title]
    try:
        chunks = chunk(fetch(title))
    except Exception:
        chunks = []
    if chunks:
        _CACHE[title] = chunks
    return chunks


# ---------------------------------------------------------------------------------------------
# Listings: the {{see}} / {{do}} entries travellers maintain on a destination page (name, short text,
# sometimes a price). They are the best free source of named sights for small towns that OpenStreetMap
# and Wikipedia barely cover. Returned in the same OSM-like shape the place builder already understands.
# ---------------------------------------------------------------------------------------------
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_LISTING_KINDS = {"see", "do"}
MAX_LISTINGS = 60
_SETTLEMENT = re.compile(r"\b(village|town|cantonment|suburb|hamlet|township|city|district)\b")
_VIEW_NAME = re.compile(r"\b(point|viewpoint|sunset|sunrise|trail|trek|hill|ridge|view)\b", re.I)
_KM = re.compile(r"(\d+(?:\.\d+)?)\s*km", re.I)
FAR_KM = 7.0                                 # a sight this far from the town is a day trip, ranked lower


def _fetch_wikitext(title: str, timeout: float = 8.0) -> str:
    q = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "redirects": 1,
                                "format": "json", "formatversion": 2})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "travel-planner-demo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("parse") or {}).get("wikitext", "") or ""


def _plain(text: str, limit: int) -> str:
    text = _LINK.sub(r"\1", text or "")
    for _ in range(3):
        text = _TEMPLATE.sub("", text)
    text = re.sub(r"<[^>]*>|'{2,}", "", text)
    return sanitize_untrusted(text, limit)


def _split_fields(body: str) -> list[str]:
    """Split a template body on top-level '|' (not inside [[links]] or nested {{templates}})."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1; cur.append(two); i += 2; continue
        if two in ("]]", "}}"):
            depth = max(0, depth - 1); cur.append(two); i += 2; continue
        if body[i] == "|" and depth == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(body[i])
        i += 1
    parts.append("".join(cur))
    return parts


def _templates(wikitext: str, kinds: str = "see|do"):
    """Yield (kind, body) for each top-level {{see ...}} / {{do ...}} (or other `kinds`) template."""
    for m in re.finditer(r"\{\{\s*(" + kinds + r")\s*\|", wikitext, flags=re.I):
        depth, i = 1, m.end()
        while i < len(wikitext) and depth:
            two = wikitext[i:i + 2]
            if two == "{{":
                depth += 1; i += 2
            elif two == "}}":
                depth -= 1; i += 2
            else:
                i += 1
        if depth == 0:
            yield m.group(1).lower(), wikitext[m.end():i - 2]


def parse_listings(wikitext: str, classify: Callable[[str], dict | None]) -> list[dict]:
    """Turn {{see}}/{{do}} entries into OSM-shaped elements. `classify(text)` maps words to a sight kind;
    'see' entries that match nothing are still sights (generic attraction), 'do' entries must match."""
    out, seen = [], set()
    for kind, body in _templates(wikitext):
        fields = {}
        for part in _split_fields(body):
            k, eq, v = part.partition("=")
            if eq:
                fields[k.strip().lower()] = v.strip()
        name = _plain(fields.get("name", ""), 80)
        if len(name) < 3 or name.lower() in seen or kind not in _LISTING_KINDS:
            continue
        content = _plain(fields.get("content") or fields.get("description") or "", 300)
        tags = classify(name) or classify(content[:100])
        if tags is None and _VIEW_NAME.search(name):
            tags = {"tourism": "viewpoint"}
        if tags is None:
            if kind == "do" or _SETTLEMENT.search(content[:100].lower()):
                continue                       # an unclassified "see" that describes a town is not a sight
            tags = {"tourism": "attraction"}
        seen.add(name.lower())
        tag = {**tags, "name": name, "name:en": name, "x_notable": 3 if kind == "see" else 1}
        km = _KM.search(_plain(fields.get("directions", ""), 200)) or _KM.search(content[:200])
        if km and float(km.group(1)) >= FAR_KM:
            tag["x_far"] = "yes"
        try:                                            # coordinates let the place builder measure the real distance
            lat, lon = float(fields.get("lat", "")), float(fields.get("long") or fields.get("lon") or "")
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                tag["x_lat"], tag["x_lon"] = round(lat, 5), round(lon, 5)
        except ValueError:
            pass
        if content:
            tag["description:en"] = content[:140]
        qid = (fields.get("wikidata") or "").strip()
        if re.fullmatch(r"Q\d{1,12}", qid):
            tag["wikidata"] = qid
        price = _plain(fields.get("price", ""), 60).lower()
        if price.startswith("free"):
            tag["fee"] = "no"
        elif re.search(r"\d", price):
            tag["fee"] = "yes"
        out.append({"type": "wv", "id": len(out) + 1, "tags": tag})
        if len(out) >= MAX_LISTINGS:
            break
    return out


def listings(title: str, fetch: Callable[[str], str] | None = None) -> list[dict]:
    """Named sights from a Wikivoyage page; [] on any failure. Cached in memory and on disk."""
    from ..tools import cache, wikipedia                     # local import: avoids a package import cycle
    key = f"wikivoyage-listings:v4:{title.lower()}"      # v4: adventure activities are kept as sights
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        found = parse_listings((fetch or _fetch_wikitext)(title), wikipedia.classify_text)
    except Exception:                                        # noqa: BLE001 - any failure means "no listings"
        return []
    if found:
        cache.put(key, found)
    return found


def _fetch_coords(titles: list[str], timeout: float = 6.0) -> dict[str, tuple[float, float]]:
    """Wikipedia coordinates for article titles (one request, up to 50 titles). Missing pages are left out."""
    q = urllib.parse.urlencode({"action": "query", "prop": "coordinates", "titles": "|".join(titles[:50]),
                                "redirects": 1, "colimit": "max", "format": "json", "formatversion": 2})
    req = urllib.request.Request(f"https://en.wikipedia.org/w/api.php?{q}", headers={"User-Agent": "travel-planner-demo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    q_data = data.get("query") or {}
    alias = {}
    for key in ("normalized", "redirects"):
        for m in q_data.get(key, []):
            alias[m["to"]] = m["from"]
    out = {}
    for page in q_data.get("pages", []):
        co = (page.get("coordinates") or [None])[0]
        if co:
            name = page.get("title", "")
            out[alias.get(name, name).lower()] = (float(co["lat"]), float(co["lon"]))
    return out


NEAR_ENOUGH_KM = 80.0        # a coordinate further than this is a different place with the same name: ignore it


def add_coordinates(elements: list[dict], center: dict, fetch: Callable[[list[str]], dict] | None = None) -> list[dict]:
    """Give listings that Wikivoyage left without a distance or coordinates a position from Wikipedia, by name,
    so places like a neighbouring town can be recognised as day trips. Best effort: any failure returns the
    listings unchanged. Only coordinates within NEAR_ENOUGH_KM of the destination are trusted."""
    from ..tools import cache
    from ..tools.geo import distance_km
    todo = [e for e in elements if e.get("type") == "wv" and "x_far" not in e["tags"] and "x_lat" not in e["tags"]]
    if not todo or "lat" not in center or "lon" not in center:
        return elements
    names = sorted({e["tags"]["name"] for e in todo})
    key = f"wikivoyage-coords:v1:{center['lat']:.3f},{center['lon']:.3f}:" + "|".join(names).lower()
    found = cache.get(key)
    if found is None:
        try:
            found = {k: list(v) for k, v in (fetch or _fetch_coords)(names).items()}
        except Exception:                                    # noqa: BLE001 - offline or rate limited: keep going
            return elements
        cache.put(key, found)
    out = []
    for e in elements:
        pos = found.get(e["tags"].get("name", "").lower()) if e in todo else None
        if pos and distance_km(center, {"lat": pos[0], "lon": pos[1]}) <= NEAR_ENOUGH_KM:
            e = {**e, "tags": {**e["tags"], "x_lat": round(pos[0], 5), "x_lon": round(pos[1], 5)}}
        out.append(e)
    return out


def parse_eat_listings(wikitext: str) -> list[dict]:
    """{{eat}} entries -> OSM-shaped elements (type 'wv') with hours, website and coordinates kept as x_ tags."""
    out, seen = [], set()
    for kind, body in _templates(wikitext, "eat"):
        fields = {}
        for part in _split_fields(body):
            k, eq, v = part.partition("=")
            if eq:
                fields[k.strip().lower()] = v.strip()
        name = _plain(fields.get("name", ""), 70)
        if len(name) < 3 or name.lower() in seen:
            continue
        seen.add(name.lower())
        tag = {"amenity": "restaurant", "name": name, "name:en": name,
               "description:en": _plain(fields.get("content") or fields.get("description") or "", 220)}
        hours = _plain(fields.get("hours", ""), 90)
        if hours:
            tag["x_hours"] = hours
        if fields.get("url") or fields.get("website"):
            tag["x_url"] = "yes"
        try:
            lat, lon = float(fields.get("lat", "")), float(fields.get("long") or fields.get("lon") or "")
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                tag["x_lat"], tag["x_lon"] = round(lat, 5), round(lon, 5)
        except ValueError:
            pass
        qid = (fields.get("wikidata") or "").strip()
        if re.fullmatch(r"Q\d{1,12}", qid):
            tag["wikidata"] = qid
        out.append({"type": "wv", "id": len(out) + 1, "tags": tag})
        if len(out) >= MAX_LISTINGS:
            break
    return out


MAX_DISTRICTS = 4


def district_titles(title: str, wikitext: str) -> list[str]:
    """Sub-pages of a big city ("Paris/1st arrondissement"): linked as [[Title/Part]] or named in a Regionlist."""
    out: list[str] = []
    prefix = title.strip() + "/"
    for m in re.finditer(r"\[\[(" + re.escape(prefix) + r"[^\]|#]+)", wikitext):
        t = m.group(1).strip()
        if t not in out:
            out.append(t)
    for m in re.finditer(r"\bregion\d+name\s*=\s*((?:\[\[[^\]]*\]\]|[^|\n}])+)", wikitext, re.I):
        t = prefix + re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", m.group(1)).strip()
        if len(t) > len(prefix) and t not in out:
            out.append(t)
    return out[:MAX_DISTRICTS]


def eat_listings(title: str, fetch: Callable[[str], str] | None = None) -> list[dict]:
    """Restaurants from a Wikivoyage page's Eat section (for a big city split into districts: from its first
    district pages); [] on any failure. Cached on disk (30 days)."""
    from concurrent.futures import ThreadPoolExecutor
    from ..tools import cache
    key = f"wikivoyage-eat:v2:{title.lower()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    get = fetch or _fetch_wikitext
    try:
        text = get(title)
        found = parse_eat_listings(text)
        if not found:
            subs = district_titles(title, text)
            if subs:
                with ThreadPoolExecutor(max_workers=len(subs)) as pool:
                    pages = list(pool.map(lambda t: _safe_text(get, t), subs))
                seen = set()
                for page in pages:
                    for el in parse_eat_listings(page):
                        nm = el["tags"]["name"].lower()
                        if nm not in seen:
                            seen.add(nm)
                            el["id"] = len(found) + 1
                            found.append(el)
                found = found[:MAX_LISTINGS]
    except Exception:                                        # noqa: BLE001 - any failure means "no listings"
        return []
    if found:
        cache.put(key, found)
    return found


def _safe_text(get: Callable[[str], str], title: str) -> str:
    try:
        return get(title)
    except Exception:                                        # noqa: BLE001 - one bad district page is fine
        return ""


live_eat_listings = eat_listings          # tests replace the name above; this stays the real one
