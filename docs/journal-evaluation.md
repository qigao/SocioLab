# Evaluate forecasts across received journal versions

`forecast journal-plan` and `forecast journal-evaluate` evaluate saved
predictions when later origins legitimately know corrected historical data.
Each origin has its own history receipt cutoff and an independently declared
target receipt cutoff. The evaluator reconstructs both versions from the same
journal, verifies the saved artifacts and reuses the existing scorer and
aggregation code. It never fits a model.

This extends the [single-origin journal adapter](journal-forecast.md). The
[immutable-prefix evaluator](forecast-evaluation.md) remains unchanged and
continues to reject revised history within its own policy.

## What changes across origins

For origin i, let K be its history cutoff and L its target cutoff:

| Object | Source |
| --- | --- |
| Historical networks and behavior | Reconstructed at K for all declared historical source instants. |
| Saved prediction | Must match that complete reconstructed history and the fixed forecast specification. |
| Scoring target | Reconstructed at L for the scheduled target instant; the saved target must match, including its source revision. |
| Next origin's training labels | Reconstructed at the next origin's own K; these may include corrections received after the preceding prediction. |

A previous scoring target and the behavior later used as a training label can
therefore differ. The evaluator preserves both versions and reports their
aggregate difference. It does not copy the previous target into the next
history or require them to be equal.

Two policies remain explicit:

| Policy | Historical revision rule |
| --- | --- |
| `expanding_immutable_prefix` | Every earlier wave, including its revision, stays identical; the added behavior equals the preceding scored target. |
| `expanding_as_known_receipt_prefix` | Each origin adds exactly one source wave and reconstructs the entire history at that origin's K. Old values or provenance can change through received source evidence. |

Both retain all planned folds, the fixed roster and the declared models and
scale. A revised history cannot be passed to the first policy by changing a
flag or discarding its provenance.

## Freeze the receipt schedule

Plan creation requires a journal ending **exactly at the initial history
cutoff**. It accepts the initial journal-history specification and a schedule
of at least two future targets. Future cutoff numbers may exceed the initial
journal length: they are declarations, not data already available to planning.

The original invented schedule is:

```json
{
  "schema": "sociolab.journal-forecast-schedule.v1",
  "folds": [
    {
      "target_time_index": 2,
      "target_at": 20,
      "history_knowledge_cutoff": 24,
      "target_knowledge_cutoff": 28
    },
    {
      "target_time_index": 3,
      "target_at": 30,
      "history_knowledge_cutoff": 36,
      "target_knowledge_cutoff": 40
    }
  ]
}
```

History cutoffs strictly increase. A target cutoff must be strictly later than
its own history cutoff. Target cutoffs need not increase across folds and can
be later than the next origin's history cutoff. This permits an explicitly
declared evaluation against more mature target versions, without replacing
the history a later forecast actually used.

The source instants and wave indices must both continue the initial constant
gap exactly. The last planned history must remain within the existing
32-wave budget. All other settings come from the initial specification:
canonical roster, population, relation layer, behavior source and attribute,
measurement scale, model profile, source reference and research question.

The target policy is `latest_effective_at_declared_target_cutoff`. It means
the effective source fact at the declared L, never the latest record in the
file at evaluation time. Changing a target cutoff requires a separately saved
plan with a different hash. The original plan and report remain intact.

**The plan contains private actor identifiers in its initial specification.**
Preserve it with the private journal, history bundles, forecasts and targets.
Only the aggregate evaluation is intended for public reporting.

Fixed receipt numbers support controlled execution and reproducible historical
replay. This command does not implement live subscriptions, online triggers or
an automatic rule for choosing a cutoff from a wall-clock deadline.
The separate [local tracking command](network-tracking.md) now continuously
accepts JSONL receipt batches and retains fixed-view network revisions. It does
not automatically issue forecasts or change this evaluator's declared schedule.

## Check that target facts were not already received

The new profile adds two mechanical checks to the journal adapter.

### Raw measurement-stream check

For each origin, inspect every original assertion in its history receipt
prefix for the declared behavior source system and attribute. Reject it if:

- its occurrence time is at or after this origin's target time; or
- its valid interval has an open end or ends after the target time.

This is a conservative check of the entire selected measurement stream,
including actors outside the fixed roster. It includes invalid values and
records later superseded or retracted. An already received target does not
become unknown because its active head was later removed. An interval starting
after the target still intersects the target-or-later time range and is
rejected. The existing point-measurement rules separately govern history and
target selection.

### Target fact ancestry check

For each selected target measurement, find the earliest receipt of the same
`(source.system, fact_id)` in its target prefix. That first receipt must be
strictly after the forecast's history cutoff.

