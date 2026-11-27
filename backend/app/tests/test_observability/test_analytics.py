"""The dashboard's numbers, checked against hand-made records whose answers are easy to work out by hand."""
import csv
import io
import json
from datetime import date, datetime, timezone

import pytest

from app.observability import analytics, reports
from app.observability.store import RecordStore


def iso(day, hour=12, minute=0):
    return datetime(2026, 11, day, hour, minute).astimezone().astimezone(timezone.utc).isoformat(
        timespec="milliseconds")


class Book:
    """Builds records by hand."""

    def __init__(self):
        self.store, self.n = RecordStore(":memory:"), 0

    def run(self, kind="plan", status="ok", ms=1000.0, day=27, trip=None, parent=None, owner=None, **attrs):
        self.n += 1
        run_id = f"{self.n:032x}"
        self.store.write({"id": run_id, "parent_id": parent, "kind": kind, "thread_id": trip, "owner": owner,
                          "status": status, "engine": "runner", "started": iso(day, 12, self.n), "duration_ms": ms,
                          "attrs": attrs})
        return run_id

    def span(self, run, type_, name, status="ok", ms=10.0, parent=None, start=0.0, **attrs):
        self.n += 1
        span_id = f"s{self.n}"
        self.store.write(spans=[{"id": span_id, "run_id": run, "parent_id": parent, "type": type_, "name": name,
                                 "start_ms": start, "duration_ms": ms, "status": status, "attrs": attrs}])
        return span_id

    def data(self, **filters):
        return analytics.Data.load(self.store, analytics.parse_filters(filters), today=date(2026, 11, 27))


def test_percentiles():
    assert analytics.percentile([], 0.5) is None
    assert analytics.percentile([7], 0.9) == 7
    assert analytics.percentile([4, 1, 3, 2], 0.5) == 2.5
    assert analytics.percentile(list(range(1, 11)), 0.9) == pytest.approx(9.1)


def test_overview_times_only_full_plans_and_counts_bookings_replans_and_failures():
    book = Book()
    first = book.run(ms=10_000, outcome="awaiting_approval")
    second = book.run(ms=30_000, outcome="awaiting_approval")
    book.run(ms=200, status="needs_info", outcome="needs_info")           # not a full plan: not timed
    book.run(ms=50, status="blocked", outcome="blocked")
    crashed = book.run(ms=900, status="failed")
    revise = book.run("approve", action="revise", outcome="awaiting_approval")
    refused_change = book.run("approve", action="revise", outcome="awaiting_approval")  # nothing replanned
    book.run("approve", action="approve", outcome="booked")
    for name in ("supervisor", "supervisor", "supervisor"):                # two automatic replans
        book.span(first, "agent", name)
    book.span(second, "agent", "supervisor")
    book.span(revise, "agent", "supervisor")
    book.span(crashed, "agent", "budget", "error")
    book.span(first, "tool", "search_flights", "not_possible")             # an answer, not a failure
    book.span(first, "retrieval", "openstreetmap.places", "empty")         # found nothing, not a failure
    book.span(first, "retrieval", "wikipedia.nearby_sights", "timeout")
    assert refused_change
    out = analytics.overview(book.data())
    assert out["requests"] == 8
    assert out["plans"]["count"] == 5
    assert out["plans"]["outcomes"] == {"awaiting_approval": 2, "needs_info": 1, "blocked": 1, "failed": 1}
    assert out["plans"]["full"] == {"count": 2, "median_ms": 20_000, "p90_ms": 28_000, "max_ms": 30_000}
    assert (out["replans"], out["revisions"], out["bookings"], out["failed_requests"]) == (2, 1, 1, 1)
    assert out["failed_steps"] == {"agent": 1, "retrieval": 1}
    assert out["per_day"] == [{"day": "2026-11-27", "ok": 5, "needs_info": 1, "blocked": 1, "refused": 0,
                               "rate_limited": 0, "failed": 1}]
    assert [p["id"] for p in out["recent_plans"]] == [first, second]


