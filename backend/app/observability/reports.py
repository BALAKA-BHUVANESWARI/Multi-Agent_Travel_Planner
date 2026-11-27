"""Things the dashboard shows that are not in the records: the latest offline test scores, the app's own daily
limits, and downloads."""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path

from app.core import config
from app.integrations import live_prices
from app.services import speech_service

EVAL_REPORT = Path(__file__).resolve().parents[2] / "evals" / "report.md"
_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*\*{0,2}([\d.]+%?)\*{0,2}\s*\|\s*([\d.]+%?)\s*\|\s*([^|]*?)\s*\|\s*$")


def eval_scores(path: Path | None = None) -> dict | None:
    """The scores table of backend/evals/report.md, written by ``python evals/run_evals.py``."""
    path = path or EVAL_REPORT
    try:
        text = path.read_text(encoding="utf-8")
        changed = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None
    main = text.split("## Per prompt")[0]
    rows = [{"metric": m[1], "planner": m[2], "baseline": m[3], "applies": m[4]}
            for line in main.splitlines() if (m := _ROW.match(line))]
    about = re.search(r"^(\d+) prompts,[^\n]*?fixed date (\d{4}-\d{2}-\d{2})", text, re.M)
    judge = re.search(r"^Mean:\s*([\d.]+)\.", text, re.M)
    if not rows:
        return None
    return {"rows": rows, "prompts": int(about[1]) if about else None, "fixed_date": about[2] if about else None,
            "judge_mean": float(judge[1]) if judge else None, "file_changed": changed}


def daily_limits(deps) -> list[dict]:
    """What this app has used today, against the limits it sets for itself (the providers have their own)."""
    llm = getattr(deps, "llm", None)
    env = llm.env if llm else None
    configured = {p["name"] for role in config.LLM_ROUTING for p in llm.chain(role)} if llm else set()
    rows = []
    for provider in config.PROVIDERS:
        used = deps.store.count(f"llm:{provider}")
        if used or provider in configured:
            rows.append({"name": f"{provider}_calls", "label": f"AI calls to {provider.title()}", "used": used,
                         "limit": llm.daily_limit if llm else config.LLM_DAILY_CALL_LIMIT})
    if speech_service.available(env):
        rows.append({"name": "voice", "label": "Voice recordings", "used": deps.store.count("stt:groq"),
                     "limit": speech_service._daily_limit(env if env is not None else os.environ)})
    if config.live_prices_enabled():
        rows.append({"name": "live_credits", "label": "Live price credits (Tavily)",
                     "used": live_prices.credits_used_today(), "limit": config.live_daily_credits()})
    return rows


# ------------------------------------------------------------------ downloads
def _cell(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        value = "; ".join(f"{k}={v}" for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        value = "; ".join(str(v) for v in value)
    if isinstance(value, str) and value.lstrip()[:1] in ("=", "+", "-", "@", "\t"):
        return "'" + value                    # a spreadsheet must show it as text, never run it as a formula
    return value


def as_csv(rows: list[dict]) -> bytes:
    columns = list(dict.fromkeys(k for row in rows for k in row))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns)
    writer.writerows([_cell(row.get(c)) for c in columns] for row in rows)
    return ("﻿" + out.getvalue()).encode("utf-8")            # the mark lets Excel read ₹ and accents


def as_json(rows: list[dict]) -> bytes:
    return json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8")
