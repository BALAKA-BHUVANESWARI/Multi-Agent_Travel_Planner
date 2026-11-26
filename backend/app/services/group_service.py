"""Group travel preferences: each traveller says what they like and what they want to avoid.

Pure code. Activities are ordered so that the person who has had the least say so far gets the next pick,
then the finished plan reports how well each person was served.
"""
from __future__ import annotations

import re

from app.core import config
from app.core.security import sanitize_untrusted, scrub
from app.services.request_parser import PREF_WORDS, parse_preferences

MAX_NAME = 30
LIKE_WEIGHT = 4.0
AVOID_WEIGHT = 5.0


def _interests(value) -> list[str]:
    """Accept a list of interest names or free text ('temples and street food')."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    found: list[str] = []
    for item in value[:12]:
        if not isinstance(item, str):
            continue
        text = item.strip().lower()[:100]
        names = [text] if text in PREF_WORDS else parse_preferences(text)
        found += [n for n in names if n not in found]
    return found


def clean_group(raw) -> list[dict]:
    """Validate the group sent by a client. Raises ValueError with a plain-language reason."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ValueError("'group' must be a list of travellers")
    if len(raw) > config.MAX_TRAVELERS:
        raise ValueError(f"I can plan for up to {config.MAX_TRAVELERS} travelers.")
    out, seen = [], set()
    for i, member in enumerate(raw, 1):
        if not isinstance(member, dict):
            raise ValueError("each traveller needs a name, likes and avoids")
        name = member.get("name")
        # a card number, OTP or password typed into the name box must never be stored or echoed
        name = sanitize_untrusted(name, MAX_NAME) if isinstance(name, str) and scrub(name) == name else ""
        name = re.sub(r"[^\w .'-]", "", name).strip() or f"Traveller {i}"
        if name.lower() in seen:
            name = f"{name} ({i})"
        seen.add(name.lower())
        avoid = _interests(member.get("avoid"))
        out.append({"name": name, "likes": [x for x in _interests(member.get("likes")) if x not in avoid],
                    "avoid": avoid})
    return out


def shared_preferences(group: list[dict]) -> list[str]:
    """Everyone's likes, most widely shared first."""
    count: dict[str, int] = {}
    for m in group:
        for like in m["likes"]:
            count[like] = count.get(like, 0) + 1
    return sorted(count, key=lambda k: -count[k])


def fair_order(ranked: list[dict], group: list[dict]) -> list[dict]:
    """Re-order ranked activities so every traveller gets a turn. Places that everybody wants to avoid are
    dropped; day trips (``far``) stay after nearby places."""
    if not group:
        return ranked

    def avoiders(c: dict) -> int:
        return sum(1 for m in group if set(m["avoid"]) & set(c.get("tags", [])))

    pool = [c for c in ranked if avoiders(c) < len(group)]
    n = max(1, len(pool))
    base = {c["id"]: (n - i) / n * 3 for i, c in enumerate(pool)}          # keep the earlier ranking's order
    served = [0] * len(group)

    def value(c: dict) -> float:
        tags = set(c.get("tags", []))
        want = sum(LIKE_WEIGHT / (1 + served[i]) for i, m in enumerate(group) if set(m["likes"]) & tags)
        return base[c["id"]] + want - AVOID_WEIGHT * avoiders(c) / len(group) * 2

    out: list[dict] = []
    for far in (False, True):
        remaining = [c for c in pool if bool(c.get("far")) is far]
        while remaining:
            best = max(remaining, key=value)                                # ties keep the earlier order
            remaining.remove(best)
            out.append(best)
            tags = set(best.get("tags", []))
            for i, m in enumerate(group):
                if set(m["likes"]) & tags:
                    served[i] += 1
    return out


def satisfaction(group: list[dict], itinerary: dict) -> list[dict]:
    """For each traveller: which planned activities match their likes, and which touch something they avoid."""
    acts = [x for d in (itinerary or {}).get("days", []) for x in d["items"] if x["type"] == "activity"]
    report = []
    for m in group:
        liked = [x["name"] for x in acts if set(m["likes"]) & set(x.get("tags", []))]
        disliked = [x["name"] for x in acts if set(m["avoid"]) & set(x.get("tags", []))]
        report.append({"name": m["name"], "likes": m["likes"], "avoid": m["avoid"], "matched": liked,
                       "conflicts": disliked, "activities": len(acts)})
    return report
