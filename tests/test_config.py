"""The .env loader must cope with the shipped template (inline comments) and quoting."""
import os

import pytest

from travel_planner import config

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
