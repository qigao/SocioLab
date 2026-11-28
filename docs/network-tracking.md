# Continuous receipt tracking for fixed network views

The fixed-view `tracking` profile connects the existing event importer,
snapshot materializer and NetworkX change analysis to a local, continuously
running JSONL input process.
Each delivery that appends records produces an immutable checkpoint and an
immediate JSON receipt. A restarted process replays the retained history and
continues at the same journal cutoff.

This is **receipt-driven reconstruction of fixed source-time views**. It answers
“what changed in these registered views after this evidence arrived?” The source
query remains fixed: a newly received correction can change the reconstruction
of an earlier instant. The process does not advance source time automatically.
The separate [temporal profile](time-tracking.md) uses the same local store and
CLI to accept explicit time controls for state queries and trailing windows.
The contracts below describe the original fixed-view profile.

The implementation uses the original [event journal](dynamic-analysis.md),
`materialize_snapshot`, `compare_snapshots` and upstream NetworkX routines. It
adds no alternative graph engine, numerical solver or authoritative Agent world.

## Run the invented example

Use an installed SocioLab environment, or the project's existing development
environment with `PYTHONPATH=src`. The store path must be a new directory whose
parent already exists.

```sh
python -m sociolab tracking init examples/network-tracking/empty.events.json examples/network-tracking/registration.json /path/to/fresh-private-store
python -m sociolab tracking run /path/to/fresh-private-store < examples/network-tracking/batches-before-restart.jsonl
python -m sociolab tracking inspect /path/to/fresh-private-store
python -m sociolab tracking run /path/to/fresh-private-store < examples/network-tracking/batches-after-restart.jsonl
python -m sociolab tracking inspect /path/to/fresh-private-store
```

The first command creates an empty-journal baseline with three registered views.
The two input files divide one invented sequence around a restart. Do not also
import `initial.batch.json`: that file is the complete first delivery, already
included in the first stream. The [fixture guide](../examples/network-tracking/README.md)
explains every invented source record and expected transition.

File redirection ends when the file reaches EOF. To keep the process running,
an upstream local producer can keep its stdin pipe open and write one complete
JSON object plus a newline per delivery. The tracker commits and flushes each
receipt before requesting the next line. Waiting for that receipt before
sending another delivery gives the producer an explicit acceptance boundary.

`inspect` takes the same exclusive lock as `run`; it fails promptly while another
process owns the store. Read the running process's receipts to observe ongoing
progress. End the writer before requesting a full inspection.

## Freeze the full view definition

A registration has schema `sociolab.network-tracking-spec.v1` and between one
and sixteen ordered views. Every item has exactly `view_id`, `view`, and
`analysis`; empty analysis settings select normalized defaults.

```json
{
  "schema": "sociolab.network-tracking-spec.v1",
  "views": [
    {
      "view_id": "cooperation_at_15",
      "view": {
        "schema": "sociolab.view.v1",
        "population": "team",
        "layer": "cooperation",
        "mode": "state",
        "directed": false,
        "at": 15
      },
      "analysis": {}
    }
  ]
}
```

All existing state, event-count, participation and annotation view contracts
remain available. The registration binds the **complete normalized view**,
including `at` or `start/end`, and all analysis settings. A snapshot's
`policy_hash` intentionally excludes source-time boundaries and is insufficient
by itself to freeze a tracking query. Changing a view, projection, method,
algorithm, seed or group selection requires a new registration and store.

Analysis defaults are `algorithm="greedy"`, `seed=0`, `resolution=1.0`, no
requested group, and `projection="none"`. The other accepted settings are the
existing `group_size`, `group_members`, `max_nodes`, `max_edges` and `max_pairs`
arguments. Unsupported settings and incompatible projections are rejected.

## Delivery and receipt contracts

Each input line has exactly these fields:

| Field | Meaning |
| --- | --- |
| `schema` | `sociolab.network-tracking-batch.v1` |
| `records` | A raw event-record array, omitting importer-owned `ingest_seq` and `recorded_at`. |
| `received_at` | An explicit UTC timestamp, or `null` to assign current UTC during ingestion. |

