# Evaluation framework (stage 1: budget and itinerary)

From the `backend` folder:

```
python -m evaluation.run_evaluation                      # everything that is built
python -m evaluation.run_evaluation --agent budget       # or: itinerary
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

## Known finding

`plan-goa-monsoon` fails: when every day is rainy, the planner replaces all beaches, does not say that the only
interest was dropped, and fills several slots with a general indoor suggestion.

## Adding a case

Add an object to `datasets/budget_cases.json` or `datasets/itinerary_cases.json` with `id` (unique), `description`,
`category`, `target` (`planner` or `self_check`), `input`, `expected_constraints` and `expected`. Copy the nearest
existing case. Work out budget figures by hand, and write money as text (`"1500.50"`). Check properties of a plan,
not exact wording.
