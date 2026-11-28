# Features

What each feature does, where its data comes from and what it will not do. For setup see the [README](../README.md).

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
islands in the list in `backend/app/services/pricing/transport_estimator.py`, which is not complete) or more than 1,500 km between countries.

**One long international exception: India and Thailand.** Car and bike can be chosen, and the choice card, plan and
summary carry a warning: the route goes through north-east India and Myanmar, border crossings may be closed or
restricted, and you must check access, permits, visas, vehicle papers and safety with official sources. The estimate
leaves out permit, visa and escort costs, and the real road is likely longer than the straight-line estimate. Train and
bus stay blocked because the planner has no through service to price. Suggestions never propose this drive. Other
routes are added to `ROAD_LINKS` only after a road link has been confirmed.

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

From `backend/`, run `python -m app.integrations.live_probe` once to see what the providers return. The output goes to
`.runtime/live_probe/`, which Git ignores.

## Trip guide: top sights and where to eat

Every plan also includes:

* **Top sights**: the most prominent places (historical, waterfalls, beaches, spiritual, viewpoints...) ranked, each with a
  label and a good time to visit (waterfalls also get a season note). Far day trips are left out of the ranking.
* **Where to eat**: top restaurants split into **vegetarian** and **non-vegetarian** (places that serve both appear in
  both), with opening hours as listed, or a typical lunch/dinner window marked "not stated: check before you go".
  Places whose diet is not stated appear under "menu not specified".

Free sources have no star ratings, so "top" means *most prominent* (traveller-listed on Wikivoyage, Wikidata/Wikipedia
entry, website, stated hours), and the plan says so. Tool: `search_dining`.

## Dashboard

| Feature | How it works |
|---|---|
| Trip form | From, to, start date, days, travellers, budget and interests become one plain sentence for the planner. Leave "To" empty for suggestions. The date picker covers tomorrow to about eleven months ahead, because the sentence carries no year; a trip picked for the 31st starts on the 30th. A second tab takes a request in your own words. |
| Agent status | Shows the four stages and whether the request is working, waiting for an answer or ready. There is no percentage: the server answers once, at the end. |
| Top 10 destinations in India | Agra, Jaipur, Goa, Delhi, Alleppey, Varanasi, Udaipur, Amritsar, Manali, Leh. A hand-picked list, not an official ranking, with rough best months and trip length. No ratings or prices, because the planner has no source for them. |
| Photos | The lead picture of a Wikipedia article, loaded by the visitor's browser, with a link to its photographer and licence. A drawing is shown if it cannot load, and for itineraries outside the ten places. |
| Other boxes | The current itinerary, places that are good in the chosen month, and a travel style from the chosen interests. |

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
| Interactive map | Leaflet with an OpenFreeMap vector map: black names in English where the map data has one, town and district names highlighted. One day shows numbered, highlighted stop names and a blue road route in visiting order, with distance and driving time from the free OSRM demo server (driving only, no live traffic; light non-commercial use, at most one request a second). Only the sights' positions are sent. If routing fails, a dashed line shows the order; if the vector map fails, the standard OpenStreetMap map is used. Needs internet access. Positions are approximate; stops with no fixed location and hotels are not plotted. |

Endpoints: `POST /api/v1/booking/{thread_id}/cancel` (`{"confirm": true}`), `POST /api/v1/auth/register|login|logout`,
`GET|DELETE /api/v1/me`, `PUT|DELETE /api/v1/me/memory`, `GET /api/v1/trips`. `POST /api/v1/plan` also accepts
`"group": [{"name": "Asha", "likes": ["history"], "avoid": ["nightlife"]}]`. Signed-in calls send
`Authorization: Bearer <token>`.

Settings (all optional): `AUTH_REQUIRED=1` stops guests from planning; `RATE_LIMIT=0` turns limits off;
`RATE_LIMIT_PLAN_PER_MINUTE`, `RATE_LIMIT_PLAN_PER_DAY`, `RATE_LIMIT_ACTIONS_PER_MINUTE`,
`RATE_LIMIT_AUTH_PER_MINUTE`, `RATE_LIMIT_READS_PER_MINUTE`, `RATE_LIMIT_VOICE_PER_MINUTE` change them.

