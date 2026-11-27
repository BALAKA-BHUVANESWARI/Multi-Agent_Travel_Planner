"""Approval agent: pauses for the traveller, then applies approve, change or cancel."""
from __future__ import annotations

from datetime import date

from app.agents.destination_agent import find_alternatives, find_place, trip_warnings
from app.agents.transport_agent import travel_mode_problem
from app.core import config
from app.core import security as guardrails
from app.core.utils import fmt_inr
from app.graph.state import RESET, entry
from app.services import geo_service as geo_mod
from app.services import request_parser as intake_mod
from app.services.export_service import render_summary
from app.services.feedback_parser import matches_excluded, parse_feedback
from app.observability import recorder as observe


def present_node(state: dict, deps) -> dict:
    br = state.get("budget_report") or {}
    left = config.MAX_REVISIONS - state.get("revisions", 0)
    msg = (f"Plan ready: {fmt_inr(br.get('total', 0))} estimated of {fmt_inr(br.get('budget', 0))} budget. "
           f"Approve to book (mock), or request changes ({max(left, 0)} revision(s) left).")
    if state.get("notice"):
        msg = f"{state['notice']} {msg}"
    alternatives = find_alternatives(state, deps)
    return {"status": "awaiting_approval", "approved": False, "message": msg, "notice": "",
            "alternatives": alternatives,
            "pending_approval": {"can_revise": left > 0, "revisions_left": max(left, 0),
                                 "auto_replans_used": state.get("retries", 0)},
            "summary": render_summary({**state, "alternatives": alternatives}),
            "log": [entry("present", "awaiting human approval")]}


def _apply_changes(state: dict, ch: dict, notes: list[str], deps) -> tuple[dict, dict, list[str]]:
    """Check each requested change and apply the possible ones.
    Returns (state update, applied changes, plain-language notes)."""
    c = dict(state["constraints"])
    ch = dict(ch)
    notes = list(notes)

    def reject(key: str, word: str, why: str) -> None:
        ch.pop(key, None)
        observe.event("guardrail", "change_not_possible", "rejected", detail=why or None, change=key)
        notes[:] = [n for n in notes if word not in n]
        notes.append(why)

    if "days" in ch and not config.MIN_DAYS <= ch["days"] <= config.MAX_DAYS:
        reject("days", " days.", f"I can plan trips of {config.MIN_DAYS} to {config.MAX_DAYS} days.")
    if "travelers" in ch and not 1 <= ch["travelers"] <= config.MAX_TRAVELERS:
        reject("travelers", " travelers.", f"I can plan for 1 to {config.MAX_TRAVELERS} travelers.")
    if "travelers" in ch and state.get("group") and ch["travelers"] < len(state["group"]):
        reject("travelers", " travelers.", f"Your group list has {len(state['group'])} people. Start a new plan "
                                           "to change who is in the group.")
    for key in ("budget", "pace", "days", "travelers"):
        if key in ch:
            c[key] = ch[key]
    if "month_day" in ch:
        month, day = ch["month_day"]
        start, _ = intake_mod.compute_start_date(month, day, date.fromisoformat(c["today"]))
        if start.isoformat() == c["start_date"]:
            reject("month_day", "travel dates", "The trip already starts on that date.")
        else:
            c.update(start_date=start.isoformat(), month=month)
            notes[:] = [f"Trip now starts {start.isoformat()}." if "travel dates" in n else n for n in notes]
    if "destination" in ch:
        geo, why = find_place(ch["destination"], deps)
        meant = geo and geo_mod.meant_instead(ch["destination"], geo)
        if geo is None:
            reject("destination", "destination to", why)
        elif meant:
            reject("destination", "destination to",
                   f"I only found “{ch['destination']}” as a very small place: {geo_mod.full_label(geo)}. "
                   f"For {geo_mod.full_label(meant)}, type “change destination to {meant['name']}”. If you really "
                   "mean the small place, start a new plan.")
        elif geo["slug"] == c["destination"]:
            reject("destination", "destination to", f"The trip already goes to {geo['name']}.")
        elif geo["slug"] == c["origin"] or (c.get("origin_geo")
                                            and geo_mod.distance_km(c["origin_geo"], geo) < 15):
            reject("destination", "destination to", "Origin and destination are the same place.")
        else:
            c.update(destination=geo["slug"], destination_geo=geo)
    if "travel_mode" in ch:
        c["travel_mode"] = ch["travel_mode"]
    if "destination" in ch or "travel_mode" in ch:
        why = travel_mode_problem(c, deps)
        if why:
            old = state["constraints"]
            if "destination" in ch:
                c.update(destination=old["destination"], destination_geo=old.get("destination_geo"))
                reject("destination", "destination to", why + " Add 'go by flight' to change both together.")
            if "travel_mode" in ch:
                c["travel_mode"] = old.get("travel_mode")
                reject("travel_mode", "Travelling by", "" if why in " ".join(notes) else why)

    excluded = list(state.get("excluded") or [])
    if "exclude" in ch:
        cands = (state.get("activities") or {}).get("candidates", [])
        found = []
        for term in ch["exclude"]:
            if any(matches_excluded(x, term) for x in cands):
                found.append(term)
                notes.append(f"Leaving out: {term}.")
                c["preferences"] = [p for p in c.get("preferences", []) if p != term]
            else:
                notes.append(f"Nothing in this plan matches '{term}'.")
        excluded = list(dict.fromkeys(excluded + found))
        if found:
            ch["exclude"] = found
        else:
            ch.pop("exclude")
    if ch.get("preferences_add"):
        c["preferences"] = list(dict.fromkeys(list(c["preferences"]) + ch["preferences_add"]))
    if "travelers" in ch and "budget" not in ch:
        notes.append(f"The total budget stays {fmt_inr(c['budget'])}.")

    update: dict = {"constraints": c, "excluded": excluded}
    if {"destination", "days", "month_day"} & set(ch):
        update["weather"] = None                                   # dates or place moved: fetch weather again
    if "destination" in ch:
        update.update(activities=None, excluded=[])
    if {"destination", "days", "month_day", "travel_mode"} & set(ch):
        update["warnings"] = [RESET] + trip_warnings(c)           # old trip warnings no longer apply
    return update, ch, [n for n in notes if n]


