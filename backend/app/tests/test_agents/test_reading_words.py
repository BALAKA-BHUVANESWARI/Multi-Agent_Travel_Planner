"""Dates in numbers or words, traveller counts in words, "Dilli" and nights written as words."""
from datetime import date

import pytest

from app.services.request_parser import parse_days, parse_request, parse_travelers

TODAY = date(2026, 11, 24)
BASE = "3 days in Goa from Delhi, budget 60000"


def read(extra: str, today: date = TODAY) -> dict:
    return parse_request(f"{BASE} {extra}", today)


@pytest.mark.parametrize("said, expected", [
    ("starting 20/12/2026", "2026-12-20"),
    ("starting 05/12/2026", "2026-12-05"),                      # day first
    ("on 5-1-2027", "2027-01-05"),
    ("on 20.12.2026", "2026-12-20"),
    ("starting 20/12/26", "2026-12-20"),
    ("starting 2026-12-20", "2026-12-20"),
    ("around 2026/12/20.", "2026-12-20"),
    ("starting 20/12/2027", "2027-12-20"),                      # a year in numbers is kept
    ("on Christmas", "2026-12-25"),
    ("for christmas eve", "2026-12-24"),
    ("on Xmas day", "2026-12-25"),
    ("in December for Christmas", "2026-12-25"),
    ("tomorrow", "2026-11-25"),
    ("day after tomorrow", "2026-11-26"),
    ("starting 28 December, back before Christmas", "2026-12-28"),
    ("in January, after Christmas", "2027-01-10"),
])
def test_start_dates(said, expected):
    got = read(said)
    c = got["constraints"]
    assert c["start_date"] == expected
    assert c["month"] == int(expected[5:7])
    assert (c["budget"], c["days"], c["travelers"]) == (60000, 3, 1)
    assert (c["origin"], c["destination"]) == ("delhi", "goa")
    assert not any("No travel month" in a for a in got["assumptions"])


@pytest.mark.parametrize("today, expected", [(date(2026, 12, 25), "2027-12-25"), (date(2026, 12, 28), "2027-12-25")])
def test_christmas_that_has_come_means_next_year(today, expected):
    assert read("on Christmas", today)["constraints"]["start_date"] == expected


def test_a_past_numeric_date_is_moved_and_said_so():
    got = read("starting 20/01/2026")
    assert got["constraints"]["start_date"] == "2027-01-20"
    assert any("2026-01-20 is not in the future" in a for a in got["assumptions"])


@pytest.mark.parametrize("said", ["starting 31/02/2027", "starting 12/25/2026"])
def test_a_date_that_does_not_exist_is_not_guessed(said):
    got = read(said)
    assert "could not read" in got["invalid"]["date"] and "valid start date" in got["invalid"]["date"]
    assert got["bad_date"] == said.split()[-1]
    assert got["constraints"]["budget"] == 60000


def test_an_unreadable_number_beside_a_good_date_is_only_mentioned():
    got = read("starting 31/02/2027, or 5 March")
    assert "date" not in got["invalid"] and got["constraints"]["start_date"] == "2027-03-05"
    assert any("could not read" in a for a in got["assumptions"])


@pytest.mark.parametrize("said", ["5N/6D", "with 24/7 reception", "to see a Christmas market"])
def test_things_that_are_not_start_dates(said):
    assert any("No travel month" in a for a in read(said)["assumptions"])


def test_a_date_is_not_read_as_a_budget():
    got = parse_request("3 days in Goa from Delhi around 2026-12-20", TODAY)
    assert got["constraints"]["budget"] is None and "budget" in got["missing"]


def test_christmas_island_does_not_set_the_date():
    got = parse_request("5 days to Christmas Island from Delhi, budget 200000", TODAY)
    assert got["texts"]["destination"] == "Christmas"           # as before: "island" ends the place phrase
    assert any("No travel month" in a for a in got["assumptions"])


def test_tomorrow_is_not_part_of_a_place_name():
    got = parse_request("3 days to Zzyzxville tomorrow from Delhi, budget 60000", TODAY)
    assert got["texts"]["destination"] == "Zzyzxville"


@pytest.mark.parametrize("text, count", [
    ("four of us to Manali", 4),
    ("budget 45000 for two adults", 2),
    ("two adults and one child", 3),
    ("2 adults and 1 child", 3),
    ("family of five to Goa", 5),
    ("me and two friends", 3),
    ("a trip with three friends", 4),
    ("two friends going to Goa", 2),
    ("Goa for two, budget 40k", 2),
    ("a couple with one kid", 3),
    ("four of us, two of us are vegetarian", 4),
    ("one of us loves beaches, we are a couple", 2),
])
def test_travellers_in_words(text, count):
    assert parse_travelers(text) == (count, False)


@pytest.mark.parametrize("text", ["Goa for two days", "Goa for two weeks", "budget for two lakh",
                                  "one of the best beaches", "travelling with two kids", "a two-day trip"])
def test_words_that_do_not_give_a_traveller_count(text):
    assert parse_travelers(text)[0] is None


@pytest.mark.parametrize("text, days", [
    ("five nights in Goa", 6),
    ("a three-night stay", 4),
    ("5 days with two nights on a houseboat", 5),
    ("five days with two nights on a houseboat", 5),
    ("a week with two nights camping", 7),
])
def test_nights_in_words(text, days):
    assert parse_days(text) == days


def test_dilli_is_delhi():
    c = parse_request("3 days in Jaipur from Dilli, budget 40000", TODAY)["constraints"]
    assert (c["origin"], c["destination"]) == ("delhi", "jaipur")
