# Source-time progression and rolling network windows

Temporal tracking adds an explicit source-time cursor to the existing local
tracker. A new observation can revise the network at the current cursor. A time
control can move the query forward and expire old window events even when no
new observation arrives. The two operations preserve separate meanings and
produce a replayable version chain.

The event journal, snapshot construction, NetworkX analyses and immutable local
store remain the original implementations. The fixed-view tracking core is
unchanged. This profile resolves registered templates into ordinary views and
records which operation caused each new version.

The [live UTC driver](live-tracking.md) can automatically generate these
explicit time controls while receiving batches. This guide describes the core
and manual `tracking run` contract; neither reads a wall clock itself.

## Two independent coordinates

The state is identified by a receipt cutoff **K** and a source-time **cursor**,
in addition to its immutable checkpoint sequence.

| Operation | Journal and K | Cursor | Result |
| --- | --- | --- | --- |
| New receipt batch | Append accepted source records | Unchanged | New checkpoint |
| Duplicate or empty batch | Unchanged | Unchanged | `NO_NEW_RECORDS`; no checkpoint |
| Forward time control | Entire journal and K unchanged | Strictly increases | New checkpoint, even if the graph is equal |
| Equal time control | Unchanged | Same parsed instant | `NO_TIME_ADVANCE`; no checkpoint |
| Backward time control | Unchanged | Rejected | No checkpoint |

Every committed transition carries `cause="receipt_batch"` or
`cause="source_time_advance"`, both cutoffs and both cursor values. The source
receipt counts in a time transition are zero; no artificial source observation
is inserted to make time pass. Checkpoint sequence advances for either kind of
commit, so K alone is not a unique checkpoint identifier.

The cursor is a declared position at which to query supplied evidence. It is
not a receipt timestamp, a promise that all earlier events have arrived, or an
authentication of source time. Late corrections remain admissible under the
existing journal rules. A large cursor jump rebuilds the requested endpoint;
it does not inspect every intermediate instant.

## Register state queries and trailing windows

Use `sociolab.temporal-tracking-spec.v1` with exactly `schema`, `initial_cursor`,
`source_time_unit`, and `views`. Every view has `view_id`, a view template,
`window_width`, and `analysis`.

```json
{
  "schema": "sociolab.temporal-tracking-spec.v1",
  "initial_cursor": 10,
  "source_time_unit": "tick",
  "views": [
    {
      "view_id": "cooperation",
      "view": {
        "schema": "sociolab.view.v1",
        "population": "team",
        "layer": "cooperation",
        "mode": "state",
        "directed": false
      },
      "window_width": null,
      "analysis": {}
    },
    {
      "view_id": "recent_communication",
      "view": {
        "schema": "sociolab.view.v1",
        "population": "team",
        "layer": "communication",
        "mode": "events",
        "directed": true,
        "actions": ["reply", "utterance"]
      },
      "window_width": 10,
      "analysis": {}
    }
  ]
}
```

A template must not contain `at`, `start`, or `end`. State templates require
`window_width: null` and resolve to `at=cursor`. Event, participation and
annotation templates require a positive integer width and resolve to
`[cursor-width, cursor)`. The original view validator applies after resolution.

The unit must be `tick` for a ticks journal or `microsecond` for a UTC journal.
Widths are exact integers: ten seconds in UTC is width `10000000`. Booleans,
fractional widths, incompatible units, negative ticks and windows outside the
supported UTC calendar are rejected. Windows are never silently shortened to
fit. UTC cursor output is normalized to six fractional digits and a `Z` suffix;
equivalent accepted `Z` and `+00:00` spellings denote the same instant.

The registration fixes the initial cursor, template, width, selection filters
and analysis settings. It admits 1–16 views and retains the existing defaults
and qualified analysis budgets. Changing a window width, source layer,
population, annotation method, projection, seed or algorithm requires a new
registration and store. Each checkpoint also saves every actual resolved view.

## Input commands and CLI

The same `tracking init/run/inspect` commands support a fixed or temporal
registration. Existing fixed stores retain their original receipt-only input
contract and reject time controls.

```sh
python -m sociolab tracking init examples/time-tracking/empty.events.json examples/time-tracking/registration.json /path/to/fresh-private-store
python -m sociolab tracking run /path/to/fresh-private-store < examples/time-tracking/commands-before-restart.jsonl
python -m sociolab tracking inspect /path/to/fresh-private-store
python -m sociolab tracking run /path/to/fresh-private-store < examples/time-tracking/commands-after-restart.jsonl
```

A receipt line retains schema `sociolab.network-tracking-batch.v1` and exact
fields `schema`, `records`, `received_at`. It holds the current source cursor
fixed. An explicit time control has exactly these two fields:

```json
{"schema":"sociolab.network-tracking-advance.v1","cursor":20}
```

For a UTC journal, `cursor` is an accepted UTC timestamp string. For a ticks
journal, it is a strict integer. A string such as `"20"` is not an integer tick.
Adding receipt records or a receipt timestamp to an advance command is an error.
Send separate commands in the intended order when both evidence and source time
need to change; their order is preserved in separate checkpoints.

