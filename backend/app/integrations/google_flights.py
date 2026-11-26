"""Read live fares out of a Google Flights results page that a web-fetch provider (Tavily Extract) turned into text.

The page lists each flight as one line:

    * 5:10 PM 5:10 PM on Fri, Dec 25 –7:45 PM 7:45 PM on Fri, Dec 25  IndiGo  2 hr 35 min DEL ...  Nonstop  212 kg CO2e
      ... ₹40,702  round trip ...

and says near the top "Prices include required taxes + fees for 2 adults.". Nothing here calls the network: the
function takes text and returns plain data, so it is tested on a real saved page (tests/fixtures).

What it will NOT do: guess. A row it cannot read completely is skipped, a row without a price keeps ``price=None``,
and business / first class rows are marked so the caller can ignore them. The caller decides what to trust.
"""
from __future__ import annotations

import re

_TIME = r"\d{1,2}:\d{2}\s?[AP]M"
_DAY = r"[A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}"
_ROW = re.compile(
    rf"^\*\s+(?P<dep>{_TIME})\s+(?P=dep) on (?P<dday>{_DAY})\s+–\s?(?P<arr>{_TIME})(?:\+\d)?\s+(?P=arr)(?:\+\d)? on "
    rf"(?P<aday>{_DAY})\s+(?P<airline>.+?)\s{{2,}}(?P<dur>\d+ hr(?: \d+ min)?|\d+ min)\s+(?P<rest>.*)$")
_STOPS = re.compile(r"\b(Nonstop|(\d) stops?)\b")
_PRICE = re.compile(r"(?P<cur>US\$|[$€£₹])\s?(?P<amt>\d[\d,]*)(?:\s+(?P<kind>round trip|one way))?")
_ADULTS = re.compile(r"for (\d+) adults?", re.IGNORECASE)
_CURRENCY = re.compile(r"\bCurrency\s+([A-Z]{3})\b")
_SYMBOL = {"₹": "INR", "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP"}
_CABINS = ("Business", "First", "Premium economy")
_IATA = re.compile(r"\b[A-Z]{3}\b")
_ROUTE = re.compile(r"([A-Z]{3})\s.*?\s–\s?([A-Z]{3})\b")      # 'DEL Indira Gandhi ...  –GOI Goa Dabolim ...'


def _minutes(text: str) -> int:
    h = re.search(r"(\d+) hr", text)
    m = re.search(r"(\d+) min", text)
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def _clock(text: str) -> str:
    """'5:10 PM' -> '17:10'."""
    hh, mm = text.replace(" ", " ").replace("\xa0", " ").strip().split(":")
    mm, ap = mm[:2], mm[2:].strip().upper()
    h = int(hh) % 12 + (12 if ap == "PM" else 0)
    return f"{h:02d}:{mm}"


def _airline(text: str) -> str:
    """Google sometimes prints a codeshare as 'Air India Express Air India'; keep the first, longer name."""
    s = " ".join(text.split())
    for cut in range(len(s) - 1, 0, -1):
        if s[cut] == " ":
            head, rest = s[:cut], s[cut + 1:]
            if rest and head.startswith(rest):
                return head
    return s


def parse_google_flights(text: str) -> dict:
    """-> {"adults": int|None, "currency": "INR"|None, "flights": [...]}.

    Each flight: airline, depart (HH:MM), depart_day, arrive (HH:MM), arrive_day, duration_min, origin_code and
    dest_code (IATA), stops (int), via (list of IATA codes), price (int, in the page's currency, the TOTAL for all adults, or None), price_kind
    ('round trip' | 'one way' | None), currency, cabin ('economy' | 'business' | 'first' | 'premium economy').
    Rows that appear twice on the page are returned once.
    """
    text = text or ""
    adults = _ADULTS.search(text[text.find("Prices include"):] if "Prices include" in text else "")
    page_currency = _CURRENCY.search(text)
    flights, seen = [], set()
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        rest = m.group("rest")
        stops_m = _STOPS.search(rest)
        if not stops_m:
            continue
        stops = 0 if stops_m.group(1) == "Nonstop" else int(stops_m.group(2))
        tail = rest[stops_m.end():]
        layover = tail.split("kg CO2e")[0] if stops else ""
        # The layover text starts with its own duration and airport; the origin and destination codes sit before
        # 'Nonstop' / 'N stop', so only codes after it are stops.
        via = list(dict.fromkeys(_IATA.findall(layover)))
        route = _ROUTE.match(rest)
        price_m = _PRICE.search(rest)
        cabin = "economy"
        for name in _CABINS:
            if re.search(rf"\b{name}(?: Class)?\b", rest):
                cabin = name.lower()
                break
        flight = {
            "airline": _airline(m.group("airline")),
            "depart": _clock(m.group("dep")), "depart_day": m.group("dday"),
            "arrive": _clock(m.group("arr")), "arrive_day": m.group("aday"),
            "duration_min": _minutes(m.group("dur")),
            "origin_code": route.group(1) if route else None, "dest_code": route.group(2) if route else None,
            "stops": stops, "via": via,
            "price": int(price_m.group("amt").replace(",", "")) if price_m else None,
            "price_kind": price_m.group("kind") if price_m else None,
            "currency": _SYMBOL.get(price_m.group("cur")) if price_m else None,
            "cabin": cabin,
        }
        key = tuple(flight[k] for k in ("airline", "depart", "arrive", "stops", "price", "cabin"))
        if key in seen:
            continue
        seen.add(key)
        flights.append(flight)
    return {"adults": int(adults.group(1)) if adults else None,
            "currency": page_currency.group(1) if page_currency else None,
            "flights": flights}


def economy_with_price(parsed: dict) -> list[dict]:
    """Economy rows that carry a price, cheapest first (ties: fewer stops, then shorter)."""
    rows = [f for f in parsed.get("flights", []) if f["cabin"] == "economy" and f["price"]]
    return sorted(rows, key=lambda f: (f["price"], f["stops"], f["duration_min"]))