This also rejects an old fact initially labeled with another attribute or
source time and later revised into the target measurement. Its ancestry is
checked regardless of the earlier name, time, actor or value.

These checks establish consistency within the supplied record history. A
caller can author receipt timestamps and serialized records; neither the
checks nor hashes independently authenticate receipt availability, external
preregistration, a real prediction-issuance time or target blinding.

## Saved-file workflow

Save the initial journal before appending later batches, then create a plan:

```bash
python -m sociolab forecast journal-plan /path/to/initial-journal.json examples/journal-evaluation/initial-history.spec.json examples/journal-evaluation/schedule.json > /path/to/private-plan.json
```

At each origin, use the declared history cutoff with `forecast journal-history`
and save the resulting forecast through `forecast create`. As in the existing
adapter, construct the next origin's specification by appending the previous
scheduled target to its historical waves and updating only the origin's
history cutoff and next target instant/index. Preserve the complete history
bundle alongside the panel and forecast.

At the target cutoff, use `forecast journal-target` with that origin's original
specification and saved prediction. Preserve the full target bundle and its
standard target artifact. The target does not require a network at its source
instant. That same source instant can later become a historical network wave
for a subsequent origin once its network observations are received.

The evaluation manifest supplies exactly the saved forecast and target for
every scheduled fold, in order:

```json
{
  "schema": "sociolab.journal-forecast-fold-manifest.v1",
  "folds": [
    {"forecast": "forecast-2.json", "target": "target-2-original.json"},
    {"forecast": "forecast-3.json", "target": "target-3-original.json"}
  ]
}
```

Paths are resolved relative to the manifest. Evaluation uses a journal with
enough receipts for all declared cutoffs:

```bash
python -m sociolab forecast journal-evaluate /path/to/private-plan.json /path/to/later-journal.json /path/to/private/folds.json > /path/to/aggregate-evaluation.json
```

The evaluator validates the full input journal, replays historical snapshots
at their own K, and reconstructs target behavior at each L. Saved target
values **and revisions** must match. Even an equal-valued target from another
receipt version is rejected. Supplied score files are not accepted; scores are
recomputed from the saved predictions and verified targets without refitting.

Initial prefix and history hashes must match the plan. Each saved forecast's
wave revisions bind its own journal prefix; each saved target's source revision
binds its target evidence. Matching a dataset name or top-level revision alone
is insufficient. These checks show consistency of the provided artifacts with
one journal, not independent source authenticity.

The report binds only the prefixes actually used. Valid records appended
after all selected cutoffs do not change the report in the same implementation
and runtime. A target network is never materialized for that fold's scoring;
the journal is nevertheless parsed and hashed, and earlier target instants can
be legitimate historical inputs at later origins.

## Aggregate report and history differences

Each fold reports its source times, K/L, history and target prefix hashes,
history bundle/panel hashes, forecast hash, target hash and score. Later folds
also report:

- how many overlapping historical waves and actor-wave behavior values changed;
- how many historical waves and directed edge entries changed;
- how many historical source revisions changed;
- hashes of historical values before and after reconstruction; and
- the changed-person count and value hashes between the previous scored target
  and the newly appended historical behavior.

These are differences reconstructed from the same journal. The report does
not infer a person's motivation or a causal reason for the change. Actor IDs,
individual values and edge pairs remain in private artifacts.

A changed provenance revision does not necessarily mean changed values:
new receipt evidence can change a manifest while its selected measurements
stay equal. The value hashes and change counts therefore exclude provenance
revisions; revision changes are counted separately.

The model summaries reuse the existing raw/clipped pooled and macro MAE/RMSE
calculation. The primary metric is **clipped pooled MAE**. Pooled RMSE is
calculated from pooled squared errors, not from the mean of fold RMSEs.
Network-minus-own-lag and network-minus-persistence comparisons remain separate.

Every planned fold is required. If a model is not estimable in any fold, that
model's full-plan aggregate losses are null, with explicit available coverage
and failed target times. There is no favorable-fold selection, silent actor
dropping or fallback model. Repeated actor-forecasts are not independent people.

## Fixed invented execution

The [fixture](../examples/journal-evaluation/README.md) has four invented people,
four behavioral source waves and **three complete historical network waves**.
It supports two forecast origins. A late alias corrects one old behavior;
a previous target is corrected before it becomes the next origin's training
label. A later second target arrives, followed by another correction to the
first target.

Two schedules are declared before prediction: history cutoffs `[24,36]` with
target cutoffs `[28,40]`, and the same history cutoffs with target cutoffs
`[41,40]`. The second schedule measures sensitivity to target version selection
while reusing exactly the same saved predictions. It does not issue new
predictions or replace the original report.

