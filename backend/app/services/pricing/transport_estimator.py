"""Estimated round-trip options for the ground and road travel modes: train, bus, car and bike.

Like the flight estimator these are SYNTHETIC ESTIMATES (straight-line distance x a road factor x a per-km rate
scaled by the places' price levels). Every option carries ``estimated: True``. The traveller decides how to travel:
a long journey is never refused, it is marked as long. A mode raises a non-retryable ToolError only when there is
no road or rail link (across the sea), or when a long route between countries is not one the planner offers
(see ROAD_LINKS).
"""
from __future__ import annotations

import math

from app.core.utils import round_to, to_hhmm
from app.tools.errors import ToolError

MODES = ("flight", "train", "bus", "car", "bike")
ROAD_FACTOR = 1.25                 # straight-line km -> road/rail km
MAX_INTERNATIONAL_KM = 1500        # between countries, longer overland trips need an entry in ROAD_LINKS
# Long international routes with a road link, as (countries) -> (modes offered, warning). Add one only after
# confirming that a road exists. There is no train or bus here: the planner has no through service to price.
ROAD_LINKS = {
    frozenset(("IN", "TH")): (
        ("car", "bike"),
        "Check before you plan: this route goes through north-east India and Myanmar. The border crossings may be "
        "closed or restricted. Confirm that you and your vehicle (above all a rented one) may cross, and check "
        "permits, visas, vehicle papers and safety advice with official sources. The estimate leaves out permit, "
        "visa and escort costs, and the real road is likely longer, slower and dearer than shown."),
}

# mode -> average km/h including stops
_SPEED = {"train": 55.0, "bus": 45.0, "car": 55.0, "bike": 45.0}
# One-way hours beyond which a journey counts as long. This NEVER blocks a choice: it adds a warning, and keeps
# destination suggestions for a chosen road mode within reach.
LONG_HOURS = {"train": 40.0, "bus": 32.0, "car": 45.0, "bike": 56.0}
_LONG_ADVICE = {"train": "Check that a direct train runs; you may have to change trains.",
                "bus": "There may be no direct bus, so expect to change buses.",
                "car": "Share the driving and keep a spare day for delays.",
                "bike": "This is hard riding: service the bike and keep a spare day for delays."}
# No road or rail link to these countries, or to these island regions (name, south, north, west, east).
_SEA_COUNTRIES = {"LK", "MV", "JP", "PH", "TW", "IS", "AU", "NZ", "MU", "SC", "FJ", "MG", "CY", "MT", "CU", "JM",
                  "BS", "BB"}
_ISLAND_REGIONS = (("Andaman and Nicobar", 6.5, 14.0, 92.0, 94.5), ("Lakshadweep", 8.0, 12.5, 71.0, 74.0),
                   ("Hawaii", 18.5, 22.5, -160.5, -154.5), ("Samui islands", 9.4, 10.15, 99.75, 100.15))
OVERNIGHT_H = 9.0                  # a train/bus journey longer than this leaves the evening (or days) before
HALT_H = 9.0                       # a car/bike journey longer than this is split over two days (night halt)
HALT_REST_H = 10.0                 # hours of rest in that halt
HALT_NIGHT_INR = 1800.0            # one room for the night, per room, before the price-level scaling


def _hhmm(minutes: float) -> str:
    return to_hhmm(int(round(minutes)) % 1440)


def road_km(straight_km: float) -> float:
    return straight_km * ROAD_FACTOR


def duration_hours(mode: str, km: float) -> float:
    """One-way door-to-door hours for the road/rail distance ``km`` (includes rest stops)."""
    hours = km / _SPEED[mode]
    if mode in ("car", "bike"):
        hours += math.floor(km / (250 if mode == "car" else 150)) * 0.5
    return hours


def _island(lat: float, lon: float) -> str:
    return next((n for n, s, w_n, w, e in _ISLAND_REGIONS if s <= lat <= w_n and w <= lon <= e), "")


def crosses_sea(origin: tuple, destination: tuple) -> bool:
    """True when no road or rail can connect the two places. Each is (lat, lon, country code)."""
    (olat, olon, occ), (dlat, dlon, dcc) = origin, destination
    if _island(olat, olon) != _island(dlat, dlon):
        return True
    return bool(occ and dcc) and occ != dcc and bool({occ, dcc} & _SEA_COUNTRIES)


