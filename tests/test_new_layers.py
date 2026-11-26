"""The new features through LangGraph and FastAPI. Each part is skipped when the library is not installed."""
from datetime import date

import pytest

from travel_planner.deps import Deps
from travel_planner.llm.router import LLMRouter
from travel_planner.service import PlannerService
from travel_planner.store import Store
from travel_planner.tools.client import InProcessClient

REQ = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2 by train"
PW = "correct-horse-battery"


def make_deps(path):
    store = Store(str(path))
    return Deps(tools=InProcessClient(), store=store, llm=LLMRouter(env={}, store=store), today=date(2026, 11, 24),
                sleep=lambda s: None)


def test_langgraph_keeps_group_changes_resets_warnings_and_deletes(tmp_path):
    pytest.importorskip("langgraph")
    from travel_planner.graph import GraphPlanner
    planner = GraphPlanner(make_deps(tmp_path / "g.db"))
    group = [{"name": "Asha", "likes": ["history"], "avoid": []}]
    first = planner.start(REQ, thread_id="g1", group=group, memory={"pace": "relaxed"})
    assert first["group_report"][0]["name"] == "Asha" and first["alternatives"]["items"]
    assert first["constraints"]["pace"] == "relaxed"
    changed = planner.resume("g1", {"action": "revise", "feedback": "change destination to Jaipur, go by flight"})
    assert changed["constraints"]["destination"] == "jaipur" and changed["itinerary"]["destination"] == "jaipur"
    assert not any("Road and rail" in w for w in changed["warnings"])
    planner.delete("g1")
    assert planner.deps.store.load_state("g1") is None


def test_fastapi_routes_for_accounts_cancellation_and_limits(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from travel_planner.api import create_app
    from travel_planner.ratelimit import RateLimiter
    from travel_planner.runner import Planner
    service = PlannerService(Planner(make_deps(tmp_path / "f.db")), limiter=RateLimiter({"plan": [(1, 60)]}),
                             require_auth=False)
    web = TestClient(create_app(service))
    token = web.post("/api/auth/register", json={"email": "f@example.com", "password": PW}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert web.get("/api/me").status_code == 401
    assert web.get("/api/me", headers=auth).json()["user"]["email"] == "f@example.com"
    assert web.put("/api/me/memory", json={"pace": "relaxed"}, headers=auth).json()["memory"]["pace"] == "relaxed"
    plan = web.post("/api/plan", json={"request": REQ, "group": [{"name": "A", "likes": ["forts"]}]},
                    headers=auth).json()
    tid = plan["thread_id"]
    assert plan["group_report"][0]["name"] == "A"
    assert web.get(f"/api/plan/{tid}").status_code == 404                       # not the owner
    assert web.post(f"/api/approve/{tid}", json={"action": "approve"}, headers=auth).json()["status"] == "booked"
    preview = web.post(f"/api/booking/{tid}/cancel", json={}, headers=auth).json()
    assert preview["status"] == "confirm_cancellation"
    done = web.post(f"/api/booking/{tid}/cancel", json={"confirm": True}, headers=auth).json()
    assert done["status"] == "booking_cancelled"
    assert web.get("/api/trips", headers=auth).json()["trips"][0]["status"] == "booking_cancelled"
    limited = web.post("/api/plan", json={"request": REQ}, headers=auth)
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
    assert web.delete("/api/me/memory", headers=auth).json()["memory"] == {"remember": False}
    assert web.request("DELETE", "/api/me", json={"confirm": True}, headers=auth).status_code == 200
