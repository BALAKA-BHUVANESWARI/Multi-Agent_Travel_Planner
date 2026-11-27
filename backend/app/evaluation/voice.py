"""The voice test: the owner records about ten fixed sentences; each recording goes through the app's voice input,
and the places, numbers and dates the planner reads from the words are compared with the sentence that was read out.

Only pass or fail per detail is saved. The recordings stay where the owner put them, and the words heard are
shown on the screen only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from app.evaluation import results
from app.evaluation.live import TODAY
from app.services import request_parser as parser
from app.services import speech_service

SENTENCES_PATH = Path(__file__).resolve().parents[2] / "evals" / "voice_sentences.json"
SUFFIXES = {".m4a": "audio/m4a", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".webm": "audio/webm",
            ".ogg": "audio/ogg", ".flac": "audio/flac", ".mp4": "audio/mp4"}
GROUPS = {"places": ("origin", "destination"), "numbers": ("days", "budget", "travelers"),
          "dates": ("start_date",), "travel mode": ("travel_mode",)}


def load_sentences(path: Path = SENTENCES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def recording_for(folder: Path, sentence_id: str) -> Path | None:
    """01.m4a, 01.wav and so on."""
    if not folder.is_dir():
        return None
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.stem == sentence_id and path.suffix.lower() in SUFFIXES:
            return path
    return None


def check_words(heard: str, expect: dict) -> dict:
    """field -> True when the planner reads the expected value from these words."""
    read = parser.parse_request(heard, TODAY)["constraints"]
    return {field: read.get(field) == value for field, value in expect.items()}


def summarise(items: list[dict]) -> dict:
    done = [i for i in items if i["status"] in ("pass", "fail")]
    out = {"sentences": len(items), "heard": len(done), "passed": sum(i["status"] == "pass" for i in done), "groups": {}}
    for name, fields in GROUPS.items():
        checks = [ok for i in done for f, ok in i["fields"].items() if f in fields]
        out["groups"][name] = {"right": sum(checks), "checked": len(checks)}
    return out


def run(folder: Path, *, env=None, store=None, transport: Callable | None = None, sentences: list | None = None,
        on_item: Callable[[dict, str], None] = lambda item, heard: None, save: bool = True) -> dict:
    """``on_item(item, words heard)``: the words are passed on for the screen and kept nowhere."""
    record = {"id": results.new_id(), "items": [], "summary": {}, "finished": False}
    stopped = ""
    for sentence in sentences or load_sentences():
        item = {"id": sentence["id"], "say": sentence["say"], "fields": {}, "problems": []}
        heard = ""
        path = recording_for(folder, sentence["id"])
        if path is None:
            item.update(status="not_recorded")
        elif stopped:
            item.update(status="not_run", problems=[stopped])
        else:
            try:
                heard = speech_service.transcribe(path.read_bytes(), SUFFIXES[path.suffix.lower()], env=env,
                                                  store=store, transport=transport)
            except speech_service.SpeechError as e:
                item.update(status="no_answer", problems=[e.message])
                if e.status in (429, 503):                 # no key, key refused or limit used up: the rest would fail too
                    stopped = e.message
            else:
                item["fields"] = check_words(heard, sentence["expect"])
                wrong = [f for f, ok in item["fields"].items() if not ok]
                item.update(status="fail" if wrong else "pass",
                            problems=["read differently: " + ", ".join(f.replace("_", " ") for f in wrong)] if wrong else [])
        record["items"].append(item)
        record["summary"] = summarise(record["items"])
        on_item(item, heard)
    record["finished"] = True
    if save and record["summary"]["heard"]:
        results.save("voice", record)
    return record
