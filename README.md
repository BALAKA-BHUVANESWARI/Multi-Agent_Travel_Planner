# AI Multi-Agent Travel Planner

Ask for a trip in plain language. A team of agents (built on **LangGraph** and **MCP**) returns a day-by-day
itinerary with a flight, a hotel and a budget breakdown. **You approve the plan before anything is "booked"**
(and the booking is a mock). It costs nothing to run: free LLM tiers, free data APIs, local-first, SQLite.

> "Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2, love beaches and food"

The normal tier comes to ₹63,500, so the Budget agent sends it back to the Supervisor, which re-plans on the
"cheaper" tier (₹46,500). The Critic checks it, and you get an approval screen.

## Trip guide: top sights and where to eat

Every plan also includes:

* **Top sights**: the most prominent places (historical, waterfalls, beaches, spiritual, viewpoints...) ranked, each with a
  label and a good time to visit (waterfalls also get a season note). Far day trips are left out of the ranking.
* **Where to eat**: top restaurants split into **vegetarian** and **non-vegetarian** (places that serve both appear in
  both), with opening hours as listed, or a typical lunch/dinner window marked "not stated: check before you go".
  Places whose diet is not stated appear under "menu not specified".

Free sources have no star ratings, so "top" means *most prominent* (traveller-listed on Wikivoyage, Wikidata/Wikipedia
entry, website, stated hours), and the plan says so. Tool: `search_dining`.

## What it demonstrates

LangGraph orchestration, supervisor pattern, parallel fan-out/join, shared typed state, conditional routing,
guardrails, human-in-the-loop (`interrupt()` + durable checkpoints), MCP tools, tool calling, retries and
graceful degradation, multi-provider LLM fallback, response caching and token budgets, evals with a baseline.

## Quick start

```bash
python -m venv .venv            # tip: put it on a drive with space, e.g. D:\...\.venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # optional: add GROQ_API_KEY / GEMINI_API_KEY

python -m pytest                # unit + scenario + MCP tests (graph/API tests included once installed)
python -m travel_planner "Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2"
python -m uvicorn travel_planner.api:create_app --factory --reload   # UI at http://127.0.0.1:8000
# 'uvicorn' not found (Windows PATH)? always use `python -m uvicorn`.
# no FastAPI at all? the same API + UI run on the stdlib:  python -m travel_planner.devserver
python evals/run_evals.py       # writes evals/report.md
```

**Windows without a terminal:** double-click `install_requirements.bat` once, then `run_server.bat` (opens the app; if
port 8000 is stuck it tells you and uses 8001) and `run_tests.bat` (`plan_trip.bat` runs the CLI). `diagnose.bat` writes `diagnose.txt` with the Python
setup and what is using port 8000, which is what to send when something does not start.

It works with **no keys at all** (rule-based mode). Keys only add LLM polish: better intake of unusual phrasing,
preference re-ranking of activities, and a friendlier written overview.

## How it works

```
START -> Input Guardrail -(blocked)-> END
      -> Intake (text -> constraints) -(missing info)-> END
      -> Supervisor -> [ Flight | Hotel | Weather | Activities ]  (parallel) -> Merge
      -> Budget -(over budget, retries < 2)-> Supervisor (cheaper strategy)
      -> Critic -(blocking issue, retries < 2)-> Supervisor
      -> Present -> Human Approval (interrupt) -(changes, revisions < 2)-> Supervisor
                                               -(approved)-> Book (mock, idempotent) -> Writer -> END
```

**Principle: hard constraints stay in deterministic code.** Money, dates and overlaps are plain Python; the LLM only
handles language and soft preferences, always with a rule-based fallback, schema validation, and a check that any
rupee amount it writes is one of the plan's own numbers.

| Part | Where | Notes |
|---|---|---|
| Shared state | `state.py` | One typed `TripState`; workers write separate keys; only `log`/`warnings` use reducers |
| Nodes | `agents.py` | All agents; `fn(state, deps) -> update` |
| Routers | `routing.py` | Pure functions, shared by LangGraph and the runner |
| LangGraph wiring | `graph.py` | Fan-out/join, `interrupt()`, SQLite checkpointer |
| Dependency-free runner | `runner.py` | Same nodes/routers; thread-pool fan-out; resumes from SQLite |
| Tools | `tools/impl.py` | In-process, or via the MCP server (`TOOLS_MODE=mcp`) |
| LLM routing | `llm/router.py` | groq -> gemini -> ollama -> rules; backoff on 429/5xx/timeout; cache; budgets |
| Guardrails | `guardrails.py` | Injection, card/OTP/ID numbers, off-topic, length; tool text is sanitised |
| Output checks | `checks.py` | Every price traces to a tool result; totals add up |
| API / UI | `api.py`, `devserver.py`, `static/index.html` | `POST /api/plan`, `POST /api/approve/{id}`, `GET /api/plan/{id}`, `GET /api/health` |

Approving over the API: `POST /api/approve/{thread_id}` with `{"action": "approve" | "revise" | "cancel", "feedback": ""}`
(`feedback` is the change request when the action is `revise`).

Details: [`docs/architecture.md`](docs/architecture.md), [`docs/decisions.md`](docs/decisions.md).

## Control flow in numbers

* Automatic re-plans (budget or critic): at most **2**, then the plan is shown with a visible warning.
* Human "request changes" rounds: at most **2**, then you can only approve or cancel.
* Strategy ladder: `normal` (3-star, best-value flight) -> `cheaper` (2-star, early/late nonstop, activities <= ₹800 pp)
  -> `cheapest` (budget stay, one-stop fare, activities <= ₹300 pp).
* Feedback understood: "make it cheaper", "budget 50000", "more food/culture/adventure…", "relaxed pace".

## Data sources and honesty

