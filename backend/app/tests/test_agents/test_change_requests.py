"""A change request searches again only for what it affects, and "cheaper hotel" or "cheaper flight" moves only that."""
import pytest

from app.agents.supervisor import agents_for_changes
from app.core import config
from app.services.feedback_parser import parse_feedback
from app.tools.client import InProcessClient

REQ = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2, beaches and adventure"
CONSTRAINTS = {"travelers": 2, "days": 5, "travel_mode": None, "budget": 300000}


class Counting(InProcessClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.asked = []

    def call(self, name, **kwargs):
        self.asked.append(name)
        return super().call(name, **kwargs)


def revise(planner, state, text):
    return planner.resume(state["thread_id"], {"action": "revise", "feedback": text})


def started(make, **kwargs):
    tools = Counting(**kwargs)
    planner = make(tools=tools)
    state = planner.start(REQ)
    tools.asked.clear()
    return planner, tools, state


def searches(tools):
    wanted = {"search_flights": "flight", "search_hotels": "hotel", "get_weather": "weather",
              "search_places": "activities"}
    return {wanted[name] for name in tools.asked if name in wanted}


def picked(state, part):
    return state[part]["selected"]


@pytest.mark.parametrize("text, expected", [
    ("a cheaper hotel", {"hotel"}), ("find a cheaper flight", {"flight"}),
    ("cheaper hotel and flight", {"hotel", "flight"}), ("add 1 person", {"hotel", "flight"}),
    ("more history", {"activities"}), ("skip water sports", {"activities"}), ("relaxed pace", set()),
    ("change flight to train", {"flight"}), ("move it to January", {"flight", "hotel", "weather"}),
    ("make it 3 days", {"flight", "hotel", "weather"}), ("make it cheaper", {"flight", "hotel", "activities"}),
    ("budget 150000", {"flight", "hotel", "activities"}),
    ("change destination to Jaipur", {"flight", "hotel", "weather", "activities"}),
])
def test_only_the_affected_searches_run_again(make, text, expected):
    planner, tools, first = started(make)
    changed = revise(planner, first, text)
    assert changed["revisions"] == 1 and searches(tools) == expected
    for part in {"flight", "hotel", "weather"} - expected:
        assert changed[part] == first[part]


@pytest.mark.parametrize("text, part, other, price", [
    ("a cheaper hotel", "hotel", "flight", "price_night_per_room"),
    ("find a cheaper flight", "flight", "hotel", "price_pp"),
])
def test_a_cheaper_part_leaves_the_rest_alone(make, text, part, other, price):
    planner, _, first = started(make)
    changed = revise(planner, first, text)
    assert picked(changed, part)[price] < picked(first, part)[price]
    assert picked(changed, other) == picked(first, other)
    assert changed["strategy"] == first["strategy"] and changed["activities"] == first["activities"]
    assert changed["budget_report"]["lines"]["food"] == first["budget_report"]["lines"]["food"]
    assert changed["budget_report"]["total"] == sum(changed["budget_report"]["lines"].values())


def test_the_cheaper_hotel_is_remembered_until_the_budget_is_set_again(make):
    planner, _, first = started(make)
    cheaper = revise(planner, first, "a cheaper hotel")
    later = revise(planner, cheaper, "add 1 person")
    assert picked(later, "hotel")["id"] == picked(cheaper, "hotel")["id"] != picked(first, "hotel")["id"]
    planner, _, first = started(make)
    again = revise(planner, revise(planner, first, "a cheaper hotel"), "budget 400000")
    assert again["part_levels"] == {} and picked(again, "hotel")["id"] == picked(first, "hotel")["id"]


def test_making_the_whole_trip_cheaper_also_lowers_a_part_already_lowered(make):
    planner, _, first = started(make)
    hotel = revise(planner, first, "a cheaper hotel")
    whole = revise(planner, hotel, "make it cheaper")
    assert whole["strategy"] == "cheaper"
    assert picked(whole, "hotel")["price_night_per_room"] < picked(hotel, "hotel")["price_night_per_room"]


def test_when_nothing_cheaper_exists_it_says_so_and_changes_nothing(make):
    planner, tools, first = started(make)
    lowest = revise(planner, revise(planner, first, "a cheaper hotel"), "a cheaper hotel")
    assert lowest["revisions"] == config.MAX_REVISIONS
    planner = make()
    first = planner.start("Plan a 4 day trip to Jaipur from Delhi on 25 December, budget 3000 for 4")
    same = revise(planner, first, "a cheaper hotel")                   # the plan is already on the cheapest
    assert same["revisions"] == 0 and "no cheaper hotel" in same["message"]
    assert same["hotel"] == first["hotel"]


@pytest.mark.parametrize("tool, key", [("search_flights", "flight"), ("search_hotels", "hotel"),
                                       ("get_weather", "weather"), ("search_places", "activities")])
def test_a_failed_search_is_tried_again_after_any_change(make, tool, key):
    planner = make(tools=InProcessClient(failures={tool: config.TOOL_RETRIES}))
    first = planner.start(REQ)
    assert first[key].get("error")
    changed = revise(planner, first, "relaxed pace")
    assert not changed[key].get("error")


def test_stand_in_places_and_a_failed_restaurant_lookup_are_not_kept():
    good = {"candidates": [], "dining": {"note": ""}}
    state = {"changed": ["pace"], "flight": {"selected": {}}, "hotel": {"selected": {}}, "weather": {"days": [1]}}
    assert agents_for_changes({**state, "activities": good}) == []
    assert agents_for_changes({**state, "activities": {**good, "data_quality": "generic"}}) == ["activities"]
    failed = {**good, "dining": {"note": "Restaurant lookup unavailable (timed out)."}}
    assert agents_for_changes({**state, "activities": failed}) == ["activities"]


def test_an_unlisted_kind_of_change_searches_everything():
    state = {"changed": ["something_new"], "flight": {"x": 1}, "hotel": {"x": 1}, "activities": {"x": 1},
             "weather": {"days": [1]}}
    assert agents_for_changes(state) == ["flight", "hotel", "weather", "activities"]


def test_a_kept_result_keeps_its_warnings_when_the_old_ones_are_cleared(make):
    planner, _, first = started(make)
    first["hotel"]["notices"] = ["Live hotel prices were unavailable (test); the hotel price is an estimate."]
    first["warnings"] = first["warnings"] + first["hotel"]["notices"]
    planner.deps.store.save_state(first["thread_id"], first)
    changed = revise(planner, first, "change flight to train")          # clears the trip's old warnings
    assert changed["warnings"].count(first["hotel"]["notices"][0]) == 1
    again = revise(planner, changed, "relaxed pace")
    assert again["warnings"].count(first["hotel"]["notices"][0]) == 1


@pytest.mark.parametrize("text, parts", [
    ("change the hotel to a cheaper one", ["hotel"]), ("the hotel is too expensive", ["hotel"]),
    ("save money on the hotel", ["hotel"]), ("I want a more affordable place to stay", ["hotel"]),
    ("replace the hotel with a cheaper one", ["hotel"]), ("make the flight cheaper", ["flight"]),
    ("cheaper train tickets", ["flight"]), ("keep the hotel, find a cheaper flight", ["flight"]),
    ("the flight and hotel are too expensive", ["hotel", "flight"]),
    ("keep the flight and the hotel is too expensive", ["hotel"]),
])
def test_cheaper_said_about_one_part(text, parts):
    changes = parse_feedback(text, CONSTRAINTS, "normal")["changes"]
    assert changes == {"cheaper_parts": parts}


@pytest.mark.parametrize("text", ["make it cheaper", "too expensive", "reduce the cost", "cheaper activities",
                                  "cheaper food", "cheaper entry tickets",
                                  "I like the hotel but make everything cheaper",
                                  "a cheaper hotel and make the whole trip cheaper"])
def test_cheaper_said_about_the_whole_trip(text):
    assert parse_feedback(text, CONSTRAINTS, "normal")["changes"] == {"strategy": "cheaper"}


@pytest.mark.parametrize("text, mode", [
    ("change flight to train", "train"), ("change the flight to a train", "train"), ("change it to bus", "bus"),
    ("change to train", "train"), ("switch from flight to train", "train"), ("train instead", "train"),
    ("change travel to car", "car"), ("replace the flight with a train", "train"),
    ("flight instead of train", "flight"),
])
def test_ways_to_ask_for_another_way_of_travelling(text, mode):
    assert parse_feedback(text, CONSTRAINTS, "normal")["changes"] == {"travel_mode": mode}


@pytest.mark.parametrize("text", ["change to a bus tour", "replace the museum with a bus tour", "add a train ride",
                                  "change it to a train museum visit", "take the bus tour instead of the museum"])
def test_a_ride_or_a_visit_is_not_a_way_of_travelling(text):
    assert "travel_mode" not in parse_feedback(text, CONSTRAINTS, "normal")["changes"]


def test_the_same_with_langgraph():
    pytest.importorskip("langgraph")
    from app.graph.workflow import GraphPlanner
    from app.tests.test_graph.test_graph_engine import deps

    tools = Counting()
    graph = GraphPlanner(deps(tools=tools))
    first = graph.start(REQ, thread_id="c1")
    tools.asked.clear()
    hotel = graph.resume("c1", {"action": "revise", "feedback": "a cheaper hotel"})
    assert searches(tools) == {"hotel"} and hotel["flight"] == first["flight"]
    assert hotel["part_levels"] == {"hotel": "cheaper"} and hotel["activities"] == first["activities"]
    tools.asked.clear()
    paced = graph.resume("c1", {"action": "revise", "feedback": "relaxed pace"})
    assert searches(tools) == set() and paced["hotel"] == hotel["hotel"] and paced["itinerary"]
