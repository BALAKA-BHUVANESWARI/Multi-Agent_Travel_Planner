"""Live AI tests: the four jobs the AI does, one provider at a time, on fixed test requests.

  reading    how a request is read: the rules alone against the rules with the AI filling gaps
  ranking    the order of things to do: by the rules against re-ordered by the AI
  summary    the AI overview of a plan, checked against the plan
  chat       answers to questions the rules cannot answer, checked against the plan

Plans and places are built offline with a fixed date, so only the AI differs from run to run. The saved-answer
cache is off. Every call to a provider counts toward one limit, retries and the AI judge included. Nothing here
goes into the dashboard's request records. Keys are never printed or saved.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import date
from pathlib import Path
from typing import Callable

from app.agents.activity_agent import _llm_rerank
from app.agents.intake_agent import intake_node
from app.agents.itinerary_agent import _allowed_amounts, ask_overview, numbers_are_grounded
from app.core import config
from app.database.repositories import Store
from app.evaluation import results
from app.graph.deps import Deps
from app.graph.runner import Planner
from app.graph.state import initial_state
from app.services import chat_service, fact_checks
from app.services.llm_service import LLMRouter, ProviderError, default_transport
from app.tools.client import InProcessClient

MAX_CALLS = 100
TODAY = date(2026, 11, 24)
PROVIDERS = ("groq", "gemini", "ollama")
RATE_WAIT = 60.0                                  # seconds to wait after a provider says "too many requests"
STOP_AFTER = 3                                    # unanswered cases in a row before a provider is skipped
GROUPS = ("reading", "ranking", "summary", "chat")
FIELDS = ("origin", "destination", "days", "budget", "travelers")
TOP = 6                                           # how many of the first activities are compared
CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "live_cases.json"
_LIMIT_STATUS = 400                               # not retried, no cool-down
_SAYS_UNKNOWN = re.compile(
    r"\b(?:does not|doesn't|doesn’t|do not|don't|don’t|not)\s+(?:\w+\s+){0,2}?(?:say|mention|include|specify|contain|"
    r"state|provide|have|list|show|give|cover|indicate|detail|available|provided|listed|specified|mentioned|included|"
    r"stated|known)|\bno (?:information|details?|mention|data)\b", re.I)
_CLAIMS_ACTION = re.compile(r"\bI(?:'ve|’ve| have)?\s+(?:now\s+|just\s+)?(?:booked|cancelled|canceled|reserved|paid|changed|"
                            r"updated|confirmed)\b", re.I)
_JUDGE_TEXT = ("You check an AI-written text against the data it was written from. List every statement in the text "
               "that the data does not support. General politeness and saying that something is unknown are fine. "
               "Return {\"unsupported\": [\"...\"]}, an empty list when everything is supported.")
_JUDGE_TEXT_SCHEMA = {"type": "object", "required": ["unsupported"],
                      "properties": {"unsupported": {"type": "array", "items": {"type": "string"}, "maxItems": 12}}}
_JUDGE_LISTS = ("Two lists, A and B, give the first things to do for the same trip. Rate how well each fits the "
                "traveller's preferences, from 1 (not at all) to 5 (very well). Return {\"a\": n, \"b\": n}.")
_JUDGE_LISTS_SCHEMA = {"type": "object", "required": ["a", "b"],
                       "properties": {"a": {"type": "integer", "minimum": 1, "maximum": 5},
                                      "b": {"type": "integer", "minimum": 1, "maximum": 5}}}


def load_cases(path: Path = CASES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def provider_env(env, name: str) -> dict:
    """Only this provider's settings, so no other one can answer in its place."""
    _, key_env, model_env, _ = config.PROVIDERS[name]
    wanted = [key_env, model_env] + (["OLLAMA_BASE_URL"] if name == "ollama" else [])
    return {k: env[k] for k in wanted if env.get(k)}


def available_providers(env) -> list[str]:
    return [n for n in PROVIDERS if LLMRouter(env=provider_env(env, n)).chain("intake")]


