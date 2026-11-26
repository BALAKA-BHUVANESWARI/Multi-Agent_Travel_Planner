"""Long overland routes between countries: car and bike where a road link is listed, always with a warning."""
from datetime import date

import pytest

from app.agents.transport_agent import build_travel_options
from app.database.repositories import Store
from app.graph.deps import Deps
from app.services.llm_service import LLMRouter
from app.services.pricing import transport_estimator as transport
from app.services.trip_toolkit import footprint
from app.tools.client import InProcessClient
from app.tools.errors import ToolError
from app.tools.flight_tools import search_flights

MUMBAI = {"slug": "mumbai", "name": "Mumbai", "country": "India", "cc": "IN", "lat": 19.08, "lon": 72.88,
          "cost_factor": 1.0, "population": 12_000_000}
BANGKOK = {"slug": "bangkok", "name": "Bangkok", "country": "Thailand", "cc": "TH", "lat": 13.75, "lon": 100.5,
           "cost_factor": 1.3, "population": 8_000_000}


def _constraints(origin, destination):
    return {"origin": origin["slug"], "destination": destination["slug"], "origin_geo": origin,
            "destination_geo": destination, "start_date": "2027-01-10", "days": 5, "travelers": 2}


def _options(origin, destination):
    store = Store(":memory:")
    deps = Deps(tools=InProcessClient(), store=store, llm=LLMRouter(env={}, store=store), today=date(2026, 11, 26),
                sleep=lambda s: None)
    rows = build_travel_options(_constraints(origin, destination), deps)
    return {r["mode"]: r for r in rows}


@pytest.mark.parametrize("origin,destination", [(MUMBAI, BANGKOK), (BANGKOK, MUMBAI)])
def test_car_and_bike_are_offered_with_a_border_warning(origin, destination):
    options = _options(origin, destination)
    for mode in ("car", "bike"):
        assert options[mode]["available"], options[mode]
        warning = options[mode]["warning"]
        assert warning.startswith("Check before you plan")
        assert "Myanmar" in warning and "leaves out permit, visa and escort costs" in warning
        assert "Long journey" in warning                      # the usual long-ride warning is kept too
    for mode in ("train", "bus"):
        assert not options[mode]["available"]
        assert f"no through {mode} service" in options[mode]["reason"]
    assert "warning" not in options["flight"]


def test_other_long_international_routes_stay_blocked_with_a_reason():
    assert "not confirmed a road link" in transport.overland_block("car", 3000, "IN", "VN")
    assert "not confirmed a road link" in transport.overland_block("bike", 6000, "IN", "FR")


def test_short_hops_and_domestic_trips_get_no_border_warning():
    for args in (("car", 900, "IN", "NP"), ("train", 2500, "IN", "IN"), ("car", 2500, "", "TH")):
        assert transport.overland_block(*args) == ""
        assert transport.border_warning(*args) == ""


def test_emissions_comparison_follows_the_same_rule():
    rows = {r["mode"]: r for r in footprint.compare(_constraints(MUMBAI, BANGKOK), "car")["modes"]}
    assert rows["car"]["available"] and rows["bike"]["available"]
    assert not rows["train"]["available"] and not rows["bus"]["available"]


def test_a_thai_island_still_has_no_road_link():
    samui = {**BANGKOK, "slug": "ko-samui", "name": "Ko Samui", "lat": 9.51, "lon": 100.01}
    with pytest.raises(ToolError, match="crosses the sea"):
        search_flights("mumbai", "ko-samui", "2027-01-10", "2027-01-14", 2, origin_geo=MUMBAI,
                       destination_geo=samui, mode="car", live_prices=False)


def test_the_warning_stays_on_the_finished_plan(tmp_path):
    from app.graph.runner import Planner
    store = Store(str(tmp_path / "road.db"))
    deps = Deps(tools=InProcessClient(), store=store, llm=LLMRouter(env={}, store=store), today=date(2026, 11, 26),
                sleep=lambda s: None)
    state = Planner(deps).start("Plan a 12 day trip to Bangkok from Mumbai in January, budget 5 lakh for 2, by car")
    assert state["status"] == "awaiting_approval"
    assert state["flight"]["journey"]["warning"].startswith("Check before you plan")
    assert "Check before you plan" in state["summary"]


@pytest.mark.parametrize("mode", ["car", "bike"])
def test_suggestions_never_propose_a_doubtful_border(mode, monkeypatch):
    from app.tools import destination_tools
    monkeypatch.setattr(destination_tools.transport, "is_long", lambda *a: False)   # leave only the border rule
    out = destination_tools.recommend_destinations("mumbai", "2027-01-10", 12, 2, 5_000_000, ["beach"], mode=mode,
                                                   scope="abroad", limit=20)
    names = str(out)
    assert "Bangkok" not in names and "Phuket" not in names
