"""Change requests: is the right thing changed, is everything else kept, is what depends on it worked out again,
and did only the agents that were needed run?

Each case has one ``aspect`` so that a wrong plan and wasted work are never mixed up:

* ``result``: the new plan itself.
* ``agents``: which worker agents ran again, against the expected affected set.
"""
from __future__ import annotations

from datetime import date, timedelta

from evaluation import harness
from evaluation.evaluators import budget, common
from evaluation.evaluators.common import Checks
from evaluation.evaluators.end_to_end import check_handover
from evaluation.results import Result

NOT_UNDERSTOOD = "couldn't tell what to change"


def _make(given: dict) -> dict:
    run = harness.run_change(given["request"], given["changes"], group=given.get("group"))
    for change in given.get("damage", []):
        common.damage(run, change)
    return run


def _activities(state: dict) -> list[dict]:
    return [i for _, i in common.planned_activities(state)]


def _part(state: dict, name: str):
    """The part of a plan that a change may have to leave alone."""
    if name == "activities":
        return sorted(i["name"] for i in _activities(state))
    if name == "weather":
        return state["weather"]["days"]
    selected = (state.get(name) or {}).get("selected") or {}
    keys = (("id", "mode", "price_pp", "depart_out", "arrive_out", "depart_back") if name == "flight"
            else ("id", "label", "price_night_per_room"))
    return {k: selected.get(k) for k in keys}


def check_untouched(checks: Checks, before: dict, after: dict, expected: dict) -> None:
    """Requirements the traveller did not ask to change stay as they were."""
    changed = expected.get("changed") or {}
    for key, value in changed.items():
        checks.same("change_missing", f"requirement '{key}' after the change", after["constraints"].get(key), value)
    allowed = set(changed) | set(expected.get("may_change", []))
    moved = {k: (before["constraints"][k], after["constraints"].get(k)) for k in before["constraints"]
             if k not in allowed and before["constraints"][k] != after["constraints"].get(k)}
    checks.need(not moved, "unintended_change", f"requirements changed without being asked: {moved}")
    for name in expected.get("keep", []):
        old, new = _part(before, name), _part(after, name)
        checks.need(old == new, "unintended_change", f"the {name} should have stayed the same: was {old}, "
                                                     f"now {new}")
    if "keep_activity_share" in expected:
        old = set(_part(before, "activities"))
        kept = len(old & set(_part(after, "activities"))) / len(old)
        checks.measured["kept_activities_share"] = round(kept, 2)
        checks.need(kept >= float(expected["keep_activity_share"]), "unintended_change",
                    f"only {kept:.0%} of the earlier activities are still planned")


def check_effect(checks: Checks, before: dict, after: dict, expected: dict) -> None:
    """The change did what was asked."""
    for wanted in expected.get("effects", []):
        if wanted == "cheaper_hotel":
            old, new = _part(before, "hotel"), _part(after, "hotel")
            checks.need(new["price_night_per_room"] < old["price_night_per_room"], "no_effect",
                        "the hotel is not cheaper")
        elif wanted == "cheaper_travel":
            old, new = _part(before, "flight"), _part(after, "flight")
            checks.need(new["price_pp"] < old["price_pp"], "no_effect", "the travel is not cheaper")
        elif wanted == "within_budget":
            checks.need(after["budget_report"]["total"] <= after["constraints"]["budget"], "no_effect",
                        "the new plan does not fit the new budget")
        elif wanted == "more_activities":
            checks.need(len(_activities(after)) > len(_activities(before)), "no_effect",
                        "no activity was added for the extra days")
        elif wanted == "new_places":
            both = set(_part(before, "activities")) & set(_part(after, "activities"))
            checks.need(not both, "stale_data", f"places of the old destination are still planned: {sorted(both)}")
        else:
            raise ValueError(f"unknown effect {wanted}")
    for tag in expected.get("no_tag", []):
        left = [i["name"] for i in _activities(after) if tag in i.get("tags", [])]
        checks.need(not left, "no_effect", f"'{tag}' activities are still planned: {left}")
    for tag in expected.get("more_of_tag", []):
        old = sum(tag in i.get("tags", []) for i in _activities(before))
        new = sum(tag in i.get("tags", []) for i in _activities(after))
        checks.need(new > old, "no_effect", f"'{tag}' activities: {old} before, {new} after")
    if expected.get("no_outdoor"):
        left = [i["name"] for i in _activities(after) if i.get("outdoor")]
        checks.need(not left, "no_effect", f"outdoor activities are still planned: {left}")
    if "mode" in expected:
        checks.same("no_effect", "way of travelling", _part(after, "flight")["mode"], expected["mode"])


