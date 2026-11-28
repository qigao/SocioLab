# Invented inputs for continuous receipt tracking

These are manually authored observations for four invented people A–D. They
exercise receipt-driven updates of three fixed network views, using
`origin: synthetic`. No real records, generated conversation, inferred social
mechanism or empirical prediction is included.

## Input files

Initialize a fresh private store with `empty.events.json` and `registration.json`.
The initial journal has no records; all three registered views initially lack
coverage. Then feed one JSON object per line from `batches.jsonl` to the tracker.

Every input line has exactly `schema`, `records` and `received_at`, with schema
`sociolab.network-tracking-batch.v1`. Its `records` array contains raw importer
records without `ingest_seq` or `recorded_at`. Receipt timestamps in this example
are explicit and invented; `null` is not used. `initial.batch.json` is a pretty
printed copy of the **complete first CLI batch envelope**, not a raw array and
not an additional batch to import before `batches.jsonl`.

The combined stream is split into `batches-before-restart.jsonl` (first eight
deliveries) and `batches-after-restart.jsonl` (last three). These are alternatives
to feeding the combined stream, not additional observations.

```sh
python -m sociolab tracking init examples/network-tracking/empty.events.json examples/network-tracking/registration.json /path/to/fresh-private-store
python -m sociolab tracking run /path/to/fresh-private-store < examples/network-tracking/batches-before-restart.jsonl
python -m sociolab tracking inspect /path/to/fresh-private-store
python -m sociolab tracking run /path/to/fresh-private-store < examples/network-tracking/batches-after-restart.jsonl
```

A live-pipe case should additionally verify that each acknowledgment arrives
while stdin remains open. Ordinary file redirection alone does not prove that
property. This fixture generator does not run the persistent tracker.

## Fixed views and initial observations

| View ID | Source query | Initial recorded edges |
| --- | --- | --- |
| `cooperation_5` | Undirected cooperation state at tick 5 | A–B, C–D |
| `cooperation_15` | Undirected cooperation state at tick 15 | A–B, C–D |
| `communication` | Directed reply/utterance counts over `[0,20)` | A → D, count 1 |

The initial batch has 13 records: four entity declarations, four membership
states marking everyone present from tick 0, two layer-specific complete
coverage declarations over `[0,20)`, two cooperation state observations, and
one reply at tick 3. Each view keeps all four people, including communication
isolates. The registration uses `analysis: {}` so the existing defaults apply.

These source queries never advance with the wall clock. Later receipts can
change what is known about tick 5 or tick 15 without changing either view's
definition. A registration must bind the full normalized view: the existing
snapshot `policy_hash` excludes `at`, `start` and `end` and by itself does not
freeze a query's time boundary.

## Delivery sequence and expected changes

The sequence below counts only accepted batches that add records. The empty
store is sequence 0, K0. Duplicate deliveries do not create a new journal
receipt or checkpoint.

| Delivery | Stage | Added records | Sequence | K | Expected effect |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | initial | 13 | 1 | 13 | Three complete initial views; comparison with the uncovered empty baseline is not qualified. |
| 2 | new_relation | 1 | 2 | 14 | B–C at tick 10 adds an edge only to `cooperation_15`. |
| 3 | late_correction | 1 | 3 | 15 | Correct the same fact to B–D at tick 4: add B–D at tick 5; replace B–C with B–D at tick 15. |
| 4 | evidence_only | 1 | 4 | 16 | Supersede the corrected fact with equal numeric strength `1.0` instead of `1`; selected evidence changes, graph values do not. |
| 5 | duplicate_old_link | 0 | 4 | 16 | Resend the original B–C record exactly; its superseded head is not restored. |
| 6 | attribute_only | 1 | 5 | 17 | Record C's invented declared position; no view gains, loses or reweights an edge. |
| 7 | retract | 2 | 6 | 19 | Retract the current link head and separately record observed zero for B–D. Both cooperation views return to A–B and C–D. |
| 8 | coverage_partial | 1 | 7 | 20 | Revise cooperation coverage to partial; retain known positive edges but skip qualified comparison for both cooperation views. |
| — | restart | 0 | 7 | 20 | Stop and reopen the same store; preserve its committed checkpoint. |
| 9 | duplicate_partial_after_restart | 0 | 7 | 20 | Resend the last committed partial-coverage record exactly. |
| 10 | coverage_recovered | 1 | 8 | 21 | Restore complete cooperation coverage. The preceding snapshot is partial, so this transition still cannot be compared analytically. |
| 11 | post_recovery_relation | 1 | 9 | 22 | A new, distinct B–C state fact at tick 12 changes only `cooperation_15`; complete-to-complete comparison resumes. |

