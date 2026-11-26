# Architecture

## Graph

```mermaid
flowchart TD
    S([START]) --> G[Input Guardrail]
    G -- blocked --> E([END])
    G --> I[Intake]
    I -- missing info --> E
    I --> SUP[Supervisor]
    SUP --> F[Flight] & H[Hotel] & W[Weather] & A[Activities]
    F & H & W & A --> M[Merge]
    M --> B[Budget]
    B -- over budget, retries < 2 --> SUP
    B --> C[Critic]
    C -- blocking issue, retries < 2 --> SUP
    C --> P[Present]
    P --> AP{{Human Approval<br/>interrupt}}
    AP -- changes, revisions < 2 --> SUP
    AP -- not understood --> P
    AP -- approved --> BK[Book mock, idempotent]
    BK --> WR[Writer]
    WR --> E
```

Around the graph, in `services/trip_service.py` and not in the graph: accounts and sessions, saved preferences, trip ownership,
rate limits and booking cancellation. A cancellation happens after the graph has ended, so it is stored on the
booking record and laid over the finished state when it is read; both engines behave the same. Destination
suggestions are a tool (`recommend_destinations`) that intake calls when no destination is named and `present`
calls for alternatives.

## Where things live

All paths in this document are inside `backend/app/`.

| Layer | Folder | Rule |
|---|---|---|
| HTTP | `api/`, `main.py` | Thin: reads the request and calls the service |
| Application | `services/` | Business logic, access rules and everything that is plain code |
| Orchestration | `graph/` | State, routing and the two engines |
| Agents | `agents/` | One file per agent, each node a function `fn(state, deps) -> update` |
| Tools | `tools/` | What agents may call, in-process or over MCP |
| Outside data | `integrations/` | One client per data source |
| Storage | `database/` | The only code that writes SQL |
| Cross-cutting | `core/` | Configuration, security, rate limits, caching, tracing |

The React app in `frontend/` talks only to `/api/v1`. It is built into `frontend/dist/`, which the backend serves.
Everything the app writes while running (database, place cache, traces) goes into `.runtime/` in the project root.

## Why two engines share one set of nodes

`agents/` holds every node as a plain function, and `graph/nodes.py` lists them once. `graph/edges.py` holds the
conditional edges as pure functions. Two thin shells execute them:

* `graph/workflow.py` wires them into **LangGraph** (parallel edges, join, `interrupt()`, SQLite checkpointer).
* `graph/runner.py` executes the same nodes with a thread pool. It is the engine the unit tests run, the CLI and the
  fallback server can use, and the automatic fallback if LangGraph is missing or fails its startup self-check
  (`graph/engine.py`).

`tests/test_graph/test_graph_engine.py` asserts both engines produce identical plans, budgets and warnings.

## Shared state

One typed `TripState`. It also carries `group`, `group_report`, `memory`, `excluded`, `suggestions` and `alternatives`.
A `warnings` update that starts with `RESET` replaces the list, so a changed destination drops old warnings.
 Workers write separate keys (`flight`, `hotel`, `weather`, `activities`), so parallel
writes never conflict. Only `log` and `warnings` are append-only (reducers). Nodes that decide a route
(`budget`, `critic`, `approval`) set `replan_reason`; routers only read it; the Supervisor consumes it.

| Key | Written by |
|---|---|
| `guardrail`, `status`, `message` | guardrail, intake, present, book |
| `constraints` | intake, approval (feedback) |
| `strategy`, `retries`, `fanout`, `replan_reason` | supervisor, budget, critic, approval |
| `flight`, `hotel`, `weather`, `activities` | one worker each |
| `itinerary` | merge |
| `budget_report` | budget |
| `critic_issues` | critic |
| `revisions`, `decision`, `approved`, `food_boost`, `notice`, `pending_approval` | present, approval |
| `booking` | book |
| `summary` | present (template), writer (final) |

## Control flow

