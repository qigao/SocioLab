# Invented inputs for automatic UTC tracking

This directory contains a deterministic source-fixture builder, not captured
live data. Its observations describe four invented people, A–D, with
`origin: synthetic`. The builder takes one explicit UTC anchor and reads no
clock, writes no file, and starts no tracking process. Runtime inputs belong in
the case runner's private output directory; no generated current-time JSON is
stored here.

## Frozen function interface

`generate_fixture.py` exposes:

```python
build_fixture(anchor_utc: str) -> dict
```

The returned dictionary has exactly four entries:

| Key | Value |
| --- | --- |
| `dataset` | A `sociolab.events.v1` UTC journal containing 13 records accepted by the existing importer. |
| `registration` | A `sociolab.temporal-tracking-spec.v1` registration with the normalized anchor as its initial cursor. |
| `late_batch` | One complete `sociolab.network-tracking-batch.v1` envelope correcting an existing relationship fact. |
| `metadata` | `sociolab.live-tracking-fixture.v1` metadata with exact time formulas, source expectations, canonical input hashes and scope. |

The caller freezes the builder and its execution protocol, samples one UTC
anchor `T0`, calls the function once, and saves the returned values privately.
The anchor must satisfy the existing UTC parser and admit the required offsets
within the supported calendar. Equivalent accepted UTC spellings normalize to
six fractional digits and a `Z` suffix. There is no implicit `now` default or
command-line mode that samples time.

Initialize the store directly from `dataset` and `registration`. The dataset
already contains the imported initial observations; do not send them again as
an additional initial batch. This fixture starts at **sequence 0, K13**.

## Source structure and exact time formulas

All temporal values are computed using integer microseconds.

| Item | Formula or definition |
| --- | --- |
| Initial cursor and initial source receipt time | `T0` |
| Entity, membership and relationship source time | `T0 − 1 day` |
| Complete coverage for both layers | `[T0 − 1 day, null)` |
| One communication event | A → C, reply, at `T0 − 1 second` |
| Trailing communication window | `[cursor − 3 seconds, cursor)` |
| Event's expiry boundary | `T0 + 2 seconds` |
| Event has left the window | `cursor > T0 + 2 seconds` |
| Late batch's explicit source receipt time | `T0 + 1 second` |

The initial 13 records are four entity declarations, four membership changes
marking everyone present, two coverage declarations, two cooperation relations
A–B and C–D, and the single communication event. Every view keeps all four
people, including isolates.

| View ID | Policy | Initial graph |
| --- | --- | --- |
| `cooperation` | Undirected state at the cursor; `window_width: null` | A–B, C–D, unit strength |
| `communication` | Directed reply/utterance counts; `window_width: 3000000` | A → C, count 1 |

Both views use `analysis: {}` and complete, explicitly authored coverage. The
open-ended declarations keep the example focused on scheduling and source
revisions; they do not authenticate real-world observation coverage.

The late correction replaces A–B with A–D at the same historical source time.
Its record ID is `cooperation-A-D-correction`, its fact ID remains
`cooperation-A-B`, and it supersedes record `cooperation-A-B`. Its kind remains
`relation.changed`, direction is undirected, strength is 1, and record revision
is `late-correction`. It is one new journal record: **K13 becomes K14**.

The envelope's `source_revision` remains
`invented-live-tracking-source-v1`; every record's source system is
`invented-live-tracking`. Replaying the complete `late_batch` exactly is an
idempotent duplicate. No second fixture version or different retry timestamp
is needed.

The source receipt times `T0` and `T0 + 1 second` are explicit, authored
provenance values, ordered consistently for the importer. They are not a claim
about when the live CLI actually receives either input. The runner records its
actual process operations, clock samples and acknowledgments separately.

## Source-only checks inside the builder

The function uses the existing importer and materializer. It verifies that the
initial graphs are complete, the endpoint correction changes the cooperation
graph, the exact duplicate is idempotent, and the old K13 snapshots remain
byte-identical when replayed after the K14 correction.

The initial window includes the event. At exactly `T0 + 2 seconds`, the event
is at the inclusive lower boundary and is still included. One microsecond
later it is excluded. These are deterministic source-materialization checks;
the live process is not required to sample those exact instants.

Metadata records both the expiry boundary's UTC string and its exact parsed
microsecond value. It includes the two initial snapshot hashes and canonical
content hashes for the three input objects. The after-expiry-and-correction
expectations are cooperation edge count 2, communication edge count 0, four
people in each view, and complete coverage. Its verification fields concern
only work performed inside the builder, not the future live case.

## Live execution contract and expected invariants

The runner uses the UTC temporal store with:

```sh
python -m sociolab tracking live /path/to/private/store --interval-ms 1000
```

The live command admits UTC temporal stores only. Its default interval is
1,000 ms, with accepted integer values from 1 through 86,400,000. Startup checks
that current UTC is not behind the saved cursor, but does not itself advance
time. The first timer is due one interval later. Each timer uses the current
UTC sample, and the next deadline is measured from timer completion. The
interval is a scheduling configuration, not a real-time latency promise.

Stdin supplies receipt batches while the timer generates source-time advances.
Manual advance commands are rejected in this mode. Observed EOF stops future
timers and permits the last valid non-newline-terminated input line to be
processed. Stdout contains ordinary receipts, with no extra startup or final
record.

The separate runner can hold stdin open and idle until an automatically saved
cursor exceeds the event's expiry boundary. It should verify that the event
leaves the communication window while the full journal and K13 remain equal.
A slow process start can make the first automatic advance cross that boundary;
the initial saved snapshot already establishes that the event was included.

The late batch may be split before its final newline to verify that incomplete
input does not block automatic progress. After the complete line arrives, the
receipt operation must preserve its own before/after cursor and change K13 to
K14. Other automatic commits can occur between the runner's observations, so
the receipt's cursor need not equal the runner's previously observed cursor.
The state correction remains effective regardless of how far the communication
window has advanced.

For SIGKILL/restart, every acknowledged checkpoint must survive unchanged. A
complete time checkpoint published before termination may not yet have been
acknowledged; the recovered head may therefore be later than the last receipt
read by the runner. Such versions must be retained and accounted for. No fixed
automatic-tick count, final checkpoint count, or precise sampling time is
declared by this fixture.

Actual timer behavior, partial-input handling, process termination, output
delivery and store recovery require the separate live case. The builder does
not execute or validate those runtime paths. Runtime inputs, outputs and
checkpoints are private; public evidence should contain only aggregate results
and artifact bindings. This example makes no claims of authenticated source
time, complete real-world event arrival, operational latency, social causality
or predictive effectiveness.
