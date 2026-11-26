"""Travel Document Assistant: a checklist for this trip, a passport validity check, reminders with a calendar
file, and a list of the traveller's own documents (names and dates only).

SAFETY RULES: never state whether a visa is needed (it depends on nationality and changes often): send the
traveller to official sources. Never ask for or keep a passport, ID, licence or card number.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone

from .. import guardrails

SCHENGEN = {"AT", "BE", "CH", "CZ", "DE", "DK", "ES", "FR", "GR", "HR", "HU", "IS", "IT", "NL", "NO", "PL", "PT",
            "SE"}
LINKS = {
    "iata": {"title": "IATA Travel Centre: passport, visa and health rules",
             "url": "https://www.iata.org/en/travel-centre/"},
    "eu": {"title": "European Union: travel documents for non-EU nationals",
           "url": "https://europa.eu/youreurope/citizens/travel/entry-exit/non-eu-nationals"},
    "passport_in": {"title": "Passport Seva (Government of India)", "url": "https://passportindia.gov.in/"},
    "airindia": {"title": "Air India: documents to carry",
                 "url": "https://www.airindia.com/in/en/travel-information/visa-documents/documents-required.html"},
    "rail": {"title": "Indian Railways: do's and don'ts for passengers",
             "url": "https://ser.indianrailways.gov.in/cris//uploads/files/"
                    "1724396632514-DO%20and%20Dont%20for%20passengers.pdf"},
}
DISCLAIMER = ("This is a planning aid, not legal advice. Rules change and depend on your nationality: confirm "
              "them with the official source, your carrier and the destination's embassy.")
KINDS = ("passport", "visa", "photo_id", "insurance", "ticket", "booking", "permit", "licence", "vehicle",
         "medical", "other")
MAX_ENTRIES = 50
NO_NUMBERS = "Please don't type passport, ID, licence or card numbers here. Save only names and dates."
_PASSPORT_NO = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][- ]?\d{7}(?![A-Za-z0-9])")
_LICENCE_NO = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}[- ]?\d{2}[- ]?\d{11}(?![A-Za-z0-9])")
_LABELLED_NO = re.compile(r"\b(passport|visa|licen[cs]e|aadhaar|aadhar|pan|voter|id)\s*(card\s*)?"
                          r"(no\.?|number|num|#)\s*(is|:|=|-)?\s*(?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]{5,}", re.I)


# ---------------------------------------------------------------- checklist
def _c(id_: str, title: str, detail: str, level: str = "advised", link: str = "") -> dict:
    return {"id": id_, "title": title, "detail": detail, "level": level, "link": LINKS.get(link)}


def _journey_docs(mode: str, label: str, indian: bool) -> list[dict]:
    out = []
    if mode == "flight":
        out.append(_c("photo-id", "Photo ID for every traveller",
                      "An original government photo ID with the same name as the ticket. Air India accepts "
                      "DigiLocker copies at Indian airports; check your own airline's list, including for children."
                      if indian else "Carry the ID your airline asks for, with the same name as the ticket.",
                      "required", "airindia" if indian else ""))
    elif mode in ("train", "ground") and indian:
        out.append(_c("rail-id", "Original photo ID on the train",
                      "In reserved coaches carry the original ID. If a Tatkal ticket names an ID, carry that one.",
                      "required", "rail"))
    elif mode in ("train", "ground", "bus"):
        out.append(_c("photo-id", "Ticket and photo ID", "Operators commonly ask for both.", "advised"))
    if mode in ("car", "bike"):
        if mode == "car" and "driver" in label.lower():
            out.append(_c("photo-id", "Photo ID and the cab booking",
                          "The driver and vehicle papers are the operator's job.", "advised"))
            return out
        rented = "rented" in label.lower() or "self-drive" in label.lower()
        out.append(_c("driving-licence", "Driving licence for this class of vehicle",
                      "Everyone who will drive or ride needs one.", "required"))
        vehicle = ("Vehicle registration (RC), insurance certificate and pollution certificate (PUC)" if indian
                   else "Vehicle registration and insurance papers")
        detail = ("For a rented vehicle, get these or copies from the rental firm, with the rental agreement. "
                  if rented else "")
        if indian:
            detail += "Copies in the government's DigiLocker or mParivahan apps are widely accepted."
        out.append(_c("vehicle-papers", vehicle, detail.strip(), "required"))
        if mode == "bike":
            out.append(_c("helmet", "Helmets for rider and pillion", "Wear them for the whole journey.", "required"))
    return out


def checklist(constraints: dict, flight_sel: dict | None, origin_cc: str, dest_cc: str) -> list[dict]:
    mode = (flight_sel or {}).get("mode") or constraints.get("travel_mode") or "flight"
    label = (flight_sel or {}).get("label", "")
    international = bool(origin_cc and dest_cc and origin_cc != dest_cc)
    items: list[dict] = []
    if international:
        passport_link = "eu" if dest_cc in SCHENGEN else "iata"
        items += [
            _c("passport", "Passport valid long enough",
               "Use the passport check below. Take one for every traveller, children included.", "required",
               passport_link),
            _c("visa", "Visa or entry permit",
               "Whether you need one depends on your nationality and changes often. Check an official source and "
               "apply early.", "check", "iata"),
            _c("onward", "Return ticket, place to stay and proof of funds", "Often asked for on arrival.", "check",
               "iata"),
            _c("insurance", "Travel and medical insurance",
               "Some visas require it. Keep the policy and its helpline with you.", "check"),
            _c("copies", "Copies of passport and visa",
               "Keep them apart from the originals, with a copy online that only you can open."),
        ]
    items += _journey_docs(mode, label, origin_cc == "IN" and not international)
    items += [
        _c("hotel-id", "Photo ID and booking for the hotel", "Hotels normally ask for ID at check-in."),
        _c("tickets", "Tickets and booking confirmations", "Save copies that open without internet."),
        _c("medical", "Prescriptions and health details",
           "Carry prescriptions for your medicines, and a note of allergies and an emergency contact."),
    ]
    if dest_cc == "IN":
        items.append(_c("permits", "Local permits, if your route needs them",
                        "Some border areas and islands need a permit. Check the official tourism site for the "
                        "places on your route.", "check"))
        if not international:
            items.append(_c("foreign-nationals", "Travellers who are not Indian citizens",
                            "Carry your passport and Indian visa, also on trips within India.", "check", "iata"))
    return items


# ---------------------------------------------------------------- passport
def add_months(d: date, months: int) -> date:
    year, month = divmod(d.month - 1 + months, 12)
    year, month = d.year + year, month + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _nice(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def passport_check(expiry: date, trip_start: date, trip_end: date, today: date, origin_cc: str, dest_cc: str,
                   issued: date | None = None) -> dict:
    """Compare a passport's dates with the trip. Status: problem | check | ok | not_needed."""
    international = bool(origin_cc and dest_cc and origin_cc != dest_cc)
    if not international:
        message = ("This is a domestic trip, so it does not normally need a passport (foreign nationals should "
                   "carry theirs).")
        expired = expiry < today
        if expired:
            message += " Your passport has expired: renew it before any trip abroad."
        return {"status": "check" if expired else "not_needed", "messages": [message], "links": []}
    schengen = dest_cc in SCHENGEN
    links = [LINKS["eu" if schengen else "iata"]] + ([LINKS["passport_in"]] if origin_cc == "IN" else [])
    problems, checks, good = [], [], []
    if issued and issued > today:
        problems.append("The issue date is in the future: check what you entered.")
    if expiry < today:
        problems.append(f"This passport expired on {_nice(expiry)}. Renew it before you travel.")
    elif expiry < trip_end:
        problems.append(f"It expires on {_nice(expiry)}, before your trip ends on {_nice(trip_end)}. Renew it.")
    elif schengen:
        needed = add_months(trip_end, 3)
        if expiry < needed:
            problems.append(f"The Schengen rule for non-EU nationals needs it to be valid until at least "
                            f"{_nice(needed)}, 3 months after you leave. Yours expires on {_nice(expiry)}.")
        else:
            good.append(f"It is valid for at least 3 months after you leave (needed until {_nice(needed)}).")
        if issued:
            if add_months(issued, 120) <= trip_start:
                problems.append("The Schengen rule also needs it to have been issued less than 10 years before "
                                "the day you arrive. Yours is older.")
            else:
                good.append("It was issued less than 10 years before you arrive.")
        else:
            checks.append("Also check the issue date: it must be less than 10 years before the day you arrive.")
    else:
        needed = add_months(trip_end, 6)
        if expiry < needed:
            checks.append(f"It has less than 6 months left after your trip (until {_nice(expiry)}). Many "
                          "countries require 6 months, others less. Check this destination's rule; if in doubt, "
                          "renew.")
        else:
            good.append("It has at least 6 months left after your trip, a common requirement. Still check this "
                        "destination's own rule.")
    status = "problem" if problems else "check" if checks else "ok"
    return {"status": status, "messages": problems + checks + good, "links": links}