Receipt order is distinct from source time. Newly appended records must have
nondecreasing UTC receipt times; source events and corrections can arrive late.
An explicit timestamp is a supplied claim, not an authenticated clock. The
example's timestamps and observations are invented.

Input lines are limited to 1,048,576 Unicode characters, including their newline.
Duplicate JSON keys, blank lines, malformed JSON, extra envelope fields,
conflicting record reuse and invalid journal/snapshot states fail the command.
Processing stops at the first failed line. Earlier committed deliveries remain
available, and later lines are not intentionally consumed by the tracker.

The importer provides **record-level idempotence**. Sending the same record ID
with identical raw source content adds no receipt, even if that fact has since
been superseded. It does not restore an old head. Reusing an ID with different
source content is an error. A mixed duplicate/new batch appends only new records.

An empty or all-duplicate batch returns `NO_NEW_RECORDS` at the current head and
creates no checkpoint. Its receipt has no new view-transition flags. There is
no separate batch-ID ledger; a repeated delivery does not necessarily return
the original historical acknowledgment if other deliveries have since arrived.

Successful receipts contain the sequence, K, checkpoint/state/registration
hashes and per-view counts, completeness and change flags. They omit raw person
and edge arrays. View names and counts are still user-supplied research output;
the receipt format alone does not establish anonymity. Complete checkpoints
contain the journal and detailed actor/network evidence and belong in private
storage.

## Four independent kinds of change

Every newly appended journal record changes the receipt prefix bound into each
snapshot. That fact alone does not mean that a network changed.

| Flag | Compared content | Example |
| --- | --- | --- |
| `observed_graph_changed` | Person/activity sets, graph type, weight meaning, endpoints and numeric strengths. | A selected relationship is added, removed or reweighted. |
| `population_changed` | Eligible, absent and unknown members, exposure and unknown intervals. | New identity or membership evidence changes who can be observed. |
| `coverage_changed` | Overall completeness and per-person coverage states. | Complete observation becomes partial. |
| `evidence_changed` | Selected record IDs, edge/coverage evidence and annotation summary. | An equal-valued source revision replaces its evidence. |

Graph fingerprints normalize equal integral numeric weights: strength `1` and
`1.0` do not create a false reweight. The original source payload and snapshot
remain preserved. All four flags can be false after a new receipt, for example
when an actor attribute is outside every registered network view.

All registered views are rematerialized after an append. This conservative
policy accounts for revisions that change source time or endpoints, identity
mapping, membership and coverage. It does not yet use a selective dependency
index or an incremental community algorithm. The savings come from skipping
unnecessary derived analyses after unchanged observable graph/population/coverage.

For a fixed source instant, an added or removed reconstructed edge is a
**knowledge revision between receipt prefixes**. It is not evidence that the
relationship formed or ended at the wall-clock time of receipt. A source-coded
conflict, an actor attribute and a separate relationship update retain their
distinct meanings. No automatic conflict-to-edge rule is introduced.

## Qualified comparison and missing observations

The tracker uses the immediately preceding checkpoint for each comparison.
It calls the original `compare_snapshots` when graph, population or coverage
changes, both snapshots are complete, and the tracking analysis budget permits
the work. The resulting report retains source changes, relations, population,
structure, communities, requested key groups and any explicit affiliation
projection under their existing qualification rules.

| `comparison.status` | Reason or result |
| --- | --- |
| `OK` | The original descriptive comparison report is saved privately. |
| `NOT_RUN / no_observable_change` | Graph, population and coverage are equal; selected evidence can still differ. |
| `NOT_RUN / incomplete_before_or_after_coverage` | An observable change exists, but at least one adjacent snapshot is incomplete. |
| `NOT_RUN / analysis_budget_exceeded` | A changed, complete pair exceeds the tracking-wide node or edge limit. |

The no-observable-change check precedes the completeness check. Every transition
also records `before_complete` and `after_complete`; a skipped unchanged view
must not be read as proof of full observation. Duplicate stream receipts carry
the current completeness but no new transition.

