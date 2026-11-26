# Decisions

| Decision | Why | Trade-off |
|---|---|---|
| Nodes are plain functions shared by LangGraph and a runner | The framework layer stays thin; nearly all logic is testable without LangGraph | Two execution shells to keep in parity (a test enforces it) |
| `ENGINE=auto` runs a LangGraph self-check, else falls back to the runner | A broken or mismatched LangGraph install must not break the app | Slightly slower first start (<1 s) |
| Hard constraints in code, LLM only for language | No hallucinated prices, dates or overlaps | Less "magical" rewording of constraints |
| Rule parser first; LLM fills gaps only | Predictable, free, offline; the LLM cannot override found values | Unusual phrasing needs a key to be understood |
| Flights/hotels: estimates by default, live Google prices when a Tavily key is set | No free flight/hotel API exists (Amadeus Self-Service is shut down; Gemini search grounding is not free). Probe on 2026-11-25: Tavily Extract on a Google Flights link returns real fares; Tavily search returns only editorial "from Rs X" text; Bright Data needs a SERP API zone and was not pursued once Tavily worked. Every price is labelled live or estimated, with source and fetch time | Depends on Google's page layout (readers tested on saved real pages, fall back to estimates); return flight time is assumed; hotels arrive in USD and are converted |
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
* **Resolution order** (`services/geo_service.py`): curated -> offline gazetteer (~190 places, deterministic tests/evals) ->
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
* **Top sights and dining.** Asked for ranked sights and veg / non-veg restaurants with good timings. Free sources have no
  star ratings, so ranking uses a prominence score and the output says so. Diet is classified from name, description and
  OSM `diet:*` / `cuisine` tags into veg, both, non-veg or unknown; unknown places are shown separately instead of guessed.
  Timings come from a per-kind table (sights) or the listed hours (restaurants), with an explicit "not stated" when typical.
* **Restaurant lookups are best effort.** Overpass needed about 40 s for a light Paris query, so the restaurant lookup has
  its own 60 s budget, runs beside the places agent, is waited for only briefly, and fills the 30-day cache for next time.

## Live prices (Phase 13)
* **Provider choice by experiment, not by guess.** One probe run sent the same Delhi-Goa and Jaipur requests to both
  providers and counted the rupee prices. Tavily's page read gave 12 real flights with airline, times, stops and a
  total for 2 adults; its search gave blog snippets (one price was "9 INR a night"). Hotels worked for exact dates when
  the dates are typed into the search text (a `checkin=` parameter was ignored) but only in US dollars (`curr=INR` is ignored
  for hotels, honoured for flights).
* **Parse text, do not ask an LLM.** The page text has a fixed shape per flight and per hotel, so plain regular
  expressions read it and a row that does not parse is skipped. An LLM could misread or invent a number; the Critic's
  rule "every price comes from a tool result" stays true.
* **Same option ids as the estimator** (best / early_late / one_stop, 3star / 2star / budget) so the strategy ladder,
  the budget loop and the Critic work unchanged; the ladder is kept monotonic (cheapest <= cheaper <= normal).
* **Validate before trusting a page:** number of adults, currency, date, route and stay dates must match the request;
  otherwise the page is rejected and the estimate is used.
* **Credits are a budget:** 2 per page read, cached 3 hours, 30 a day by default, retry of an empty page once.
  The travel-mode choice cards ask for estimates only.
* **Suggestions use the estimator only.** Pricing dozens of places with live lookups would spend a month of free
  credits in a day. Suggestions and the "current place" they are compared with are priced the same way.
* **Group fairness is plain code.** The next pick favours whoever has been served least, so a majority cannot take
  every slot. Something everyone wants to avoid is dropped; otherwise it is ranked down and reported.
* **Change requests are rules, checked before use.** An impossible change (unknown place, mode too far, too many days)
  leaves the plan and the revision count alone. A bare "2 days" is ignored, so "spend 2 days at the beach" cannot
  shorten the trip.
