"""Post-Trip Expense Analysis: what was really spent, against what the plan estimated. All amounts in rupees."""
from __future__ import annotations

import csv
import io
import math
from datetime import date

from .. import guardrails

CATEGORIES = ("travel", "hotel", "activities", "food", "other")
PLAN_LINE = {"travel": "flight", "hotel": "hotel", "activities": "activities", "food": "food"}
LABELS = {"travel": "Travel to and from", "hotel": "Hotel", "activities": "Activities", "food": "Food",
          "other": "Other (local transport, shopping, fees)"}
MAX_AMOUNT = 10_000_000
MAX_ENTRIES = 300
NOTE = "Enter amounts in rupees. For foreign spending, use the rupee figure from your card or exchange receipt."


def clean_entry(raw: dict, today: date) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("send the expense as a JSON object")
    category = raw.get("category")
    if category not in CATEGORIES:
        raise ValueError("choose a category: " + ", ".join(CATEGORIES))
    amount = raw.get("amount")
    if isinstance(amount, str):
        try:
            amount = float(amount.replace(",", "").strip())
        except ValueError:
            amount = None
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) \
            or not 0 < amount <= MAX_AMOUNT:
        raise ValueError(f"enter an amount in rupees between 1 and {MAX_AMOUNT:,}")
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("the amount must be more than zero")
    note = str(raw.get("note") or "")
    if guardrails._sensitive(note):
        raise ValueError("please don't type card, ID or password details in the note")
    note = " ".join(guardrails._CTRL.sub(" ", note).split())[:120]
    when = raw.get("date") or today.isoformat()
    try:
        spent = date.fromisoformat(str(when))
    except ValueError:
        raise ValueError("the date must look like 2027-03-31")
    return {"category": category, "amount": amount, "note": note, "date": spent.isoformat()}


def _money(x: float) -> int:
    return int(round(x))


def _insights(rows: list[dict], total: dict, travelers: int, days: int, finished: bool) -> list[str]:
    spent = [r for r in rows if r["entries"]]
    if not spent:
        return ["Add what you spend to see how the plan's estimate compares."]
    out = []
    planned_rows = [r for r in spent if r["planned"] > 0]
    over = max(planned_rows, key=lambda r: r["difference"], default=None)
    under = min(planned_rows, key=lambda r: r["difference"], default=None)
    if over and over["difference"] > 0:
        out.append(f"{over['label']} ran furthest over its estimate: ₹{over['difference']:,} more.")
    if finished and under and under["difference"] < 0:
        out.append(f"{under['label']} came in furthest under its estimate: ₹{-under['difference']:,} less.")
    other = next(r for r in rows if r["category"] == "other")
    if other["actual"]:
        out.append(f"₹{other['actual']:,} went on things the plan did not estimate (the 'Other' category).")
    missing = [r["label"].lower() for r in rows if r["planned"] > 0 and not r["entries"]]
    if missing:
        out.append(("Nothing was recorded for " if finished else "Nothing recorded yet for ")
                   + ", ".join(missing) + ", so the totals do not cover the whole trip.")
    food = next(r for r in rows if r["category"] == "food")
    if finished and food["actual"]:
        each = _money(food["actual"] / max(1, travelers) / max(1, days))
        out.append(f"Your recorded food spending was about ₹{each:,} per person per day: a useful figure for "
                   "your next budget.")
    if finished and not missing:
        gap = total["actual"] - total["planned"]
        if total["planned"]:
            out.append(f"Overall you spent {abs(gap) / total['planned']:.0%} "
                       f"{'more' if gap > 0 else 'less'} than the plan estimated.")
    return out


def summary(budget_report: dict, constraints: dict, entries: list[dict], today: date, end: date,
            cancelled: bool = False) -> dict:
    planned_lines = budget_report.get("lines") or {}
    rows = []
    for category in CATEGORIES:
        planned = _money(planned_lines.get(PLAN_LINE.get(category, ""), 0) or 0)
        mine = [e for e in entries if e["category"] == category]
        actual = _money(sum(e["amount"] for e in mine))
        rows.append({"category": category, "label": LABELS[category], "planned": planned, "actual": actual,
                     "entries": len(mine), "difference": actual - planned,
                     "percent_of_plan": round(100 * actual / planned) if planned else None})
    planned_total = _money(budget_report.get("total") or 0)
    actual_total = _money(sum(e["amount"] for e in entries))
    budget = _money(constraints.get("budget") or budget_report.get("budget") or 0)
    travelers = constraints.get("travelers") or 1
    days = constraints.get("days") or 1
    finished = today > end
    total = {"planned": planned_total, "actual": actual_total, "difference": actual_total - planned_total,
             "budget": budget, "budget_left": budget - actual_total,
             "per_person": _money(actual_total / travelers), "per_day": _money(actual_total / days)}
    notes = _insights(rows, total, travelers, days, finished)
    if cancelled:
        notes.insert(0, "This trip's booking was cancelled; the comparison is with the plan as it stood.")
    return {"stage": "final" if finished else "so far", "categories": rows, "total": total, "insights": notes,
            "note": NOTE}


def to_csv(entries: list[dict]) -> str:
    """The entries as CSV. A cell that a spreadsheet would run as a formula is prefixed with a quote."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(["date", "category", "amount_inr", "note"])
    for e in entries:
        note = e.get("note", "")
        if note[:1] in ("=", "+", "-", "@"):
            note = "'" + note
        writer.writerow([e["date"], e["category"], f"{e['amount']:.2f}", note])
    return buf.getvalue()
