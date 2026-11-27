"""A live fare that was never asked for (the daily limit) must not be recorded as a failed lookup."""
import pytest

from app.integrations import live_prices as live
from app.observability import analytics
from app.observability import recorder as observe
from app.observability.store import RecordStore

SHELL = "an empty page"


def recorded(call, times=1):
    recorder = observe.Recorder(RecordStore(":memory:"), False)
    with recorder.run("plan"):
        for n in range(times):
            try:
                call(n)
            except live.LiveUnavailable:
                pass
    steps = sorted((s for s in recorder.store.spans() if s["name"] == "live_prices.page"), key=lambda s: s["start_ms"])
    return recorder, steps


@pytest.fixture(autouse=True)
def pages(monkeypatch):
    monkeypatch.setattr(live, "_read_page", lambda url: "fares" if "good" in url else SHELL)


def test_a_lookup_stopped_by_the_daily_limit_is_skipped_with_the_reason(monkeypatch):
    monkeypatch.setenv("LIVE_DAILY_CREDITS", "2")
    recorder, steps = recorded(lambda n: live.get_page(f"https://x/good{n}", lambda t: t == "fares"), times=3)
    assert [s["status"] for s in steps] == ["ok", "skipped", "skipped"]
    assert [s["attrs"].get("reason") for s in steps] == [None, "daily_limit", "daily_limit"]
    assert not any(s["attrs"].get("page_reads") for s in steps[1:])
    out = analytics.retrieval(analytics.Data.load(recorder.store, analytics.parse_filters({})))
    row, = out["sources"]
    assert (row["ok"], row["skipped"], row["error"], row["from_cache"]) == (1, 2, 0, 0) and not out["problems"]


@pytest.mark.parametrize("limit,reason", [("30", "no_results_on_page"), ("2", "daily_limit")])
def test_a_page_that_was_read_and_gave_nothing_is_still_a_failure(monkeypatch, limit, reason):
    monkeypatch.setenv("LIVE_DAILY_CREDITS", limit)               # 2: the limit stops the second try
    _, steps = recorded(lambda n: live.get_page("https://x/empty", lambda t: False))
    step, = steps
    assert step["status"] == "error" and step["attrs"]["reason"] == reason and step["attrs"]["page_reads"] >= 1


def test_a_tavily_problem_is_recorded_as_a_fixed_word(monkeypatch):
    def refused(url):
        raise live.LiveUnavailable("Tavily rejected the key (check TAVILY_API_KEY)", "tavily_rejected_key")
    monkeypatch.setattr(live, "_read_page", refused)
    _, steps = recorded(lambda n: live.get_page("https://x/y", lambda t: True))
    assert (steps[0]["status"], steps[0]["attrs"]["reason"]) == ("error", "tavily_rejected_key")
    assert "check TAVILY_API_KEY" not in str(steps[0]["attrs"])          # no message text in basic records


@pytest.mark.parametrize("unreachable,status", [(False, "not_possible"), (True, "error")])
def test_a_place_that_does_not_exist_is_an_answer_not_a_broken_tool(monkeypatch, unreachable, status):
    from app.integrations import openmeteo
    from app.services import geo_service
    from app.tools.client import InProcessClient, call_with_retry
    from app.tools.errors import ToolError

    def geocoder(url, params, timeout=6.0):
        if unreachable:
            raise OSError("down")
        return {"results": []}
    monkeypatch.setenv("REAL_DATA", "1")
    monkeypatch.setattr(openmeteo, "fetch_json", geocoder)
    geo_service._CACHE.clear()
    recorder = observe.Recorder(RecordStore(":memory:"), False)
    with recorder.run("plan"):
        with pytest.raises(ToolError):
            call_with_retry(InProcessClient(), "resolve_place", retries=1, query="Zzzqx")
    step, = [s for s in recorder.store.spans() if s["type"] == "tool"]
    assert step["status"] == status
