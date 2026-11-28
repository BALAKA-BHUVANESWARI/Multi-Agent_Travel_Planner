"""Whether something an AI model returned may be used. Unlike the records in ``fact_checks``, this changes what
the traveller sees, and it works with recording switched off.

* An AI summary or chat answer is not shown when it states money, a date, a place name or a hotel or place feature
  that the plan does not hold. If the check itself breaks, the text is not shown either.
* A starting city, destination, budget or trip length read by an AI is used only when the traveller's own words
  state it.

This is not proof: only the listed kinds are looked for (see ``fact_checks``), and a true statement can be held back.
Day and night counts are recorded but do not hold a text back ("spend 2 days on the beach" is a fair thing to say).
"""
from __future__ import annotations

import re

from app.services import fact_checks as facts

_OTHER_MONEY = re.compile(r"(?:[$€£¥฿]\s?\d[\d,.]*|\b(?:usd|eur|gbp|aed|thb)\s?\d[\d,.]*|"
                          r"\b\d[\d,.]*\s?(?:dollars?|euros?|pounds?|dirhams?|baht)\b)", re.I)

# "the plan does not include Hampi" is true of any place the plan does not hold
_NOT_PLANNED = re.compile(r"\b(?:plan|itinerary|trip) (?:does(?:n['’]t| not)) (?:include|visit|cover|go to)\b", re.I)


def unsupported(text: str, plan: list, *, start_date, days, amounts: set | None = None) -> list[str]:
    """The kinds of unsupported detail in ``text`` (empty: it may be shown). ``plan`` is any nested data;
    ``amounts``, when given, are the only rupee figures allowed."""
    try:
        leaves = facts._leaves(plan)
        found = set()
        if facts.check_amounts(text, facts.numbers_in(leaves) if amounts is None else amounts)[0]:
            found.add("amounts")
        everything = "\n".join(leaves).lower()
        if any(m.group().lower() not in everything for m in _OTHER_MONEY.finditer(text)):
            found.add("amounts")
        if facts.check_dates(text, leaves, start_date, days)[0]:
            found.add("dates")
        for flag in facts.check_places(text, leaves)[0]:       # every unknown name, also one from the question
            for m in re.finditer(re.escape(flag["value"]), text):
                if not facts.says_unsure(text, m.start(), m.end()) \
                        and not _NOT_PLANNED.search(text[max(m.start() - 60, 0):m.start()]):
                    found.add("places")
        if facts.check_features(text, leaves)[0]:
            found.add("features")
        return sorted(found)
    except Exception:                                        # noqa: BLE001 - when in doubt, do not show it
        return ["check_failed"]


# ------------------------------------------------------------------ values an AI read from the request
_UNITS_WORDS = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                "seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_NUMBER_WORDS = {w: n for n, w in enumerate(_UNITS_WORDS, 1)}
_NUMBER_WORDS.update({w: 10 * n for n, w in enumerate(_TENS, 2)})
_WORD = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_COUNT = rf"(?:\d{{1,2}}|(?:{'|'.join(_TENS)})(?:[ -](?:{'|'.join(_UNITS_WORDS[:9])}))?|{_WORD}|an?)"
_LENGTH = re.compile(
    rf"(?<![\w.,])(?:({_COUNT})\s*(?:-|to|or)\s*)?({_COUNT})[\s-]*(?:(?:more|full|whole|nice|short|long)[\s-]+)?"
    rf"(days?|dayz|dys?|din|nights?|nites?|weeks?|wks?)\b", re.I)
_SHORT_FORM = re.compile(r"\b(\d{1,2})\s?d\b(?:\s*/?\s*\d{1,2}\s?n\b)?|\bdays?\s*[:=]\s*(\d{1,2})\b", re.I)


def _count(words: str) -> int:
    low = words.lower()
    if low.isdigit():
        return int(low)
    return 1 if low in ("a", "an") else sum(_NUMBER_WORDS[w] for w in re.split(r"[ -]", low))


def stated_days(text: str) -> set[int]:
    """Every trip length, in days, that the words of ``text`` state."""
    found: set[int] = set()
    for m in _LENGTH.finditer(text):
        unit = m.group(3).lower()
        for words in filter(None, (m.group(1), m.group(2))):
            n = _count(words)
            found.add(n + 1 if unit.startswith("ni") else 7 * n if unit.startswith("w") else n)
    for m in _SHORT_FORM.finditer(text):
        found.add(int(m.group(1) or m.group(2)))
    low = text.lower()
    if re.search(r"\bweekend\b", low):
        found.update({2, 3})
    if re.search(r"\bfortnight\b", low):
        found.add(14)
    return found


_WORDED_MONEY = re.compile(
    rf"(?<![\d.,])\b(half a|(?:{_COUNT})(?: and a half)?)[ -](?:hundred[ -])?(thousand|grand|lakhs?|lacs?|crores?)\b", re.I)


def _spell_out(text: str) -> str:
    """"fifty thousand" -> "50000", "one and a half lakh" -> "150000"."""
    def number(m):
        said, unit = m.group(1).lower(), m.group(2).lower()
        n = 0.5 if said == "half a" else _count(said.removesuffix(" and a half")) + \
            (0.5 if said.endswith(" and a half") else 0)
        n *= 100 if "hundred" in m.group().lower() else 1
        scale = 1_000 if unit in ("thousand", "grand") else 10_000_000 if unit.startswith("cr") else 100_000
        return str(round(n * scale))
    return _WORDED_MONEY.sub(number, text)


def typed_place(value: str, text: str, other: str = "") -> bool:
    """Whether the traveller's own words name this place: as written, by another known name of the same place, or
    one letter off. ``other`` is the place at the other end of the trip: the words naming it name that end only."""
    try:
        rest = f" {facts._norm(text)} "
        if other:                                             # "a trip to Goa" does not say "from Goa"
            end = facts._norm(other)
            for name in sorted(facts._known_places().get(end, {end}), key=len, reverse=True):
                if name and f" {name} " in rest:
                    rest = rest.replace(f" {name} ", " | ", 1)
                    break
        names = dict.fromkeys((str(value), str(value).split(",")[0]))        # "Delhi, India" is typed as "Delhi"
        return any(facts._supported_place(name, rest) for name in names)
    except Exception:                                        # noqa: BLE001
        return False


def typed_value(field: str, value, text: str) -> bool:
    """Whether the traveller's own words state this ``days`` or ``budget`` value."""
    try:
        if field == "days":
            return int(value) in stated_days(text)
        rupees = _spell_out(_OTHER_MONEY.sub(" ", text))      # "$5000" does not state 5000 rupees
        return facts._supported_budget(int(value), rupees)
    except Exception:                                        # noqa: BLE001
        return False
