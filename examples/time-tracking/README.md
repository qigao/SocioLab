# Invented inputs for explicit source-time tracking

This fixture contains manually authored observations about four invented people,
A–D. It separates two independent coordinates: **K**, the number of accepted
source records, and a **source-time cursor**, advanced only by an explicit
command. All source values, including future-dated observations, are known
before execution. This is an engineering example with `origin: synthetic`.

## Inputs and registration

Initialize an empty journal from `empty.events.json` with `registration.json`.
The initial state is sequence 0, K0, cursor 10. All three initial empty snapshots
lack complete coverage. Do not import `initial.batch.json` separately before
the stream: it is a pretty-printed copy of the **complete first CLI batch
envelope**, not a raw records array or an additional delivery.

The registration uses `sociolab.temporal-tracking-spec.v1`, `initial_cursor: 10`
and `source_time_unit: "tick"`. Each entry declares a view without `at`, `start`
or `end`, a `window_width`, and `analysis: {}` for the existing defaults.

| View ID | Resolution at cursor c | Width | Initial edges after delivery 1 |
| --- | --- | ---: | --- |
| `cooperation` | Undirected cooperation state at c | `null` | A–B, C–D |
| `communication` | Directed reply/utterance counts over `[c−10,c)` | 10 | A → B |
| `trust` | Undirected trust state at c | `null` | A–D |

Every resolved view keeps all four people, including isolates. The query
policies remain fixed while their explicit source-time boundaries advance.
Neither receipt timestamps nor elapsed wall time move the cursor.

`commands.jsonl` contains the complete eleven-delivery stream. The split files
`commands-before-restart.jsonl` and `commands-after-restart.jsonl` contain the
first five and remaining six deliveries. They are alternatives to the combined
stream, not additional observations. Stop and restart after the fifth delivery,
whose commit changes time without appending source records.

Receipt lines have exactly `schema`, `records` and `received_at`, with schema
`sociolab.network-tracking-batch.v1`. Their records have no `ingest_seq` or
`recorded_at`; the real importer assigns those fields. The receipt timestamps
are explicit and invented.

Advance lines have exactly `schema` and `cursor`, with schema
`sociolab.network-tracking-advance.v1`. For example:

```json
{"schema":"sociolab.network-tracking-advance.v1","cursor":15}
```

A strictly later cursor creates a checkpoint even when all observed graph,
population, coverage and selected-evidence values stay unchanged. An equal
cursor returns `NO_TIME_ADVANCE` and creates no checkpoint. An exact duplicate
receipt returns `NO_NEW_RECORDS`. A backwards cursor is rejected.

## Initial source records

The initial batch has 19 records:

- Four entity declarations and four membership states, all people present from
  tick 0.
- Complete cooperation and communication coverage over `[0,20)`, and complete
  trust coverage over `[0,40)`.
- Cooperation A–B and C–D from tick 0, plus a received but not yet effective
  B–C state change at tick 15.
- Trust A–D from tick 0.
- Replies A → B at tick 5, C → D at tick 10, B → C at tick 15 and D → A at
  tick 20.

All relationship strengths and event counts are 1. State changes are effective
at `occurred_at <= cursor`. Communication selection instead requires
`cursor − width <= occurred_at < cursor`. A received record outside the current
view remains in the journal without creating an edge in that view.

## Delivery sequence

Sequence counts committed changes on either coordinate; it is not another name
for K. The initial empty checkpoint is included in the final checkpoint count.

| Delivery | Stage | Added records | Sequence | K | Cursor | Expected result |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 1 | initial | 19 | 1 | 19 | 10 | Complete views; communication includes only the reply at 5. |
| 2 | advance_to_15 | 0 | 2 | 19 | 15 | B–C cooperation becomes effective; communication includes replies at 5 and 10, excluding 15. |
| 3 | equal_advance_15 | 0 | 2 | 19 | 15 | `NO_TIME_ADVANCE`; no new checkpoint. |
| 4 | late_correction_at_15 | 1 | 3 | 20 | 15 | Supersede the reply at 10, changing C → D to C → A; cursor stays fixed. |
| 5 | advance_to_20 | 0 | 4 | 20 | 20 | Cooperation coverage expires; communication `[10,20)` remains complete and includes replies at 10 and 15. |
| — | restart | 0 | 4 | 20 | 20 | Reopen the time-only commit; K alone cannot identify it. |
| 6 | equal_advance_20_after_restart | 0 | 4 | 20 | 20 | `NO_TIME_ADVANCE`; restarted state retains the cursor. |
| 7 | advance_to_21 | 0 | 5 | 20 | 21 | Communication now includes replies at 15 and 20, with partial coverage over `[11,21)`. |
| 8 | coverage_recovered_at_21 | 2 | 6 | 22 | 21 | New coverage assertions over `[20,40)` complete both affected layers at the held cursor. |
| 9 | duplicate_recovery_at_21 | 0 | 6 | 22 | 21 | `NO_NEW_RECORDS`; same source records with a later delivery timestamp. |
| 10 | advance_to_25 | 0 | 7 | 22 | 25 | `[15,25)` keeps the reply at its inclusive lower boundary; all four semantic flags stay unchanged. |
| 11 | advance_to_26 | 0 | 8 | 22 | 26 | `[16,26)` drops the reply at 15; communication has only D → A. |

