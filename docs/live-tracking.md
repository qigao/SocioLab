# Automatic UTC progression with continuous receipt input

`tracking live` drives an existing UTC temporal store with the local wall
clock while accepting source receipt batches from stdin. A kept-open pipe can
be idle, or contain an unfinished line, and the query cursor still advances.
Recent-event windows can therefore expire observations without receiving new
source records.

The driver uses the same writer lock, replay, immutable checkpoint publisher,
snapshot materializer and qualified comparisons as the
[explicit temporal tracker](time-tracking.md). It generates ordinary explicit
advance requests for that core. No alternate journal or graph engine is added.

## Run

Prepare a journal with `clock: {"kind": "utc"}` and a
`sociolab.temporal-tracking-spec.v1` registration with
`source_time_unit: "microsecond"`. Its initial cursor must not be ahead of the
machine's current UTC time. Initialize a new private store, then run:

```sh
python -m sociolab tracking init journal.json registration.json /path/to/private/store
python -m sociolab tracking live /path/to/private/store --interval-ms 1000
```

The second command runs in the foreground. Its stdin accepts UTF-8 JSONL
receipt batches using the original exact envelope:

```json
{"schema":"sociolab.network-tracking-batch.v1","records":[],"received_at":null}
```

An empty batch is a no-op. Real source adapters supply actual validated raw
records and keep the pipe open between deliveries. `received_at` keeps its
existing meaning: an explicit supplied receipt time, or `null` for importer
assignment. The driver never rewrites it to the query cursor. Nondecreasing
receipt validation and duplicate-record rules remain unchanged.

Manual advance commands are rejected on this command's stdin: the live driver
owns query-time progression. Use `tracking run` for explicit historical or
delayed source-time controls. Fixed-view stores and tick-clock stores are not
eligible for `tracking live`; ticks have no implicit conversion to wall time.

| Option | Meaning |
| --- | --- |
| `--interval-ms` | Integer from 1 to 86,400,000; default 1,000. Delay before the first clock update and after each completed clock update. |

The accepted minimum is a configuration boundary, not a claim that snapshots
can be produced every millisecond. There is no lag parameter or automatic
source-completeness watermark.

## Two clocks and one ordered writer

The driver schedules a deadline with `time.monotonic_ns()`. On a due update,
it separately samples `time.time_ns() // 1000` and formats that integer UTC
microsecond value with the existing temporal formatter. Nanoseconds below one
microsecond are discarded in this local clock sample; supplied source
timestamps still use the unchanged exact parser.

