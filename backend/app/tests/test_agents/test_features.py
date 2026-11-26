"""Destination suggestions and alternatives, conversational changes, group preferences and map coordinates."""
from datetime import date

import pytest

from app.data import destination_ideas
from app.graph.state import RESET, add_or_reset
from app.services import group_service as group_mod
from app.services.feedback_parser import matches_excluded, parse_feedback
from app.services.pricing import price_estimator as dynamic
from app.services.request_parser import parse_request, split_destination_choice
from app.tools import destination_tools, flight_tools, maps_tools
from app.tools.client import InProcessClient

REQ = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2"
NO_DEST = "Suggest a 4 day beach trip from Delhi in January, budget 90k for 2"
CONSTRAINTS = {"travelers": 2, "days": 5, "travel_mode": None}


def activities(state):
    return [x for d in state["itinerary"]["days"] for x in d["items"] if x["type"] == "activity"]


# ------------------------------------------------------------ recommendations
def test_no_destination_offers_affordable_matching_places_without_live_prices(make):
    tools = InProcessClient()
    s = make(tools=tools).start(NO_DEST)
    assert s["status"] == "needs_info" and 1 <= len(s["suggestions"]) <= 4
    assert all(x["estimated"] and x["fits_budget"] and x["estimate_from"] <= 90000 for x in s["suggestions"])
    assert "beach" in s["suggestions"][0]["matched"]
    assert {c["name"] for c in tools.calls} == {"recommend_destinations"}


def test_choosing_a_suggestion_plans_it(make):
    p = make()
    first = p.start(NO_DEST)
    name = first["suggestions"][0]["name"]
    s = p.start(f"{NO_DEST} | destination: {name}")
    assert s["status"] == "awaiting_approval"
    assert s["constraints"]["destination_geo"]["name"] == name


def test_destination_marker_overrides_the_sentence():
    text, chosen = split_destination_choice("trip to Goa from Delhi | destination: Jaipur | travel: by train")
    assert chosen == "Jaipur" and "destination:" not in text and "travel: by train" in text
    parsed = parse_request("5 days to Goa from Delhi, budget 60k | destination: Jaipur", date(2026, 11, 24))
    assert parsed["constraints"]["destination"] is None and parsed["texts"]["destination"] == "Jaipur"


@pytest.mark.parametrize("scope,check", [("india", lambda c: c == "India"), ("abroad", lambda c: c != "India")])
def test_suggestion_scope(scope, check):
    res = destination_tools.recommend_destinations("delhi", "2027-01-10", 5, 2, 500000, ["beach"], scope=scope)
    assert res["suggestions"] and all(check(x["country"]) for x in res["suggestions"])


def test_tiny_budget_is_honest_about_not_fitting():
    res = destination_tools.recommend_destinations("delhi", "2027-01-10", 5, 4, 3000, [])
    assert not res["any_fit"] and not any(x["fits_budget"] for x in res["suggestions"])


def test_every_profile_resolves_to_a_known_place_and_interest():
    from app.services.request_parser import PREF_WORDS
    for slug, (tags, months) in destination_ideas.PROFILES.items():
        assert destination_ideas.geo_for(slug), slug
        assert set(tags) <= set(PREF_WORDS) and all(1 <= m <= 12 for m in months), slug


def test_plan_carries_alternatives_priced_like_for_like(make):
    s = make().start(REQ)
    alt = s["alternatives"]
    assert alt["baseline"]["from"] > 0 and alt["items"]
    assert all(a["slug"] != "goa" for a in alt["items"])


def test_a_failing_recommender_never_breaks_a_plan(make):
    s = make(tools=InProcessClient(failures={"recommend_destinations": -1})).start(REQ)
    assert s["status"] == "awaiting_approval" and s["alternatives"] == {}


# ------------------------------------------------------ conversational changes
@pytest.mark.parametrize("text,key,value", [
    ("make it 4 days", "days", 4), ("add 2 days", "days", 7), ("one day less", "days", 4),
    ("2 more days please", "days", 7), ("add 1 person", "travelers", 3), ("we are 4 now", "travelers", 4),
    ("one more person", "travelers", 3), ("go by train", "travel_mode", "train"),
    ("switch to car", "travel_mode", "car"), ("change destination to Jaipur", "destination", "Jaipur"),
    ("let's go to Udaipur instead", "destination", "Udaipur"),
    ("skip water sports", "exclude", ["water sports"]), ("no nightlife", "exclude", ["nightlife"]),
    ("we don't want water sports or nightlife", "exclude", ["water sports", "nightlife"]),
    ("can we avoid temples?", "exclude", ["temples"]), ("skip the spa and make it cheaper", "exclude", ["spa"]),
    ("visit more museums", "preferences_add", ["culture"]), ("make it less busy", "pace", "relaxed"),
    ("change the trip to 6 days", "days", 6), ("4 days please", "days", 4), ("a 3 day trip", "days", 3),
    ("for 4 people", "travelers", 4), ("we are now three", "travelers", 3),
])
def test_parse_change_requests(text, key, value):
    assert parse_feedback(text, CONSTRAINTS, "normal")["changes"].get(key) == value


