"""Offline test cases, saved results and hand checks."""
import json
from pathlib import Path

import pytest

from app.evaluation import offline, results, view, voice
from app.services import chat_service
from app.services.llm_service import LLMRouter
from app.tests.conftest import TODAY

EVALS = Path(__file__).resolve().parents[3] / "evals"


def reading_cases():
    return offline.load_cases(EVALS / "reading_cases.json")


def test_every_counted_reading_case_passes_and_every_known_gap_still_fails():
    for case in reading_cases():
        found = offline.reading_result(case, TODAY)
        # a known gap that starts passing should have its mark removed, so the report stays true
        assert found["passed"] == (not case.get("known_gap")), f"{case['id']}: {found['failed']}"


def test_the_exact_start_date_is_checked():
    wrong = offline.reading_result({"id": "x", "text": "3 days in Goa from Delhi starting 28 December, budget 60000",
                                    "expect": {"start_date": "2026-12-10"}}, TODAY)
    assert not wrong["passed"] and "2026-12-28" in wrong["failed"][0]


def test_known_gaps_are_not_counted():
    rows = [{"passed": True, "known_gap": ""}, {"passed": False, "known_gap": "why"}, {"passed": False, "known_gap": ""}]
    assert offline.counted(rows) == (1, 2)


def test_every_chat_case_passes(make):
    for case in offline.load_cases(EVALS / "chat_cases.json"):
        found = offline.chat_result(case, make)
        assert found["passed"], f"{case['id']}: {found['failed']}"


def test_a_chat_that_approved_would_be_caught(make, monkeypatch):
    real = chat_service.respond

    def books(message, state, **kwargs):
        if state and message == "book it":
            planner.resume(state["thread_id"], {"action": "approve"})
        return real(message, state, **kwargs)

    made = {}

    def one():
        made["planner"] = make()
        return made["planner"]

    class Proxy:
        def __getattr__(self, name):
            return getattr(made["planner"], name)

    planner = Proxy()
    monkeypatch.setattr(chat_service, "respond", books)
    case = {"id": "chat-book", "message": "book it", "expect": {"never_books": True}}
    found = offline.chat_result(case, one)
    assert not found["passed"] and "THE CHAT BOOKED OR APPROVED" in found["failed"]


# ------------------------------------------------------------------ saved results
def test_save_load_and_newest_first():
    results.save("offline", {"id": "20260101-100000-aaaa", "n": 1})
    results.save("offline", {"id": "20260102-100000-bbbb", "n": 2})
    assert [r["n"] for r in results.runs("offline")] == [2, 1]
    assert results.load("offline", "20260101-100000-aaaa")["n"] == 1
    assert results.load("offline", "../marks") is None and results.load("nope", "20260101-100000-aaaa") is None


def test_old_runs_are_deleted(monkeypatch):
    monkeypatch.setitem(results.KEEP, "live", 2)
    for day in (1, 2, 3):
        results.save("live", {"id": f"2026010{day}-100000-aaaa"})
    assert [r["id"][:8] for r in results.runs("live")] == ["20260103", "20260102"]


def test_a_damaged_file_is_skipped():
    results.save("voice", {"id": "20260101-100000-aaaa"})
    (results.folder() / "voice" / "20260102-100000-bbbb.json").write_text("{half", encoding="utf-8")
    assert [r["id"] for r in results.runs("voice")] == ["20260101-100000-aaaa"]


def test_hand_checks_are_only_for_saved_answers():
    run = results.save("live", {"items": [{"id": "groq.ask"}]})
    assert results.set_mark(run, "groq.ask", "good") and results.marks() == {f"{run}/groq.ask": "good"}
    assert not results.set_mark(run, "groq.other", "good")
    assert not results.set_mark("20260101-100000-ffff", "groq.ask", "good")
    assert results.set_mark(run, "groq.ask", "") and results.marks() == {}


def test_code_version_is_read_without_running_git(tmp_path):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    assert results.code_version(tmp_path) == "a" * 7
    (git / "refs" / "heads" / "main").unlink()
    (git / "packed-refs").write_text("# pack\n" + "b" * 40 + " refs/heads/main\n")
    assert results.code_version(tmp_path) == "b" * 7
    assert results.code_version(tmp_path / "nothing") == ""