* **Accounts with the standard library.** scrypt password hashes, hashed session tokens, and a bearer header instead
  of cookies (no cross-site request forgery). No new dependency and no outside identity provider.
* **Memory only fills gaps.** What the request says always wins, the plan says when memory was used, the budget is
  never kept, and "Forget everything" also stops learning.
* **Cancellation is a second approval.** The first call only shows the mock refund; only a literal `confirm: true`
  cancels, and repeating it changes nothing.
* **The traveller chooses how to travel (2026-11-26).** Fixed hour limits hid train, bus, car and bike for places such
  as Pondicherry from Delhi. Raising them for one route only moved the cut-off, so they no longer block anything: they
  only trigger a warning, shown with the real leave and return dates. Only a missing land route blocks a mode.
  Destination suggestions for a chosen road mode still stay within the old limits.
* **A saved travel mode is a hint, not an answer.** Applying it silently meant a traveller who had once booked a flight
  was never asked again. It is now highlighted among the choices (and applied only when the question is switched off).

## Trip toolkit (2026-11-26)
* **Safety, legal and money facts are plain code and stored data, never an AI model.** A fluent wrong emergency number
  or visa rule is worse than none.
* **Emergency numbers need a source.** Each entry records its sources and the date checked. Where two government pages
  differ (Sri Lanka) both numbers are shown. A fire number that no source clearly showed (Belgium, Germany, Maldives)
  is left blank with a note. An unlisted country shows no number at all.
* **Numbers come first and never depend on the map.** They work offline, without sign-in, and still show when the
  nearby search fails or is rate limited.
* **The traveller's position is used once.** It is rounded to about 100 m, not cached, not stored and not repeated in
  the reply. A named town may be cached for 7 days.
* **No visa verdicts.** The rules depend on nationality and change often, so the checklist says to check and links to
  IATA Travel Centre or an official page. The passport check states only rules that were read on an official page
  (Schengen) and calls the 6-month figure a common requirement to check.
* **No document numbers.** The app refuses passport, ID, licence and card numbers before saving; names and expiry
  dates are enough for reminders.
* **Emissions are shown with their method.** Different publishers use different boundaries, so the app shows its
  sources, marks the figures as estimates and treats small gaps as a tie. Flights show the figure with and without
  high-altitude warming. India's published bus figure is for city buses, so coaches use the UK coach factor.
* **Expenses are typed in rupees.** No live currency conversion, so the comparison cannot drift with exchange rates.

## Project layout (2026-11-26)
* **Why:** the first layout was one flat package that grew with every feature (one agents file passed 1,000 lines), so a
  new reader could not see how the system fits together.
* **Backend and frontend are separate**, and the backend is split by layer: `api -> services -> graph -> agents -> tools ->
  integrations`. File names say what is inside. Folders that would have been empty were not created.
* **Behaviour did not change.** Planning results for a fixed set of scenarios and the evaluation scores were compared
  before and after, and the old and new web pages were driven through the same browser steps.
* **React with esbuild only.** Two runtime packages (`react`, `react-dom`) and one build tool keep the install small. The
  backend serves the built files, so there is one address and no cross-origin setup.
* **One data folder.** Everything written while running goes to `.runtime/`, so the project root stays clean. A relative
  `TRIP_DB` or `TRACE_FILE` is placed there too, which keeps an older `.env` working.
* **API paths moved to `/api/v1`.**

Entries above this section use the file names of their time.

## Long international road routes (2026-11-26)
* **Why:** for Mumbai to Bangkok only a flight could be chosen. The traveller picked: open car and bike, with warnings.
* **A short list, not a rule.** Only India and Thailand are listed. Sources disagree on whether the Myanmar crossings can
  be used, so the app does not claim the route is open. It tells the traveller what to check.
* **No train or bus.** The planner has no through service to price, so a fare and travel time would be made up.
* **Never suggested.** A traveller can choose the drive, but destination suggestions leave it out.