Python's [monotonic clock](https://docs.python.org/3.12/library/time.html#time.monotonic)
measures elapsed intervals independently of system clock adjustments. Its
reference value is not a UTC timestamp. The
[wall-clock API](https://docs.python.org/3.12/library/time.html#time.time_ns)
provides the actual timestamp used for this query. Host clock accuracy and
authentication remain external responsibilities.

| Event | Result |
| --- | --- |
| Startup | Replay existing versions, validate UTC temporal eligibility and check current UTC is not behind the saved cursor. No startup time commit. |
| First deadline | Sample current UTC after one configured interval. |
| Later UTC sample | Commit a time advance; full journal and K remain unchanged. |
| Equal UTC sample | Emit `NO_TIME_ADVANCE`; no checkpoint. |
| UTC behind saved cursor | Stop with an error; do not clamp, move backward or invent a later timestamp. |
| Receipt batch | Apply at the saved cursor; accepted new records advance K. The receipt does not reset the timer deadline. |
| Delayed work or forward clock jump | Sample the current endpoint once; do not manufacture all missed intermediate versions. |

The next deadline is **clock-update completion plus the interval**, including
completion of its output flush. This is fixed-delay scheduling. Receipt
processing, graph analysis, filesystem synchronization, OS scheduling and slow
stdout consumers can delay clock updates. No fixed sampling frequency or
latency bound is promised.

All operations share one synchronous writer. Before a due update, a bounded
ready input read can observe EOF. If EOF is not observed, at most one due clock
update and one complete input line are processed before rechecking the loop.
Continuous batches cannot reset the timer indefinitely; the timer cannot
repeatedly catch up ahead of an already buffered input line.

## Framing, EOF and output

The driver reads a file descriptor directly using nonblocking `os.read` and
`select.select`. It does not call a blocking text `readline()` after readiness.
This matters when a producer writes only part of a JSON line and leaves its
pipe open. Python documents POSIX pipe readiness in
[select](https://docs.python.org/3.12/library/select.html#select.select).

Each read is at most 65,536 bytes. Pending input is bounded to four times the
existing 1,048,576-character line limit, plus one byte to detect overflow.
Complete lines are decoded individually with strict UTF-8, then checked against
the character limit, including the newline. A split UTF-8 character is retained
as bytes until its line is complete. Invalid UTF-8 or JSON in a later line from
one read does not undo an earlier committed line from that read.

Observed EOF stops further timers. Buffered complete lines and a valid last
JSON line without a newline are processed, then the process exits normally.
An invalid final fragment fails with its line number. A producer's close is
not yet observed EOF while unread bytes remain in the pipe, so time commits
may still occur before EOF is actually read. An idle open pipe is not EOF.
The driver does not tail a regular file after reaching its end.

Stdout contains only the existing `NETWORK_TRACKING_RECEIPT` objects, one line
per successful input request or generated clock control. There is no startup
or final extra record. `transition_cause` distinguishes `receipt_batch` and
`source_time_advance`; no-op receipts have no new change flags. Every applied
operation publishes its complete checkpoint before writing and flushing its
receipt. Input errors stop at that line while retaining prior progress.

An output failure stops the process and reports that its checkpoint may
already be committed. Restart uses the retained store. The producer can resend
the same source records; their idempotence does not promise exactly-once
delivery of output acknowledgments.

## Recovery and storage growth

The same POSIX writer lock remains held for the session. A second writer or
inspection process cannot open the store concurrently. The caller's input
descriptor is left open, and its previous blocking mode is restored on normal
return or a handled failure. Callers must give the driver exclusive reading
ownership and must not mix buffered text reads with these descriptor reads.

Replay reconstructs the concrete cursors already saved; it never samples the
current clock to rewrite old versions. After replay, a new session can create
later clock versions. If a process was killed between checkpoint publication
and receipt delivery, recovery may find a head later than the last received
acknowledgment. That complete published version is retained, including a
time-only version with unchanged semantic flags.

Every forward time update saves a full journal and all registered snapshots,
even if graph, population, coverage and evidence remain equal. Disk use and
complete startup replay grow with retained history and configured frequency.
Choose a cadence and study duration appropriate for a small local study.
Compaction, retention policies, delta storage and a continuously operated
large-scale service are not implemented by this driver.

## Meaning of the saved scope

Existing checkpoint schemas and core scope values are unchanged. The retained
`automatic_event_time_advance: false` describes the core, which accepts explicit
operations and does not read a clock. `tracking live` is the separate local
driver that automatically supplies those explicit operations. That old value
must not be interpreted as a statement that the end-to-end live command has
no timer.

A checkpoint proves which query cursor and supplied journal were saved under
the consistency checks. It does not authenticate the machine's time or prove
whether a human or the driver supplied an otherwise identical advance.
Execution records are required for claims about how a particular process ran.

## Research and integration limits

The driver observes changes in queries over supplied evidence. Window expiry
does not establish that a real relationship ended. A source-declared future
state becoming eligible is not a generated prediction. Coverage can expire as
the cursor moves, and the existing immediate-adjacent completeness and
analysis-budget gates still determine whether a comparison can run.

External sources remain authoritative. This command provides a local input
pipe and timer, not a network connector, subscription protocol, broker,
service manager or source-authentication mechanism. It does not automatically
label language, trigger a behavior forecast, validate predictive performance
or identify causal effects.

The [invented fixture](../examples/live-tracking/README.md) defines a separate
actual-process case with an idle input, partial line, window expiry, late
correction and SIGKILL/restart. Its social values are authored; its runtime UTC
anchor and actual automatic samples are retained separately.

## Executed live-process case

The [protocol](experiments/2026-11-28-live-tracking/protocol.json), fixture
builder, runner and independent checker were finalized before the actual case.
The runner then sampled one UTC anchor and instantiated the authored source
times around it. Automatic tick counts and final checkpoint counts were not
fixed in advance; the protocol required source, clock and recovery invariants.

The actual run used the default 1,000 ms delay and two CLI subprocesses:

| Saved sequence | K | Observed operation |
| ---: | ---: | --- |
| 0 | 13 | Initial complete state: two cooperation ties and one communication event. |
| 1 | 13 | Idle input; an automatic time update still includes the event. |
| 2 | 13 | Idle input; an automatic time update expires the event from the three-second window. |
| 3–4 | 13 | Two automatic time updates occur while only the first half of a receipt line has been delivered. |
| 5 | 14 | The completed late correction changes a cooperation endpoint at the exact previous cursor. |
| 6 | 14 | Another automatic update; the first process is then stopped with SIGKILL. |
| 7 | 14 | The restarted process automatically advances beyond its recovered cursor. |
| 7 | 14 | An exact duplicate correction returns `NO_NEW_RECORDS`; normal input EOF ends the process. |

There were **six automatic time commits, one receipt commit and one duplicate
receipt**, producing **eight acknowledgments, eight checkpoints and sixteen
snapshots**. Two view comparisons qualified: communication expiry and the
cooperation endpoint correction. The initial communication edge count was one;
the final count was zero. Cooperation remained at two edges while its corrected
endpoint changed. All views remained complete under the invented declarations.

The first receipt line was 616 bytes, delivered in two 308-byte writes. The two
selected partial-input advances have UTC samples after the first write finished
and before the second write started. The second process received the same
616-byte line in one write. The exact bytes, write logs and raw stdout/stderr
are retained privately and bound by the
[execution record](experiments/2026-11-28-live-tracking/execution.json).

Recovery retained sequence 6 / K14 and the exact committed cursor before the
second process continued. This run had **zero unacknowledged published time
versions and zero retained pending files**. The protocol permits an
unacknowledged complete time tail, but this particular run does not demonstrate
that race occurring. Competing access was rejected. Every observed checkpoint
retained its first recorded file hash; all source-input and auxiliary artifact
seals also matched at the end. See the
[aggregate report](experiments/2026-11-28-live-tracking/report.json).

**427 native tests passed, including 22 new tests**, with no failures, errors
or skips and all source/test hashes unchanged. They cover deterministic clock
jumps, rollback and equality, input fairness, exact framing, EOF ordering and
durable time commits after output failure. The
[retained-profile replay](experiments/2026-11-28-live-tracking/retained-profiles-replay.json)
also reconstructed ten prior fixed-view and nine prior manual-temporal
checkpoints with identical saved summaries; all 29 old private JSON files
remained unchanged, without replaying their input streams.

The [independent checker](experiments/2026-11-28-live-tracking/independent_live_tracking_check.py)
was frozen before execution at SHA-256
`309d1d1794fd78447ea65fbe3ec2c444838afad584ec53eca86c2bcb46bc5d59`.
Its [result](experiments/2026-11-28-live-tracking/independent-check.json) reports
**3,940 checks, including 621 exact numeric comparisons**, with maximum
absolute difference zero. It directly reconstructs all sixteen fixture
snapshots from source records using only the standard library, verifies the
two axes, hash chains, receipts, exact input bytes and retained process records,
and confirms **all 35 private files unchanged**. It does not run the tracker,
independently observe the operating-system process or independently implement
the community algorithms. Neither the case nor its checker establishes a
latency SLA, source authenticity, empirical forecast quality or causal effect.

## Python API

```python
from sociolab.live_tracking import consume_live_tracking_stream

processed_input_requests = consume_live_tracking_stream(
    store_path, input_fd, output_stream, interval_ms=1000,
)
```

The return value counts stdin requests, including duplicate or empty batches.
It does not count generated clock controls. The function uses the existing
private store and requires the same POSIX environment as manual tracking.
