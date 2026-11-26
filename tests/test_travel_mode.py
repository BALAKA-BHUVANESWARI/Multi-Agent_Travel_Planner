"""Travel-mode choice: flight / train / bus / car / bike. The planner asks when the request does not say,
and only the chosen mode is priced, scheduled and shown."""
from datetime import date

import pytest

from travel_planner import agents, config
from travel_planner.intake import parse_request, parse_travel_mode
from travel_planner.tools import impl, transport
from travel_planner.tools.errors import ToolError

TODAY = date(2026, 11, 24)
BASE = "Plan a 4 day trip to Jaipur from Delhi in December, budget 60k for 2"


def search(dest, mode, n=2, origin="delhi"):
    return impl.search_flights(origin, dest, "2026-12-10", "2026-12-13", n, mode=mode)


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("text,mode", [
    ("trip to goa by flight", "flight"), ("we will fly", "flight"), ("by train please", "train"),
    ("take a volvo bus", "bus"), ("road trip with my car", "car"), ("self-drive", "car"),
    ("on my royal enfield motorcycle", "bike"), ("any mode is fine", "auto"), ("you decide", "auto"),
    ("trip to goa", None), ("flight or train", None),
    ("by flight or train | travel: by bus", "bus"),
])
def test_parse_travel_mode(text, mode):
    assert parse_travel_mode(text) == mode


def test_the_mode_is_a_constraint():
    assert parse_request(BASE + " by train", TODAY)["constraints"]["travel_mode"] == "train"
    assert parse_request(BASE, TODAY)["constraints"]["travel_mode"] is None


# --------------------------------------------------------------- estimator
@pytest.mark.parametrize("mode", ["flight", "train", "bus", "car", "bike"])
def test_every_mode_returns_three_priced_options(mode):
    r = search("jaipur", mode)
    assert r["mode"] == mode and r["estimated"] is True
    assert [o["id"] for o in r["options"]] == ["best", "early_late", "one_stop"]
    assert all(o["mode"] == mode and o["price_pp"] > 0 and o["estimated"] for o in r["options"])
    prices = [o["price_pp"] for o in r["options"]]
    assert prices[0] >= prices[1] >= prices[2]                # normal >= cheaper >= cheapest


def test_auto_keeps_the_old_behaviour():
    assert search("jaipur", None)["mode"] == "ground"          # short hop
    assert search("goa", None)["mode"] == "flight"
    assert search("goa", "auto")["mode"] == "flight"


def test_car_and_bike_costs_are_shared_between_travellers():
    one, four = search("jaipur", "car", n=1), search("jaipur", "car", n=4)
    assert one["options"][0]["price_pp"] > 3 * four["options"][0]["price_pp"]      # one car, four people
    two = search("jaipur", "bike", n=2)
    assert "1 bike" in two["options"][0]["label"]
    assert "2 bike" in search("jaipur", "bike", n=4)["options"][0]["label"]


GROUND = ("train", "bus", "car", "bike")


def place(name):
    return impl.resolve_place(name)["geo"]


def far(origin, dest, mode, days=4, n=2):
    geo = place(dest)
    return impl.search_flights(origin, geo["slug"], "2026-12-10", f"2026-12-{9 + days:02d}", n,
                               destination_geo=geo, mode=mode)


@pytest.mark.parametrize("dest", ["Pondicherry", "Goa", "Kochi", "Kanyakumari"])
@pytest.mark.parametrize("mode", GROUND)
def test_every_mode_with_a_land_route_can_be_chosen_however_far(dest, mode):
    options = far("delhi", dest, mode)["options"]
    assert [o["id"] for o in options] == ["best", "early_late", "one_stop"]
    assert all(o["price_pp"] > 0 and o["return_days_after"] >= 0 for o in options)
    assert options[0]["price_pp"] >= options[1]["price_pp"] >= options[2]["price_pp"]


@pytest.mark.parametrize("origin,dest,why", [
    ("delhi", "Port Blair", "crosses the sea"),           # same country, but an island
    ("chennai", "Colombo", "crosses the sea"),            # short hop, but across the sea
    ("delhi", "Bangkok", "between countries"),
])
@pytest.mark.parametrize("mode", GROUND)
def test_no_practical_land_route_is_refused(origin, dest, why, mode):
    with pytest.raises(ToolError) as e:
        far(origin, dest, mode)
    assert e.value.retryable is False and why in str(e.value) and "flight" in str(e.value)
    assert far(origin, dest, "flight")["options"]


