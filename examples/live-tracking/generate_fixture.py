"""Build invented live-tracking inputs from one explicitly supplied UTC anchor.

This module never samples a clock or writes a file. The caller freezes this
source and its protocol, samples the runtime anchor, then retains the returned
inputs privately. Validation uses only the existing importer and materializer;
no tracking process, graph analysis, forecast or simulation is executed here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from sociolab.events import EventDataset, ingest_records, parse_time
from sociolab.snapshots import content_hash, materialize_snapshot


ACTORS = ("A", "B", "C", "D")
POPULATION = "invented-team"
SYSTEM = "invented-live-tracking"
SOURCE_REVISION = "invented-live-tracking-source-v1"
WINDOW_WIDTH_MICROSECONDS = 3_000_000
SECOND = 1_000_000
DAY = 86_400 * SECOND
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _utc(value: int) -> str:
    try:
        instant = EPOCH + timedelta(microseconds=value)
    except OverflowError as error:
        raise ValueError("anchor does not admit the fixture's required UTC offsets") from error
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _record(record_id, kind, payload, *, at, interval=None,
            fact_id=None, supersedes=None, revision="initial"):
    return {
        "record_id": record_id,
        "fact_id": record_id if fact_id is None else fact_id,
        "operation": "assert", "supersedes": supersedes, "kind": kind,
        "occurred_at": at, "valid_interval": interval,
        "source": {"system": SYSTEM, "record_id": record_id, "revision": revision,
                   "evidence_ref": "synthetic:" + record_id},
        "payload": payload,
    }


def _relation(record_id, source, target, *, at, **revision):
    return _record(record_id, "relation.changed", {
        "layer": "cooperation", "source": source, "target": target,
        "directed": False, "strength": 1,
    }, at=at, **revision)


def _canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _snapshots(dataset, registration, cursor, *, cutoff=None):
    instant = parse_time(cursor, dataset.clock)
    result = {}
    for entry in registration["views"]:
        view = dict(entry["view"])
        if view["mode"] == "state":
            view["at"] = cursor
        else:
            view.update(start=_utc(instant - entry["window_width"]), end=cursor)
        result[entry["view_id"]] = materialize_snapshot(dataset, view, cutoff).to_dict()
    return result


def _require(condition, message):
    if not condition:
        raise AssertionError("invented live fixture: " + message)


def _require_graph(snapshot, edges):
    _require(snapshot["persons"] == list(ACTORS), "all four people must remain eligible")
    _require(snapshot["activities"] == [], "the fixture has no activities")
    _require(snapshot["coverage"]["complete"], "declared coverage must be complete")
    _require({(edge["source"], edge["target"], edge["strength"])
              for edge in snapshot["edges"]} == edges, "materialized edges differ from the authored source")


def build_fixture(anchor_utc: str) -> dict:
    """Return dataset, registration, late_batch and metadata for one UTC anchor.

    The supplied anchor is the only varying input. Accepted UTC spellings are
    normalized to six fractional digits and Z. The returned dataset already
    contains 13 imported source records; initialize it directly, without sending
    those records again. The single-record late_batch changes K13 to K14, and
    replaying that exact batch is an idempotent duplicate.

    The explicit source receipt times (anchor and anchor + one second) are
    authored provenance values. They are not measurements of when a later CLI
    process receives input. That process must retain its own execution evidence.
    """
    anchor_value = parse_time(anchor_utc, {"kind": "utc"})
    anchor = _utc(anchor_value)
    source_start_value = anchor_value - DAY
    source_start = _utc(source_start_value)
    event_value = anchor_value - SECOND
    event_time = _utc(event_value)
    expiry_boundary_value = event_value + WINDOW_WIDTH_MICROSECONDS
    expiry_boundary = _utc(expiry_boundary_value)
    after_expiry = _utc(expiry_boundary_value + 1)
    late_received_at = _utc(anchor_value + SECOND)

    empty = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "synthetic-live-tracking-example",
        "origin": "synthetic", "source_revision": SOURCE_REVISION,
        "clock": {"kind": "utc"}, "records": [],
    })
    records = [_record("declare-" + actor, "entity.observed", {
        "entity_id": actor, "entity_type": "person",
    }, at=source_start) for actor in ACTORS]
    records.extend(_record("membership-" + actor, "membership.changed", {
        "actor": actor, "population": POPULATION, "status": "present",
    }, at=source_start) for actor in ACTORS)
    records.extend(_record("coverage-" + layer, "coverage.observed", {
        "population": POPULATION, "layer": layer,
        "actors": list(ACTORS), "status": "complete",
    }, at=source_start, interval=[source_start, None])
        for layer in ("cooperation", "communication"))
    records.extend([
        _relation("cooperation-A-B", "A", "B", at=source_start),
        _relation("cooperation-C-D", "C", "D", at=source_start),
        _record("reply-A-C", "interaction.observed", {
            "actor": "A", "target": "C", "action": "reply", "topic": "task",
        }, at=event_time),
    ])
    dataset = ingest_records(empty, records, received_at=anchor)

    state_view = {
        "schema": "sociolab.view.v1", "population": POPULATION,
        "layer": "cooperation", "mode": "state", "directed": False,
        "actions": [], "roles": [], "topics": [],
    }
    registration = {
        "schema": "sociolab.temporal-tracking-spec.v1",
        "initial_cursor": anchor, "source_time_unit": "microsecond",
        "views": [
            {"view_id": "cooperation", "view": state_view,
             "window_width": None, "analysis": {}},
            {"view_id": "communication", "view": {
                **state_view, "layer": "communication", "mode": "events", "directed": True,
                "actions": ["reply", "utterance"],
            }, "window_width": WINDOW_WIDTH_MICROSECONDS, "analysis": {}},
        ],
    }
    late_batch = {
        "schema": "sociolab.network-tracking-batch.v1",
        "received_at": late_received_at,
        "records": [_relation(
            "cooperation-A-D-correction", "A", "D", at=source_start,
            fact_id="cooperation-A-B", supersedes="cooperation-A-B", revision="late-correction",
        )],
    }

    # Source-only validation. These snapshots are never tracking checkpoints.
    _require(len(dataset.records) == 13, "initial journal must contain exactly 13 records")
    initial = _snapshots(dataset, registration, anchor)
    base_edges = {("A", "B", 1), ("C", "D", 1)}
    corrected_edges = {("A", "D", 1), ("C", "D", 1)}
    _require_graph(initial["cooperation"], base_edges)
    _require_graph(initial["communication"], {("A", "C", 1)})

    at_boundary = _snapshots(dataset, registration, expiry_boundary)
    expired = _snapshots(dataset, registration, after_expiry)
    _require_graph(at_boundary["communication"], {("A", "C", 1)})
    _require_graph(expired["communication"], set())
    _require_graph(expired["cooperation"], base_edges)
    _require(initial["communication"]["dataset"] == expired["communication"]["dataset"],
             "changing the query must preserve its receipt-prefix evidence")

    corrected = ingest_records(dataset, late_batch["records"], received_at=late_received_at)
    _require(len(corrected.records) == 14, "one correction must advance K13 to K14")
    _require(corrected.source_revision == dataset.source_revision == SOURCE_REVISION,
             "the source envelope revision must remain fixed")
    at_same_cursor = _snapshots(corrected, registration, anchor)
    after_expiry_and_late = _snapshots(corrected, registration, after_expiry)
    _require_graph(at_same_cursor["cooperation"], corrected_edges)
    _require_graph(at_same_cursor["communication"], {("A", "C", 1)})
    _require_graph(after_expiry_and_late["cooperation"], corrected_edges)
    _require_graph(after_expiry_and_late["communication"], set())
    repeated = ingest_records(corrected, late_batch["records"], received_at=late_received_at)
    _require(repeated is corrected, "the exact correction retry must be idempotent")
    replayed_initial = _snapshots(corrected, registration, anchor, cutoff=13)
    _require(_canonical_bytes(replayed_initial) == _canonical_bytes(initial),
             "later source correction must preserve earlier cutoff snapshots")

    dataset_mapping = dataset.to_dict()
    metadata = {
        "schema": "sociolab.live-tracking-fixture.v1", "origin": "synthetic",
        "anchor_utc": anchor, "anchor_value": anchor_value,
        "source_start_utc": source_start, "source_start_value": source_start_value,
        "event_time": event_time, "event_value": event_value,
        "expiry_boundary_utc": expiry_boundary, "expiry_boundary_value": expiry_boundary_value,
        "expiry_condition": "cursor_value > expiry_boundary_value",
        "initial_received_at": anchor, "late_received_at": late_received_at,
        "initial_cursor": anchor, "source_time_unit": "microsecond",
        "window_width_microseconds": WINDOW_WIDTH_MICROSECONDS,
        "window_boundary": "start_inclusive_end_exclusive",
        "invented_person_count": 4, "registered_view_count": 2,
        "initial_knowledge_cutoff": 13, "after_late_knowledge_cutoff": 14,
        "late_batch_record_count": 1,
        "initial_view_expectations": {
            name: {"person_count": len(snapshot["persons"]), "edge_count": len(snapshot["edges"]),
                   "complete": snapshot["coverage"]["complete"]}
            for name, snapshot in initial.items()
        },
        "after_expiry_and_late_view_expectations": {
            name: {"person_count": len(snapshot["persons"]), "edge_count": len(snapshot["edges"]),
                   "complete": snapshot["coverage"]["complete"]}
            for name, snapshot in after_expiry_and_late.items()
        },
        "initial_snapshot_hashes": {name: snapshot["content_hash"] for name, snapshot in initial.items()},
        "input_content_hashes": {"dataset": content_hash(dataset_mapping),
                                 "registration": content_hash(registration), "late_batch": content_hash(late_batch)},
        "verification": {
            "existing_ingest_records_used": True, "existing_materialize_snapshot_used": True,
            "initial_and_corrected_source_graphs_checked": True,
            "event_retained_at_inclusive_lower_boundary_checked": True,
            "event_excluded_one_microsecond_after_lower_boundary_checked": True,
            "exact_duplicate_correction_is_idempotent": True,
            "old_cutoff_snapshot_bytes_preserved": True,
            "tracking_runtime_executed": False, "wall_clock_sampled": False,
            "subprocess_recovery_verified": False,
        },
        "scope": {
            "engineering_fixture_only": True, "real_data_used": False,
            "all_source_values_authored": True, "source_receipt_times_authored": True,
            "anchor_is_only_varying_input": True, "automatic_tick_count_predeclared": False,
            "live_checkpoint_count_predeclared": False,
            "actual_timer_samples_and_process_evidence_retained_separately": True,
            "source_authenticity_verified": False, "real_time_latency_guarantee": False,
            "causal_effect_identified": False, "empirical_prediction_validated": False,
        },
    }
    return {"dataset": dataset_mapping, "registration": registration,
            "late_batch": late_batch, "metadata": metadata}
