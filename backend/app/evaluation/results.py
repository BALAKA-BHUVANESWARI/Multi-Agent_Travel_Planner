"""Saved evaluation results: one JSON file per run in ``.runtime/evals/<kind>/``, plus the owner's hand checks.

These are results of fixed test cases, never of a traveller's requests. ``EVAL_DIR`` in the environment moves them.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path

from app.core import config

KINDS = ("offline", "live", "voice")
KEEP = {"offline": 100, "live": 30, "voice": 30}          # older runs are deleted
VERDICTS = ("good", "wrong")                              # a hand check of one live test answer
_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")
_ITEM = re.compile(r"[A-Za-z0-9_.:\-]{1,80}")
_lock = threading.Lock()


def folder() -> Path:
    return Path(config.runtime_path(os.environ.get("EVAL_DIR"), "evals"))


def new_id(now: datetime | None = None) -> str:
    return f"{(now or datetime.now()):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def code_version(root: Path | None = None) -> str:
    """The short id of the last commit, read from .git without running git ("" when unknown). Changes that are not
    committed yet are not seen."""
    git = (root or config.PROJECT_ROOT) / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(None, 1)[1]
            try:
                head = (git / ref).read_text(encoding="utf-8").strip()
            except OSError:
                packed = (git / "packed-refs").read_text(encoding="utf-8").splitlines()
                head = next(line.split()[0] for line in packed if line.endswith(" " + ref))
        return head[:7] if re.fullmatch(r"[0-9a-f]{40}", head) else ""
    except (OSError, StopIteration, IndexError):
        return ""


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(temp, path)                                # never leaves half a file behind


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _files(kind: str) -> list[Path]:
    """Newest first. The names start with the date and time."""
    return sorted((p for p in (folder() / kind).glob("*.json") if _ID.fullmatch(p.stem)), reverse=True)


def save(kind: str, record: dict) -> str:
    """Store one run; ``record`` gets an id and a time if it has none. Safe to call again for the same run."""
    if kind not in KINDS:
        raise ValueError("unknown kind of result")
    record.setdefault("id", new_id())
    record.setdefault("started", datetime.now().astimezone().isoformat(timespec="seconds"))
    record.setdefault("version", code_version())
    with _lock:
        _write(folder() / kind / f"{record['id']}.json", record)
        for old in _files(kind)[KEEP[kind]:]:
            old.unlink(missing_ok=True)
    return record["id"]


def runs(kind: str) -> list[dict]:
    return [r for r in (_read(p) for p in _files(kind)) if isinstance(r, dict)]


def load(kind: str, run_id: str) -> dict | None:
    if kind not in KINDS or not _ID.fullmatch(run_id or ""):
        return None
    found = _read(folder() / kind / f"{run_id}.json")
    return found if isinstance(found, dict) else None


def marks() -> dict:
    """"<run id>/<item id>" -> verdict."""
    found = _read(folder() / "marks.json")
    return found if isinstance(found, dict) else {}


def set_mark(run_id: str, item_id: str, verdict: str) -> bool:
    """A hand check of one live test answer; "" removes it. False when there is no such answer."""
    run = load("live", run_id)
    if run is None or not _ITEM.fullmatch(item_id or "") \
            or not any(i.get("id") == item_id for i in run.get("items") or []):
        return False
    with _lock:
        kept = {k: v for k, v in marks().items() if load("live", k.split("/")[0]) is not None}
        if verdict:
            kept[f"{run_id}/{item_id}"] = verdict
        else:
            kept.pop(f"{run_id}/{item_id}", None)
        _write(folder() / "marks.json", kept)
    return True
