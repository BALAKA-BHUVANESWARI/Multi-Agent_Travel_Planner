"""What an AI returns is used only when the plan or the traveller's own words support it."""
import json

import pytest

from app.agents import intake_agent
from app.services import ai_guard, fact_checks
from app.services.export_service import render_summary
from app.services.trip_service import PlannerService
from app.tests.test_observability.test_fact_checks import ai_service, pretend_ai

PLAN = [{"trip": {"from": "Delhi", "to": "Goa", "days": 3, "start_date": "2026-12-15"},
         "hotel": "3-star hotel (Calangute-Baga belt) at ₹2,600 a night", "budget": "Total ₹28,400 of ₹30,000",
         "itinerary": [{"day": 1, "items": [{"name": "Fort Aguada"}, {"name": "Ayurvedic spa session"}]}]}]


def held(text):
    return ai_guard.unsupported(text, PLAN, start_date="2026-12-15", days=3)


@pytest.mark.parametrize("text, kind", [
    ("A lovely break for just 4999 rupees.", "amounts"),
    ("It is only $120.", "amounts"),
    ("Dinner is about 40 euros.", "amounts"),
    ("Stay at the Moonlight Pearl Palace and relax.", "places"),
    ("You come back on 22 December.", "dates"),
    ("Your hotel has a rooftop pool.", "features"),
    ("The hotel is rated 4.9.", "features"),
    ("It is a 5-star hotel.", "features"),
    ("Enjoy free Wi-Fi and breakfast is included.", "features"),
    ("Fort Aguada opens at nine.", "features"),
    ("Amber Fort is wheelchair friendly.", "places"),
    ("The plan does not say much, but your room has a sea view.", "features"),
    ("The plan does not say, although there is a gym.", "features"),
])
def test_unsupported_details_hold_a_text_back(text, kind):
    assert kind in held(text)


@pytest.mark.parametrize("text", [
    "A relaxed 3 day trip to Goa from Delhi for ₹28,400.",
    "Day 1 is Fort Aguada, then an Ayurvedic spa session at your 3-star hotel.",
    "The plan does not say whether your hotel has a pool.",
    "The plan doesn't mention any dress code.",
    "The plan does not provide information about wheelchair access.",
    "Please check with the hotel whether there is parking available.",
    "The plan does not include Hampi.",
    "Spend 2 days enjoying the beach. Happy Travels!",
])
def test_supported_or_honest_text_may_be_shown(text):
    assert held(text) == []


def test_a_check_that_breaks_holds_the_text_back(monkeypatch):
    monkeypatch.setattr(fact_checks, "check_features", lambda *a: 1 / 0)
    assert held("A relaxed trip.") == ["check_failed"]


@pytest.mark.parametrize("words, days", [
    ("3 days in Goa", {3}), ("a 5-day trip", {5}), ("four days", {4}), ("five nights", {6}),
    ("a week in Goa", {7}), ("two weeks", {14}), ("a fortnight", {14}), ("a long weekend", {2, 3}),
    ("3 to 4 days", {3, 4}), ("4d/3n package", {4}), ("days: 6", {6}), ("twenty one days", {21}),
    ("for 5 people in December", set()), ("budget 60000 for 2", set()), ("a trip to Goa", set()),
])
def test_only_a_stated_trip_length_counts(words, days):
    assert ai_guard.stated_days(words) == days


@pytest.mark.parametrize("words, value, ok", [
    ("budget 60000", 60000, True), ("under 60k", 60000, True), ("1.5 lakh in all", 150000, True),
    ("fifty thousand for the trip", 50000, True), ("one and a half lakh", 150000, True),
    ("half a lakh", 50000, True), ("20000 per person for 2", 40000, True), ("two lakhs", 200000, True),
    ("a trip to Goa", 50000, False), ("for 5 people", 50000, False), ("about $5000", 5000, False),
    ("budget 60000", 90000, False),
])
def test_only_a_stated_budget_counts(words, value, ok):
    assert ai_guard.typed_value("budget", value, words) is ok


@pytest.mark.parametrize("words, city, destination, ok", [
    ("Delhi se Goa, 4 days", "Delhi", "goa", True), ("we live in Bombay, Goa please", "Mumbai", "goa", True),
    ("starting at dehli", "Delhi", "goa", True), ("from Delhi to Goa", "Delhi, India", "goa", True),
    ("flying out of Zzqxv to Goa", "Zzqxv", "goa", True), ("a trip to Goa", "Delhi", "goa", False),
    ("a trip to Goa", "Goa", "goa", False), ("a trip to Bombay", "Mumbai", "mumbai", False),
    ("from home to Goa", "Pune", "goa", False), ("a trip from Zzqxv to Goa", "Delhi", "goa", False),
])
def test_only_a_named_starting_city_counts(words, city, destination, ok):
    assert ai_guard.typed_place(city, words, destination) is ok


