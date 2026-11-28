"""Turn human change requests into changes: 'make it cheaper', 'a cheaper hotel', 'a cheaper flight', 'budget
50000', 'more food', 'make it 4 days', 'add 1 person', 'go by train', 'change flight to train', 'move it to January',
'change destination to Jaipur', 'skip water sports'.

Rules only (no LLM). This module reads the words; the approval agent checks that each change is possible.
"""
from __future__ import annotations

import re

from app.core.utils import next_strategy
from app.services.request_parser import (
    PREF_WORDS,
    _phrase,
    parse_budget,
    parse_month,
    parse_travel_mode,
)

_CHEAPER = re.compile(r"\b(cheaper|cheap|less expensive|reduce (the )?cost|lower (the )?cost|save (some )?money|"
                      r"cut costs?|too expensive|economical|affordable)\b", re.I)
# "cheaper" said about the hotel or the travel only
_HOTEL_WORD = r"(?:hotels?|stay|accomm?odation|rooms?|lodging|hostels?|homestays?|place to stay)"
_TRAVEL_WORD = (r"(?:flights?|air ?fares?|(?:train|bus|flight) (?:tickets?|fares?)|tickets?|trains?|bus(?:es)?|"
                r"transport(?:ation)?)")
_PART = rf"(?:{_HOTEL_WORD}|{_TRAVEL_WORD})"
_PARTS = (rf"{_PART}(?:\s*(?:and|&)\s*(?:(?:a|an|the|my|our)\s+)?{_PART}"
          r"(?!\s+(?:is|are|should|stays?|can|as)\b))*")
_BOTH = rf"{_PART}\s*(?:and|&)\s*(?:(?:the|my|our)\s+)?{_PART}"     # "the flight and hotel are ..."
_NAMED = rf"(?:{_BOTH}(?=\s+(?:are|prices|costs|fares)\b)|{_PART})"
_BEFORE_PART = r"(?:(?:a|an|the|my|our|some|return|round[- ]trip|\d[- ]star|place for the)\s+){0,2}"
_LOW = r"(?:cheaper|cheap|less expensive|more affordable|affordable|economical)"
_PART_CHEAPER = [re.compile(p, re.I) for p in (
    # "a cheaper hotel", "cheaper flight and hotel"
    rf"\b{_LOW}\s+{_BEFORE_PART}({_PARTS})\b",
    # "the hotel is too expensive", "change the hotel to a cheaper one", "make the flight cheaper"
    rf"\b({_NAMED})\s+(?:(?:price|cost|fare)s?\s+)?(?:(?:is|are|was|seems?|looks?|should be|must be|needs? to be|"
    rf"to be|to|for)\s+)?(?:(?:a|an|something|a bit|a little|much|way|slightly)\s+)?"
    rf"(?:{_LOW}|too expensive|too costly)(?:\s+(?:one|option)s?)?\b",
    # "reduce the hotel cost", "lower the cost of the flight", "save money on the hotel"
    rf"\b(?:reduce|lower|cut)\s+(?:the\s+|my\s+|our\s+)?(?:(?:cost|price|fare)s?\s+(?:of|for|on)\s+"
    rf"(?:the\s+|my\s+|our\s+)?({_PARTS})|({_PARTS})\s+(?:cost|price|fare|bill)s?)\b",
    # "replace the hotel with a cheaper one"
    rf"\b(?:replace|swap)\s+(?:the\s+|my\s+|our\s+)?({_PART})\s+(?:with|for)\s+(?:(?:a|an|something)\s+)?{_LOW}"
    r"(?:\s+(?:one|option))?\b",
    rf"\b(?:save (?:some )?money|spend less)\s+on\s+(?:the\s+|my\s+|our\s+)?({_PARTS})\b")]
_UPGRADE = re.compile(r"\b(luxury|upgrade|more comfortable|nicer hotel|better hotel|splurge|premium)\b", re.I)
_RELAXED = re.compile(r"\b(relax(ed)?|slower|slow pace|less rushed|fewer activities|less packed|not so busy|"
                      r"too (busy|packed|rushed)|less (busy|hectic))\b", re.I)
_BUSIER = re.compile(r"\b(more activities|more things|busier|packed|fuller schedule)\b", re.I)
_MORE_ALIAS = {"eating": "food", "restaurants": "food", "temples": "spiritual", "museums": "culture",
               "markets": "shopping", "beaches": "beach", "forts": "history"}