**Agent names in the code** (`backend/app/agents/`): `destination_agent.py` resolves and suggests places,
`activity_agent.py` finds sights, tips and restaurants, and `itinerary_agent.py` builds the days (the `merge` node)
and writes the summary (the `writer` node).

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

Endpoints: `POST /api/v1/emergency` (`{"place": "Bangkok", "nearby": true}`, `{"lat": 15.4, "lon": 73.8}` or
`{"thread_id": "..."}`; never needs sign-in) and `GET /api/v1/trip/{thread_id}/{companion|emergency|documents|footprint|expenses}`,
`POST /api/v1/trip/{thread_id}/expenses`, `POST /api/v1/trip/{thread_id}/documents` (also `/documents/passport-check` and
`/documents/tick`), `DELETE /api/v1/trip/{thread_id}/{expenses|documents}/{id}`. MCP tools used: `find_help_nearby`,
`local_tips`.

## A misspelled or misheard place name

A name typed or spoken one letter wrong can match a real but tiny place: "Gova" is a village of 45 people in Italy.
When a place found online has fewer than 5,000 people (or no figure) and is one letter off a well-known place, the
planner asks **"Did you mean Goa, India?"** before planning. Both places are offered, on the page and in the chat, so
you can still choose the one you typed. Asking to change the destination to such a name does not move the trip; it
tells you what to type. "One letter off" means one letter added, left out or changed, or two neighbours swapped, so a
worse misspelling is not caught. The "Explore more places" search does not ask.

## World destinations and exploring any place

* The **World Destinations** page (`#world`) shows 15 hand-picked places. It is not an official ranking, and the best
  months and trip lengths are rough guidance. **Plan this trip** fills in the trip form.
* **Explore more places** takes any place name. Three steps run: the place is looked up, its top sights are ranked
  (the same sources as a trip plan), and a picture is found for each. This is separate from the trip graph and uses no
  AI model. Nothing is saved apart from the usual place cache.
* **Pictures are only shown when they can be confirmed:** the Wikipedia article must have its own location close to the
  place. A sight with a known position must match within 5 km. Otherwise a drawing is shown. Some real places get a
  drawing because their article gives no main location.
* A region or country name (for example "Switzerland") asks for a city or town instead.
* Sights need live data (`REAL_DATA=1`). In very large cities the free sources can miss famous sights.

Endpoint: `POST /api/v1/explore` with `{"place": "Prague"}`. MCP tool added: `find_place_photos`.

## Photos in the day-by-day plan

* Each named sight shows up to four thumbnails. **View all photos** opens a gallery with up to 24, with captions,
  arrow keys, and a link to each photo's author and licence.
* Flexible suggestions (dinner, café time, market stroll and so on) are not one place. They get up to eight example
  photos, labelled as examples, and a map search for real places of that kind at the destination. Dinner uses the
  country's cuisine article; the walking tour uses the destination's article, confirmed by its location; the others
  use a general article, so their pictures come from around the world.
* Photos come from the sight's Wikipedia article, and only when the article's location matches the sight. Maps,
  plans, logos and non-JPEG files are left out; old views, pictures of events and people, and pictures of fires or
  repairs are listed last. This
  filter works on file names and captions, so a few drawings or paintings can still appear.
* How many photos there are depends on the article. Every sight also has **More images on Google** and **Google
  Maps** links, which work when no photo could be confirmed. Those open Google with the place name.
* The server only confirms which article to use (`POST /api/v1/photos` with `{"thread_id": "..."}`; it reads the saved
  plan and changes nothing). The photos are loaded by the visitor's browser.

## Chatbot with voice input

The **Chat** button (bottom right) opens a chat that uses the same planner as the form.

