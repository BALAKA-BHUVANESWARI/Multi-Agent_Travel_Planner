"""Merge step: build the day-by-day itinerary (pure code, no LLM).

Day shapes
  arrival   : arrive -> check-in 15:00 -> optional afternoon (if landing by 11:00) -> evening
  full      : morning 09:30 / afternoon 14:00 / evening 18:30 (relaxed pace: morning + evening)
  departure : check-out 09:00 -> optional morning activity -> airport 3h before the flight
              (1h before a train/bus for short ground trips)

Rain: days at/above the rain threshold are filled first and prefer indoor places. If the
best choice for a slot is outdoor, it is *swapped* for the best indoor option (or a
generic indoor block) and the swap is recorded.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core import config
from app.core.utils import to_hhmm, to_minutes
from app.data.curated_destinations import GENERIC_INDOOR, place_name

MORNING = ("morning", 9 * 60 + 30, 13 * 60)
AFTERNOON = ("afternoon", 14 * 60, 18 * 60)
EVENING = ("evening", 18 * 60 + 30, 22 * 60 + 30)
MIN_SLOT_MIN = 45
RAIN_NOTE = "Rain: nothing planned matches your interest in "     # how the warning about a lost interest begins
LEAD_FLIGHT, LEAD_GROUND, LEAD_ROAD = 180, 60, 0   # minutes at the airport / station before departing


def _slots_for_day(i: int, n: int, arr: int, dep: int, pace: str,
                   lead: int = LEAD_FLIGHT) -> list[tuple[str, int, int]]:
    if i == 0:
        slots = []
        if arr <= 11 * 60:
            slots.append(("afternoon", 15 * 60 + 30, 18 * 60))
        if arr <= 17 * 60 + 30:                                # check-in ends 90 min after arriving: never overlap it
            slots.append((EVENING[0], max(EVENING[1], arr + 90), EVENING[2]))
        return slots
    if i == n - 1:
        limit = dep - (lead + 30)
        if limit - MORNING[1] >= 60:
            return [("morning", MORNING[1], min(MORNING[2], limit))]
        return []
    return [MORNING, EVENING] if pace == "relaxed" else [MORNING, AFTERNOON, EVENING]


def _item(kind: str, name: str, start: int, end: int, **extra) -> dict:
    return {"type": kind, "name": name, "start": to_hhmm(start), "end": to_hhmm(end),
            "start_min": start, "end_min": end, **extra}


def _lost_to_rain(wanted: list[str], placed: dict, swaps: list[dict], candidates: list[dict],
                  rainy_days: int, n: int) -> str | None:
    """A warning when the rain swaps left an interest the traveller named with nothing in the plan."""
    served = {t for items in placed.values() for it in items for t in it.get("tags", [])}
    tags = {c["name"]: c.get("tags", []) for c in candidates}
    lost, names = [], []
    for pref in wanted:
        replaced = [s["from"] for s in swaps if pref in tags.get(s["from"], [])]
        if pref not in served and replaced:
            lost.append(pref)
            names += replaced
    if not lost:
        return None
    when = f"all {n} days" if rainy_days == n else f"{rainy_days} of {n} days"
    return (f"{RAIN_NOTE}{', '.join(lost)}. Rain is expected on {when}, so outdoor places such as "
            f"{' and '.join(list(dict.fromkeys(names))[:2])} were replaced with indoor plans. For a better chance, "
            "try drier dates or check the forecast closer to the trip.")


def build_itinerary(constraints: dict, flight_sel: dict | None, hotel_sel: dict | None,
                    weather: dict | None, candidates: list[dict]) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    n = constraints["days"]
    travelers = constraints["travelers"]
    start = date.fromisoformat(constraints["start_date"])
    dest = place_name(constraints, "destination")
    tmode = (flight_sel or {}).get("mode")
    ground = tmode in ("ground", "train", "bus")
    road = tmode in ("car", "bike")
    lead = LEAD_ROAD if road else (LEAD_GROUND if ground else LEAD_FLIGHT)

    if flight_sel:
        arr = to_minutes(flight_sel["arrive_out"])
        dep = to_minutes(flight_sel["depart_back"])
    else:
        arr, dep = 12 * 60, 17 * 60
        warnings.append("No flight data: itinerary assumes arrival around 12:00 and departure around 17:00.")

    wx = {d["date"]: d for d in (weather or {}).get("days", [])}
    if not wx:
        warnings.append("No weather data: rain-day swaps were not applied.")

    dates = [start + timedelta(days=i) for i in range(n)]
    slots = {i: _slots_for_day(i, n, arr, dep, constraints.get("pace", "normal"), lead) for i in range(n)}
    rainy = {i: bool(wx.get(dates[i].isoformat(), {}).get("rainy")) for i in range(n)}
    order = [i for i in range(n) if rainy[i]] + [i for i in range(n) if not rainy[i]]

    used: set[str] = set()
    placed: dict[int, list[dict]] = {i: [] for i in range(n)}
    swaps: list[dict] = []

    def compat(slot: str) -> list[dict]:
        """Exact slot matches first, then adjacent-slot places as a fallback (e.g. an outdoor
        afternoon market works in the evening) so days are not left empty."""
        free = [c for c in candidates if c["id"] not in used]
        primary = [c for c in free if c["slot"] in ("any", slot)]
        fallback = [c for c in free if c not in primary and (
            (slot == "afternoon" and c["slot"] == "morning")
            or (slot == "morning" and c["slot"] == "afternoon")
            or (slot == "evening" and c["slot"] == "afternoon" and c["outdoor"]))]
        return primary + fallback

    for i in order:
        for slot, w_start, w_end in slots[i]:
            if w_end - w_start < MIN_SLOT_MIN:
                continue
            options = compat(slot)
            chosen = options[0] if options else None
            note = None
            if chosen and rainy[i] and chosen["outdoor"]:
                indoor = next((c for c in options if not c["outdoor"]), None)
                if indoor:
                    note = f"Rain expected: swapped '{chosen['name']}' for indoor '{indoor['name']}'."
                    swaps.append({"day": i + 1, "from": chosen["name"], "to": indoor["name"]})
                    chosen = indoor
                else:
                    note = f"Rain expected: replaced '{chosen['name']}' with a flexible indoor block."
                    swaps.append({"day": i + 1, "from": chosen["name"], "to": GENERIC_INDOOR["name"]})
                    chosen = dict(GENERIC_INDOOR)
            if chosen is None:
                continue
            if chosen["id"] != GENERIC_INDOOR["id"]:
                used.add(chosen["id"])
            dur = min(int(chosen["hours"] * 60), w_end - w_start)
            placed[i].append(_item(
                "activity", chosen["name"], w_start, w_start + dur, id=chosen["id"], slot=slot,
                cost_pp=chosen["cost"], cost_total=chosen["cost"] * travelers, outdoor=chosen["outdoor"],
                tags=chosen.get("tags", []), desc=chosen.get("desc", ""), note=note,
                **({"lat": chosen["lat"], "lon": chosen["lon"]} if "lat" in chosen and "lon" in chosen else {})))

    days = []
    for i in range(n):
        items = list(placed[i])
        kind = "arrival" if i == 0 else ("departure" if i == n - 1 else "full")
        flabel = flight_sel["label"] if flight_sel else "flight (no data)"
        if i == 0:
            items.append(_item("transport", f"Arrive in {dest} ({flabel})", arr, arr + 60, leg="arrival"))
            items.append(_item("hotel", f"Check in: {hotel_sel['label'] if hotel_sel else 'hotel (no data)'}",
                               max(15 * 60, arr + 60), max(15 * 60, arr + 60) + 30))
        if i == n - 1:
            items.append(_item("hotel", "Check out", 9 * 60, 9 * 60 + 30))
            home = (f"Check out and {'drive' if tmode == 'car' else 'ride'} home" if road else
                    "Travel to the station or bus stand and head home" if ground
                    else "Airport transfer and flight home")
            items.append(_item("transport", home, dep - lead, dep, leg="departure"))
        items.sort(key=lambda x: (x["start_min"], x["end_min"]))
        w = wx.get(dates[i].isoformat())
        notes = [it["note"] for it in items if it.get("note")]
        n_act = sum(1 for it in items if it["type"] == "activity")
        if n_act == 0 and kind == "full":
            warnings.append(f"Day {i + 1} has no activities (not enough matching places for your budget tier).")
        days.append({"day": i + 1, "date": dates[i].isoformat(), "kind": kind, "weather": w,
                     "rainy": rainy[i], "items": items, "notes": notes})
    dropped = _lost_to_rain(constraints.get("preferences") or [], placed, swaps, candidates, sum(rainy.values()), n)
    if dropped:
        warnings.append(dropped)
    itin = {"start_date": dates[0].isoformat(), "end_date": dates[-1].isoformat(), "nights": n - 1,
            "destination": constraints["destination"], "days": days, "swaps": swaps}
    return itin, warnings


def count_activities_per_day(itin: dict) -> list[int]:
    return [sum(1 for it in d["items"] if it["type"] == "activity") for d in itin["days"]]


def max_per_day() -> int:
    return config.MAX_ACTIVITIES_PER_DAY