Temporal receipts add `cursor`, exact parsed `cursor_value`, `source_time_unit`,
`view_templates_fixed`, and `transition_cause`. Every view summary includes its
resolved `source_time`, either `{at}` or `{start,end}`. On duplicate/equal-time
requests, the receipt reports the requested cause and the current cursor but
does not repeat an earlier transition's change flags. Initialization and
inspection have no newly requested cause.

An equal-time retry is idempotent at the current cursor. Once another command
has advanced farther, resending an older cursor is a backward request and is
rejected. There is no historical command-ID ledger or exactly-once delivery
guarantee. A producer recovering a lost acknowledgment should inspect/retry
before sending new progress, under the existing single-writer rules.

The stream still stops at the first failed line, preserves earlier commits,
flushes one receipt per successful request, and ends normally at EOF. A local
producer or explicit user action supplies time controls. This command adds no
wall-clock timer, scheduler, remote subscription or background-service manager.
The separate `tracking live` command supplies a local UTC timer; see its
[input, clock and EOF rules](live-tracking.md).

## Source-time selection and interpretation

The original materializer makes these selections:

| View or evidence | Boundary |
| --- | --- |
| State-view `relation.changed` / `membership.changed` | Latest source state with `occurred_at <= cursor` |
| Event-count window | `cursor-width <= occurred_at < cursor` |
| Point/interval observations | Only their declared instant or half-open interval; no extra carry-forward |
| Identity and entity resolution | Effective declarations at receipt cutoff K, under the existing journal contract |

Window views derive eligible people from membership intervals across the whole
window. Communication events also require both participants to be present at
the event's source time. A person who leaves at tick 18 can therefore retain an
eligible event at tick 15 in `[10,20)`; their state at cursor 20 does not erase
their earlier participation.

An event at the right window boundary is excluded. An event at the left boundary
is included and exits only when the left boundary moves beyond it. A supplied
future-dated state change can become selected as the cursor reaches its source
time; the tracker is querying a previously received declaration, not forecasting
a new fact. The example's future-dated records are deliberately invented to
exercise this boundary.