_MORE = re.compile(r"\bmore\s+(" + "|".join(sorted({*PREF_WORDS, *_MORE_ALIAS}, key=len, reverse=True)) + r")\b", re.I)

_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10}
_N = r"(\d{1,2}|" + "|".join(_NUM_WORDS) + r")"
_PEOPLE = r"(?:people|persons?|travell?ers?|adults?|pax|friends?|members?|of us)"
_DAYS_ADD = re.compile(rf"\b(?:add|extra|extend(?:\s+it)?(?:\s+by)?)\s+{_N}\s+(?:more\s+)?(?:days?|nights?)\b|"
                       rf"\b{_N}\s+(?:more|extra|additional)\s+(?:days?|nights?)\b", re.I)
_DAYS_CUT = re.compile(rf"\b(?:remove|drop|cut|reduce(?:\s+it)?(?:\s+by)?|shorten(?:\s+it)?\s+by)\s+{_N}\s+"
                       rf"(?:days?|nights?)\b|\b{_N}\s+(?:days?|nights?)\s+(?:less|shorter|fewer)\b", re.I)
# A bare "2 days" is not enough ("spend 2 days at the beach"): it takes a cue, "N day trip", or opening the message.
_DAYS_SET = re.compile(
    r"\b(?:make(?:\s+(?:it|the\s+trip))?|change(?:\s+(?:it|the\s+trip|the\s+duration|duration))?\s+to|to|"
    r"total(?:\s+of)?|trip\s+of|(?:stay|plan(?:\s+it)?)\s+for|only|just)\s+(?:a\s+)?(\d{1,2})[\s-]*days?\b"
    r"(?!\s+(?:at|in|on|of)\b)|\b(\d{1,2})[\s-]*day\s+(?:trip|plan|itinerary|holiday)\b|"
    r"^\s*(\d{1,2})\s*days?\b(?!\s+(?:at|in|on|of)\b)", re.I)
_PAX_ADD = re.compile(rf"\badd\s+{_N}\s+(?:more\s+)?{_PEOPLE}\b|\b{_N}\s+more\s+{_PEOPLE}\b", re.I)
_PAX_CUT = re.compile(rf"\b(?:remove|drop)\s+{_N}\s+{_PEOPLE}\b|\b{_N}\s+(?:less|fewer)\s+{_PEOPLE}\b|"
                      rf"\b{_N}\s+{_PEOPLE}\s+(?:dropped out|can'?t come|cannot come|less)\b", re.I)
_COUNT = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"      # not "a": "we are a family"
_PAX_SET = re.compile(
    rf"\b(?:we(?:\s+are|'re|\s+will\s+be)(?:\s+now)?|there\s+(?:are|will\s+be)|family\s+of|group\s+of)\s+{_COUNT}\b"
    rf"(?!\s+(?:of|days?|big|group|family|couple|vegetarians?)\b)|"
    rf"\b(?:for|to|make\s+it)\s+{_COUNT}\s+(?:people|persons?|travell?ers?|adults?|pax)\b|"
    rf"\b(\d{{1,2}})\s+(?:people|travell?ers?|adults|pax)\b(?!\s+(?:love|like|want|prefer|are\s+vegetarian))", re.I)
_MODE_CUE = re.compile(r"\b(?:by|switch(?:\s+it)?\s+to|travel\s+by|go(?:ing)?\s+by|take\s+(?:a|the)|prefer(?:ably)?)"
                       r"\s+(?:a\s+|the\s+)?(flight|plane|air|train|rail|bus|car|cab|taxi|bike|motorbike)\b"
                       r"(?!\s+(?:ride|tour|rental|safari|museum)\b)|"
                       r"\b(fly|drive|ride)\s+instead\b|\b(?:self[- ]drive|road ?trip)\b", re.I)
# "change flight to train", "switch from flight to train", "change it to bus", "train instead"
_MODE_WORD = r"(flight|plane|air|train|rail|bus|car|cab|taxi|bike|motorbike)"
_MODE_CHANGE = re.compile(
    r"\b(?:change|switch|replace)\s+(?:(?:the|my|our)\s+)?"
    r"(?:(?:flight|plane|train|rail|bus|car|bike|travel|transport|journey|mode(?:\s+of\s+travel)?|it|this)\s+)?"
    r"(?:(?:from|of)\s+(?:a\s+|the\s+)?(?:flight|plane|train|bus|car|bike)\s+)?(?:to|with)\s+(?:a\s+|the\s+)?"
    rf"{_MODE_WORD}\b(?!\s+(?:ride|tour|rental|safari|museum|station|stand|ticket price)\b)|"
    rf"\b{_MODE_WORD}\s+instead\b", re.I)