* **Plan:** type, for example, "3 days in Goa from Delhi, budget 30000". If something is missing (starting city,
  budget, way of travelling) it asks, and your short reply is added to the earlier request. "start over" drops it.
* **Change:** "make it cheaper", "make it 4 days", "add 1 person", "go by train". These use the same change rules and
  the same limit of 2 changes as the page.
* **Ask:** cost, travel, hotel, weather, food, warnings, booking status or "show day 2" are answered by rules from the
  saved plan. Only a question no rule covers goes to an AI model (Groq, then Gemini, then Ollama). It is given the plan
  but no group names or saved preferences, and its answer is marked as an AI answer. It can be wrong.
* **Never from the chat:** approving, booking and cancelling. Those are only the buttons, so a misheard word cannot
  book anything. Visa and entry questions and emergency questions get fixed replies without any AI model: the app
  never says whether a visa is needed, and emergency numbers come only from "Emergency help".
* **Voice:** press **Speak**, then **Stop** (at most one minute). The recording goes to Groq's Whisper model, the
  words appear in the text box, and nothing is sent until you press **Send**. It needs `GROQ_API_KEY`, works in
  English for now, and uses the microphone only while recording. Browsers allow the microphone on `localhost` or HTTPS.
* **Privacy:** the app does not save recordings, and chat messages stay only on the screen. The audio itself goes to
  Groq, and no text check can remove something sensitive from audio before it is sent, so don't say card or ID numbers
  or passwords. If the returned text contains one, it is discarded.
* **If voice is refused:** the message says whether Groq rejected the key (401), blocked the voice model in your
  organization or project settings, or refused for another reason. The server window prints Groq's reason, without
  the key. While the page itself is planning, the chat says so and waits; options from before a change on the page are
  removed.
* **Limits:** `VOICE_DAILY_LIMIT` (default 100 recordings a day) and 10 recordings a minute. Check your Groq account's
  free limits.

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
| Places (any other destination) | Four free sources asked at the same time and merged by name: **Wikivoyage** "See"/"Do" listings (best for small towns), **OpenStreetMap** (Overpass; wikidata/heritage/tourism tags), **Wikipedia** nearby articles (kind taken from the Wikidata description; stubs ignored) and the Wikivoyage page text for tips. A notability score ranks them and a per-kind cap keeps the list varied. Sights 7 km or more from the town centre (by a distance in the Wikivoyage listing, its coordinates, or a Wikipedia position looked up by name) are marked **day trips** and always rank after nearby sights. None of them has prices, so entry fees are **estimated** from the kind of place and the country's price level. Each lookup is cached on disk for 30 days (`.runtime/place_cache/`), and the shared Overpass server gets a short time budget with mirror fallback because it is often at capacity. If every source fails the plan uses clearly generic suggestions (walking tour, market, dinner) and says so in a warning | "estimated" + warning |
| Restaurants | **Wikivoyage** "Eat" listings (best for small towns) + **OpenStreetMap** restaurants (diet and cuisine tags). Ranked by prominence, not stars. No prices, so meals are covered by the food allowance | "estimated" + note |
| Tips / knowledge | Wikivoyage text -> local TF-IDF vector store (CC BY-SA, attributed) | attributed |
| Nearby ideas | OpenStreetMap via Overpass (ODbL). **No prices exist, so these never enter the itinerary or budget** | "no prices" |
| Flights and hotels (live) | **Google Flights / Google Hotels** pages read through **Tavily Extract** (needs `TAVILY_API_KEY`); hotel dollars converted with **Frankfurter** (ECB rates). See "Live flight and hotel prices" | "live" badge, source and fetch time |
| Flights, trains and hotels (fallback, and trains/buses/cars/bikes always) | **Synthetic estimator** (great-circle distance, season, country price level; no free real API exists). Under 300 km it prices a train/bus instead of a flight; international trips get higher per-km fares, long-haul (> 9,000 km) gets one-stop options only. Hotels scale with the country's price level and city size | "estimated" everywhere |
| Booking | Mock tool with an idempotency key; nothing is purchased | "MOCK" everywhere |

