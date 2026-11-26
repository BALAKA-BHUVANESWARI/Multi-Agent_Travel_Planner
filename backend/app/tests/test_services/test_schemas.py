"""The data shapes in app/schemas must match what the code really produces. Real plans are run, and every
record must have all the required keys and no key that its shape does not declare."""
import pytest

from app.schemas.accommodation import AccommodationResult, HotelOption
from app.schemas.activity import Activity, ActivityResult, Dining, Eatery, TopSight
from app.schemas.budget import BudgetLines, BudgetReport
from app.schemas.itinerary import DayPlan, Itinerary, ItineraryItem
from app.schemas.transport import (
    Journey,
    TransportOption,
    TransportResult,
    TravelChoice,
)
from app.schemas.traveller import GroupMember, GroupMemberReport
from app.schemas.trip import Booking, Place, Suggestion, TripConstraints
from app.services import dining_service, group_service

GOA = "Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2, beaches and food"


def check(shape, record):
    keys = set(record)
    missing = shape.__required_keys__ - keys
    unknown = keys - shape.__required_keys__ - shape.__optional_keys__
    assert not missing and not unknown, f"{shape.__name__}: missing {sorted(missing)}, undeclared {sorted(unknown)}"


def check_all(shape, records):
    for record in records:
        check(shape, record)


def check_plan(state):
    c = state["constraints"]
    check(TripConstraints, c)
    for key in ("origin_geo", "destination_geo"):
        if c.get(key):
            check(Place, c[key])
    check(TransportResult, state["flight"])
    check_all(TransportOption, state["flight"]["options"] + [state["flight"]["selected"]])
    if state["flight"].get("journey"):
        check(Journey, state["flight"]["journey"])
    check(AccommodationResult, state["hotel"])
    check_all(HotelOption, state["hotel"]["options"] + [state["hotel"]["selected"]])
    check(ActivityResult, state["activities"])
    check_all(Activity, state["activities"]["candidates"])
    check_all(TopSight, state["activities"]["top_sights"])
    check(Dining, state["activities"]["dining"])
    check(Itinerary, state["itinerary"])
    check_all(DayPlan, state["itinerary"]["days"])
    check_all(ItineraryItem, [item for day in state["itinerary"]["days"] for item in day["items"]])
    check(BudgetReport, state["budget_report"])
    check(BudgetLines, state["budget_report"]["lines"])
    check_all(Suggestion, (state.get("alternatives") or {}).get("items", []))


@pytest.mark.parametrize("request_text", [
    GOA,
    "Plan a 3 day trip to Paris from Mumbai in December, budget 5 lakh for 2, museums",
    "3 days in Manali from Delhi in January, budget 40k for 1, adventure, by bus",
    "Plan a 6 day trip to Goa from Delhi on 25 December, budget 2 lakh for 2, by bike",
    "Plan a 4 day trip to Jaipur from Delhi on 25 December, budget 3000 for 4",
])
def test_plans_match_the_shapes(make, request_text):
    state = make().start(request_text, thread_id="shape")
    assert state["status"] == "awaiting_approval", state.get("message")
    check_plan(state)


def test_group_and_booking_shapes(make):
    group = group_service.clean_group([{"name": "A", "likes": ["beaches"], "avoid": ["temples"]},
                                       {"name": "B", "likes": ["food"]}])
    planner = make()
    state = planner.start(GOA, thread_id="group", group=group)
    check_all(GroupMember, state["group"])
    check_all(GroupMemberReport, state["group_report"])
    state = planner.resume("group", {"action": "approve"})
    check(Booking, state["booking"])


def test_questions_asked_back_match_the_shapes(make):
    planner = make()
    planner.deps.ask_travel_mode = True
    state = planner.start(GOA, thread_id="ask")
    assert state["status"] == "needs_info"
    check_all(TravelChoice, state["travel_options"])
    state = make().start("5 day trip from Delhi in December, budget 60k for 2", thread_id="ideas")
    check_all(Suggestion, state["suggestions"])


def test_restaurant_entries_match_the_shape():
    elements = [{"type": "node", "tags": {"name": "Spice Garden", "amenity": "restaurant", "diet:vegetarian": "yes"}},
                {"type": "wv", "tags": {"name": "Fisherman's Catch", "description:en": "Fresh seafood"}}]
    dining = dining_service.build_dining(elements)
    assert dining["veg"] and dining["nonveg"]
    check_all(Eatery, dining["veg"] + dining["nonveg"] + dining["other"])