_DATE_CUE = re.compile(r"\b(move|shift|postpone|prepone|reschedul\w+|start(?:ing)?|travel(?:ling)?\s+in|go\s+in|"
                       r"dates?|instead|change\s+(?:it\s+)?to)\b", re.I)
_DEST = [re.compile(p, re.I) for p in (
    r"\b(?:change|switch)\s+(?:the\s+)?(?:destination|place|city|location)\s+to\s+(.+)",
    r"\b(?:new\s+)?destination\s*(?:is|:)\s*(.+)",
    r"\b(?:go(?:ing)?\s+to|visit|take\s+(?:us|me)\s+to|switch\s+to)\s+(.+?)\s+instead\b")]
_SKIP = re.compile(r"\b(?:skip|remove|drop|exclude|leave out|take out|without|avoid|no|don'?t (?:want|include))\s+"
                   r"([A-Za-z][A-Za-z '&-]{2,80}?)(?=\s*(?:,|\.|;|!|\?|\bplease\b|$))", re.I)
# pieces after "no"/"remove" that are not things to leave out of the plan
_SKIP_IGNORE = re.compile(r"^(?:(?:changes?|problems?|worries|rush(?:ing)?|issues?|need|thanks?|more|less|days?|"
                          r"nights?|people|persons?|expensive|too|so|to|budget|costs?|prices?|flights?|flying|hotels?|"
                          r"make|add|go|going|change|move|keep|use|take|have|give|switch|travel|start|set)\b|\d)", re.I)


def _num(match: re.Match) -> int:
    raw = next(g for g in match.groups() if g)
    return int(raw) if raw.isdigit() else _NUM_WORDS[raw.lower()]


def _cheaper_parts(low: str) -> tuple[list[str], str]:
    """(the parts, of "hotel" and "flight" (any way of travelling), that are to be cheaper; the text without them)."""
    parts: list[str] = []
    rest = low
    for pattern in _PART_CHEAPER:
        while m := pattern.search(rest):
            named = next(g for g in m.groups() if g)
            for part, word in (("hotel", _HOTEL_WORD), ("flight", _TRAVEL_WORD)):
                if re.search(rf"\b{word}\b", named) and part not in parts:
                    parts.append(part)
            rest = rest[:m.start()] + " , " + rest[m.end():]
    return parts, rest


def _mode(words: str) -> str | None:
    return parse_travel_mode("by " + words)


def _trip_shape(low: str, constraints: dict, changes: dict, notes: list[str]) -> str:
    """Days and travelers. Returns the text with the matched phrases removed."""
    for key, add, cut, setter, label in (("days", _DAYS_ADD, _DAYS_CUT, _DAYS_SET, "days"),
                                         ("travelers", _PAX_ADD, _PAX_CUT, _PAX_SET, "travelers")):
        current = constraints.get(key)
        value = None
        for pattern, sign in ((add, 1), (cut, -1), (setter, 0)):
            m = pattern.search(low)
            if m and (sign == 0 or current):
                value = current + sign * _num(m) if sign else _num(m)
                low = low[:m.start()] + " " + low[m.end():]
                break
        if value is None and key == "days":
            if re.search(r"\b(?:one|a)\s+day\s+(?:longer|more)\b", low) and current:
                value = current + 1
            elif re.search(r"\b(?:one|a)\s+day\s+(?:shorter|less)\b", low) and current:
                value = current - 1
        if value is not None and value != current:
            changes[key] = value
            notes.append(f"Changing to {value} {label}.")
    return low