Free-tier limits change often: check each provider's console. The router has a per-run token ceiling and a
per-provider daily call counter (`backend/app/core/config.py`) so you never hit a limit unexpectedly.
A provider that fails all its retries (429, 5xx, timeout) is skipped for 60 s (`LLM_COOLDOWN`), so an overloaded
free tier costs one slow call, not one per step; a bad answer or a bad key never triggers the cool-down.

## Tracing: time and cost per run

Every `/api/v1/plan` and `/api/v1/approve` response carries a `metrics` object, and the UI shows it under the agent log:
total seconds, the time each agent took (and the slowest one), tool calls and failures, LLM calls, cache hits,
fallbacks, estimated tokens and automatic replans. Cost is always **$0** because every service is a free tier, so the
numbers that matter are call counts and the token estimate (what free-tier limits are measured in). Each run is
also appended as one JSON line to `.runtime/traces.jsonl` (set `TRACE_FILE=other.jsonl` to move it, `TRACE_FILE=off` to
disable). Timings come from one wrapper that both engines (LangGraph and the runner) register their nodes through, so
they mean the same in either. Tool and LLM counters are before/after deltas: exact for one request at a time,
approximate when requests overlap. Langfuse is not used: it would add an account and a dependency for a local project.

On Windows, double-click `scripts\run_tests.bat` for the tests and `scripts\run_evals.bat` for the evals including the LLM judge
(the judge needs your keys in `.env`; it makes about one free-tier call per prompt that states preferences).

## Records for the evaluation dashboard

Each plan, approval, chat message, voice recording, destination search, photo lookup and booking cancellation is
recorded in `.runtime/observability.db`, on this computer only. A record holds the steps of the request as a tree:
agents, tool calls (with each retry), data lookups (found, empty, error, timeout, skipped or cached), AI calls
(provider, model, retries, fallback, tokens as reported by the provider or estimated), safety decisions and the
automatic made-up fact checks. The metrics dashboard below shows them. They can also be printed from the `backend` folder:

```
python -m app.observability            latest requests, and the steps of the newest one
python -m app.observability 3          the steps of the third request in the list
python -m app.observability 3 --text   with the detailed text, if it was kept
```

| Setting in `.env` | Default | Meaning |
| --- | --- | --- |
| `OBSERVABILITY` | 1 | 0 stops recording |
| `RECORD_DETAILS` | 0 | 1 also keeps typed requests, AI prompts and replies, retrieved text and error messages |
| `RECORD_KEEP_DAYS` | 30 | records older than this are deleted (at most 5,000 requests are kept) |
| `RECORD_DETAIL_KEEP_DAYS` | 7 | detailed text is deleted sooner |

* **Basic records** hold names, times, counts and result codes. They hold no typed text, place names, AI replies or
  error messages.
* **Detailed records** also keep the examples of what a fact check flagged, with the AI text it checked. They are
  cleaned first: API keys, email addresses, group members' names and the saved home city are
  hidden, and text that looks like a card or ID number, code or password is withheld. Prompts that carry saved
  preferences are not kept. Cleaning works by pattern, so it cannot recognise every personal detail someone types
  (a street address, or a name that is not in the group list). Switch it on only when you need it.
* **Never recorded:** keys, sign-in tokens, passwords, audio and transcripts, emergency help and trip toolkit
  requests, and the text of chat messages about an emergency (a chat reply fixed in advance is counted by its topic
  only).
* Deleting an account also deletes its records. Recording problems never stop or change a plan.
* With `TOOLS_MODE=mcp`, tool calls are recorded but the data lookups inside the tool server are not.

## Metrics dashboard

A separate page at `http://127.0.0.1:8000/dashboard`, with its own menu, for the person who runs the app. It is off
until `.env` has these two lines (then restart the server):