def test_sea_rule_works_both_ways_and_leaves_land_borders_alone():
    delhi, blair, kathmandu = (28.6, 77.2, "IN"), (11.62, 92.73, "IN"), (27.7, 85.3, "NP")
    assert transport.crosses_sea(delhi, blair) and transport.crosses_sea(blair, delhi)
    assert not transport.crosses_sea(delhi, kathmandu)
    assert not transport.crosses_sea((6.93, 79.85, "LK"), (7.29, 80.63, "LK"))     # inside one island country


def test_long_journey_warning():
    assert transport.long_journey_warning("car", 9, 0, 4) == ""
    assert transport.long_journey_warning("train", 18, 1, 5) == ""                 # a normal overnight train
    assert "may be no direct bus" in transport.long_journey_warning("bus", 52, 5, 4)
    short_break = transport.long_journey_warning("train", 18, 2, 2)                # as long on the way as there
    assert "adding 2 day(s)" in short_break and "direct train" not in short_break
    assert transport.long_journey_warning("flight", 99, 9, 1) == ""


def test_bike_rental_covers_the_days_on_the_road():
    o = far("delhi", "Goa", "bike")["options"]
    scale = 0.7 + 0.3 * (1.0 + impl.DESTINATIONS["goa"]["cost_factor"]) / 2
    rented_days = 4 + 2 * o[1]["leave_days_before"]                    # the 4-day trip plus the ride both ways
    assert abs((o[1]["price_pp"] - o[2]["price_pp"]) - 700 * rented_days * scale / 2) <= 200   # 1 bike, 2 people


def test_a_road_trip_to_goa_from_delhi_is_possible_by_car_and_by_bike():
    car = search("goa", "car")["options"]
    bike = search("goa", "bike")["options"]
    assert [o["id"] for o in car] == [o["id"] for o in bike] == ["best", "early_late", "one_stop"]
    assert car[0]["leave_days_before"] == 3 and bike[0]["leave_days_before"] == 4
    assert "3 night halt(s)" in car[0]["note"] and "4 night halt(s)" in bike[0]["note"]
    assert car[0]["price_pp"] > car[1]["price_pp"] > car[2]["price_pp"]
    assert bike[0]["price_pp"] > bike[1]["price_pp"] > bike[2]["price_pp"]


def test_multi_day_road_trips_set_off_in_the_morning_and_arrive_the_same_afternoon():
    for mode, start in (("car", "07:00"), ("bike", "07:30")):
        o = search("goa", mode)["options"][0]
        assert o["depart_out"] == start and "07:00" <= o["arrive_out"] <= "17:30"
        assert o["depart_back"] == "06:00" and o["arrive_back"] <= "16:00"      # the last day's drive only
        assert start[:2] in o["label"] or "at 07" in o["label"]


def test_unknown_mode_is_a_non_retryable_error():
    with pytest.raises(ToolError) as e:
        search("jaipur", "rocket")
    assert e.value.retryable is False


def test_long_overland_trips_start_before_the_first_day_and_arrive_in_the_morning():
    o = search("manali", "bus")["options"][0]
    assert "before" in o["label"] and o["depart_out"] >= "17:00" and o["arrive_out"] == "09:30"
    assert o["leave_days_before"] == 1


def test_a_very_long_train_ride_starts_two_days_before():
    o = search("goa", "train")["options"][0]                      # Delhi -> Goa, about 34 h
    assert o["leave_days_before"] == 2 and "2 days before" in o["label"] and o["arrive_out"] == "09:30"


def test_long_car_trips_include_night_halts_in_the_price():
    short = impl.search_flights("delhi", "jaipur", "2026-12-10", "2026-12-13", 2, mode="car")["options"][1]
    far = impl.search_flights("mumbai", "jaipur", "2026-12-10", "2026-12-14", 2, mode="car")["options"][1]
    assert "night halts" in far["note"] and "night halts" not in short["note"]
    assert far["leave_days_before"] >= 1