Receipt refreshes reconstruct the current queries using later evidence. Time
advances reconstruct different queries using the same evidence. Both retain
the separate graph, population, coverage and evidence flags documented in the
[fixed tracking guide](network-tracking.md#four-independent-kinds-of-change).
Receipt-prefix hashes stay equal during a time-only advance, while snapshot
hashes change with their resolved queries.

Window expiry can remove a communication edge or reduce its count without
retracting a single source record. That means the selected recent-event window
changed. It does not establish that a person stopped communicating, that a
relationship ended, or that a conflict was resolved. A new checkpoint with all
four flags false still records a real query-time advance and must survive
restart.

## Coverage and analysis

Coverage is recomputed for the actual resolved query. For coverage `[0,20)`, a
state view at tick 20 is outside its interval, while a trailing window `[10,20)`
can remain fully covered. Advancing that window to `[11,21)` introduces an
uncovered segment and can make it partial. Known positive observations remain
in the snapshot; missing coverage is not evidence of absent relationships.

The existing comparison policy applies to immediate adjacent versions. The
tracker skips full comparison when graph/population/coverage are unchanged,
when an observable change involves an incomplete endpoint, or when the analysis
budget is exceeded. Coverage recovery is still compared with its immediately
preceding incomplete version and therefore does not immediately qualify that
transition for analysis. A later complete-to-complete change can qualify.

Community discovery, structural analysis, requested key groups and explicit
person–activity projection continue through the original functions. The
200-node / 2,000-edge tracking-wide budget, projected-edge preflight and
separate group-selection budgets are unchanged. Source-time progression adds
no graph solver or alternative community algorithm.

## Replay and failure boundaries

The shared immutable store still uses one numbered JSON file per committed
version, POSIX locking and non-overwriting atomic publication. Startup replays
the complete chain. For a receipt transition it reconstructs the new raw tail
and keeps the previous cursor; for a time transition it requires the entire
journal to be equal and reconstructs at the saved new cursor. It rejects a
stored equal-time checkpoint, a receipt checkpoint with no new tail, and an
advance that secretly appends source records.

Exact regenerated state and transition comparisons also bind registration,
clock, source envelope, cursor, snapshots and the predecessor hashes. Editing a
derived report or moving a cursor and recomputing the hashes does not replace
semantic replay. These are consistency checks on supplied artifacts, not
source authentication or independent proof of historical availability.

The existing [storage failure boundaries](network-tracking.md#atomic-commits-and-restart)
remain in force: final published files are never rolled back after an output
failure; locks release on process exit; recognizable unfinished temporary files
are ignored; corrupt finals, gaps and unexpected files stop replay. Full
historical reconstruction grows with retained history and is intended for
small local studies. Runtime changes that alter saved results require an
explicit migration decision; no silent conversion is performed.

## Executed invented case

The [frozen protocol](experiments/2026-11-28-time-tracking/protocol.json),
[input metadata](../examples/time-tracking/metadata.json), runner and independent
checker were all finalized before this case. Four invented people and three
query templates exercise two state layers and a ten-tick communication window.
All source observations and future-dated boundary cases were known in advance.

| Checkpoint | K | Cursor | Observation |
| ---: | ---: | ---: | --- |
| 0 | 0 | 10 | Empty initial journal; views lack coverage. |
| 1 | 19 | 10 | Initial observations received; a communication event at 10 is still outside `[0,10)`. |
| 2 | 19 | 15 | Time-only advance selects a state change at 15 and the communication window `[5,15)`. |
| 3 | 20 | 15 | A late correction revises a communication endpoint while the cursor stays fixed. |
| 4 | 20 | 20 | Time-only advance; cooperation state loses coverage while `[10,20)` communication remains complete. |
| 5 | 20 | 21 | Communication window now partly exceeds its coverage; known positive observations remain. |
| 6 | 22 | 21 | New coverage records restore completeness at the same cursor; the immediate predecessor was incomplete. |
| 7 | 22 | 25 | Cursor advances with all four semantic change flags false; the new checkpoint is still retained. |
| 8 | 22 | 26 | The event at tick 15 leaves `[16,26)`; the journal and K remain equal. |

The stream contains **11 requests**: three accepted receipt batches, five
accepted time advances, two equal-time retries and one duplicate receipt batch.
It creates **nine checkpoints** and **27 snapshots**, with **five qualified
view comparisons**. Final cooperation, communication and trust edge counts are
**3, 1 and 1**, respectively, with complete coverage in all three views.

Two actual CLI processes received input through live pipes. All eleven
acknowledgments arrived before EOF. After request 5 the runner used SIGKILL on
the first process, at the time-only checkpoint **sequence 4 / K20 / cursor20**.
The same store replayed and recovered that exact position before the second
process continued. All nine checkpoint files retained their creation hashes.
Competing access was rejected; backward time, a string tick cursor and a mixed
advance/receipt command each exited with code 2 and preserved the final head.

The [aggregate report](experiments/2026-11-28-time-tracking/report.json) retains
the per-request receipts, and the
[execution record](experiments/2026-11-28-time-tracking/execution.json) binds the
implementation, fixture, protocol and checker hashes before/after the run.
The case tests process termination and explicit input controls, not physical
power loss, an external subscription, a clock scheduler or an operational
latency guarantee.

**405 native tests passed**, including **25 new tests**, with zero failures,
errors or skips. The
[test execution record](experiments/2026-11-28-time-tracking/tests-execution.json)
confirms all source/test hashes were unchanged during the suite. Separately,
the new shared store successfully replayed all ten retained fixed-profile
checkpoints from the preceding case and returned the identical saved summary;
all fifteen old private JSON files were unchanged. That
[fixed-profile replay record](experiments/2026-11-28-time-tracking/fixed-profile-replay.json)
does not rerun the earlier input stream.

The [standard-library checker](experiments/2026-11-28-time-tracking/independent_time_tracking_check.py)
was frozen before execution, SHA-256
`cae5e9a7674455f10783a58363bb6a5c25f9231f9adcbded7cb61e7669b0854c`.
Its [result](experiments/2026-11-28-time-tracking/independent-check.json) reports
**6,620 checks, including 877 exact numeric comparisons**, with maximum absolute
difference zero. It independently reconstructs all 27 fixture snapshots and
checks full journal equality on time advances, unchanged cursor on receipt
appends, source revision chains, boundaries, coverage, fingerprints and saved
transition/receipt bindings. All fourteen private JSON artifacts remained
unchanged. It checks retained process records but does not independently observe
the process, rerun the tracker or implement community algorithms.

## Python API

| Function in `temporal_tracking.py` | Meaning |
| --- | --- |
| `initialize_temporal_tracking(dataset, registration)` | Resolve templates at the initial cursor and create state 0. |
| `apply_temporal_tracking_batch(state, batch, received_at=None)` | Append observations while holding the cursor fixed. |
| `advance_temporal_tracking(state, cursor)` | Move source time while keeping the complete journal/K unchanged. |
| `validate_temporal_tracking_state(state)` | Validate and reconstruct all saved snapshots at their declared cursor. |

Both mutation functions return a fresh `state` and separate `transition`, without
writing files. The shared `tracking_store` functions additionally retain and
replay the complete ancestry. The original fixed-profile Python API remains
available with its fixed-query semantics.

## Relation to the research question

This extension can show how a recent interaction window, a source-declared
relationship state or observation coverage changes as the selected time moves
forward. It can separately show how a late correction revises the current view.
Those distinctions are needed before interpreting community movement, network
fragmentation or changing structural positions.

Behavior forecasts and their target-version evaluation remain separate. No
automatic forecast issuance, language interpretation, causal mechanism or
validated effect on later behavior follows from advancing a query cursor.