def planned_calls(cases: dict, providers: list[str], judge: bool = True) -> dict:
    """How many calls a run needs when nothing is retried."""
    each = sum(len(cases[g]) for g in GROUPS)
    judged = sum(len(cases[g]) for g in ("ranking", "summary", "chat")) if judge else 0
    return {"tests": each * len(providers), "judge": judged * len(providers)}


class Budget:
    def __init__(self, limit: int):
        self.limit = max(0, min(int(limit), MAX_CALLS))
        self.used = 0

    @property
    def left(self) -> int:
        return self.limit - self.used


class LiveStore(Store):
    """The app's database for the daily call counters, with the saved-answer cache switched off."""

    def __init__(self, path: str, budget: Budget):
        super().__init__(path)
        self.budget = budget

    def cache_get(self, key: str):
        return None

    def cache_set(self, key: str, value: dict) -> None:
        return None

    def bump(self, name: str, today: str | None = None) -> int:
        if self.budget.left <= 0:                  # this call will not be made, so it does not count for today
            return self.count(name, today)
        return super().bump(name, today)


class _Run:
    def __init__(self, env, store: LiveStore, budget: Budget, transport, sleep, pause: float, on_item, rng):
        self.env, self.store, self.budget, self.sleep, self.pause = env, store, budget, sleep, pause
        self.on_item, self.rng = on_item, rng
        self.send = transport or default_transport
        self.current = ""                          # provider being called, for the call counts
        self.calls: dict = {}
        self.blocked = False                       # a call was refused by the limit
        self.routers: dict = {}
        self.models: dict = {}
        self.silent: dict = {}                     # provider -> unanswered cases in a row
        self.items: list[dict] = []
        self.limited: set = set()                  # providers whose last answer was "too many requests"
        self.on_wait = lambda provider, seconds: None
        self.offline = Planner(Deps(tools=InProcessClient(), store=Store(), llm=LLMRouter(env={}), today=TODAY,
                                    sleep=lambda s: None))

    def transport(self, url, headers, body, timeout):
        if self.budget.left <= 0:
            self.blocked = True
            raise ProviderError("the call limit for this run is used up", _LIMIT_STATUS)
        if self.current in self.limited:           # free plans count per minute: a quick retry only wastes a call
            self.limited.discard(self.current)
            self.on_wait(self.current, RATE_WAIT)
            self.sleep(RATE_WAIT)
        elif self.budget.used and self.pause:
            self.sleep(self.pause)                 # free plans allow only a few calls a minute
        self.budget.used += 1
        self.calls[self.current] = self.calls.get(self.current, 0) + 1
        status, payload = self.send(url, headers, body, timeout)
        if status == 429:
            self.limited.add(self.current)
        return status, payload

    def router(self, name: str) -> LLMRouter:
        if name not in self.routers:
            self.routers[name] = LLMRouter(env=provider_env(self.env, name), store=self.store,
                                           transport=self.transport, sleep=self.sleep)
            self.models[name] = self.routers[name].chain("intake")[0]["model"]
        return self.routers[name]

    def ready(self, name: str) -> str:
        """"" when this provider can be tried, else why not."""
        if self.budget.left <= 0:
            return "the call limit for this run was reached"
        if self.silent.get(name, 0) >= STOP_AFTER:
            return f"{name} did not answer {STOP_AFTER} times in a row"
        return ""

    def fresh(self, name: str) -> LLMRouter:
        router = self.router(name)
        router.begin_run()
        router._cooldown.clear()                   # each case gets its own chance
        self.current, self.blocked = name, False
        return router

    def failure(self, router: LLMRouter) -> str:
        text = router.last_failure or "no answer"
        for name in PROVIDERS:
            key = self.env.get(config.PROVIDERS[name][1])
            if key and len(str(key)) > 6:
                text = text.replace(str(key), "***")
        return text[:200]

    def add(self, item: dict) -> None:
        self.items.append(item)
        self.on_item(item)

    def plan(self, request: str) -> dict:
        state = self.offline.start(request)
        if not state.get("itinerary"):
            raise ValueError(f"the test request did not give a plan: {request}")
        return state


