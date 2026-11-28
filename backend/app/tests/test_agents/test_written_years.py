"""A year written in a date is kept, for new requests, replies and change requests."""
from datetime import date

import pytest

from app.services.chat_service import complete_request
from app.services.request_parser import parse_request

TODAY = date(2026, 11, 28)
BASE = "4 days in Goa from Delhi, budget 60000"


@pytest.mark.parametrize("said, expected", [
    ("starting 25 December 2027", "2027-12-25"), ("on 25th of December, 2027", "2027-12-25"),
    ("on December 25th, 2027", "2027-12-25"), ("in March 2028", "2028-03-10"), ("in December 2027", "2027-12-10"),
    ("on Christmas 2027", "2027-12-25"), ("for christmas eve, 2028", "2028-12-24"),
    ("from 28 December 2027 to 3 January 2028", "2027-12-28"), ("starting 25 December", "2026-12-25"),
    ("in December", "2026-12-10"), ("in November 2026", "2026-12-01"),
])
def test_the_written_year_is_used(said, expected):
    got = parse_request(f"{BASE}, {said}", TODAY)
    c = got["constraints"]
    assert (c["start_date"], c["budget"], c["days"], c["travelers"]) == (expected, 60000, 4, 1)
    assert not got["invalid"] and not any("in the past" in a or "not in the future" in a for a in got["assumptions"])


@pytest.mark.parametrize("said, expected, note", [
    ("starting 25 December 2025", "2026-12-25", "2025-12-25 is not in the future"),
    ("starting 29 February 2024", "2027-02-28", "2024-02-29 is not in the future"),
    ("in March 2025", "2027-03-10", "March 2025 is in the past"),
])
def test_a_year_that_has_passed_is_moved_and_said_so(said, expected, note):
    got = parse_request(f"{BASE}, {said}", TODAY)
    assert got["constraints"]["start_date"] == expected
    assert any(note in a for a in got["assumptions"])


@pytest.mark.parametrize("said", ["in March, 2050 per head", "on 5 March 2000"])
def test_other_numbers_are_not_taken_for_a_year(said):
    assert parse_request(f"{BASE}, {said}", TODAY)["constraints"]["start_date"].startswith("2027-03")


def test_the_impossible_day_is_judged_in_the_written_year():
    got = parse_request(f"{BASE}, starting 31 February 2028", TODAY)
    assert "February 2028 has only 29 days" in got["invalid"]["date"]


@pytest.mark.parametrize("reply, expected", [
    ("March 2028", "2028-03-10"), ("1 March 2028", "2028-03-01"), ("Christmas 2027", "2027-12-25"),
])
def test_a_reply_to_the_date_question_keeps_its_year(reply, expected):
    asked = {"request": f"{BASE}, starting 31 February 2027",
             "constraints": {"origin": "delhi", "destination": "goa", "days": 4, "budget": 60000,
                             "today": TODAY.isoformat()}}
    got = parse_request(complete_request(asked, reply), TODAY)
    assert not got["invalid"] and got["constraints"]["start_date"] == expected


def planned(make):
    planner = make()
    return planner, planner.start(f"{BASE}, starting 10 December 2027")


@pytest.mark.parametrize("change, expected", [
    ("move it to 25 December 2027", "2027-12-25"), ("move it to March 2028", "2028-03-10"),
])
def test_a_change_keeps_its_year(make, change, expected):
    planner, state = planned(make)
    assert state["constraints"]["start_date"] == "2027-12-10"
    after = planner.resume(state["thread_id"], {"action": "revise", "feedback": change})
    assert after["constraints"]["start_date"] == expected


def test_a_change_to_a_past_date_is_refused(make):
    planner, state = planned(make)
    after = planner.resume(state["thread_id"], {"action": "revise", "feedback": "move it to 25 December 2025"})
    assert after["constraints"]["start_date"] == "2027-12-10" and after.get("revisions", 0) == 0
    assert "in the past" in after["notice"] + after["message"]


def test_another_change_keeps_the_year_of_the_trip(make):
    planner, state = planned(make)
    after = planner.resume(state["thread_id"], {"action": "revise", "feedback": "make it 3 days"})
    assert after["constraints"]["start_date"] == "2027-12-10"