def parse_feedback(text: str, constraints: dict, strategy: str) -> dict:
    """Return {recognized, changes, notes}.

    changes keys: cheaper_parts ("hotel", "flight": only these are to be cheaper), budget, strategy, preferences_add, pace, food_boost, days, travelers, travel_mode,
    month_day (month, day), destination (a place name still to be checked), exclude (things to leave out).
    """
    changes: dict = {}
    notes: list[str] = []
    low = text.lower()

    amount, per_person = parse_budget(text)
    if amount is not None:
        if per_person:
            amount *= constraints.get("travelers", 1)
        changes["budget"] = amount
        notes.append(f"Budget set to {amount}.")
        changes["strategy"] = "normal"       # new budget: restart from the best-value strategy
    parts, others = _cheaper_parts(low)
    if parts:
        changes["cheaper_parts"] = parts             # the approval agent checks that something cheaper exists
    if _CHEAPER.search(others):                      # "cheaper" about the whole trip
        changes.pop("cheaper_parts", None)           # which covers the hotel and the travel too
        nxt = next_strategy(changes.get("strategy", strategy))
        if nxt == changes.get("strategy", strategy):
            notes.append("Already using the cheapest options; no cheaper tier is available.")
        else:
            changes["strategy"] = nxt
            notes.append(f"Switching to the '{nxt}' strategy.")
    elif _UPGRADE.search(low):
        changes["strategy"] = "normal"
        notes.append("Switching back to the best-value (normal) strategy.")
    for m in _MORE.finditer(low):
        pref = _MORE_ALIAS.get(m.group(1).lower(), m.group(1).lower())
        changes.setdefault("preferences_add", [])
        if pref not in changes["preferences_add"]:
            changes["preferences_add"].append(pref)
        if pref == "food":
            changes["food_boost"] = True
            notes.append("More food: ranking food stops higher and raising the food allowance by 25%.")
        else:
            notes.append(f"More {pref}: ranking {pref} stops higher.")
    if _RELAXED.search(low):
        changes["pace"] = "relaxed"
        notes.append("Relaxed pace: 2 activities per day.")
    elif _BUSIER.search(low):
        changes["pace"] = "normal"
        notes.append("Normal pace: 3 activities per day.")

    rest = _trip_shape(low, constraints, changes, notes)

    for pattern in _DEST:
        m = pattern.search(text)
        if m:
            place = _phrase(m.group(1))
            if place:
                changes["destination"] = place
                notes.append(f"Changing the destination to {place}.")
            break

    changed_to = _MODE_CHANGE.search(low)
    mode_match = None if changed_to else _MODE_CUE.search(low)
    if changed_to:
        mode = _mode(next(g for g in changed_to.groups() if g))
        if mode and mode != "auto" and mode != constraints.get("travel_mode"):
            changes["travel_mode"] = mode
            notes.append(f"Travelling by {mode}.")
    elif mode_match:
        cue = mode_match.group()
        mode = parse_travel_mode("by " + cue) or ("flight" if "fly" in cue else None)
        if mode is None and re.search(r"\b(drive|road ?trip)\b", cue):
            mode = "car"
        if mode and mode != "auto" and mode != constraints.get("travel_mode"):
            changes["travel_mode"] = mode
            notes.append(f"Travelling by {mode}.")

    if _DATE_CUE.search(rest):
        month, day = parse_month(rest)
        if month is not None:
            changes["month_day"] = (month, day)
            notes.append("Changing the travel dates.")

    skips: list[str] = []
    for m in _SKIP.finditer(rest):
        for piece in re.split(r"\s+(?:and|or)\s+", m.group(1)):           # "water sports or nightlife"
            term = re.sub(r"^(?:the|any|a|an)\s+", "", " ".join(piece.split()).strip(" -'"))
            if _SKIP_IGNORE.match(term):
                break                                                  # the sentence moved on to something else
            term = re.sub(r"\s+(?:activity|activities|visit|stuff|places?|from the plan|instead)$", "", term)
            if len(term) >= 3 and term not in skips:
                skips.append(term)
    if skips:
        changes["exclude"] = skips[:5]

    recognized = bool(changes) or any("Already" in n for n in notes)
    return {"recognized": recognized, "changes": changes, "notes": notes}


def matches_excluded(candidate: dict, term: str) -> bool:
    """Does an activity match something the traveller asked to leave out? By name, or by kind of interest."""
    term = term.lower().strip()
    name = str(candidate.get("name", "")).lower()
    singular = term[:-1] if term.endswith("s") and len(term) > 3 else term
    if re.search(rf"\b{re.escape(singular)}(?:s|es)?\b", name):
        return True
    for interest, words in PREF_WORDS.items():
        if term == interest or term in words:
            return interest in candidate.get("tags", [])
    return False
