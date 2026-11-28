# Bind a forecast to a received version of the event journal

The journal adapter rebuilds a historical panel at one explicit receipt cutoff,
using the existing event importer and snapshot materializer. It then feeds that
panel into the existing [behavior forecast](behavior-forecast.md). Appending a
correction, retraction or identity mapping produces a new available version;
replaying the original cutoff preserves the original panel and its evidence.

The adapter adds **data version selection and provenance**. It does not add a
prediction model or change the existing NetworkX/NumPy calculations. It also
does not identify why a person changed their behavior. That remains a separate
question requiring a supported causal design and suitable observations.

## Two times, two responsibilities

Every source record has an occurrence time and a receipt sequence. They answer
different questions:

| Field | Meaning in this adapter |
| --- | --- |
| `occurred_at` | Which exact source wave contains this point observation? |
| `ingest_seq` | Was this record present by the selected receipt cutoff? |
| `recorded_at` | The UTC receipt timestamp assigned by the importer; retained as evidence, not independently authenticated. |
| `knowledge_cutoff` | The last admitted receipt sequence. It is mandatory and applies to **all historical waves** in one issuance. |
| `time_index` | The existing panel's wave index, with an explicit mapping to source time. |

For a cutoff K, the journal first resolves the effective head of each source
fact using only receipts 1 through K. Behavior selection and every historical
network snapshot use this same K. A correction received before K may revise an
older wave in this newly constructed history. This is **history as known at
issuance**, not a claim that every value was already available at its original
wave's date.

Later receipts cannot alter a replay of K while the journal envelope and its
first K records stay the same. The top-level journal `source_revision` is part
of that envelope. Keep it stable when appending receipts; changing it declares
a different source version. `ingest_records` already preserves it.

The importer accepts explicit receipt timestamps, and serialized files can be
authored by callers. Enforced prefix selection is therefore distinct from
externally verified historical availability. All forecast claims of verified
historical availability, empirical validation and causality remain false.
This adapter does not prove a prediction was issued before its real target.

## The initial profile

This is a deliberately narrow, single-origin input contract:

- 2–200 fixed, canonical people and 2–32 complete historical waves.
- A directed, binary observed relation layer. The existing state materializer
  must report complete coverage and exactly the declared roster at every wave.
- All positive retained edges have strength exactly 1. An observed zero remains
  absence evidence. Weighted ties, event counts and person–activity projections
  are not silently converted into binary social ties.
- One declared attribute name from one declared source system, measured at an
  exact source instant. Each actor must have exactly one effective point
  measurement, with an integer value inside the externally declared scale.
- No interpolation, last-observation carry-forward, automatic language score,
  missing-person deletion or inferred absence outside complete coverage.

The network view uses all sources already admitted to its selected layer;
the state materializer resolves their evidence and rejects conflicts. The
behavior source filter is separate and does not filter network records.

Duplicate independent behavior facts are ambiguous even when their values
agree. An alias and a canonical ID resolving to the same person are checked
together. Explicit source revisions can replace a fact through the journal's
supersession chain; an arbitrary later independent observation cannot win by
arrival order. Nulls, booleans, floating values and strings are rejected.
Interval-valued attributes at a selected wave are unsupported rather than
being treated as point measurements.

### Exact source timing

Both the panel indices and their source instants must be strictly increasing
and evenly spaced. The target must be exactly one such step after the last
historical wave. Numbering irregular dates `0, 1, 2` cannot bypass this check.

UTC instants are compared using the event parser's exact integer microseconds;
equivalent timestamp spellings refer to the same instant. For a selected UTC
behavior observation, receipt before occurrence is rejected. Tick instants
belong to the journal's declared `run_id`. A tick clock has no implicit mapping
to UTC receipt time, so the adapter does not compare the two units or infer
real-world temporal availability from them.

## Specification

The checked-in [invented specification](../examples/journal-forecast/history.spec.json)
is a complete example. Its exact fields are:

```json
{
  "schema": "sociolab.journal-forecast-history.v1",
  "knowledge_cutoff": 24,
  "source_reference": null,
  "actors": ["A", "B", "C", "D"],
  "population": "invented-cohort",
  "layer": "directed_observed_social_tie",
  "behavior_source": {
    "system": "invented-journal-fixture",
    "attribute": "invented_behavior_level_0_to_5"
  },
  "waves": [
    {"time_index": 0, "at": 0},
    {"time_index": 1, "at": 10}
  ],
  "target_at": 20,
  "forecast_specification": {
    "schema": "sociolab.behavior-forecast.v1",
    "profile": "own-lag-outgoing-gap-ols-v1",
    "behavior": {
      "variable": "invented_behavior_level_0_to_5",
      "minimum": 0,
      "maximum": 5,
      "measurement_reference": "synthetic:hand-authored-journal-levels"
    },
    "target_time_index": 2,
    "research_question": "Check receipt-cutoff isolation with manually authored inputs; no empirical performance claim."
  }
}
```

