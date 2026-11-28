# Invented receipt-aware evaluation inputs

This self-contained fixture contains manually authored records for four invented
people, two forecast origins and two predeclared target-version schedules. It
uses `origin: synthetic` and `source_reference: null`. No social model generated
the records, and none are real observations. It does not depend on the earlier
`journal-forecast` example.

`generate_fixture.py` writes deterministic input files and validates them with
the actual `ingest_records` and `materialize_snapshot` functions. It does not
create evaluation plans, export panels or manifests, fit a model, create a
prediction, or calculate scores. The separate case runner performs those
operations after freezing its protocol.

## Files and frozen schedules

Start with `empty.events.json`, then import the five raw batch files in the
order listed below. `initial-history.spec.json` declares the first history's
receipt cutoff, source wave times, canonical roster, behavior measurement and
unchanged forecast profile. `metadata.json` contains the stage schedule,
receipt times, exact cutoffs and SHA-256 hashes of all nine input JSON files.

Both schedule files have schema `sociolab.journal-forecast-schedule.v1` and
exact fields `schema` and `folds`. Each fold declares `target_time_index`,
`target_at`, `history_knowledge_cutoff` and `target_knowledge_cutoff`.

| Schedule | Target wave index | Target source time | History K | Scoring target K |
| --- | ---: | ---: | ---: | ---: |
| `schedule.json` | 2 | 20 | 24 | 28 |
| `schedule.json` | 3 | 30 | 36 | 40 |
| `revised-target.schedule.json` | 2 | 20 | 24 | 41 |
| `revised-target.schedule.json` | 3 | 30 | 36 | 40 |

The runner must create and save **both plans before either forecast**. They
share the issuance history schedule, model specification and roster, while
explicitly selecting different target versions. The second schedule is a
predeclared target-version sensitivity comparison; it is not selected after
looking at errors. Each report uses the same two saved forecasts.

A scoring cutoff may be later than the next forecast's historical cutoff.
Here the revised first target uses K41, after the second forecast's history
K36. Scoring cutoffs also need not increase across folds: `[41,40]` is
intentional. Source wave times still advance from 20 to 30. The first target
selected for scoring need not equal the version used in the next issuance's
history, and a later scoring revision must not rewrite that history.

## Import sequence

The source clock is ticks with `run_id: journal-evaluation-example`. History
wave indices 0, 1 and 2 map to source instants 0, 10 and 20; the final target
wave index 3 maps to source instant 30. These indices are not calendar dates.

| Stage | Batch | Invented UTC receipt | Added records | K |
| --- | --- | --- | ---: | ---: |
| initial | `initial.batch.json` | `2026-11-28T00:00:00Z` | 24 | 24 |
| target_first | `target-first.batch.json` | `2026-11-28T00:01:00Z` | 4 | 28 |
| second_history | `second-history.batch.json` | `2026-11-28T00:02:00Z` | 8 | 36 |
| target_second | `target-second.batch.json` | `2026-11-28T00:03:00Z` | 4 | 40 |
| revised_target | `revised-target.batch.json` | `2026-11-28T00:04:00Z` | 1 | 41 |

Raw records omit `ingest_seq` and `recorded_at`; the importer assigns those
fields when passed the declared `received_at`. The journal envelope remains
fixed, including top-level `source_revision:
invented-journal-evaluation-source-v1`. Individual records identify their batch
through `source.revision`. Changing the envelope would change old prefix
hashes and is not an append-only replay.

The intended run order is: import the initial history; freeze both plans;
save forecast 1; receive its first target; import the late history changes and
new network evidence; save forecast 2; receive its target; evaluate the primary
plan; receive the final target correction; replay the primary report and
evaluate the revised-target plan. The primary report must reproduce the same
bytes after K41, and the two forecast files must remain unchanged throughout.

## Source values and observations

All four canonical people A, B, C and D are declared and explicitly present
from tick 0. Membership remains unchanged throughout. Behavior is recorded as
an exact integer point `actor.attribute.observed` measurement from source
system `invented-journal-evaluation`, attribute
`invented_behavior_level_0_to_5`, on the declared 0–5 scale.