Expected totals are 11 deliveries, eight committed changes, three idempotent
deliveries, 22 accepted records and nine checkpoints including initialization.
Three commits append receipts; five advance time without appending records.
The final state is sequence 8, K22, cursor 26, with cooperation/communication/
trust edge counts **3/1/1**, all complete. Trust has unchanged graph, population,
coverage and selected evidence after the initial batch.

## Boundary and coverage meaning

The reply at tick 10 is excluded from the initial `[0,10)` window. At cursor 15,
the reply at 5 remains because the lower bound is inclusive, while the reply at
15 is excluded because the upper bound is exclusive. At that same cursor,
the B–C relationship change at 15 is already effective. Advancing to 20 still
excludes the reply at 20; advancing to 21 includes it.

Coverage intervals also exclude their right endpoint. Cooperation state at 20
has no applicable coverage declaration and is therefore incomplete, while
communication `[10,20)` is fully covered. At cursor 21, communication has
partial coverage because `[20,21)` is uncovered. Known positive relationships
and events remain visible in these incomplete snapshots. No missing declaration
is converted into a zero-valued edge or an absence observation.

Recovery uses two new, nonoverlapping coverage facts over `[20,40)`, adjoining
the earlier intervals. It does not revise the old coverage interval or assert
an explicit `unobserved` status over known positive evidence. The recovery
transition still has an incomplete predecessor, so qualified comparison is
skipped for the recovered layers. Later complete-to-complete comparisons can
resume.

The late reply correction keeps its source system, fact ID and kind and
supersedes the active record. It changes what is known at the held cursor 15,
without claiming that the interaction changed at receipt time. The envelope's
`source_revision` stays `invented-time-tracking-source-v1` throughout.

## Metadata and comparison checks

`metadata.json` records every delivery's before/after K, cursor and sequence,
expected status, whether a checkpoint is created, and each view's resolved
time bounds, counts, coverage, flags and snapshot hash. Its `checkpoints` list
shows why an identifier must distinguish repeated K values at different source
times. Replaying an old pair **(K, cursor)** after all receipts must preserve
the old snapshot bytes.

Qualification and scheduled analysis are recorded separately. The generator's
`qualified_comparison_status` and `qualified_relation_change_counts` use the
existing `compare_snapshots` function when both snapshots are complete. The
expected tracker fields are `tracking_comparison_status` and
`tracking_comparison_reason`. No-op deliveries have no comparison; an unchanged
graph/population/coverage gives `NOT_RUN/no_observable_change`; otherwise an
incomplete before or after gives `NOT_RUN/incomplete_before_or_after_coverage`.
The fixture is below the existing analysis budgets. Five view transitions are
expected to run qualified tracker comparisons.

All three snapshot hashes change on a committed cursor advance because the
resolved source queries change. Receipt appends also change receipt-prefix
provenance in all three snapshots. A changed snapshot hash therefore does not
by itself establish a graph, population, coverage or selected-evidence change.
In particular, delivery 10 must commit the new cursor while those four flags
remain false for every view.

## Separate rejection inputs

Each negative file is intended for an independent rejected delivery after the
successful stream, with sequence 8, K22, cursor 26 and all checkpoints preserved:

- `rejected-backwards.jsonl`: move the cursor backwards to 25.
- `rejected-cursor-type.jsonl`: supply string `"27"` instead of an integer tick.
- `rejected-mixed-command.jsonl`: include a `records` field in an advance command.

These files are not part of the successful stream. The fixture generator writes
their declared expectations; it does not run the temporal tracker or claim that
the actual CLI rejection paths have been tested.

## Generation and scope

```sh
python examples/time-tracking/generate_fixture.py
python examples/time-tracking/generate_fixture.py --check
```

The generator uses the real importer and materializer and the existing snapshot
comparison with complete inputs. It checks graph values, exact temporal bounds,
coverage, idempotent imports, and byte-identical replay at every retained
(K, cursor). At the restart point it checks only a JSON round trip of the source
journal and explicit cursor. `--check` compares generated bytes with existing
files without writing.

Actual checkpoint persistence, process restart, rejection behavior and receipt
acknowledgments before EOF remain separate case-runner checks. Metadata marks
them as unexecuted by this generator. This fixture does not authenticate source
times, establish real-time latency, subscribe to an external source, predict
future behavior or identify causal effects.
