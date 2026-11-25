# Decisions

| Decision | Why | Trade-off |
|---|---|---|
| Nodes are plain functions shared by LangGraph and a runner | The framework layer stays thin; nearly all logic is testable without LangGraph | Two execution shells to keep in parity (a test enforces it) |
| `ENGINE=auto` runs a LangGraph self-check, else falls back to the runner | A broken or mismatched LangGraph install must not break the app | Slightly slower first start (<1 s) |
| Hard constraints in code, LLM only for language | No hallucinated prices, dates or overlaps | Less "magical" rewording of constraints |
| Rule parser first; LLM fills gaps only | Predictable, free, offline; the LLM cannot override found values | Unusual phrasing needs a key to be understood |
| Flights/hotels are synthetic and labelled | No free real API exists; honesty beats a fake "live price" | Not real fares |
| OSM places never enter the budget | OSM has no prices | They appear only as "also nearby" ideas |
| Weather: forecast only if the *whole* trip is inside 16 days | Avoids mixing forecast and climate in one itinerary | A trip starting in 10 days but ending in 20 uses climate |
| Per-run and per-day LLM budgets, SQLite cache | Never hit a free-tier limit unexpectedly; repeat runs are free | Cache can serve stale phrasing (keyed by prompt only) |
| Retries share one counter for budget and critic (cap 2) | Hard upper bound on loops and cost | A critic retry can use up a budget retry |
| Unrecognised feedback does not consume a revision | The user is not punished for a vague message | Needs a clear hint message (shown) |
| `interrupt()` in a dedicated node preceded by a `present` node | State visible to the API is `awaiting_approval` while paused | One extra node |
| Mock booking with idempotency key stored in SQLite | Demonstrates safe retries and double-click protection | Nothing real happens |
| MCP tool errors returned as data | Keeps message and `retryable` across the protocol; the v2 SDK masks raised exceptions | Slightly non-standard error shape |
| Keys only via `.env` (never committed); no key = rule-based mode | Zero cost, zero setup | Fewer LLM features by default |


## Any destination (added after the 5-destination version)

* **Why:** a planner limited to five cities is a demo. Users name any place, so the tools accept a resolved
  place (`destination_geo`) and only use the hand-written catalog when the slug is curated.
* **Resolution order** (`tools/geo.py`): curated -> offline gazetteer (~190 places, deterministic tests/evals) ->
  Open-Meteo geocoding. A fuzzy match must be >= 0.72 similar to the typed name; regions/countries are rejected
  with a request for a specific city. Nothing is invented.
* **Hard constraints stay in code:** every price still comes from a tool result and the Critic recomputes totals.
  For generated destinations the places tool builds the candidate list from OSM, so ranking, rain swaps, budget
  retries and the price-traceability check work unchanged.
* **Estimated, not invented:** OSM has no prices, so entry fees = base fee by kind of place x country price level
  ^0.8; hotels/food scale with the country price level. Everything is labelled "estimated".
* **Several free sources, not one:** a live test showed the public Overpass servers are often "at capacity" or
  take 30+ s. Sights now come from Wikivoyage listings, OpenStreetMap and Wikipedia in parallel (all return the same
  OSM-shaped elements, so one builder ranks and prices them), Overpass gets mirrors plus a ~16 s budget, and every
  successful lookup is cached on disk for 30 days. A source that fails never blocks the others.
* **Graceful degradation:** no source answers -> generic (unnamed) suggestions + warning; no geocoder -> only known
  places resolve; no weather API -> a latitude/month climate stand-in, labelled.
* **Ground travel:** below 300 km the estimator returns train/bus options (same option ids, so the strategy
  ladder still works) and the itinerary uses a 1 h (not 3 h) lead time before departure.

## Day trips for generated destinations

* **Why:** a live Kasauli plan scheduled Sanawar, Subathu and other towns several kilometres away as ordinary sights.
* **Three layers, because each failed alone:** (1) a listing 7 km or more away (`FAR_KM`) is flagged `far`, ranked 2.5 points
  lower, and shown as "Day trip from town"; (2) the LLM re-rank is told the same rule, but a model can ignore a prompt, so
  `_llm_rerank` also moves far items after nearby ones in code; (3) Wikivoyage often gives no distance, so listings without
  one get a position from Wikipedia by name (trusted only within 80 km, cached), and the builder measures the distance.
* **Cache lesson:** the 30-day disk cache kept serving listings saved before the flag existed, so the fix seemed not to
  work. Cache keys now carry a version (`wikivoyage-listings:v3:`); bump it whenever a cached source starts returning more.
* **Every source, one rule:** Wikipedia results now carry coordinates and OSM results already do, so any sight 7 km or more
  from the centre (14 km for cities of 100k+, whose own sights spread out) becomes a day trip. A sight named exactly like the
  destination is dropped (it is the town, not a sight).
* **Adventure listings kept:** Wikivoyage "Do" entries were dropped unless they matched a sight kind; rafting, trekking and
  camping now form an `adventure` kind so the adventure preference has something to match.
* **Trade-off:** a place with no distance, no coordinates and no Wikipedia article is treated as nearby.

## Tracing (Phase 7)

* **Local logs, not Langfuse.** The project is local-first and free: a JSONL file and a `metrics` field in the API
  response need no account, no network and no dependency, and show the same things (latency per agent, calls, tokens).
* **One wrapper, both engines.** `trace.wrap` times each node and is applied where the runner and the LangGraph
  graph register nodes, so the two engines report the same way and the node code stays untouched.
* **Honest cost.** Everything runs on free tiers, so `cost_usd` is 0.0; the useful numbers are LLM calls, cache hits,
  fallbacks and a token *estimate* (the router's own budget counter, 1 token ~ 4 characters).
* **Tracing never breaks a plan.** Writing the file swallows OS errors; a missing tracer is a no-op.
* **Tests are offline by construction.** While adding this, a test turned out to call the real weather API (it passed
  here only because this sandbox is offline, and would have failed on an online machine). An autouse fixture now fails
  any test that reaches a non-local host, and another keeps tests from reading a developer's real `.env`.
* **Provider cool-down.** Live runs showed Gemini's free tier answering "high demand" (503) for minutes at a time.
  After a provider exhausts its retries on a retryable error it is skipped for 60 s, so later steps (and the next run)
  go straight to the fallback. Bad answers and bad keys are not outages and do not trigger it.
* **Overpass grace period.** If Wikivoyage + Wikipedia already found at least 6 sights, the (often overloaded)
  Overpass lookup gets only 4 more seconds; it keeps running in the background and fills the 30-day cache for next time.
  A live Kasauli run spent 18.7 s in the places agent waiting for Overpass before this.