Partial snapshots remain inspectable and preserve known observations. When
coverage recovers, the preceding partial snapshot still prevents a qualified
comparison for that recovery transition. The tracker never silently jumps to
an older complete snapshot. Contradictory assertions are errors, distinct from
incomplete observation, and abort the whole uncommitted batch.

Tracking-wide analysis limits are 200 nodes and 2,000 edges per input graph.
For participation views, both incidence graphs and requested person projections
must fit. Projection preflight uses the original bounded `affiliation_report`;
it does not implement another projection. A 67-person, one-activity incidence
graph has only 67 incidence edges but projects to 2,211 person pairs, so the
wrapper skips complete graph analysis. Existing group-selection budgets remain
separate, and a projection exceeding its `max_pairs` contract raises an error.

These bounds constrain derived graph analysis, not total journal length or
the cost of retaining and validating receipts. The journal and snapshots are
copied into each checkpoint. This first storage format targets small local
studies; long histories need a separately designed storage/retention strategy.

## Atomic commits and restart

The store is created with private directory permissions; checkpoint files use
private file permissions. Local POSIX `flock`, hard links and directory `fsync`
are required. No claim is made for unsupported or remotely mounted filesystems.
Other SocioLab commands can still import on platforms without `fcntl`; tracking
storage reports an explicit unsupported-platform error when requested there.

One writer holds the lock for the input session. Each new version is one JSON
file containing the complete state, its transition and the preceding checkpoint
hash. The initial version is `00000000.json`, followed by contiguous sequence
numbers. There is no mutable `HEAD` or separately overwritten journal file.

The writer saves and fsyncs a uniquely named temporary file, publishes its
numbered name with a hard link that cannot overwrite an existing file, removes
the temporary name, and fsyncs the store directory. Initialization also fsyncs
the parent directory. Only then does it send and flush a success receipt.

Once the final numbered file is published, errors do not remove it. A failure
in later durability confirmation or receipt output can leave a committed
version whose acknowledgment was lost. Inspect and retry the same records
before supplying new ones; record idempotence prevents duplicate ingestion.
This is not an exactly-once output-delivery guarantee. The experiment exercises
process termination and injected I/O failures, not physical power loss.

On restart or inspection the loader checks every numbered checkpoint, then
chronologically replays the initial state and each appended receipt tail using
the fixed registration. It verifies the full journal envelope and old raw
prefix, snapshot reconstruction, transition output and hash chain. A
hash-consistent edited historical derived report fails semantic replay.
Comparing the compact snapshot record-history metadata alone would not protect
the original raw source fields.

Gaps, unexpected files, symlinks, corrupt final JSON and mismatched replay fail
closed. Recognizable unfinished temporary files are ignored and never promoted
to commits. An interruption before the first commit can leave an uninitialized
directory; `init` deliberately refuses to overwrite it. Inspect the situation
and choose a new path rather than treating partial initialization as accepted.

Full historical replay costs grow with retained history and can repeat original
upstream analyses. A runtime or implementation change that alters a saved
result fails replay; this command supplies no silent migration. The hashes
establish consistency among the provided files, not author identity, authentic
source times or completeness of an external data feed.

## Executed invented case

The [fixed protocol](experiments/2026-11-28-network-tracking/protocol.json)
and input expectations were recorded before the actual CLI execution. The
[runner](experiments/2026-11-28-network-tracking/run_tracking_case.py) used two
live stdin pipes, checked every receipt while input remained open, and killed
the first process with SIGKILL after its eighth acknowledgment. It then inspected
the same store and restarted it. All original inputs were known in advance;
this was an engineering execution, not external preregistration or prospective
social research.

| Observed result | Recorded value |
| --- | --- |
| Invented people and registered views | 4 people, 3 fixed views |
| Deliveries | 11: 9 append new records and 2 are idempotent retries |
| Retained checkpoints | 10, including the empty initial version |
| Checkpoint after forced process exit | Sequence 7, K20; recovered exactly on restart |
| Final checkpoint | Sequence 9, K22 |
| Acknowledgments observed before EOF | All 11 |
| Qualified view comparisons actually executed | 6 |
| Final edge counts | Cooperation at tick 5: 2; at tick 15: 3; communication: 1 |
| Final observation coverage | Complete in all three views |
| Retained checkpoint bytes | All 10 match their creation-time hashes |