def test_parse_date_change():
    assert parse_feedback("move it to January", CONSTRAINTS, "normal")["changes"]["month_day"][0] == 1


@pytest.mark.parametrize("text", ["make it cheaper", "budget 50000", "more food", "relaxed pace",
                                  "budget 40k per person", "no changes", "no problem",
                                  "remove the budget limit", "drop the cost", "I don't want to spend more than 50000",
                                  "I want to spend 2 days at the beach", "one of us loves beaches",
                                  "we are a vegetarian family", "2 people want museums", "take a bike tour"])
def test_old_requests_gain_no_surprise_changes(text):
    changes = parse_feedback(text, CONSTRAINTS, "normal")["changes"]
    assert not {"days", "travelers", "travel_mode", "destination", "exclude", "month_day"} & set(changes)


def test_matches_excluded_by_name_or_interest():
    water = {"name": "Water sports at Calangute", "tags": ["adventure", "beach"]}
    assert matches_excluded(water, "water sports") and matches_excluded(water, "adventure")
    assert not matches_excluded(water, "museum")


def revise(planner, state, text):
    return planner.resume(state["thread_id"], {"action": "revise", "feedback": text})


def test_change_days_and_travelers(make):
    p = make()
    s = revise(p, p.start(REQ), "make it 3 days and add 1 person")
    assert s["status"] == "awaiting_approval" and s["revisions"] == 1
    assert len(s["itinerary"]["days"]) == 3 and len(s["weather"]["days"]) == 3
    assert s["constraints"]["travelers"] == 3 and s["hotel"]["selected"]["nights"] == 2
    assert not [i for i in s["critic_issues"] if i["severity"] == "blocking"]


def test_change_destination_refetches_everything_and_drops_old_warnings(make):
    p = make()
    first = p.start("Plan a 4 day trip to Goa from Delhi in December, budget 3 lakh for 2 by train")
    s = revise(p, first, "change destination to Jaipur")
    assert s["constraints"]["destination"] == "jaipur" and s["itinerary"]["destination"] == "jaipur"
    assert all(a["id"].startswith(("jp-", "generic")) for a in activities(s))
    assert s["warnings"].count(first["warnings"][-1]) <= 1


def test_change_date(make):
    p = make()
    s = revise(p, p.start(REQ), "move it to February")
    assert s["constraints"]["start_date"].startswith("2027-02")
    assert s["weather"]["days"][0]["date"] == s["constraints"]["start_date"]


def test_skip_removes_the_activity_for_good(make):
    p = make()
    first = p.start(REQ + ", love adventure and beaches")
    assert any("Water sports" in a["name"] for a in activities(first))
    s = revise(p, first, "skip water sports")
    assert not any("Water sports" in a["name"] for a in activities(s))
    s = revise(p, s, "make it cheaper")
    assert not any("Water sports" in a["name"] for a in activities(s))


@pytest.mark.parametrize("text", ["make it 40 days", "change destination to Zzyzxville",
                                  "skip the pyramids", "change destination to Delhi"])
def test_impossible_change_keeps_the_plan_and_the_revision(make, text):
    p = make()
    first = p.start(REQ)
    s = revise(p, first, text)
    assert s["status"] == "awaiting_approval" and s["revisions"] == 0
    assert s["constraints"] == first["constraints"] and s["message"]


def test_impossible_road_mode_is_refused(make):
    p = make()
    first = p.start("Plan a 4 day trip to Bangkok from Mumbai in January, budget 3 lakh for 2")
    s = revise(p, first, "go by bike")
    assert s["constraints"].get("travel_mode") is None and s["revisions"] == 0


def test_warning_reset_reducer():
    assert add_or_reset(["a"], ["b"]) == ["a", "b"]
    assert add_or_reset(["a"], [RESET, "c"]) == ["c"]


# --------------------------------------------------------------------- groups
GROUP = [{"name": "Asha", "likes": ["temples", "history"], "avoid": ["nightlife"]},
         {"name": "Ravi", "likes": "water sports", "avoid": []},
         {"name": "Meena", "likes": ["shopping"]}]


def test_clean_group_validates_and_maps_words_to_interests():
    g = group_mod.clean_group(GROUP + [{"name": "<b>x</b>" * 20, "likes": ["nonsense"]}])
    assert g[0]["likes"] == ["spiritual", "history"] and g[1]["likes"] == ["adventure"]
    assert len(g[3]["name"]) <= 30 and "<" not in g[3]["name"] and g[3]["likes"] == []
    for bad in ("x", [1], [{}] * 11):
        with pytest.raises(ValueError):
            group_mod.clean_group(bad)