| Data | Source | Label |
|---|---|---|
| Weather | **Open-Meteo** (no key, non-commercial, attribution shown). Forecast when the whole trip is within 16 days, otherwise historical climate from the same dates in the last 3 years. Offline: monthly averages | source shown per plan |
| Any place you name | Resolved in this order: 5 curated destinations + 14 origin cities -> built-in list of ~190 popular places -> **Open-Meteo geocoding** (free, no key, GeoNames data). A name nobody knows is never guessed: the planner asks again. Regions and countries ("Kerala", "Japan") ask for a specific city or town | source shown in the log |
| Places (curated) | Goa, Jaipur, Manali, Kochi, Udaipur: hand-written list with **estimated** entry prices | "estimated" |
| Places (any other destination) | Four free sources asked at the same time and merged by name: **Wikivoyage** "See"/"Do" listings (best for small towns), **OpenStreetMap** (Overpass; wikidata/heritage/tourism tags), **Wikipedia** nearby articles (kind taken from the Wikidata description; stubs ignored) and the Wikivoyage page text for tips. A notability score ranks them and a per-kind cap keeps the list varied. Sights 7 km or more from the town centre (by a distance in the Wikivoyage listing, its coordinates, or a Wikipedia position looked up by name) are marked **day trips** and always rank after nearby sights. None of them has prices, so entry fees are **estimated** from the kind of place and the country's price level. Each lookup is cached on disk for 30 days (`.place_cache/`), and the shared Overpass server gets a short time budget with mirror fallback because it is often at capacity. If every source fails the plan uses clearly generic suggestions (walking tour, market, dinner) and says so in a warning | "estimated" + warning |
| Restaurants | **Wikivoyage** "Eat" listings (best for small towns) + **OpenStreetMap** restaurants (diet and cuisine tags). Ranked by prominence, not stars. No prices, so meals are covered by the food allowance | "estimated" + note |
| Tips / knowledge | Wikivoyage text -> local TF-IDF vector store (CC BY-SA, attributed) | attributed |
| Nearby ideas | OpenStreetMap via Overpass (ODbL). **No prices exist, so these never enter the itinerary or budget** | "no prices" |
| Flights, trains and hotels | **Synthetic estimator** (great-circle distance, season, country price level; no free real API exists). Under 300 km it prices a train/bus instead of a flight; international trips get higher per-km fares, long-haul (> 9,000 km) gets one-stop options only. Hotels scale with the country's price level and city size | "estimated" everywhere |
| Booking | Mock tool with an idempotency key; nothing is purchased | "MOCK" everywhere |

Free-tier limits change often: check each provider's console. The router has a per-run token ceiling and a
per-provider daily call counter (`config.py`) so you never hit a limit unexpectedly.
A provider that fails all its retries (429, 5xx, timeout) is skipped for 60 s (`LLM_COOLDOWN`), so an overloaded
free tier costs one slow call, not one per step; a bad answer or a bad key never triggers the cool-down.

## Testing

`pytest` covers intake parsing, guardrails, estimators, budget math, routers, and scenarios: generous budget,
tight budget (exact retry counts), impossible budget (warning), rainy month (indoor swaps), tool outage and
transient failure with backoff, rejection with feedback, revision cap, guardrail block, missing info, restart
and resume, idempotent booking, concurrency (the 4 workers' tool calls overlap in time), MCP vs in-process parity,
and LLM fallback (forced 429, invalid JSON, cache, budgets, number grounding).
`tests/test_graph_engine.py` checks that the LangGraph graph and FastAPI app behave exactly like the runner.
The test suite is offline and repeatable by design: an autouse fixture fails any test that calls a non-local host,
and tests ignore your real `.env` (keys and `REAL_DATA`), so running `pytest` never spends free-tier calls.

## Tracing: time and cost per run

Every `/api/plan` and `/api/approve` response carries a `metrics` object, and the UI shows it under the agent log:
total seconds, the time each agent took (and the slowest one), tool calls and failures, LLM calls, cache hits,
fallbacks, estimated tokens and automatic replans. Cost is always **$0** because every service is a free tier, so the
numbers that matter are call counts and the token estimate (what free-tier limits are measured in). Each run is
also appended as one JSON line to `traces.jsonl` (set `TRACE_FILE=other.jsonl` to move it, `TRACE_FILE=off` to
disable). Timings come from one wrapper that both engines (LangGraph and the runner) register their nodes through, so
they mean the same in either. Tool and LLM counters are before/after deltas: exact for one request at a time,
approximate when requests overlap. Langfuse is not used: it would add an account and a dependency for a local project.

On Windows, double-click `run_tests.bat` for the tests and `run_evals.bat` for the evals including the LLM judge
(the judge needs your keys in `.env`; it makes about one free-tier call per prompt that states preferences).

## Known limitations

* Flight and hotel prices are estimates, not live fares. Curated place prices are approximate.
* Any city or town can be planned, but quality varies: the 5 curated destinations are hand-checked; elsewhere the
  sights come from OpenStreetMap and costs are rough estimates. International trips show a warning because visas,
  insurance and currency costs are not included. All money is shown in INR.
* Place supply is finite: long trips on the `cheapest` tier may leave a few slots empty (a warning says so).
* Restaurants: for big cities split into districts (Paris) the list comes from the first district pages on Wikivoyage; the public OpenStreetMap server is slow (about 40 s) and runs in the background, so its extra places may only appear on a repeat plan. Hours are as listed on the source; places without a stated diet appear under "menu not specified".
* Open-Meteo is for non-commercial use; keep the attribution.
* The mock booking cannot be undone or modified because nothing real happens.

## Demo

See [`docs/demo.md`](docs/demo.md) for a 3-minute walkthrough script (a recording was not produced here).