def test_agent_figures_include_retries_under_the_agent():
    book = Book()
    run = book.run()
    flight = book.span(run, "agent", "flight", ms=100)
    tool = book.span(run, "tool", "search_flights", "error", parent=flight, attempt=1)
    book.span(run, "tool", "search_flights", parent=flight, attempt=2)
    book.span(run, "retrieval", "live_prices.page", "error", parent=tool)
    book.span(run, "agent", "flight", "degraded", ms=300)
    book.span(run, "agent", "flight", "not_needed", ms=0)                  # a replan that skipped it
    writer = book.span(run, "agent", "writer", ms=50)
    llm = book.span(run, "llm", "writer", parent=writer)
    book.span(run, "llm_call", "gemini", "http_error", parent=llm, attempt=1)
    book.span(run, "llm_call", "gemini", "http_error", parent=llm, attempt=2)
    book.span(run, "retrieval", "weather.offline_estimate", "fallback", parent=flight)       # not a lookup
    rows = {r["agent"]: r for r in analytics.agents(book.data())["agents"]}
    f = rows["flight"]
    assert (f["runs"], f["ok"], f["degraded"], f["errors"], f["success_rate"]) == (2, 1, 1, 0, 0.5)
    assert (f["median_ms"], f["max_ms"]) == (200, 300)
    assert (f["tool_calls"], f["tool_retries"], f["tool_errors"], f["lookups"], f["failed_lookups"]) == (2, 1, 1, 1, 1)
    assert (rows["writer"]["ai_calls"], rows["writer"]["ai_retries"]) == (2, 1)
    assert list(rows) == ["flight", "writer"]                              # in the order the planner runs them


def test_ai_figures_cover_fallback_cache_tokens_and_requests_without_a_call():
    book = Book()
    run = book.run()
    first = book.span(run, "llm", "intake", answered_by="gemini", fallback=True)
    book.span(run, "llm_call", "groq", "http_error", ms=100, parent=first, model="a", attempt=1, http_status=500)
    book.span(run, "llm_call", "gemini", ms=300, parent=first, model="b", attempt=1, tokens_in=100, tokens_out=20,
              tokens_estimated=False)
    book.span(run, "llm", "intake", cache_hit=True)
    book.span(run, "llm", "writer", "failed", reason="no_provider_answered")
    book.span(run, "llm", "chat", "not_configured")
    book.span(run, "voice", "groq.transcribe", ms=900, model="whisper", audio_bytes=5000)
    out = analytics.ai(book.data())
    models = {(m["job"], m["provider"]): m for m in out["models"]}
    assert models[("intake", "groq")]["failed"] == 1 and models[("intake", "groq")]["failures"] == {"http_error": 1}
    gemini = models[("intake", "gemini")]
    assert (gemini["ok"], gemini["fallback_answers"], gemini["tokens_in"], gemini["tokens_out"],
            gemini["estimated_token_calls"], gemini["median_ms"]) == (1, 1, 100, 20, 0, 300)
    assert models[("voice", "groq")]["calls"] == 1
    jobs = {j["job"]: j for j in out["jobs"]}
    assert (jobs["intake"]["asked"], jobs["intake"]["answered"], jobs["intake"]["from_cache"],
            jobs["intake"]["by_fallback"]) == (2, 1, 1, 1)
    assert jobs["writer"]["unanswered"] == 1 and jobs["chat"] == {
        "job": "chat", "asked": 0, "answered": 0, "from_cache": 0, "by_fallback": 0, "unanswered": 0, "no_key": 1}
    assert out["total_calls"] == 6                    # 3 calls, 1 cached, 1 never reached a model, 1 without a key
    assert {c["provider"] for c in out["calls"]} == {"groq", "gemini", "cache", "none"}
    only_b = analytics.ai(book.data(model="b"))
    assert [c["model"] for c in only_b["calls"]] == ["b"]


def test_retrieval_figures_keep_empty_apart_from_failed_and_show_what_reached_plans():
    book = Book()
    run = book.run(outcome="awaiting_approval", activity_sources={"wikipedia": 3, "generic": 1},
                   transport_price="estimated", hotel_price="live")
    book.span(run, "retrieval", "openstreetmap.places", "empty", ms=100, results=0)
    book.span(run, "retrieval", "openstreetmap.places", "error", ms=200, error="URLError", results=0)
    book.span(run, "retrieval", "openstreetmap.places", "ok", ms=1, results=10, memory_cache_hits=1)
    book.span(run, "retrieval", "openstreetmap.places", "skipped", ms=0, reason="failed_recently")
    book.span(run, "retrieval", "live_prices.flights", "fallback", ms=0)
    book.span(run, "retrieval_wait", "openstreetmap.places", "gave_up", ms=0, error="TimeoutError")
    book.run("approve", action="approve", outcome="booked", activity_sources={"wikipedia": 3})   # same plan: once
    out = analytics.retrieval(book.data())
    row, = out["sources"]
    assert (row["lookups"], row["ok"], row["empty"], row["error"], row["timeout"], row["skipped"]) == (4, 1, 1, 1, 0, 1)
    assert row["from_cache"] == 1 and row["results_per_lookup"] == 3.3
    assert out["fallbacks"] == [{"what": "live_prices.flights", "times": 1}]
    assert out["gave_up"] == [{"what": "openstreetmap.places", "times": 1}]
    assert out["in_plans"] == {"plans": 1, "activities": 4, "by_source": {"wikipedia": 3, "generic": 1},
                               "real_share": 0.75}
    assert out["prices"] == {"transport_price": {"estimated": 1}, "hotel_price": {"live": 1}}
    assert sorted(p["status"] for p in out["problems"]) == ["error", "gave_up"]


