# Repeat-interaction evaluation across planned origins

This is the second engineering slice of [R1 / #21](https://github.com/qigao/SocioLab/issues/21).
It evaluates saved predictions across a declared sequence of times using the
[existing three repeat-interaction baselines](repeat-interaction.md). Its purpose
is to reveal changes in error, risk composition and observation coverage across
time. It introduces no predictor or model dependency.

## What the plan fixes

The plan binds an eligible initial history at its explicit receipt cutoff K,
the fixed actor roster and alias map, action/topic stream, historical start,
recent-window duration, prediction horizon, all origin windows and probability
bin boundaries. Later origins use expanding history from the same start; each
origin freezes the ordered pairs with a positive event in **its own** known
history. Target events never add pairs to an already saved prediction.

A schedule has exactly these fields:

```json
{
  "schema": "sociolab.repeat-interaction-schedule.v1",
  "probability_bins": [0, 0.2, 0.4, 0.6, 0.8, 1],
  "folds": [
    {"origin_at": 20, "recent_start": 15, "target_end": 30},
    {"origin_at": 30, "recent_start": 25, "target_end": 40},
    {"origin_at": 40, "recent_start": 35, "target_end": 50}
  ]
}
```

The first window must match the initial specification. There must be 2–100
origins, with increasing nonoverlapping target windows. Recent and target
durations stay constant; gaps between target windows are allowed and remain
outside the declared evaluation. Tick clocks use nonnegative integers; UTC
clocks use explicit Z/+00:00 timestamps with exact microsecond arithmetic.

The first scheduled fold uses the initial K if its saved prediction is supplied.
Later history cutoffs may **stay equal or increase**: advancing a timer does not
require a new receipt. Future receipt counts are supplied with the actual saved
forecasts, not guessed when planning. History specifications must otherwise
match the planned windows and initial contract, including the observation
reference. The same reference can name the observation protocol across origins.

Creating or replaying a plan only consumes its initial K. A supplied journal
tail beyond that K does not affect the plan. Every actual forecast still passes
the original raw-future-assertion gate and is rebuilt from its own historical
prefix when scored. A malformed or altered forecast raises an error; it cannot
silently turn into an ordinary missing observation.

The plan contains actor identities and is a **private input artifact**. Its hash
binds the supplied content but does not authenticate the author, historical
availability, prospective registration or issuance time. Rebuilding the initial
closed-form prediction to validate a plan does not establish that a prediction
was actually issued before the outcome. These are engineering guarantees about
the supplied journal, not evidence that a real dataset has passed admission.

## Every planned origin remains visible

Evaluation takes one ordered input slot per planned origin:

```python
from sociolab.repeat_evaluation import (
    make_repeat_interaction_plan, evaluate_repeat_interaction_forecasts,
)

plan = make_repeat_interaction_plan(initial_dataset, initial_specification, schedule)
report = evaluate_repeat_interaction_forecasts(final_dataset, plan, [
    {"origin_at": 20, "forecast": saved_forecast_20, "target": target_declaration_20},
    {"origin_at": 30, "forecast": saved_forecast_30, "target": target_declaration_30},
    {"origin_at": 40, "forecast": None, "target": None},
])
```

A null/null slot is labeled `FORECAST_NOT_SUPPLIED`. Its risk count is `null`,
not zero. This label records a missing saved input; it does not prove that no
forecast was ever issued or authenticate a reason for the omission. Supplying
a damaged forecast instead raises. A slot with a forecast must include a target
declaration; an immature target can use the existing `observed_through` boundary
at or after the origin and will be unscored until closure.

Each supplied slot retains its aggregate v1 score, target K, source observation
reference, target prefix/snapshot hashes and diagnostic hash. Missing slots
cannot disappear merely because another origin was easier to score. The report
exposes these different denominators:

| Field | Meaning |
| --- | --- |
| `planned_origins` | All scheduled prediction times. |
| `supplied_forecast_origins` / `missing_forecast_origins` | Saved-input availability across that schedule. |
| `scorable_origins` | Origins with at least one fully observed pair. |
| `fully_scored_origins` | Origins with a nonempty risk set and all its pairs scored. |
| `risk_pairs_across_supplied_origins` | Sum of risk-pair counts in the supplied forecasts. |
| `scorable_pairs_across_supplied_origins` | Pair-origin observations entering every model's score. |
| `unscored_pairs_across_supplied_origins` | Known risk-pair observations excluded for follow-up, membership or coverage. |
| `full_plan_risk_pair_origin_count` | The same known risk total only if all predictions are supplied; otherwise `null`. |

Positive/negative evidence counts and mutually exclusive exclusion reasons also
sum across supplied origins. A repeated ordered pair contributes one observation
per origin; these are **pair-origin observations**, not independent people,
relationships or independent trials. Aggregate output contains no pair-level
rows. Caller-supplied observation references are carried through unchanged, so
they should not contain personal information intended to remain private.

## Error and probability diagnostics

All three models use exactly the same complete-follow-up pairs, through the
original scorer's qualification and target-label logic. Known positives with
partial follow-up stay visible as evidence and remain excluded from all model
scores and bins.

For origin f with n_f scored observations and Brier score B_f:

```text
pooled_brier = sum(n_f * B_f) / sum(n_f)
macro_brier  = sum(B_f) / planned_origin_count
```

Pooled Brier weights each **scorable pair-origin observation** equally. It
describes the observed subset and must be read beside its coverage denominators.
Macro Brier weights each planned origin equally and is `null` if any origin is
missing or has no scored pair. An origin with some excluded pairs still has a
subset Brier, so macro may be defined for a partially scored report; it does
not repair selection from missing coverage. No scored observations produces
null error and probability metrics for every model.

`probability_bins` contains 2–21 finite strictly increasing edges, starting at 0
and ending at 1. A bin includes its left edge and excludes its right edge; the
last bin also includes 1. Empty bins remain in the report with zero counts and
null means. Each bin reports count, probability sum, positive count, squared
error sum, mean prediction, observed fraction and Brier score. These additive
totals support transparent aggregation across origins.

The API `diagnose_repeat_interaction_forecast(dataset, forecast, target, bins)`
also exposes these aggregates for one forecast. Its `score` field is exactly the
existing `sociolab.repeat-interaction-score.v1` output; the original score schema,
values and hashes are preserved. Both paths share one qualification/label pass.

Bins are **descriptive probability diagnostics**, not a fitted calibrator or a
finding that predictions are calibrated. No independent-sample confidence
interval, p-value, model selection or parameter fitting is performed. New
probability boundaries require a different plan and therefore a different plan
hash; the code cannot prove that a user chose the plan before seeing outcomes.

## Changing risk sets and corrected evidence

For adjacent supplied origins, the report gives a hash of each ordered-pair
risk set and counts of retained, newly included and removed pairs. Even with
expanding history, later corrections can retract an old event and remove a
previously eligible pair. Risk-set changes are changes in this prediction
population; they do not establish formation or dissolution of relationships.

The first origin has no comparison. A missing origin also breaks comparison:
the next saved forecast is not silently compared across that gap. Actor IDs
are not included in these change summaries.

Target cutoffs are explicit per fold and per evaluation. A corrected first
target can be scored at a later K than the second target without rewriting the
second origin's history. The earlier target version need not equal the next
origin's historical view. Reusing the original declarations after appending
corrections reproduces the original report. Selecting revised target cutoffs
produces a new report hash while retaining the saved predictions. Callers remain
responsible for retaining old files; stdout does not make files immutable.

## Commands

```sh
python -m sociolab forecast interaction-plan history.events.json initial-spec.json schedule.json > plan.json
python -m sociolab forecast interaction-create history-at-20.events.json spec-at-20.json > forecast-20.json
python -m sociolab forecast interaction-create history-at-30.events.json spec-at-30.json > forecast-30.json
python -m sociolab forecast interaction-evaluate final.events.json plan.json folds.json > evaluation.json
```

The `interaction-create` command continues to take a full specification. Copy
the fixed initial contract, update its three planned window fields and provide
the actual receipt K. Issuance is explicit; no live subscription or timer hook
automatically creates forecasts in this change.

The CLI manifest resolves forecast and target file paths relative to the
manifest, not the current working directory:

```json
{
  "schema": "sociolab.repeat-interaction-fold-manifest.v1",
  "folds": [
    {"origin_at": 20, "forecast": "forecast-20.json", "target": "target-20.json"},
    {"origin_at": 30, "forecast": "forecast-30.json", "target": "target-30.json"},
    {"origin_at": 40, "forecast": null, "target": null}
  ]
}
```

The target files use the unchanged `sociolab.repeat-interaction-target.v1`
contract. Raw individual events and saved pair predictions remain private
inputs. See the [source admission review](repeat-interaction-source-review.md)
for the actual evidence examined this round. No reviewed candidate was upgraded
to complete observation by constructing missing membership or coverage records.

## Validation scope

Native tests exercise unequal fold sizes, independent closed-form expectations,
probability-bin boundaries, incomplete follow-up, partial coverage, missing
origins, risk removal after history correction, equal K at successive timer
origins, independently revised target versions, tail-invariant replay, UTC
microseconds, malformed artifacts and real CLI parsing/path resolution.

These authored cases establish software behavior. They do not estimate the
predictive quality of any baseline on people. Source admission, genuine future
evaluation, dependent-observation uncertainty, latent relationship measurement,
language interpretation, motivation and causal identification remain separate
research requirements in R1–R6.

### Executed validation — 2026-11-28

The [native execution record](experiments/2026-11-28-repeat-evaluation/tests-execution.json)
and [complete log](experiments/2026-11-28-repeat-evaluation/native-tests.log)
record **479 passing tests**, including **25 new tests**, in 10.843 seconds,
with no failures, errors or skips. Source and test file hashes were unchanged
during execution. Four pre-refactor single-origin score identities—complete,
partial, immature and empty—remain unchanged in the compatibility checks.

This run used the existing Python environment and native suite. It installed
no dependency and added no CI workflow or installer/consumer test. No real-source
prediction experiment was executed or qualified by this software validation.
