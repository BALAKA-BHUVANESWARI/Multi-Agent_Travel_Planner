"""Reading live fares from a Google Flights page. The fixture is a real page (Delhi to Goa, 2 adults, round trip),
fetched through Tavily Extract on 2026-11-25 with the links and images removed."""
from pathlib import Path

import pytest

from app.integrations.google_flights import economy_with_price, parse_google_flights

PAGE = (Path(__file__).parents[1] / "fixtures" / "google_flights_del_goi.txt").read_text(encoding="utf-8")

ROW = ("*        {dep} {dep} on Fri, Dec 25  –{arr}{plus} {arr} on {aday}  {airline}  {dur} DEL Indira Gandhi "
       "International Airport  –GOI Goa Dabolim International Airport   {stops}   212 kg CO2e  Avg emissions "
       "Avg emissions      {price}  {kind}      Departure Fri, Dec 25 212 kg CO2e")


def row(**kw):
    base = dict(dep="5:10 PM", arr="7:45 PM", plus="", aday="Fri, Dec 25", airline="IndiGo", dur="2 hr 35 min",
                stops="Nonstop", price="₹40,702", kind="round trip")
    return ROW.format(**{**base, **kw})


def test_real_page_gives_twelve_unique_flights():
    p = parse_google_flights(PAGE)
    assert p["adults"] == 2 and p["currency"] == "INR" and len(p["flights"]) == 12


def test_real_page_first_flight_is_read_exactly():
    f = parse_google_flights(PAGE)["flights"][0]
    assert f == {"airline": "IndiGo", "depart": "17:10", "depart_day": "Fri, Dec 25", "arrive": "19:45",
                 "arrive_day": "Fri, Dec 25", "duration_min": 155, "origin_code": "DEL", "dest_code": "GOI",
                 "stops": 0, "via": [], "price": 40702,
                 "price_kind": "round trip", "currency": "INR", "cabin": "economy"}


def test_real_page_stops_layovers_and_codeshare_names():
    flights = parse_google_flights(PAGE)["flights"]
    one_stop = [f for f in flights if f["stops"] == 1]
    assert sorted(f["via"][0] for f in one_stop) == ["AMD", "AMD", "BOM"]
    assert one_stop[0]["duration_min"] == 360 and one_stop[0]["price"] == 38980
    assert "Air India Express" in {f["airline"] for f in flights}          # not 'Air India Express Air India'


def test_real_page_business_class_and_missing_price_are_flagged():
    flights = parse_google_flights(PAGE)["flights"]
    assert [f["price"] for f in flights if f["cabin"] == "business"] == [47478]
    assert [f["airline"] for f in flights if f["price"] is None] == ["Air India Express"]


def test_economy_with_price_skips_business_and_unpriced_and_sorts():
    rows = economy_with_price(parse_google_flights(PAGE))
    prices = [f["price"] for f in rows]
    assert prices == sorted(prices) and 47478 not in prices and len(rows) == 10
    assert rows[0]["price"] == 38980 and rows[0]["stops"] == 1
    assert [f["price"] for f in rows if f["stops"] == 0][0] == 40702


def test_total_is_for_all_adults_as_the_page_says():
    assert "for 2 adults" in PAGE
    assert parse_google_flights(PAGE)["adults"] == 2


def test_arrival_on_the_next_day_uses_the_printed_date():
    p = parse_google_flights(row(dep="11:30 PM", arr="1:55 AM", plus="+1", aday="Sat, Dec 26"))
    f = p["flights"][0]
    assert (f["depart"], f["arrive"], f["arrive_day"]) == ("23:30", "01:55", "Sat, Dec 26")


def test_narrow_no_break_space_before_am_pm():
    p = parse_google_flights(row(dep="5:10 PM", arr="7:45 PM"))
    assert (p["flights"][0]["depart"], p["flights"][0]["arrive"]) == ("17:10", "19:45")


def test_twelve_o_clock_is_read_correctly():
    f = parse_google_flights(row(dep="12:05 AM", arr="12:40 PM"))["flights"][0]
    assert (f["depart"], f["arrive"]) == ("00:05", "12:40")


@pytest.mark.parametrize("cell,code,amount", [("US$105", "USD", 105), ("$1,250", "USD", 1250), ("€99", "EUR", 99),
                                              ("£1,020", "GBP", 1020), ("₹9,012", "INR", 9012)])
def test_other_currencies(cell, code, amount):
    f = parse_google_flights(row(price=cell))["flights"][0]
    assert (f["currency"], f["price"]) == (code, amount)


def test_one_way_price_is_labelled():
    assert parse_google_flights(row(kind="one way"))["flights"][0]["price_kind"] == "one way"


def test_two_stops_collect_both_airports_once():
    # the layover text for two stops is an assumed layout (the real page only had one-stop rows)
    line = row(stops="2 stops 1 hr 5 min BOM, 55 min HYD").replace("Nonstop", "")
    f = parse_google_flights(line)["flights"][0]
    assert f["stops"] == 2 and f["via"] == ["BOM", "HYD"]


def test_a_row_it_cannot_read_is_skipped_not_guessed():
    broken = "*  Select flight  ₹40,702  round trip\n" + row() + "\n*  7:45 PM on Fri  garbage ₹1"
    assert len(parse_google_flights(broken)["flights"]) == 1


@pytest.mark.parametrize("text", ["", None, "Loading results", "<html>captcha</html>", "Price unavailable"])
def test_pages_with_no_flights_give_an_empty_result(text):
    p = parse_google_flights(text)
    assert p["flights"] == [] and p["adults"] is None and economy_with_price(p) == []


def test_duplicate_rows_are_returned_once():
    assert len(parse_google_flights(row() + "\n" + row())["flights"]) == 1
