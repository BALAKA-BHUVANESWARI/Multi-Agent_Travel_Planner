"""The record store and the recorder: nesting, threads, safety, retention and deletion."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from app.observability import privacy, settings
from app.observability import recorder as observe
from app.observability.store import RecordStore, now


def make_recorder(details=False, **kwargs):
    return observe.Recorder(RecordStore(":memory:"), details, **kwargs)


def by_name(recorder):
    return {s["name"]: s for s in recorder.store.spans()}


def test_nothing_is_recorded_outside_a_request():
    recorder = make_recorder(details=True)
    with observe.span("agent", "intake") as step:
        step.set(x=1)
        step.detail("text", "hello")
    observe.event("guardrail", "input_check")
    observe.run_detail("request", "hello")
    observe.set_run(status="ok")
    assert recorder.store.runs() == [] and recorder.store.spans() == []


def test_steps_nest_and_work_handed_to_threads_stays_in_the_request():
    recorder = make_recorder()

    def lookup(name):
        with observe.span("retrieval", name):
            pass

    with recorder.run("plan"):
        with observe.span("agent", "activities"):
            with ThreadPoolExecutor(2) as pool:
                list(pool.map(observe.carry(lookup), ["one", "two"]))
        observe.event("guardrail", "critic_checks", "ok", blocking=0)
    spans = by_name(recorder)
    assert spans["one"]["parent_id"] == spans["two"]["parent_id"] == spans["activities"]["id"]
    assert spans["critic_checks"]["parent_id"] is None
    run, = recorder.store.runs()
    assert run["kind"] == "plan" and run["status"] == "ok" and run["duration_ms"] >= 0


def test_an_agent_on_a_thread_that_lost_the_request_finds_it_by_the_trip_id():
    recorder = make_recorder()

    def agent():
        with observe.adopt("abc123"), observe.span("agent", "weather"):
            pass

    with recorder.run("plan"):
        observe.set_run(thread_id="abc123")
        thread = threading.Thread(target=agent)             # a new thread starts without the request
        thread.start()
        thread.join()
    assert "weather" in by_name(recorder)
    with observe.adopt("abc123"):                            # the request has ended
        assert not observe.active()


def test_errors_pass_through_and_are_noted():
    recorder = make_recorder()
    with pytest.raises(ZeroDivisionError):
        with recorder.run("plan"):
            with observe.span("agent", "budget"):
                1 / 0
    run, = recorder.store.runs()
    assert run["status"] == "failed" and run["attrs"]["error"] == "ZeroDivisionError"
    assert by_name(recorder)["budget"]["status"] == "error"
    assert not observe.active()


def test_a_broken_store_changes_nothing(monkeypatch):
    recorder = make_recorder()

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(recorder.store, "write", broken)
    with recorder.run("plan"):
        with observe.span("agent", "intake"):
            answer = 42
    assert answer == 42 and recorder.errors == 1 and not observe.active()


def test_a_step_that_finishes_after_the_request_is_still_kept():
    recorder = make_recorder()
    release, done = threading.Event(), threading.Event()

    def slow():
        with observe.span("retrieval", "slow_lookup"):
            release.wait(5)
        done.set()

    with recorder.run("plan"):
        threading.Thread(target=observe.carry(slow)).start()
    release.set()
    assert done.wait(5)
    assert by_name(recorder)["slow_lookup"]["attrs"]["finished_after_request"] is True


def test_a_lookup_says_whether_it_failed_or_found_nothing():
    recorder = make_recorder()

    @observe.retrieval("source")
    def lookup(mode):
        if mode == "swallowed":
            try:
                raise TimeoutError("too slow")
            except TimeoutError as e:
                observe.problem(e)
                return []
        return [] if mode == "nothing" else ["a", "b"]

    with recorder.run("plan"):
        for mode in ("nothing", "swallowed", "found"):
            lookup(mode)
    nothing, swallowed, found = recorder.store.spans()
    assert (nothing["status"], nothing["attrs"]["results"]) == ("empty", 0)
    assert (swallowed["status"], swallowed["attrs"]["error"]) == ("timeout", "TimeoutError")
    assert (found["status"], found["attrs"]["results"]) == ("ok", 2)


def test_basic_records_cannot_hold_sentences():
    attrs = privacy.safe_attrs({"n": 3, "ok": True, "code": "off_topic", "model": "openai/gpt-oss-120b",
                                "text": "plan a trip for Asha", "list": ["a", "two words"],
                                "table": {"wikipedia": 2, "bad key!": 1}, "none": None, "nested": [{"x": 1}]})
    assert attrs == {"n": 3, "ok": True, "code": "off_topic", "model": "openai/gpt-oss-120b", "list": ["a"],
                     "table": {"wikipedia": 2}, "nested": []}


def test_detailed_text_is_cleaned(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_abcdefghijklmnop123456")
    text = privacy.clean_detail("key gsk_abcdefghijklmnop123456 other AIzaSyA1234567890abcdefghij_KLM "
                                "mail asha@example.com Asha and ASHA in org_01abcdefghij", hide=["Asha"])
    assert text == "key [key] other [key] mail [email] [hidden] and [hidden] in [account]"
    assert privacy.clean_detail("my card is 4111 1111 1111 1111") == "[withheld: contains a card number]"
    assert len(privacy.clean_detail("x" * 20000)) == privacy.MAX_DETAIL_CHARS


def test_details_are_kept_only_when_switched_on():
    for details in (False, True):
        recorder = make_recorder(details)
        with recorder.run("plan"):
            observe.run_detail("request", "a trip to somewhere")
            with observe.span("llm", "intake") as step:
                step.detail("prompt", "words")
        assert sorted(d["name"] for d in recorder.store.details()) == (["prompt", "request"] if details else [])


def test_a_private_request_keeps_no_text():
    recorder = make_recorder(details=True)
    with recorder.run("chat"):
        observe.run_detail("message", "I need help near the old bridge")
        observe.private_request()
        observe.event("guardrail", "chat_fixed_reply", "blocked", detail="more words", topic="emergency")
    assert recorder.store.details() == []
    assert recorder.store.spans()[0]["attrs"] == {"topic": "emergency"}


def test_old_records_are_deleted_and_details_sooner():
    store = RecordStore(":memory:")
    recorder = observe.Recorder(store, details=True)
    with recorder.run("plan"):
        observe.run_detail("request", "old text")
    store._conn.execute("UPDATE details SET created=?", ((now() - timedelta(days=8)).isoformat(),))
    store.prune(keep_days=30, detail_keep_days=7)
    assert store.details() == [] and len(store.runs()) == 1
    store._conn.execute("UPDATE runs SET started=?", ((now() - timedelta(days=31)).isoformat(),))
    store.prune(keep_days=30, detail_keep_days=7)
    assert store.runs() == [] and store.spans() == []


def test_the_number_of_requests_is_limited():
    recorder = make_recorder()
    for _ in range(5):
        with recorder.run("plan"):
            observe.event("log", "intake")
    recorder.store.prune(30, 7, max_runs=2)
    assert len(recorder.store.runs()) == 2 and len(recorder.store.spans()) == 2


def test_records_of_a_trip_or_an_account_can_be_removed():
    recorder = make_recorder()
    for thread_id, owner in (("t1", "u1"), ("t2", "u1"), ("t3", None), ("t4", "u2")):
        with recorder.run("plan"):
            observe.set_run(thread_id=thread_id, owner=owner)
            observe.event("log", "intake")
    recorder.forget(thread_id="t3")
    recorder.forget(owner="u1")
    assert [r["thread_id"] for r in recorder.store.runs()] == ["t4"]
    assert len(recorder.store.spans()) == 1


def test_recording_can_be_switched_off(monkeypatch):
    assert observe.Recorder.from_env() is not None
    monkeypatch.setenv("OBSERVABILITY", "0")
    assert observe.Recorder.from_env() is None


def test_off_by_default_for_details_and_sensible_limits(monkeypatch):
    assert settings.enabled() and not settings.details_enabled()
    assert (settings.keep_days(), settings.detail_keep_days()) == (30, 7)
    monkeypatch.setenv("RECORD_KEEP_DAYS", "nonsense")
    monkeypatch.setenv("RECORD_DETAIL_KEEP_DAYS", "0")
    assert (settings.keep_days(), settings.detail_keep_days()) == (30, 1)
