import os
import sys
from datetime import date
from pathlib import Path

# Tests are offline and key-less by default.
os.environ["REAL_DATA"] = "0"
for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "OLLAMA_ENABLED", "BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE",
          "TAVILY_API_KEY"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # the backend folder

import json  # noqa: E402

import pytest  # noqa: E402

from app.database.repositories import Store  # noqa: E402
from app.graph.deps import Deps  # noqa: E402
from app.graph.runner import Planner  # noqa: E402
from app.services.llm_service import LLMRouter  # noqa: E402
from app.tools.client import InProcessClient  # noqa: E402

TODAY = date(2026, 11, 24)


@pytest.fixture(autouse=True)
def _ignore_real_dotenv(monkeypatch):
    """The CLI and API start-up read ./.env. Tests must never pick up a developer's real keys or REAL_DATA=1,
    so only an explicit path (used by tests/test_config.py) is honoured."""
    from app.core import config
    real = config.load_env

    def guarded(path=None):
        if path is not None:
            real(path)
    monkeypatch.setattr(config, "load_env", guarded)


@pytest.fixture(autouse=True)
def _no_internet(monkeypatch):
    """Tests must be offline and repeatable: a call to any non-local host fails the test that made it.
    (Code under test swallows network errors by design, so without this a leak would go unnoticed here
    and only show up on a machine that is online.)"""
    import urllib.parse
    import urllib.request
    real = urllib.request.urlopen
    leaks = []

    def guard(req, *a, **k):
        url = getattr(req, "full_url", req)
        if urllib.parse.urlparse(url).hostname not in ("127.0.0.1", "localhost", "::1"):
            leaks.append(url)
            raise OSError(f"tests must not use the network: {url}")
        return real(req, *a, **k)
    monkeypatch.setattr(urllib.request, "urlopen", guard)
    yield
    assert not leaks, f"test made real network calls: {leaks}"


@pytest.fixture(autouse=True)
def _isolated_place_cache(tmp_path, monkeypatch):
    """Place lookups are cached on disk: keep tests away from the real cache and from each other."""
    from app.integrations import openstreetmap as osm
    monkeypatch.setenv("TRIP_CACHE_DIR", str(tmp_path / "place_cache"))
    monkeypatch.setenv("TRACE_FILE", str(tmp_path / "traces.jsonl"))
    osm._PLACES_CACHE.clear()
    osm._FAILED.clear()
    yield
    osm._PLACES_CACHE.clear()
    osm._FAILED.clear()


@pytest.fixture
def make():
    """Planner factory: make(tools=..., env=..., transport=..., db=..., nodes=...)."""
    def _make(tools=None, env=None, db=":memory:", transport=None, nodes=None, today=TODAY):
        store = Store(db)
        llm = LLMRouter(env=env or {}, store=store, transport=transport, sleep=lambda s: None)
        deps = Deps(tools=tools or InProcessClient(), store=store, llm=llm, today=today, sleep=lambda s: None)
        return Planner(deps, nodes=nodes)
    return _make


class FakeTransport:
    """Scriptable LLM transport. handlers: {url_substring: callable(body) -> (status, content_obj|str)}"""

    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append(url)
        for sub, fn in self.handlers.items():
            if sub in url:
                status, content = fn(body)
                if status != 200:
                    return status, {}
                if not isinstance(content, str):
                    content = json.dumps(content)
                return 200, {"choices": [{"message": {"content": content}}]}
        return 404, {}

    def count(self, sub):
        return sum(1 for u in self.calls if sub in u)


@pytest.fixture
def fake_transport():
    return FakeTransport


@pytest.fixture(autouse=True)
def _no_wikipedia_coordinate_lookup(monkeypatch):
    """Looking up listing coordinates is a live Wikipedia call; tests that want it pass their own fetch."""
    from app.integrations import wikivoyage
    monkeypatch.setattr(wikivoyage, "_fetch_coords", lambda titles, timeout=6.0: {})


@pytest.fixture(autouse=True)
def _no_live_restaurant_lookup(monkeypatch):
    """Restaurant suggestions call Wikivoyage and Overpass live; tests that want them pass fake data."""
    from app.integrations import openstreetmap as osm
    from app.integrations import wikivoyage
    monkeypatch.setattr(wikivoyage, "eat_listings", lambda title, fetch=None: [])
    monkeypatch.setattr(osm, "restaurant_elements", lambda lat, lon, radius_m, post=None: [])
