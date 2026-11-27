"""Look at the records from a terminal (the dashboard comes later). Run from the backend folder:

    python -m app.observability            the latest requests, and the steps of the newest one
    python -m app.observability 3          the steps of the third request in that list
    python -m app.observability 3 --text   with the detailed text too (only kept when RECORD_DETAILS=1)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from app.core import config
from app.observability import settings
from app.observability.store import RecordStore

SHOWN = 15


def _local(started: str) -> str:
    return datetime.fromisoformat(started).astimezone().strftime("%d %b %H:%M:%S")


def _seconds(ms) -> str:
    return f"{(ms or 0) / 1000:7.2f}s"


def _facts(attrs: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in attrs.items() if v not in ({}, []))


def tree(spans: list) -> list[str]:
    children: dict = {}
    ids = {s["id"] for s in spans}
    for s in spans:
        if s["type"] != "log":
            children.setdefault(s["parent_id"] if s["parent_id"] in ids else None, []).append(s)
    lines: list[str] = []

    def walk(parent, depth):
        for s in sorted(children.get(parent, []), key=lambda item: item["start_ms"]):
            lines.append(f"{_seconds(s['duration_ms'])}  {'  ' * depth}{s['type']}: {s['name']} "
                         f"[{s['status']}] {_facts(s['attrs'])}".rstrip())
            walk(s["id"], depth + 1)

    walk(None, 0)
    return lines


def report(store: RecordStore, number: int = 1, text: bool = False) -> str:
    runs = store.runs(SHOWN)
    if not runs:
        return "No requests recorded yet. Plan a trip on the page, then run this again."
    lines = ["Latest requests (newest first):"]
    for n, run in enumerate(runs, 1):
        via = f"  (started from {run['attrs']['via']})" if run["attrs"].get("via") else ""
        lines.append(f"{n:3}. {_local(run['started'])}  {run['kind']:8} {run['status']:13} "
                     f"{_seconds(run['duration_ms'])}  engine={run['engine']}{via}")
    if not 1 <= number <= len(runs):
        return "\n".join([*lines, f"\nThere is no request number {number}."])
    run = runs[number - 1]
    lines += ["", f"Request {number}: {run['kind']} ({run['status']})  {_facts(run['attrs'])}", *tree(store.spans(run["id"]))]
    if text:
        details = store.details(run["id"])
        lines += ["", "Detailed text:" if details else "No detailed text was kept (RECORD_DETAILS=1 keeps it)."]
        names = {s["id"]: s["name"] for s in store.spans(run["id"])}
        lines += [f"- {names.get(d['span_id'], 'request')} / {d['name']}: {d['content'][:400]}" for d in details]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    config.load_env()
    path = settings.db_path()
    if not os.path.exists(path):
        print(f"No records yet ({path} does not exist).")
        return 0
    numbers = [a for a in argv if a.isdigit()]
    out = report(RecordStore(path), int(numbers[0]) if numbers else 1, "--text" in argv)
    encoding = sys.stdout.encoding or "utf-8"                  # a Windows console may not print every character
    print(out.encode(encoding, "replace").decode(encoding))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