def test_times_stay_inside_the_day():
    for dest, mode in (("jaipur", "car"), ("manali", "car"), ("jaipur", "bike"), ("manali", "train")):
        for o in search(dest, mode)["options"]:
            for k in ("depart_out", "arrive_out", "depart_back", "arrive_back"):
                h, m = o[k].split(":")
                assert 0 <= int(h) < 24 and 0 <= int(m) < 60


def test_overland_between_countries_is_limited():
    with pytest.raises(ToolError):
        impl.search_flights("delhi", "bangkok", "2026-12-10", "2026-12-14", 2, mode="car")


# ----------------------------------------------------------- the planner
def test_asks_how_to_travel_when_not_said(make):
    p = make()
    p.deps.ask_travel_mode = True
    s = p.start(BASE)
    assert s["status"] == "needs_info"
    modes = {o["mode"]: o for o in s["travel_options"]}
    assert set(modes) == {"flight", "train", "bus", "car", "bike"}
    assert modes["train"]["available"] and modes["train"]["price_pp"] > 0
    assert "How would you like to travel" in s["message"] and "Train" in s["message"]
    assert not s.get("flight") and not s.get("itinerary")      # nothing was planned yet


PONDICHERRY = ("Suggest a 4 day beach trip from Delhi in January, budget 70k for 2 | destination: Pondicherry")


def ask(make, text, **kw):
    p = make()
    p.deps.ask_travel_mode = True
    return p, p.start(text, **kw)


def test_all_five_ways_are_offered_for_a_far_place_with_dates_and_warnings(make):
    _, s = ask(make, PONDICHERRY)                                                  # the reported case
    opts = {o["mode"]: o for o in s["travel_options"]}
    assert all(opts[m]["available"] for m in ("flight",) + GROUND)
    for mode in GROUND:
        o = opts[mode]
        assert o["extra_days"] > 0 and o["leave_date"] < s["constraints"]["start_date"] < o["home_date"]
        assert "Long journey" in o["warning"]
    assert not opts["flight"].get("warning") and "not available" not in s["message"]
    assert "Long journey" in s["message"] and "leave " in s["message"]


@pytest.mark.parametrize("mode", GROUND)
def test_a_long_mode_can_be_planned_and_the_plan_shows_the_real_dates(make, mode):
    p, s = ask(make, PONDICHERRY)
    s = p.start(PONDICHERRY + f" | travel: by {mode}")
    assert s["status"] == "awaiting_approval" and s["flight"]["selected"]["mode"] == mode
    journey = s["flight"]["journey"]
    assert journey["leave_date"] < s["constraints"]["start_date"] and "Long journey" in journey["warning"]
    assert "Leave home on" in s["summary"] and "Long journey" in s["summary"]
    assert not any("Long journey" in w for w in s["warnings"])      # lives with the selected option only


def test_a_departure_date_that_has_passed_is_called_out(make):
    c = {"start_date": TODAY.isoformat(), "days": 4}
    o = far("delhi", "Goa", "bike")["options"][0]
    assert "has passed" in agents._journey(c, o, TODAY)["warning"]
    assert agents._journey(c, {"mode": "flight"}, TODAY) is None


def test_unavailable_modes_say_why(make):
    _, s = ask(make, "Plan a 4 day trip to Bangkok from Delhi in December, budget 2 lakh for 2")
    opts = {o["mode"]: o for o in s["travel_options"]}
    assert opts["flight"]["available"] and not any(opts[m]["available"] for m in GROUND)
    assert "between countries" in opts["car"]["reason"] and "not available" in s["message"]


def test_a_saved_travel_mode_is_highlighted_not_silently_applied(make):
    _, s = ask(make, BASE, memory={"travel_mode": "flight"})
    assert s["status"] == "needs_info" and len(s["travel_options"]) == 5
    assert [o["mode"] for o in s["travel_options"] if o.get("usual")] == ["flight"]
    assert not any("travel by flight" in w for w in s.get("warnings", []))
    quiet = make().start(BASE, memory={"travel_mode": "train"})                   # question switched off
    assert quiet["constraints"]["travel_mode"] == "train"
    assert any("travel by train" in w for w in quiet["warnings"])