The stream ends with cooperation edge counts 2 and 3, and communication edge
count 1. All three views are complete, with four people each. There are 11
deliveries, nine applied batches, 22 accepted journal records, and ten expected
checkpoints including the empty initial checkpoint. Communication's observed
graph and coverage remain unchanged after the initial batch.

`metadata.json` records the cutoff and accepted sequence after every delivery,
per-view expected flags, observed edge counts and whether adjacent snapshots
qualify for comparison. Its relation change counts come from the existing
`compare_snapshots` function only when both inputs are complete. Empty and
partial snapshots remain inspectable without treating missing coverage as zero.

Qualification and scheduled analysis are distinct. The metadata's
`qualified_comparison_status` and `qualified_relation_change_counts` describe
the generator's source comparison check. The tracker skips analysis when
graph values, population and coverage are all unchanged, including evidence-only
and attribute-only receipts. Its expected receipt fields are separately recorded
as `tracking_comparison_status` and `tracking_comparison_reason`: duplicates
have no comparison; unchanged observations give `NOT_RUN/no_observable_change`;
an observable change with incomplete before/after coverage gives
`NOT_RUN/incomplete_before_or_after_coverage`; otherwise the small example gives
`OK`. Unchanged communication observations therefore need no repeated analysis.

## Evidence, retractions and coverage

The late correction preserves the link's source system, fact ID and kind and
supersedes its active record. The next revision changes only evidence and the
numeric spelling `1` to `1.0`. It must not be reported as a reweighted edge.
The retraction has `payload: null` and supersedes that latest head. A separate
zero-valued source fact supplies explicit absence evidence; withdrawal alone
is not evidence that a real relationship ended.

Coverage changes use one revision chain: complete → partial → complete. Adding
an independent conflicting coverage assertion would be invalid. Declaring
`unobserved` while positive observations remain active would also be invalid;
the example deliberately uses `partial` instead.

The tracker must distinguish the full snapshot hash, selected evidence, and
observed graph values. Every newly appended record changes receipt-prefix
provenance and therefore snapshot hashes, including the unrelated communication
view. An attribute-only receipt can leave all graph values and selected network
evidence unchanged. A changed content hash is not by itself a changed network.

The journal envelope's `source_revision` remains
`invented-network-tracking-source-v1`; individual record revisions identify the
source updates. Holding the envelope fixed lets any old K reproduce its old
snapshot after later receipts arrive.

## Separate rejection case

After the main stream, `rejected-conflicting-retry.jsonl` resends `link-v1` with
different source content under the same record ID. This must be rejected, with
sequence 9, K22 and the last checkpoint unchanged. It is not part of either
successful stream segment. Exact duplicate detection includes every raw source
field; updating `source.revision` on a retry would also make it conflicting.

## Generation and scope

```sh
python examples/network-tracking/generate_fixture.py
python examples/network-tracking/generate_fixture.py --check
```

The generator uses the real importer, snapshot materializer and qualified
snapshot comparison. It checks the semantic sequence above, duplicate handling,
the rejection case, fixed-cutoff byte replay and a journal JSON round trip at
the restart point. It inserts no current timestamp into generated files.
`--check` compares existing fixture bytes without writing.

Persistent checkpoint recovery, acknowledgments before EOF and the actual CLI
process restart are separate runner checks, explicitly marked unexecuted in
metadata. This fixture cannot establish authenticated source times, a remote
subscription, real-world social effects, or causal influence from a person's
attribute to a relationship.
