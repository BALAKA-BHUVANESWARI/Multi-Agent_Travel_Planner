"""Pictures for the sights of a saved day-by-day plan."""
import pytest

from app.integrations import wikipedia
from app.services.plan_photos import plan_photos, plan_sights
from app.services.trip_service import ApiError, PlannerService
from app.tools import explore_tools
from app.tools.client import InProcessClient

REQ = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2"
PARIS = {"name": "Paris", "lat": 48.86, "lon": 2.35}


def state_with(*items):
    return {"constraints": {"destination_geo": PARIS},
            "itinerary": {"days": [{"items": list(items)}]}}


def activity(pid, name, **extra):
    return {"type": "activity", "id": pid, "name": name, **extra}


def test_only_real_sights_are_looked_up_once_each():
    state = state_with(activity("wp-1", "Notre-Dame de Paris", lat=48.853, lon=2.35),
                       activity("gen-dinner", "Dinner at a well-reviewed local restaurant"),
                       activity("generic-indoor", "Indoor downtime"),
                       {"type": "hotel", "name": "Check out"},
                       activity("wp-1", "Notre-Dame de Paris"))
    assert plan_sights(state) == [{"id": "wp-1", "name": "Notre-Dame de Paris", "lat": 48.853, "lon": 2.35}]


def test_a_long_plan_is_looked_up_in_batches(make, monkeypatch):
    monkeypatch.setenv("REAL_DATA", "1")
    sights = [activity(f"wp-{i}", f"Sight number {i}", lat=48.86, lon=2.35) for i in range(30)]
    monkeypatch.setattr(wikipedia, "article_info", lambda titles, fetch=None: {
        t: {"title": t, "lat": 48.86, "lon": 2.35, "image": True} for t in titles})
    tools = InProcessClient()
    r = plan_photos(state_with(*sights), make(tools=tools).deps)
    assert tools.call_count("find_place_photos") == 3
    assert r["photos"] == {f"wp-{i}": f"Sight number {i}" for i in range(30)} and r["checked"] is True
    assert r["attribution"] == [wikipedia.ATTRIBUTION]


def test_the_destination_article_is_confirmed_even_with_no_named_sights(make, monkeypatch):
    monkeypatch.setenv("REAL_DATA", "1")
    monkeypatch.setattr(wikipedia, "article_info", lambda titles, fetch=None: {
        "Paris": {"title": "Paris", "lat": 48.8567, "lon": 2.3522, "image": True}})
    r = plan_photos(state_with(activity("gen-walk", "Old town and city-centre walking tour")), make().deps)
    assert r["place"] == "Paris" and r["photos"] == {} and r["checked"] is True


def test_a_longer_plan_name_matches_only_an_article_on_the_same_spot(monkeypatch):
    monkeypatch.setenv("REAL_DATA", "1")
    pages = {"Fort Aguada": {"title": "Fort Aguada", "lat": 15.492, "lon": 73.774, "image": True}}
    monkeypatch.setattr(wikipedia, "article_info",
                        lambda titles, fetch=None: {t: pages[t] for t in titles if t in pages})
    goa = {"name": "Goa", "lat": 15.49, "lon": 73.82}
    sight = {"id": "a", "name": "Fort Aguada and lighthouse"}
    here = explore_tools.find_place_photos(goa, [{**sight, "lat": 15.493, "lon": 73.773}])
    elsewhere = explore_tools.find_place_photos(goa, [{**sight, "lat": 15.30, "lon": 74.10}])
    unknown_spot = explore_tools.find_place_photos(goa, [sight])
    assert here["sights"] == {"a": "Fort Aguada"} and elsewhere["sights"] == {} == unknown_spot["sights"]


def test_offline_or_failing_lookup_says_not_checked(make):
    state = state_with(activity("wp-1", "Notre-Dame de Paris"))
    assert plan_photos(state, make().deps) == {"photos": {}, "place": None, "checked": False, "attribution": []}
    down = make(tools=InProcessClient(failures={"find_place_photos": -1})).deps
    assert plan_photos(state, down)["checked"] is False


def test_a_saved_plan_can_be_asked_for_its_photos_without_changing_it(make):
    service = PlannerService(make())
    plan = service.plan(REQ)
    before = service.get(plan["thread_id"])
    assert set(service.photos({"thread_id": plan["thread_id"]})) == {"photos", "place", "checked", "attribution"}
    assert service.get(plan["thread_id"]) == before


@pytest.mark.parametrize("body,status", [(None, 422), ({}, 422), ({"thread_id": 5}, 422),
                                         ({"thread_id": "x" * 65}, 422), ({"thread_id": "nope"}, 404)])
def test_photos_refuses_bad_requests(make, body, status):
    with pytest.raises(ApiError) as e:
        PlannerService(make()).photos(body)
    assert e.value.status == status


def test_another_travellers_plan_stays_private(make):
    service = PlannerService(make())
    owner = service.account("POST", "auth/register", {"email": "a@example.com", "password": "long-test-pass-1"})
    plan = service.plan(REQ, token=owner["token"])
    with pytest.raises(ApiError) as e:
        service.photos({"thread_id": plan["thread_id"]})
    assert e.value.status == 404
