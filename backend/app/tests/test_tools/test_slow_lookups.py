"""A replan must not sit through the same slow or empty OpenStreetMap search again."""
import threading
import time

import pytest

from app.integrations import openstreetmap as osm
from app.integrations import wikivoyage
from app.observability import recorder as observe
from app.observability.store import RecordStore
from app.services import geo_service
from app.tools import places_tools

HERE = (44.3355, 10.5132, 3500)
CAFE = {"type": "node", "id": 1, "lat": 44.33, "lon": 10.51,
        "tags": {"name": "Green Leaf", "amenity": "restaurant", "diet:vegetarian": "only"}}


class Overpass:
    """A pretend Overpass that answers only when released."""

    def __init__(self, answer):
        self.answer, self.calls, self.release = answer, 0, threading.Event()

    def __call__(self, query, timeout=0, budget=0):
        self.calls += 1
        assert self.release.wait(10)
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"elements": self.answer}


def finished():
    deadline = time.monotonic() + 5
    while osm._RUNNING and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not osm._RUNNING


@pytest.fixture
def dining(monkeypatch):
    monkeypatch.setenv("REAL_DATA", "1")
    monkeypatch.setattr(places_tools, "DINING_GRACE", 0.2)
    monkeypatch.setattr(osm, "restaurant_elements", osm.live_restaurant_elements)    # not the offline stand-in
    monkeypatch.setattr(wikivoyage, "eat_listings", lambda *a, **k: [])
    place = {"slug": "x-it", "name": "X", "lat": HERE[0], "lon": HERE[1], "cc": "IT", "population": 45}

    def search():
        started = time.monotonic()
        result = places_tools.search_dining("x-it", destination_geo=place)
        return result, time.monotonic() - started
    return search


def test_a_replan_does_not_wait_again_for_a_search_that_is_still_running(dining, monkeypatch):
    overpass = Overpass([CAFE] * 8)
    monkeypatch.setattr(osm, "_post_with_mirrors", overpass)
    first, waited = dining()
    assert waited >= 0.2 and first["data_quality"] == "none"
    for _ in range(2):                                        # the two cheaper replans
        again, waited = dining()
        assert waited < 0.15 and again["data_quality"] == "none"
    assert overpass.calls == 1                                # and the busy free server is not asked again
    overpass.release.set()
    finished()
    later, _ = dining()                                       # the late answer was kept and is used
    assert [r["name"] for r in later["veg"]] == ["Green Leaf"] and not osm._GIVEN_UP


@pytest.mark.parametrize("answer", [[], OSError("busy")])
def test_nothing_found_or_a_failure_is_remembered_for_a_short_while(monkeypatch, answer):
    overpass = Overpass(answer)
    overpass.release.set()
    monkeypatch.setattr(osm, "_post_with_mirrors", overpass)
    assert osm.live_restaurant_elements(*HERE) == []
    calls = overpass.calls
    assert osm.live_restaurant_elements(*HERE) == [] and overpass.calls == calls
    for memory in (osm._EMPTY, osm._FAILED):                  # after the short while it is asked again
        for key in memory:
            memory[key] -= osm.FAILURE_MEMORY + 1
    osm.live_restaurant_elements(*HERE)
    assert overpass.calls > calls


def test_places_and_restaurants_are_remembered_separately(monkeypatch):
    overpass = Overpass([])
    overpass.release.set()
    monkeypatch.setattr(osm, "_post_with_mirrors", overpass)
    osm.place_elements(*HERE)
    asked = overpass.calls
    osm.live_restaurant_elements(*HERE)
    assert overpass.calls > asked


def test_someone_who_has_not_given_up_still_gets_their_own_try(monkeypatch):
    overpass = Overpass([CAFE])
    monkeypatch.setattr(osm, "_post_with_mirrors", overpass)
    first = threading.Thread(target=osm.place_elements, args=HERE)
    first.start()
    while not osm._RUNNING:
        time.sleep(0.01)
    osm.gave_up_waiting("restaurants", *HERE)                 # another kind of search: places are unaffected
    second = threading.Thread(target=osm.place_elements, args=HERE)
    second.start()
    overpass.release.set()
    first.join(5)
    second.join(5)
    assert overpass.calls == 2 and not osm._GIVEN_UP


def test_the_records_say_why_it_was_skipped(dining, monkeypatch):
    overpass = Overpass([CAFE])
    monkeypatch.setattr(osm, "_post_with_mirrors", overpass)
    recorder = observe.Recorder(RecordStore(":memory:"), False)
    with recorder.run("plan"):
        dining()
        dining()
    steps = [s for s in recorder.store.spans() if s["name"] == "openstreetmap.restaurants" and s["type"] == "retrieval"]
    assert [(s["status"], s["attrs"].get("reason")) for s in steps] == [("skipped", "still_running")]
    overpass.release.set()
    finished()
