# Evaluate saved forecasts across declared time origins

The separate [journal adapter](journal-forecast.md) reconstructs a single
issuance from an explicit receipt prefix. Different receipt cutoffs change
historical provenance revisions and are not automatically compatible with
this evaluator's immutable-prefix policy.

Use the separate [receipt-version evaluation](journal-evaluation.md) when
origins need corrected historical observations at their own journal cutoffs.
Its target versions are fixed by a schedule and historical differences are
reported explicitly; it does not weaken the policy documented here.

The `forecast plan` and `forecast evaluate` commands extend the separate
[prediction and scoring workflow](behavior-forecast.md) to several forecast
origins. They answer a reproducible evaluation question: **does the network
feature improve predictions across all the time periods that were specified?**

The models remain persistence, own-lag OLS and own-lag OLS with the outgoing
neighbor behavior gap. A new wave can contain changed relationships and changed
behavior. This profile does not add a network-change regressor or estimate a
causal effect of a particular conflict, utterance, relationship or community
change. The recorded execution is an invented engineering example, not a new
empirical multi-origin accuracy result.

## Declare the periods before evaluating them

Create a plan from the initial history and the first forecast specification:

```bash
python -m sociolab forecast plan examples/forecast-evaluation/initial.history.json examples/forecast-evaluation/initial.spec.json --targets 2 3 4 5 > /path/to/plan.json
```

Planning does not fit a model or accept target observations. The plan binds the
initial history, roster hash and count, dataset/source, behavior scale,
measurement reference, research question, model profile, training policy and
complete schedule. Its content hash records that declaration; it is not an
external timestamp or evidence that the author had never seen the outcomes.

The schedule has at least two consecutive one-step targets at the same positive
wave-index gap. Each forecast history stays within the existing limits of
200 actors and 32 historical waves. The first target is immediately after the
initial history. Models, scale and research question stay the same; only the
specification's target time changes between origins.

The six-wave example follows this schedule, using zero-based wave indices:

| Origin | Supplied history | Known training transitions | Target |
| ---: | --- | --- | ---: |
| 1 | 0, 1 | 0 → 1 | 2 |
| 2 | 0, 1, 2 | 0 → 1; 1 → 2 | 3 |
| 3 | 0, 1, 2, 3 | 0 → 1; 1 → 2; 2 → 3 | 4 |
| 4 | 0, 1, 2, 3, 4 | 0 → 1; 1 → 2; 2 → 3; 3 → 4 | 5 |