```
DASHBOARD=1
DASHBOARD_PASSWORD=choose-your-own-password
```

The password needs at least 8 characters. Signing in lasts until the browser tab is closed, 12 hours pass, the server
restarts or the password changes. Wrong guesses are limited (5 a minute). The dashboard cannot change a plan or what
was recorded. The one thing it saves is your own mark on a flagged fact check. Looking at it is not recorded.

| Tab | What it shows |
| --- | --- |
| Overview | requests by result, median / p90 / slowest time of a full plan, replans, changes, mock bookings, failed steps, today's use of the app's own daily limits, and the latest offline test scores |
| Agents | runs, success rate, times, retries and errors of each agent, with the tool calls, AI calls and lookups made inside it |
| AI models | every call (job, provider, model, time, result and error code, retries, backup provider, saved answer, tokens), with totals by job and by model; chat and voice included |
| Traces | one request as a timeline, parallel agents side by side, with linked requests (changes, approval, chat) |
| Retrieval | each data source (found, found nothing, failed, timed out, skipped, from cache, times), fallbacks, and which sources' places reached finished plans |
| Logs | every step, warning and error, with search and filters; each line opens its request's timeline |
| Guardrails | typed messages stopped (by reason), private details withheld (type only), web text cleaned, AI output thrown away, plan checks and price or total failures, change and rate limits, chat replies fixed in advance, and the latest times a rule stepped in |
| Hallucination checks | AI summaries, chat answers, request values and activity rankings checked and flagged, by kind of detail and by model, with examples and your "real problem / false alarm" mark |

Filters: period or dates, request type, result, agent, AI model, and request or trip id. Refresh, optional refresh
every 15 seconds, and CSV or JSON download of what the filters show (the file stays on your computer; cells that a
spreadsheet could run as a formula are written as text).

How to read it:

* Plan times count only plans that reached "awaiting approval". A figure made from fewer than 5 values is marked.
* A "not possible" tool answer (no train across the sea, or no place by that name) is not an error, and a lookup that
  found nothing is not counted as failed.
* A live price page that was never read because the app's daily limit was used up is **skipped** (`daily limit`), not
  failed. Records made before this change still show it as failed. Only answered lookups count as "From cache".
* Daily limits are what this app counted today against its own settings. Providers have their own limits, and the app
  cannot see a bill.
* The Overview tab's test scores come from `backend/evals/report.md`, so they change only when
  `python evals/run_evals.py` is run again.
* With the most records it keeps (5,000 requests), a tab can take a few seconds to load.
* A rule on the Guardrails tab can stop an ordinary message by mistake, so a count there is not a count of attacks.
  Only limits hit by recorded requests appear.
* The Evaluations tab shows saved test results. It never starts a test.

### Evaluations

The Evaluations tab shows test runs on made-up requests, so the filters of the other tabs do not apply to it. You
start every test yourself, from the `backend` folder. Results are kept in `.runtime/evals/` (the newest 100 offline
runs and 30 live and voice runs).

| Test | Command | Needs |
| --- | --- | --- |
| Offline | `python evals/run_evals.py` | nothing: no internet, no AI, fixed date, so the same code gives the same result |
| Live AI | `python evals/run_live_evals.py` (`--list` shows the plan and calls nothing) | an AI key in `.env` |
| Voice (optional) | `python evals/run_voice_test.py --list`, record, then run without `--list` | `GROQ_API_KEY` |

**Offline.** The 23 planning requests (planner against a single-agent baseline), `reading_cases.json` (exact start
dates and other phrasings) and `chat_cases.json` (answers, fixed replies, and that the chat never books). A
**known gap** is something the planner is known to get wrong: it is listed, not counted in the pass rates, and
reported when it starts passing. No gaps are listed at the moment. The tab keeps a history and says which cases
changed since the run before.

