"""Rule-based intake: free text -> structured trip constraints.

This is the always-available parser. An LLM (if configured) may only *fill gaps*;
it never overrides what the rules found, and its output is schema-validated.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from app.core import config
from app.data import gazetteer
from app.data.curated_destinations import ALIASES, CITIES, DESTINATIONS

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
}
_MONTH_FULL = "|".join(k for k in MONTHS if len(k) > 4 or k in ("june", "july", "march", "april"))

PREF_WORDS = {
    "beach": ["beach", "beaches", "sea", "sand", "coast"],
    "food": ["food", "foodie", "cuisine", "eat", "eating", "restaurant", "restaurants", "street food", "seafood"],
    "culture": ["culture", "cultural", "art", "arts", "museum", "museums", "craft", "crafts"],
    "history": ["history", "historic", "historical", "heritage", "fort", "forts", "palace", "palaces"],
    "adventure": ["adventure", "trek", "trekking", "rafting", "paragliding", "hiking", "thrill", "thrilling",
                  "adrenaline", "water sports"],
    "nature": ["nature", "scenic", "waterfall", "waterfalls", "lake", "lakes", "backwater", "backwaters",
               "mountain", "mountains", "wildlife", "hills"],
    "nightlife": ["nightlife", "party", "parties", "pub", "pubs", "club", "clubs"],
    "shopping": ["shopping", "market", "markets", "bazaar", "bazaars"],
    "relaxation": ["relax", "relaxing", "relaxation", "peaceful", "spa", "chill", "laid-back", "laid back"],
    "spiritual": ["temple", "temples", "spiritual", "church", "churches", "monastery"],
    "family": ["kids", "children", "family-friendly", "kid-friendly"],
}

_UNITS = {"k": 1e3, "thousand": 1e3, "l": 1e5, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5,
          "cr": 1e7, "crore": 1e7, "crores": 1e7}
_AMT = r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|l|crores?|cr)?"
_NOT_UNIT = r"(?!\s*(?:days?|nights?|people|persons?|pax|adults?|travell?ers?|kids?|children|friends|d\b|n\b))"
_CTX = (r"(?:budget|under|within|upto|up to|max(?:imum)?|around|about|approx(?:imately)?|spend|limit|total|cap)"
        r"\s*(?:is|of|:|to|at|=|for)?\s*(?:₹|rs\.?|inr|rupees)?\s*")


def _amount(num: str, unit: str | None) -> int:
    v = float(num.replace(",", ""))
    return int(round(v * _UNITS.get((unit or "").lower(), 1)))


def parse_budget(text: str) -> tuple[int | None, bool]:
    """Return (amount_inr, per_person). Handles 50k, 1.5L, 1 lakh, Rs 40,000, 'budget 60000'."""
    low = text.lower()
    amount = None
    span_end = 0
    for pat in (
        rf"{_CTX}{_AMT}{_NOT_UNIT}",
        rf"(?:₹|rs\.?|inr|rupees)\s*{_AMT}{_NOT_UNIT}",
        rf"(?<![\d.]){_AMT}\s*(?:rs|inr|rupees|₹)",
        rf"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|l|crores?|cr)\b{_NOT_UNIT}",
    ):
        for m in re.finditer(pat, low):
            try:
                val = _amount(m.group(1), m.group(2))
            except ValueError:
                continue
            if config.MIN_BUDGET <= val <= config.MAX_BUDGET:
                amount, span_end = val, m.end()
                break
        if amount is not None:
            break
    if amount is None:
        return None, False
    tail = low[span_end:span_end + 30]
    per_person = bool(re.search(r"per\s*(person|head|adult)|\bpp\b|\beach\b|/person|a head", tail))
    return amount, per_person


def parse_days(text: str) -> int | None:
    low = text.lower()
    m = re.search(r"(\d+)\s*n\s*/?\s*(\d+)\s*d\b", low)          # 5N/6D
    if m:
        return int(m.group(2))
    m = re.search(r"(\d+)\s*[- ]?\s*days?\b", low)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*[- ]?\s*nights?\b", low)
    if m:
        return int(m.group(1)) + 1
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    m = re.search(r"\b(" + "|".join(words) + r")[- ]days?\b", low)
    if m:
        return words[m.group(1)]
    m = re.search(r"\b(\d+|a|one|two)\s+weeks?\b", low)
    if m:
        n = {"a": 1, "one": 1, "two": 2}.get(m.group(1)) or int(m.group(1))
        return 7 * n
    if re.search(r"\bweek\s?-?\s?long\b|\ba week\b|\bone week\b", low):
        return 7
    if re.search(r"\bweekend\b", low):
        return 3
    return None


def parse_month(text: str) -> tuple[int | None, int | None]:
    """Return (month, day_of_month). 'may' must follow a preposition to avoid the verb."""
    low = text.lower()
    mon = rf"({_MONTH_FULL}|may|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)"
    year = r"(?:20\d\d)\b"
    m = re.search(rf"(?<![\d,.])(\d{{1,2}})(?:st|nd|rd|th)\s+(?:of\s+)?{mon}\b", low) or \
        re.search(rf"(?<![\d,.])(\d{{1,2}})\s+(?:of\s+)?{mon}\b(?!\s*(?!{year})\d)", low)       # a year may follow
    if m and 1 <= int(m.group(1)) <= 31:
        return MONTHS[m.group(2)], int(m.group(1))
    # "December 28th", or "December 28" when the number can't be a count of days, people or money
    not_a_day = r"(?![\s-]*(?:days?|nights?|weeks?|people|persons?|adults?|kids?|children|friends|travell?ers?|pax|" \
                r"of us|k\b|l\b|lakh|lac|thousand)|[,.]\d|%)"
    m = re.search(rf"\b{mon}\s+(\d{{1,2}})(?:(?:st|nd|rd|th)\b|\b{not_a_day})", low)
    if m and 1 <= int(m.group(2)) <= 31:
        return MONTHS[m.group(1)], int(m.group(2))
    m = re.search(rf"\b(?:in|during|for|around|early|late|mid|this|next|of|by)\s+(?:the\s+)?(?:month\s+of\s+)?"
                  rf"({_MONTH_FULL}|may|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b", low)
    if m:
        return MONTHS[m.group(1)], None
    m = re.search(rf"\b({_MONTH_FULL}|jan|feb|apr|jun|jul|aug|sept?|oct|nov|dec)\b", low)
    if m:
        return MONTHS[m.group(1)], None
    return None, None


def parse_travelers(text: str) -> tuple[int | None, bool]:
    """Return (count, assumed). assumed=True when a count had to be guessed (e.g. 'family')."""
    low = text.lower()
    m = re.search(r"(?:family|group|party|team)\s+of\s+(\d+)", low)
    if m:
        return int(m.group(1)), False
    m = re.search(r"\b(?:me|myself|i)\s*(?:and|\+|&|with)\s*(?:my\s*)?(\d+)\s*(?:friends?|cousins?|colleagues?|"
                  r"buddies|siblings?)", low)
    if m:
        return int(m.group(1)) + 1, False
    total = 0
    for m in re.finditer(r"(\d+)\s*(?:adults?|people|persons?|pax|travell?ers?|friends|guys|girls|"
                         r"kids?|children|seniors?|of us)", low):
        total += int(m.group(1))
    if total:
        return total, False
    if re.search(r"\bcouple\b|\bhoneymoon\b|\bwith my (wife|husband|girlfriend|boyfriend|partner|spouse|"
                 r"fianc[eé]e?)\b|\bmy (wife|husband|partner) and i\b|\bme and my (wife|husband|partner)\b", low):
        return 2, False
    if re.search(r"\bwith my parents\b", low):
        return 3, False
    if re.search(r"\bsolo\b|\balone\b|\bby myself\b|\bjust me\b", low):
        return 1, False
    m = re.search(r"\bfor\s+(\d{1,2})\b(?!\s*(?:days?|nights?|d\b|k\b|l\b|lakh|%|,?\d))", low)
    if m and 1 <= int(m.group(1)) <= config.MAX_TRAVELERS:
        return int(m.group(1)), False
    if re.search(r"\bfamily\b", low):
        return 4, True
    return None, False


def parse_preferences(text: str) -> list[str]:
    low = text.lower()
    found = []
    for pref, words in PREF_WORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            found.append(pref)
    return found


# Words that end (or void) a place phrase when reading free text such as "trip to Hampi in March".
_STOP = set("""
from to in on at for with and or by during around budget under within of the a an my our your this next coming
upcoming last early late mid per each about approx after before till until via using including between through
into onto over near nearby love loves like likes want wants need needs prefer prefers looking interested enjoy
enjoying please pls i we me us he she they it is are am be will would can could should also plus but so if then
than too very really just only some any all more most less few many lots lot one two three four five six seven
eight nine ten day days night nights week weeks weekend weekends month months year trip trips travel travelling
traveling vacation holiday holidays visit visiting tour tours getaway stay staying fly flying flight flights go
going goes journey trek trekking honeymoon explore exploring itinerary plan planning book booking hotel hotels
adults adult people persons person pax kids kid children child family friends friend couple solo alone parents
wife husband partner rs inr rupees lakh lakhs lac lacs crore crores k l cr somewhere anywhere abroad overseas
outside international domestic city town place places village countryside island islands resort resorts jungle
desert river forest romantic relaxing relaxed cheap luxury short long quick fun amazing perfect nice great good
beautiful cozy calm quiet busy memorable unforgettable ideal best top popular famous
""".split()) | {w for words in PREF_WORDS.values() for w in words} | set(MONTHS)

_BREAK = re.compile(r"[,;:.!?()\d\u20b9/@#]")
_ORIGIN_CUE = re.compile(r"\b(?:starting from|flying out from|flying from|travelling from|traveling from|"
                         r"leaving from|departing from|out of|based in|living in|leaving|departing|starting|"
                         r"from)\s+", re.I)
_DEST_CUE = re.compile(r"\b(?:to|visit|visiting|explore|exploring|towards?|into|in|at|around|near)\s+", re.I)
_NOUN_AFTER = re.compile(r"((?:[A-Za-z\u00c0-\u024f'\u2019-]+\s+){1,3})(?:trip|vacation|holiday|tour|itinerary|getaway|"
                         r"honeymoon)\b")


def _phrase(s: str) -> str | None:
    """Place phrase at the start of ``s``: up to 4 words, ending at punctuation, a number or a stop word."""
    s = re.sub(r"^\s*the\s+", "", _BREAK.split(s, maxsplit=1)[0], flags=re.I)
    words: list[str] = []
    for w in s.split():
        if w.lower().strip("'\u2019-") in _STOP:
            break
        words.append(w.strip("'\u2019"))
        if len(words) == 4:
            break
    phrase = " ".join(words).strip()
    return phrase if 2 <= len(phrase) <= 40 and re.search(r"[A-Za-z\u00c0-\u024f]", phrase) else None


def extract_place_texts(text: str, taken: list[tuple[int, int]]) -> dict[str, str]:
    """Free-text origin/destination phrases NOT already matched against the known-place lists.
    They are only candidates: each is validated by the place lookup before it is used."""
    def free(start: int) -> bool:
        return not any(s <= start < e for s, e in taken)

    out: dict[str, str] = {}
    for m in _ORIGIN_CUE.finditer(text):
        if free(m.end()):
            ph = _phrase(text[m.end():])
            if ph:
                out["origin"] = ph
                break
    for m in _DEST_CUE.finditer(text):
        cue = m.group().strip().lower()
        if not free(m.end()):
            continue
        if cue in ("in", "at") and re.search(r"(?:living|based|staying|born|raised)\s+$", text[:m.start()], re.I):
            continue
        if _ORIGIN_CUE.search(text[max(0, m.start() - 20):m.end()]) and cue in ("in", "at"):
            continue
        ph = _phrase(text[m.end():])
        if ph and ph.lower() != out.get("origin", "").lower():
            out["destination"] = ph
            break
    if "destination" not in out:                                   # "a Bali holiday", "Paris trip"
        for m in _NOUN_AFTER.finditer(text):
            words = [w for w in m.group(1).split()]
            tail: list[str] = []
            for w in reversed(words):
                if w.lower().strip("'\u2019-") in _STOP or not w[:1].isupper():
                    break
                tail.insert(0, w)
            ph = " ".join(tail)
            if ph and free(m.start() + m.group(1).rfind(tail[0])):
                out["destination"] = ph
                break
    return out


def parse_places(text: str) -> tuple[str | None, str | None, dict[str, str]]:
    """Return (origin, destination, texts): known-place slugs, plus free-text candidates for the rest."""
    low = text.lower()
    mentions = []                              # (start, end, slug)
    taken: list[tuple[int, int]] = []
    pairs = [(a, slug) for slug, al in ALIASES.items() for a in al]
    pairs += [(a, e["slug"]) for a, e in gazetteer.scan_names()]
    pairs.sort(key=lambda x: -len(x[0]))
    for alias, slug in pairs:
        for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            mentions.append((m.start(), m.end(), slug))
    mentions.sort()
    origin = dest = None
    origin_cue = re.compile(r"(?:from|out of|leaving|departing|starting(?: from)?|flying(?: out)? from|"
                            r"based in|living in|travelling from|traveling from)\s*$")
    roles: dict[int, str] = {}
    for i, (s, e, slug) in enumerate(mentions):
        if origin_cue.search(low[max(0, s - 24):s]):
            roles[i] = "origin"
    for i, (s, e, slug) in enumerate(mentions[:-1]):                     # "Delhi to Goa"
        nxt = mentions[i + 1]
        if i not in roles and re.fullmatch(r"\s*(?:to|->|\u2192|-|till|for)\s*", low[e:nxt[0]]):
            roles[i] = "origin"
            roles[i + 1] = "dest"
    for i, (s, e, slug) in enumerate(mentions):
        role = roles.get(i)
        if role == "origin" and origin is None:
            origin = slug
        elif role == "dest" and dest is None:
            dest = slug
    for i, (s, e, slug) in enumerate(mentions):
        if i in roles:
            continue
        if dest is None and (slug in DESTINATIONS or slug not in CITIES):   # curated or offline-list place
            dest = slug
        elif origin is None and slug != dest:
            origin = slug
    texts = extract_place_texts(text, taken) if (dest is None or origin is None) else {}
    if dest is not None:
        texts.pop("destination", None)
    if origin is not None:
        texts.pop("origin", None)
    return origin, dest, texts


def compute_start_date(month: int | None, day: int | None, today: date) -> tuple[date, bool]:
    """Return (start_date, assumed). With no month: today + 21 days (assumed)."""
    if month is None:
        return today + timedelta(days=21), True
    year = today.year
    d = min(day or 10, 28 if month == 2 else calendar.monthrange(year, month)[1])
    cand = date(year, month, d)
    if cand <= today:
        if month == today.month:
            cand = today + timedelta(days=3)
        else:
            cand = date(year + 1, month, d)
    return cand, False


_MODE_WORDS = {
    "flight": r"\b(flights?|fly|flying|flown|air ?plane|by air|air travel)\b",
    "train": r"\b(trains?|rail|railway|by rail)\b",
    "bus": r"\b(buses|bus|volvo|coach)\b",
    "car": r"\b(car|cab|taxi|drive|driving|road ?trip|self[- ]drive)\b",
    "bike": r"\b(bikes?|motorbikes?|motorcycles?|scooter|bullet|biking|riding)\b",
}
# Words that look like a travel mode but are not a choice of how to get there.
_NOT_A_MODE = (r"\b(?:horse|horseback|camel|elephant|jeep)[- ]?(?:riding|ride)s?\b|"
               r"\b(?:quad|mountain|dirt)[- ]?(?:bikes?|biking)\b|"
               r"(?<!by )\bflights?\s*(?:and|&|\+)\s*hotels?\b|\bhotels?\s*(?:and|&|\+)\s*flights?\b")
_MODE_AUTO = r"\b(any (travel )?mode|any way|whichever|you (choose|decide|pick)|cheapest (way|mode))\b"


def parse_travel_mode(text: str) -> str | None:
    """How the person says they will travel: flight | train | bus | car | bike | auto, or None when not said
    (or when several different modes are mentioned, which is ambiguous)."""
    low = text.lower()
    if "| travel:" in low:                       # the page appends the person's choice after this marker
        low = low.rsplit("| travel:", 1)[1]
    low = re.sub(_NOT_A_MODE, " ", low)
    found = [m for m, pat in _MODE_WORDS.items() if re.search(pat, low)]
    if len(found) == 1:
        return found[0]
    if not found and re.search(_MODE_AUTO, low):
        return "auto"
    return None


_DEST_MARKER = re.compile(r"\|\s*destination:\s*([^|]{1,60})", re.I)


def split_destination_choice(text: str) -> tuple[str, str | None]:
    """The page appends ' | destination: X' when the traveller picks a suggested place; it wins over whatever
    the original sentence said. Returns (text without the marker, chosen place or None)."""
    found = _DEST_MARKER.findall(text)
    if not found:
        return text, None
    return _DEST_MARKER.sub(" ", text).strip(), found[-1].strip() or None


def parse_scope(text: str) -> str:
    """Where suggestions may be: 'abroad', 'india' or 'any'."""
    low = text.lower()
    if re.search(r"\b(abroad|overseas|international|outside india|foreign)\b", low):
        return "abroad"
    if re.search(r"\b(in india|within india|inside india|domestic)\b", low):
        return "india"
    return "any"


def parse_request(text: str, today: date, group_size: int = 0) -> dict:
    """Return {constraints, missing, invalid, assumptions}. ``group_size``: how many people filled in the
    group-preferences form (0 when it was not used)."""
    text, chosen = split_destination_choice(text)
    origin, dest, texts = parse_places(text)
    if chosen:
        dest = None
        texts["destination"] = chosen
    days = parse_days(text)
    month, day = parse_month(text)
    budget, per_person = parse_budget(text)
    travelers, assumed_t = parse_travelers(text)
    prefs = parse_preferences(text)
    pace = "relaxed" if re.search(r"\brelax(ed)?\b.*\bpace\b|\bslow\s+pace\b|\bnot too (many|busy|packed)\b|"
                                  r"\blaid[- ]back\b|\bunhurried\b|\bfewer activities\b", text.lower()) else "normal"
    assumptions: list[str] = []
    invalid: dict[str, str] = {}
    if group_size and (travelers is None or assumed_t):
        travelers, assumed_t = group_size, False
    elif group_size and travelers < group_size:
        assumptions.append(f"You listed {group_size} people in the group, so I planned for {group_size} travelers.")
        travelers = group_size
    if travelers is None:
        travelers = 1
        assumptions.append("No traveler count given: assumed 1 traveler.")
    elif assumed_t:
        assumptions.append(f"'Family' without a number: assumed {travelers} travelers.")
    if travelers > config.MAX_TRAVELERS:
        invalid["travelers"] = f"I can plan for up to {config.MAX_TRAVELERS} travelers."
    if days is not None and not (config.MIN_DAYS <= days <= config.MAX_DAYS):
        invalid["days"] = f"I can plan trips of {config.MIN_DAYS} to {config.MAX_DAYS} days."
    if budget is not None and per_person:
        budget *= travelers
        assumptions.append("Budget read as per person and multiplied by the number of travelers.")
    start, assumed_start = compute_start_date(month, day, today)
    if assumed_start:
        assumptions.append(f"No travel month given: assumed the trip starts around {start.isoformat()}.")
    constraints = {
        "origin": origin, "destination": dest, "days": days, "month": month,
        "start_date": start.isoformat(), "budget": budget, "travelers": travelers,
        "preferences": prefs, "pace": pace, "today": today.isoformat(),
        "travel_mode": parse_travel_mode(text),
    }
    missing = [k for k in ("origin", "destination", "days", "budget")
               if constraints[k] is None and k not in texts]
    return {"constraints": constraints, "missing": missing, "invalid": invalid, "assumptions": assumptions,
            "texts": texts}


_QUESTION = {
    "origin": "which city or town you're travelling from",
    "destination": "where you want to go (any city or town)",
    "days": f"how many days ({config.MIN_DAYS}-{config.MAX_DAYS})",
    "budget": "your total budget in INR (e.g. 60k or 1.5L)",
}


def build_question(missing: list[str], invalid: dict[str, str]) -> str:
    parts = []
    if invalid:
        parts.append(" ".join(invalid.values()))
    need = [k for k in missing if k not in invalid]
    if need:
        parts.append("To plan this I still need: " + "; ".join(_QUESTION[k] for k in need) + ".")
    return " ".join(parts)