class _Recorder:
    """Notes the last JSON a router returned, without changing what the caller gets."""

    def __init__(self, router: LLMRouter):
        self.router, self.last = router, None

    def available(self, role: str) -> bool:
        return self.router.available(role)

    def complete_json(self, role, system, user, schema):
        self.last = self.router.complete_json(role, system, user, schema)
        return self.last


# ------------------------------------------------------------------ the four tests
def score_field(expected, got) -> str:
    """right, wrong, missed (nothing read), invented (a value although the request gives none) or left_out."""
    if expected is None:
        return "right" if got is None else "invented"
    if got is None:
        return "missed"
    return "right" if got == expected else "wrong"


def _read(run: _Run, request: str, llm) -> dict:
    deps = Deps(tools=InProcessClient(), store=Store(), llm=llm, today=TODAY, sleep=lambda s: None)
    return intake_node(initial_state(request), deps).get("constraints") or {}


def _reading(run: _Run, router, case: dict) -> dict:
    watched = _Recorder(router)
    rules = _read(run, case["text"], LLMRouter(env={}))
    with_ai = _read(run, case["text"], watched)
    if watched.last is None:
        return {"status": "no_answer"}
    fields = {k: {"expected": v, "rules": rules.get(k), "with_ai": with_ai.get(k),
                  "rules_result": score_field(v, rules.get(k)), "ai_result": score_field(v, with_ai.get(k))}
              for k, v in case["expect"].items()}
    if "travelers" in fields and case["expect"]["travelers"] is not None:
        fields["travelers"]["note"] = "the app never lets the AI fill in the number of travellers"
    bad = [f"{k}: {f['ai_result']} (expected {f['expected']}, got {f['with_ai']})"
           for k, f in fields.items() if f["ai_result"] != "right"]
    return {"status": "fail" if bad else "pass", "fields": fields, "problems": bad,
            "answer": json.dumps(watched.last, ensure_ascii=False)}


def tag_share(rows: list[dict], preferences: list) -> float | None:
    first = rows[:TOP]
    if not first or not preferences:
        return None
    return round(sum(bool(set(r.get("tags") or []) & set(preferences)) for r in first) / len(first), 3)


def _ranking(run: _Run, router, case: dict) -> dict:
    state = run.plan(case["text"])
    by_rules, c = state["activities"]["candidates"], state["constraints"]
    watched = _Recorder(router)
    by_ai, used = _llm_rerank(list(by_rules), c, Deps(tools=InProcessClient(), store=Store(), llm=watched,
                                                       today=TODAY, sleep=lambda s: None))
    if watched.last is None:
        return {"status": "no_answer"}
    known = {r["id"] for r in by_rules}
    unknown = [str(i)[:60] for i in watched.last.get("order") or [] if i not in known]
    prefs = c.get("preferences") or []
    return {"status": "pass" if used and not unknown else "fail",
            "problems": ([] if used else ["the AI order could not be used"])
            + ([f"{len(unknown)} ids that were not on the list (dropped)"] if unknown else []),
            "rules_share": tag_share(by_rules, prefs), "ai_share": tag_share(by_ai, prefs), "unknown_ids": unknown,
            "preferences": prefs, "rules_list": [r["name"] for r in by_rules[:TOP]],
            "ai_list": [r["name"] for r in by_ai[:TOP]], "answer": " | ".join(r["name"] for r in by_ai[:TOP])}


def _plan_data(state: dict, facts) -> list:
    return [facts, chat_service.plan_facts(state), (state.get("flight") or {}).get("journey")]


def _summary(run: _Run, router, case: dict) -> dict:
    state = run.plan(case["text"])
    obj, facts = ask_overview(state, router)
    if not obj:
        return {"status": "no_answer"}
    text, c = str(obj["overview"])[:2000], state["constraints"]
    allowed = _allowed_amounts(state)
    shown = numbers_are_grounded(obj["overview"], allowed)
    flags, looked = fact_checks.check_text(text, _plan_data(state, facts), start_date=c.get("start_date"),
                                           days=c.get("days"), amounts=allowed)
    problems = [f"{f['kind']}: {f['value']}" for f in flags]
    if not shown:
        problems.insert(0, "the app would not show this text: an amount does not match the plan")
    return {"status": "fail" if problems else "pass", "answer": text, "problems": problems, "shown": shown,
            "flags": [f"{f['kind']}: {f['value']}" for f in flags], "looked_at": sum(looked.values()),
            "judge_data": facts}