* **Budget loop.** Budget totals flight + hotel + activities + food. If over budget and `retries < 2`, it sets
  `replan_reason = over_budget`; the Supervisor moves `normal -> cheaper -> cheapest`, clears stale results, and
  re-runs only flight, hotel and activities (weather is unaffected by price).
* **Critic.** Deterministic checks: dates, hotel nights, overlaps, activities per day (max 4), airport buffer,
  price traceability, totals. A blocking issue triggers a re-plan (sharing the same 2-retry counter).
  At the cap the plan is shown anyway with the unresolved issue as a warning.
* **Human approval.** `present` sets `awaiting_approval` and the graph pauses. Decisions: approve, cancel, or
  revise with free text. Feedback is parsed (`services/feedback_parser.py`); unrecognised feedback does not consume a revision.
  After 2 revisions only approve/cancel remain.
* **Booking.** The key is a hash of thread, destination, dates, travelers and total. A second approve (double
  click, retry, restart) finds the stored booking and returns it; the tool is not called again.

## Resilience

* Tool calls go through `call_with_retry`: exponential backoff for retryable errors, none for invalid input.
* After retries a worker returns `{error, selected: None}` plus a warning. Merge/Budget/Critic degrade: the plan
  is built without that part, totals are flagged incomplete, and the user sees "Partial plan" warnings.
* Real-data tools (Open-Meteo, Wikivoyage, OSM) never raise; any failure returns offline estimates fast.
* LLM calls: backoff on 429/5xx/timeout, then next provider, then rules. Responses are schema-validated, cached
  in SQLite by prompt hash, and bounded by a per-run token budget and daily call counters.

## Security model

* Valid instructions come only from the user. Tool output (places, Wikivoyage text, OSM names) is data: it is
  sanitised (control characters, injection phrases, markup) before it reaches state or the UI.
* User text sent to an LLM is wrapped as data; the system prompt says never to follow instructions inside it.
* LLM output cannot change money: it can only reorder already-filtered candidates, fill missing intake fields
  (validated against the catalog and ranges), or add an overview whose rupee figures must match the plan.
* React escapes every string it shows. The one place that builds HTML (map pop-ups) escapes it first, and links from
  outside data are used only if they start with `https://`.

## MCP

`tools/mcp_server.py` serves the tools over stdio (from `backend/`: `python -m app.tools.mcp_server`). `McpClient` keeps one
persistent session in a background event loop. Tool errors travel as data (`{error, retryable}`) so the client
raises the same `ToolError` as the in-process client. Works with the v1 `FastMCP` and v2 `MCPServer` SDKs.
Switch with `TOOLS_MODE=mcp`; a test proves identical results.

## Trip toolkit

`services/trip_toolkit/` holds the five post-planning features. It sits beside the graph, not in it:

```
UI -> /api/v1/trip/{id}/{tool}  -> PlannerService (access rules, rate limit) -> trip_toolkit/handlers.py
UI -> /api/v1/emergency         -> PlannerService (no sign-in needed)        -> trip_toolkit/emergency.py
handlers -> saved plan (read only) + trip_items table (documents, ticks, expenses)
handlers -> tools find_help_nearby / local_tips (in-process or MCP)
```

| Module | Job |
|---|---|
| `companion.py`, `data/country_facts.py` | Packing rules, customs, country facts |
| `emergency.py`, `data/emergency_numbers.py` | Sourced numbers; cleaning and sorting of nearby places |
| `documents.py` | Checklist, passport check, reminders, calendar file, refusal of document numbers |
| `footprint.py` | Emission factors and the comparison; also used by the flight node and the travel choices |
| `expenses.py` | Validation, planned against actual, CSV |
| `handlers.py` | Turns a saved plan into each view |

No new graph state key was added (LangGraph drops undeclared keys): the plan's footprint is stored inside `flight`.
Nothing in the toolkit calls an AI model. The only network calls are the two tools, which use OpenStreetMap
(Overpass) and Wikivoyage and return an empty, explained result when offline.

