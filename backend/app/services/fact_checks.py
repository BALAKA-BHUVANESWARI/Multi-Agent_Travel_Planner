"""Automatic checks for made-up facts in what an AI model returned. They only record and flag.

Nothing here changes what the traveller sees, and nothing here is proof: a flag means "this was not found in the
plan (or in the typed request)", which can be a false alarm. The dashboard lets the owner mark each one.

What is compared:
* an AI summary or chat answer: rupee amounts, dates, day and night counts, and place names, against the saved plan;
* request values an AI filled in (places, days, budget, interests), against the words the traveller typed;
* the AI's ranking of activities: ids that were not on the list it was given.

Limits: money written without ₹, Rs, INR or "rupees" is not checked; a made-up one-word name is only caught when it
is a known town or city; weekday names, times and distances are not checked.

Every public ``record_*`` function does nothing outside a recorded request and never raises: recording must not
break or change a plan. The text and the flagged examples are kept only with RECORD_DETAILS=1.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Callable

from app.core import config
from app.data import gazetteer
from app.data.curated_destinations import ALIASES
from app.observability import recorder as observe
from app.services import request_parser as parser
from app.services.geo_service import _one_slip

MAX_FLAGS = 20                       # examples kept for one check
MAX_SENTENCE = 200
KINDS = ("amounts", "dates", "day_counts", "places", "days", "budget", "preferences", "unknown_ids")

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
           "nov": 11, "dec": 12}
_MONTH = (r"(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\b|"
          r"(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\b\.?)")
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})(?:,?\s+(20\d\d))?", re.I)
# the month first needs its capital letter, so that "you may 2..." is not a date
_MONTH_DAY = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?![,.:]\d|\s*%)(?:,?\s+(20\d\d))?")

_UNIT = r"(k|thousand|lakhs?|lacs?|crores?)\b"
_MONEY = (re.compile(rf"(?:₹|\brs\.?|\binr\b|\brupees?\b)\s*(\d[\d,]*(?:\.\d+)?)(?:\s*{_UNIT})?", re.I),
          re.compile(rf"(?<![\d.,₹])(\d[\d,]*(?:\.\d+)?)(?:\s*{_UNIT})?\s*(?:rupees?\b|inr\b)", re.I))
_NUMBER = re.compile(rf"(\d[\d,]*(?:\.\d+)?)(?:\s*{_UNIT})?", re.I)

_WORD_NUMBERS = {w: n for n, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen".split(), 1)}
_NUM = r"(\d{1,2}|" + "|".join(list(_WORD_NUMBERS)[1:]) + r")"         # "one day you could..." is not a count
_COUNT = re.compile(rf"\b{_NUM}(?:\s*|-)(days?|nights?)\b", re.I)
_DAY_N = re.compile(r"\bday\s+(\d{1,2})\b", re.I)

# a run of capitalised words, which may have a short joining word inside ("Fort of Aguada", "Basilica de Bom")
_CAP = r"[A-ZÀ-Þ][A-Za-zÀ-ɏ'’]*"
_PHRASE = re.compile(rf"{_CAP}(?:(?:[ -]|\s(?:of|de|del|da|la|le|di|du|the|ka|ki)\s)(?:(?:the|de|la)\s)?{_CAP})+")
_ORDINARY = set("""a an the on in at for from to of and or but your you our we i it its this that these those there here
day days night nights trip plan tour visit enjoy explore start head spend take try see go stay then next after before
first last final morning afternoon evening today tomorrow arrive arrival depart departure return back total budget cost
price estimated about around roughly nothing note yes no if so as with by each per also please remember with
monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september
october november december google maps flights hotels mock openstreetmap wikivoyage wikipedia open meteo
source sources""".split())


# Words (matched at the start of a word) that count as the traveller asking for an interest. Wider than the request
# reader's own list on purpose: the AI is only asked for interests when that list found none.
_INTEREST_WORDS = {
    "beach": "beach sea sand coast island ocean swim shore",
    "food": "food eat cuisine restaurant cook dish tast culinary",
    "culture": "cultur art museum craft temple galler festival tradition architecture music dance local",
    "history": "histor heritage fort palace monument ruin ancient castle old",
    "adventure": "adventur trek hik raft paraglid thrill adrenaline camp climb surf scuba diving bungee zip ski sport",
    "nature": "natur scenic waterfall lake backwater mountain wildlife hill forest jungle safari garden valley "
              "outdoor snow green",
    "nightlife": "nightlife night party parties pub club bar",
    "shopping": "shop market bazaar souvenir mall buy",
    "relaxation": "relax peace spa chill laid quiet calm unwind slow rest wellness",
    "spiritual": "temple spirit church monaster mosque shrine pilgrim ghat ashram yoga meditat gurdwara pray darshan",
    "family": "kid child family son daughter toddler baby parent",
}
# whole words only, so that "art" does not match "start" or "artificial" and "bar" does not match "barely"
_SHORT = {"art", "eat", "sea", "old", "bar", "spa", "ski", "zip", "son", "pub", "buy", "rest", "club", "mall",
          "sand", "ghat", "fort", "hill", "lake", "camp", "pray", "local", "night", "sport", "green", "slow"}


def _asked_for(interest: str, text: str) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{w}s?\b" if w in _SHORT else rf"\b{w}", low)
               for w in _INTEREST_WORDS.get(interest, "").split())


def _norm(text: str) -> str:
    return gazetteer.normalize(re.sub(r"['’]s\b", "", str(text)))   # "Old Manali’s cafés" names Old Manali


def _leaves(value) -> list[str]:
    """Every piece of text and every number inside the facts."""
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in _leaves(v)]
    if isinstance(value, (list, tuple, set)):
        return [x for v in value for x in _leaves(v)]
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def _sentence(text: str, start: int, end: int) -> str:
    left = max((text.rfind(c, 0, start) for c in ".!?\n"), default=-1)
    right = min((i for i in (text.find(c, end) for c in ".!?\n") if i >= 0), default=len(text) - 1)
    return " ".join(text[left + 1:right + 1].split())[:MAX_SENTENCE]


def _value(number: str, unit: str | None) -> float:
    return float(number.replace(",", "")) * parser._UNITS.get((unit or "").lower(), 1)


# ------------------------------------------------------------------ the single checks: (flags, how many looked at)
def check_amounts(text: str, allowed: set) -> tuple[list, int]:
    flags, seen, looked = [], set(), 0
    for pattern in _MONEY:
        for m in pattern.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in seen):
                continue
            seen.add((m.start(), m.end()))
            try:
                amount = _value(m.group(1), m.group(2))
            except ValueError:
                continue
            looked += 1
            if round(amount) not in allowed:
                flags.append({"kind": "amounts", "value": m.group().strip(),
                              "sentence": _sentence(text, m.start(), m.end())})
    return flags, looked


def numbers_in(leaves: list[str]) -> set:
    found = set()
    for leaf in leaves:
        for m in _NUMBER.finditer(leaf):
            try:
                found.add(round(_value(m.group(1), m.group(2))))
            except ValueError:
                pass
    return found


def _dates_in(text: str):
    """(month, day, year or None, start, end) for every date written in ``text``."""
    taken = []
    for pattern, order in ((_ISO, "ymd"), (_DAY_MONTH, "dmy"), (_MONTH_DAY, "mdy")):
        for m in pattern.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            parts = dict(zip(order, m.groups()))
            month = parts["m"]
            month = int(month) if month.isdigit() else _MONTHS[month[:3].lower()]
            day = int(parts["d"])
            if 1 <= month <= 12 and 1 <= day <= 31:
                taken.append((m.start(), m.end()))
                yield month, day, int(parts["y"]) if parts.get("y") else None, m.start(), m.end()


def check_dates(text: str, leaves: list[str], start_date: str | None, days: int | None) -> tuple[list, int]:
    allowed: set = set()                          # (month, day, year or None)
    for leaf in leaves:
        allowed.update((mo, d, y) for mo, d, y, _, _ in _dates_in(leaf))
    try:
        first = date.fromisoformat(str(start_date))
        for offset in range(int(days or 1)):
            day = first + timedelta(days=offset)
            allowed.add((day.month, day.day, day.year))
    except (TypeError, ValueError):
        pass
    years = {y for _, _, y in allowed if y}
    month_days = {(mo, d) for mo, d, _ in allowed}
    flags, looked = [], 0
    for month, day, year, start, end in _dates_in(text):
        looked += 1
        wrong_year = year and years and year not in years
        if (month, day) not in month_days or wrong_year:
            flags.append({"kind": "dates", "value": text[start:end], "sentence": _sentence(text, start, end)})
    return flags, looked


def check_day_counts(text: str, leaves: list[str], days: int | None) -> tuple[list, int]:
    if not days:
        return [], 0
    given = {"day": {days}, "night": {max(days - 1, 0)}}
    for leaf in leaves:                           # e.g. "leaves 2 days before", "3 nights"
        for m in _COUNT.finditer(leaf):
            given[m.group(2).lower().rstrip("s")].add(_WORD_NUMBERS.get(m.group(1).lower()) or int(m.group(1)))
    flags, looked = [], 0
    for m in _COUNT.finditer(text):
        looked += 1
        number = _WORD_NUMBERS.get(m.group(1).lower()) or int(m.group(1))
        if number not in given[m.group(2).lower().rstrip("s")]:
            flags.append({"kind": "day_counts", "value": m.group(), "sentence": _sentence(text, m.start(), m.end())})
    for m in _DAY_N.finditer(text):
        looked += 1
        if not 1 <= int(m.group(1)) <= days:
            flags.append({"kind": "day_counts", "value": m.group(), "sentence": _sentence(text, m.start(), m.end())})
    return flags, looked


_known: dict = {}


def _known_places() -> dict:
    """normalised name -> every name of that same place (so "Bombay" is fine when the plan says "Mumbai")."""
    if not _known:
        groups: dict = {}
        for slug, aliases in ALIASES.items():
            groups.setdefault(slug, set()).update(_norm(a) for a in [slug, *aliases])
        for alias, found in gazetteer.scan_names():
            groups.setdefault(found["slug"], set()).update({_norm(alias), _norm(found["name"])})
        for names in groups.values():
            for name in names:
                if len(name) >= 4 or name in ("goa", "leh", "ooty", "puri"):          # not airport codes
                    _known.setdefault(name, set()).update(names)
    return _known


def check_places(text: str, leaves: list[str], also_allowed: str = "") -> tuple[list, int]:
    """Known towns and cities, and names of two or more capitalised words, that the plan does not mention."""
    pieces = [_norm(x) for x in leaves]
    everything = f" {' '.join(pieces)} {_norm(also_allowed)} "
    word_sets = [set(p.split()) for p in pieces] + [set(_norm(also_allowed).split())]
    flags, looked, spans, flagged = [], 0, [], set()

    for m in _PHRASE.finditer(text):
        words = re.findall(r"\S+", m.group())
        offset = m.start()
        while words and _norm(words[0]) in _ORDINARY:                # "Visit Fort Aguada" -> "Fort Aguada"
            offset = text.find(words[1], offset + len(words[0])) if len(words) > 1 else m.end()
            words.pop(0)
        while words and _norm(words[-1]) in _ORDINARY:
            words.pop()
        if len(words) < 2:
            continue
        phrase = " ".join(words)
        key = _norm(phrase)
        significant = set(key.split()) - {"of", "the", "de", "del", "da", "la", "le", "di", "du", "and", "ka", "ki"}
        if not significant or significant <= _ORDINARY:
            continue
        looked += 1
        spans.append((offset, m.end()))
        if f" {key} " in everything or any(significant <= s for s in word_sets) or key in flagged:
            continue
        flagged.add(key)
        flags.append({"kind": "places", "value": phrase, "sentence": _sentence(text, offset, m.end())})

    low = text.lower()
    for name, same in _known_places().items():
        m = re.search(rf"\b{re.escape(name)}\b", low) if name in low else None
        if not m or any(a <= m.start() < b for a, b in spans):
            continue
        if not text[m.start()].isupper():                            # an ordinary word, not a name
            continue
        looked += 1
        if not any(f" {other} " in everything for other in same) and name not in flagged:
            flagged.add(name)
            flags.append({"kind": "places", "value": text[m.start():m.end()],
                          "sentence": _sentence(text, m.start(), m.end())})
    return flags, looked


# ------------------------------------------------------------------ recording
def _record(job: str, flags: list, looked: dict, shown: bool, text: str | None = None, **more) -> None:
    counts: dict = {}
    for flag in flags:
        counts[flag["kind"]] = counts.get(flag["kind"], 0) + 1
    # one entry: the examples and the AI text travel with it (kept only with RECORD_DETAILS=1)
    with observe.span("fact_check", job, shown=shown, flags=len(flags), kinds=counts,
                      looked_at={k: v for k, v in looked.items() if v}, **more) as step:
        step.status = "flagged" if flags else "ok"
        if flags:
            step.detail("flags", flags[:MAX_FLAGS])
        if text:
            step.detail("ai_text", text[:2000])


def check_text(text: str, plan, *, start_date, days, question: str = "", amounts: set | None = None) -> tuple[list, dict]:
    """Every check on one AI text against ``plan`` (any nested data). Returns (flags, kind -> how many looked at)."""
    leaves = _leaves(plan)
    found, looked = [], {}
    for kind, (flags, count) in {
        "amounts": check_amounts(text, numbers_in(leaves) if amounts is None else amounts),
        "dates": check_dates(text, leaves, start_date, days),
        "day_counts": check_day_counts(text, leaves, days),
        "places": check_places(text, leaves, question),
    }.items():
        found += flags
        looked[kind] = count
    return found, looked


def record_text(job: str, text: str, plan: Callable[[], list], *, start_date, days, shown: bool, question: str = "",
                amounts: Callable[[], set] | None = None, amounts_rejected: bool = False) -> None:
    """An AI summary or chat answer against the plan. ``plan()`` returns any nested data the plan is made of;
    ``amounts()`` the only rupee figures allowed (by default every number found in the plan). Both are called only
    while a request is being recorded, and inside the safety net."""
    if not observe.active():
        return
    try:
        found, looked = check_text(text, plan(), start_date=start_date, days=days, question=question,
                                   amounts=None if amounts is None else amounts())
        if amounts_rejected and not any(f["kind"] == "amounts" for f in found):
            found.append({"kind": "amounts", "value": "an amount not written as ₹ with a figure from the plan",
                          "sentence": ""})
        _record(job, found, looked, shown, text)
    except Exception:                                    # noqa: BLE001 - a check must never break anything
        observe.event("fact_check", job, "error")


def _supported_number(value: int, text: str) -> bool:
    low = text.lower()
    numbers = {int(x) for x in re.findall(r"\d+", low) if len(x) <= 3}
    numbers |= {n for w, n in _WORD_NUMBERS.items() if re.search(rf"\b{w}\b", low)}
    if value in numbers or value - 1 in numbers and re.search(r"\bnights?\b", low):
        return True
    if value == 7 and re.search(r"\bweek\b", low) or value == 14 and re.search(r"\bfortnight\b", low):
        return True
    if value % 7 == 0 and value // 7 in numbers and "week" in low:
        return True
    return value in (2, 3) and "weekend" in low


def _supported_budget(value: int, text: str) -> bool:
    amounts = numbers_in([text])
    if value in amounts:
        return True
    low = text.lower()
    people = {int(x) for x in re.findall(r"(?<![\d.,])(\d{1,2})(?![\d.,]*\d)", low)}
    people |= {n for w, n in _WORD_NUMBERS.items() if re.search(rf"\b{w}\b", low)}
    if re.search(r"\bcouple\b|\bwife\b|\bhusband\b|\bpartner\b|\bhoneymoon\b", low):
        people.add(2)
    per_person = re.search(r"per\s*(person|head|adult)|\bpp\b|\beach\b|/person|a head", low)
    return bool(per_person) and any(value == a * n for a in amounts for n in people
                                    if 1 < n <= config.MAX_TRAVELERS and a >= config.MIN_BUDGET / 2)


def _supported_place(value: str, text: str) -> str:
    """"typed" (also under another name of the same place), "corrected" (one letter off a typed word) or ""."""
    key, low = _norm(value), f" {_norm(text)} "
    if not key:
        return ""
    same = _known_places().get(key, {key})
    if any(f" {name} " in low for name in same):
        return "typed"
    words, size = low.split(), len(key.split())
    near = (" ".join(words[i:i + size]) for i in range(len(words) - size + 1))
    return "corrected" if len(key) >= 4 and any(_one_slip(key, w) for w in near) else ""


def check_request_values(text: str, filled: dict) -> tuple[list, dict, int]:
    """``filled``: field -> the value an AI supplied. Returns (flags, looked at, spellings it corrected)."""
    flags, looked, corrected = [], {}, 0
    for field, value in filled.items():
        if field in ("origin", "destination"):
            looked["places"] = looked.get("places", 0) + 1
            how = _supported_place(str(value), text)
            corrected += how == "corrected"
            if not how:
                flags.append({"kind": "places", "value": f"{field}: {value}", "sentence": ""})
        elif field == "days":
            looked["days"] = 1
            if not _supported_number(int(value), text):
                flags.append({"kind": "days", "value": f"days: {value}", "sentence": ""})
        elif field == "budget":
            looked["budget"] = 1
            if not _supported_budget(int(value), text):
                flags.append({"kind": "budget", "value": f"budget: {value}", "sentence": ""})
        elif field == "preferences":
            looked["preferences"] = len(value)
            flags += [{"kind": "preferences", "value": f"interest: {p}", "sentence": ""}
                      for p in value if not _asked_for(p, text)]
    return flags, looked, corrected


def record_request_values(text: str, filled: dict) -> None:
    if not observe.active() or not filled:
        return
    try:
        flags, looked, corrected = check_request_values(text, filled)
        _record("request_reading", flags, looked, True, **({"spelling_corrected": corrected} if corrected else {}))
    except Exception:                                    # noqa: BLE001
        observe.event("fact_check", "request_reading", "error")


def record_ranking(returned: int, unknown: list) -> None:
    """Ids the AI returned that were not on its list. They are dropped before the plan is built."""
    if not observe.active():
        return
    try:
        flags = [{"kind": "unknown_ids", "value": str(i)[:60], "sentence": ""} for i in unknown]
        _record("ranking", flags, {"unknown_ids": returned}, False)
    except Exception:                                    # noqa: BLE001
        observe.event("fact_check", "ranking", "error")
