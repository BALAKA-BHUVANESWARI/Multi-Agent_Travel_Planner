"""The live AI tests, run here with a pretend provider (no internet, no keys)."""
import json
import sqlite3

import pytest

from app.evaluation import live, results
from app.observability import recorder as observe
from app.services.llm_service import LLMRouter
from app.services.request_parser import parse_request

KEYS = {"GROQ_API_KEY": "gsk_pretend_secret_000111", "GEMINI_API_KEY": "AIzaPretendSecret222333"}
CASES = live.load_cases()


def small(**counts):
    """The first few cases of each group."""
    return {g: CASES[g][:counts.get(g, 0)] for g in live.GROUPS}


def reply(content):
    return 200, {"choices": [{"message": {"content": json.dumps(content)}}]}


class Pretend:
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, url, headers, body, timeout):
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"][len("<user_data>"):-len("</user_data>")]
        job = ("reading" if system.startswith("Extract trip") else "ranking" if system.startswith("You re-rank")
               else "summary" if system.startswith("Write a friendly") else "judge_lists"
               if system.startswith("Two lists") else "judge_text" if system.startswith("You check") else "chat")
        self.calls.append((url, job, user))
        if job in self.answers:
            return self.answers[job](url, user)
        if job == "reading":
            return reply({"days": 14, "budget_inr": 200000})
        if job == "ranking":
            return reply({"order": [c["id"] for c in reversed(json.loads(user)["candidates"])]})
        if job == "summary":
            return reply({"overview": "A relaxed trip with time to explore."})
        if job == "judge_lists":
            return reply({"a": 5, "b": 1})
        if job == "judge_text":
            return reply({"unsupported": []})
        return reply({"answer": "The plan does not say."})


def run(tmp_path, transport, providers=("groq",), cases=None, **kwargs):
    kwargs.setdefault("pause", 0)
    return live.run(dict(KEYS), providers=list(providers), cases=cases or small(reading=2), db=str(tmp_path / "t.db"),
                    transport=transport, sleep=lambda s: None, **kwargs)


def counters(tmp_path) -> int:
    with sqlite3.connect(tmp_path / "t.db") as db:
        return db.execute("SELECT COALESCE(SUM(n), 0) FROM counters WHERE name LIKE 'llm:%'").fetchone()[0]


def test_there_are_enough_cases_and_a_full_run_fits_the_limit():
    needed = live.planned_calls(CASES, ["groq", "gemini"])
    assert needed["tests"] + needed["judge"] <= live.MAX_CALLS


def test_the_limit_counts_retries_and_is_never_passed(tmp_path):
    sent = []

    def busy(*args):
        sent.append(1)
        return 503, {}

    record = run(tmp_path, busy, providers=("groq", "gemini"), cases=small(reading=10, chat=8), limit=7)
    assert len(sent) == record["calls_used"] == 7
    assert counters(tmp_path) == 7                       # only calls that were made count toward today
    assert any(i["status"] == "not_run" for i in record["items"])


def test_the_limit_cannot_be_raised_above_100(tmp_path):
    assert live.Budget(5000).limit == 100


def test_the_saved_answer_cache_is_off(tmp_path):
    transport = Pretend()
    run(tmp_path, transport)
    run(tmp_path, transport)
    assert len(transport.calls) == 4
    with sqlite3.connect(tmp_path / "t.db") as db:
        assert db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0


def test_each_provider_is_tested_on_its_own(tmp_path):
    transport = Pretend()
    run(tmp_path, transport, providers=("gemini",))
    assert transport.calls and all("googleapis" in url for url, _, _ in transport.calls)
    assert live.provider_env(KEYS, "gemini") == {"GEMINI_API_KEY": KEYS["GEMINI_API_KEY"]}


def test_a_silent_provider_is_skipped_after_three_cases(tmp_path):
    def mixed(url, headers, body, timeout):
        return (401, {"error": {"message": "bad key " + KEYS["GROQ_API_KEY"]}}) if "groq" in url \
            else reply({"days": 14})

    record = run(tmp_path, mixed, providers=("groq", "gemini"), cases=small(reading=6))
    groq = [i["status"] for i in record["items"] if i["provider"] == "groq"]
    assert groq == ["no_answer"] * 3 + ["not_run"] * 3
    assert all(i["status"] in ("pass", "fail") for i in record["items"] if i["provider"] == "gemini")
    saved = json.dumps(results.runs("live"))
    assert "pretend_secret" not in saved and "PretendSecret" not in saved


def test_reading_compares_the_rules_with_the_ai(tmp_path):
    record = run(tmp_path, Pretend(), cases={**small(), "reading": [c for c in CASES["reading"]
                                                                    if c["id"] in ("read-fortnight", "trap-no-budget")]})
    good, trap = record["items"]
    assert good["status"] == "pass" and good["fields"]["days"]["rules_result"] == "missed"
    # the AI made up a budget: the app does not take it, and the record still says what the AI proposed
    assert trap["fields"]["budget"] == {**trap["fields"]["budget"], "with_ai": None, "ai_result": "right",
                                        "ai_refused": 200000}
    row = record["providers"]["groq"]["groups"]["reading"]
    assert row["invented"] == 0 and row["ai_right"] > row["rules_right"]


