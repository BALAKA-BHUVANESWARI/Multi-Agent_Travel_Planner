"""Optional voice test. It sends your recordings to the app's voice service (Groq Whisper) with your key.

    python evals/run_voice_test.py --list     # the sentences to read out and where to put the files

1. Record each sentence as its own file named by its number: 01.m4a, 02.m4a ... (mp3, wav, webm, ogg also work).
2. Put the files in the folder .runtime/voice_test at the top of the project.
3. python evals/run_voice_test.py

The words heard are printed here only. The dashboard gets pass or fail for places, numbers and dates, never the
words or the sound. Each recording counts toward the daily voice limit (VOICE_DAILY_LIMIT, default 100).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config  # noqa: E402
from app.database.repositories import Store  # noqa: E402
from app.evaluation import results, voice  # noqa: E402
from app.services import speech_service  # noqa: E402

WORDS = {"pass": "ok", "fail": "PROBLEM", "no_answer": "not transcribed", "not_recorded": "no file",
         "not_run": "not run"}


def show(item: dict, heard: str) -> None:
    print(f"  {item['id']}  {WORDS[item['status']]}" + (f": {'; '.join(item['problems'])}" if item["problems"] else ""))
    if heard:
        print(f"      heard: {heard}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Voice test (uses your Groq key).")
    ap.add_argument("--list", action="store_true", help="show the sentences; send nothing")
    ap.add_argument("--folder", help="where the recordings are (default: .runtime/voice_test)")
    args = ap.parse_args()
    folder = Path(args.folder) if args.folder else Path(config.runtime_path(None, "voice_test"))
    sentences = voice.load_sentences()
    if args.list:
        folder.mkdir(parents=True, exist_ok=True)
        print(f"Record each sentence as its own file (01.m4a, 02.m4a ...) and put the files in:\n  {folder}\n")
        for s in sentences:
            print(f"  {s['id']}  {s['say']}")
        print("\nNothing was sent.")
        return 0
    config.load_env()
    if not speech_service.available():
        print("The voice test needs GROQ_API_KEY in .env.")
        return 2
    if not any(voice.recording_for(folder, s["id"]) for s in sentences):
        print(f"No recordings found in {folder}. Run with --list to see what to record.")
        return 2
    store = Store(config.db_path())
    try:
        record = voice.run(folder, store=store, on_item=show)
    finally:
        store.close()
    found = record["summary"]
    print(f"\n{found['passed']} of {found['heard']} recordings read fully right.")
    for name, g in found["groups"].items():
        if g["checked"]:
            print(f"  {name}: {g['right']} of {g['checked']}")
    if found["heard"]:
        print(f"Saved (pass or fail only) in {results.folder() / 'voice'}. You can delete the recordings now.")
    return 0 if found["heard"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
