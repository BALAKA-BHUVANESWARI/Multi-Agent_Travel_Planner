"""Sustainable Travel: compare the ways of getting there by estimated greenhouse-gas emissions.

estimate = distance x a published average factor. It knows nothing about the actual aircraft, train or vehicle,
so the page always calls it an estimate. Factors are per kilometre: kg CO2 per passenger (train, bus, flight) or
per vehicle (car, motorbike, then shared between the people in it).
"""
from __future__ import annotations

import math

from app.services.geo_service import distance_km
from app.services.pricing import transport_estimator as transport

SOURCES = {
    "rail_in": {"title": "India GHG Program: rail transport emission factors (2014-15, CO2 only)",
                "url": "https://indiaghgp.org/sites/default/files/Rail%20Transport%20Emission.pdf"},
    "road_in": {"title": "India GHG Program: road transport emission factors (2015 draft, CO2 only)",
                "url": "https://indiaghgp.org/sites/default/files/Road%20Transport%20Technical%20Paper.pdf"},
    "uk2025": {"title": "UK government 2025 conversion factors (CO2e), as listed by GreenCalculus",
               "url": "https://greencalculus.com/data/business-travel-freight-logistics-emission-factors/"},
}
# kg per km
RAIL = {"in": (0.0078, "rail_in"), "other": (0.0355, "uk2025")}                 # per passenger
CAR = {"in": (0.140, "road_in"), "other": (0.163, "uk2025")}                    # per car: petrol hatchback / average
BIKE = {"in": (0.0458, "road_in"), "other": (0.1137, "uk2025")}                 # per motorbike
COACH = (0.0278, "uk2025")     # per passenger; the Indian figure covers city buses only, so it is not used
# flight bands: (up to km, with high-altitude warming effects, fuel burn only), per passenger, economy
FLIGHT = ((700.0, 0.229, 0.136), (3700.0, 0.126, 0.074), (float("inf"), 0.117, 0.069))
INDIAN_VEHICLES = {"IN", "NP", "BT", "BD"}
PER_CAR, PER_BIKE = 4, 2

LABELS = {"flight": "Flight", "train": "Train", "bus": "Bus", "car": "Car", "bike": "Motorbike",
          "ground": "Train/bus"}
TIPS = [
    "Take a direct flight when you can: every take-off burns a lot of fuel.",
    "One longer trip usually means less travel than several short ones.",
    "At your destination, walk, cycle or use public transport for short hops.",
    "Carry a refillable water bottle and avoid single-use plastic.",
    "Stay on marked paths, leave no litter and do not disturb wildlife.",
]
METHOD = ("Each figure is distance x an average published factor, for the round trip. Distance is the straight "
          "line between the two places (road and rail add 25%). It ignores your actual vehicle, how full it is, "
          "layovers, travel at the destination and the hotel. Flights include the UK government's allowance for "
          "extra warming from emissions at altitude; the fuel-only figure is shown too. A longer flight is never "
          "shown as emitting less than a shorter one. The figures come from different studies and years, so treat "
          "gaps of less than about a quarter as a tie. Use them to compare options, not as a measurement.")


def flight_factor_km(km: float, fuel_only: bool = False) -> float:
    """kg for one passenger one way. The published bands step down with distance, so the result is held at the
    top of the previous band until the longer band overtakes it."""
    column = 2 if fuel_only else 1
    floor = 0.0
    for band in FLIGHT[:-1]:
        limit, factor = band[0], band[column]
        if km <= limit:
            return max(floor, km * factor)
        floor = max(floor, limit * factor)
    return max(floor, km * FLIGHT[-1][column])


def _round(kg: float) -> float:
    return round(kg, 1) if kg < 10 else float(round(kg))


def region(origin_cc: str, dest_cc: str) -> str:
    return "in" if origin_cc == "IN" and dest_cc in INDIAN_VEHICLES else "other"


def estimate(mode: str, straight_km: float, travelers: int, origin_cc: str, dest_cc: str) -> dict | None:
    """Round-trip estimate per person for one way of travelling, or None for an unknown mode."""
    travelers = max(1, int(travelers))
    area = region(origin_cc, dest_cc)
    road = transport.road_km(straight_km)
    fuel_only = None
    if mode == "flight":
        pp = 2 * flight_factor_km(straight_km)
        fuel_only = _round(2 * flight_factor_km(straight_km, fuel_only=True))
        source, basis = "uk2025", "per economy passenger, including high-altitude warming"
    elif mode == "train":
        factor, source = RAIL[area]
        pp, basis = 2 * road * factor, "per passenger"
    elif mode in ("bus", "ground"):
        factor, source = COACH
        pp = 2 * road * factor
        basis = "per passenger, long-distance coach" + (" (bus figure used for train/bus)" if mode == "ground"
                                                        else "")
    elif mode in ("car", "bike"):
        factor, source = (CAR if mode == "car" else BIKE)[area]
        seats = PER_CAR if mode == "car" else PER_BIKE
        vehicles = math.ceil(travelers / seats)
        pp = 2 * road * factor * vehicles / travelers
        word = "car" if mode == "car" else "motorbike"
        basis = f"your share of {vehicles} {word}(s) for {travelers} traveller(s)"
    else:
        return None
    return {"mode": mode, "label": LABELS[mode], "kg_pp": _round(pp), "kg_group": _round(pp * travelers),
            "fuel_only_kg_pp": fuel_only, "basis": basis, "source": source}


