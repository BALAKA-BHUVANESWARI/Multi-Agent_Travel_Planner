"""The AI judge (with pretend judges only: no test calls a real model) and the speed and cost figures."""
import json
import os
from decimal import Decimal

import pytest

from app.observability.store import RecordStore, now
from evaluation import judge, performance, report
from evaluation import run_evaluation as runner

KEY = "gsk-" + "k" * 30
ENV = {"GROQ_API_KEY": KEY}
BASIC = ["destination_relevance", "explanation_quality", "activity_relevance", "itinerary_coherence",
         "clarity_usefulness"]


def reply_for(dimensions, score=4, claims=(), reason="Day 2 shows it."):
    return {"scores": {d: {"score": score, "reason": reason} for d in dimensions}, "unsupported_claims": list(claims)}


class PretendJudge:
    """``answer(shown, dimensions)`` returns the reply (a dict, a text, or an HTTP status number)."""

    def __init__(self, answer=None):
        self.answer = answer or (lambda shown, dims: reply_for(dims))
        self.requests = []

    def __call__(self, url, headers, body, timeout):
        self.requests.append((url, headers, body))
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        shown = json.loads(user.removeprefix("<user_data>").removesuffix("</user_data>"))
        dims = [d for d in judge.RUBRIC if f"\n{d}: " in system]
        found = self.answer(shown, dims)
        if isinstance(found, int):
            return found, {}
        text = found if isinstance(found, str) else json.dumps(found)
        return 200, {"choices": [{"message": {"content": text}}],
                     "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}


def attentive(shown, dims):
    """A judge that really reads the plan, so that it notices the planted problems."""
    text = shown["plan"]["written_plan"]
    claims = ["Your hotel has a rooftop infinity pool."] if "rooftop infinity pool" in text else []
    found = reply_for(dims, 4, claims)
    if "tax office" in text:
        found["scores"]["activity_relevance"]["score"] = 1
    if not text.startswith("#") and "rooftop" not in text:
        found["scores"]["clarity_usefulness"]["score"] = 1
    return found


def run(pretend, tmp_path, env=ENV, **more):
    more.setdefault("pause", 0)
    more.setdefault("sleep", lambda s: None)
    return judge.run(env, transport=pretend, db=str(tmp_path / "judge.db"), **more)


def some(*ids):
    return [c for c in judge.load() if c["id"] in ids]


# ---------------------------------------------------------------- the rubric and what the judge is shown
def test_every_quality_describes_all_five_scores():
    assert len(judge.RUBRIC) == 6
    for question, levels in judge.RUBRIC.values():
        assert question and len(levels) == 5 and len(set(levels)) == 5


def test_group_balance_is_only_asked_about_groups():
    for case in judge.load():
        assert ("group_balance" in case["expected"]["dimensions"]) == bool(case["input"].get("group"))


def test_the_judge_gets_the_request_the_constraints_the_plan_and_the_sources():
    shown = judge.material(some("judge-goa-group")[0])
    assert set(shown) == {"request", "group", "expected_constraints", "plan", "source_records"}
    assert shown["plan"]["written_plan"].startswith("# ") and shown["plan"]["group_report"]
    records = shown["source_records"]
    assert records["places_in_plan"] and records["travel"]["chosen"] and records["hotel"]["source"]
    assert len(records["weather"]["days"]) == 5


def test_only_the_check_cases_get_a_planted_problem():
    texts = {c["id"]: judge.material(c)["plan"]["written_plan"] for c in judge.load()}
    assert "rooftop infinity pool" in texts["judge-check-invented"]
    assert "tax office" in texts["judge-check-activities"]
    assert not texts["judge-check-scrambled"].startswith("# ")
    normal = texts["judge-goa-beaches"]
    assert normal.startswith("# ") and "tax office" not in normal and "rooftop" not in normal
    assert sorted(texts["judge-check-scrambled"].split()) == sorted(normal.split())
    assert "MOCK-" not in normal and judge.material(some("judge-goa-beaches")[0])["plan"]["written_plan"] == normal


def test_a_check_case_that_plants_nothing_is_refused(tmp_path):
    data = json.loads((judge.datasets.DATASETS / judge.DATASET).read_text("utf-8"))
    del data["cases"][-1]["input"]["plant"]
    (tmp_path / judge.DATASET).write_text(json.dumps(data), "utf-8")
    with pytest.raises(judge.datasets.DatasetError, match="plants nothing"):
        judge.load(tmp_path)


# ---------------------------------------------------------------- scoring with a pretend judge
def test_an_attentive_judge_notices_every_planted_problem(tmp_path):
    record = run(PretendJudge(attentive), tmp_path)
    summary = record["summary"]
    assert summary["statuses"]["scored"] == 9 and record["calls_used"] == 9
    assert summary["planted_problems"] == {"total": 3, "noticed": 3, "missed": 0, "not_checked": 0}
    assert summary["averages"]["clarity_usefulness"] == {"mean": 4, "cases": 6}     # check cases are left out
    assert summary["averages"]["group_balance"]["cases"] == 1
    assert record["tokens"] == {"calls_with_counts": 9, "calls_without_counts": 0, "tokens_in": 9000,
                                "tokens_out": 1800}


def test_a_judge_that_likes_everything_is_shown_up(tmp_path):
    record = run(PretendJudge(lambda shown, dims: reply_for(dims, 5)), tmp_path)
    assert record["summary"]["planted_problems"] == {"total": 3, "noticed": 0, "missed": 3, "not_checked": 0}
    assert "MISSED" in "\n".join(report.judge_lines(record))


def test_a_claim_that_is_not_in_the_plan_is_marked(tmp_path):
    claims = ["The hotel offers free airport pickup", "Baga Beach"]
    record = run(PretendJudge(lambda s, d: reply_for(d, claims=claims)), tmp_path, cases=some("judge-goa-beaches"))
    assert [c["found_in_plan"] for c in record["cases"][0]["unsupported_claims"]] == [False, True]
    assert "these words are not in the plan" in "\n".join(report.judge_lines(record))


def _bad(kind):
    def answer(shown, dims):
        found = reply_for(dims)
        if kind == "missing quality":
            del found["scores"][dims[0]]
        elif kind == "score too high":
            found["scores"][dims[0]]["score"] = 7
        elif kind == "score as words":
            found["scores"][dims[0]]["score"] = "good"
        elif kind == "no reason":
            found["scores"][dims[0]]["reason"] = "  "
        elif kind == "no claims list":
            del found["unsupported_claims"]
        else:
            return "I think it is a lovely plan."
        return found
    return answer


@pytest.mark.parametrize("kind", ["missing quality", "score too high", "score as words", "no reason",
                                  "no claims list", "not JSON"])
def test_an_unusable_reply_is_never_scored(tmp_path, kind):
    record = run(PretendJudge(_bad(kind)), tmp_path, cases=some("judge-goa-beaches", "judge-check-invented"))
    first = record["cases"][0]
    assert first["status"] == "invalid" and first["reason"] and not first["scores"]
    assert record["summary"]["averages"] == {}
    assert record["summary"]["planted_problems"]["not_checked"] == 1


def test_a_failing_service_gives_no_answer_then_the_rest_is_not_run(tmp_path):
    record = run(PretendJudge(lambda s, d: 500), tmp_path)
    statuses = [r["status"] for r in record["cases"]]
    assert statuses[:3] == ["no_answer"] * 3 and set(statuses[3:]) == {"not_run"}
    assert record["summary"]["statuses"]["scored"] == 0


def test_the_call_limit_is_never_passed(tmp_path):
    pretend = PretendJudge()
    record = run(pretend, tmp_path, limit=2)
    assert len(pretend.requests) == 2 and record["calls_used"] == 2
    assert [r["status"] for r in record["cases"]].count("not_run") == 7
    assert run(PretendJudge(), tmp_path, limit=5000, cases=some("judge-goa-beaches"))["limit"] == 100


def test_after_too_many_requests_it_waits(tmp_path):
    answers, waits = [429], []
    pretend = PretendJudge(lambda s, d: answers.pop() if answers else reply_for(d))
    record = run(pretend, tmp_path, cases=some("judge-goa-beaches"), sleep=waits.append)
    assert record["cases"][0]["status"] == "scored" and 60.0 in waits and record["calls_used"] == 2


# ---------------------------------------------------------------- a separate judge model, and keys
def test_the_judge_can_have_its_own_model_and_key(tmp_path):
    env = {"GROQ_API_KEY": "app-key-" + "a" * 20, "GEMINI_API_KEY": "gem-" + "g" * 20,
           "JUDGE_PROVIDER": "gemini", "JUDGE_MODEL": "my-judge-model", "JUDGE_API_KEY": "judge-" + "j" * 30}
    pretend = PretendJudge()
    record = run(pretend, tmp_path, env=env, cases=some("judge-goa-beaches"))
    url, headers, body = pretend.requests[0]
    assert "googleapis" in url and body["model"] == "my-judge-model"
    assert headers["Authorization"] == f"Bearer {env['JUDGE_API_KEY']}"
    assert (record["provider"], record["model"]) == ("gemini", "my-judge-model")
    assert env["GEMINI_API_KEY"] == "gem-" + "g" * 20                     # the app's settings are not changed


def test_no_key_is_ever_saved_or_reported(tmp_path):
    def answer(url, headers, body, timeout):
        return 401, {"error": {"message": f"bad key {KEY}"}}
    record = run(answer, tmp_path, cases=some("judge-goa-beaches"))
    saved = judge.save(record, tmp_path).read_text("utf-8")
    assert record["cases"][0]["status"] == "no_answer"
    assert KEY not in saved and KEY not in "\n".join(report.judge_lines(record))


@pytest.mark.parametrize("env", [{}, {"JUDGE_PROVIDER": "unknown"}, {**ENV, "JUDGE_MODEL": "m"}])
def test_unusable_judge_settings_are_explained(env):
    with pytest.raises(ValueError, match="JUDGE_|key"):
        judge.settings(env)


# ---------------------------------------------------------------- the command
@pytest.fixture
def no_calls(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(judge, "default_transport", lambda *a: calls.append(a) or (500, {}))
    monkeypatch.setenv("TRIP_DB", str(tmp_path / "app.db"))
    for name in ("JUDGE_PROVIDER", "JUDGE_MODEL", "JUDGE_API_KEY", "EVAL_PRICES"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_without_judge_the_judge_is_not_run_and_not_counted(tmp_path, no_calls, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    assert runner.main(["--agent", "budget", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert data["judge"] == judge.not_run(judge.load()) and data["performance"] == {} and not no_calls
    assert "9 case(s) not run" in (tmp_path / "report.md").read_text("utf-8")


def test_listing_the_judge_calls_nothing(no_calls, monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    assert runner.main(["--judge-list"]) == 0
    assert "Nothing was called" in capsys.readouterr().out and not no_calls


@pytest.mark.parametrize("args", [["--deterministic-only", "--judge"], ["--agent", "llm_judge"]])
def test_the_judge_never_starts_by_accident(args, no_calls):
    with pytest.raises(SystemExit):
        runner.main(args)
    assert not no_calls


def test_without_a_key_it_stops_before_doing_anything(tmp_path, no_calls, capsys):
    assert runner.main(["--judge", "--out", str(tmp_path)]) == 2
    assert "no AI key" in capsys.readouterr().out and not (tmp_path / "report.json").exists()


def test_a_judge_run_is_reported_with_cost_from_your_prices(tmp_path, no_calls, monkeypatch):
    pretend = PretendJudge()
    monkeypatch.setattr(judge, "default_transport", pretend)
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"currency": "USD", "models": {"openai/gpt-oss-120b": {
        "input_per_million": "2", "output_per_million": "10"}}}), "utf-8")
    code = runner.main(["--agent", "llm_judge", "--judge", "--judge-limit", "1", "--prices", str(prices),
                        "--out", str(tmp_path)])
    data = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert code == 0 and len(pretend.requests) == 1 and data["cases"] == []
    assert data["summary"]["all"]["passed"] == 0 and data["summary"]["all"]["pass_rate"] is None
    # 1000 tokens in at 2 per million + 200 out at 10 per million
    assert data["estimated_cost"]["value"] == "0.004000" and data["tokens"]["llm_calls"] == 1
    assert list((tmp_path / "judge").glob("judge_*.json"))


def test_your_dotenv_settings_never_reach_the_fixed_checks(tmp_path, no_calls, monkeypatch):
    from app.core import config

    def dotenv(path=None):
        os.environ.setdefault("GROQ_API_KEY", KEY)
        os.environ.setdefault("TOOLS_MODE", "mcp")

    monkeypatch.setattr(config, "load_env", dotenv)
    monkeypatch.delenv("TOOLS_MODE", raising=False)
    seen = []
    original = runner.run
    monkeypatch.setattr(runner, "run", lambda agents: seen.append(
        (os.environ.get("TOOLS_MODE"), os.environ.get("GROQ_API_KEY"))) or original(agents))
    pretend = PretendJudge()
    monkeypatch.setattr(judge, "default_transport", pretend)
    runner.main(["--agent", "budget", "--judge", "--judge-limit", "1", "--out", str(tmp_path)])
    assert seen == [(None, None)] and len(pretend.requests) == 1
    assert "TOOLS_MODE" not in os.environ and "GROQ_API_KEY" not in os.environ


# ---------------------------------------------------------------- cost
USE = [{"model": "a", "tokens_in": 1_000_000, "tokens_out": 500_000}, {"model": "a", "tokens_in": 3, "tokens_out": 0},
       {"model": "b", "tokens_in": 10, "tokens_out": 10}]


def price(**models):
    return {"currency": "USD", "models": {k: (Decimal(i), Decimal(o)) for k, (i, o) in models.items()}}


def test_cost_is_exact():
    found = performance.cost(USE[:2], price(a=("0.10", "0.40")))
    assert found["value"] == "0.300000" and not found["partial"]      # 0.1000003 + 0.2, rounded to six places


def test_a_model_without_a_price_makes_the_cost_partial():
    found = performance.cost(USE, price(a=("1", "1")))
    assert found["partial"] and found["note"].startswith("PARTIAL: no price for b")


@pytest.mark.parametrize("usage,prices,words", [
    (USE, None, "no prices are configured"), ([], price(a=("1", "1")), "no AI tokens"),
    (USE, price(other=("1", "1")), "no price is given for a, b")])
def test_no_cost_is_made_up(usage, prices, words):
    found = performance.cost(usage, prices)
    assert found["value"] is None and words in found["note"]


@pytest.mark.parametrize("text", [
    "not json", "{}", '{"currency": "USD", "models": {}}', '{"currency": "", "models": {"a": {}}}',
    '{"currency": "USD", "models": {"a": {"input_per_million": -1, "output_per_million": 1}}}',
    '{"currency": "USD", "models": {"a": {"input_per_million": "NaN", "output_per_million": 1}}}',
    '{"currency": "USD", "models": {"a": {"input_per_million": "cheap", "output_per_million": 1}}}'])
def test_a_wrong_price_file_is_refused(tmp_path, text):
    (tmp_path / "p.json").write_text(text, "utf-8")
    with pytest.raises(ValueError):
        performance.load_prices(tmp_path / "p.json")


# ---------------------------------------------------------------- speed figures, against sums done by hand
def span(run_id, number, type_, name, ms, status="ok", parent=None, **attrs):
    return {"id": f"{run_id}-{number}", "run_id": run_id, "parent_id": parent, "type": type_, "name": name,
            "start_ms": number, "duration_ms": ms, "status": status, "attrs": attrs}


def make_records(path):
    store = RecordStore(str(path))
    for number, (status, ms) in enumerate([("ok", 100.0), ("ok", 300.0), ("failed", 900.0)]):
        run_id = f"{number}" * 32
        spans = [span(run_id, 1, "agent", "hotel", 10.0 * (number + 1), "ok" if number else "degraded"),
                 span(run_id, 2, "tool", "search_hotels", 5.0, "error", f"{run_id}-1", attempt=1),
                 span(run_id, 3, "tool", "search_hotels", 5.0, "ok", f"{run_id}-1", attempt=2),
                 span(run_id, 4, "retrieval", "overpass", 50.0, ["ok", "timeout", "skipped"][number]),
                 span(run_id, 5, "llm", "writer", 40.0, "ok", cache_hit=number == 2)]
        if number < 2:
            spans.append(span(run_id, 6, "llm_call", "groq", 200.0 * (number + 1), ["ok", "http_error"][number],
                              f"{run_id}-5", model="m1", attempt=number + 1, tokens_in=100, tokens_out=10))
        store.write({"id": run_id, "parent_id": None, "kind": "plan", "thread_id": None, "owner": None,
                     "status": status, "engine": "runner", "started": now().isoformat(), "duration_ms": ms,
                     "attrs": {}}, spans)
    return store


def test_the_figures_match_sums_done_by_hand(tmp_path):
    make_records(tmp_path / "r.db")
    out = performance.from_records(path=str(tmp_path / "r.db"))
    assert out["requests"] == 3 and out["workflow"]["failure_rate"] == 0.3333
    assert out["workflow"]["by_kind"][0]["median_ms"] == 300.0
    hotel = out["agents"][0]
    assert (hotel["runs"], hotel["median_ms"], hotel["success_rate"], hotel["tool_retries"]) == (3, 20.0, 0.6667, 3)
    assert out["tools"] == {"calls": 6, "failed": 3, "failure_rate": 0.5, "retries": 3}
    ai = out["ai"]
    assert (ai["model_calls"], ai["failed_calls"], ai["failure_rate"], ai["retries"]) == (2, 1, 0.5, 1)
    assert (ai["tokens_in"], ai["tokens_out"], ai["cache_hit_rate"]) == (200, 20, 0.3333)
    # three lookups: one skipped (never tried), one timed out
    assert (out["external"]["lookups"], out["external"]["failure_rate"]) == (3, 0.5)


def test_nothing_to_measure_is_not_zero(tmp_path):
    RecordStore(str(tmp_path / "empty.db"))
    out = performance.from_records(path=str(tmp_path / "empty.db"))
    assert out["requests"] == 0 and out["workflow"]["failure_rate"] is None
    assert out["ai"]["failure_rate"] is None and out["external"]["cache_hit_rate"] is None
    assert "failure rate not measured" in "\n".join(report.performance_lines(out))


def test_no_records_file_is_said_and_none_is_created(tmp_path):
    out = performance.from_records(path=str(tmp_path / "none.db"))
    assert "no records yet" in out["note"] and not (tmp_path / "none.db").exists()


def test_reading_the_records_changes_none_and_shows_no_text(tmp_path):
    store = make_records(tmp_path / "r.db")
    run_id = "0" * 32
    store.write(details=[{"run_id": run_id, "span_id": None, "name": "request", "content": "my private words"}])
    before = (store.runs(), store.spans(), store.details())
    out = performance.from_records(path=str(tmp_path / "r.db"))
    assert (store.runs(), store.spans(), store.details()) == before
    assert "private words" not in json.dumps(out)


def test_the_offline_speed_run_measures_the_real_agents(tmp_path):
    requests = performance.workload()
    assert requests and not any(r.get("failures") for r in requests)
    out = performance.offline(repeat=1, requests=requests[:3])
    names = {a["agent"] for a in out["agents"]}
    assert {"intake", "flight", "hotel", "weather", "activities", "budget", "critic"} <= names
    assert out["requests"] >= 3 and out["recording_errors"] == 0
    assert out["ai"]["model_calls"] == 0 and out["ai"]["failure_rate"] is None
    assert "not measured" in out["outside_services"] and "not live speed" in out["source"]
    assert not (tmp_path / "observability.db").exists()          # kept in memory only
