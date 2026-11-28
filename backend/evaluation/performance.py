"""Speed, reliability and cost figures, worked out from records that were really measured.

Two sources, never mixed:

* ``offline``: the whole-trip test requests, run now with recording on. No internet and no AI, so it shows how long
  the app's own steps take on this computer. It says nothing about live speed.
* ``records``: what the app recorded while you used it (``.runtime/observability.db``): real AI and data lookups.
  Only counts, times and model names are read, never typed text.

The sums themselves are the dashboard's (``app/observability/analytics.py``). A figure with nothing to measure is
"not measured", never zero. Cost is worked out only from prices you give; none are built in.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.observability import analytics, settings
from app.observability.recorder import Recorder
from app.observability.store import RecordStore
from app.services.trip_service import PlannerService
from evaluation import cases as datasets
from evaluation import harness

WORKLOAD = "end_to_end_cases.json"


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def figures(data: analytics.Data) -> dict:
    """Every performance figure for the requests in ``data``."""
    over = analytics.overview(data)
    agents = analytics.agents(data)["agents"]
    models = analytics.ai(data)
    sources = analytics.retrieval(data)["sources"]
    steps = [s for _, s in data.each()]
    tools = [s for s in steps if s["type"] == "tool"]
    tool_errors = sum(s["status"] == "error" for s in tools)

    attempts = [m for m in models["models"] if m["job"] != "voice"]
    calls = sum(m["calls"] for m in attempts)
    asked = sum(j["asked"] for j in models["jobs"])
    from_cache = sum(j["from_cache"] for j in models["jobs"])
    ai = {"model_calls": calls, "failed_calls": sum(m["failed"] for m in attempts),
          "failure_rate": _rate(sum(m["failed"] for m in attempts), calls),
          "retries": sum(m["retries"] for m in attempts),
          "tokens_in": sum(m["tokens_in"] for m in attempts), "tokens_out": sum(m["tokens_out"] for m in attempts),
          "calls_with_estimated_tokens": sum(m["estimated_token_calls"] for m in attempts),
          "questions_for_ai": asked, "answered_from_cache": from_cache, "cache_hit_rate": _rate(from_cache, asked),
          "models": [{k: m[k] for k in ("job", "provider", "model", "calls", "failed", "retries", "tokens_in",
                                        "tokens_out", "median_ms", "p90_ms")} for m in models["models"]]}

    tried = sum(s["lookups"] - s["skipped"] for s in sources)
    failed = sum(s["error"] + s["timeout"] for s in sources)
    answered = sum(s["ok"] + s["empty"] for s in sources)
    cached = sum(s["from_cache"] for s in sources)
    external = {"lookups": sum(s["lookups"] for s in sources), "failed": failed,
                "skipped": sum(s["skipped"] for s in sources), "failure_rate": _rate(failed, tried),
                "answered_from_cache": cached, "cache_hit_rate": _rate(cached, answered),
                "sources": [{k: s[k] for k in ("source", "lookups", "error", "timeout", "from_cache", "median_ms",
                                               "p90_ms")} for s in sources]}
    return {"requests": over["requests"],
            "workflow": {"by_kind": [{k: r[k] for k in ("kind", "count", "median_ms", "p90_ms", "max_ms")}
                                     for r in over["by_kind"]],
                         "full_plans": over["plans"]["full"], "failed_requests": over["failed_requests"],
                         "failure_rate": _rate(over["failed_requests"], over["requests"]),
                         "automatic_replans": over["replans"]},
            "agents": [{k: a[k] for k in ("agent", "runs", "median_ms", "p90_ms", "max_ms", "success_rate",
                                          "tool_calls", "tool_retries", "tool_errors", "ai_calls", "ai_retries")}
                       for a in agents],
            "tools": {"calls": len(tools), "failed": tool_errors, "failure_rate": _rate(tool_errors, len(tools)),
                      "retries": sum(s["attrs"].get("attempt", 1) > 1 for s in tools)},
            "ai": ai, "external": external}


# ------------------------------------------------------------------ the two sources
def workload(folder: Path = datasets.DATASETS) -> list[dict]:
    """The whole-trip requests without made-up outages, which would distort the failure and retry figures."""
    return [c["input"] for c in datasets.load(folder / WORKLOAD)
            if c["target"] == "planner" and not c["input"].get("failures")]


def offline(repeat: int = 3, requests: list[dict] | None = None) -> dict:
    """Run the workload ``repeat`` times with recording on, in memory, and measure it."""
    requests = requests if requests is not None else workload()
    store = RecordStore(":memory:")
    recorder = Recorder(store, details=False, prune=False)
    with harness.offline():
        for _ in range(repeat):
            for given in requests:
                planner = harness.Planner(harness._deps(harness.InProcessClient(), harness.Store(":memory:")))
                service = PlannerService(planner, require_auth=False, recorder=recorder)
                view = service.plan(given["request"], group=given.get("group"))
                if given.get("approve") and view.get("status") == "awaiting_approval":
                    service.approve(view["thread_id"], {"action": "approve"})
    out = figures(analytics.Data.load(store, analytics.Filters()))
    return {"source": f"offline: {len(requests)} test requests, {repeat} time(s), no internet and no AI. "
                      "The app's own steps on this computer; not live speed.",
            "outside_services": "not measured: offline, no AI and no outside data service is called (the lookups "
                                "listed here are local)",
            "recording_errors": recorder.errors, **out}


def from_records(period: str = "all", path: str | None = None) -> dict:
    """What was recorded while the app was used."""
    path = path or settings.db_path()
    if not Path(path).is_file():
        return {"source": "your recorded use", "requests": 0,
                "note": "no records yet: use the app with recording on (OBSERVABILITY=1)"}
    store = RecordStore(path)
    out = figures(analytics.Data.load(store, analytics.parse_filters({"period": period})))
    return {"source": f"your recorded use (period: {period}); real requests, real lookups", **out}


# ------------------------------------------------------------------ cost
def load_prices(path: str | Path | None) -> dict | None:
    """{"currency": "...", "models": {name: {"input_per_million": n, "output_per_million": n}}}, or None."""
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_float=str, parse_int=str)
        currency, models = str(data["currency"]).strip(), data["models"]
        prices = {name: (Decimal(str(m["input_per_million"])), Decimal(str(m["output_per_million"])))
                  for name, m in models.items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
        raise ValueError('the price file must look like {"currency": "USD", "models": {"model name": '
                         '{"input_per_million": 0.0, "output_per_million": 0.0}}}') from None
    if not currency or not prices or any(not v.is_finite() or v < 0 for pair in prices.values() for v in pair):
        raise ValueError("the price file needs a currency and prices of zero or more")
    return {"currency": currency, "models": prices}


def cost(usage: list[dict], prices: dict | None) -> dict:
    """``usage``: rows with model, tokens_in, tokens_out. Money is worked out with Decimal."""
    used: dict = {}
    for row in usage:
        if row.get("tokens_in") or row.get("tokens_out"):
            pair = used.setdefault(row["model"], [0, 0])
            pair[0] += row.get("tokens_in") or 0
            pair[1] += row.get("tokens_out") or 0
    if not used:
        return {"value": None, "note": "not worked out: no AI tokens were used"}
    if prices is None:
        return {"value": None, "note": "not worked out: no prices are configured (--prices FILE or EVAL_PRICES)"}
    total, unpriced, by_model = Decimal(0), [], {}
    for model, (tokens_in, tokens_out) in sorted(used.items()):
        if model not in prices["models"]:
            unpriced.append(model)
            continue
        per_in, per_out = prices["models"][model]
        amount = (per_in * tokens_in + per_out * tokens_out) / Decimal(1_000_000)
        by_model[model] = str(amount.quantize(Decimal("0.000001")))
        total += amount
    if not by_model:
        return {"value": None, "note": "not worked out: no price is given for " + ", ".join(unpriced)}
    note = "from your prices and the recorded tokens; voice is not included. It is not a bill."
    if unpriced:
        note = "PARTIAL: no price for " + ", ".join(unpriced) + ". " + note
    return {"value": str(total.quantize(Decimal("0.000001"))), "currency": prices["currency"],
            "partial": bool(unpriced), "by_model": by_model, "note": note}