def test_logs_can_be_searched_and_filtered_by_level_and_type():
    book = Book()
    run = book.run(status="failed", error="RuntimeError")
    agent = book.span(run, "agent", "flight", warnings=1, start=5)
    book.span(run, "retrieval", "wikivoyage.sights", "error", error="URLError", start=7)
    book.span(run, "guardrail", "input_check", "blocked", code="off_topic", start=1)
    book.store.write(details=[{"run_id": run, "span_id": agent, "name": "text", "content": "picked the marigold one"}])
    everything = analytics.logs(book.store, book.data())
    assert everything["total"] == 4 and everything["types"] == ["agent", "guardrail", "request", "retrieval"]
    assert [e["name"] for e in everything["entries"]][1:] == ["wikivoyage.sights", "flight", "input_check"]
    assert [e["name"] for e in analytics.logs(book.store, book.data(), level="error")["entries"]] == [
        "plan", "wikivoyage.sights"]
    assert analytics.logs(book.store, book.data(), type_="guardrail")["total"] == 1
    assert analytics.logs(book.store, book.data(), search="MARIGOLD")["entries"][0]["name"] == "flight"
    assert analytics.logs(book.store, book.data(), search="off_topic")["total"] == 1
    assert analytics.logs(book.store, book.data(), search="marigold", clip=6)["entries"][0]["text"] == "text: "


def test_filters_choose_requests_and_steps():
    book = Book()
    old = book.run(day=1, trip="trip1")
    recent = book.run(day=22, trip="trip2")
    today = book.run("chat", status="blocked", day=27)
    flight = book.span(old, "agent", "flight")
    tool = book.span(old, "tool", "search_flights", parent=flight)
    book.span(old, "retrieval", "live_prices.page", parent=tool)
    book.span(old, "agent", "hotel")
    book.span(recent, "llm_call", "groq", model="m1")

    def ids(**filters):
        return [r["id"] for r in book.data(**filters).runs]

    assert ids() == [today, recent, old]
    assert ids(period="today") == [today] and ids(period="7d") == [today, recent] and ids(period="30d") == ids()
    assert ids(date_from="2026-11-01", date_to="2026-11-22") == [recent, old]
    assert ids(period="today", date_to="2026-11-01") == [old]               # chosen dates win
    assert ids(kind="chat") == [today] and ids(status="blocked") == [today]
    assert ids(agent="flight") == [old] and ids(model="m1") == [recent]
    assert ids(run="trip2") == [recent] and ids(run=today) == [today]
    scoped = book.data(agent="flight")
    assert sorted(s["name"] for s in scoped.spans(old)) == ["flight", "live_prices.page", "search_flights"]


@pytest.mark.parametrize("bad", [{"period": "year"}, {"date_from": "27/11/2026"}, {"kind": "emergency"},
                                 {"status": "x"}, {"agent": "a b"}, {"model": "'; drop"}, {"run": "x" * 90}])
def test_bad_filters_are_refused(bad):
    with pytest.raises(ValueError):
        analytics.parse_filters(bad)


def test_a_trace_is_a_tree_with_linked_requests_and_no_user_id():
    book = Book()
    chat = book.run("chat", ms=100, owner="user-secret")
    plan = book.run(ms=90, parent=chat, trip="t1", owner="user-secret")
    later = book.run("approve", trip="t1")
    agent = book.span(plan, "agent", "activities", start=10, ms=50)
    book.span(plan, "tool", "search_places", parent=agent, start=12, ms=200)      # finished late
    note = book.span(plan, "log", "activities", parent=agent, start=60, ms=0)
    book.store.write(details=[{"run_id": plan, "span_id": note, "name": "text", "content": "6 candidates"},
                              {"run_id": plan, "span_id": None, "name": "request", "content": "typed words"}])
    out = analytics.trace(book.store, plan)
    assert [(s["name"], s["depth"]) for s in out["steps"]] == [("activities", 0), ("search_places", 1)]
    assert out["steps"][0]["texts"] == [{"name": "agent note", "text": "6 candidates"}]
    assert out["texts"] == [{"name": "request", "text": "typed words"}] and out["has_texts"]
    assert out["timeline_ms"] == 212
    assert [r["id"] for r in out["linked"]] == [chat, later]
    assert "user-secret" not in json.dumps(out) and "user-secret" not in json.dumps(analytics.run_list(book.data()))
    assert analytics.trace(book.store, "nope") is None and analytics.trace(book.store, "f" * 32) is None


