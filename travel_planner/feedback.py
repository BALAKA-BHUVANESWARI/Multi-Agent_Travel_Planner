"""Turn human change requests ('make it cheaper', 'budget 50000', 'more food') into changes."""
from __future__ import annotations

import re

from . import config
from .intake import PREF_WORDS, parse_budget
from .utils import next_strategy

_CHEAPER = re.compile(r"\b(cheaper|cheap|less expensive|reduce (the )?cost|lower (the )?cost|save (some )?money|"
                      r"cut costs?|too expensive|economical|affordable)\b", re.I)
_UPGRADE = re.compile(r"\b(luxury|upgrade|more comfortable|nicer hotel|better hotel|splurge|premium)\b", re.I)
_RELAXED = re.compile(r"\b(relax(ed)?|slower|slow pace|less rushed|fewer activities|less packed|not so busy|"
                      r"too (busy|packed|rushed))\b", re.I)
_BUSIER = re.compile(r"\b(more activities|more things|busier|packed|fuller schedule)\b", re.I)
_MORE = re.compile(r"\bmore\s+(" + "|".join(sorted(PREF_WORDS, key=len, reverse=True)) + r")\b", re.I)
_MORE_ALIAS = {"eating": "food", "restaurants": "food", "temples": "spiritual", "museums": "culture",
               "markets": "shopping", "beaches": "beach", "forts": "history"}


def parse_feedback(text: str, constraints: dict, strategy: str) -> dict:
    """Return {recognized, changes, notes}.

    changes keys: budget, strategy, preferences_add, pace, food_boost.
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
    if _CHEAPER.search(low):
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
    recognized = bool(changes) or any("Already" in n for n in notes)
    return {"recognized": recognized, "changes": changes, "notes": notes}