def is_long(mode: str, hours: float) -> bool:
    return hours > LONG_HOURS.get(mode, float("inf"))


def long_journey_warning(mode: str, hours: float, extra_days: int, days: int) -> str:
    """'' unless the journey is long in itself, or takes at least as many extra days as the trip lasts."""
    if mode not in _SPEED or not (is_long(mode, hours) or extra_days >= days):
        return ""
    advice = f" {_LONG_ADVICE[mode]}" if is_long(mode, hours) else ""
    return (f"Long journey: about {hours:.0f} h each way, adding {extra_days} day(s) of travel to your "
            f"{days}-day trip.{advice} Meals on the way are not in the budget.")


def overland_block(mode: str, straight_km: float, o_cc: str | None, d_cc: str | None) -> str:
    """'' when this overland mode may be chosen between the two countries, otherwise why not."""
    if not (o_cc and d_cc) or o_cc == d_cc or straight_km <= MAX_INTERNATIONAL_KM:
        return ""
    link = ROAD_LINKS.get(frozenset((o_cc, d_cc)))
    if not link:
        return (f"Not offered between these countries over {MAX_INTERNATIONAL_KM:,} km ({round(straight_km):,} km): "
                "the planner has not confirmed a road link. Try flight.")
    if mode not in link[0]:
        return (f"The planner has no through {mode} service it can price on this route. Try flight, or car or bike "
                "after checking the border.")
    return ""


def border_warning(mode: str, straight_km: float, o_cc: str | None, d_cc: str | None) -> str:
    """The warning for a long international road route that is offered, otherwise ''."""
    if not (o_cc and d_cc) or o_cc == d_cc or straight_km <= MAX_INTERNATIONAL_KM:
        return ""
    link = ROAD_LINKS.get(frozenset((o_cc, d_cc)))
    return link[1] if link and mode in link[0] else ""


def _check(mode: str, straight_km: float, countries: tuple) -> tuple[float, float]:
    why = overland_block(mode, straight_km, *countries)
    if why:
        raise ToolError(why, retryable=False, not_possible=True)
    km = road_km(straight_km)
    return km, duration_hours(mode, km)


def _leave_text(depart_rel: float) -> str:
    """Words for when the journey starts, given minutes from midnight of trip day 1 (negative = before)."""
    if depart_rel >= 0:
        return ""
    days_before = math.ceil(-depart_rel / 1440)
    clock = to_hhmm(depart_rel % 1440)
    if days_before == 1:
        return "leave the evening before" if depart_rel % 1440 >= 17 * 60 else "leave the day before"
    return f"leave {days_before} days before, at {clock}"


def halts_each_way(mode: str, hours: float) -> int:
    """Night halts on a car/bike journey: about 10 hours of riding or driving a day."""
    if mode in ("car", "bike") and hours > HALT_H:
        return max(1, math.ceil(hours / 10.0) - 1)
    return 0


def _timing(mode: str, hours: float) -> tuple[float, float, float, str, int]:
    """(departure, arrival, departure back) in minutes from midnight of trip day 1 (departure can be negative:
    the journey starts before the trip), a note, and the number of night halts each way."""
    if mode in ("train", "bus"):
        if hours <= OVERNIGHT_H:
            dep = 9 * 60.0
            return dep, dep + hours * 60, 16 * 60 + 30.0, "", 0
        arrive = 9 * 60 + 30.0                                      # reach the destination in the morning
        back = 19 * 60.0 if hours <= 20 else 16 * 60.0
        return arrive - hours * 60, arrive, back, "Overnight journey: it starts before the first day.", 0
    if hours <= HALT_H:
        dep = (7 * 60.0 if mode == "car" else 7 * 60.0 + 30)
        return dep, dep + hours * 60, _back_minutes(hours), "", 0
    halts = halts_each_way(mode, hours)                             # several driving days with night halts
    set_off = 7 * 60.0 if mode == "car" else 7 * 60.0 + 30          # each day starts in the morning (no night riding)
    arrive = set_off + hours / (halts + 1) * 60                     # the last day's drive ends the same afternoon
    return (set_off - halts * 1440, arrive, 6 * 60.0,
            f"Split over {halts + 1} days with {halts} night halt(s) each way; "
            "take a break every 2-3 hours.", halts)


def _back_minutes(hours: float) -> float:
    """Leave early enough to be home by about 21:00 (never later than 16:30, never before 06:00)."""
    return max(6 * 60.0, min(16 * 60 + 30.0, 21 * 60 - hours * 60))


