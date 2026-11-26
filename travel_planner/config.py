"""Central configuration: caps, strategy levels, routing table, env helpers.

Everything tunable lives here so behaviour is easy to audit.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# ---- control-flow caps -------------------------------------------------------
MAX_AUTO_REPLANS = 2          # budget/critic driven replans (shared counter)
MAX_REVISIONS = 2             # human "request changes" rounds
STRATEGIES = ("normal", "cheaper", "cheapest")

# ---- input limits ------------------------------------------------------------
MAX_REQUEST_CHARS = 1000
MIN_DAYS = 2
MAX_DAYS = 14
MAX_TRAVELERS = 10
MIN_BUDGET = 3000
MAX_BUDGET = 10_000_000

# ---- itinerary / weather -----------------------------------------------------
FORECAST_WINDOW_DAYS = 16     # Open-Meteo forecast horizon; beyond -> climate
RAIN_THRESHOLD = 60           # precip probability (%) at/above which a day is "rainy"
MAX_ACTIVITIES_PER_DAY = 4

# ---- cost model (INR, estimated) ---------------------------------------------
FOOD_PER_PERSON_DAY = {"normal": 1200, "cheaper": 800, "cheapest": 550}
FOOD_BOOST = 1.25
ACTIVITY_COST_CAP = {"normal": None, "cheaper": 800, "cheapest": 300}   # per person

# ---- tool resilience ---------------------------------------------------------
TOOL_RETRIES = 3
TOOL_BACKOFF_BASE = 0.2       # seconds; doubles each attempt

# ---- LLM ---------------------------------------------------------------------
# role -> provider fallback chain. Rule-based code is always the last resort.
LLM_ROUTING = {
    "intake": ["groq", "gemini", "ollama"],
    "activities": ["groq", "gemini", "ollama"],
    "writer": ["gemini", "groq", "ollama"],
}
LLM_RETRIES = 3               # attempts per provider on 429/5xx/timeout
LLM_BACKOFF_BASE = 0.5
LLM_COOLDOWN = 60.0            # seconds a provider is skipped after it failed all its attempts (429/5xx/timeout)
LLM_TIMEOUT = 20
HTTP_USER_AGENT = "travel-planner/1.0 (local learning project)"
LLM_RUN_TOKEN_BUDGET = 20_000     # rough per-run ceiling (prompt+completion estimate)
LLM_DAILY_CALL_LIMIT = 200        # per provider; stay under free tiers (verify in consoles)

PROVIDERS = {
    # name: (base_url, api-key env var, model env var, default model)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
               "GEMINI_MODEL", "gemini-3.8-flash"),
    "ollama": ("http://localhost:11434/v1", "OLLAMA_ENABLED", "OLLAMA_MODEL", "llama3.1"),
}


# ---- env helpers -------------------------------------------------------------
def load_env(path: str | os.PathLike | None = None) -> None:
    """Minimal .env loader (no dependency). Existing environment wins."""
    p = Path(path) if path else Path.cwd() / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.lower().startswith("export "):
            k = k[7:].strip()
        os.environ.setdefault(k, _parse_env_value(v))


def _parse_env_value(raw: str) -> str:
    """Value part of a .env line: quoted values are taken verbatim, unquoted
    values lose a trailing ' # comment'."""
    raw = raw.strip()
    if raw[:1] in ('"', "'"):
        end = raw.find(raw[0], 1)
        return raw[1:end] if end != -1 else raw[1:]
    m = re.search(r"\s#", raw)
    if m:
        raw = raw[:m.start()]
    return raw.strip()


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def real_data_enabled() -> bool:
    """Open-Meteo / OSM / Wikivoyage lookups (always fall back to offline data)."""
    return env_bool("REAL_DATA", True)


def tavily_key() -> str:
    return os.environ.get("TAVILY_API_KEY", "").strip()


def live_prices_enabled() -> bool:
    """Live flight and hotel prices need the Tavily key, internet access (REAL_DATA) and LIVE_PRICES not switched off."""
    return real_data_enabled() and bool(tavily_key()) and env_bool("LIVE_PRICES", True)


def _env_number(name: str, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def live_daily_credits() -> int:
    """Tavily credits the planner may spend per day (a page read costs 2; the free plan has ~33 a day)."""
    return int(_env_number("LIVE_DAILY_CREDITS", 30, 0, 100_000))


def live_cache_hours() -> float:
    return _env_number("LIVE_CACHE_HOURS", 3, 0, 72)


def auth_required() -> bool:
    """AUTH_REQUIRED=1: only signed-in users may plan. Off by default so guests can use the planner."""
    return env_bool("AUTH_REQUIRED", False)


def rate_limits_enabled() -> bool:
    return env_bool("RATE_LIMIT", True)


def rate_limit(name: str, default: int) -> int:
    return int(_env_number(f"RATE_LIMIT_{name}", default, 1, 1_000_000))


def tools_mode() -> str:
    return os.environ.get("TOOLS_MODE", "inprocess").strip().lower()   # inprocess | mcp


def ask_travel_mode() -> bool:
    """Ask "flight, train, bus, car or bike?" when a request does not say. ASK_TRAVEL_MODE=0 turns it off."""
    return os.environ.get("ASK_TRAVEL_MODE", "1").strip().lower() not in ("0", "false", "no", "off")


def db_path() -> str:
    return os.environ.get("TRIP_DB", "travel_planner.db")