The first new relationship affects only the later cooperation view. Correcting
its endpoint and source time changes both views. An equal-valued revision then
changes evidence without changing the graph. The unrelated actor attribute
changes only receipt provenance. Coverage loss and recovery preserve edges
but skip comparison against incomplete adjacent observations; a later complete
pair resumes analysis. Communication remains unchanged after its initial batch.

A competing process was rejected while the writer held the lock. A final
conflicting reuse of a record ID exited with code 2 and changed no checkpoint.
The [execution record](experiments/2026-11-28-network-tracking/execution.json)
binds source/input hashes before and after the run; the
[aggregate report](experiments/2026-11-28-network-tracking/report.json) retains
all per-delivery summary receipts. Six additional runner boundary checks
confirmed path/overwrite rejection without rerunning the tracker case.

**380 native tests passed**, including 33 new tracking/core/storage/CLI tests,
with no failures, errors or skips. The
[native execution record](experiments/2026-11-28-network-tracking/tests-execution.json)
confirms source and test hashes were unchanged during that suite. Existing
forecast, journal, graph and numerical tests remain included; no installer or
consumer tests and no new CI workflow were introduced.

The [independent audit](experiments/2026-11-28-network-tracking/independent_tracking_audit.py)
uses only Python's standard library. It reconstructs 30 fixture snapshots and
checks raw revision chains, prefixes, state/transition/checkpoint hashes,
change flags, receipt bindings and retained execution records. Its
[result](experiments/2026-11-28-network-tracking/independent-check.json) reports
**6,408 checks, including 804 exact numeric comparisons**, with maximum absolute
difference zero. All 15 private JSON artifacts remained unchanged. The audit
does not rerun the tracker or independently implement community algorithms.

The validation history is retained explicitly. After the case, extra
protocol/public-output assertions were added to the checker. The first audit
correctly refused the resulting mismatch with the checker version frozen into
the execution record; its
[failed execution record](experiments/2026-11-28-network-tracking/independent-execution-attempt-1.json)
is preserved. The original checker was restored byte-for-byte as
`independent_tracking_check.py` (SHA-256 `f8b2b04c65c1d154ad71a936f062778ecf73f73b5f159b9cd7458468cb96a625`).
The expanded audit is separately retained as `independent_tracking_audit.py`
(SHA-256 `184a4636436fbd634eac74c79b50e7c99d33d16ed28d7ff7d61e22cfe6db6866`).
The [successful audit execution](experiments/2026-11-28-network-tracking/independent-execution.json)
checks the unchanged original case bindings and identifies the exact separately
executed audit version. Production source, fixtures and saved checkpoints were
unchanged, and the tracking case was not rerun.

## Python interfaces

| Interface | Result |
| --- | --- |
| `initialize_network_tracking(dataset, registration)` | Initial private state with normalized registration, journal and every snapshot. |
| `apply_network_tracking_batch(state, batch, received_at=None)` | Fresh `state` and separate `transition`; no filesystem mutation. |
| `validate_network_tracking_state(state)` | Fresh validated state after replaying its snapshots. |
| `initialize_tracking_store(path, dataset, registration)` | New private store and initialization receipt. |
| `consume_tracking_stream(path, source, output)` | Serial commit/acknowledgment until EOF; returns processed delivery count. |
| `inspect_tracking_store(path)` | Full retained-history replay and current summary. |

Core functions are in [network_tracking.py](../src/sociolab/network_tracking.py);
persistence functions are in [tracking_store.py](../src/sociolab/tracking_store.py).
The pure core validates one state; the store additionally checks its ancestry
and replays every retained transition.

## Relationship to behavior forecasts

The [journal forecast](journal-forecast.md) and
[receipt-version evaluation](journal-evaluation.md) commands remain separate.
Tracking does not automatically select forecast origins, train models, choose
future target versions or explain causal effects. A later integration can
consume committed journal prefixes while keeping those forecasting decisions
explicit. This command also supplies no remote connector, background service,
rolling source-time window, automatic language classifier, causal mechanism
or validated behavioral prediction.