def _chat(run: _Run, router, case: dict) -> dict:
    state = run.plan(case["plan"])
    answer = chat_service.ai_answer(state, case["text"], router)
    if not answer:
        return {"status": "no_answer"}
    c, data = state["constraints"], chat_service.plan_facts(state)
    flags, looked = fact_checks.check_text(answer, [data, (state.get("flight") or {}).get("journey")],
                                           start_date=c.get("start_date"), days=c.get("days"), question=case["text"])
    problems = [f"{f['kind']}: {f['value']}" for f in flags]
    if case.get("not_in_plan") and not _SAYS_UNKNOWN.search(answer):
        problems.append("the plan cannot answer this, but the reply does not say so")
    if _CLAIMS_ACTION.search(answer):
        problems.append("the reply says it booked, cancelled or changed something")
    return {"status": "fail" if problems else "pass", "answer": answer, "problems": problems,
            "not_in_plan": bool(case.get("not_in_plan")), "flags": [f"{f['kind']}: {f['value']}" for f in flags],
            "looked_at": sum(looked.values()), "judge_data": data}


TESTS = {"reading": _reading, "ranking": _ranking, "summary": _summary, "chat": _chat}


# ------------------------------------------------------------------ the AI judge
def _judge_for(run: _Run, provider: str, providers: list[str]) -> str:
    """Another provider when one can still answer, else the provider itself."""
    return next((n for n in providers if n != provider and not run.ready(n)), provider)


def _judge(run: _Run, item: dict, providers: list[str]) -> None:
    judge = _judge_for(run, item["provider"], providers)
    why = run.ready(judge)
    if why:
        item["judge"] = {"not_run": why}
        return
    router = run.fresh(judge)
    flipped = False
    if item["group"] == "ranking":
        flipped = run.rng.random() < 0.5            # the judge must not know which list the AI made
        first, second = (item["ai_list"], item["rules_list"]) if flipped else (item["rules_list"], item["ai_list"])
        found = router.complete_json("activities", _JUDGE_LISTS, json.dumps(
            {"preferences": item["preferences"], "a": first, "b": second}, ensure_ascii=False), _JUDGE_LISTS_SCHEMA)
    else:
        data = {"text": item["answer"], "data": item["judge_data"]}
        if item["group"] == "chat":
            data["question"] = item["text"]
        found = router.complete_json("chat", _JUDGE_TEXT, json.dumps(data, ensure_ascii=False, default=str),
                                     _JUDGE_TEXT_SCHEMA)
    if not found:
        run.silent[judge] = run.silent.get(judge, 0) + 1
        item["judge"] = {"not_run": "the call limit for this run was reached" if run.blocked
                         else f"{judge}: {run.failure(router)}"}
        return
    run.silent[judge] = 0
    out = {"by": judge, "itself": judge == item["provider"]}
    if item["group"] == "ranking":
        out["rules_score"], out["ai_score"] = (found["b"], found["a"]) if flipped else (found["a"], found["b"])
    else:
        out["unsupported"] = [" ".join(str(x).split())[:240] for x in found["unsupported"]]
    item["judge"] = out


# ------------------------------------------------------------------ one run
def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None


