"""Read hotel prices out of a Google Hotels results page that Tavily Extract turned into text.

Each hotel is a heading followed by a price card:

    ## Radisson Hotel Jaipur City Center
    [GREAT DEAL$126 $126 nightly $599 total 4 nights with taxes + fees $126 43% less than usual]()
    [4.6 (16.6K) 5 4 3 2 1 People often mention ...]() ... Amenities for Radisson ..., a 4-star hotel.

``$599 total 4 nights with taxes + fees`` is the whole stay, taxes included. Pure text in, plain data out: no network,
no guessing. A hotel without a readable price card is skipped.
"""
from __future__ import annotations

import re

_HEAD = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
_CARD = re.compile(r"(?P<cur>US\$|[$€£₹])(?P<night>\d[\d,]*)\s+(?P=cur)(?P=night)\s+nightly"
                   r"(?:\s+(?P=cur)(?P<total>\d[\d,]*)\s+total\s+(?P<n>\d+)\s+nights?)?")
_RATING = re.compile(r"\[(\d\.\d)\s+\(([\d.,]+)(K?)\)")
_STARS = re.compile(r"\b(\d)-star hotel")
_STAY = re.compile(r"\b([A-Z][a-z]{2} \d{1,2} – (?:[A-Z][a-z]{2} )?\d{1,2})\b")
_SYMBOL = {"₹": "INR", "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP"}


def _int(text: str) -> int:
    return int(text.replace(",", ""))


def _reviews(number: str, k: str) -> int | None:
    try:
        return int(round(float(number.replace(",", "")) * (1000 if k else 1)))
    except ValueError:
        return None


def stay_label(checkin, checkout) -> str:
    """How Google prints the dates on a card: 'Dec 25 – 29', or 'Dec 30 – Jan 2' across a month end."""
    if checkin.month == checkout.month:
        return f"{checkin:%b} {checkin.day} – {checkout.day}"
    return f"{checkin:%b} {checkin.day} – {checkout:%b} {checkout.day}"


def parse_google_hotels(text: str) -> dict:
    """-> {"hotels": [...], "stays": [...]}. Each hotel: name, currency, nightly (price per night, before taxes),
    total (whole stay with taxes and fees, or None), nights (int or None), rating (float or None), reviews (int or
    None), stars (int or None). ``stays`` are the date ranges printed on the cards, e.g. ['Dec 25 – 29']."""
    text = text or ""
    heads = list(_HEAD.finditer(text))
    hotels, seen, stays = [], set(), []
    for i, h in enumerate(heads):
        section = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        card = _CARD.search(section)
        name = h.group(1).strip()
        if not card or name in seen:
            continue
        seen.add(name)
        rating = _RATING.search(section)
        stars = _STARS.search(section)
        stay = _STAY.search(section[card.start(): card.end() + 160])
        if stay and stay.group(1) not in stays:
            stays.append(stay.group(1))
        hotels.append({
            "name": name, "currency": _SYMBOL[card.group("cur")], "nightly": _int(card.group("night")),
            "total": _int(card.group("total")) if card.group("total") else None,
            "nights": int(card.group("n")) if card.group("n") else None,
            "rating": float(rating.group(1)) if rating else None,
            "reviews": _reviews(rating.group(2), rating.group(3)) if rating else None,
            "stars": int(stars.group(1)) if stars else None,
        })
    return {"hotels": hotels, "stays": stays}
