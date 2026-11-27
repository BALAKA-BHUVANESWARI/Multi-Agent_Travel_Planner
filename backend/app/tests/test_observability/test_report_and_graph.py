"""The terminal report, and records from the LangGraph engine (skipped where LangGraph is not installed)."""
import pytest

from app.observability import __main__ as cli
from app.observability import recorder as observe
from app.observability.store import RecordStore
from app.services.trip_service import PlannerService

GOA = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2 by flight"


def test_the_report_lists_requests_and_their_steps(make, capsys):
    assert cli.main([]) == 0 and "No records yet" in capsys.readouterr().out
    PlannerService(make()).plan(GOA)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "plan" in out and "agent: activities [ok]" in out and "  tool: search_places [ok]" in out
    assert cli.main(["1", "--text"]) == 0 and "No detailed text" in capsys.readouterr().out
    assert cli.main(["9"]) == 0 and "no request number 9" in capsys.readouterr().out


def test_the_report_on_an_empty_database():
    assert "No requests recorded yet" in cli.report(RecordStore(":memory:"))


def test_langgraph_steps_and_the_approval_are_recorded(make):
    pytest.importorskip("langgraph")
    from app.graph.workflow import GraphPlanner
    recorder = observe.Recorder(RecordStore(":memory:"))
    svc = PlannerService(GraphPlanner(make().deps), require_auth=False, recorder=recorder)
    state = svc.plan(GOA)
    svc.approve(state["thread_id"], {"action": "revise", "feedback": "zzz qqq"})
    svc.approve(state["thread_id"], {"action": "approve"})
    booked, revised, plan = recorder.store.runs()
    agents = {s["name"] for s in recorder.store.spans(plan["id"]) if s["type"] == "agent"}
    assert {"guardrail", "intake", "flight", "hotel", "weather", "activities", "budget", "critic"} <= agents
    tools = [s for s in recorder.store.spans(plan["id"]) if s["type"] == "tool"]
    assert tools and all(s["parent_id"] for s in tools)
    assert "feedback_check" in {s["name"] for s in recorder.store.spans(revised["id"])}
    assert booked["attrs"]["outcome"] == "booked"
    assert any(s["name"] == "writer" for s in recorder.store.spans(booked["id"]))
