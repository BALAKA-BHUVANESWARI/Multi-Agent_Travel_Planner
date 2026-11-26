"""Itinerary agent: builds the day-by-day plan and writes the final summary."""
from __future__ import annotations

import re

from app.agents.common import llm_note
from app.core import security as guardrails
from app.data.curated_destinations import place_name
from app.graph.state import entry
from app.services import group_service as group_mod
from app.services.export_service import render_summary
from app.services.itinerary_builder import build_itinerary


def merge_node(state: dict, deps) -> dict:
    c = state["constraints"]
    flight = (state.get("flight") or {}).get("selected")
    hotel = (state.get("hotel") or {}).get("selected")
    cands = (state.get("activities") or {}).get("candidates", [])
    itin, warns = build_itinerary(c, flight, hotel, state.get("weather"), cands)
    nact = sum(1 for d in itin["days"] for it in d["items"] if it["type"] == "activity")
    log = [entry("merge", f"{len(itin['days'])} days, {nact} activities, {len(itin['swaps'])} rain swaps")]
    group = state.get("group") or []
    report = group_mod.satisfaction(group, itin) if group else []
    for m in report:
        if m["likes"] and not m["matched"]:
            warns.append(f"Group: nothing planned matches what {m['name']} likes ({', '.join(m['likes'])}). "
                         "No suitable place fitted the dates and budget tier.")
    return {"itinerary": itin, "group_report": report, "warnings": warns, "log": log}


_WRITER_SCHEMA = {"type": "object", "required": ["overview"],
                  "properties": {"overview": {"type": "string"}}}


def numbers_are_grounded(text: str, allowed: set[int]) -> bool:
    """Every rupee amount in LLM text must be one of the plan's own figures."""
    for m in re.finditer(r"₹\s?([\d,]+)", text):
        try:
            if int(m.group(1).replace(",", "")) not in allowed:
                return False
        except ValueError:
            return False
    return not re.search(r"\b(?:rs\.?|inr)\s?\d", text, re.I)


def _allowed_amounts(state: dict) -> set[int]:
    br = state["budget_report"]
    vals = set(br["lines"].values()) | {br["total"], br["budget"], br["per_person"], abs(br["remaining"])}
    fl = (state.get("flight") or {}).get("selected")
    ho = (state.get("hotel") or {}).get("selected")
    if fl:
        vals.add(fl["price_pp"])
    if ho:
        vals.add(ho["price_night_per_room"])
    for d in state["itinerary"]["days"]:
        for it in d["items"]:
            if it["type"] == "activity":
                vals.update({it["cost_pp"], it["cost_total"]})
    return vals


def writer_node(state: dict, deps) -> dict:
    template = render_summary(state)
    overview, used = "", False
    if deps.llm and deps.llm.available("writer"):
        import json
        facts = {"destination": place_name(state["constraints"], "destination"),
                 "days": [{"day": d["day"], "date": d["date"],
                           "highlights": [x["name"] for x in d["items"] if x["type"] == "activity"],
                           "rainy": d["rainy"]} for d in state["itinerary"]["days"]],
                 "total_inr": state["budget_report"]["total"], "budget_inr": state["budget_report"]["budget"],
                 "over_budget": state["budget_report"]["over_budget"],
                 "warnings": list(dict.fromkeys(state.get("warnings", [])))}
        system = ("Write a friendly 80-120 word overview of this trip plan. Use ONLY the facts given. Do not "
                  "invent places, prices or times. If you mention money, use the exact rupee figures provided "
                  "with the symbol ₹. Return {\"overview\": \"...\"}.")
        obj = deps.llm.complete_json("writer", system, json.dumps(facts), _WRITER_SCHEMA)
        if obj and numbers_are_grounded(obj["overview"], _allowed_amounts(state)):
            overview, used = guardrails.sanitize_untrusted(obj["overview"], 900), True
    text = (f"{overview}\n\n---\n\n{template}" if overview else template)
    return {"summary": text, "log": [entry("writer", ("LLM overview + template" if used else "template summary")
                                           + llm_note(deps, "writer", used))]}