def summarise(items: list[dict], providers: list[str], calls: dict, models: dict) -> dict:
    out = {}
    for name in providers:
        mine = [i for i in items if i["provider"] == name]
        groups = {}
        for group in GROUPS:
            rows = [i for i in mine if i["group"] == group]
            done = [i for i in rows if i["status"] in ("pass", "fail")]
            row = {"cases": len(rows), "answered": len(done), "passed": sum(i["status"] == "pass" for i in done),
                   "no_answer": sum(i["status"] == "no_answer" for i in rows),
                   "not_run": sum(i["status"] == "not_run" for i in rows),
                   "seconds": _mean([i.get("seconds") for i in done])}
            judged = [i["judge"] for i in done if i.get("judge") and "by" in i["judge"]]
            row["judged"] = len(judged)
            row["judged_by_itself"] = sum(j["itself"] for j in judged)
            if group == "reading":
                fields = [f for i in done for f in i["fields"].values()]
                row["fields"] = len(fields)
                row["rules_right"] = sum(f["rules_result"] == "right" for f in fields)
                row["ai_right"] = sum(f["ai_result"] == "right" for f in fields)
                for kind in ("wrong", "missed", "invented"):
                    row[kind] = sum(f["ai_result"] == kind for f in fields)
            elif group == "ranking":
                row["rules_share"] = _mean([i["rules_share"] for i in done])
                row["ai_share"] = _mean([i["ai_share"] for i in done])
                row["unknown_ids"] = sum(len(i["unknown_ids"]) for i in done)
                row["judge_rules"] = _mean([j["rules_score"] for j in judged])
                row["judge_ai"] = _mean([j["ai_score"] for j in judged])
            else:
                row["flagged"] = sum(bool(i["flags"]) for i in done)
                row["judge_flagged"] = sum(bool(j["unsupported"]) for j in judged)
                if group == "summary":
                    row["not_shown"] = sum(not i["shown"] for i in done)
            groups[group] = row
        out[name] = {"model": models.get(name, ""), "calls": calls.get(name, 0), "groups": groups}
    return out


def run(env, *, providers: list[str], cases: dict | None = None, db: str | None = None, transport=None,
        sleep: Callable[[float], None] = time.sleep, limit: int = MAX_CALLS, pause: float = 2.0, judge: bool = True,
        groups: tuple = GROUPS, on_item: Callable[[dict], None] = lambda item: None,
        clock: Callable[[], float] = time.monotonic, save: bool = True, seed: int | None = None,
        on_wait: Callable[[str, float], None] = lambda provider, seconds: None) -> dict:
    """Run the tests and return the record. With ``save`` it is written after every case, so a stopped run keeps
    what it had."""
    cases = cases or load_cases()
    budget = Budget(limit)
    store = LiveStore(db or config.db_path(), budget)
    record = {"id": results.new_id(), "limit": budget.limit, "calls_used": 0, "providers": {}, "items": [],
              "judge": judge, "fixed_date": str(TODAY), "cache": "off", "finished": False}

    def keep() -> None:
        record["calls_used"] = budget.used
        record["items"] = [{k: v for k, v in i.items() if k != "judge_data"} for i in state.items]
        record["providers"] = summarise(state.items, providers, state.calls, state.models)
        if save:
            results.save("live", record)

    state = _Run(env, store, budget, transport, sleep, pause, on_item, random.Random(seed))
    state.on_wait = on_wait
    try:
        for name in providers:
            state.router(name)
            for group in GROUPS:
                if group not in groups:
                    continue
                for case in cases[group]:
                    item = {"id": f"{name}.{case['id']}", "case": case["id"], "provider": name, "group": group,
                            "text": case["text"]}
                    why = state.ready(name)
                    if why:
                        state.add({**item, "status": "not_run", "problems": [why]})
                        continue
                    router = state.fresh(name)
                    started = clock()
                    try:
                        outcome = TESTS[group](state, router, case)
                    except Exception as e:                      # noqa: BLE001 - one broken case must not end the run
                        outcome = {"status": "error", "problems": [f"the test itself failed: {type(e).__name__}"]}
                    if outcome["status"] == "no_answer":
                        if state.blocked:
                            outcome = {"status": "not_run", "problems": ["the call limit for this run was reached"]}
                        else:
                            state.silent[name] = state.silent.get(name, 0) + 1
                            outcome["problems"] = [state.failure(router)]
                    elif outcome["status"] in ("pass", "fail"):
                        state.silent[name] = 0
                        outcome["seconds"] = round(max(0.0, clock() - started), 2)
                    state.add({**item, **outcome})
                    keep()
        if judge:                                              # last, with whatever calls are left
            for item in state.items:
                if item["group"] != "reading" and item["status"] in ("pass", "fail"):
                    _judge(state, item, providers)
                    keep()
        record["finished"] = True
    finally:
        keep()
        store.close()
    return record
