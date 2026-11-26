"""Tool: suggest destinations that fit a budget, a month and a traveller's interests.

Deterministic and free: popular destinations are priced with the estimator (never the live lookup, so suggestions
spend no Tavily credits), then ranked. Every figure is an ESTIMATE.
"""
from __future__ import annotations

from datetime import timedelta

from app.core import config
from app.core.utils import round_to
from app.data.curated_destinations import CITIES
from app.data.destination_ideas import PROFILES, geo_for, profile_tags
from app.services import geo_service as geo_mod
from app.services.pricing import transport_estimator as transport
from app.tools.accommodation_tools import search_hotels
from app.tools.common import clean_geo, origin_point, parse_date
from app.tools.errors import ToolError
from app.tools.flight_tools import search_flights

ACTIVITY_ALLOWANCE = 450      # INR per person per day at India's price level: entry fees and tours, a rough allowance
MAX_PER_ABROAD_COUNTRY = 1
DEFAULT_LIMIT = 4


def estimate_trip(origin: str, origin_geo: dict | None, slug: str, geo: dict, start, days: int,
                  travelers: int, mode: str | None = None) -> dict:
    """Cheapest and comfortable totals for one destination, from the estimator only."""
    ret = start + timedelta(days=days - 1)
    fl = search_flights(origin, slug, start.isoformat(), ret.isoformat(), travelers, origin_geo, geo,
                             mode if mode not in (None, "auto") else None, live_prices=False)
    ho = search_hotels(slug, start.isoformat(), days - 1, travelers, geo, live_prices=False)
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
    out["border_warning"] = fl.get("border_warning", "")
    out["travel_hours"] = next((o["duration_h"] for o in fl["options"] if o["id"] == "best"), 0)
    return out


def recommend_destinations(origin: str, start_date: str, days: int, travelers: int, budget: int,
                           preferences: list | None = None, exclude: str | None = None,
                           origin_geo: dict | None = None, exclude_geo: dict | None = None,
                           scope: str = "any", mode: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """Destinations that suit the interests, month and budget. ``exclude`` is the current destination (it is
    priced the same way and returned as ``baseline`` so alternatives can be compared like for like)."""

    start = parse_date(start_date)
    days, travelers, budget = int(days), int(travelers), int(budget)
    if not (config.MIN_DAYS <= days <= config.MAX_DAYS) or not (1 <= travelers <= config.MAX_TRAVELERS):
        raise ToolError("days or travelers out of range", retryable=False)
    prefs = [p for p in (preferences or []) if isinstance(p, str)]
    olat, olon, o_cc, _ = origin_point(origin, origin_geo)
    wanted = prefs or profile_tags(exclude or "")
    rows = []
    for order, (slug, (tags, months)) in enumerate(PROFILES.items()):
        geo = geo_for(slug)
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
        # don't SUGGEST a very long ride or a doubtful border crossing (picking the place yourself is free)
        if est["border_warning"] or transport.is_long(mode or "", est["travel_hours"]):
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
        geo = clean_geo(exclude_geo) or geo_for(exclude)
        if geo:
            try:
                baseline = estimate_trip(origin, origin_geo, exclude, geo, start, days, travelers, mode)
            except ToolError:
                baseline = None
    return {"source": "curated-tags + synthetic-estimator", "estimated": True, "suggestions": chosen,
            "baseline": baseline, "any_fit": bool(affordable),
            "origin_name": CITIES[origin][0] if origin in CITIES else (origin_geo or {}).get("name", origin)}
