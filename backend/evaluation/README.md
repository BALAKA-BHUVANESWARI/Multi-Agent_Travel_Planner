# Evaluation framework

It answers four questions: is the planner right, can the checks be trusted, what does a reader think of the
plans, and what does it cost in time and money. All test data is **synthetic**.

**Contents:** [Running it](#running-it) · [Reading the report](#reading-the-report) ·
[What is checked and why](#what-is-checked) · [AI judge](#ai-judge) · [Speed and cost](#speed-and-cost) ·
[What needs a key](#what-needs-a-key-and-what-is-pretend) · [Adding a case](#adding-a-case) ·
[LangSmith](#langsmith)

## Running it

From the `backend` folder:

| Command | What it does | AI key |
|---|---|---|
| `python -m evaluation.run_evaluation` | every fixed check, plus offline speed figures | no |
| `... --agent budget` | one part (`--help` lists the names) | no |
| `... --deterministic-only` | the fixed checks; the judge can never start | no |
| `... --records [--period today\|7d\|30d\|all]` | adds speed figures from your own recorded use | no |
| `... --prices prices.json` | works out AI cost from your prices | no |
| `... --judge-list` | shows what the judge would do; calls nothing | no |
| `... --judge [--judge-limit N]` | also asks the AI judge | **yes** |
| `... --agent llm_judge --judge` | the judge only | **yes** |
| `python -m pytest app/tests/test_evaluation` | tests of the evaluators themselves | no |

Reports go to `.runtime/evaluation/` (`report.md` for reading, `report.json` for programs) and are replaced on every
run. Each judge run is also kept in `.runtime/evaluation/judge/`. Exit codes: **0** nothing failed, **1** a case
failed or broke (with the known failures below this is expected), **2** it could not start. With
`--agent llm_judge` it is 1 only when nothing could be scored. `--out` changes the folder.

The older evaluations (`evals/` and the dashboard's Evaluations tab) are unchanged.

## Reading the report

1. **Summary.** Look at the two rows separately. If a *self-check* fails, an evaluator is broken: fix that before
   trusting any planner result.
2. **By agent / by category** show where failures are.
3. **Measures** are averages such as the share of activities that match the interests. A share with few cases says
   little.
4. **Failed cases** give a code and the reason. Compare with *Known failures* below: a new id is a change in
   behaviour.
5. **Not supported** is a list of missing features, not of passes. **Warnings** are worth reading but never fail.
6. **Time, tokens and cost** and the **AI judge** come last. Neither changes any pass rate.

A high pass rate means the plans agree with the rules in these cases. It does not mean prices, weather or opening
times are true.

## Two scores that are never mixed

- **Planner:** is the application right?
- **Evaluator self-checks:** made-up data with planted mistakes. Do the checks find exactly those?

**Not supported** means the application cannot do what the case asks. **Not run** and **not supported** are never
counted as passed. Pass rate = passed / (passed + failed + errors).

## What is checked

### Why each part matters

| Part or measure | Why it matters |
|---|---|
| supervisor | a wrong route wastes calls or plans without the facts it needs |
| destination | a poor suggestion sends the traveller to the wrong place |
| transport, accommodation | usually most of the money; a wrong date, room count or price spoils the budget |
| weather | an outdoor day in heavy rain is a lost day |
| activity | this is what the traveller travels for |
| budget | a wrong total can leave someone short of money on the trip |
| itinerary | clashes and missing days make a plan impossible to follow |
| group | one person's wishes can silently disappear |
| end_to_end | correct parts can still be joined wrongly |
| grounding | made-up details look exactly like real ones |
| replanning | a small change must not undo choices the traveller was happy with |
| pass rate | whether behaviour got better or worse, on these cases only |
| share matching interests / in season | how well plans fit, beyond pass or fail |
| time per agent and per plan | shows where waiting comes from |
| tool, lookup and workflow failure rates | how often the traveller gets a thinner plan or none |
| retries | hidden waiting and extra calls on a free allowance |
| cache hit rate | how many calls were saved |
| tokens and cost | whether free limits will last, and what paid use would cost |

### Pass rules


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

The five `grd-ai-…` cases that used to fail here pass since `app/services/ai_guard.py`: an AI summary or chat
answer with an unsupported amount, date, place or listed feature is not shown, and an AI budget or trip length counts
only when the traveller's words state it. They test these particular inventions; they do not show that nothing made
up can ever get through.

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

A judge case goes in `datasets/judge_cases.json`: `target` is `judge` or `judge_check`, `input.request` (and
`group`), `expected_constraints` (what the judge is told was wanted) and `expected.dimensions`. A `judge_check` also
has `input.plant` (`add_to_summary`, `rename_activities` or `scramble_summary`) and `expected.must_list`, or
`expected.compare_with` with `expected.lower_on`. Each judge case costs one AI call per run.

## AI judge

The judge (`judge.py`, cases in `datasets/judge_cases.json`) gives opinions on what rules cannot measure. It is
**not** the source of truth: its scores never pass or fail anything and are never added to a pass rate. It is told
not to check sums, dates, times, data format, prices or availability.

It is sent the request, the expected constraints, the written plan (without the mock booking), the planner's notes,
the group report and a shortened copy of the source records. The plans are built offline by the app's rules and
templates, so no AI wrote the text being judged. Only these made-up requests are sent to the provider.

**Rubric.** Each quality is scored 1 to 5. Every score has its own description (`RUBRIC` in `judge.py`), and the
judge must give a reason for each.

| Quality | Question | 1 means | 5 means |
|---|---|---|---|
| destination relevance | Does the plan suit the destination and what the traveller asked of it? | The plan is about the wrong place, or ignores what was asked of the destination. | It clearly fits this destination and every stated wish. |
| explanation quality | Does the plan explain its choices and say what is uncertain, estimated or missing? | No explanation; limits or estimates are hidden or misleading. | Choices, trade-offs, estimates and gaps are all clearly explained. |
| activity relevance | Do the activities match the traveller's interests and the kind of trip? | The activities have nothing to do with the interests or the place. | Nearly all match the interests and suit this trip. |
| itinerary coherence | Do the days make sense as a trip: grouping, variety and flow? (Not exact times or sums.) | The days are jumbled and could not be followed. | Every day hangs together, with a natural flow and good variety. |
| group balance | Does each person in the group get a fair share of what they like, and is any compromise stated? | One or more people are ignored entirely and nothing says so. | A fair share for everyone, with compromises clearly explained. |
| clarity usefulness | Could a traveller read this and act on it? | Unreadable or of no practical use. | Very clear, well organised and ready to act on. |

Group balance is asked about group trips only. The judge also lists statements the source records do not support.
Each is marked if its words are not found in the plan, because a judge can make things up too. Check them yourself.

**Testing the judge.** Three cases plant a problem: an invented hotel feature (it should be listed), unrelated
activities (their relevance should score lower than in the normal plan) and a plan with its words shuffled (clarity
should score lower). The report says how many were noticed. One run is a small sample: the same model can score
differently another time.

**Its own model.** In `.env`, `JUDGE_PROVIDER` (`groq`, `gemini` or `ollama`), `JUDGE_MODEL` and `JUDGE_API_KEY`
give the judge a separate model. All three are optional; without them it uses the first provider that has a key.
`JUDGE_MODEL` needs `JUDGE_PROVIDER`.

**Limits.** One call per case (9 now), plus retries, never more than 100 a run, or `--judge-limit`. The
saved-answer cache is off, calls count toward the app's daily limit, it pauses between calls and waits a minute
after "too many requests", so a free tier can make a run take several minutes. If you stop it with Ctrl+C, the
finished scores are saved and reported, the other cases are marked *not run* and the exit code is 130. A new run
starts from the first case again. After three unanswered cases in a row the rest are marked *not run*. A reply that
does not fit the rubric is *invalid* and is never scored.

## Speed and cost

Two sources, shown separately. The sums are the dashboard's (`app/observability/analytics.py`).

- **Offline** (in every full run): the whole-trip test requests without made-up outages, three times each, recorded
  in memory. It measures the app's own steps on that computer. No AI or outside service is called, so it says
  **nothing about live speed**.
- **Your records** (`--records`): what the app recorded while you used it, with real AI calls and data lookups.
  Records are only read. Only counts, times, source and model names are used, never typed text.

Both give time per agent and per request, tool calls, failures and retries, workflow failure rate, automatic
re-plans, AI calls, tokens in and out (marked when estimated), AI and lookup cache hit rates, and time and failures
per data source. "Median" is the middle value; "p90" is the time that 9 in 10 stayed within. A rate with nothing to
count is **not measured**. Percentiles from a few requests move a lot.

**Cost** is worked out only from prices you give: no price is built in. Create a JSON file with your provider's
current prices per million tokens, replacing the words in angle brackets with numbers:

```
{"currency": "USD",
 "models": {"<model name as shown in the report>": {"input_per_million": <price>, "output_per_million": <price>}}}
```

Pass it with `--prices`, or set `EVAL_PRICES` in `.env`. It is used for the judge's calls and, with `--records`,
for recorded calls. A model without a price makes the total **partial**. Voice is not included. It is an estimate
from token counts, not a bill; a free plan may charge nothing.

## What needs a key, and what is pretend

| Part | Needs an AI key | What stands in |
|---|---|---|
| every fixed check | no | the app's offline price estimator, built-in place and weather data |
| live price grounding cases | no | saved real Google pages in `app/tests/fixtures/`; a made-up exchange rate |
| AI invention cases | no | a scripted **pretend AI** |
| failures and outages | no | tools told to fail |
| change requests, whole trips | no | the built-in runner (not LangGraph) |
| all pytest tests, the judge's too | no | a **pretend judge**, including broken replies and service errors |
| offline speed figures | no | nothing is called |
| your records | no | your own earlier use (that use needed keys if it called an AI) |
| `--judge` | **yes** | nothing: a real model is called |

Passing pytest shows that the judge code handles replies correctly. It says nothing about how well a real model
judges; only the planted problems in a real run give a hint of that. The older live AI tests
(`evals/run_live_evals.py`) also need a key.

## LangSmith

LangSmith is **not included**, by choice: it would send run data to an outside service. There is nothing to
configure and no setting turns it on. Local records, the dashboard and these reports cover tracing and evaluation.
