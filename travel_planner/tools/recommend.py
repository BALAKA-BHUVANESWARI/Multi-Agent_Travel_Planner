"""Destination recommendations (also used for "alternative destinations").

Deterministic and free: a hand-tagged list of popular destinations is priced with the synthetic estimator
(never the live lookup, so suggestions spend no Tavily credits), then ranked by interests, season and budget.
Every figure is an ESTIMATE. The tags and best months are rough, hand-entered guidance.
"""
from __future__ import annotations

from datetime import timedelta

from .. import config
from ..utils import round_to
from . import gazetteer, geo as geo_mod
from .catalog import CITIES, DESTINATIONS
from .errors import ToolError

ACTIVITY_ALLOWANCE = 450      # INR per person per day at India's price level: entry fees and tours, a rough allowance
MAX_PER_ABROAD_COUNTRY = 1
DEFAULT_LIMIT = 4

# slug -> (interests it is known for, best months). List order breaks ties (rough popularity).
PROFILES: dict[str, tuple[tuple[str, ...], tuple[int, ...]]] = {
    "goa": (("beach", "nightlife", "food", "relaxation"), (11, 12, 1, 2, 3)),
    "jaipur": (("history", "culture", "shopping", "food"), (10, 11, 12, 1, 2, 3)),
    "udaipur": (("history", "culture", "relaxation", "food"), (10, 11, 12, 1, 2, 3)),
    "kochi": (("culture", "history", "food", "nature", "relaxation"), (10, 11, 12, 1, 2, 3)),
    "manali": (("adventure", "nature", "relaxation"), (3, 4, 5, 6, 10, 12, 1)),
    "rishikesh": (("adventure", "spiritual", "nature"), (2, 3, 4, 10, 11)),
    "varanasi": (("spiritual", "culture", "history", "food"), (10, 11, 12, 1, 2, 3)),
    "agra": (("history", "culture"), (10, 11, 12, 1, 2, 3)),
    "amritsar": (("spiritual", "history", "food", "culture"), (10, 11, 12, 1, 2, 3)),
    "shimla": (("nature", "relaxation", "family"), (3, 4, 5, 6, 10, 12)),
    "darjeeling": (("nature", "relaxation", "culture"), (3, 4, 5, 10, 11)),
    "gangtok": (("nature", "adventure", "spiritual"), (3, 4, 5, 10, 11)),
    "munnar": (("nature", "relaxation", "family"), (9, 10, 11, 12, 1, 2, 3)),
    "alleppey": (("relaxation", "nature", "food", "family"), (10, 11, 12, 1, 2)),
    "mysuru": (("history", "culture", "family", "shopping"), (10, 11, 12, 1, 2)),
    "hampi": (("history", "culture", "adventure"), (10, 11, 12, 1, 2)),
    "pondicherry": (("beach", "relaxation", "food", "culture"), (10, 11, 12, 1, 2, 3)),
    "ooty": (("nature", "family", "relaxation"), (4, 5, 6, 10, 11)),
    "leh": (("adventure", "nature", "spiritual"), (6, 7, 8, 9)),
    "jaisalmer": (("history", "adventure", "culture"), (11, 12, 1, 2)),
    "shillong": (("nature", "adventure"), (3, 4, 10, 11)),
    "port-blair": (("beach", "nature", "adventure"), (11, 12, 1, 2, 3, 4)),
    "gokarna": (("beach", "relaxation", "spiritual"), (10, 11, 12, 1, 2)),
    "coorg": (("nature", "relaxation", "food"), (9, 10, 11, 12, 1, 2, 3)),
    "varkala": (("beach", "relaxation"), (11, 12, 1, 2, 3)),
    "dharamshala": (("nature", "spiritual", "adventure"), (3, 4, 5, 9, 10, 11)),
    "sawai-madhopur": (("nature", "adventure", "family"), (10, 11, 12, 1, 2, 3, 4)),
    "bangkok": (("food", "shopping", "spiritual", "nightlife", "culture"), (11, 12, 1, 2)),
    "phuket": (("beach", "nightlife", "relaxation"), (11, 12, 1, 2, 3)),
    "bali": (("beach", "nature", "relaxation", "spiritual"), (4, 5, 6, 7, 8, 9)),
    "kathmandu": (("spiritual", "culture", "adventure", "history"), (3, 4, 10, 11)),
    "pokhara": (("adventure", "nature", "relaxation"), (3, 4, 10, 11)),
    "paro": (("spiritual", "nature", "culture"), (3, 4, 5, 9, 10, 11)),
    "kandy": (("culture", "nature", "spiritual"), (1, 2, 3, 4, 7, 8)),
    "hanoi": (("food", "culture", "history"), (10, 11, 3, 4)),
    "da-nang": (("beach", "food", "family"), (2, 3, 4, 5, 6, 7, 8)),
    "siem-reap": (("history", "culture", "spiritual"), (11, 12, 1, 2)),
    "kuala-lumpur": (("food", "shopping", "family"), (5, 6, 7, 12, 1, 2)),
    "singapore": (("family", "food", "shopping", "culture"), (2, 3, 4, 7, 8)),
    "dubai": (("shopping", "family", "adventure", "beach"), (11, 12, 1, 2, 3)),
    "maldives": (("beach", "relaxation", "nature"), (11, 12, 1, 2, 3, 4)),
    "istanbul": (("history", "culture", "food", "shopping"), (4, 5, 9, 10)),
    "tokyo": (("food", "shopping", "culture", "family"), (3, 4, 10, 11)),
    "kyoto": (("history", "culture", "spiritual"), (3, 4, 10, 11)),
    "paris": (("culture", "history", "food", "shopping"), (4, 5, 6, 9, 10)),
    "rome": (("history", "culture", "food", "spiritual"), (4, 5, 6, 9, 10)),
    "interlaken": (("adventure", "nature"), (6, 7, 8, 9, 12, 1, 2)),
    "prague": (("history", "culture", "nightlife"), (4, 5, 6, 9, 10)),
    "barcelona": (("beach", "culture", "nightlife", "food"), (5, 6, 9, 10)),
}


