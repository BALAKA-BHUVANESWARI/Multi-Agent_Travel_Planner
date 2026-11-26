"""Tool: travel search (flights, trains, buses, car, bike). Live prices when configured,
otherwise clearly labelled estimates."""
from __future__ import annotations

from app.core import config
from app.core.utils import hash01, round_to, to_hhmm
from app.integrations import live_prices as live
from app.services.pricing import transport_estimator as transport
from app.tools.common import (
    country_of,
    destination_info,
    haversine_km,
    origin_name,
    origin_point,
    parse_date,
    season_factor,
)
from app.tools.errors import ToolError

GROUND_KM = 300          # below this a flight makes no sense: price a train/bus journey instead
LONG_HAUL_KM = 9000      # beyond this the estimator offers one-stop itineraries only


def search_flights(origin: str, destination: str, depart_date: str, return_date: str, travelers: int,
                   origin_geo: dict | None = None, destination_geo: dict | None = None,
                   mode: str | None = None, live_prices: bool = True) -> dict:
    """Round-trip travel options. ``mode``: flight | train | bus | car | bike, or None / "auto" to let the
    estimator choose (a flight, or train/bus for short distances). ``live_prices=False`` skips the live lookup
    (used for the quick "how would you like to travel" cards, which would otherwise spend Tavily credits)."""
    mode = (mode or "auto").lower()
    if mode != "auto" and mode not in transport.MODES:
        raise ToolError(f"unknown travel mode '{mode}' (use one of: {', '.join(transport.MODES)} or auto)",
                        retryable=False)
    d = destination_info(destination, destination_geo)
    olat, olon, o_cc, o_cf = origin_point(origin, origin_geo)
    if origin == destination:
        raise ToolError("origin and destination are the same", retryable=False)
    dep, ret = parse_date(depart_date), parse_date(return_date)
    if ret <= dep:
        raise ToolError("return date must be after departure date", retryable=False)
    km = haversine_km(olat, olon, d["lat"], d["lon"])
    if km < 15:
        raise ToolError("origin and destination are the same place", retryable=False)
    d_cc = country_of(destination, destination_geo)
    international = bool(d_cc) and bool(o_cc) and d_cc != o_cc
    jitter = 1 + (hash01("flight", origin, destination, depart_date) - 0.5) * 0.10

    def opt(id_, label, dep_out, dep_back, price, stops, dur, mode):
        return {
            "id": id_, "label": label, "stops": stops, "duration_h": round(dur, 1), "mode": mode,
            "depart_out": to_hhmm(dep_out), "arrive_out": to_hhmm(dep_out + dur * 60),
            "depart_back": to_hhmm(dep_back), "arrive_back": to_hhmm(dep_back + dur * 60),
            "price_pp": round_to(price), "estimated": True,
        }

    if mode in ("train", "bus", "car", "bike"):                   # the traveller chose an overland mode
        if transport.crosses_sea((olat, olon, o_cc), (d["lat"], d["lon"], d_cc)):
            raise ToolError("No road or rail link: this trip crosses the sea. Try flight.", retryable=False)
        days = (ret - dep).days + 1
        options, basis = transport.options_for(mode, km, o_cf, d["cost_factor"], travelers, days,
                                               international, jitter)
        return {"source": "synthetic-estimator", "estimated": True, "origin": origin, "destination": destination,
                "depart_date": depart_date, "return_date": return_date, "travelers": travelers,
                "distance_km": round(km), "currency": "INR", "price_basis": basis, "mode": mode,
                "international": international, "options": options}
    if mode == "auto" and km < GROUND_KM:                         # short hop: train / bus
        rate = 2.5 * (((o_cf + d["cost_factor"]) / 2) ** 0.7)       # INR per km one way, per person (comfortable seat)
        base = max(300.0, rate * km) * 2 * jitter
        dur = km / 55.0 + 0.5
        options = [
            opt("best", "Train/bus, comfortable seat, mid-morning out / late-afternoon back", 9 * 60,
                16 * 60 + 30, base, 0, dur, "ground"),
            opt("early_late", "Train/bus, early start out / evening back", 5 * 60 + 45, 19 * 60 + 45,
                base * 0.88, 0, dur, "ground"),
            opt("one_stop", "Cheapest bus or train (basic class)", 6 * 60 + 30, 15 * 60 + 30, base * 0.65, 1,
                dur * 1.15, "ground"),
        ]
        mode, basis = "ground", "round trip by train/bus, per person"
    else:
        if international:
            one_way = (3000 + 4.5 * km) * (0.75 + 0.25 * o_cf)
        else:
            one_way = max(2500.0, 1900 + 2.9 * km) * (0.6 + 0.4 * o_cf)
        base = one_way * 2 * 0.92 * season_factor(d, dep.month, 1.2, 0.9) * jitter
        nonstop_h = 1.0 + km / 700.0
        stop_h = nonstop_h * 1.4 + 1.5
        if km > LONG_HAUL_KM:
            options = [
                opt("best", "1 stop, comfortable timings, mid-morning out / late-afternoon back", 9 * 60,
                    16 * 60 + 30, base, 1, stop_h, "flight"),
                opt("early_late", "1 stop, early-morning out / evening back", 5 * 60 + 45, 19 * 60 + 45,
                    base * 0.88, 1, stop_h, "flight"),
                opt("one_stop", "1 stop, cheapest fare", 6 * 60 + 30, 15 * 60 + 30, base * 0.72, 1, stop_h * 1.1,
                    "flight"),
            ]
        else:
            options = [
                opt("best", "Nonstop, mid-morning out / late-afternoon back", 9 * 60, 16 * 60 + 30, base, 0,
                    nonstop_h, "flight"),
                opt("early_late", "Nonstop, early-morning out / evening back", 5 * 60 + 45, 19 * 60 + 45,
                    base * 0.88, 0, nonstop_h, "flight"),
                opt("one_stop", "1 stop, cheapest fare", 6 * 60 + 30, 15 * 60 + 30, base * 0.72, 1, stop_h,
                    "flight"),
            ]
        mode, basis = "flight", "round trip, per person"
    result = {"source": "synthetic-estimator", "estimated": True, "origin": origin, "destination": destination,
              "depart_date": depart_date, "return_date": return_date, "travelers": travelers,
              "distance_km": round(km), "currency": "INR", "price_basis": basis, "mode": mode,
              "international": international, "options": options}
    if mode == "flight" and live_prices and config.live_prices_enabled():
        try:
            result.update(live.flights(origin, destination, origin_name(origin, origin_geo), d["name"], dep, ret,
                                       travelers))
        except live.LiveUnavailable as e:
            result["live_note"] = f"Live fares were unavailable ({e}); the flight price is an estimate."
        except Exception as e:                                       # noqa: BLE001 - never let this break a plan
            result["live_note"] = (f"Live fares were unavailable ({type(e).__name__}); the flight price is an "
                                   "estimate.")
    return result
