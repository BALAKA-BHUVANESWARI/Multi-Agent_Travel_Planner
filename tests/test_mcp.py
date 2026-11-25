"""MCP round trip: identical results in-process and through the stdio MCP server."""
from datetime import date

import pytest

pytest.importorskip("mcp")

from travel_planner.deps import Deps  # noqa: E402
from travel_planner.llm.router import LLMRouter  # noqa: E402
from travel_planner.runner import Planner  # noqa: E402
from travel_planner.store import Store  # noqa: E402
from travel_planner.tools.client import InProcessClient, McpClient  # noqa: E402
from travel_planner.tools.errors import ToolError  # noqa: E402

ARGS = {
    "resolve_place": dict(query="Paris"),
    "search_flights": dict(origin="delhi", destination="goa", depart_date="2026-12-10",
                           return_date="2026-12-14", travelers=2),
    "search_hotels": dict(destination="goa", checkin="2026-12-10", nights=4, travelers=2),
    "get_weather": dict(destination="goa", start_date="2026-12-10", days=5, today="2026-11-24"),
    "search_places": dict(destination="goa", preferences=["beach", "food"]),
    "search_dining": dict(destination="goa"),
    "book_trip": dict(idempotency_key="abc", summary={"x": 1}),
}


@pytest.fixture(scope="module")
def mcp_client():
    c = McpClient()
    yield c
    c.close()


@pytest.mark.parametrize("tool", sorted(ARGS))
def test_same_result_in_process_and_over_mcp(mcp_client, tool):
    assert mcp_client.call(tool, **ARGS[tool]) == InProcessClient().call(tool, **ARGS[tool])


def test_any_destination_tools_match_over_mcp(mcp_client):
    """Resolved places travel as plain JSON arguments to every tool."""
    local = InProcessClient()
    og = local.call("resolve_place", query="Delhi")["geo"]
    dg = local.call("resolve_place", query="Rishikesh")["geo"]
    calls = {
        "search_flights": dict(origin=og["slug"], destination=dg["slug"], depart_date="2027-01-10",
                               return_date="2027-01-13", travelers=2, origin_geo=og, destination_geo=dg),
        "search_hotels": dict(destination=dg["slug"], checkin="2027-01-10", nights=3, travelers=2,
                              destination_geo=dg),
        "get_weather": dict(destination=dg["slug"], start_date="2027-01-10", days=4, today="2026-11-24",
                            destination_geo=dg),
        "search_places": dict(destination=dg["slug"], preferences=["nature"], destination_geo=dg),
    }
    for tool, args in calls.items():
        assert mcp_client.call(tool, **args) == local.call(tool, **args), tool


def test_unknown_place_error_is_not_retryable_over_mcp(mcp_client):
    with pytest.raises(ToolError) as e:
        mcp_client.call("resolve_place", query="Zzyzxville")
    assert e.value.retryable is False and "Zzyzxville" in str(e.value)


def test_errors_keep_message_and_retryable_flag(mcp_client):
    with pytest.raises(ToolError) as e:
        mcp_client.call("search_flights", origin="goa", destination="goa", depart_date="2026-12-10",
                        return_date="2026-12-14", travelers=1)
    assert "same" in str(e.value) and e.value.retryable is False


def test_full_plan_identical_through_mcp(mcp_client):
    def plan(tools):
        store = Store()
        deps = Deps(tools=tools, store=store, llm=LLMRouter(env={}, store=store), today=date(2026, 11, 24),
                    sleep=lambda s: None)
        return Planner(deps).start("Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2",
                                   thread_id="same")
    a, b = plan(InProcessClient()), plan(mcp_client)
    assert a["budget_report"] == b["budget_report"] and a["itinerary"] == b["itinerary"]
    assert a["strategy"] == b["strategy"] == "cheaper"