def profile_tags(slug: str) -> list[str]:
    return list(PROFILES.get(slug, ((), ()))[0])


def _geo_for(slug: str) -> dict | None:
    if slug in DESTINATIONS:
        return geo_mod.from_catalog(slug)
    entry = gazetteer.lookup(slug.replace("-", " "))
    return geo_mod._from_gazetteer(entry) if entry else None


def estimate_trip(origin: str, origin_geo: dict | None, slug: str, geo: dict, start, days: int,
                  travelers: int, mode: str | None = None) -> dict:
    """Cheapest and comfortable totals for one destination, from the estimator only."""
    from . import impl                                           # impl imports this module's tool

    ret = start + timedelta(days=days - 1)
    fl = impl.search_flights(origin, slug, start.isoformat(), ret.isoformat(), travelers, origin_geo, geo,
                             mode if mode not in (None, "auto") else None, live_prices=False)
    ho = impl.search_hotels(slug, start.isoformat(), days - 1, travelers, geo, live_prices=False)
    nights, rooms = days - 1, ho["rooms"]
    out = {}
    for key, pick, strategy in (("from", min, "cheapest"), ("comfortable", None, "normal")):
        if pick:
            travel = min(o["price_pp"] for o in fl["options"])
            night = min(o["price_night_per_room"] for o in ho["options"])
        else:
            travel = next(o for o in fl["options"] if o["id"] == "best")["price_pp"]
            night = next(o for o in ho["options"] if o["id"] == "3star")["price_night_per_room"]
        food = config.FOOD_PER_PERSON_DAY[strategy] * geo["cost_factor"] * days * travelers
        acts = ACTIVITY_ALLOWANCE * (geo["cost_factor"] ** 0.8) * days * travelers * (0.5 if pick else 1.0)
        out[key] = int(round_to(travel * travelers + night * nights * rooms + food + acts, 500))
    out["travel_mode"] = fl["mode"]
    out["travel_hours"] = next((o["duration_h"] for o in fl["options"] if o["id"] == "best"), 0)
    return out