def _point(geo: dict | None) -> dict | None:
    try:
        return {"lat": float(geo["lat"]), "lon": float(geo["lon"]), "cc": str(geo.get("cc") or "")}
    except (TypeError, KeyError, ValueError):
        return None


def for_trip(constraints: dict, mode: str | None) -> dict | None:
    """The estimate for the way of travelling in the current plan (None when places or mode are unknown)."""
    o, d = _point(constraints.get("origin_geo")), _point(constraints.get("destination_geo"))
    if not o or not d or not mode:
        return None
    return estimate(mode, distance_km(o, d), constraints.get("travelers") or 1, o["cc"], d["cc"])


def _hours(mode: str, km: float) -> float:
    if mode == "flight":
        return round(1.0 + km / 700.0, 1)
    return round(transport.duration_hours(mode, transport.road_km(km)), 1)


def _unavailable(mode: str, km: float, o: dict, d: dict) -> str:
    if mode == "flight":
        return ""
    if transport.crosses_sea((o["lat"], o["lon"], o["cc"]), (d["lat"], d["lon"], d["cc"])):
        return "No road or rail link: this trip crosses the sea."
    if o["cc"] and d["cc"] and o["cc"] != d["cc"] and km > transport.MAX_INTERNATIONAL_KM:
        return "Too far to go overland between countries."
    return ""


def _advice(rows: list[dict], selected: str | None, travelers: int) -> list[str]:
    usable = [r for r in rows if r["available"]]
    if not usable:
        return []
    best = min(usable, key=lambda r: r["kg_pp"])
    if len(usable) == 1:
        return [f"{best['label']} is the only way of travelling this planner offers for this route, so there is "
                "nothing to compare it with."]
    out = []
    chosen = next((r for r in usable if r["mode"] == selected), None)
    if chosen is None and selected == "ground":
        out.append(f"{best['label']} has the lowest estimate for this route.")
    elif chosen is None or chosen["mode"] == best["mode"]:
        out.append(f"{best['label']} has the lowest estimate for this route"
                   + (": that is what your plan uses." if chosen else "."))
    elif chosen["kg_pp"] > best["kg_pp"] * 1.15:
        saved = chosen["kg_pp"] - best["kg_pp"]
        out.append(f"Going by {best['label'].lower()} instead of {chosen['label'].lower()} would cut travel "
                   f"emissions by about {saved / chosen['kg_pp']:.0%} ({saved:.0f} kg per person). It takes about "
                   f"{best['hours']:g} h each way instead of {chosen['hours']:g} h.")
    else:
        out.append(f"{chosen['label']} is close to the lowest estimate ({best['label'].lower()}) for this route.")
    car = next((r for r in usable if r["mode"] == "car"), None)
    if car and travelers % PER_CAR:
        out.append("By car, each extra person sharing a vehicle lowers everyone's share.")
    return out


def compare(constraints: dict, selected: str | None) -> dict:
    o, d = _point(constraints.get("origin_geo")), _point(constraints.get("destination_geo"))
    if not o or not d:
        return {"available": False, "reason": "The places in this trip have no coordinates.", "modes": []}
    km = distance_km(o, d)
    travelers = constraints.get("travelers") or 1
    rows = []
    for mode in transport.MODES:
        why = _unavailable(mode, km, o, d)
        if why:
            rows.append({"mode": mode, "label": LABELS[mode], "available": False, "reason": why})
            continue
        rows.append({**estimate(mode, km, travelers, o["cc"], d["cc"]), "available": True, "hours": _hours(mode, km),
                     "selected": mode == selected})
    usable = [r for r in rows if r["available"]]
    lowest = min(r["kg_pp"] for r in usable)
    for r in usable:
        r["lowest"] = len(usable) > 1 and r["kg_pp"] == lowest
    rows.sort(key=lambda r: (not r["available"], r.get("kg_pp", 0)))
    used = sorted({r["source"] for r in usable})
    return {"available": True, "straight_km": round(km), "travelers": travelers, "selected": selected,
            "current": for_trip(constraints, selected), "modes": rows, "advice": _advice(rows, selected, travelers),
            "tips": TIPS, "method": METHOD, "sources": [SOURCES[k] for k in used], "estimated": True}
