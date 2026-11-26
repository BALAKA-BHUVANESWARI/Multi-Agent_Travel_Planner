"""The trip's budget: what each part costs and whether the total fits. Plain arithmetic, no AI."""
from __future__ import annotations

from app.core import config
from app.data.curated_destinations import dest_cost_factor


def food_line(constraints: dict, strategy: str, food_boost: bool) -> int:
    rate = config.FOOD_PER_PERSON_DAY[strategy] * dest_cost_factor(constraints)
    if food_boost:
        rate *= config.FOOD_BOOST
    return int(round(rate * constraints["days"] * constraints["travelers"]))


def build_budget_report(state: dict) -> dict:
    c = state["constraints"]
    strategy = state.get("strategy", "normal")
    fl = (state.get("flight") or {}).get("selected")
    ho = (state.get("hotel") or {}).get("selected")
    lines = {
        "flight": fl["price_pp"] * c["travelers"] if fl else 0,
        "hotel": ho["price_night_per_room"] * ho["nights"] * ho["rooms"] if ho else 0,
        "activities": sum(it["cost_total"] for d in (state.get("itinerary") or {}).get("days", [])
                          for it in d["items"] if it["type"] == "activity"),
        "food": food_line(c, strategy, state.get("food_boost", False)),
    }
    total = sum(lines.values())
    incomplete = [k for k, v in (("flight", fl), ("hotel", ho)) if v is None]
    return {"currency": "INR", "lines": lines, "total": total, "budget": c["budget"],
            "over_budget": total > c["budget"], "remaining": c["budget"] - total,
            "per_person": round(total / c["travelers"]), "strategy": strategy, "estimated": True,
            "incomplete": incomplete,
            "live": [k for k, blk in (("flight", state.get("flight")), ("hotel", state.get("hotel")))
                     if (blk or {}).get("live") and (blk or {}).get("selected")]}
