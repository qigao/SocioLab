# Dynamic observations and network changes

This release implements **D1–D3** of the [dynamic-network design](https://github.com/qigao/SocioLab/pull/6): a versioned event journal, typed temporal snapshots, general upstream graph analyses, and descriptive change reports. Work is tracked in [Issue #5](https://github.com/qigao/SocioLab/issues/5). This implementation builds on the runtime and numerical work in [PR #4](https://github.com/qigao/SocioLab/pull/4).

External sources remain authoritative. SocioLab reads their structured observations and revisions; it does not operate another social world. All CLI commands write strict JSON to standard output. Files are the initial interface: there is no database, background worker, subscription, or UI.

The additional **D4a** slice accepts versioned human or externally supplied annotations, constructs explicit annotation-count views and reports descriptive agreement; see the [annotation guide](annotations.md). **D4b** automatic-provider qualification remains open. A separate [D5 joint-model adapter](coevolution.md) fits one observed network and one declared ordinal behavior retrospectively. Independent model and population qualification remain open. No classifier, generated dialogue, forecast or causal intervention effect is supplied.

## Run the checked-in example

From the repository root, with Python 3.12–3.13 and the package installed:

```bash
python -m pip install -e .
python -m sociolab events validate examples/dynamic/events.json

python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/cooperation-before.view.json > cooperation-before.snapshot.json
python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/cooperation-after.view.json > cooperation-after.snapshot.json

python -m sociolab changes cooperation-before.snapshot.json cooperation-after.snapshot.json --algorithm greedy --group-size 2 > cooperation-change.json
python -m sociolab communities analyze cooperation-before.snapshot.json --algorithm greedy
python -m sociolab communities compare cooperation-before.snapshot.json cooperation-after.snapshot.json --algorithm greedy
python -m sociolab keyplayers select cooperation-before.snapshot.json --size 2
python -m sociolab keyplayers score cooperation-after.snapshot.json --members C D
```

The [example journal](../examples/dynamic/events.json) is entirely synthetic; its [builder](../examples/dynamic/build_example.py) defines the observations. Two triangles, `ABC` and `DEF`, initially have a cooperation bridge `C–D`. A separate, explicit `relation.changed` record sets that bridge's strength to zero at tick 10. The views select ticks 5 and 15.

| Quantity | Tick 5 | Tick 15 |
| --- | ---: | ---: |
| Eligible people | 6 | 6 |
| Cooperation edges | 7 | 6 |
| Connected components | 1 | 2 |
| Other people structurally reachable from each person | 5 | 2 |
| Greedy communities | ABC / DEF | ABC / DEF |
| Original group C/D, normalized unweighted group betweenness | 2/3 | 0 |

The original group's after-score is available, but selecting a new group on the disconnected after-graph is `NOT_RUN`, with the reason recorded. Unchanged communities do not imply unchanged access. The earlier conflict record and changed actor attribute do not themselves remove the cooperation edge; the explicit relationship update does. The report does not claim that the conflict caused that update.

Saved execution artifacts are [bridge-change.json](experiments/2026-11-27-dynamic-runtime/bridge-change.json), [affiliation-newman.json](experiments/2026-11-27-dynamic-runtime/affiliation-newman.json), [communication.snapshot.json](experiments/2026-11-27-dynamic-runtime/communication.snapshot.json), and the [validation record](experiments/2026-11-27-dynamic-runtime/validation.json).

### Communication, participation, and conflict views

```bash
python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/communication.view.json > communication.snapshot.json
python -m sociolab communities analyze communication.snapshot.json

python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/participation.view.json > participation.snapshot.json
python -m sociolab affiliations analyze participation.snapshot.json
python -m sociolab affiliations analyze participation.snapshot.json --projection count
python -m sociolab affiliations analyze participation.snapshot.json --projection newman --max-pairs 100000

python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/conflict.view.json > conflict.snapshot.json
python -m sociolab communities analyze conflict.snapshot.json
```

The communication window is `[20,30)`. F replies to A at tick 22 and leaves the population at tick 25. F remains eligible for this window with **5 ticks of exposure**, while the other people have 10. The `F→A` event is counted; a later `A→F` record at tick 26 is excluded because F is no longer eligible at that event time. A reply record does not create a separately observed delivery or receipt.

The workshop has six attendance incidences. Count projection produces **15 derived person pairs**, each of strength 1. Newman projection also produces 15 pairs, each of strength `1/(6-1) = 0.2`. Both retain the original incidence report and supporting activity/evidence IDs. These pairs describe shared attendance, not observed friendship, conversation, or trust.

The conflict view contains the source-coded `C→D` conflict action on topic `proposal`. Community detection on conflict counts describes concentrations of those links; it does not identify allied factions or infer hostility from a text. Cooperation and conflict remain separate layers.

## Event journal and raw imports

The implemented contract is defined in [events.py](../src/sociolab/events.py). JSON objects require exactly their declared fields, including fields whose value is `null`. Duplicate object keys, unknown kinds or fields, nonfinite values, invalid references, and ambiguous revision branches are rejected. IDs and other required text fields must be nonempty and trimmed.

### Envelope

An accepted journal has exactly these six fields:

```json
{
  "schema": "sociolab.events.v1",
  "dataset_id": "my-study",
  "origin": "synthetic",
  "source_revision": "study-export-1",
  "clock": {"kind": "ticks", "run_id": "study-run"},
  "records": []
}
```

`origin` is `synthetic`, `external_observation`, or `simulation_export`. The source clock is either `{"kind":"utc"}` or `{"kind":"ticks","run_id":"..."}`. The envelope has no mutable entity catalog or top-level identity map: those are journal records whose availability depends on the receipt cutoff.

`source_revision` is the stable envelope revision for this journal. `ingest_records` preserves it when returning a new journal. Appending observations does not increment it; individual source revisions belong in each record's `source.revision`. Keeping the envelope stable is necessary for historical snapshot hashes to remain stable when later records are appended. A different envelope is a different input, even if it claims the same dataset ID.

### Record fields

| Field | Required meaning |
| --- | --- |
| `record_id` | Globally unique immutable record ID within this journal |
| `fact_id` | Stable identity of an assertion/action across corrections, scoped by `source.system` |
| `operation` | `assert` or `retract` |
| `supersedes` | `null` for a new fact; otherwise the current predecessor's record ID |
| `kind` | One of the typed kinds below |
| `occurred_at` | Event time in the declared source clock |
| `valid_interval` | `null` or `[start,end]`; the end may be `null` for an open interval |
| `source` | Exactly `system`, `record_id`, `revision`, and `evidence_ref`, each nonempty text |
| `payload` | Exactly the fields for that kind; `null` for a retraction |
| `ingest_seq` | Importer-owned receipt sequence, contiguous from 1 |
| `recorded_at` | Importer-owned UTC receipt timestamp, nondecreasing in receipt order |

The accepted journal contains all eleven fields. A **raw import batch** is a JSON array of records containing the first nine fields only: it must omit `ingest_seq` and `recorded_at`. The importer assigns receipts. Supplying receipt fields in a raw batch is an error; passing the complete journal as a raw batch is also an error.

A fact has one revision root. Corrections preserve source system, fact ID and kind, and supersede its current head. A retraction requires a predecessor and `payload: null`. It withdraws the assertion; it is not a later real-world state transition. For example, a relationship ending at a later time is a new `relation.changed` action with its own fact ID. Correcting the earlier relationship record uses that earlier fact's revision chain instead.

Reimporting the same record ID with identical canonical source content is idempotent. Reusing it with different content fails. Receipt order records when information became available; it is not evidence of the causal order of simultaneous actions.

### Supported assertion payloads

These are the exact payload field sets. All referenced entities must already be valid at the relevant receipt prefix.

| Kind | Exact fields and admitted values |
| --- | --- |
| `entity.observed` | `entity_id`, `entity_type` (`person` or `activity`) |
| `identity.mapped` | `alias`, `canonical`; both declared entities of the same type |
| `membership.observed` | `actor`, `population`, `status` (`present` or `absent`); requires a valid interval |
| `membership.changed` | `actor`, `population`, `status` (`present` or `absent`); instantaneous source-state update |
| `actor.attribute.observed` | `actor`, `name`, `value`; value is a finite primitive JSON value or `null` |
| `activity.observed` | `activity`, `status` (`scheduled`, `held`, `cancelled`), `activity_type` |
| `participation.observed` | `actor`, `activity`, `role`, `status` (`attended` or `absent`) |
| `interaction.observed` | `actor`, `target`, `action` (`utterance`, `reply`, `delivery`, `cooperation`, `conflict`), `topic` (text or `null`) |
| `relation.observed` | `layer`, `source`, `target`, `directed` (boolean), `strength` (finite, nonnegative) |
| `relation.changed` | Same relation fields; instantaneous source-state update |
| `coverage.observed` | `population`, `layer`, `actors` (unique person IDs), `status` (`complete`, `partial`, `unobserved`); requires a valid interval |
| `content.observed` | `interaction_record_id`, `content_ref`, `content_revision`, `content_hash`, `language`, `length`; exact schema and source-binding rules in the [annotation guide](annotations.md) |
| `annotation.recorded` | `target_record_id`, `target_content_revision`, `target_content_hash`, `method`, `taxonomy`, `label`, `subject`, `topic`, `evidence`, `score`; registered metadata and labels only |

Entity and identity declarations, interactions, content and annotation records, and `.changed` kinds must have `valid_interval: null`. Attributes, activities, participation and relation observations admit a point or explicit interval. A zero relation strength is an observed absence and remains in selected evidence; only positive strengths create edges.

Entity declarations and identity mappings are resolved separately at every knowledge cutoff. Aliases must be acyclic and type-preserving. Duplicate active entity declarations, unknown references, mapped self-relations, and mappings that invalidate active references fail. Later mappings cannot leak into an earlier as-known view. A declared person still needs explicit membership evidence for the requested population.

`annotation.recorded` now accepts the strict D4a schema described in the [annotation guide](annotations.md). Message-body fields, arbitrary annotation objects, unregistered taxonomies and extra text fields remain unsupported. An attribute is not automatically interpreted as an annotation or relationship change. `interaction.observed` with `action: "conflict"` still records a source-coded action; the separate `annotated_conflict` layer counts selected labels without classifying or fetching source text.

### Create and import a journal

This complete shell example imports a single entity declaration. Membership and coverage must be added before it can support a fully observed network analysis.

```bash
python -m sociolab events init --dataset-id my-study --origin synthetic --source-revision study-export-1 --clock ticks --run-id study-run > empty.events.json

cat > person.batch.json <<'JSON'
[
  {
    "record_id": "person-A",
    "fact_id": "person-A",
    "operation": "assert",
    "supersedes": null,
    "kind": "entity.observed",
    "occurred_at": 0,
    "valid_interval": null,
    "source": {
      "system": "my-source",
      "record_id": "person-A",
      "revision": "1",
      "evidence_ref": "synthetic:person-A"
    },
    "payload": {"entity_id": "A", "entity_type": "person"}
  }
]
JSON

python -m sociolab events import empty.events.json person.batch.json --received-at 2026-11-27T12:00:00Z > imported.events.json
python -m sociolab events validate imported.events.json
```

`--received-at` gives reproducible receipts; omitting it uses current UTC time. Use a different output filename from the input journal: shell redirection to an input filename would truncate it before the command starts. No CLI command modifies the source application or appends to an input file in place.

## Time, membership, and observation coverage

UTC event timestamps require an explicit `Z` or `+00:00` suffix, with at most six fractional digits. Calculations use exact integer microseconds. Tick times are nonnegative integers tied to the declared run. Receipt timestamps are always UTC, including for tick-based datasets; receipt sequence, not source time, controls the knowledge cutoff.

Time intervals and query windows are half-open: `[start,end)`. A point observation applies only at its exact instant. An interval observation applies within its declared interval. Only `membership.changed` and `relation.changed` carry a source-declared state forward until a subsequent change. Independent simultaneous or overlapping assertions that disagree raise an error; receipt order cannot choose a winner. Revising one fact's head is a separate, explicit operation.

State views use `eligible_at(t)`. Event and participation windows use `eligible_any_overlap([start,end))`, then admit each observation only during the relevant person's eligible time. Window exposure is reported per person in ticks or UTC microseconds. State exposure is a point indicator. An unknown membership interval remains unknown even if the person is known present during another part of the window; the materializer does not intersect rosters to manufacture complete data.

Coverage is declared per population, relation layer, actors and interval. Complete communication collection does not establish complete trust or friendship observations. Missing coverage remains `unobserved`; partial coverage is preserved. A snapshot can be inspected with incomplete coverage, but the analytical CLI commands and `compare_snapshots` reject it. Unknown membership among cutoff-known people also prevents complete coverage. A known-empty population still requires an applicable coverage declaration.

Conflicting coverage declarations fail. An explicit `unobserved` declaration overlapping an effective observation in that view also fails, rather than concealing the contradiction. A missing coverage declaration with known observations produces an incomplete snapshot that can be inspected; it is not silently promoted to complete. Complete serialized snapshots must contain selected, effective `coverage.observed` evidence.

### Activity and attendance consistency

An activity occurrence needs its own entity and an effective `activity.observed` description. A point-only activity admits attended participation at **that exact instant**. To represent duration, give the activity an explicit interval; an attendance interval does not infer the activity's duration. The participation view retains binary person–activity incidences, including supporting attendance and activity-description record IDs. Multiple selected roles do not multiply a binary incidence.

An effective attended record conflicting with a scheduled or cancelled activity raises an error. If the workshop example is corrected to cancelled, the source update must also retract or correct **all six** still-effective attendance assertions. A valid correction batch would supersede `workshop-description` with its cancelled description and separately retract each `attendance-A` through `attendance-F` fact, using its current record as `supersedes` and a null payload. After that batch is imported, later as-known views use the correction; earlier receipt cutoffs retain the held workshop and attendance.

Overlapping `attended` and `absent` assertions for the same actor, activity and role also fail. They require source correction or retraction. Cancellation never silently erases contradictory attendance evidence. Shared activity attendance within a window does not prove simultaneous presence; the current projection is affiliation, not a qualified co-presence or delivery model.

## View specifications and snapshot hashes

The checked-in [before view](../examples/dynamic/cooperation-before.view.json) illustrates the state form:

```json
{
  "schema": "sociolab.view.v1",
  "population": "team",
  "layer": "cooperation",
  "mode": "state",
  "directed": false,
  "actions": [],
  "roles": [],
  "topics": [],
  "at": 5
}
```

| Mode | Time fields | Additional requirements | Weight meaning |
| --- | --- | --- | --- |
| `state` | `at` | Explicit layer/direction; action, role and topic filters empty | Observed relation strength |
| `events` | `start`, `end` | Directed; explicit nonempty actions valid for the selected layer; roles empty | Eligible event count |
| `participation` | `start`, `end` | Undirected `participation` layer; roles may filter; actions/topics empty | Binary participation |
| `annotations` | `start`, `end` | Directed communication sources; explicit method, taxonomy, labels and utterance/reply actions; see [annotation views](annotations.md#annotation-count-network-views) | Derived annotation count |

The three original filter arrays default to empty if omitted. Event layers admit exactly: `communication` with `utterance`/`reply`, `delivery` with `delivery`, `cooperation_actions` with `cooperation`, and `conflict` with `conflict`. A nonempty topic filter selects matching topics. State views do not infer their edges from these interactions. Annotation views add `source_layer`, `method`, `taxonomy` and `labels`; they require one usable decision for every eligible source interaction before label/topic filtering and preserve unresolved items and their measurement status.

`snapshot` defaults to all available receipts. For an earlier as-known view:

```bash
python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/cooperation-after.view.json --knowledge-cutoff 24 > earlier-knowledge.snapshot.json
```

In the checked-in example, receipt 24 is the last initial cooperation assertion. This query still asks about tick 15, but it cannot use the later-received relationship ending, so it retains the bridge. The cutoff is a receipt count, not tick 24 or a wall-clock timestamp.

The result is `sociolab.snapshot.v1`, containing dataset provenance, normalized view, knowledge cutoff, person/activity partitions, edges with evidence IDs, coverage, population/exposure, receipt history, weight semantics and hashes. The reader validates serialized hashes and evidence references before analysis.

The hashes have distinct scopes:

- `EventDataset.content_hash` identifies the complete accepted journal currently loaded.
- Snapshot `dataset.content_hash` identifies the envelope with **only the selected receipt prefix**. The full later journal hash is intentionally absent. Appending later records therefore does not change an earlier snapshot at the same cutoff and view.
- Snapshot `dataset.known_records_hash` identifies that receipt-prefix record array, including corrections and retractions.
- `policy_hash` identifies the normalized view policy and clock, excluding `at`/`start`/`end`. Changing the layer, direction, population, filters, or an annotation method/taxonomy prevents comparison under the old policy.
- Snapshot `content_hash` identifies the complete normalized snapshot, including its query and provenance.

These are reproducibility and integrity checks, **not source authentication**. A valid journal or matching hash does not establish that the supplied observations happened in the real world. See [snapshots.py](../src/sociolab/snapshots.py) for the materialization and serialized contract.

## Analysis and change-report scope

Community analysis uses actual NetworkX Louvain by default, or greedy modularity with `--algorithm greedy`. It records algorithm, version, seed, resolution, weight and canonical node/edge order. Isolates remain in the graph. Empty/no-edge graphs have explicit statuses and `modularity: null` where undefined. Conflict counts are positive link strengths, not a signed-network model.

Community comparison uses common observable people, retains every nonzero overlap for splits and merges, and calls upstream maximum-weight matching only for display-ID continuity. Tied matching candidates are reported; display names do not constitute social identities. Population entry/exit is separate from movement among common people. No common observable population means no comparable stability score.

Group selection uses upstream greedy `prominent_group` and independently re-scores its returned members with upstream group betweenness. Its initial scope is a connected, simple, undirected, unit-strength graph, with `1 <= k <= min(4,n-2)`. Defaults bound selection to 200 nodes and 2,000 edges. The result is a heuristic, not a proven global optimum. Nonempty exclusion sets are unsupported after an observed inconsistency in the pinned upstream exclusion path; the Python `excluded` argument must remain empty.

Directed group selection is unsupported. **Scoring an explicitly supplied group is supported on directed or disconnected simple unit-strength graphs**, provided at least two nodes remain outside the group. An absent original member makes that group's after-score unavailable; SocioLab does not quietly score its surviving subset. Nonunit `strength`, `weight` or `distance` attributes are rejected by these unweighted group APIs. There is no implicit conversion of interaction frequency or community strength into shortest-path distance.

Affiliation projection is explicit and bounded by `max_pairs` (default 100,000), using an upper bound before allocation. `count` calls upstream weighted projection; `newman` calls upstream collaboration-weighted projection. The original bipartite graph and evidence remain in the report. With no projection, `changes` reports participation changes and marks person-community, group and structural analyses `NOT_RUN`. With a projection, it labels the analyzed person graph as derived co-participation. Nonunit projected weights remain outside current group-analysis scope.

`changes` requires equal dataset ID, origin, clock and policy hashes, plus complete coverage on both sides. It records input windows, cutoffs and source revisions and returns `DESCRIPTIVE_NETWORK_CHANGE` with:

- New, corrected and retracted receipt records, plus selected-evidence changes. Records present only in the earlier receipt prefix are an availability difference, not automatically a retraction.
- Population eligibility changes, explicit unknowns and exposure; newly observed people are not automatically classified as having joined.
- Added, removed and reweighted edges, with evidence-only changes separately preserved.
- Undirected components, isolates, bridges and reachable-person counts, or directed weak/strong components and outgoing descendants.
- Community results and lineage, original-group before/after scores, and a new selection or explicit scope reason.
- Participation and requested projection changes when the snapshots are bipartite.

Structural reachability is potential connectivity, not observed transmission or a time-respecting event path. A recorded conflict, later relationship change and changed graph metric are not an identified causal chain. Window expiry, revisions, membership changes and changed observation coverage must be interpreted alongside the graph.

## Python API

The public functions accept existing validated data or actual NetworkX graphs. Graph-only APIs cannot check a journal's observation coverage; call `snapshot.require_complete()` before handing them a materialized graph.

```python
from sociolab.events import EventDataset, ingest_records, load_event_dataset
from sociolab.snapshots import (
    NetworkSnapshot, load_snapshot, load_view, materialize_snapshot,
)
from sociolab.communities import community_report, compare_communities
from sociolab.keyplayers import select_key_group, score_key_group
from sociolab.affiliations import affiliation_report
from sociolab.changes import compare_snapshots

dataset = load_event_dataset("examples/dynamic/events.json")
before = materialize_snapshot(
    dataset,
    load_view("examples/dynamic/cooperation-before.view.json", dataset.clock),
)
after = materialize_snapshot(
    dataset,
    load_view("examples/dynamic/cooperation-after.view.json", dataset.clock),
)
report = compare_snapshots(before, after, algorithm="greedy", group_size=2)

before.require_complete()
after.require_complete()
partition = community_report(before.to_graph(), algorithm="greedy", seed=0, resolution=1.0)
selection = select_key_group(before.to_graph(), 2, max_nodes=200, max_edges=2000)
after_score = score_key_group(after.to_graph(), selection["members"])
```

Useful signatures and contracts:

| Entry point | Contract |
| --- | --- |
| `EventDataset.from_mapping(data)` | Validates a complete receipt-bearing journal and its prefixes |
| `ingest_records(dataset, raw_records, *, received_at=None)` | Returns a validated new journal; identical reimport is idempotent |
| `dataset.as_known(knowledge_cutoff=None)` | Effective unretracted assertions within that receipt prefix |
| `dataset.entities_at(...)`, `dataset.identity_map_at(...)` | Cutoff-scoped entity/type and resolved-alias mappings |
| `materialize_snapshot(dataset, view_spec, knowledge_cutoff=None)` | Creates an inspectable typed snapshot, including explicit incompleteness |
| `load_snapshot(path)`, `NetworkSnapshot.from_mapping(data)` | Validate serialized snapshot fields, hashes and evidence |
| `snapshot.to_dict()`, `snapshot.to_graph()` | Fresh defensive values; editing them does not mutate the snapshot |
| `community_report(graph, *, algorithm="louvain", seed=0, resolution=1.0, weight="strength")` | Actual upstream partition and modularity |
| `compare_communities(before_partition, after_partition, *, observable=None)` | Label-independent full lineage; `observable` is an explicit common-node subset |
| `select_key_group(graph, group_size=2, *, excluded=(), max_nodes=200, max_edges=2000)` | Qualified upstream greedy selection with empty exclusions |
| `score_key_group(graph, members)` | Actual upstream score for the full supplied group |
| `affiliation_report(graph, persons, *, projection="none", max_pairs=100000)` | Binary bipartite input and optional count/Newman projection |
| `compare_snapshots(before, after, *, algorithm="louvain", seed=0, resolution=1.0, group_size=None, group_members=None, projection="none", max_nodes=200, max_edges=2000, max_pairs=100000)` | Complete, policy-compatible descriptive comparison |

Supplying `group_members` to `compare_snapshots` fixes the original group and implies its size. If `group_size` is also given it must match. Without either, group analysis is not requested. Selection budgets do not truncate the population analyzed by communities or structure. Incompatible inputs fail; unexpected upstream failures propagate.

## Existing references and remaining work

`karate`, `davis`, `communities` with no subcommand, `keyplayers --size 2`, `structure`, `threshold`, `panel`, `s50`, and `saom` retain their existing behavior. The old `sociolab.network.v1` and `sociolab.longitudinal.v1` contracts remain separate from events and snapshots. Do not insert undeclared dynamic fields into those schemas.

Run the native suite with `python -m unittest discover -s tests -v`. The separately invoked genuine SAOM runtime suite remains `python -m unittest discover -s tests/saom_runtime -v` and requires the optional `.[saom]` installation.

The existing `saom` command remains a network-only, three-effect conditional model with the numerical gate described in [saom-numerical-validation.md](saom-numerical-validation.md). The separate `coevolution` command implements the [fixed unconditional network/ordinal-behavior profile](coevolution.md), with explicit scale, full parameter-layout diagnostics and CPU path checks. Journal attributes and conflict counts are not automatically converted into its behavior measurements. Structured annotation ingestion and descriptive comparison are implemented as D4a; automatic text inference and provider qualification remain open as D4b. Independent empirical qualification, signed-network models, event-history estimation, future prediction and causal identification also require additional work.

Implementation sources: [events.py](../src/sociolab/events.py), [snapshots.py](../src/sociolab/snapshots.py), [communities.py](../src/sociolab/communities.py), [keyplayers.py](../src/sociolab/keyplayers.py), [affiliations.py](../src/sociolab/affiliations.py), [changes.py](../src/sociolab/changes.py), and [cli.py](../src/sociolab/cli.py). NetworkX 3.7 supplies the graph algorithms; [its projection documentation](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.bipartite.projection.collaboration_weighted_projected_graph.html) explains the Newman weighting, and [its group-centrality documentation](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.group.prominent_group.html) describes the original selection routine.