**Wording the rules read.** Dates in numbers with a year (`20/12/2026`, `20-12-2026`, `2026-12-20`), read **day
first**; `20/12` without a year is not read. "Christmas" (25 December, "Christmas eve" 24), "tomorrow" and "day after
tomorrow", with a note that says which date was used. Traveller counts in words up to twelve ("four of us", "two
adults and one child"), "five nights" (6 days) and "Dilli" for Delhi. These apply to new requests; a change request
on a finished plan still needs a day and a month in words ("move it to 20 December").

**Live AI.** Four jobs, each provider on its own: reading a request (rules alone against rules with the AI),
ordering activities (rules against AI), the plan summary and chat answers (checked with the made-up fact checks;
questions the plan cannot answer must say so). Plans are built offline, so only the AI is live. The saved-answer
cache is off. A run makes **at most 100 calls, retries and the AI judge included**; the calls also count toward the
app's daily limit per provider. The judge runs last with what is left: another provider where one is available,
otherwise the same one, which the tab says. When it compares two activity lists it is not told which is the AI's.
On the tab you can mark each answer **Good** or **Wrong**. These are a few cases per job: enough to spot problems,
not to prove that one model is better.

**Voice.** You record ten set sentences (`01.m4a` to `10.m4a` in `.runtime/voice_test/`). It checks whether the
planner reads the right places, numbers and dates from the transcript. Only pass or fail per detail is saved, never
the transcript or the sound. The recordings stay where you put them until you delete them.

Live and voice results are not part of the request records on the other tabs.

### Made-up fact checks

The checks compare what an AI model returned with facts the app already has. They only record and flag: the planner,
the summary and the chat reply are exactly as they would be without them. (The older rule that leaves out an AI
summary with a rupee amount not in the plan still works as before.)

| AI output | What is compared |
| --- | --- |
| Trip summary and chat answers | rupee amounts, dates, day and night counts and place names, against the plan. Places named in the chat question are allowed |
| Values read from a request | places, days, budget and interests that the rules could not read, against the typed words. A one-letter spelling correction is counted, not flagged |
| Activity ranking | ids that were not on the list the model was given |

**These are not proof.** A flag means "not found in the plan or the request", and it can be a false alarm: a real
nearby town the plan does not mention is flagged too, and so is a figure the model worked out itself. A made-up detail
can also slip through: money not written with ₹, Rs, INR or "rupees", a one-word place name that is not a known town
or city, weekdays, clock times, distances, opinions, and a true detail used in a wrong sentence. No AI judge is used.

To read what was flagged, set `RECORD_DETAILS=1`. Each example then has **Real problem** and **False alarm** buttons;
press a pressed button again to remove the mark. A mark is deleted with its record. Requests made before the checks
existed were not checked.

## Known limitations

- **Accounts are for local or demo use.** Passwords and session tokens are stored hashed, but there is no email
  verification or password reset, and the app does not provide HTTPS. Add HTTPS before putting it online. Guest
  trips can be opened by anyone who has the trip id. A trip planned as a guest and then approved while signed in is
  added to that account.
- Deleting an account removes the user, sessions, saved preferences, saved trips, mock booking records and the
  account's dashboard records. It does not clear cached AI-model replies or the local trace log.
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
* Restaurants: for big cities split into districts (Paris) the list comes from the first district pages on Wikivoyage; the public OpenStreetMap server is slow (40 s to 2 minutes) and runs in the background, so its extra places may only appear on a repeat plan. A plan waits for it once (up to 25 s); cheaper re-plans go on without waiting while that search is still running, and a search that found nothing or failed is not repeated for 2 minutes. Hours are as listed on the source; places without a stated diet appear under "menu not specified".
* Open-Meteo is for non-commercial use; keep the attribution.
* The mock booking cannot be undone or modified because nothing real happens.

* Trip toolkit: emergency numbers can change, so the checked date is shown; most come from Wikipedia and only a few
  countries were also checked against government pages. Nearby places depend on what OpenStreetMap volunteers have
  mapped. Emissions are rough estimates. Document reminders are shown in the app or exported to your calendar; the app
  sends no emails or notifications.
