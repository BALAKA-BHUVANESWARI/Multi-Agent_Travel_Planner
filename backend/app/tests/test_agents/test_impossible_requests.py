"""A day that does not exist is asked about, "India" gets suggestions, and rain that drops an interest is said."""
from datetime import date

import pytest

from app.services.chat_service import complete_request
from app.services.itinerary_builder import RAIN_NOTE, build_itinerary
from app.services.request_parser import compute_start_date, parse_request, parse_scope

TODAY = date(2026, 11, 24)
BASE = "4 day trip from Delhi to Goa, budget 60000"


def read(extra: str, today: date = TODAY) -> dict:
    return parse_request(f"{BASE}, starting {extra}", today)


@pytest.mark.parametrize("said, why", [
    ("31 February 2027", "February 2027 has only 28 days"),
    ("30th February", "February 2027 has only 28 days"),
    ("February 29", "February 2027 has only 28 days"),
    ("29 February 2027", "February 2027 has only 28 days"),
    ("31 April", "April has only 30 days"),
    ("June 31", "June has only 30 days"),
    ("32nd January", "January has only 31 days"),
    ("31 November", "November has only 30 days"),
])
def test_a_day_that_does_not_exist_is_asked_about(said, why):
    got = read(said)
    assert why in got["invalid"]["date"] and "does not exist" in got["invalid"]["date"]
    assert got["bad_date"].lower() == said.lower()


@pytest.mark.parametrize("said, expected", [
    ("31 January", "2027-01-31"), ("30 April", "2027-04-30"), ("28 February", "2027-02-28"),
    ("31 December", "2026-12-31"), ("29 February 2028", "2028-02-29"),
])
def test_real_days_are_planned_as_said(said, expected):
    got = read(said)
    assert "date" not in got["invalid"] and got["constraints"]["start_date"] == expected


def test_29_february_works_when_the_next_one_exists():
    assert read("29 February", date(2027, 6, 1))["constraints"]["start_date"] == "2028-02-29"
    assert compute_start_date(2, 29, date(2027, 6, 1))[0] == date(2028, 2, 29)


@pytest.mark.parametrize("reply, start", [
    ("28 February", "2027-02-28"), ("make it 1 March instead", "2027-03-01"), ("March", "2027-03-10"),
    ("20/12/2026", "2026-12-20"), ("tomorrow", "2026-11-25"),
])
@pytest.mark.parametrize("wrong", ["31 February 2027", "31/02/2027"])
def test_the_reply_takes_the_place_of_the_wrong_date(wrong, reply, start):
    asked = {"request": f"{BASE}, starting {wrong}", "constraints": {"origin": "delhi", "destination": "goa",
             "days": 4, "budget": 60000, "today": TODAY.isoformat()}}
    request = complete_request(asked, reply)
    assert wrong not in request
    got = parse_request(request, TODAY)
    assert not got["invalid"] and got["constraints"]["start_date"] == start
    assert (got["constraints"]["budget"], got["constraints"]["days"]) == (60000, 4)


@pytest.mark.parametrize("reply", ["ok", "yes", "28", "31 April"])
def test_a_reply_without_a_real_date_is_asked_again(reply):
    asked = {"request": f"{BASE}, starting 31 February", "constraints": {"origin": "delhi", "destination": "goa",
             "days": 4, "budget": 60000, "today": TODAY.isoformat()}}
    assert "date" in parse_request(complete_request(asked, reply), TODAY)["invalid"]


def test_the_planner_asks_only_about_the_date_then_plans(make):
    planner = make()
    state = planner.start(f"{BASE}, starting 31 February 2027")
    assert state["status"] == "needs_info" and "does not exist" in state["message"]
    assert "still need" not in state["message"] and not state.get("itinerary")
    state = planner.start(complete_request(state, "28 February"))
    assert state["status"] == "awaiting_approval"
    assert state["constraints"]["start_date"].endswith("-02-28")


def test_a_change_to_a_day_that_does_not_exist_is_refused(make):
    planner = make()
    state = planner.start(f"{BASE}, starting 10 December")
    before = state["constraints"]["start_date"]
    after = planner.resume(state["thread_id"], {"action": "revise", "feedback": "move it to 31 February"})
    assert after["constraints"]["start_date"] == before and after.get("revisions", 0) == 0
    assert "does not exist" in after["notice"] + after["message"]


@pytest.mark.parametrize("text", [
    "Suggest somewhere in India for 4 days from Mumbai, budget 60000, history",
    "Plan a 4 day trip to India from Mumbai, budget 60000",
    "Anywhere in India, 4 days from Mumbai, budget 60000",
    "4 days from Mumbai, budget 60000 | destination: India",
])
def test_india_is_where_to_look_not_a_destination(text):
    got = parse_request(text, TODAY)
    assert got["constraints"]["destination"] is None and "destination" not in got["texts"]
    assert got["missing"] == ["destination"] and parse_scope(text) == "india"


@pytest.mark.parametrize("text, scope", [
    ("somewhere abroad from Delhi, I live in India", "abroad"), ("a place outside India", "abroad"),
    ("a trip from Delhi", "any"),
])
def test_other_scopes_are_unchanged(text, scope):
    assert parse_scope(text) == scope


def test_a_named_place_in_india_is_still_planned():
    assert parse_request("4 days in India, to Goa from Delhi, budget 60000", TODAY)["constraints"]["destination"] \
        == "goa"


# ------------------------------------------------------------------ rain
def place(n, tags, outdoor):
    return {"id": f"p{n}", "name": f"Place {n}", "tags": tags, "outdoor": outdoor, "slot": "any", "hours": 2,
            "cost": 100}


def built(prefs, rainy):
    constraints = {"days": 3, "travelers": 1, "start_date": "2027-07-01", "destination": "goa", "preferences": prefs}
    weather = {"days": [{"date": f"2027-07-0{i + 1}", "rainy": r} for i, r in enumerate(rainy)]}
    places = [place(1, ["beach"], True)] + [place(n, ["history"], False) for n in range(2, 12)]
    return build_itinerary(constraints, None, None, weather, places)


def rain_notes(warnings):
    return [w for w in warnings if w.startswith(RAIN_NOTE)]


def test_an_interest_lost_to_rain_is_said_with_the_reason():
    itin, warnings = built(["beach", "history"], [True, True, True])
    note, = rain_notes(warnings)
    assert "interest in beach." in note and "all 3 days" in note and "Place 1" in note
    assert not any(it.get("id") == "p1" for d in itin["days"] for it in d["items"])


@pytest.mark.parametrize("prefs, rainy", [
    (["beach"], [False, False, False]),            # served
    (["beach"], [True, False, False]),             # moved to a dry day, so nothing is lost
    (["history"], [True, True, True]),             # served indoors
    (["shopping"], [True, True, True]),            # nothing was found for it: rain is not the reason
    ([], [True, True, True]),
])
def test_rain_is_only_blamed_when_it_is_the_reason(prefs, rainy):
    assert not rain_notes(built(prefs, rainy)[1])


def test_a_replan_does_not_repeat_or_keep_an_old_rain_warning(make):
    planner = make()
    state = planner.start("Plan a 5 day trip to Goa from Delhi in July, budget 90000 for 2 by flight, love beaches")
    assert len(rain_notes(state["warnings"])) == 1
    others = [w for w in state["warnings"] if not w.startswith(RAIN_NOTE)]
    after = planner.resume(state["thread_id"], {"action": "revise", "feedback": "relaxed pace"})
    assert len(rain_notes(after["warnings"])) == 1
    assert all(w in after["warnings"] for w in others)
