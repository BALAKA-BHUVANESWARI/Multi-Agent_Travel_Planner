# Evaluation framework (stages 1 and 2)

From the `backend` folder:

```
python -m evaluation.run_evaluation                      # everything that is built
python -m evaluation.run_evaluation --agent budget       # one part; --help lists the names
python -m evaluation.run_evaluation --deterministic-only
```

Reports go to `.runtime/evaluation/` (`report.md` and `report.json`). The command ends with code 1 when a case
failed. It runs offline with a fixed date, uses no AI and needs no key. All test data is **synthetic**.

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

"Provider's answer" offline means the application's own **price estimator**. These checks show that the plan
repeats it faithfully and labels it as an estimate. They say nothing about real prices or availability. The same
holds for destination tags and seasons: there is no outside source to verify them. The end-to-end cases use the
built-in runner, not LangGraph.

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

**Not supported:** several destinations in one trip, flexible dates, source links, ratings, amenities, live
availability offline, opening hours, verified entry fees, weather retrieval times, sources for destination facts,
extra budget lines and other currencies. For several destinations and flexible dates the planner also does not
tell the traveller.

## Self-checks and planted mistakes

A self-check runs the planner, then changes its output (`input.damage`: `set`, `delete`, `append` or `copy_from`
on a dotted path). It passes only if exactly the checks in `expected.finds` fail. A path that does not exist is an
error. A test also runs each one without the damage and requires a clean result.

## Adding a case

Add an object to the part's file in `datasets/` with `id` (unique), `description`, `category`, `target` (`planner`
or `self_check`), `input` (usually `request`; also `group`, `failures`, `changes`, `approve`), `expected_constraints`
(limits such as `min_preference_share`) and `expected` (properties of a right answer). Copy the nearest existing
case. Work out budget figures by hand, and write money as text (`"1500.50"`). Check properties of a plan, not
exact wording. `app/tests/test_evaluation/test_framework_agents.py` lists the expected failures and unsupported
cases; update it when they change.

Not built yet: grounding, change-request (re-planning) checks and the AI judge.