def test_group_plan_serves_everyone(make):
    s = make().start("Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh",
                     group=group_mod.clean_group(GROUP))
    assert s["constraints"]["travelers"] == 3
    assert {m["name"] for m in s["group_report"]} == {"Asha", "Ravi", "Meena"}
    assert all(m["matched"] for m in s["group_report"]), s["group_report"]
    assert "## Group fit" in s["summary"]


def test_fair_order_gives_the_minority_a_turn_and_drops_what_all_avoid():
    cands = [{"id": f"b{i}", "tags": ["beach"]} for i in range(4)] + \
            [{"id": "m", "tags": ["culture"]}, {"id": "n", "tags": ["nightlife"]}]
    g = [{"name": "a", "likes": ["beach"], "avoid": ["nightlife"]},
         {"name": "b", "likes": ["culture"], "avoid": ["nightlife"]}]
    order = [c["id"] for c in group_mod.fair_order(cands, g)]
    assert "m" in order[:2] and "n" not in order


# ------------------------------------------------------------------------ map
def test_curated_activities_carry_coordinates(make):
    s = make().start(REQ)
    located = [a for a in activities(s) if "lat" in a]
    assert len(located) >= len(activities(s)) // 2
    assert all(14 < a["lat"] < 17 and 73 < a["lon"] < 75 for a in located)


def test_open_data_places_keep_their_coordinates():
    geo = {"name": "Testville", "lat": 10.0, "lon": 76.0, "cost_factor": 1.0, "population": 5000}
    elements = [{"type": "node", "id": 1, "lat": 10.001, "lon": 76.002, "tags": {"tourism": "museum", "name": "Old Museum"}},
                {"type": "way", "id": 2, "center": {"lat": 10.01, "lon": 76.01}, "tags": {"leisure": "park", "name": "River Park"}},
                {"type": "wp", "id": 3, "tags": {"tourism": "attraction", "name": "No Position"}}]
    found = {c["name"]: c for c in dynamic.build_candidates(geo, elements)[0]}
    assert (found["Old Museum"]["lat"], found["Old Museum"]["lon"]) == (10.001, 76.002)
    assert found["River Park"]["lat"] == 10.01 and "lat" not in found["No Position"]


def test_the_request_the_page_rebuilds_for_another_destination_parses_back():
    parsed = parse_request("Plan a 5 day trip from Delhi starting 25 December, budget 80000 for 2 people, love beach "
                           "and family-friendly, relaxed pace | destination: Jaipur", date(2026, 11, 26))
    c = parsed["constraints"]
    assert (c["origin"], c["days"], c["budget"], c["travelers"], c["start_date"], c["pace"]) == \
        ("delhi", 5, 80000, 2, "2026-12-25", "relaxed")
    assert c["preferences"] == ["beach", "family"] and parsed["texts"]["destination"] == "Jaipur"


def test_llm_cannot_invent_a_destination_when_ideas_were_asked_for(make, fake_transport):
    guess = fake_transport({"groq": lambda body: (200, {"destination": "Goa"})})
    s = make(env={"GROQ_API_KEY": "k"}, transport=guess).start(NO_DEST)
    assert s["status"] == "needs_info" and s["suggestions"] and not s["constraints"].get("destination")


def test_every_state_key_is_declared_for_langgraph(make):
    """LangGraph silently drops keys that TripState does not declare, which the plain runner would not notice."""
    from app.graph.state import TripState
    p = make()
    first = p.start(REQ, group=group_mod.clean_group(GROUP), memory={"home_city": "Delhi"})
    for state in (first, revise(p, first, "change destination to Jaipur"), make().start(NO_DEST)):
        assert set(state) <= set(TripState.__annotations__), set(state) - set(TripState.__annotations__)


def test_a_card_number_typed_as_a_name_is_not_kept():
    assert group_mod.clean_group([{"name": "4111 1111 1111 1111"}])[0]["name"] == "Traveller 1"


def test_suggestions_for_a_road_mode_stay_within_a_long_ride():
    from app.services.pricing import transport_estimator as transport
    res = destination_tools.recommend_destinations("delhi", "2027-01-10", 4, 2, 300000, ["beach"], mode="bus",
                                           exclude="goa")
    assert res["baseline"]["travel_hours"] > transport.LONG_HOURS["bus"]     # the current trip is still priced
    for item in res["suggestions"]:
        geo = maps_tools.resolve_place(item["name"])["geo"]
        hours = flight_tools.search_flights("delhi", geo["slug"], "2027-01-10", "2027-01-13", 2, destination_geo=geo,
                                    mode="bus")["options"][0]["duration_h"]
        assert hours <= transport.LONG_HOURS["bus"], item["name"]
