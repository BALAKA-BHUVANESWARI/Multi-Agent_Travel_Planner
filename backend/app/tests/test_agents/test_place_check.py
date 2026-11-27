""""Did you mean Goa?": a typed or spoken name that only matches a tiny place is asked about, never planned silently."""
import pytest

from app.graph.state import TripState
from app.integrations import openmeteo, openstreetmap, wikipedia, wikivoyage
from app.services import chat_service, geo_service
from app.services.trip_service import PlannerService

# the request that was planned as a hamlet of 45 people in Italy
SAID = "Make a trip to 3 days in Gova from the Banglore within 30k budget by flight, from bangalore"


def _hit(name, cc, country, admin1, lat, lon, population):
    return {"name": name, "latitude": lat, "longitude": lon, "feature_code": "PPL", "country_code": cc,
            "country": country, "admin1": admin1, "population": population}


GEOCODER = {
    "gova": [_hit("Gova", "IT", "Italy", "Emilia-Romagna", 44.34, 10.51, 45)],
    "kasauli": [_hit("Kasauli", "IN", "India", "Himachal Pradesh", 30.9, 76.96, 3800)],
    "parys": [_hit("Parys", "ZA", "South Africa", "Free State", -26.9, 27.46, 44000)],
}


@pytest.fixture(autouse=True)
def online(monkeypatch):
    monkeypatch.setenv("REAL_DATA", "1")
    monkeypatch.setattr(openmeteo, "fetch_json",
                        lambda url, params, timeout=6.0: {"results": GEOCODER.get(params["name"].lower(), [])})
    for module, name in ((openstreetmap, "place_elements"), (openstreetmap, "restaurant_elements"),
                         (openstreetmap, "nearby"), (wikipedia, "nearby_sights"), (wikivoyage, "listings"),
                         (wikivoyage, "eat_listings"), (wikivoyage, "load_chunks")):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, lambda *a, **k: [])
    for name in ("forecast", "climate"):
        monkeypatch.setattr(openmeteo, name, lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    geo_service._CACHE.clear()
    yield
    geo_service._CACHE.clear()


@pytest.mark.parametrize("typed,meant", [("Gova", "Goa"), ("Gaoa", "Goa"), ("Jaipir", "Jaipur"), ("Manli", "Manali"),
                                         ("Parls", "Paris"), ("Lisbn", "Lisbon"), ("Leha", "Leh")])
def test_one_slip_from_a_well_known_place_is_noticed(typed, meant):
    tiny = {"source": "open-meteo-geocoding", "population": 45, "name": typed}
    assert geo_service.meant_instead(typed, tiny)["name"] == meant


@pytest.mark.parametrize("typed,geo", [
    ("Kasauli", {"source": "open-meteo-geocoding", "population": 3800}),   # a real small town, nothing close to it
    ("Bir", {"source": "open-meteo-geocoding", "population": 0}),          # "blr" is an airport code, not a place
    ("Gova", {"source": "open-meteo-geocoding", "population": 90000}),     # a sizeable town is believed
    ("Goa", {"source": "curated", "population": 0}),
])
def test_other_places_are_not_questioned(typed, geo):
    assert geo_service.meant_instead(typed, geo) is None


def test_the_planner_asks_instead_of_planning_a_hamlet(make):
    state = PlannerService(make(), require_auth=False).plan(SAID)
    assert state["status"] == "needs_info" and not state.get("itinerary") and not state.get("flight")
    assert state["place_check"] == {"role": "destination", "typed": "Gova", "suggested": "Goa",
                                    "suggested_label": "Goa, India",
                                    "found_label": "Gova, Emilia-Romagna, Italy"}
    assert "Did you mean Goa, India?" in state["message"]
    assert "place_check" in TripState.__annotations__                      # or LangGraph would drop it


def test_either_answer_is_followed(make):
    svc = PlannerService(make(), require_auth=False)
    meant = svc.plan(f"{SAID} | place: Gova = Goa")
    assert meant["status"] == "awaiting_approval" and meant["constraints"]["destination"] == "goa"
    kept = svc.plan(f"{SAID} | place: Gova = Gova")
    assert kept["status"] == "awaiting_approval" and kept["constraints"]["destination"] == "gova-it"
    assert not kept.get("place_check")


def test_the_form_marker_and_a_travel_choice_keep_the_answer(make):
    svc = PlannerService(make(), require_auth=False)
    form = "Plan a 3 day trip from Delhi, budget 30000 for 2 people | destination: Gova"
    assert svc.plan(form)["place_check"]["typed"] == "Gova"
    answered = svc.plan(f"{form} | place: Gova = Goa | travel: by train")
    assert answered["constraints"]["destination"] == "goa" and answered["constraints"]["travel_mode"] == "train"


def test_a_misspelled_starting_place_is_asked_about_too(make):
    state = PlannerService(make(), require_auth=False).plan("3 days from Gova to Jaipur, budget 30000")
    assert state["status"] == "needs_info" and state["place_check"]["role"] == "origin"


@pytest.mark.parametrize("typed", ["Kasauli", "Parys"])
def test_real_places_are_still_planned_without_a_question(make, typed):
    state = PlannerService(make(), require_auth=False).plan(f"3 days in {typed} from Delhi, budget 3 lakh by flight")
    assert state["status"] == "awaiting_approval" and not state.get("place_check")


@pytest.mark.parametrize("answer,chosen", [
    ("Goa", "Goa"), ("goa, India", "Goa"), ("yes", "Goa"), ("Yes, Goa", "Goa"), ("ok", "Goa"), ("I meant Goa", "Goa"),
    ("Gova", "Gova"), ("no, Gova in Italy", "Gova"), ("Udaipur", "Udaipur"), ("go to Manali", "Manali"),
])
def test_chat_answers_to_the_question(make, answer, chosen):
    asked = PlannerService(make(), require_auth=False).plan(SAID)
    assert chat_service.complete_request(asked, answer).endswith(f"| place: Gova = {chosen}")


def test_the_chat_offers_both_places_and_plans_the_chosen_one(make):
    svc = PlannerService(make(), require_auth=False)
    first = svc.chat({"message": SAID})
    assert [s["label"] for s in first["suggestions"]] == ["Goa, India", "Gova, Emilia-Romagna, Italy"]
    assert "Pick one below" in first["reply"]
    second = svc.chat({"message": "Goa", "thread_id": first["result"]["thread_id"]})
    assert second["result"]["constraints"]["destination"] == "goa"


def test_changing_the_destination_to_a_misspelling_does_not_move_the_trip(make):
    svc = PlannerService(make(), require_auth=False)
    state = svc.plan("3 days in Jaipur from Delhi, budget 60000 by train")
    changed = svc.approve(state["thread_id"], {"action": "revise", "feedback": "change destination to Gova"})
    assert changed["constraints"]["destination"] == "jaipur"
    said = " ".join([changed.get("message", ""), changed.get("notice", "")])
    assert "change destination to Goa" in said