def recommend_destinations(origin: str, start_date: str, days: int, travelers: int, budget: int,
                           preferences: list | None = None, exclude: str | None = None,
                           origin_geo: dict | None = None, exclude_geo: dict | None = None,
                           scope: str = "any", mode: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """Destinations that suit the interests, month and budget. ``exclude`` is the current destination (it is
    priced the same way and returned as ``baseline`` so alternatives can be compared like for like)."""
    from . import impl, transport

    start = impl._date(start_date)
    days, travelers, budget = int(days), int(travelers), int(budget)
    if not (config.MIN_DAYS <= days <= config.MAX_DAYS) or not (1 <= travelers <= config.MAX_TRAVELERS):
        raise ToolError("days or travelers out of range", retryable=False)
    prefs = [p for p in (preferences or []) if isinstance(p, str)]
    olat, olon, o_cc, _ = impl._origin_point(origin, origin_geo)
    wanted = prefs or profile_tags(exclude or "")
    rows = []
    for order, (slug, (tags, months)) in enumerate(PROFILES.items()):
        geo = _geo_for(slug)
        if geo is None or slug in (origin, exclude):
            continue
        if geo_mod.distance_km({"lat": olat, "lon": olon}, geo) < 60:
            continue
        if (scope == "india" and geo["cc"] != "IN") or (scope == "abroad" and geo["cc"] == (o_cc or "IN")):
            continue
        try:
            est = estimate_trip(origin, origin_geo, slug, geo, start, days, travelers, mode)
        except ToolError:                                    # e.g. no land route for the chosen road mode
            continue
        if transport.is_long(mode or "", est["travel_hours"]):  # don't SUGGEST a very long ride (picking is free)
            continue
        matched = [t for t in wanted if t in tags]
        in_season = start.month in months
        fits, easy = est["from"] <= budget, est["comfortable"] <= budget
        score = 3 * len(matched) + (2 if in_season else -3) + (2 if easy else 1 if fits else -6)
        if not easy and fits:
            score -= 0.5
        rows.append((score, order, {
            "slug": slug, "name": geo["name"], "country": geo["country"], "tags": list(tags), "matched": matched,
            "in_season": in_season, "fits_budget": fits, "comfortable_fits": easy,
            "estimate_from": est["from"], "estimate_comfortable": est["comfortable"],
            "travel_mode": est["travel_mode"], "estimated": True,
        }))
    rows.sort(key=lambda r: (-r[0], r[2]["estimate_from"] if not r[2]["fits_budget"] else 0, r[1]))
    affordable = [r for r in rows if r[2]["fits_budget"]]
    pool = affordable or sorted(rows, key=lambda r: r[2]["estimate_from"])[:12]
    chosen, per_country = [], {}
    for _, _, item in pool:
        cc = item["country"]
        if cc != "India" and per_country.get(cc, 0) >= MAX_PER_ABROAD_COUNTRY:
            continue
        per_country[cc] = per_country.get(cc, 0) + 1
        chosen.append(item)
        if len(chosen) >= max(1, min(8, int(limit))):
            break
    baseline = None
    if exclude:
        geo = impl._clean_geo(exclude_geo) or _geo_for(exclude)
        if geo:
            try:
                baseline = estimate_trip(origin, origin_geo, exclude, geo, start, days, travelers, mode)
            except ToolError:
                baseline = None
    return {"source": "curated-tags + synthetic-estimator", "estimated": True, "suggestions": chosen,
            "baseline": baseline, "any_fit": bool(affordable),
            "origin_name": CITIES[origin][0] if origin in CITIES else (origin_geo or {}).get("name", origin)}