# ---------------------------------------------------------------- own documents
def holds_document_number(text: str) -> bool:
    return bool(guardrails._sensitive(text) or _PASSPORT_NO.search(text) or _LICENCE_NO.search(text)
                or _LABELLED_NO.search(text))


def parse_date(value, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{name} must be a date like 2027-03-31")
    if not 1990 <= parsed.year <= 2100:
        raise ValueError(f"{name} is out of range")
    return parsed


def _text(value, limit: int) -> str:
    return " ".join(guardrails._CTRL.sub(" ", str(value or "")).split())[:limit]


def clean_entry(raw: dict) -> dict:
    """Validate one of the traveller's own document entries. Raises ValueError with a message for the traveller."""
    if not isinstance(raw, dict):
        raise ValueError("send the document as a JSON object")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError("choose a document type: " + ", ".join(KINDS))
    full = " ".join(str(raw.get(k) or "") for k in ("label", "note"))
    if holds_document_number(full):                       # checked before truncating, so nothing slips through
        raise ValueError(NO_NUMBERS)
    label, note = _text(raw.get("label"), 80), _text(raw.get("note"), 200)
    if not label:
        raise ValueError("give the document a short name")
    expiry = parse_date(raw.get("expiry"), "the expiry date")
    return {"kind": kind, "label": label, "note": note, "expiry": expiry.isoformat() if expiry else None,
            "done": raw.get("done") is True}


# ---------------------------------------------------------------- reminders
def reminders(constraints: dict, flight_sel: dict | None, entries: list[dict], today: date, home: date,
              leave: date, international: bool) -> list[dict]:
    """Dated to-dos for this trip. A preparation date that has already passed becomes "today" (marked overdue);
    nothing is suggested once the trip is over."""
    start = date.fromisoformat(constraints["start_date"])
    mode = (flight_sel or {}).get("mode")
    plan: list[tuple[date, str, str]] = []
    if international:
        plan += [(start - timedelta(days=90), "Check every passport's expiry date", "Renewals take time."),
                 (start - timedelta(days=60), "Check visa and entry rules", "Use an official source."),
                 (start - timedelta(days=14), "Arrange travel insurance, money and phone roaming", "")]
    if mode == "flight":
        plan.append((leave - timedelta(days=2), "Check in online", "Airlines open check-in at different times."))
    if mode in ("car", "bike"):
        plan.append((leave - timedelta(days=7), "Check licence and vehicle papers; service the vehicle", ""))
    plan += [(leave - timedelta(days=7), "Make sure you have enough medicines", ""),
             (leave - timedelta(days=1), "Download tickets, bookings and ID copies", "They should open offline.")]
    out = []
    if today <= home:
        for when, title, detail in plan:
            out.append({"date": max(when, today).isoformat(), "title": title, "detail": detail,
                        "overdue": when < today, "problem": False})
    for e in entries:
        if not e.get("expiry"):
            continue
        expiry = date.fromisoformat(e["expiry"])
        if expiry < today:
            out.append({"date": today.isoformat(), "title": f"{e['label']} has expired",
                        "detail": f"It expired on {_nice(expiry)}.", "overdue": True, "problem": True})
        elif today <= home and expiry < home:
            out.append({"date": today.isoformat(), "title": f"{e['label']} expires before you are home",
                        "detail": f"It expires on {_nice(expiry)}.", "overdue": False, "problem": True})
        else:
            out.append({"date": max(today, expiry - timedelta(days=30)).isoformat(),
                        "title": f"{e['label']} expires on {_nice(expiry)}", "detail": "Renew it in good time.",
                        "overdue": False, "problem": False})
    return sorted(out, key=lambda r: (not r["problem"], r["date"]))


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
