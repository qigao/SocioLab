# Repeat-interaction evidence and baselines

This is the first executable slice of [R1 / #21](https://github.com/qigao/SocioLab/issues/21).
It asks: **for an ordered pair with an observed interaction in a declared past
window, will another interaction of that action occur in the next window?**

The answer is a frozen probability or binary baseline, followed by separate
coverage-aware scoring. The implementation reuses `EventDataset`, original
snapshot materialization and receipt-prefix provenance. It adds no model library
or live subscription. Relationship-state estimation and empirical predictive
qualification remain separate research milestones.

## Three meanings of change

| Evidence | Interpretation |
| --- | --- |
| An interaction leaves a trailing window | Its occurrence no longer contributes to that query's count. |
| Coverage is incomplete, or membership is unknown | The absence of a record cannot establish a full-horizon negative outcome. |
| An effective `relation.changed` declaration sets strength to zero | The source explicitly asserts a zero state for that relation layer, under its own measurement definition. |

The event baselines do not estimate friendship, trust, motivation or termination.
They never write `relation.changed` records. A cooperation relation can remain
source-declared active after every recent communication event has expired.
Conversely, a recorded relationship ending does not erase earlier interactions.

## Frozen specification

`sociolab.repeat-interaction-spec.v1` requires exactly the fields below:

```json
{
  "schema": "sociolab.repeat-interaction-spec.v1",
  "knowledge_cutoff": 17,
  "source_reference": null,
  "observation_reference": "Invented complete communication history for an engineering case.",
  "actors": ["A", "B", "C", "D"],
  "population": "team",
  "layer": "communication",
  "actions": ["reply"],
  "topics": [],
  "history_start": 0,
  "recent_start": 15,
  "origin_at": 20,
  "target_end": 30,
  "risk_set": "history_positive_ordered_pairs"
}
```

Use the generated example's actual receipt cutoff when executing it. A source
reference is null for explicitly synthetic data and an HTTPS reference for
external observations; that reference alone does not admit a source scientifically.

The initial profile supports one typed directed action, optional declared topic
filters, 2–200 fixed canonical people and at most 2,000 previously observed
ordered pairs. The fixed roster must equal the history's eligible population,
with full presence and complete coverage throughout history and presence at
the prediction origin. Missing historical exposure is rejected, not imputed.

The intervals are half-open: history `[history_start, origin_at)`, recent history
`[recent_start, origin_at)` and target `[origin_at, target_end)`. Require
`history_start <= recent_start < origin_at < target_end`. Ticks remain integer
ticks; UTC uses exact integer microseconds. Simultaneous events are counted as
supplied; no within-timestamp order is invented. Multiple source facts count as
multiple observations: the existing journal's source-system/fact identity rules
apply, without cross-system semantic deduplication or a source-system filter.

The risk set is **conditional on a positive history observation**. It excludes
never-observed pairs and cannot evaluate first-contact prediction or all possible
social relationships. Empty risk sets remain explicit and produce no scored
sample, rather than an error of zero. The prediction artifact contains private
pair identities, counts, event ages and probabilities.

## Three fixed baselines

Let `H` be target duration, `W` the historical duration, `Wr` the recent duration,
and `n`/`nr` the pair's corresponding event counts.

| Model | Probability / binary prediction | Assumption |
| --- | --- | --- |
| `historical_poisson` | `1 - exp(-n * H / W)` | A homogeneous Poisson rate estimated from the entire declared history. |
| `recent_poisson` | `1 - exp(-nr * H / Wr)` | The same constant-rate assumption, estimated only from the declared recent window. |
| `recent_occurrence` | 1 if `nr > 0`, otherwise 0 | Repeat the recent event-presence indicator; a hard binary baseline. |

The two count-rate formulas use `-expm1(-intensity)` for numerical stability.
The artifact also preserves time since the last eligible history event. No
parameters, thresholds or window widths are selected using target outcomes.
The Poisson assumptions and probability calibration are **unvalidated**. A zero
estimated event rate is not evidence that a relationship ended. No HMM, duration
model, fitted psychological construct or new simulation world is introduced.

## Target evidence and eligibility

Scoring takes the unchanged saved forecast, the same journal with later receipts,
and a separate target declaration:

```json
{
  "schema": "sociolab.repeat-interaction-target.v1",
  "knowledge_cutoff": 21,
  "observed_through": 30,
  "observation_reference": "Invented target follow-up declared closed through tick 30."
}
```

`observed_through` is a **source-supplied follow-up declaration**, not the current
wall clock, a live checkpoint or proof that all records have arrived. It is an
exclusive right boundary, just like the event windows. Its reference and value
are bound into the score hash alongside target K and the target prefix hash.
Receipt timestamps, source completeness and prospective issuance are not
externally authenticated by this implementation.

Each forecast pair receives one eligibility result, in this order:

1. If follow-up has not reached `target_end`, `followup_not_closed`.
2. If either person's target membership is unknown at any point,
   `membership_unknown`.
3. If either person was not present for the whole target duration,
   `membership_not_full_horizon`.
4. If either person's corresponding layer lacks full coverage,
   `coverage_incomplete`.
5. Otherwise the pair is scorable: at least one eligible event is 1; none is 0.

Checking a snapshot's global `coverage.complete` alone is insufficient: that
flag can be true when someone left midway, because it describes their in-scope
observation intervals. This profile additionally checks full-horizon exposure.
People first seen in the target period do not enlarge the frozen risk set, and
unrelated unknown newcomers do not invalidate fully observed old pairs.

Known positives under incomplete follow-up are retained in aggregate evidence
counts but excluded from **every model's** scores. This avoids pooling selectively
observed positives with completely observed negatives. Before maturity, only
events before `observed_through` are inspected. No observation period is silently
extended merely because future-dated assertions are already present.

All three models use the same scorable pairs. Output includes risk, scored and
unscored counts, mutually exclusive exclusion reasons, positive/negative counts,
Brier mean squared probability error, mean prediction and observed event fraction.
No scorable pairs produces `UNSCORED` and null metrics. Partial scoring is labeled
`PARTIALLY_SCORED`; performance then describes that selected complete-follow-up
subset, not the entire risk population. These dependent pair observations do not
receive IID confidence intervals or significance claims. Mean prediction versus
event fraction is descriptive and does not establish full calibration.

## Receipt versions, leakage and replay

The history uses only the declared receipt prefix K. A later journal tail cannot
change an old prediction. Source-time windows and receipt cutoffs remain separate.

Two mechanical gates follow the existing journal evaluation conventions:

- Issuance rejects every raw assertion in the selected action/topic stream with
  source time at or after `origin_at`, across actors and including assertions
  later superseded or retracted. Hiding a known future event is not past-only input.
- A selected target event's `(source.system, fact_id)` must first have arrived
  after the history K. Revising an already-known old fact into the target interval
  cannot make it an independent future outcome.

Scoring reconstructs the original forecast at its old K and requires exact
artifact agreement. A changed probability with a recomputed hash is rejected
unless it agrees with the original history and fixed calculation. This replay
recomputes the old closed-form baselines; target information never refits them.
The target must preserve the original canonical actors and alias map. New
unrelated entity declarations are allowed, while changing the alias mapping
requires a different study specification.

Later target corrections produce a separately hashed score at a new target K.
Prior forecasts and scores remain caller-owned immutable artifacts; the CLI
writes JSON to stdout and cannot prevent a caller from overwriting a file.
The [multi-origin evaluator](repeat-interaction-evaluation.md) adds fixed window
schedules, explicit missing slots, coverage denominators and descriptive
probability bins around this unchanged single-origin score. Automatic issuance
and calibration fitting remain separate extensions under R1/R2.

## Commands and runnable fictional case

```sh
python examples/repeat-interaction/generate_fixture.py /path/to/fictional-case
python -m sociolab forecast interaction-create /path/to/fictional-case/history.events.json /path/to/fictional-case/specification.json > /path/to/private-forecast.json
python -m sociolab forecast interaction-score /path/to/fictional-case/complete.events.json /path/to/private-forecast.json /path/to/fictional-case/complete.target.json
python -m sociolab forecast interaction-score /path/to/fictional-case/partial.events.json /path/to/private-forecast.json /path/to/fictional-case/partial.target.json
```

The execution runner and predeclared scenario list live in
`docs/experiments/2026-11-28-repeat-interaction/`. All people, event times,
coverage and relationship declarations are invented engineering examples.
Software agreement on these cases is not synthetic recovery of a latent model,
real-source predictive validation or a measured causal effect.

### Executed validation — 2026-11-28

The [frozen protocol](experiments/2026-11-28-repeat-interaction/protocol.json)
was saved before execution. The
[case report](experiments/2026-11-28-repeat-interaction/case-report.json)
records these five authored target scenarios for the same three predictions:

| Scenario | Target K | Known positive pairs | Scorable pairs | Unscored pairs |
| --- | ---: | ---: | ---: | ---: |
| Complete observation | 21 | 2 | 3 | 0 |
| Follow-up only through tick 23 | 23 | 2 | 0 | 3 |
| Coverage gap and one person leaving | 23 | 3 | 1 | 2 |
| Missing coverage subsequently supplied | 24 | 3 | 2 | 1 |
| One target event subsequently retracted | 25 | 2 | 2 | 1 |

The unclosed target has null scores for all models. Source corrections change
the selected target and its score identity; replay of the original forecast and
the earlier K23 score returns identical bytes. A separate state control has
zero communication edges in a completely observed recent window while one
cooperation edge remains active. Only the explicit source zero removes that
state edge.

All **14 actual subprocess commands** completed with exit 0. The
[standard-library checker](experiments/2026-11-28-repeat-interaction/independent_case_check.py)
compares authored outcomes and independently calculated closed-form probabilities
and Brier scores; its [result](experiments/2026-11-28-repeat-interaction/independent-check.json)
has maximum absolute numeric difference **0.0** for this case. It does not import
SocioLab or independently establish source authenticity or model validity.
The [execution record](experiments/2026-11-28-repeat-interaction/execution.json)
binds implementation, fixture and protocol hashes and confirms that retained
private artifacts were unchanged.

The [native test execution](experiments/2026-11-28-repeat-interaction/tests-execution.json)
passes **454 tests**, including **27 new API/CLI tests**, with no failures,
errors or skips. Source and test hashes stayed equal during that suite. This
validates the implemented observation and replay rules; all data in the new
case are fictional and all target outcomes were authored in advance.

## Current source admission

The existing source audits do not yet supply a real dataset suitable for this
complete-history directed-event profile:

| Source | Existing evidence | R1 admission gap |
| --- | --- | --- |
| Hypertext 2009 | Reviewed recorded-contact archive; [descriptive case](recorded-contact-case.md) | Undirected badge proximity, no device-uptime evidence or qualified population/complete log. The archive-wide roster uses future records. |
| s50 | [Forecast/source review](forecast-source-admission.md) and teaching panels | Friendship nomination waves, not a continuously observed interaction event stream; no qualified population boundary for this purpose. |
| Mauldin | [Source admission](mauldin-source-admission.md) and candidate-cohort audit | Unresolved roster/response coverage, item-level missingness, no required continuous event/follow-up evidence; retains `NOT_ESTIMABLE` for its existing panel task. |

Their previous descriptive or educational uses remain valid within their stated
scope. No missing history is converted to zeros or complete coverage for this
new task. The next empirical milestone requires an admitted event source with
population, channels, historical coverage and independent target follow-up.
Only then can out-of-time predictive performance, uncertainty and calibration be
evaluated beyond fictional software cases.
