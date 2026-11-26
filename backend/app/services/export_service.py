"""Everything a traveller can take away: the plan as readable text, trip reminders as a calendar file (.ics)
and expenses as a spreadsheet file (.csv)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from app.core.utils import fmt_inr
from app.data.curated_destinations import place_name


# ---------------------------------------------------------------- the plan as text
def short_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b}"


def price_tag(block: dict | None) -> str:
    """'live: Google Flights via Tavily, fetched 25 Nov 10:45 UTC' for a live result, else 'estimated'."""
    block = block or {}
    if block.get("estimated", True):
        return "estimated"
    when = ""
    try:
        when = ", fetched " + datetime.fromisoformat(block["fetched_at"]).strftime("%d %b %H:%M UTC")
    except (KeyError, TypeError, ValueError):
        pass
    return f"live: {block.get('source', 'web')}{when}"


def travel_heading(sel: dict | None) -> str:
    mode = (sel or {}).get("mode")
    return {"ground": "Train/bus", "train": "Train", "bus": "Bus", "car": "Car", "bike": "Bike"}.get(mode, "Flight")


def _fmt_day(d: dict) -> str:
    dt = date.fromisoformat(d["date"])
    w = d.get("weather")
    wx = f" - {w['tmax']}°/{w['tmin']}°C, {w['precip_prob']}% rain{' (RAINY)' if w['rainy'] else ''}" if w else ""
    return f"**Day {d['day']} - {dt.strftime('%a %d %b')} ({d['kind']}){wx}**"


def render_summary(state: dict) -> str:
    c = state["constraints"]
    it, br = state.get("itinerary"), state.get("budget_report")
    if not it or not br:
        return ""
    name = place_name(c, "destination")
    fl = (state.get("flight") or {}).get("selected")
    ho = (state.get("hotel") or {}).get("selected")
    L = [f"# {c['days']}-day trip to {name} ({it['start_date']} to {it['end_date']})",
         f"{c['travelers']} traveler(s) from {place_name(c, 'origin')} - strategy: {state.get('strategy', 'normal')}", ""]
    heading = travel_heading(fl)
    L.append(f"## {heading} ({price_tag(state.get('flight'))})")
    L.append(f"{fl['label']}: out {fl['depart_out']} (arrive {fl['arrive_out']}), back {fl['depart_back']} - "
             f"{fmt_inr(fl['price_pp'])} per person round trip" if fl else "Not available (tool failure).")
    if fl and fl.get("note"):
        L.append(fl["note"])
    journey = (state.get("flight") or {}).get("journey") if fl else None
    if journey and journey["extra_days"]:
        L.append(f"Leave home on {short_date(journey['leave_date'])}; back home on {short_date(journey['home_date'])}.")
    if journey and journey["warning"]:
        L.append(journey["warning"])
    emissions = (state.get("flight") or {}).get("footprint") if fl else None
    if emissions:
        L.append(f"Travel emissions, there and back: about {emissions['kg_pp']:g} kg CO2e per person (estimate).")
    L.append(f"\n## Hotel ({price_tag(state.get('hotel'))})")
    L.append(f"{ho['label']}: {fmt_inr(ho['price_night_per_room'])}/room/night x {ho['nights']} nights x "
             f"{ho['rooms']} room(s)" if ho else "Not available (tool failure).")
    if ho and (state.get("hotel") or {}).get("fx_note"):
        L.append(state["hotel"]["fx_note"])
    wsrc = (state.get("weather") or {}).get("source")
    L.append(f"\n## Day by day (weather: {wsrc or 'unavailable'})")
    for d in it["days"]:
        L.append(_fmt_day(d))
        for x in d["items"]:
            cost = f" - {fmt_inr(x['cost_total'])}" if x["type"] == "activity" and x["cost_total"] else ""
            L.append(f"- {x['start']}-{x['end']} {x['name']}{cost}")
        for n in d["notes"]:
            L.append(f"  - {n}")
    acts = state.get("activities") or {}
    top = acts.get("top_sights") or []
    if top:
        planned = {x["name"]: f"Day {d['day']} {x['start']}" for d in it["days"] for x in d["items"]
                   if x["type"] == "activity"}
        L.append("\n## Top sights (most prominent first)")
        for t in top:
            extra = f" - planned {planned[t['name']]}" if t["name"] in planned else ""
            L.append(f"{t['rank']}. {t['name']} ({t['label']}): best {t['best_time'][0].lower() + t['best_time'][1:]}"
                     + (f". {t['season']}" if t.get("season") else "") + extra)
        L.append(f"  - {acts.get('top_sights_note', '')}")
    dn = acts.get("dining") or {}
    if dn.get("veg") or dn.get("nonveg") or dn.get("other"):
        L.append("\n## Where to eat")
        for title, key in (("Vegetarian", "veg"), ("Non-vegetarian", "nonveg"), ("Restaurants (menu not specified)" if not (dn.get("veg") or dn.get("nonveg")) else "More places (menu not specified)", "other")):
            if dn.get(key):
                L.append(f"**{title}**")
                for i, r in enumerate(dn[key], 1):
                    cu = f" - {r['cuisine']}" if r.get("cuisine") else ""
                    L.append(f"{i}. {r['name']}{cu}: {r['hours']}. Best: {r['best_time']}")
        L.append(f"  - {dn.get('note', '')}")
    if state.get("group_report"):
        L.append("\n## Group fit")
        for m in state["group_report"]:
            wants = f" (likes {', '.join(m['likes'])})" if m["likes"] else ""
            L.append(f"- {m['name']}{wants}: {len(m['matched'])} of {m['activities']} activities match"
                     + (f"; {len(m['conflicts'])} touch something they wanted to avoid" if m["conflicts"] else ""))
    L.append("\n## Budget (estimated)")
    for k, v in br["lines"].items():
        L.append(f"- {k.title()}: {fmt_inr(v)}")
    status = "OVER budget" if br["over_budget"] else "within budget"
    L.append(f"- **Total: {fmt_inr(br['total'])}** of {fmt_inr(br['budget'])} ({status}); "
             f"{fmt_inr(br['per_person'])} per person")
    alts = (state.get("alternatives") or {}).get("items") or []
    if alts and br["over_budget"]:
        L.append("\n## Other places to consider (estimated cheapest totals)")
        L += [f"- {a['name']}, {a['country']}: from about {fmt_inr(a['estimate_from'])}" for a in alts]
    if state.get("warnings"):
        L.append("\n## Warnings")
        L += [f"- {w}" for w in dict.fromkeys(state["warnings"])]
    live_flight, live_hotel = (bool((state.get(k) or {}).get("live") and (state.get(k) or {}).get("selected"))
                               for k in ("flight", "hotel"))
    if live_flight and live_hotel:
        L.append("\nFlight and hotel prices are live listings read from Google Flights and Google Hotels; they can "
                 "change and are not a booking. Activities and food are estimates.")
    elif live_flight or live_hotel:
        L.append(f"\nThe {'flight' if live_flight else 'hotel'} price is a live Google listing and can change; the "
                 f"{'hotel' if live_flight else heading.lower()} price is a synthetic ESTIMATE, as are activities and "
                 "food.")
    else:
        L.append(f"\n{heading} and hotel prices are synthetic ESTIMATES, not live fares.")
    if state.get("booking"):
        L.append(f"\n## Booking\n{state['booking']['booking_id']}: {state['booking']['status']}")
    return "\n".join(L)


# ---------------------------------------------------------------- calendar file (RFC 5545)
def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "")
            .replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Lines may be at most 75 bytes; a continuation line starts with a space. Never splits a character."""
    parts, current, size = [], "", 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        if size + width > (75 if not parts else 74):
            parts.append(current)
            current, size = "", 0
        current += ch
        size += width
    parts.append(current)
    return "\r\n ".join(parts)


def ics(thread_id: str, trip_name: str, items: list[dict], now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Multi-Agent Travel Planner//Trip reminders//EN",
             "CALSCALE:GREGORIAN"]
    for n, r in enumerate(items, 1):
        day = date.fromisoformat(r["date"])
        summary = f"{r['title']} ({trip_name})"
        lines += ["BEGIN:VEVENT", f"UID:{thread_id}-{n}@travel-planner", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_escape(summary)}"]
        if r.get("detail"):
            lines.append(f"DESCRIPTION:{_escape(r['detail'])}")
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(summary)}", "TRIGGER:PT9H",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def to_csv(entries: list[dict]) -> str:
    """The entries as CSV. A cell that a spreadsheet would run as a formula is prefixed with a quote."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(["date", "category", "amount_inr", "note"])
    for e in entries:
        note = e.get("note", "")
        if note[:1] in ("=", "+", "-", "@"):
            note = "'" + note
        writer.writerow([e["date"], e["category"], f"{e['amount']:.2f}", note])
    return buf.getvalue()