def test_scores_of_a_field():
    assert [live.score_field(*pair) for pair in ((None, None), (None, 5), (5, None), (5, 4), (5, 5))] == \
        ["right", "invented", "missed", "wrong", "right"]


def test_ranking_notes_made_up_ids_and_the_judge_does_not_know_which_list_is_which(tmp_path):
    def made_up(url, user):
        return reply({"order": ["not-a-real-id"] + [c["id"] for c in reversed(json.loads(user)["candidates"])]})

    # the judge likes list "a" best, so the scores must follow wherever each list was put
    seen = {}
    for seed in range(12):
        transport = Pretend({"ranking": made_up})
        record = run(tmp_path, transport, providers=("groq", "gemini"), cases=small(ranking=1), seed=seed)
        item = record["items"][0]
        assert item["status"] == "fail" and item["unknown_ids"] == ["not-a-real-id"]
        assert item["judge"]["by"] == "gemini" and item["judge"]["itself"] is False
        url, _, user = next(c for c in transport.calls if c[1] == "judge_lists")
        assert "googleapis" in url and "ai_list" not in user and "rules" not in user
        ai_first = json.loads(user)["a"] == item["ai_list"]
        assert (item["judge"]["ai_score"], item["judge"]["rules_score"]) == ((5, 1) if ai_first else (1, 5))
        seen[ai_first] = True
    assert seen == {True: True, False: True}


def test_with_one_provider_the_judge_says_it_judged_itself(tmp_path):
    record = run(tmp_path, Pretend(), cases=small(chat=1))
    assert record["items"][0]["judge"] == {"by": "groq", "itself": True, "unsupported": []}
    assert record["providers"]["groq"]["groups"]["chat"]["judged_by_itself"] == 1
    assert "judge_data" not in record["items"][0]


def test_the_judge_comes_last_and_is_marked_when_calls_run_out(tmp_path):
    transport = Pretend()
    record = run(tmp_path, transport, cases=small(summary=2, chat=2), limit=5)
    assert [job for _, job, _ in transport.calls] == ["summary", "summary", "chat", "chat", "judge_text"]
    assert sum("not_run" in (i.get("judge") or {}) for i in record["items"]) == 3


def test_a_summary_with_a_wrong_amount_or_place_is_a_problem(tmp_path):
    def wrong(url, user):
        return reply({"overview": "Only ₹123 in all. Do not miss Hawa Mahal Palace."})

    item = run(tmp_path, Pretend({"summary": wrong}), cases=small(summary=1), judge=False)["items"][0]
    assert item["status"] == "fail" and item["shown"] is False
    assert any(f.startswith("amounts") for f in item["flags"]) and any("Hawa Mahal" in f for f in item["flags"])


def test_chat_must_admit_what_the_plan_does_not_say(tmp_path):
    unanswerable = [c for c in CASES["chat"] if c.get("not_in_plan")][:1]
    for text, status in (("It opens early in the morning.", "fail"), ("The plan doesn't say.", "pass"),
                         ("The plan does not mention opening times.", "pass"),
                         ("I have booked it. The plan does not say.", "fail")):
        found = run(tmp_path, Pretend({"chat": lambda u, d, t=text: reply({"answer": t})}),
                    cases={**small(), "chat": unanswerable}, judge=False)["items"][0]
        assert found["status"] == status, text


def test_a_stopped_run_keeps_what_it_had(tmp_path):
    def stops(item):
        if item["case"] == CASES["reading"][1]["id"]:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, Pretend(), cases=small(reading=3), on_item=stops)
    saved = results.runs("live")[0]
    assert saved["finished"] is False and len(saved["items"]) == 2 and saved["calls_used"] == 2


def test_nothing_goes_into_the_request_records(tmp_path, monkeypatch):
    written = []
    monkeypatch.setattr(observe, "_finish_span", lambda *a, **k: written.append(a))
    run(tmp_path, Pretend(), cases=small(reading=1, ranking=1, summary=1, chat=1))
    assert written == [] and not observe.active()


def test_after_too_many_requests_it_waits_a_minute_before_trying_again(tmp_path):
    answers = [(429, {"error": {"message": "Rate limit reached in organization `org_01abcdef2345` on tokens per minute"}}),
               reply({"days": 14})]
    waits, told = [], []
    record = live.run(dict(KEYS), providers=["groq"], cases=small(reading=1), db=str(tmp_path / "t.db"),
                      transport=lambda *a: answers.pop(0), sleep=waits.append, pause=0,
                      on_wait=lambda provider, seconds: told.append(provider))
    assert live.RATE_WAIT in waits and told == ["groq"]
    assert record["calls_used"] == 2 and record["items"][0]["status"] in ("pass", "fail")


def test_the_account_name_in_a_provider_error_is_not_saved(tmp_path):
    def limited(*args):
        return 429, {"error": {"message": "Rate limit reached in organization `org_01abcdef2345` on tokens"}}

    record = run(tmp_path, limited, cases=small(reading=1))
    assert "org_***" in record["items"][0]["problems"][0]
    assert "01abcdef2345" not in json.dumps(results.runs("live"))


def test_every_live_reading_case_leaves_the_ai_something_to_read():
    """If the rules read everything, the AI is never asked and a healthy provider looks silent."""
    for case in CASES["reading"]:
        parsed = parse_request(case["text"], live.TODAY)
        assert parsed["missing"] or parsed["invalid"], case["id"]