@pytest.mark.parametrize("words, city, origin, ok", [
    ("Delhi se Goa jana hai", "Goa", "delhi", True), ("4 days in Bombay from Pune", "Mumbai", "pune", True),
    ("from Delhi, Gokarna ghoomna hai", "Gokarna", "delhi", True), ("from Delhi to jaipor", "Jaipur", "delhi", True),
    ("a trip from Delhi", "Goa", "delhi", False), ("a trip from Delhi", "Delhi", "delhi", False),
    ("a trip from Bombay", "Mumbai", "mumbai", False), ("from Delhi to the capital of Rajasthan", "Jaipur", "delhi", False),
])
def test_only_a_named_destination_counts(words, city, origin, ok):
    assert ai_guard.typed_place(city, words, origin) is ok


def ai_reads(values):
    def reply(url, headers, body, timeout):
        body = body if isinstance(body, dict) else json.loads(body)
        wanted = body["messages"][0]["content"].startswith("Extract trip")
        return 200, {"choices": [{"message": {"content": json.dumps(values if wanted else {})}}]}
    return reply


def test_an_unnamed_starting_city_is_asked_for(make):
    svc = ai_service(make, transport=ai_reads({"origin": "Delhi"}), records=False)
    state = svc.plan("Plan a 4 day trip to Goa, budget 60000")
    assert state["status"] == "needs_info" and state["constraints"]["origin"] is None
    assert "starting" in state["message"].lower() or "from" in state["message"].lower()


@pytest.mark.parametrize("words", ["Plan a 4 day trip from Delhi, budget 60000",
                                   "Plan a 4 day trip from Delhi to the capital of Rajasthan, budget 60000"])
def test_an_unnamed_destination_is_never_planned(make, words):
    svc = ai_service(make, transport=ai_reads({"destination": "Jaipur"}), records=False)
    state = svc.plan(words)
    assert state["status"] == "needs_info" and state["constraints"]["destination"] is None


def test_a_destination_the_rules_miss_is_still_read_by_the_ai(make):
    svc = ai_service(make, transport=ai_reads({"destination": "Mumbai"}), records=False)
    state = svc.plan("Plan a 4 day trip from Delhi, budget 60000, Bombay chalte hain")
    assert state["constraints"]["destination"] == "mumbai"


def test_the_saved_home_city_is_used_instead_of_an_invented_one(make):
    parsed = {"constraints": {"origin": None, "destination": None, "days": 4, "budget": 60000, "preferences": []},
              "texts": {"destination": "goa"}, "missing": ["origin"], "invalid": {}, "assumptions": []}
    planner = make(env={"GROQ_API_KEY": "k" * 20}, transport=ai_reads({"origin": "Delhi"}))
    intake_agent._llm_fill_gaps(parsed, "Plan a 4 day trip to Goa, budget 60000", planner.deps)
    intake_agent._apply_memory(parsed, {"home_city": "Pune"}, "Plan a 4 day trip to Goa, budget 60000", [])
    assert parsed["texts"]["origin"] == "Pune"


def test_it_works_with_recording_switched_off(make):
    transport = pretend_ai(overview="Stay at the Moonlight Pearl Palace.", answer="Your hotel has a rooftop pool.")
    svc = ai_service(make, transport=transport, records=False)
    state = svc.plan("Plan a 3 day trip to Goa from Delhi in December, budget 90000 for 2 by flight")
    asked = svc.chat({"message": "does my hotel have a pool?", "thread_id": state["thread_id"]})
    assert asked["source"] == "rules" and "rooftop" not in asked["reply"]
    booked = svc.approve(state["thread_id"], {"action": "approve"})
    assert "Moonlight" not in booked["summary"] and booked["summary"].startswith("# ")


@pytest.mark.parametrize("mode, label", [("train", "Train"), ("bus", "Bus"), ("car", "Car"), ("flight", "Flight")])
def test_the_budget_names_the_way_of_travel(make, mode, label):
    svc = PlannerService(make(), require_auth=False, recorder=None)
    state = svc.planner.get(svc.plan(
        f"Plan a 4 day trip to Jaipur from Delhi in January, budget 90000 for 2 by {mode}")["thread_id"])
    budget = render_summary(state).split("## Budget (estimated)")[1]
    assert f"\n- {label}: ₹" in budget
    assert mode == "flight" or "Flight" not in budget
