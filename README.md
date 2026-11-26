# AI Multi-Agent Travel Planner

Ask for a trip in plain language. A team of agents (built on **LangGraph** and **MCP**) returns a day-by-day
itinerary with a flight, a hotel and a budget breakdown. **You approve the plan before anything is "booked"**
(and the booking is a mock). It costs nothing to run: free LLM tiers, free data APIs, local-first, SQLite.

> "Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2, love beaches and food"

The normal tier comes to ₹63,500, so the Budget agent sends it back to the Supervisor, which re-plans on the
"cheaper" tier (₹46,500). The Critic checks it, and you get an approval screen.

## Choose how you travel

If your request does not say, the planner first asks: **flight, train, bus, car or bike?** Each option shows an
estimated round-trip price per person and the travel time. **You decide, however far it is:** train, bus, car and bike can be chosen whenever there is a land route.
Click one (or "any mode") and the agents plan **only that mode**: the schedule, budget and summary use it, with no
airport steps on a road trip. You can also say it up front: *"4 days in Jaipur from Delhi by train, 60k for 2"*.
Overland journeys are estimated from the straight-line distance (x1.25 for roads) and cars and bikes are shared per
vehicle. Long journeys start before the first day so you arrive in the morning (a train from Delhi to Goa leaves two
days before). Cars and bikes are split into days of about 10 hours, setting off in the morning with night halts that are
priced in; a rented bike is charged for the days on the road too.

A long journey is **warned about, not refused**. The choice card and the plan show when you must leave and when you get
home, with a warning if the ride is very long (above about 40 h by train, 32 h by bus, 45 h by car or 56 h by bike), if
the extra travel days are at least as many as the trip, or if the departure date has already passed. Delhi to
Pondicherry by bike, for example, adds 10 days of travel to a 4-day trip. Meals on the way are not in the budget.
Overland travel is unavailable only where it makes no sense: across the sea (Andaman, Lakshadweep, Sri Lanka and other
islands in the list in `tools/transport.py`, which is not complete) or more than 1,500 km between countries.

If you are signed in, your usual way of travelling is highlighted on the choice screen; you are still asked.
Set `ASK_TRAVEL_MODE=0` to switch the question off (the planner then picks a flight, or train/bus for short trips).

## Live flight and hotel prices (optional)

With a free **Tavily** key in `.env` (`TAVILY_API_KEY`, 1,000 credits a month, no card) the flight and hotel agents read the
**Google Flights** and **Google Hotels** result pages for your exact dates and travellers, and use those numbers instead
of the estimator's. Each price on screen carries a green **live** badge with its source and fetch time; anything the
agents could not read stays an **estimated** price, with a warning that says why.

* **Flights:** Google's total for all adults (taxes and fees included) divided by the travellers. The three tiers are
  real listed flights: Google's own top pick (normal), the cheapest nonstop below it (cheaper) and the cheapest fare
  overall (cheapest). Google shows no return times until you pick the outbound flight, so the plan assumes a
  late-afternoon return (about 17:00) and says so. Flights that land the next day are skipped.
* **Any place:** known cities use airport codes; any other place is searched by name and Google picks the airport.
* **Hotels:** the price for your dates, per room per night for two guests, taxes and fees included. Tavily's reader
  sees Google Hotels in US dollars, so prices are converted to rupees at the day's rate (free Frankfurter API, ECB data)
  and the conversion is shown. Tiers: normal = a mid-priced hotel, cheaper = a lower-quartile one, cheapest = the
  lowest-priced hotel rated 3.8 or more.
* **Cost control:** a page read costs 2 credits, so a live plan costs 4. Pages are cached for 3 hours (a replan to a cheaper
  tier costs nothing) and `LIVE_DAILY_CREDITS` (default 30) caps the spend per day. The travel-mode choice cards never
  spend credits. `LIVE_PRICES=0` switches live prices off.
* **Never blocks a plan:** no key, `REAL_DATA=0`, an error, a rate limit, an empty page or prices for other dates or
  another currency all fall back to the estimator.

Run `python -m travel_planner.tools.live_probe` once to see what the providers return; `live_probe/` is git-ignored.

## Trip guide: top sights and where to eat

Every plan also includes:

* **Top sights**: the most prominent places (historical, waterfalls, beaches, spiritual, viewpoints...) ranked, each with a
  label and a good time to visit (waterfalls also get a season note). Far day trips are left out of the ranking.
* **Where to eat**: top restaurants split into **vegetarian** and **non-vegetarian** (places that serve both appear in
  both), with opening hours as listed, or a typical lunch/dinner window marked "not stated: check before you go".
  Places whose diet is not stated appear under "menu not specified".

