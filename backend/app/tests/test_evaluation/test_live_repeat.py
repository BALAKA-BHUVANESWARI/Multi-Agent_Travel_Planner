"""Blocked AI answers are kept, every call is timed, and saved runs are put together (pretend provider only)."""
import copy

from app.evaluation import live, repeat, results
from app.tests.test_evaluation.test_live import KEYS, Pretend, reply, small

INVENTED = {"answer": "Yes. The hotel has a rooftop infinity pool and you should see the Hawa Mahal Palace."}


class Clock:
    """Each send takes ``step`` seconds; pauses and waits take much longer and must not be counted."""

    def __init__(self, transport, step=2.0):
        self.now, self.step, self.transport = 0.0, step, transport

    def __call__(self):
        return self.now

    def send(self, *args):
        self.now += self.step
        return self.transport(*args)

    def sleep(self, seconds):
        self.now += 1000


def run(tmp_path, transport, cases, step=2.0, **kwargs):
    clock = Clock(transport, step)
    kwargs.setdefault("judge", False)
    return live.run(dict(KEYS), providers=["groq"], cases=cases, db=str(tmp_path / "t.db"), transport=clock.send,
                    sleep=clock.sleep, clock=clock, **kwargs)


def test_a_chat_answer_the_app_holds_back_is_still_an_answer(tmp_path):
    record = run(tmp_path, Pretend({"chat": lambda u, d: reply(INVENTED)}), small(chat=4), pause=0)
    assert [i["status"] for i in record["items"]] == ["fail"] * 4       # not "no answer", and never skipped
    item = record["items"][0]
    assert item["shown"] is False and item["answer"] == INVENTED["answer"]
    assert item["problems"][0].startswith("the app would not show this answer: unsupported")
    assert record["providers"]["groq"]["groups"]["chat"]["not_shown"] == 4
    assert record["providers"]["groq"]["call_stats"] == {"made": 4, "failed": 0, "kinds": {},
                                                          "reply": repeat.times([2.0] * 4)}


def test_a_supported_chat_answer_is_marked_as_shown(tmp_path):
    item = run(tmp_path, Pretend(), small(chat=1), pause=0)["items"][0]
    assert item["shown"] is True and not any("would not show" in p for p in item["problems"])


def test_a_summary_is_judged_by_every_check_the_app_uses(tmp_path):
    item = run(tmp_path, Pretend({"summary": lambda u, d: reply({"overview": "Do not miss Hawa Mahal Palace."})}),
               small(summary=1), pause=0)["items"][0]
    assert item["shown"] is False and "unsupported places" in item["problems"][0]


def test_reply_time_leaves_out_pauses_and_waits(tmp_path):
    answers = [(429, {}), reply({"days": 14}), reply({"days": 14})]
    record = run(tmp_path, lambda *a: answers.pop(0), small(reading=2), pause=5.0)
    assert [(c["result"], c["seconds"], c["job"]) for c in record["call_log"]] == \
        [("rate_limited", 2.0, "reading"), ("ok", 2.0, "reading"), ("ok", 2.0, "reading")]
    stats = record["providers"]["groq"]["call_stats"]
    assert stats["kinds"] == {"rate_limited": 1} and stats["reply"]["median"] == 2.0


def test_kinds_of_failed_calls(tmp_path):
    from app.services.llm_service import ProviderError
    outcomes = [(503, {}), ProviderError("network error: The read operation timed out"),
                ProviderError("network error: connection refused")]

    def failing(*args):
        found = outcomes.pop(0)
        if isinstance(found, Exception):
            raise found
        return found

    record = run(tmp_path, failing, small(reading=1), pause=0)
    assert [c["result"] for c in record["call_log"]] == ["server_busy", "timeout", "network"]
    assert record["items"][0]["status"] == "no_answer"


def test_a_reply_that_cannot_be_used_is_a_failed_call(tmp_path):
    record = run(tmp_path, lambda *a: (200, {"choices": [{"message": {"content": "not json"}}]}),
                 small(chat=1), pause=0)
    assert [c["result"] for c in record["call_log"]] == ["unusable"]
    assert record["items"][0]["status"] == "no_answer"


def test_the_apps_daily_limit_is_not_counted_against_the_ai(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.LLM_DAILY_CALL_LIMIT", 1)
    record = run(tmp_path, Pretend(), small(chat=3), pause=0)
    assert [i["status"] for i in record["items"]][1:] == ["not_run", "not_run"]
    assert "no call was made" in record["items"][1]["problems"][0] and len(record["call_log"]) == 1
    assert repeat.combine([record])[0]["jobs"]["chat"]["not_run"] == 2
    assert "not run (call limit, daily limit or a silent provider): 2" in repeat.text([record], {})


def three_runs(tmp_path):
    replies = iter(["The plan does not say.", "It opens early.", "The plan does not say."])
    for _ in range(3):
        text = next(replies)
        run(tmp_path, Pretend({"chat": lambda u, d, t=text: reply({"answer": t})}),
            {**small(reading=2), "chat": [c for c in live.load_cases()["chat"] if c.get("not_in_plan")][:1]},
            pause=0, judge=True)
    return results.runs("live")


def test_saved_runs_are_put_together_and_changes_between_runs_are_named(tmp_path):
    found, left_out = repeat.comparable(three_runs(tmp_path))
    assert len(found) == 3 and not any(left_out.values())
    entry, = repeat.combine(found)
    chat = entry["jobs"]["chat"]
    assert (chat["answered"], chat["passed"], chat["repeated_cases"], len(chat["changed"])) == (3, 2, 1, 1)
    reading = entry["jobs"]["reading"]
    assert reading["repeated_cases"] == 2 and not reading["changed"]
    items = [i for r in found for i in r["items"] if i["group"] == "reading"]
    assert entry["reading"]["fields"] == sum(len(i["fields"]) for i in items)
    assert entry["calls"]["made"] == sum(r["calls_used"] for r in found)
    assert entry["claims"]["chat"]["answers"] == 3 == entry["claims"]["chat"]["judged"]
    report = repeat.text(found, left_out)
    assert "3 run(s) combined" in report and "Fewer than 3 runs" not in report and "Reply time" in report
    assert "pretend_secret" not in report


def test_older_and_different_runs_are_left_out_and_said_so(tmp_path):
    newest = run(tmp_path, Pretend(), small(reading=1), pause=0)
    old = {k: v for k, v in copy.deepcopy(newest).items() if k not in ("measure", "call_log", "cases_id")}
    other = {**copy.deepcopy(newest), "version": "abc1234"}
    found, left_out = repeat.comparable([newest, old, other, newest], last=1)
    assert len(found) == 1
    assert left_out == {"older_way_of_measuring": 1, "other_code_or_cases": 1, "beyond_the_limit_asked_for": 1}
    report = repeat.text(found, left_out)
    assert "Fewer than 3 runs" in report and "older way of measuring" in report
    assert "No run to report yet" in repeat.text(*repeat.comparable([old]))


def test_few_calls_give_no_nine_in_ten_figure():
    assert repeat.times([1, 2, 30]) == {"calls": 3, "median": 2, "p90": None, "slowest": 30}
    assert repeat.times(list(range(1, 11)))["p90"] == 9
    assert repeat.times([]) == {"calls": 0, "median": None, "p90": None, "slowest": None}