| Wave / selected version | Source instant | Behavior in A, B, C, D order | Positive directed relations |
| --- | ---: | --- | --- |
| Wave 0, all history versions | 0 | 1, 2, 3, 4 | A → B, B → C, C → A |
| Wave 1, initial history K24 | 10 | 2, 3, 2, 4 | A → C, B → A, C → D |
| Wave 1, second history K36 | 10 | 2, 3, 3, 4 | A → C, B → A, C → D |
| Wave 2, first scored target K28 | 20 | 3, 2, 3, 4 | No complete network yet |
| Wave 2, second history K36 | 20 | 3, 2, 3, 1 | A → D, B → C, D → A |
| Wave 3, second target K40 | 30 | 2, 3, 4, 2 | No network supplied |
| Wave 2, revised scoring target K41 | 20 | 3, 2, 3, 2 | Scoring does not use a target network |

The initial batch has two complete network coverage declarations, `[0,10)`
and `[10,20)`. All positive relations are directed point observations with
strength 1. No relation is carried from one wave into the next. D is an
observed isolate at wave 0 and stays in every history and target roster.

The first target batch supplies only the four at-20 behavior measurements.
At K28 that target can be scored, but it cannot yet be added as a complete
historical network wave. The second-history batch then supplies coverage
`[20,30)` and three at-20 relations. Only at K36 is that wave usable in the
second forecast's three-wave history. The final target at 30 is outside all
declared network coverage, and no at-30 network is needed for scoring.

There are therefore four behavior wave times and three complete historical
network wave times, not four fully observed joint network/behavior waves.
No behavior or attendance is inferred from missing ties.

## Corrections and identity

The eight records in the second-history batch are ordered as follows:

1. Declare person identifier `C_alias`.
2. Map `C_alias` to the existing canonical C.
3. Correct C's old at-10 behavior from 2 to 3, using `C_alias` in the
   replacement payload and explicitly superseding the original source fact.
4. Correct canonical D's at-20 behavior from 4 to 1 through its source fact's
   revision chain.
5. Declare complete network coverage for canonical A–D over `[20,30)`.
6. Through 8. Add the three at-20 positive relation observations.

The declaration-only intermediate K29 leaves an unresolved alias with unknown
membership. It is not an issuance cutoff. The completed K36 batch again
resolves to exactly four canonical people. Membership and coverage never list
the alias separately, avoiding duplicate identities and membership conflicts.

The alias is used only for historical at-10 behavior. Every target version
uses canonical actors already known at its forecast's issuance. The last
batch revises canonical D's at-20 value again, from 1 to 2. The complete chain
is `4 → 1 → 2`, with one fact ID, one source system and an explicit predecessor
for each revision.

The primary first target `[3,2,3,4]` differs from the next history's at-20
behavior `[3,2,3,1]`. That is an intended, attributable revision, not an
accidental mismatch. The revised first target `[3,2,3,2]` also differs from
what the second forecast knew. Each object must be reproduced at its own
receipt cutoff; the evaluator must not force these versions to match by
changing an old prediction or substituting a later history.

## Validation and reproduction

From the repository root, using an environment with SocioLab's dependencies:

```sh
python examples/journal-evaluation/generate_fixture.py
python examples/journal-evaluation/generate_fixture.py --check
```

The first command generates input JSON and metadata; the second performs the
same importer/snapshot validation and compares existing bytes without writing.
No current wall-clock timestamp enters the generated files.

The generator verifies complete fixed-roster histories at K24 and K36,
incomplete target-time networks at their first receipt, alias resolution,
behavior revision chains and unchanged fixed-cutoff snapshot/evidence replay
after all appends. It checks that both training designs have rank 3 using an
exact rational 3×3 minor with determinant −3: the first design has four rows,
the second eight. This checks algebraic feasibility without fitting any
coefficients or measuring prediction error.

Plan, panel, forecast, target and report byte checks belong to the separate
runner. Metadata marks them as pending rather than claiming they have already
passed. The runner keeps those individual records and predictions outside the
repository and publishes aggregate evidence only.

All source values, future batches, target-version schedules and invented
receipt timestamps are known before execution. This example checks software
boundaries and auditable revision handling. It cannot establish a blinded or
prospective experiment, externally authenticated availability, empirical
predictive benefit, stable performance, attendance prediction or a causal
effect. The eight actor-forecast rows in each report are not independent
observations, and the two reports are alternative scoring versions of the
same two forecasts.