The [protocol](experiments/2026-11-28-journal-evaluation/protocol.json) fixes all
inputs and the [runner](experiments/2026-11-28-journal-evaluation/run_receipt_evaluation.py)
uses the actual CLI. It refuses overwrites, records every private JSON's hash
at creation, and checks aggregate output before publication.

```bash
python docs/experiments/2026-11-28-journal-evaluation/run_receipt_evaluation.py --private-directory /path/to/fresh-private-directory --output /path/to/fresh-public-evidence
```

All invented batches and target values are known before execution. Receipt
timestamps are also invented. Save order validates the engineering process;
it does not establish blind evaluation, prospective validity, stable empirical
prediction or a causal network effect.

### Recorded result — 2026-11-28

One fixed execution completed **20 CLI steps**, including two plan creations,
two forecast creations and three evaluations: original, original replay after
K41, and revised-target sensitivity. Both plans were saved before either
forecast. Each forecast was saved before its corresponding target batch was
ingested. All **31 private JSON artifacts** retained their creation-time hashes.

At the second origin, the overlapping history contained one changed behavior
value, while its existing network edges stayed the same. Both old wave source
revisions changed because their receipt evidence changed. Separately, the
previous scoring target and the newly appended historical behavior differed
for one person. These counts are reported independently rather than conflated.

The original evaluation replayed **byte-identically** after the additional
K41 correction. The other predeclared plan selected the later first-target
version while retaining both saved predictions and the second target version.

The primary metrics below illustrate why target versions need a fixed policy.
They are numerical results on invented inputs, not empirical model rankings:

| Clipped pooled MAE | Original targets `[28,40]` | Later first target `[41,40]` |
| --- | ---: | ---: |
| Persistence | 0.875000 | 1.125000 |
| Own-lag OLS | 0.683333 | 0.808333 |
| Network-lag OLS | 0.583631 | 0.833631 |
| Network minus own-lag | −0.099702 | +0.025298 |

The forecasts are identical across columns. Changing only the declared target
version reverses the sign of this example's network-versus-own-lag comparison.
The later record is a different source version; the system does not independently
certify it as the true outcome.

Evidence:

- [Native execution record](experiments/2026-11-28-journal-evaluation/tests-execution.json)
  and [complete log](experiments/2026-11-28-journal-evaluation/native-tests.log):
  **347 tests passed**, including 18 new tests; no failures, errors or skips.
- [Independent check](experiments/2026-11-28-journal-evaluation/independent-check.json):
  **1,569 checks, including 160 numeric comparisons**, all passed. Maximum
  absolute difference was `1.1102230246251565e-16`, with absolute and relative
  tolerances of `1e-12`. The standard-library checker verifies receipt gates,
  retained bindings and revision counts, then pools saved individual errors
  directly. It imports no SocioLab code, performs no fit and does not implement
  the snapshot algorithm or independently validate coefficients.
- [Original evaluation](experiments/2026-11-28-journal-evaluation/evaluation-original.json)
  and [later-target evaluation](experiments/2026-11-28-journal-evaluation/evaluation-revised-target.json):
  complete fold scores and both pooled/macro summaries.
- [Execution](experiments/2026-11-28-journal-evaluation/execution.json) and
  [aggregate report](experiments/2026-11-28-journal-evaluation/report.json):
  source hashes, command order, file seals and the two-plan relationship.
- [Runner boundaries](experiments/2026-11-28-journal-evaluation/runner-boundary-checks.json):
  eight fresh-path and overwrite-rejection checks passed.
- [Validation manifest](experiments/2026-11-28-journal-evaluation/validation.json):
  the final implementation, fixture, documentation and evidence bindings.

## Python API

```python
from sociolab.events import load_event_dataset
from sociolab.journal_evaluation import (
    make_journal_forecast_plan, evaluate_journal_forecasts,
)
from sociolab.behavior_forecast import load_behavior_forecast, load_behavior_target

plan = make_journal_forecast_plan(
    load_event_dataset("initial-journal.json"), initial_history_spec, schedule,
)
# Save plan, separately issue/save each forecast and obtain its target version.
folds = [
    {"forecast": load_behavior_forecast("forecast-2.json"),
     "target": load_behavior_target("target-2-original.json")},
    {"forecast": load_behavior_forecast("forecast-3.json"),
     "target": load_behavior_target("target-3-original.json")},
]
report = evaluate_journal_forecasts(plan, load_event_dataset("later-journal.json"), folds)
```