Free sources have no star ratings, so "top" means *most prominent* (traveller-listed on Wikivoyage, Wikidata/Wikipedia
entry, website, stated hours), and the plan says so. Tool: `search_dining`.

## Suggestions, changes, groups, accounts and the map

| Feature | How it works |
|---|---|
| Destination suggestions | Leave the destination out ("Suggest a 4 day beach trip from Delhi in January, budget 70k for 2"). A hand-tagged list of about 50 places is priced with the estimator and ranked by interests, season and budget. No Tavily credits are used. Add "abroad" or "in India" to narrow it. |
| Alternative destinations | Every plan lists up to 3 other places for the same dates and group, with estimated totals compared like for like. |
| Conversational changes | "make it 4 days", "add 1 person", "move it to January", "go by train", "change destination to Jaipur", "skip water sports", plus budget, cheaper, more food and relaxed pace. A change that is not possible is explained and does not use up a revision (limit: 2). Rules only, so unusual phrasing may not be understood. |
| Group preferences | Open "Planning for a group?" and give each person's likes and things to avoid. Activities take turns between people, places everyone wants to avoid are dropped, and "Group fit" shows how each person is served. A place only some want to avoid can still appear, and is listed. |
| Accounts and memory | Optional local accounts. A signed-in traveller gets "My trips" and saved defaults (home city, interests, travel mode, pace), learned from approved bookings or edited by hand. They only fill what a request does not say, and the plan says when they were used. The budget is never remembered. |
| Booking cancellation | Two steps: see the refund, then confirm. Booking, cancellation and the refund policy are all **mock**. |
| API rate limits | Per signed-in user or client address: 10 plans a minute and 200 a day, 30 actions a minute, 8 sign-in tries a minute. Over the limit returns HTTP 429 with `Retry-After`. |
| Interactive map | Leaflet with OpenStreetMap tiles, all days or one day. Needs internet access. Positions are approximate; stops with no fixed location and hotels are not plotted. |

New endpoints: `POST /api/booking/{thread_id}/cancel` (`{"confirm": true}`), `POST /api/auth/register|login|logout`,
`GET|DELETE /api/me`, `PUT|DELETE /api/me/memory`, `GET /api/trips`. `POST /api/plan` also accepts
`"group": [{"name": "Asha", "likes": ["history"], "avoid": ["nightlife"]}]`. Signed-in calls send
`Authorization: Bearer <token>`.

Settings (all optional): `AUTH_REQUIRED=1` stops guests from planning; `RATE_LIMIT=0` turns limits off;
`RATE_LIMIT_PLAN_PER_MINUTE`, `RATE_LIMIT_PLAN_PER_DAY`, `RATE_LIMIT_ACTIONS_PER_MINUTE`,
`RATE_LIMIT_AUTH_PER_MINUTE`, `RATE_LIMIT_READS_PER_MINUTE` change them.

**Agent names:** the "Destination Agent" is the `activities` node (places, tips and restaurants) and the
"Itinerary Agent" is `merge` (builds the days) plus `writer` (writes the summary).

## Trip toolkit

Five extras that work from a finished plan (the **Trip toolkit** card). They read the plan and never change it.
**🆘 Emergency help** at the top of the page also works with no plan. None of them uses an AI model.

| Feature | What you get | How it works and what it will not do |
|---|---|---|
| Travel companion | Packing list for this trip, local customs, currency, driving side, plug types, dialling code, plus Wikivoyage "Respect / Stay safe / Stay healthy" notes | The list comes from the trip's weather, planned activities, way of travelling and whether it is abroad. Customs and country facts are a hand-written reference, so check anything important. Wikivoyage notes need `REAL_DATA=1`. Packing ticks stay in your browser. |
| Emergency assistant | Emergency numbers (tap to call) and nearby hospitals, clinics, pharmacies and police | Numbers are stored with their sources and a checked date. An unlisted country, or a service that no source confirmed (fire in Belgium, Germany and the Maldives), gets **no number** rather than a guess. Places come from OpenStreetMap, may be incomplete, and need `REAL_DATA=1`. "Use my location" rounds the position, sends it to this server and the map service, and does not save it. |
| Document assistant | Checklist, passport date check, dated reminders, calendar (.ics) file, your own list of documents | It **never says whether you need a visa**: it links to where to check. The passport check applies the Schengen 3-month and 10-year rules, and flags under 6 months elsewhere as something to check. It **refuses passport, ID, licence and card numbers**; store only names and dates. Saving needs an account. Not legal advice. |
| Sustainable travel | Estimated kg CO₂e per person for flight, train, bus, car and bike, also on the travel choice cards | Published average factors multiplied by an estimated distance, for the trip there and back only (not the hotel or activities). Indian rail and road factors (CO₂ only) are used for trips from India to India, Nepal, Bhutan or Bangladesh; UK 2025 factors elsewhere and for flights and coaches. The sources differ in method, so treat gaps under about a quarter as a tie. |
| Post-trip expenses | Record what you spent, compare it with the planned budget by category, download CSV | Amounts are typed in rupees (no currency conversion, no receipt reading). Until the trip is over the view says "so far" and draws no under-budget conclusions. |