def approval_node(state: dict, decision: dict, deps=None) -> dict:
    """Apply the human's decision. A function of (state, decision); ``deps`` is only used to check that a new
    destination or travel mode is possible."""
    action = (decision or {}).get("action")
    base = {"decision": decision}
    if action == "approve":
        return {**base, "approved": True, "replan_reason": None, "log": [entry("approval", "approved")]}
    if action == "cancel":
        return {**base, "status": "cancelled", "approved": False, "replan_reason": None,
                "message": "Trip cancelled. Nothing was booked.", "log": [entry("approval", "cancelled")]}
    if action != "revise":
        return {**base, "replan_reason": None, "notice": "Unknown action. Use approve, revise or cancel.",
                "log": [entry("approval", f"unknown action {action!r}")]}
    text = (decision.get("feedback") or "").strip()
    g = guardrails.check_input(text, require_topic=False)
    observe.event("guardrail", "feedback_check", "ok" if g["allowed"] else "blocked", code=g["code"])
    if not g["allowed"]:
        return {**base, "replan_reason": None, "notice": g["message"],
                "log": [entry("approval", f"feedback blocked: {g['code']}")]}
    if state.get("revisions", 0) >= config.MAX_REVISIONS:
        observe.event("guardrail", "revision_limit", "blocked")
        return {**base, "replan_reason": None, "pending_approval": {"can_revise": False, "revisions_left": 0,
                                                                     "auto_replans_used": state.get("retries", 0)},
                "warnings": ["Revision limit reached: approve this plan or cancel."],
                "notice": "Revision limit reached: approve this plan or cancel.",
                "log": [entry("approval", "revision cap reached")]}
    fb = parse_feedback(text, state["constraints"], state.get("strategy", "normal"))
    if not fb["recognized"]:
        observe.event("guardrail", "feedback_understood", "rejected")
        return {**base, "replan_reason": None,
                "notice": "I couldn't tell what to change. Try: 'make it cheaper', 'budget 80000', 'make it 4 "
                          "days', 'add 1 person', 'move it to January', 'go by train', 'change destination to "
                          "Jaipur', 'skip water sports', 'more food' or 'relaxed pace'.",
                "log": [entry("approval", "feedback not understood")]}
    update, ch, notes = _apply_changes(state, fb["changes"], fb["notes"], deps) if fb["changes"] \
        else ({}, {}, fb["notes"])
    if not ch:                      # recognised but nothing to do (e.g. already cheapest, or not possible)
        return {**base, "replan_reason": None, "notice": " ".join(notes),
                "log": [entry("approval", "no-op feedback: " + " ".join(notes))]}
    return {**base, **update, "strategy": ch.get("strategy", state.get("strategy", "normal")),
            "food_boost": ch.get("food_boost", state.get("food_boost", False)),
            "revisions": state.get("revisions", 0) + 1, "replan_reason": "feedback", "approved": False,
            "status": "running", "notice": " ".join(notes),
            "log": [entry("approval", "revise: " + " ".join(notes))]}