def _opt(id_: str, label: str, mode: str, hours: float, price_total: float, travelers: int, stops: int = 0,
         note: str = "", extra_cost: float = 0.0) -> dict:
    depart, arrive, back, tnote, halts = _timing(mode, hours)
    last_leg = hours / (halts + 1)                                  # on the way back the last day's drive only
    after = halts if halts else int((back + hours * 60) // 1440)    # days after the trip ends until home
    leave = _leave_text(depart)
    full_note = " ".join(x for x in (tnote, note) if x)
    return {
        "id": id_, "label": f"{label}, {leave}" if leave else label, "stops": stops, "duration_h": round(hours, 1),
        "mode": mode, "depart_out": _hhmm(depart), "arrive_out": _hhmm(arrive),
        "depart_back": _hhmm(back), "arrive_back": _hhmm(back + last_leg * 60),
        "leave_days_before": max(0, math.ceil(-depart / 1440)) if depart < 0 else 0, "return_days_after": after,
        "price_pp": round_to((price_total + extra_cost) / max(1, travelers)), "estimated": True, "note": full_note,
    }


def options_for(mode: str, straight_km: float, o_cf: float, d_cf: float, travelers: int, days: int,
                countries: tuple, jitter: float) -> tuple[list[dict], str]:
    """Three options (ids best / early_late / one_stop, the same ids the strategy ladder uses) for a mode."""
    if mode not in _SPEED:
        raise ToolError(f"unknown travel mode '{mode}'", retryable=False)
    km, hours = _check(mode, straight_km, countries)
    cf = (o_cf + d_cf) / 2
    halts_n = halts_each_way(mode, hours)
    if mode in ("train", "bus"):
        rate = (2.6 if mode == "train" else 2.4) * (cf ** 0.7)          # INR per km one way per person
        base = max(300.0, rate * km) * 2 * jitter
        names = {
            "train": ("Train, AC chair car / 3-tier AC", "Train, AC 3-tier / second class",
                      "Train, sleeper or general class (cheapest)"),
            "bus": ("Volvo / AC sleeper bus", "AC semi-sleeper bus", "Ordinary state bus (cheapest)"),
        }[mode]
        mult = (1.0, 0.8, 0.55)
        options = [_opt(i, n, mode, hours * h, base * m, travelers, 0 if i != "one_stop" else 1)
                   for (i, n, m, h) in zip(("best", "early_late", "one_stop"), names, mult, (1.0, 1.05, 1.15))]
        return options, "round trip by " + mode + ", per person"
    rooms = math.ceil(travelers / 2)
    scale = 0.7 + 0.3 * cf
    halts = 2 * halts_n * HALT_NIGHT_INR * scale * rooms                  # nights on the way there and back
    if mode == "car":
        cars = math.ceil(travelers / 4)
        fuel_tolls = km * 2 * scale * cars
        rates = (13.0, 8.5, 6.5)                                        # cab with driver / self-drive / small car
        names = ("Cab with driver (outstation)", "Self-drive car, fuel + tolls",
                 "Self-drive small hatchback, fuel + tolls, share the driving")
        options = [_opt(i, f"{n} - {cars} car(s)", mode, hours, fuel_tolls * r, travelers, 0,
                        f"Includes {2 * halts_n} night halts." if halts_n else "", halts)
                   for (i, n, r) in zip(("best", "early_late", "one_stop"), names, rates)]
        return options, "round trip by car, cost shared per person"
    bikes = math.ceil(travelers / 2)                                    # one rider + one pillion per bike
    fuel = km * 2 * 3.2 * scale * bikes
    rentals = (1500.0, 700.0, 0.0)                                      # touring bike / commuter bike / own bike
    names = ("Rented touring bike (fuel + rental)", "Rented commuter bike (fuel + rental)", "Own bike, fuel only")
    rented_days = days + 2 * halts_n                                   # the days on the road count too
    options = [_opt(i, f"{n} - {bikes} bike(s)", mode, hours, fuel + r * rented_days * bikes * scale, travelers, 0,
                    (f"Includes {2 * halts_n} night halts. " if halts_n else "") +
                    "Avoid riding at night; carry a helmet for the pillion.", halts)
               for (i, n, r) in zip(("best", "early_late", "one_stop"), names, rentals)]
    return options, "round trip by bike, cost shared per person"
