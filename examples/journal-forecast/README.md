# Invented journal → forecast inputs

These are manually authored records for four invented people. They exercise
the real event importer and snapshot materializer. No social model generated
the records, and they are not empirical observations. The source explicitly
uses `origin: synthetic` and `source_reference: null`.

`generate_fixture.py` writes the input JSON and metadata. It checks ingestion,
snapshot coverage, alias handling, retractions, and fixed-cutoff replay. It
does **not** export forecast panels or manifests, fit a model, create a
prediction, or compute a score. Those actions belong to the separate case
runner after its protocol has been frozen.

## Batch order and receipt cutoffs

The event clock uses ticks with `run_id: journal-forecast-example`. History
wave indices 0 and 1 correspond to event instants 0 and 10. Target wave index 2
corresponds to event instant 20. These indices are not calendar durations.

| Stage | Input batch | Invented UTC receipt | Added records | Receipt cutoff |
| --- | --- | --- | ---: | ---: |
| Initial history | `initial.batch.json` | `2026-11-28T00:00:00Z` | 24 | 24 |
| Late history corrections | `late-history.batch.json` | `2026-11-28T00:01:00Z` | 5 | 29 |
| First target observations | `target.batch.json` | `2026-11-28T00:02:00Z` | 4 | 33 |
| Target revision | `revised-target.batch.json` | `2026-11-28T00:03:00Z` | 1 | 34 |

Start with `empty.events.json` and pass each raw batch to
`sociolab.events.ingest_records`, using the corresponding `received_at` value.
The raw batch records deliberately omit `ingest_seq` and `recorded_at`: the
importer assigns those fields. `metadata.json` exposes the ordered stages,
cutoffs, receipt times, and SHA-256 file hashes for runner use.

The journal's top-level `source_revision` remains
`invented-journal-source-v1`. A record's `source.revision` identifies its input
batch. Changing top-level journal metadata would change an old cutoff's
snapshot hash even when its record prefix is unchanged; this fixture does not
do that.

## Initial history

The fixed roster is `A`, `B`, `C`, `D`. Four entity declarations and four
`membership.changed` records establish that each is present from tick 0.
Two `coverage.observed` records declare complete observation of the directed
binary relation layer over `[0,10)` and `[10,20)`. Their union is `[0,20)`.

Each relation is a point `relation.observed` measurement at its wave instant,
with `valid_interval: null` and integer strength 1. Such observations do not
persist into another wave. The complete coverage declarations make omitted
pairs meaningful within this invented source contract.

| Wave | Event instant | Positive directed relations | Behavior values in A, B, C, D order |
| --- | ---: | --- | --- |
| 0 | 0 | A → B, B → C, C → A | 1, 2, 3, 4 |
| 1 | 10 | A → C, B → A, C → D | 2, 3, 2, 4 |

D is an observed isolate in wave 0 and remains in the roster. Behavior is
recorded separately as one point `actor.attribute.observed` measurement per
person and wave, under source system `invented-journal-fixture` and attribute
`invented_behavior_level_0_to_5`. All values are exact integers on the declared
0–5 scale. The relation layer is not used to infer behavior or attendance.

`history.spec.json` fixes receipt cutoff 24, the canonical roster, both wave
instants, behavior source, target instant, and the existing three-model
forecast profile. The network model's training design has four rows and three
columns. Its first three rows have determinant −3, so the design has rank 3.
The generator verifies this with exact rational arithmetic; it does not
estimate coefficients or inspect model performance.

## Late history corrections

The five records in `late-history.batch.json` are ordered deliberately:

1. Declare the new person identifier `C_alias`.
2. Map `C_alias` to the existing canonical identifier C.
3. Revise C's wave 1 behavior from 2 to 3, using `C_alias` in the replacement
   payload. The record keeps the original fact ID and source system and
   explicitly supersedes the previous record.
4. Retract the erroneous positive wave 1 relation B → A. The retraction has
   the same fact ID and kind, references its current head, and has a null
   payload.
5. Add a distinct point relation fact with strength 0 for B → A. This explicitly
   records the measured zero; a withdrawal by itself is not evidence of absence.

Membership and coverage always use canonical A–D. The alias receives no
separate membership assertion and is not added to the coverage actor list.
This avoids creating conflicting membership or duplicate identities when the
mapping takes effect. The declaration-only intermediate cutoff 25 is valid
as a journal prefix but has unknown membership for the unresolved alias; it
is intentionally not a history export point. The completed batch cutoff 29
again resolves to exactly the four canonical people with complete coverage.

At cutoff 29, wave 0 is analytically unchanged; wave 1 has two positive edges,
A → C and C → D, and C's behavior is 3. The revised source evidence makes this
a distinct history version. A runner must preserve the original cutoff-24
panel, manifest, and issued forecast under their original paths and hashes,
and create a separate corrected-history artifact and forecast for cutoff 29.

## Target observations and revision

The target batch contains only four behavior measurements at tick 20, with
values 3, 2, 3, 4 in A–D order. It contains no relation or coverage records.
Tick 20 falls outside the declared network coverage interval; a materialized
target-time snapshot has known membership but incomplete network coverage.
The target exporter must be able to use the complete behavior measurements
without requiring a future network. Target actors use the canonical IDs
already known at each forecast's issuance cutoff.

The final batch revises D's target behavior from 4 to 1. It uses the original
target fact ID and source system and supersedes that target's current head.
A runner should score each already-saved forecast against the original and
revised targets in separate score files, without fitting again or modifying
either forecast. Replaying target cutoff 33 after this revision still returns
the original target; cutoff 34 returns the revised version.

The intended runner order is: import initial history, export and save its
forecast; import late history corrections, export and save the separate
corrected-history forecast; then import the target and its later revision.
The generator confirms snapshot bytes and selected behavior at fixed history
cutoffs 24 and 29 survive every subsequent append. It leaves panel, manifest,
forecast-byte, and score checks to the case runner and labels them accordingly
in metadata.

## Reproduction and scope

From the repository root, using an environment with SocioLab's dependencies:

```sh
python examples/journal-forecast/generate_fixture.py
python examples/journal-forecast/generate_fixture.py --check
```

The first command regenerates the deterministic input JSON and metadata; the
second validates the same inputs and compares their bytes without writing.
No current wall-clock timestamp is inserted into generated files.

The full fixture, including target values and invented receipt times, is known
before any case execution. Separating importer receipts, export cutoffs, and
prediction files can demonstrate engineering boundaries, but this example
cannot establish a blinded or prospective study, real-world data availability,
empirical predictive benefit, attendance prediction, or a causal effect. The
separate runner keeps exported panels, manifests, predictions, and targets
outside the repository and publishes aggregate evidence only.
