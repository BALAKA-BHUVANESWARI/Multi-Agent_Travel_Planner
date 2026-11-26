"""The .env loader must cope with the shipped template (inline comments) and quoting."""
import os

import pytest

from app.core import config, tracing
from app.core.config import load_env as real_load_env  # taken before conftest guards it

NAMES = ("ENGINE", "TOOLS_MODE", "REAL_DATA", "GROQ_API_KEY", "GEMINI_API_KEY", "PLAIN", "EMPTY", "EXPORTED")


@pytest.fixture(autouse=True)
def _restore_environ():
    """load_env writes to os.environ; undo everything so other tests never see it."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _load(tmp_path, monkeypatch, text):
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)
    f = tmp_path / ".env"
    f.write_text(text, encoding="utf-8")
    config.load_env(f)


def test_inline_comments_are_stripped(tmp_path, monkeypatch):
    _load(tmp_path, monkeypatch,
          "ENGINE=auto            # auto | langgraph | runner\n"
          "TOOLS_MODE=inprocess   # inprocess | mcp\n"
          "REAL_DATA=1            # 1 = real data\n")
    assert os.environ["ENGINE"] == "auto"
    assert config.tools_mode() == "inprocess"
    assert config.real_data_enabled() is True


def test_quotes_hash_and_blank_values(tmp_path, monkeypatch):
    _load(tmp_path, monkeypatch,
          'GROQ_API_KEY="gsk_abc#123"   # quoted keeps its hash\n'
          "GEMINI_API_KEY='AQ.key'\n"
          "PLAIN=abc#def\n"
          "EMPTY=\n"
          "export EXPORTED=yes\n")
    assert os.environ["GROQ_API_KEY"] == "gsk_abc#123"
    assert os.environ["GEMINI_API_KEY"] == "AQ.key"
    assert os.environ["PLAIN"] == "abc#def"      # '#' without a space before it is part of the value
    assert os.environ["EMPTY"] == ""
    assert os.environ["EXPORTED"] == "yes"


def test_existing_environment_wins_and_bom_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE", "runner")
    f = tmp_path / ".env"
    f.write_bytes("﻿ENGINE=langgraph\nTOOLS_MODE=mcp\n".encode("utf-8"))
    monkeypatch.delenv("TOOLS_MODE", raising=False)
    config.load_env(f)
    assert os.environ["ENGINE"] == "runner"
    assert os.environ["TOOLS_MODE"] == "mcp"


def test_files_the_app_writes_go_into_the_runtime_folder_wherever_it_is_started(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for value in (None, "", "travel_planner.db"):             # unset, empty, and the old .env.example line
        if value is None:
            monkeypatch.delenv("TRIP_DB", raising=False)
        else:
            monkeypatch.setenv("TRIP_DB", value)
        assert config.db_path() == str(config.RUNTIME_DIR / "travel_planner.db")
    monkeypatch.setenv("TRIP_DB", ":memory:")
    assert config.db_path() == ":memory:"
    monkeypatch.setenv("TRIP_DB", str(tmp_path / "x.db"))
    assert config.db_path() == str(tmp_path / "x.db")
    monkeypatch.setenv("TRACE_FILE", "traces.jsonl")
    assert tracing.trace_path() == str(config.RUNTIME_DIR / "traces.jsonl")
    monkeypatch.setenv("TRACE_FILE", "off")
    assert tracing.trace_path() is None


def test_the_env_file_at_the_top_of_the_project_is_found_from_any_folder(monkeypatch, tmp_path):
    assert (config.PROJECT_ROOT / "backend" / "app" / "core" / "config.py").is_file()
    root, elsewhere = tmp_path / "project", tmp_path / "elsewhere"
    root.mkdir()
    elsewhere.mkdir()
    (root / ".env").write_text("PLAIN=from-the-project\n")
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("PLAIN", raising=False)
    real_load_env()
    assert os.environ["PLAIN"] == "from-the-project"