def test_changes_since_the_run_before():
    def case(i, passed, gap=""):
        return {"group": "chat", "id": i, "passed": passed, "known_gap": gap}

    before = {"started": "x", "cases": [case("a", True), case("b", False), case("gone", True)]}
    now = {"cases": [case("a", False), case("b", True), case("new", True), case("gap", False, "why")]}
    found = view.changes(now, before)
    assert found["newly_failing"] == ["chat/a"] and found["newly_passing"] == ["chat/b"]
    assert (found["new_cases"], found["removed_cases"]) == (1, 1)
    assert view.changes(now, None) is None


# ------------------------------------------------------------------ the voice test
def test_the_rules_read_every_voice_sentence_as_typed():
    for s in voice.load_sentences():
        assert all(voice.check_words(s["say"], s["expect"]).values()), s["id"]


def recordings(tmp_path, *ids):
    folder = tmp_path / "voice"
    folder.mkdir()
    for i in ids:
        (folder / f"{i}.m4a").write_bytes(b"sound" * 400)
    return folder


def test_the_voice_test_saves_pass_or_fail_only(tmp_path):
    heard = "Plan a three day trip to Gokarna from Delhi with a budget of 30000 rupees zebra"
    shown = []
    record = voice.run(recordings(tmp_path, "01"), env={"GROQ_API_KEY": "gsk_secret_key_123"},
                       transport=lambda *a: (200, {"text": heard}), on_item=lambda i, words: shown.append(words))
    first = record["items"][0]
    assert first["status"] == "fail" and first["fields"] == {"origin": True, "destination": False, "days": True,
                                                            "budget": True}
    assert record["items"][1]["status"] == "not_recorded"
    assert record["summary"]["groups"]["places"] == {"right": 1, "checked": 2}
    assert shown[0] == heard                                        # on the screen
    saved = json.dumps(results.runs("voice"))
    assert "zebra" not in saved and "Gokarna" not in saved and "gsk_secret" not in saved


def test_the_voice_test_stops_when_the_key_is_refused(tmp_path):
    calls = []

    def refused(*args):
        calls.append(1)
        return 401, {"error": {"message": "bad key"}}

    record = voice.run(recordings(tmp_path, "01", "02", "03"), env={"GROQ_API_KEY": "k" * 20}, transport=refused)
    assert len(calls) == 1
    assert [i["status"] for i in record["items"][:3]] == ["no_answer", "not_run", "not_run"]
    assert results.runs("voice") == []                              # nothing was heard, so nothing to keep


def test_the_voice_test_keeps_to_the_daily_voice_limit(tmp_path, make):
    store = make().deps.store
    record = voice.run(recordings(tmp_path, "01", "02"), env={"GROQ_API_KEY": "k" * 20, "VOICE_DAILY_LIMIT": "1"},
                       store=store, transport=lambda *a: (200, {"text": "hello"}))
    assert [i["status"] for i in record["items"][:2]] == ["fail", "no_answer"]
    assert store.count("stt:groq") == 1


# ------------------------------------------------------------------ the record run_evals.py saves
def test_the_offline_script_saves_a_history_record_the_tab_can_read(monkeypatch, tmp_path):
    import importlib.util
    monkeypatch.setenv("REAL_DATA", "0")
    spec = importlib.util.spec_from_file_location("run_evals_for_test", EVALS / "run_evals.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr("sys.argv", ["run_evals.py", "--out", str(tmp_path / "report.md")])
    assert script.main() == 0
    record = results.runs("offline")[0]
    assert record["groups"]["planning"] == {"passed": 23, "total": 23}
    assert {c["group"] for c in record["cases"]} == {"planning", "reading", "chat"}
    assert record["metrics"]["baseline"]["budget"]["share"] < record["metrics"]["planner"]["budget"]["share"] == 1.0
    from app.observability import reports
    # the Overview tab's table is unchanged: the measures plus speed and tool calls, nothing from the new section
    assert [r["metric"] for r in reports.eval_scores(tmp_path / "report.md")["rows"]] == \
        script.METRICS + ["mean latency (ms)", "mean tool calls"]
    assert view.evaluations({})["offline"]["latest"]["id"] == record["id"]