def check_recalculated(checks: Checks, run: dict, limits: dict) -> None:
    """Everything that depends on the change was worked out again and agrees."""
    after = run["state"]
    c = after["constraints"]
    check_handover(checks, run)
    first = date.fromisoformat(c["start_date"])
    wanted = [(first + timedelta(days=i)).isoformat() for i in range(c["days"])]
    checks.same("not_recalculated", "dates of the day plan", [d["date"] for d in after["itinerary"]["days"]], wanted)
    checks.same("not_recalculated", "dates with weather", [d["date"] for d in after["weather"]["days"]], wanted)
    hotel = after["hotel"]["selected"]
    checks.same("not_recalculated", "hotel nights", hotel["nights"], c["days"] - 1)
    checks.same("not_recalculated", "hotel rooms", hotel["rooms"], -(-c["travelers"] // 2))
    wrong = budget.compare_report(budget.calculate(budget.trip_from_state(
        after, limits["food_per_person_day"], budget.money(limits.get("food_boost", "1.25")))),
        after["budget_report"])
    checks.need(not wrong, "budget_inconsistent", "; ".join(wrong))
    seen = [i["id"] for i in _activities(after) if i["id"] != "generic-indoor"]
    checks.need(len(seen) == len(set(seen)), "itinerary_inconsistent", "a place is planned twice after the change")
    for day in after["itinerary"]["days"]:
        items = sorted(day["items"], key=lambda i: i["start_min"])
        checks.need(all(b["start_min"] >= a["end_min"] for a, b in zip(items, items[1:])),
                    "itinerary_inconsistent", f"things overlap on day {day['day']} after the change")


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    before, after = run["before"], run["state"]
    message = str(after.get("message", ""))
    checks.measured.update(applied=run["applied"], agents_run=run["ran"])
    if expected.get("refused"):                                  # the right answer is to change nothing
        checks.need(not run["applied"], "should_refuse", "the change was applied although it must not be")
        for words in expected["says"]:
            checks.need(words.lower() in message.lower(), "refusal_not_explained",
                        f"the answer does not say '{words}': {message!r}")
        check_untouched(checks, before, after, {"keep": ["flight", "hotel", "weather", "activities"]})
        return
    if not run["applied"]:
        honest = NOT_UNDERSTOOD in message
        unchanged = all(_part(before, n) == _part(after, n) for n in ("flight", "hotel", "weather", "activities")) \
            and before["constraints"] == after["constraints"]
        if expected.get("capability") and honest and unchanged:
            checks.unsupported("change", f"the planner cannot {expected['capability']}: it said it could not tell "
                                         "what to change, and kept the plan as it was")
        else:
            checks.need(False, "change_not_applied", f"the change was not made: {message.split('Plan ready')[0]!r}")
        return
    if expected["aspect"] == "agents":
        need, may = set(expected["agents"]), set(expected.get("may_run", []))
        ran = set(run["ran"])
        checks.need(need <= ran, "agent_not_rerun", f"affected agents that did not run again: {sorted(need - ran)}")
        extra = ran - need - may
        checks.need(not extra, "unnecessary_rerun", f"agents ran again although the change does not affect them: "
                                                    f"{sorted(extra)}")
        return
    check_untouched(checks, before, after, expected)
    check_effect(checks, before, after, expected)
    check_recalculated(checks, run, limits)
    checks.need(after.get("revisions") == before.get("revisions", 0) + 1, "change_count",
                "the change was not counted as one revision")
    if expected.get("needs_versions"):
        if not after.get("versions") and "version" not in after:
            checks.unsupported("versions", "the planner keeps no trip versions: the earlier plan is overwritten")


def evaluate(case: dict) -> Result:
    return common.judge(case, check, _make)
