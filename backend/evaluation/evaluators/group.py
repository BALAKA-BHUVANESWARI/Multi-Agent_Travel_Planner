"""Group trips: everyone counted, everyone's interests served or the gap said openly, and an honest report."""
from __future__ import annotations

from evaluation.evaluators import common
from evaluation.evaluators.common import Checks
from evaluation.results import Result


def check(checks: Checks, run: dict, limits: dict, expected: dict) -> None:
    state = run["state"]
    if not checks.need(common.plan_made(state), "no_plan", f"no plan was made: {state.get('message', '')}"):
        return
    c = state["constraints"]
    common.expect_requirements(checks, state, expected)
    group = state.get("group") or []
    checks.need(c["travelers"] >= len(group), "traveller_count",
                f"{len(group)} people filled in the group form, but the plan is for {c['travelers']}")
    for tool in ("search_flights", "search_hotels"):
        made = common.calls(run, tool)
        checks.need(bool(made) and made[-1]["args"].get("travelers") == c["travelers"], "traveller_count",
                    f"{tool} was not asked for all {c['travelers']} travellers")
    planned = [i for _, i in common.planned_activities(state)]
    report = {m["name"]: m for m in state.get("group_report") or []}
    checks.same("report_members", "people in the group report", sorted(report), sorted(m["name"] for m in group))
    served, with_likes = 0, 0
    for member in group:
        entry = report.get(member["name"])
        if entry is None:
            continue
        likes, avoid = set(member["likes"]), set(member["avoid"])
        liked = [i["name"] for i in planned if likes & set(i.get("tags", []))]
        clashes = [i["name"] for i in planned if avoid & set(i.get("tags", []))]
        checks.same("report_wrong", f"{member['name']}: activities they like", entry["matched"], liked)
        checks.same("report_wrong", f"{member['name']}: activities they want to avoid", entry["conflicts"], clashes)
        if likes:
            with_likes += 1
            served += bool(liked)
            if not liked:
                checks.need(common.warned(state, member["name"]), "member_ignored",
                            f"nothing matches what {member['name']} likes and no warning says so")
    everyone_avoids = set.intersection(*(set(m["avoid"]) for m in group)) if group else set()
    banned = [i["name"] for i in planned if everyone_avoids & set(i.get("tags", []))]
    checks.need(not banned, "everyone_avoids", f"everybody wants to avoid these, but they are planned: {banned}")
    if with_likes:
        share = served / with_likes
        checks.measured["members_served_share"] = round(share, 2)
        checks.need(share >= limits.get("min_members_served_share", 1.0), "unfair",
                    f"only {served} of {with_likes} people get something they like")
    conflicts = sum(len(m["conflicts"]) for m in report.values())
    checks.measured.update(travelers=c["travelers"], activities=len(planned), disliked_by_someone=conflicts)
    if conflicts:
        checks.warn("conflicting_choices", f"{conflicts} case(s) where a planned activity is something one person "
                                           "wants to avoid (the report shows them)")


def evaluate(case: dict) -> Result:
    return common.judge(case, check)
