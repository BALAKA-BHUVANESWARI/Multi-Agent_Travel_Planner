"""Start dates written with numbers ("20/12/2026", "2026-12-20") or as words ("Christmas", "tomorrow").

Numbers are read day first, as in India: 05/12/2026 is 5 December. Only dates that include a year are read, so
that "5N/6D" or "24/7" is never taken for a date. Pure text in, plain data out.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

_ISO = re.compile(r"(?<![\d./-])(20\d\d)([-/.])(\d{1,2})\2(\d{1,2})(?![\d/-]|\.\d)")
_DAY_FIRST = re.compile(r"(?<![\d./-])(\d{1,2})([-/.])(\d{1,2})\2(20\d\d)(?![\d/-]|\.\d)")
_SHORT_YEAR = re.compile(r"(?<![\d./-])(\d{1,2})(/)(\d{1,2})/(\d\d)(?![\d/-]|\.\d)")
# "Christmas Island" is a place and a "Christmas market" is a thing to see: neither says when the trip starts.
_CHRISTMAS = re.compile(r"\b(?:christmas|x-?mas)\b(?!\s+(?:island|markets?)\b)(?:[\s-]+(eve|day)\b)?", re.I)
_TOMORROW = re.compile(r"\b(day\s+after\s+)?tomorrow\b", re.I)


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """Put a comma where each date was, so its digits and words are not read as anything else."""
    for start, end in sorted(spans, reverse=True):
        text = f"{text[:start]} , {text[end:]}"
    return text


def take_numeric_date(text: str) -> tuple[str, date | None, str | None]:
    """(text without numeric dates, the first real date, the first one that is not a real date)."""
    found: list[tuple[int, int, int, int, int]] = []                 # start, end, year, month, day
    for m in _ISO.finditer(text):
        found.append((m.start(), m.end(), int(m.group(1)), int(m.group(3)), int(m.group(4))))
    for pattern, century in ((_DAY_FIRST, 0), (_SHORT_YEAR, 2000)):
        for m in pattern.finditer(text):
            found.append((m.start(), m.end(), century + int(m.group(4)), int(m.group(3)), int(m.group(1))))
    good = bad = None
    for start, end, year, month, day in sorted(found):
        try:
            value = date(year, month, day)
        except ValueError:
            bad = bad or text[start:end]
            continue
        good = good or value
    return _blank(text, [(f[0], f[1]) for f in found]), good, bad


def take_named_days(text: str) -> tuple[str, int | None, int | None]:
    """(text without those words, day of December if Christmas is named, days from today if 'tomorrow' is said)."""
    spans: list[tuple[int, int]] = []
    christmas = ahead = None
    for m in _CHRISTMAS.finditer(text):
        spans.append(m.span())
        if christmas is None:
            christmas = 24 if (m.group(1) or "").lower() == "eve" else 25
    for m in _TOMORROW.finditer(text):
        spans.append(m.span())
        if ahead is None:
            ahead = 2 if m.group(1) else 1
    return _blank(text, spans), christmas, ahead


def next_christmas(day: int, today: date) -> date:
    this_year = date(today.year, 12, day)
    return this_year if this_year > today else date(today.year + 1, 12, day)


def days_from(today: date, ahead: int) -> date:
    return today + timedelta(days=ahead)