@pytest.mark.parametrize("text,mode", [
    ("find flights and hotels in goa", None), ("hotel + flight for goa", None), ("flight & hotel", None),
    ("we want horse riding and rafting", None), ("camel ride and camel riding", None), ("quad biking in goa", None),
    ("mountain bike trails", None), ("horse riding trip, go by bus", "bus"), ("go by flight and hotel by sea", "flight"),
    ("riding there on my bike", "bike"),
])
def test_activity_words_do_not_choose_how_to_travel(text, mode):
    assert parse_travel_mode(text) == mode


def test_does_not_ask_when_the_mode_is_given(make):
    p = make()
    p.deps.ask_travel_mode = True
    s = p.start(BASE + " by bus")
    assert s["status"] == "awaiting_approval"
    assert s["flight"]["selected"]["mode"] == "bus"


def test_any_mode_plans_without_asking(make):
    p = make()
    p.deps.ask_travel_mode = True
    s = p.start(BASE + " | travel: any mode")
    assert s["status"] == "awaiting_approval" and s["flight"]["selected"]["mode"] in ("ground", "flight")


def test_the_default_does_not_ask(make):
    assert make().start(BASE)["status"] == "awaiting_approval"      # tests, evals and the CLI keep old behaviour


@pytest.mark.parametrize("mode,word", [("train", "Train"), ("bus", "Bus"), ("car", "Car"), ("bike", "Bike"),
                                       ("flight", "Flight")])
def test_only_the_chosen_mode_is_planned_and_shown(make, mode, word):
    p = make()
    s = p.start(BASE + f" by {mode}")
    assert s["status"] == "awaiting_approval"
    sel = s["flight"]["selected"]
    assert sel["mode"] == mode
    assert {o["mode"] for o in s["flight"]["options"]} == {mode}
    assert f"## {word} (estimated)" in s["summary"]
    other = {"Flight", "Train", "Bus", "Car", "Bike"} - {word}
    assert not any(f"## {o} (estimated)" in s["summary"] for o in other)
    assert s["budget_report"]["lines"]["flight"] == sel["price_pp"] * 2          # budget uses the chosen mode


def test_road_trip_itinerary_has_no_airport_steps(make):
    s = make().start(BASE + " by car")
    names = " ".join(i["name"] for d in s["itinerary"]["days"] for i in d["items"])
    assert "Airport" not in names and "drive home" in names
    assert any("estimated from the straight-line distance" in w for w in s["warnings"])


def test_a_chosen_mode_with_no_land_route_asks_again(make):
    p = make()
    s = p.start("Plan a 4 day trip to Port Blair from Delhi in December, budget 90k for 2 by bike")
    assert s["status"] == "needs_info" and "crosses the sea" in s["message"]
    assert any(o["mode"] == "flight" and o["available"] for o in s["travel_options"])
    assert s["constraints"]["travel_mode"] is None


def test_config_switch(monkeypatch):
    monkeypatch.setenv("ASK_TRAVEL_MODE", "0")
    assert config.ask_travel_mode() is False
    monkeypatch.delenv("ASK_TRAVEL_MODE")
    assert config.ask_travel_mode() is True


@pytest.mark.parametrize("mode,word", [("car", "Car"), ("bike", "Bike")])
def test_a_whole_plan_by_car_or_bike_from_delhi_to_goa(make, mode, word):
    s = make().start(f"Plan a 5 day trip to Goa from Delhi starting 25 December, budget 2 lakh for 2 by {mode}")
    assert s["status"] == "awaiting_approval"
    sel = s["flight"]["selected"]
    assert sel["mode"] == mode and sel["leave_days_before"] in (3, 4)
    assert not [i for i in s["critic_issues"] if i["severity"] == "blocking"]
    assert f"## {word} (estimated)" in s["summary"] and "Airport" not in s["summary"]
    assert len(s["itinerary"]["days"]) == 5



def test_a_late_afternoon_arrival_does_not_overlap_the_hotel_check_in():
    from travel_planner import itinerary
    slots = itinerary._slots_for_day(0, 5, 17 * 60 + 6, 17 * 60, "normal", 0)
    assert slots == [("evening", 17 * 60 + 6 + 90, 22 * 60 + 30)]
    assert itinerary._slots_for_day(0, 5, 16 * 60, 17 * 60, "normal", 0)[-1][1] == 18 * 60 + 30   # unchanged
    assert itinerary._slots_for_day(0, 5, 18 * 60, 17 * 60, "normal", 0) == []