A target becomes historical information for the next origin after it is
observed. It never enters its own prediction. This is the chronological
principle of [time-series cross-validation](https://otexts.com/fpp3/toolbox.html#time-series-cross-validation).
The evaluator does not perform random train/test splitting, future-dependent
roster intersection, scale inference or tuning.

## Keep issuance and evaluation separate

For each declared origin, supply only that origin's history to the existing
`forecast create` command. Save its JSON output before obtaining its separate
target file. The existing `forecast score` command can then produce a one-origin
score without fitting again.

The final evaluator receives an ordered manifest of **saved histories,
predictions and targets**. It recomputes every score from those inputs. An
unverified score file is not accepted as the source of accuracy measurements.

```json
{
  "schema": "sociolab.behavior-forecast-fold-manifest.v1",
  "folds": [
    {"history": "history-2.json", "forecast": "forecast-2.json", "target": "target-2.json"},
    {"history": "history-3.json", "forecast": "forecast-3.json", "target": "target-3.json"},
    {"history": "history-4.json", "forecast": "forecast-4.json", "target": "target-4.json"},
    {"history": "history-5.json", "forecast": "forecast-5.json", "target": "target-5.json"}
  ]
}
```

Paths resolve relative to the manifest's directory; absolute paths also work.
They are file locations, not research identities, and are omitted from the
evaluation report.

```bash
python -m sociolab forecast evaluate /path/to/plan.json /path/to/private/fold-manifest.json > /path/to/evaluation.json
```

The evaluator never calls the fit routine. It checks saved forecast integrity,
recalculates target errors and aggregates them without rewriting inputs. The
report includes every per-origin aggregate score and its hash, both
network-versus-baseline comparisons, and whole-plan metrics. It contains no
roster IDs, individual predictions, individual outcomes or individual errors.

Prediction artifacts, histories and targets still contain actor-level records
and belong with private source data. Aggregate output and content hashes do not
constitute authorship authentication or proof of actual historical availability.

## Require complete chronological coverage

The fixed training policy is `expanding_immutable_prefix`. The implementation
checks full supplied values, not just revision names:

- The first history must match the plan's initial history hash.
- Every later history adds exactly one wave to the preceding history. All
  previously supplied waves, including their observations and revisions,
  remain identical.
- The added wave's behavior must equal the preceding separately scored target.
  Its source revision need not equal the target revision: a network-and-behavior
  wave and a behavior-only target can have different content identities.
- Each forecast binds its own history content hash, correct origin/target,
  identical fixed roster and source, and the plan's unchanged specification
  apart from the target index.
- Every planned target must occur exactly once and in order. Missing, duplicate,
  reordered or substituted periods fail evaluation. Missing individual target
  outcomes continue to fail under the existing complete-data profile.

New waves may introduce genuine network and behavior changes; the immutable
requirement concerns **rewriting an already supplied historical wave**. Late
corrections or revised measurement policies require separately declared
versioned analysis, preserving earlier forecasts. They are not silently mixed
into this plan. A future journal bridge that allows newly received revisions
needs its own explicit historical-version policy.

The initial fixed roster must itself be defensible. Checking it against a plan
does not prove that its author chose it without knowing future attrition.
Source admission and receipt history remain separate requirements.

## Whole-plan metrics and non-estimable models

The predeclared primary metric is **clipped pooled MAE**; pooled RMSE is
secondary, and macro metrics are reported alongside them.

For each model and raw/clipped prediction variant, let a fold have `n_f`
evaluated actors, `MAE_f` and `RMSE_f`. The evaluator reports:

$$
\operatorname{MAE}_{pooled}=
\frac{\sum_f n_f\operatorname{MAE}_f}{\sum_f n_f},\qquad
\operatorname{RMSE}_{pooled}=
\sqrt{\frac{\sum_f n_f\operatorname{RMSE}_f^2}{\sum_f n_f}}.
$$

The `macro` metrics are the arithmetic means of the per-fold MAEs and RMSEs.
With the same complete roster in every fold, pooled MAE equals macro MAE.
Pooled RMSE generally differs from macro RMSE. For example, two equal-sized
folds with RMSE 0 and 2 have pooled RMSE `sqrt(2)` and macro RMSE 1.

Network-minus-own and network-minus-persistence differences are computed from
the corresponding pooled or macro metrics. The average of per-fold RMSE
differences is not called a pooled RMSE difference.

All planned folds stay visible. If a model is `NOT_ESTIMABLE` at any origin,
its whole-plan metrics are null and its available/expected fold and
actor-forecast counts are reported. Baselines that are estimable everywhere
retain their whole-plan metrics. A whole-plan comparison is available only
when both models are estimable at every planned origin. The evaluator does not
drop inconvenient folds or compare a partial network result to a complete
baseline result.

The report distinguishes unique `actor_count`, temporal `fold_count`, and
`actor_forecast_count`. Repeated forecasts of one person are not new people.
Overlapping training histories and social ties also create dependence; the
report supplies no IID standard error, row bootstrap, confidence interval,
significance test or automatic stability qualification.

## Run the complete invented example

The fixture has six manually authored waves and four invented actors. Its
purpose is to exercise the ordering, saved-file and arithmetic contracts.
It is not fitted simulation data or a sample of real behavior.

```bash
python docs/experiments/2026-11-28-forecast-evaluation/run_synthetic_evaluation.py --private-directory /path/to/fresh-private-directory --output /path/to/aggregate-evidence
```

The runner requires a fresh private directory outside the checkout and separate
public output paths. It saves the plan, issues each prediction in its own CLI
process, and only then constructs that prediction's target artifact. It saves
individual scores and checks that the final evaluation reproduces them.
Prediction and input files must retain their exact hashes throughout scoring
and evaluation.

The complete invented fixture is known to the runner. This process order is
engineering evidence, not a blind or prospective experiment. The generic
`evaluate` command itself cannot establish when external observations arrived.

The [fixed protocol](experiments/2026-11-28-forecast-evaluation/protocol.json)
was saved before executing this example. Execution and independent arithmetic
verification are recorded alongside it.

### Recorded engineering result: 2026-11-28

All four planned origins completed for the same four invented actors:
**4 unique actors, 4 origins, 16 actor-forecasts**. These are arithmetic
reference values for reproducing this implementation, not measurements of
social predictive performance.

| Target index | Persistence MAE | Own-lag MAE | Network MAE |
| ---: | ---: | ---: | ---: |
| 2 | 0.500000000 | 0.500000000 | 0.469696970 |
| 3 | 1.000000000 | 0.785714286 | 0.866666667 |
| 4 | 0.500000000 | 0.500000000 | 0.500000000 |
| 5 | 1.000000000 | 0.750000000 | 0.699275362 |

| Model | Clipped pooled MAE | Clipped pooled RMSE | Clipped macro RMSE |
| --- | ---: | ---: | ---: |
| Persistence | 0.750000000 | 0.866025404 | 0.853553391 |
| Own lag | 0.633928571 | 0.693409206 | 0.681813705 |
| Own lag and network | 0.633909750 | 0.697382825 | 0.678893966 |

No predictions required clipping. The files retain unrounded values; the
tables round for display. The individual periods and distinct aggregation
methods remain visible instead of being reduced to a single model ranking.

Verification evidence:

- [Saved plan](experiments/2026-11-28-forecast-evaluation/plan.json) and
  [full evaluation](experiments/2026-11-28-forecast-evaluation/evaluation.json)
  bind every declared period and contain only aggregate metadata, errors
  and hashes.
- [Execution record](experiments/2026-11-28-forecast-evaluation/execution.json)
  records 10 actual CLI steps, including a saved prediction before each target
  artifact. All private inputs and the plan retained their file hashes, and
  every aggregate fold score equals its separately saved score.
- [Native test record](experiments/2026-11-28-forecast-evaluation/tests-execution.json)
  and [log](experiments/2026-11-28-forecast-evaluation/native-tests.log):
  **309 tests passed**, including 19 added tests, with no skips.
- [Independent check](experiments/2026-11-28-forecast-evaluation/independent-check.json):
  **900 checks, including 132 numeric comparisons, passed**, maximum absolute
  difference `1.1102230246251565e-16` with `rtol=atol=1e-12`. The checker uses
  only the Python standard library, directly pools saved individual errors,
  and neither imports SocioLab nor refits coefficients. It verifies input
  identity and aggregation, not the regression solver or empirical accuracy.
- [Validation manifest](experiments/2026-11-28-forecast-evaluation/validation.json)
  retains the artifact checks, qualification limits and file fingerprints.

## Why no new real multi-origin result is claimed

The existing s50 case has three waves. With two known waves required for the
first fit, it provides one held-out target. Multiple origins require at least
four suitable waves; repeating the same target does not add a new origin.

The [official Knecht tutorial data](https://www.stats.ox.ac.uk/~snijders/siena/tutorial2010_data.htm)
describe four network and delinquency waves, but include missing observations
and changing class membership. The alcohol variable has only three waves.
This source has not been admitted to the current complete, fixed-roster
forecast profile. See the [documentation-only source review](forecast-source-admission.md)
for exact encodings, scope and remaining checks.

No future leaver or future missing respondent was removed to manufacture a
complete sample. No unknown edge was changed into an absent edge. No additional
real-data fit or score was run for this feature.

## Python API

```python
from sociolab.panels import load_panel
from sociolab.behavior_forecast import (
    load_behavior_forecast_spec, load_behavior_forecast, load_behavior_target,
)
from sociolab.forecast_evaluation import (
    make_behavior_forecast_plan, load_behavior_forecast_plan,
    evaluate_behavior_forecasts,
)

plan = make_behavior_forecast_plan(
    load_panel("initial.history.json"),
    load_behavior_forecast_spec("initial.spec.json"),
    [2, 3, 4, 5],
)
# Save plan; separately issue and save each forecast, then obtain its target.
folds = [
    {
        "history": load_panel(f"history-{time}.json"),
        "forecast": load_behavior_forecast(f"forecast-{time}.json"),
        "target": load_behavior_target(f"target-{time}.json"),
    }
    for time in [2, 3, 4, 5]
]
report = evaluate_behavior_forecasts(load_behavior_forecast_plan("plan.json"), folds)
```
