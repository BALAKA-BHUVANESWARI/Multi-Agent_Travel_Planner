import time
from datetime import date

import pytest

from app.core import config
from app.database.repositories import Store
from app.graph.deps import Deps
from app.graph.runner import Planner
from app.services.llm_service import LLMRouter
from app.tools.client import InProcessClient, call_with_retry
from app.tools.errors import ToolError

REQ = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2"


def test_workers_run_concurrently(make):
    tools = InProcessClient(latency=0.3)
    p = make(tools=tools)
    t0 = time.perf_counter()
    s = p.start(REQ)
    elapsed = time.perf_counter() - t0
    assert s["status"] == "awaiting_approval" and s["retries"] == 0
    first5 = sorted(tools.calls, key=lambda c: c["start"])[:5]       # the 4 workers + the restaurant lookup
    assert {c["name"] for c in first5} == {"search_flights", "search_hotels", "get_weather", "search_places",
                                           "search_dining"}
    assert max(c["start"] for c in first5) < min(c["end"] for c in first5), "calls must overlap in time"
    assert elapsed < 0.3 * 2.2, f"sequential would take ~1.2s; took {elapsed:.2f}s"


def test_transient_failure_retried_with_exponential_backoff(make):
    tools = InProcessClient(failures={"search_flights": 2})
    p = make(tools=tools)
    sleeps = []
    p.deps.sleep = sleeps.append
    s = p.start(REQ)
    assert tools.call_count("search_flights") == 3
    assert s["flight"]["selected"] and not [w for w in s["warnings"] if "Flight" in w]
    assert sleeps == [config.TOOL_BACKOFF_BASE, config.TOOL_BACKOFF_BASE * 2]


def test_tool_outage_yields_partial_plan_with_warnings(make):
    tools = InProcessClient(failures={"search_hotels": -1})
    p = make(tools=tools)
    s = p.start(REQ)
    assert tools.call_count("search_hotels") == config.TOOL_RETRIES
    assert s["status"] == "awaiting_approval"
    assert s["hotel"]["selected"] is None and s["budget_report"]["incomplete"] == ["hotel"]
    assert any("Hotel search failed" in w for w in s["warnings"])
    assert any("Partial plan" in w for w in s["warnings"])
    assert any(i["code"] == "partial_plan" for i in s["critic_issues"])
    assert s["itinerary"]["days"] and "Not available" in s["summary"]
    assert s["flight"]["selected"]                              # the other agents still delivered
    assert p.resume(s["thread_id"], {"action": "approve"})["status"] == "booked"


@pytest.mark.parametrize("tool", ["search_flights", "get_weather", "search_places"])
def test_each_single_tool_outage_degrades_gracefully(make, tool):
    s = make(tools=InProcessClient(failures={tool: -1})).start(REQ)
    assert s["status"] == "awaiting_approval" and s["itinerary"]
    assert any("failed after retries" in w for w in s["warnings"])


def test_weather_outage_skips_rain_swaps_with_warning(make):
    s = make(tools=InProcessClient(failures={"get_weather": -1})).start(REQ)
    assert any("No weather data" in w for w in s["warnings"]) and s["itinerary"]["swaps"] == []


def test_all_tools_down_still_returns_something_sane(make):
    tools = InProcessClient(failures={n: -1 for n in ("search_flights", "search_hotels", "get_weather",
                                                      "search_places")})
    s = make(tools=tools).start(REQ)
    assert s["status"] == "awaiting_approval" and s["budget_report"]["lines"]["flight"] == 0
    assert len(s["warnings"]) >= 4


def test_non_retryable_errors_are_not_retried():
    calls = []

    class C:
        def call(self, name, **kw):
            calls.append(name)
            raise ToolError("bad input", retryable=False)
    with pytest.raises(ToolError):
        call_with_retry(C(), "x", sleep=lambda s: None)
    assert len(calls) == 1


def test_booking_failure_keeps_plan_awaiting_approval(make):
    tools = InProcessClient(failures={"book_trip": -1})
    p = make(tools=tools)
    s = p.start(REQ)
    s2 = p.resume(s["thread_id"], {"action": "approve"})
    assert s2["status"] == "awaiting_approval" and not s2.get("booking")
    assert any("Booking failed" in w for w in s2["warnings"]) and p.deps.store.booking_count() == 0
    tools.failures.clear()                                     # service recovers
    assert p.resume(s["thread_id"], {"action": "approve"})["status"] == "booked"


def test_paused_run_resumes_after_restart(tmp_path):
    db = str(tmp_path / "trips.db")

    def planner():
        store = Store(db)
        deps = Deps(tools=InProcessClient(), store=store, llm=LLMRouter(env={}, store=store),
                    today=date(2026, 11, 24), sleep=lambda s: None)
        return Planner(deps)
    p1 = planner()
    s = p1.start(REQ)
    tid = s["thread_id"]
    p1.deps.store.close()                                      # "process exits"
    p2 = planner()                                             # brand-new process, same DB file
    paused = p2.get(tid)
    assert paused["status"] == "awaiting_approval" and paused["itinerary"] == s["itinerary"]
    done = p2.resume(tid, {"action": "approve"})
    assert done["status"] == "booked"
    p3 = planner()
    assert p3.resume(tid, {"action": "approve"})["booking"]["booking_id"] == done["booking"]["booking_id"]
    assert p3.deps.store.booking_count() == 1


def test_resume_on_non_waiting_thread_raises(make):
    p = make()
    s = p.start("trip to goa")                                  # needs_info
    with pytest.raises(ValueError):
        p.resume(s["thread_id"], {"action": "approve"})


def test_threads_are_independent(make):
    p = make()
    a, b = p.start(REQ), p.start(REQ.replace("Goa", "Jaipur"))
    assert a["thread_id"] != b["thread_id"]
    p.resume(a["thread_id"], {"action": "cancel"})
    assert p.get(b["thread_id"])["status"] == "awaiting_approval"


def test_restaurant_outage_does_not_break_the_plan(make):
    tools = InProcessClient(failures={"search_dining": -1})
    s = make(tools=tools).start(REQ)
    assert s["status"] == "awaiting_approval" and s["activities"]["candidates"]
    dn = s["activities"]["dining"]
    assert dn["veg"] == [] and dn["nonveg"] == [] and "unavailable" in dn["note"]
    assert not [w for w in s["warnings"] if "Unresolved" in w]
