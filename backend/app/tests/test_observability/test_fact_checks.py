"""The made-up fact checks: what they flag, what they leave alone, and that they never change a plan."""
import json
import re

import pytest

from app.observability import recorder as observe
from app.observability.store import RecordStore
from app.services import chat_service, fact_checks
from app.services.export_service import render_summary
from app.services.trip_service import PlannerService
from app.tests.conftest import FakeTransport

GOA = "Plan a 3 day trip to Goa from Delhi in December, budget 90000 for 2 by flight"

PLAN = [{"trip": {"from": "Delhi", "to": "Goa", "days": 3, "start_date": "2026-12-15"},
         "budget": "Total ₹28,400 of ₹30,000",
         "itinerary": [{"day": 1, "items": [{"name": "Fort Aguada", "about": "A fort near Sinquerim Beach"},
                                            {"name": "Basilica of Bom Jesus"}]},
                       {"day": 2, "items": [{"name": "Baga Beach"}]}]}]


def flags(text, question=""):
    leaves = fact_checks._leaves(PLAN)
    found = (fact_checks.check_amounts(text, fact_checks.numbers_in(leaves))[0]
             + fact_checks.check_dates(text, leaves, "2026-12-15", 3)[0]
             + fact_checks.check_day_counts(text, leaves, 3)[0]
             + fact_checks.check_places(text, leaves, question)[0])
    return [(f["kind"], f["value"]) for f in found]


@pytest.mark.parametrize("text", [
    "Your 3-day Goa trip costs about ₹28,400, within your ₹30,000 budget.",
    "Day 1 starts at Fort Aguada, then the Basilica of Bom Jesus. Day 2 is Baga Beach.",
    "Enjoy three days from Delhi; two nights of hotel stay are included.",
    "One day you could relax. You may 2 times visit the beach.",
    "It is about ₹28.4k. Check in on 2026-12-15 and leave on 17th of December.",
    "Sources: Wikivoyage and OpenStreetMap.",
])
def test_text_that_matches_the_plan_is_not_flagged(text):
    assert flags(text) == []


@pytest.mark.parametrize("text, expected", [
    ("It costs Rs 25,000.", [("amounts", "Rs 25,000")]),
    ("It costs 25000 rupees.", [("amounts", "25000 rupees")]),
    ("Your budget is ₹3 lakh.", [("amounts", "₹3 lakh")]),
    ("You come back on 18 December.", [("dates", "18 December")]),
    ("You leave on Dec 15, 2027.", [("dates", "Dec 15, 2027")]),
    ("Spend 4 days there.", [("day_counts", "4 days")]),
    ("On Day 5, rest.", [("day_counts", "Day 5")]),
    ("Visit Dudhsagar Falls and Chapora Fort.", [("places", "Dudhsagar Falls"), ("places", "Chapora Fort")]),
    ("Then fly on to Mumbai.", [("places", "Mumbai")]),
])
def test_details_that_are_not_in_the_plan_are_flagged(text, expected):
    assert flags(text) == expected


def test_a_place_the_traveller_asked_about_is_not_flagged():
    assert flags("The plan does not include Hampi.", "is Hampi on the plan?") == []
    assert flags("The plan does not include Hampi.") == [("places", "Hampi")]


@pytest.mark.parametrize("request_text", [
    "3 days in Goa from Delhi, budget 30000 for 2",
    "5 days in Paris from Mumbai in March, budget 4 lakh, museums",
    "4 days in Manali from Delhi in January, budget 60000 by bus",
])
def test_text_written_by_the_planner_itself_is_not_flagged(make, request_text):
    """Text built only from the plan (no AI) is the best test for false alarms."""
    svc = PlannerService(make(), require_auth=False, recorder=None)
    state = svc.planner.get(svc.plan(request_text)["thread_id"])
    c = state["constraints"]
    leaves = fact_checks._leaves([chat_service.plan_facts(state), state["flight"].get("journey")])
    from app.agents.itinerary_agent import _allowed_amounts
    asked = ["show day 1", "what is the total cost?", "which hotel?", "what is the weather?"]
    for text in [render_summary(state), *filter(None, (chat_service.rule_answer(state, q) for q in asked))]:
        found = (fact_checks.check_amounts(text, fact_checks.numbers_in(leaves) | _allowed_amounts(state))[0]
                 + fact_checks.check_dates(text, leaves, c["start_date"], c["days"])[0]
                 + fact_checks.check_day_counts(text, leaves, c["days"])[0]
                 + fact_checks.check_places(text, leaves)[0])
        assert found == [], text[:60]


@pytest.mark.parametrize("text, filled, expected", [
    ("3 days in goa from delhi under 30k", {"origin": "Delhi", "destination": "Goa", "days": 3, "budget": 30000}, []),
    ("a week in bombay, 20000 per person for 2, we love temples",
     {"destination": "Mumbai", "days": 7, "budget": 40000, "preferences": ["spiritual", "food"]},
     [("preferences", "interest: food")]),
    ("trip to jaipor for three nights", {"destination": "Jaipur", "days": 4, "budget": 50000, "origin": "Pune"},
     [("budget", "budget: 50000"), ("places", "origin: Pune")]),
    ("somewhere to start the new year", {"days": 5, "preferences": ["culture", "nightlife"]},
     [("days", "days: 5"), ("preferences", "interest: culture"), ("preferences", "interest: nightlife")]),
])
def test_values_the_ai_read_from_a_request(text, filled, expected):
    found, looked, _ = fact_checks.check_request_values(text, filled)
    assert [(f["kind"], f["value"]) for f in found] == expected
    assert sum(looked.values()) >= len(filled)