def test_filter_choices_come_from_what_was_recorded():
    book = Book()
    first, last = book.run(day=2), book.run(day=20)
    for name in ("writer", "flight", "flight"):
        book.span(first, "agent", name)
    book.span(last, "llm_call", "groq", model="b")
    book.span(last, "voice", "groq.transcribe", model="a")
    book.span(last, "llm_call", "ollama")                                  # no model name
    out = analytics.options(book.store)
    assert (out["agents"], out["models"], out["recorded"]) == (["flight", "writer"], ["a", "b"], 2)
    assert (out["oldest"], out["newest"]) == (iso(2, 12, 1), iso(20, 12, 2))


def test_no_records_is_not_an_error():
    data = analytics.Data.load(None, analytics.Filters())
    assert analytics.overview(data)["requests"] == 0 and analytics.overview(data)["plans"]["full"]["median_ms"] is None
    assert analytics.agents(data) == {"agents": []} and analytics.ai(data)["calls"] == []
    assert analytics.retrieval(data)["in_plans"]["real_share"] is None
    assert analytics.logs(None, data)["total"] == 0 and analytics.options(None)["recorded"] == 0


def test_downloads_are_safe_to_open_in_a_spreadsheet():
    rows = [{"name": "=cmd|'/c calc'!A1", "n": -5, "attrs": {"a": 1}, "list": ["x", "y"], "none": None},
            {"name": "  +SUM(A1)", "extra": "@x"}]
    text = reports.as_csv(rows).decode("utf-8-sig")
    first, second = csv.DictReader(io.StringIO(text))
    assert first["name"].startswith("'=") and second["name"].startswith("'  +") and second["extra"] == "'@x"
    assert (first["n"], first["attrs"], first["list"], first["none"]) == ("-5", "a=1", "x; y", "")
    assert json.loads(reports.as_json(rows))[0]["n"] == -5


def test_the_latest_eval_scores_are_read_from_the_report(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# Evaluation report\n\n23 prompts, offline deterministic tools, fixed date 2026-11-24.\n\n"
                      "| Metric | Multi-agent | Baseline (single agent) | Applies to |\n|---|---|---|---|\n"
                      "| outcome | **100%** | 61% | 23 / 23 prompts |\n| mean tool calls | 5.9 | 4.4 | all |\n\n"
                      "## Per prompt\n| a | 1 | 2 | x |\n\n## LLM-as-judge\n\nMean: 3.50. LLM judges are noisy.\n",
                      encoding="utf-8")
    out = reports.eval_scores(report)
    assert out["rows"] == [{"metric": "outcome", "planner": "100%", "baseline": "61%", "applies": "23 / 23 prompts"},
                           {"metric": "mean tool calls", "planner": "5.9", "baseline": "4.4", "applies": "all"}]
    assert (out["prompts"], out["fixed_date"], out["judge_mean"]) == (23, "2026-11-24", 3.5)
    assert reports.eval_scores(tmp_path / "missing.md") is None
    assert len(reports.eval_scores()["rows"]) >= 8                       # the project's own report still parses


def test_only_an_answered_lookup_counts_as_from_cache():
    book = Book()
    run = book.run()
    # older records: a glance at the live-price usage counter was counted as a cache hit on lookups that failed
    for status in ("error", "skipped", "timeout"):
        book.span(run, "retrieval", "live_prices.page", status, error="LiveUnavailable", disk_cache_hits=1)
    book.span(run, "retrieval", "live_prices.page", "ok", disk_cache_hits=1)
    book.span(run, "retrieval", "live_prices.page", "ok", disk_cache_hits=1, page_reads=1)       # read the page
    row, = analytics.retrieval(book.data())["sources"]
    assert (row["lookups"], row["from_cache"]) == (5, 1)


def test_a_known_reason_is_shown_instead_of_the_error_class():
    book = Book()
    run = book.run()
    book.span(run, "retrieval", "live_prices.page", "error", error="LiveUnavailable", reason="tavily_limit")
    book.span(run, "retrieval", "openstreetmap.places", "error", error="URLError")
    why = {p["source"]: p["error"] for p in analytics.retrieval(book.data())["problems"]}
    assert why == {"live_prices.page": "tavily_limit", "openstreetmap.places": "URLError"}
