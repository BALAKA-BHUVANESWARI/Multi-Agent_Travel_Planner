# Evaluation framework (stages 1 to 3)

From the `backend` folder:

```
python -m evaluation.run_evaluation                      # everything that is built
python -m evaluation.run_evaluation --agent budget       # one part; --help lists the names
python -m evaluation.run_evaluation --deterministic-only
```

Reports go to `.runtime/evaluation/` (`report.md` and `report.json`). The command ends with code 1 when a case
failed. It runs offline with a fixed date, calls no real AI and needs no key. All test data is **synthetic**.

The older evaluations (`evals/` and the dashboard's Evaluations tab) are unchanged.

## Two scores that are never mixed

- **Planner:** is the application right?
- **Evaluator self-checks:** made-up data with planted mistakes. Do the checks find exactly those?

**Not supported** means the application cannot do what the case asks. **Not run** and **not supported** are never
counted as passed. Pass rate = passed / (passed + failed + errors).

## What is checked

Each part has an evaluator in `evaluators/` and cases in `datasets/`. A case **fails** when any hard check fails; the
report gives the reason. It is **not supported** when nothing fails but it asks for something the application
cannot do. Warnings never fail a case.

| Part | Passes when | Metrics in the report |
|---|---|---|
| supervisor | requirements read correctly; the right agents run, and only those; missing details are asked for before any search; a failed agent is retried within limits, reported, and does not stop the others | agents run, tool calls, automatic re-plans |
| destination | suggestions suit the interests and the requested area, "fits budget" marks are right, off-season and over-budget are said openly, alternatives are priced like the planned place | share matching interests, share in season |
| transport | the search has the right route, dates and travellers; price, times, stops and mode equal the provider's answer; totals add up; estimates are labelled; nothing is invented in an outage | mode, price, source |
| accommodation | check-in, nights, guests and rooms are right; rate, rating, amenities and link equal the provider's answer when present; estimates are labelled; nothing is invented in an outage | room type, rate, source |
| weather | every trip day is covered; forecast or climate matches the dates; climate is never called a forecast; rain is read correctly; no outdoor activity stays on a rainy day; moves are explained | rainy days, activities moved |
| activity | every activity comes from the places data unchanged, is near the destination, appears once and suits the weather; no interest or request is dropped silently | share matching interests, share of general suggestions |
| group | everyone is counted and priced; each person gets something they like or a warning says why; the group report is true | share of people served |
| end_to_end | the right final status; a legal route through the workflow; data passed on unchanged; failures reported; the response fits the shapes in `app/schemas` | re-plans, tool calls, warnings |
| grounding | every outside detail matches what a source answered; each block names its source and says estimate or live; live data has a fresh fetch time; links come from a source; the written plan states no unbacked price; nothing an AI invents is shown or fills a gap | links, live parts |
| replanning | **result:** what was asked changed, everything else stayed, dependent figures were worked out again; **agents:** only the affected agents ran again | change applied, agents run, share of activities kept |

"Provider's answer" offline means the application's own **price estimator**. These checks show that the plan
repeats it faithfully and labels it as an estimate. They say nothing about real prices or availability. The same
holds for destination tags and seasons: there is no outside source to verify them. The end-to-end cases use the
built-in runner, not LangGraph.

**Grounding** (`evaluators/grounding.py`) is why external data can be trusted or not. The *source records* are the
tool answers kept while planning. It shows where a detail came from, not whether the source is right.

- Live prices come from **saved real Google pages** in `app/tests/fixtures/`, not from the internet
  (`input.live`). The saved hotel page is in US dollars and uses a fixed, made-up exchange rate in tests.
- AI cases use a **scripted pretend AI** (`input.ai`) that invents things on purpose. No real model is called, so
  these cases show what the app does **if** a model invents something, not how often a real one does.
- *Full provenance* cases ask for a source, a link or reference, a retrieval time and an estimate/live label.
  What the app does not keep is "not supported".

**Change requests** (`evaluators/replanning.py`): each change gives up to two cases, so a wrong plan and wasted work
are not mixed. `rp-…-result` checks the new plan. `rp-…-agents` compares the agents that ran with
`expected.agents` (must run) and `expected.may_run` (also fine). A change the planner cannot read, says so, and
leaves the plan alone is "not supported" when the case names it in `expected.capability`; otherwise it fails.

The affected-agent sets are a judgement of what each change **needs**:

| Change | Must run again | Also accepted |
|---|---|---|
| cheaper hotel | hotel | |
| cheaper flight, or another way to travel | travel | |
| lower budget | travel, hotel, activities | |
| more or fewer days, new dates | travel, hotel, weather | activities |
| new destination | all four | |
| one more traveller | travel, hotel | |
| other interests, or something left out | activities | |

A higher budget has no agents case: searching prices again would also be reasonable.

**Budget** (`evaluators/budget.py`): every amount is worked out again with `Decimal`, without the application's
formulas or price settings. It covers travel, rooms, food, activities, total, per person, equal shares, remaining
money, overspending, missing prices and recalculation after changes. For finished plans it takes the plan's own
unit prices, so it checks the **arithmetic**, not whether a price is true. If you change the food allowance in
`app/core/config.py`, update `food_per_person_day` in the cases too.

The planner has no lines for local transport, miscellaneous costs or contingency, and totals rupees only. Those
cases are "not supported"; the evaluator's own arithmetic for them is covered by self-checks.

**Itinerary** (`evaluators/itinerary.py`): dates and missing days, clashes, repeats, durations, arrival and
departure, opening hours, travel time, straight-line distance, lunch and rest gaps, rain, daily and total budget,
and interests. Each finding is a **failure**, a **warning** or **not checked**. Limits are in `DEFAULT_RULES`; a
case can change them in `expected_constraints.rules`. Opening hours and travel times are checked only when the
data has them (the offline planner has neither). A straight-line distance is not a route distance.

## Known failures

These are real, and the planner is deliberately left unchanged:

- `plan-goa-monsoon`: when every day is rainy, all beaches are replaced, nothing says that the only interest was
  dropped, and several slots get a general indoor suggestion.
- `dst-india-only`: "somewhere in India" is read as a destination called India, so nothing is suggested ("within
  India" works). Seen offline.
- `e2e-invalid-date-words`: "31 February" becomes 28 February without a word (31/02/2027 in numbers is reported).
- `grd-ai-amount-words`: the guard on AI summaries stops `₹`, `Rs` and `INR` amounts, but not "4999 rupees".
- `grd-ai-place`, `grd-ai-chat`: a place or detail an AI invents is shown. The made-up fact checks only record and
  flag (an earlier, deliberate choice), and only while records are on.
- `grd-ai-budget`, `grd-ai-days`: when the budget or trip length is missing and an AI supplies one, the planner
  uses it without a note, instead of asking.
- `rp-cheaper-hotel-result`, `rp-cheaper-flight-result`: "cheaper" lowers the level of the whole plan, so asking
  for one changes the other and the activities too.
- `rp-…-agents` (cheaper hotel, cheaper flight, to train, one more person, no adventure, more history): every
  change searches travel, hotels and activities again. This is one cause, in `agents/supervisor.py`.
- `rp-flight-to-train-result`: "change flight to train" is not understood ("switch to train" is).

**Not supported:** several destinations in one trip, flexible dates, source links, ratings, amenities, live
availability offline, opening hours, verified entry fees, weather retrieval times, sources for destination facts,
extra budget lines and other currencies. For several destinations and flexible dates the planner also does not
tell the traveller. Also: a link and retrieval time on travel, hotel, weather and places data (a live fare has a
time but no link); swapping outdoor for indoor activities, replacing the interests or adding a named group member
after planning; and trip versions (the earlier plan is overwritten).

## Self-checks and planted mistakes

A self-check runs the planner, then changes its output (`input.damage`: `set`, `delete`, `append` or `copy_from`
on a dotted path). It passes only if exactly the checks in `expected.finds` fail. A path that does not exist is an
error. A test also runs each one without the damage and requires a clean result.

## Adding a case

Add an object to the part's file in `datasets/` with `id` (unique), `description`, `category`, `target` (`planner`
or `self_check`), `input` (usually `request`; also `group`, `failures`, `changes`, `approve`, `ai`, `ask`, `live`), `expected_constraints`
(limits such as `min_preference_share`) and `expected` (properties of a right answer). Copy the nearest existing
case. Work out budget figures by hand, and write money as text (`"1500.50"`). Check properties of a plan, not
exact wording. `test_framework_agents.py` and `test_framework_stage3.py` in `app/tests/test_evaluation/` list the
expected failures and unsupported cases; update them when they change.

Not built yet: the AI judge, and speed and cost figures per agent.