A guest's expenses are protected only by the trip id, like the guest's trip itself. Adding an expense or document
while signed in makes an unowned trip yours. Deleting your account deletes these records too.

New endpoints: `POST /api/emergency` (`{"place": "Bangkok", "nearby": true}`, `{"lat": 15.4, "lon": 73.8}` or
`{"thread_id": "..."}`; never needs sign-in) and `GET /api/trip/{thread_id}/{companion|emergency|documents|footprint|expenses}`,
`POST /api/trip/{thread_id}/expenses`, `POST /api/trip/{thread_id}/documents` (also `/documents/passport-check` and
`/documents/tick`), `DELETE /api/trip/{thread_id}/{expenses|documents}/{id}`. New MCP tools: `find_help_nearby`,
`local_tips`.

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
| Flights and hotels (live) | **Google Flights / Google Hotels** pages read through **Tavily Extract** (needs `TAVILY_API_KEY`); hotel dollars converted with **Frankfurter** (ECB rates). See "Live flight and hotel prices" | "live" badge, source and fetch time |
| Flights, trains and hotels (fallback, and trains/buses/cars/bikes always) | **Synthetic estimator** (great-circle distance, season, country price level; no free real API exists). Under 300 km it prices a train/bus instead of a flight; international trips get higher per-km fares, long-haul (> 9,000 km) gets one-stop options only. Hotels scale with the country's price level and city size | "estimated" everywhere |
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

The new LangGraph and FastAPI paths are covered by `tests/test_new_layers.py` (skipped when those libraries are missing).
`tests/test_toolkit.py` covers the trip toolkit: number table and sources, nearby search (including that your own
position is never cached), passport date limits, refusal of document numbers, calendar and CSV safety, emission
estimates, expense maths, access rules and both web servers.

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

- **Accounts are for local or demo use.** Passwords and session tokens are stored hashed, but there is no email
  verification or password reset, and the app does not provide HTTPS. Add HTTPS before putting it online. Guest
  trips can be opened by anyone who has the trip id. A trip planned as a guest and then approved while signed in is
  added to that account.
- Deleting an account removes the user, sessions, saved preferences, saved trips and mock booking records. It does not
  clear cached AI-model replies or the local trace log.
- Rate-limit counts are kept in memory: they reset on restart and are not shared between server processes.
- Suggestion tags, best months and map positions of curated landmarks are rough, hand-entered guidance.

* Flight and hotel prices are **live Google listings** only when a Tavily key is set and the lookup works; otherwise (and
  always for trains, buses, cars and bikes) they are estimates. Live prices can change before you book, are not a
  booking, and depend on Google's page layout, so the readers are tested on saved real pages and fall back to
  estimates when a page cannot be read. Reading Google's travel pages through a provider is fine for a personal or demo
  project; check Google's and Tavily's terms before any commercial use. Curated place prices are approximate.
* Any city or town can be planned, but quality varies: the 5 curated destinations are hand-checked; elsewhere the
  sights come from OpenStreetMap and costs are rough estimates. International trips show a warning because visas,
  insurance and currency costs are not included. All money is shown in INR.
* Place supply is finite: long trips on the `cheapest` tier may leave a few slots empty (a warning says so).
* Restaurants: for big cities split into districts (Paris) the list comes from the first district pages on Wikivoyage; the public OpenStreetMap server is slow (about 40 s) and runs in the background, so its extra places may only appear on a repeat plan. Hours are as listed on the source; places without a stated diet appear under "menu not specified".
* Open-Meteo is for non-commercial use; keep the attribution.
* The mock booking cannot be undone or modified because nothing real happens.

* Trip toolkit: emergency numbers can change, so the checked date is shown; most come from Wikipedia and only a few
  countries were also checked against government pages. Nearby places depend on what OpenStreetMap volunteers have
  mapped. Emissions are rough estimates. Document reminders are shown in the app or exported to your calendar; the app
  sends no emails or notifications.

## Demo

See [`docs/demo.md`](docs/demo.md) for a 3-minute walkthrough script (a recording was not produced here).