Names in this illustration must match the input journal. A synthetic journal
requires `source_reference: null`. An external observation journal requires
an explicit HTTPS source reference. `simulation_export` is not admitted to
this forecasting profile and is never relabeled as an observed or synthetic
panel. The adapter does not certify a source's completeness or measurement
quality merely because the declared fields pass validation.

## Command-line workflow

Append source batches with `events import`, then save the complete history
bundle and the panel used by the existing forecast command:

```bash
python -m sociolab forecast journal-history /path/to/events.json /path/to/history.spec.json > /path/to/private-history.bundle.json
python -m sociolab forecast journal-history /path/to/events.json /path/to/history.spec.json --panel-only > /path/to/private-history.json
python -m sociolab forecast create /path/to/private-history.json /path/to/forecast.spec.json > /path/to/private-prediction.json
```

`forecast.spec.json` is the unchanged `forecast_specification` object from the
history specification. Preserve the full history bundle alongside the panel
and prediction. The panel retains per-wave provenance hashes, while the bundle
contains the evidence those hashes identify. Both outputs are private: they
contain actor identities, measurements, ties and source records.

Once a target has been received, use the same history specification and saved
prediction with an explicit target cutoff:

```bash
python -m sociolab forecast journal-target /path/to/later-events.json /path/to/history.spec.json /path/to/private-prediction.json --knowledge-cutoff 33 > /path/to/private-target.bundle.json
python -m sociolab forecast journal-target /path/to/later-events.json /path/to/history.spec.json /path/to/private-prediction.json --knowledge-cutoff 33 --target-only > /path/to/private-target.json
python -m sociolab forecast score /path/to/private-prediction.json /path/to/private-target.json > /path/to/aggregate-score.json
```

The target command replays the **original history cutoff** to check the saved
forecast's history, source, roster, scale and specification. It does not refit.
It then selects target behavior at the target cutoff, which must be at least
the original history cutoff. It never materializes a target or future network.
The input journal is still parsed and validated as a whole; this is not a claim
that its other records' bytes are never read.

### Identity during scoring

Every frozen roster actor must retain its issuance-time identity. A source
actor used by the target must already have been known at issuance, and its
identity resolution must agree at both cutoffs. A newly introduced alias cannot
silently become an outcome for an issued prediction. Such a case requires a
separately specified identity reconciliation policy and is rejected here.
Unrelated later aliases do not invalidate canonical target observations.

This restriction still permits a newly reconstructed history to use a late
alias at its new issuance cutoff. It preserves the distinction between a new
analysis version and rescoring an earlier one.

### Corrections after issuance

| Later information | Permitted result |
| --- | --- |
| Corrected old behavior, relation retraction or new alias | Replay the old cutoff unchanged; construct a separately saved history and prediction at a new cutoff. |
| First receipt of target behavior | Extract a separate target and score the saved prediction. |
| Corrected target behavior | Save a new target version and score the same original prediction again. Keep both target versions and scores. |
| Changed identity of a frozen target person | Reject automatic target extraction for that issuance. |
| Incomplete target roster | Reject scoring for the complete-roster profile; do not drop individuals. |

The functions return values; they do not overwrite previously saved artifacts.
The recorded example additionally refuses to overwrite any output file.

## Evidence structure

The history bundle contains the normalized specification, the derived panel
and a private provenance manifest. The manifest preserves the journal envelope,
receipt-prefix hashes and full receipt records, effective facts, entity and
identity evidence, and each wave's source time, complete snapshot and selected
behavior records. A wave's `source_revision` is its wave-manifest hash. Hash
inputs exclude their own hash fields and contain no current execution time.

The target bundle binds the original history bundle and forecast hashes to a
target manifest containing its own cutoff, prefix hashes, identity evidence
and selected behavior records. Its manifest hash becomes the target's
`source_revision`. It includes no target network snapshot. These deterministic
bindings support inspection and replay; they do not authenticate the source.

### Relation to multi-origin evaluation

The [existing evaluator](forecast-evaluation.md) requires each historical
prefix, including its wave revisions, to remain unchanged within one plan.
Changing K changes the evidence environment and therefore the old wave
revisions, even if some numeric values stay equal. This journal adapter is a
single-origin profile. Histories reconstructed at different receipt cutoffs
cannot simply be inserted into one `expanding_immutable_prefix` plan.

A future evaluation across receipt cutoffs needs an explicit revision policy,
separate issuance records and target-version policy. The current evaluator's
invariants remain intact.

## Reproducible engineering example