def test_a_corrected_spelling_is_counted_but_not_flagged():
    found, _, corrected = fact_checks.check_request_values("trip to jaipor", {"destination": "Jaipur"})
    assert found == [] and corrected == 1


# ------------------------------------------------------------------ through the planner, with a pretend AI
def pretend_ai(overview="Spend 9 days there and see Hawa Mahal Palace for Rs 5.", answer="Yes, on 25 December.",
               order=("made-up-id",)):
    def reply(body):
        body = body if isinstance(body, dict) else json.loads(body)
        system = body["messages"][0]["content"]
        if system.startswith("Write a friendly"):
            return 200, {"overview": overview}
        if system.startswith("You answer"):
            return 200, {"answer": answer}
        if system.startswith("Extract trip"):
            return 200, {}
        return 200, {"order": list(order)}
    return FakeTransport({"groq": reply, "googleapis": reply})


def ai_service(make, details=False, transport=None, records=True):
    planner = make(env={"GROQ_API_KEY": "k" * 20, "GEMINI_API_KEY": "g" * 20}, transport=transport or pretend_ai())
    recorder = observe.Recorder(RecordStore(":memory:"), details) if records else None
    return PlannerService(planner, require_auth=False, recorder=recorder)


def checks(svc, job):
    return [s for s in svc.recorder.store.spans() if s["type"] == "fact_check" and s["name"] == job]


def full_trip(svc):
    state = svc.plan(GOA)
    booked = svc.approve(state["thread_id"], {"action": "approve"})
    asked = svc.chat({"message": "is it a good plan for my grandmother?", "thread_id": state["thread_id"]})
    return booked, asked


def test_ai_text_is_checked_and_flags_are_counted(make):
    svc = ai_service(make)
    booked, asked = full_trip(svc)
    summary = checks(svc, "summary")[0]
    assert summary["status"] == "flagged" and summary["attrs"]["shown"] is False     # rejected for the amount
    assert {"amounts", "day_counts", "places"} <= set(summary["attrs"]["kinds"])
    assert "Hawa Mahal" not in booked["summary"]
    chat = checks(svc, "chat")[0]
    assert chat["status"] == "flagged" and chat["attrs"] == {"shown": True, "flags": 1, "kinds": {"dates": 1},
                                                            "looked_at": {"dates": 1}}
    assert asked["reply"] == "Yes, on 25 December."                                  # shown unchanged
    ranking = checks(svc, "ranking")[0]
    assert ranking["status"] == "flagged" and ranking["attrs"]["kinds"] == {"unknown_ids": 1}
    stored = json.dumps([svc.recorder.store.spans(), svc.recorder.store.details()])
    for words in ("Hawa Mahal", "25 December", "grandmother", "made-up-id"):
        assert words not in stored                              # without RECORD_DETAILS no text is kept
    assert svc.recorder.errors == 0


def test_examples_are_kept_only_with_detailed_records(make):
    svc = ai_service(make, details=True)
    full_trip(svc)
    summary = checks(svc, "summary")[0]
    kept = {d["name"]: d["content"] for d in svc.recorder.store.details() if d["span_id"] == summary["id"]}
    assert "Hawa Mahal Palace" in kept["flags"] and "Spend 9 days" in kept["ai_text"]


def test_a_matching_ai_summary_is_marked_ok(make):
    svc = ai_service(make, transport=pretend_ai(overview="A relaxed 3 day break in Goa from Delhi."))
    full_trip(svc)
    assert checks(svc, "summary")[0]["status"] == "ok"
    assert checks(svc, "summary")[0]["attrs"]["shown"] is True


def test_checks_do_not_change_what_the_traveller_sees(make):
    def seen(svc):
        booked, asked = full_trip(svc)
        summary = re.sub(r"MOCK-[0-9A-F]+", "MOCK", booked["summary"])      # booking ids are random on every run
        return summary, booked["itinerary"], asked["reply"]
    assert seen(ai_service(make)) == seen(ai_service(make, records=False))


def test_a_broken_check_never_breaks_a_plan(make, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bug in a check")
    for name in ("check_places", "check_request_values"):
        monkeypatch.setattr(fact_checks, name, broken)
    svc = ai_service(make)
    booked, asked = full_trip(svc)
    assert booked["status"] == "booked" and asked["reply"] == "Yes, on 25 December."
    assert checks(svc, "summary")[0]["status"] == "error"


def test_nothing_is_checked_when_nothing_is_recorded(make, monkeypatch):
    monkeypatch.setattr(fact_checks, "check_places", lambda *a: pytest.fail("should not run"))
    booked, _ = full_trip(ai_service(make, records=False))
    assert booked["status"] == "booked"