The [invented batches](../examples/journal-forecast/README.md) use four actors,
two history waves and one target time. They append a corrected historical
behavior through a newly declared alias, retract a relation and add explicit
observed-zero evidence, then receive and correct a separate target. Target
time has no complete network coverage.

The [runner](experiments/2026-11-28-journal-forecast/run_synthetic_journal_forecast.py)
uses the real `events import`, `forecast journal-history`, `forecast create`,
`forecast journal-target` and `forecast score` CLI commands. It saves both
history versions' predictions before ingesting the target batch, replays the
original cutoff after each later batch, and rescoring uses the original saved
prediction. Inputs are fixed by the [protocol](experiments/2026-11-28-journal-forecast/protocol.json).

```bash
python docs/experiments/2026-11-28-journal-forecast/run_synthetic_journal_forecast.py --private-directory /path/to/fresh-private-directory --output /path/to/fresh-aggregate-evidence
```

All batches were invented and known before execution. Saving predictions
before ingesting these targets is an engineering check, not a blinded or
prospective experiment. No real prediction qualification, external receipt
authentication, causal effect or live subscription is established by this
example.

### Recorded result — 2026-11-28

The fixed execution completed **19 CLI steps** once, without retry or tuning.
It retained four invented people, two history waves, one target time and two
separately saved history versions:

| Receipt cutoff | New evidence admitted | Observed result |
| --- | --- | --- |
| K=24 | Original complete history | Initial panel, provenance bundle and prediction saved. |
| K=29 | Late alias, old behavior correction, relation retraction and observed zero | Replaying K=24 yields byte-identical history and prediction; selecting K=29 changes historical behavior and network edges and produces a separate prediction. |
| K=33 | Four target measurements | Both saved history versions can be scored; target time has no complete network coverage. |
| K=34 | One corrected target measurement | Replaying target K=33 stays byte-identical; selecting K=34 changes the target and score while retaining the original forecast hash. |

All **31 private JSON artifacts** retained their creation-time file hashes.
The two distinct predictions and the repeated prediction from the original
cutoff were saved before the target batch was ingested. The fixture itself
already contained those target values; this does not establish target blinding.

Validation evidence:

- [Native tests](experiments/2026-11-28-journal-forecast/tests-execution.json)
  and [complete log](experiments/2026-11-28-journal-forecast/native-tests.log):
  **329 passed**, including 20 new tests; no failures, errors or skips.
- [Independent check](experiments/2026-11-28-journal-forecast/independent-check.json):
  **728 checks, including 63 numeric comparisons**, all passed. Maximum absolute
  difference was **0.0**, with absolute and relative tolerances of `1e-12`.
  The standard-library checker reconstructs the fixed fixture's receipt heads,
  identities, point measurements, snapshot evidence and manifest hashes; it
  recomputes errors from saved predictions. It imports no SocioLab, NetworkX or
  NumPy code and performs no fit. It does not independently validate fitted
  coefficients or implement a general snapshot replacement.
- [Runner boundaries](experiments/2026-11-28-journal-forecast/runner-boundary-checks.json):
  eight path/overwrite checks passed against the final runner. A prior check
  record is retained for the earlier runner version; the case itself ran once.
- [Execution](experiments/2026-11-28-journal-forecast/execution.json) and
  [aggregate report](experiments/2026-11-28-journal-forecast/report.json):
  command order, source hashes, receipt cutoffs and immutable artifact bindings.
- [Original score](experiments/2026-11-28-journal-forecast/score-original.json),
  [revised-history score](experiments/2026-11-28-journal-forecast/score-revised-history.json)
  and [corrected-target score](experiments/2026-11-28-journal-forecast/score-corrected-target.json):
  separate aggregate outputs. Their numerical differences are engineering
  observations on invented values, not evidence of predictive advantage.
- [Validation manifest](experiments/2026-11-28-journal-forecast/validation.json):
  binds the final implementation, fixtures, documentation and recorded evidence.

## Python API

```python
from sociolab.events import load_event_dataset
from sociolab.journal_forecast import (
    make_journal_forecast_history,
    make_journal_forecast_target,
)
from sociolab.panels import LongitudinalPanel
from sociolab.behavior_forecast import make_behavior_forecast, score_behavior_forecast

bundle = make_journal_forecast_history(load_event_dataset("events.json"), history_spec)
prediction = make_behavior_forecast(
    LongitudinalPanel.from_mapping(bundle["history"]),
    bundle["specification"]["forecast_specification"],
)
# Save bundle and prediction, then separately obtain the target observations.
target_bundle = make_journal_forecast_target(
    load_event_dataset("later-events.json"), history_spec, prediction, knowledge_cutoff=33,
)
score = score_behavior_forecast(prediction, target_bundle["target"])
```
