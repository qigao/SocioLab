#!/usr/bin/env python3
"""Write invented receipts and explicit source-time advances.

The oracle uses the existing importer, materializer and qualified snapshot
comparison. It never imports or executes either tracking implementation.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys


DIRECTORY = Path(__file__).resolve().parent
REPOSITORY = DIRECTORY.parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from sociolab.changes import compare_snapshots
from sociolab.events import EventDataset, ingest_records
from sociolab.snapshots import materialize_snapshot


ACTORS = ("A", "B", "C", "D")
POPULATION = "invented-team"
SYSTEM = "invented-time-tracking"
SOURCE_REVISION = "invented-time-tracking-source-v1"
VIEW_IDS = ("cooperation", "communication", "trust")
BATCH_SCHEMA = "sociolab.network-tracking-batch.v1"
ADVANCE_SCHEMA = "sociolab.network-tracking-advance.v1"
INITIAL_CURSOR = 10
RESTART_AFTER_DELIVERY = 5


def _record(record_id, kind, payload, *, at=0, interval=None,
            fact_id=None, supersedes=None, revision="initial"):
    return {
        "record_id": record_id, "fact_id": record_id if fact_id is None else fact_id,
        "operation": "assert", "supersedes": supersedes, "kind": kind,
        "occurred_at": at, "valid_interval": interval,
        "source": {"system": SYSTEM, "record_id": record_id, "revision": revision,
                   "evidence_ref": "synthetic:" + record_id},
        "payload": payload,
    }


def _relation(record_id, source, target, *, at, layer="cooperation"):
    return _record(record_id, "relation.changed", {
        "layer": layer, "source": source, "target": target,
        "directed": False, "strength": 1,
    }, at=at)


def _coverage(record_id, layer, interval, *, revision="initial"):
    return _record(record_id, "coverage.observed", {
        "population": POPULATION, "layer": layer,
        "actors": list(ACTORS), "status": "complete",
    }, at=interval[0], interval=interval, revision=revision)


def _interaction(record_id, actor, target, *, at, **revision):
    return _record(record_id, "interaction.observed", {
        "actor": actor, "target": target, "action": "reply", "topic": "task",
    }, at=at, **revision)


def _registration():
    state = {
        "schema": "sociolab.view.v1", "population": POPULATION,
        "layer": "cooperation", "mode": "state", "directed": False,
        "actions": [], "roles": [], "topics": [],
    }
    return {
        "schema": "sociolab.temporal-tracking-spec.v1",
        "initial_cursor": INITIAL_CURSOR, "source_time_unit": "tick",
        "views": [
            {"view_id": VIEW_IDS[0], "view": state, "window_width": None, "analysis": {}},
            {"view_id": VIEW_IDS[1], "view": {
                **state, "layer": "communication", "mode": "events", "directed": True,
                "actions": ["reply", "utterance"],
            }, "window_width": 10, "analysis": {}},
            {"view_id": VIEW_IDS[2], "view": {**state, "layer": "trust"},
             "window_width": None, "analysis": {}},
        ],
    }


def fixture_inputs():
    empty = {
        "schema": "sociolab.events.v1", "dataset_id": "synthetic-time-tracking-example",
        "origin": "synthetic", "source_revision": SOURCE_REVISION,
        "clock": {"kind": "ticks", "run_id": "time-tracking-example"}, "records": [],
    }
    initial = [_record("declare-" + actor, "entity.observed", {
        "entity_id": actor, "entity_type": "person",
    }) for actor in ACTORS]
    initial.extend(_record("membership-" + actor, "membership.changed", {
        "actor": actor, "population": POPULATION, "status": "present",
    }) for actor in ACTORS)
    initial.extend([
        _coverage("coverage-cooperation-initial", "cooperation", [0, 20]),
        _coverage("coverage-communication-initial", "communication", [0, 20]),
        _coverage("coverage-trust", "trust", [0, 40]),
        _relation("cooperation-A-B", "A", "B", at=0),
        _relation("cooperation-C-D", "C", "D", at=0),
        _relation("cooperation-future-B-C", "B", "C", at=15),
        _relation("trust-A-D", "A", "D", at=0, layer="trust"),
        _interaction("reply-A-B-at-5", "A", "B", at=5),
        _interaction("reply-C-D-at-10", "C", "D", at=10, fact_id="reply-at-10"),
        _interaction("reply-B-C-at-15", "B", "C", at=15),
        _interaction("reply-D-A-at-20", "D", "A", at=20),
    ])
    correction = [_interaction("reply-C-A-at-10", "C", "A", at=10,
        fact_id="reply-at-10", supersedes="reply-C-D-at-10", revision="late-correction")]
    recovery = [
        _coverage("coverage-cooperation-continuation", "cooperation", [20, 40], revision="recovery"),
        _coverage("coverage-communication-continuation", "communication", [20, 40], revision="recovery"),
    ]

    def batch(records, minute):
        return {"schema": BATCH_SCHEMA, "records": records,
                "received_at": f"2026-11-28T01:{minute:02d}:00Z"}

    def advance(cursor):
        return {"schema": ADVANCE_SCHEMA, "cursor": cursor}

    stages = [
        ("initial", batch(initial, 1)),
        ("advance_to_15", advance(15)),
        ("equal_advance_15", advance(15)),
        ("late_correction_at_15", batch(correction, 4)),
        ("advance_to_20", advance(20)),
        ("equal_advance_20_after_restart", advance(20)),
        ("advance_to_21", advance(21)),
        ("coverage_recovered_at_21", batch(recovery, 8)),
        ("duplicate_recovery_at_21", batch(deepcopy(recovery), 9)),
        ("advance_to_25", advance(25)),
        ("advance_to_26", advance(26)),
    ]
    negative = {
        "rejected-backwards.jsonl": {"schema": ADVANCE_SCHEMA, "cursor": 25},
        "rejected-cursor-type.jsonl": {"schema": ADVANCE_SCHEMA, "cursor": "27"},
        "rejected-mixed-command.jsonl": {"schema": ADVANCE_SCHEMA, "cursor": 27, "records": []},
    }
    return empty, _registration(), [name for name, _ in stages], [value for _, value in stages], negative


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _jsonl_bytes(values):
    return ("".join(json.dumps(value, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False) + "\n" for value in values)).encode("utf-8")


def _resolved_views(registration, cursor):
    result = {}
    for entry in registration["views"]:
        view = deepcopy(entry["view"])
        if view["mode"] == "state":
            view["at"] = cursor
        else:
            view.update(start=cursor - entry["window_width"], end=cursor)
        result[entry["view_id"]] = view
    return result


def _graph(data):
    return (data["persons"], data["activities"], data["directed"], data["bipartite"],
            {(edge["source"], edge["target"]): edge["strength"] for edge in data["edges"]})


def _evidence(data):
    return (data["provenance"]["selected_records"], data["coverage"]["evidence"],
            [(edge["source"], edge["target"], edge["evidence"]) for edge in data["edges"]],
            data.get("annotation_summary"))


def validate_fixture(empty, registration, stage_names, deliveries):
    dataset = EventDataset.from_mapping(empty)
    cursor, sequence = INITIAL_CURSOR, 0
    initial_views = _resolved_views(registration, cursor)
    previous = {name: materialize_snapshot(dataset, view, 0) for name, view in initial_views.items()}
    checkpoints = [(0, 0, cursor, previous)]
    base = {("A", "B"), ("C", "D")}
    cooperation = base | {("B", "C")}
    trust = {("A", "D")}
    communications = (
        {("A", "B")},
        {("A", "B"), ("C", "D")},
        {("A", "B"), ("C", "D")},
        {("A", "B"), ("C", "A")},
        {("C", "A"), ("B", "C")},
        {("C", "A"), ("B", "C")},
        {("B", "C"), ("D", "A")},
        {("B", "C"), ("D", "A")},
        {("B", "C"), ("D", "A")},
        {("B", "C"), ("D", "A")},
        {("D", "A")},
    )
    expected_cutoffs = [19, 19, 19, 20, 20, 20, 20, 22, 22, 22, 22]
    expected_sequences = [1, 2, 2, 3, 4, 4, 5, 6, 6, 7, 8]
    expected_cursors = [10, 15, 15, 15, 20, 20, 21, 21, 21, 25, 26]
    stages = {}
    for index, (name, delivery) in enumerate(zip(stage_names, deliveries), 1):
        before_dataset, before_cursor, before_sequence = dataset, cursor, sequence
        before_cutoff = len(dataset.records)
        is_receipt = delivery["schema"] == BATCH_SCHEMA
        if is_receipt:
            dataset = ingest_records(dataset, delivery["records"], received_at=delivery["received_at"])
        else:
            assert type(delivery["cursor"]) is int and delivery["cursor"] >= cursor
            cursor = delivery["cursor"]
        added = len(dataset.records) - before_cutoff
        time_advanced = cursor != before_cursor
        committed = bool(added or time_advanced)
        if committed:
            sequence += 1
        else:
            assert dataset is before_dataset
        cutoff = len(dataset.records)
        assert (cutoff, sequence, cursor) == (
            expected_cutoffs[index - 1], expected_sequences[index - 1], expected_cursors[index - 1])
        assert dataset.source_revision == SOURCE_REVISION
        resolved = _resolved_views(registration, cursor)
        current = {view_id: materialize_snapshot(dataset, view, cutoff) for view_id, view in resolved.items()}
        view_results = {}
        for view_id in VIEW_IDS:
            old, new = previous[view_id], current[view_id]
            old_data, data = old.to_dict(), new.to_dict()
            wanted_edges = (base if index == 1 else cooperation) if view_id == "cooperation" else (
                communications[index - 1] if view_id == "communication" else trust)
            assert {(edge["source"], edge["target"]) for edge in data["edges"]} == wanted_edges
            assert all(edge["strength"] == 1 for edge in data["edges"])
            assert tuple(data["persons"]) == ACTORS
            expected_complete = not (
                (view_id == "cooperation" and index in (5, 6, 7))
                or (view_id == "communication" and index == 7))
            assert new.coverage_complete == expected_complete
            expected_coverage = "complete" if expected_complete else (
                "unobserved" if view_id == "cooperation" else "partial")
            assert set(data["coverage"]["actors"].values()) == {expected_coverage}
            graph_changed = _graph(old_data) != _graph(data)
            population_changed = old_data["population"] != data["population"]
            coverage_changed = any(old_data["coverage"][key] != data["coverage"][key]
                                   for key in ("complete", "actors"))
            evidence_changed = _evidence(old_data) != _evidence(data)
            qualified = bool(committed and old.coverage_complete and new.coverage_complete)
            change_counts = None
            if qualified:
                comparison = compare_snapshots(old, new, algorithm="greedy", seed=0, resolution=1.0)
                relations = comparison["relations"]
                change_counts = {key: len(relations[key]) for key in ("added", "removed", "reweighted", "evidence_changed")}
            if not committed:
                assert _json_bytes(old_data) == _json_bytes(data)
                tracking_status, tracking_reason = None, None
            elif not (graph_changed or population_changed or coverage_changed):
                tracking_status, tracking_reason = "NOT_RUN", "no_observable_change"
            elif not old.coverage_complete or not new.coverage_complete:
                tracking_status, tracking_reason = "NOT_RUN", "incomplete_before_or_after_coverage"
            else:
                tracking_status, tracking_reason = "OK", None
            if committed:
                assert old.content_hash != new.content_hash
            view_results[view_id] = {
                "person_count": 4, "activity_count": 0, "edge_count": len(data["edges"]),
                "complete": new.coverage_complete, "coverage_status_counts": {expected_coverage: 4},
                "observed_graph_changed": graph_changed, "population_changed": population_changed,
                "coverage_changed": coverage_changed, "evidence_changed": evidence_changed,
                "selected_evidence_changed": old_data["provenance"]["selected_records"] != data["provenance"]["selected_records"],
                "receipt_prefix_changed": bool(added),
                "resolved_view_changed": old_data["view"] != data["view"],
                "snapshot_hash_changed": old.content_hash != new.content_hash,
                "snapshot_hash": new.content_hash,
                "source_time": {key: resolved[view_id][key] for key in ("at", "start", "end") if key in resolved[view_id]},
                "comparison_eligible": qualified,
                "qualified_comparison_status": None if not committed else ("OK" if qualified else "NOT_RUN"),
                "tracking_comparison_status": tracking_status,
                "tracking_comparison_reason": tracking_reason,
                "qualified_relation_change_counts": change_counts,
            }
        if name == "advance_to_25":
            assert time_advanced and not added
            assert all(not result[key] for result in view_results.values()
                       for key in ("observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed"))
        if index > 1:
            assert not any(view_results["trust"][key] for key in (
                "observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed"))
        status = "APPLIED" if committed else ("NO_NEW_RECORDS" if is_receipt else "NO_TIME_ADVANCE")
        stages[name] = {
            "delivery_index": index,
            "delivery_kind": "receipt_batch" if is_receipt else "source_time_advance",
            "expected_transition_cause": "receipt_batch" if is_receipt else "source_time_advance",
            "received_at": delivery.get("received_at"),
            "record_count": len(delivery.get("records", [])), "records_added": added,
            "knowledge_cutoff_before": before_cutoff, "knowledge_cutoff": cutoff,
            "source_cursor_before": before_cursor, "source_cursor": cursor,
            "source_time_advanced": time_advanced, "sequence_before": before_sequence,
            "sequence": sequence, "checkpoint_created": committed,
            "expected_receipt_status": status, "views": view_results,
        }
        if committed:
            checkpoints.append((sequence, cutoff, cursor, current))
        if index == RESTART_AFTER_DELIVERY:
            # This is only a source journal/cursor JSON round trip. The case
            # runner must independently test the actual store/process restart.
            saved = json.loads(_json_bytes({"dataset": dataset.to_dict(), "cursor": cursor}))
            dataset = EventDataset.from_mapping(saved["dataset"])
            assert saved["cursor"] == cursor == 20 and sequence == 4 and cutoff == 20
            for view_id, view in resolved.items():
                assert _json_bytes(materialize_snapshot(dataset, view, cutoff).to_dict()) == _json_bytes(current[view_id].to_dict())
        previous = current

    assert (len(dataset.records), sequence, cursor, len(checkpoints)) == (22, 8, 26, 9)
    for _, cutoff, old_cursor, snapshots in checkpoints:
        for view_id, view in _resolved_views(registration, old_cursor).items():
            replay = materialize_snapshot(dataset, view, cutoff)
            assert _json_bytes(replay.to_dict()) == _json_bytes(snapshots[view_id].to_dict())
    assert sum(v["tracking_comparison_status"] == "OK" for s in stages.values() for v in s["views"].values()) == 5
    return stages, [{"sequence": sequence, "knowledge_cutoff": cutoff, "source_cursor": cursor}
                    for sequence, cutoff, cursor, _ in checkpoints]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate and compare existing fixture bytes without writing")
    args = parser.parse_args()
    empty, registration, stage_names, deliveries, negative = fixture_inputs()
    stages, checkpoints = validate_fixture(empty, registration, stage_names, deliveries)
    encoded = {
        "empty.events.json": _json_bytes(empty),
        "initial.batch.json": _json_bytes(deliveries[0]),
        "registration.json": _json_bytes(registration),
        "commands.jsonl": _jsonl_bytes(deliveries),
        "commands-before-restart.jsonl": _jsonl_bytes(deliveries[:RESTART_AFTER_DELIVERY]),
        "commands-after-restart.jsonl": _jsonl_bytes(deliveries[RESTART_AFTER_DELIVERY:]),
        **{name: _jsonl_bytes([value]) for name, value in negative.items()},
    }
    metadata = {
        "schema": "sociolab.temporal-tracking-fixture.v1", "origin": "synthetic",
        "description": "Four invented people; two state-at-cursor views and one trailing communication window.",
        "initial_dataset": "empty.events.json", "registration": "registration.json",
        "initial_batch_shape": "full_sociolab.network-tracking-batch.v1_envelope_not_raw_array",
        "streams": {"all": "commands.jsonl", "before_restart": "commands-before-restart.jsonl", "after_restart": "commands-after-restart.jsonl"},
        "stage_order": stage_names, "stages": stages, "checkpoints": checkpoints,
        "restart_after_delivery": RESTART_AFTER_DELIVERY,
        "restart_state": {"sequence": 4, "knowledge_cutoff": 20, "source_cursor": 20},
        "initial_sequence": 0, "initial_knowledge_cutoff": 0, "initial_cursor": INITIAL_CURSOR,
        "source_time_unit": "tick", "registered_view_count": 3,
        "delivery_count": 11, "applied_delivery_count": 8,
        "applied_receipt_batch_count": 3, "applied_source_time_advance_count": 5,
        "no_new_records_count": 1, "no_time_advance_count": 2, "idempotent_delivery_count": 3,
        "final_sequence": 8, "final_knowledge_cutoff": 22, "final_cursor": 26,
        "expected_checkpoint_count_including_initial": 9, "expected_qualified_tracking_comparison_count": 5,
        "negative_cases": [
            {"file": name, "attempt_after_delivery": 11, "expected": reason,
             "sequence_must_remain": 8, "knowledge_cutoff_must_remain": 22, "source_cursor_must_remain": 26}
            for name, reason in zip(negative, (
                "reject_backwards_source_time", "reject_noninteger_tick_cursor", "reject_mixed_advance_and_receipt_fields"))
        ],
        "input_file_sha256": {name: sha256(raw).hexdigest() for name, raw in encoded.items()},
        "generator_file_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "verification": {
            "real_ingest_records_used": True, "real_materialize_snapshot_used": True,
            "real_compare_snapshots_used_only_with_complete_inputs": True,
            "fixed_cutoff_and_cursor_snapshot_bytes_preserved_after_all_appends": True,
            "idempotent_imports_and_equal_cursors_preserve_source_snapshots": True,
            "journal_and_explicit_cursor_json_round_trip_at_restart_point_checked": True,
            "persistent_tracking_api_executed": False, "negative_tracking_commands_executed": False,
            "live_acknowledgment_before_eof_verified": False, "disk_restart_verified": False,
        },
        "scope": {
            "engineering_fixture_only": True, "real_data_used": False,
            "receipt_timestamps_invented": True, "all_source_values_known_before_execution": True,
            "registered_query_policies_fixed": True, "source_cursor_explicit_not_wall_clock": True,
            "future_dated_source_records_are_invented_boundary_checks": True,
            "external_source_subscription": False, "source_authenticity_verified": False,
            "causal_effect_identified": False, "empirical_prediction_validated": False,
        },
    }
    encoded["metadata.json"] = _json_bytes(metadata)
    for name, raw in encoded.items():
        path = DIRECTORY / name
        if args.check:
            if not path.is_file() or path.read_bytes() != raw:
                raise SystemExit("fixture file differs from deterministic generator: " + name)
        else:
            path.write_bytes(raw)
    print(json.dumps({"status": "PASS", "mode": "check" if args.check else "write",
                      "delivery_count": 11, "applied_delivery_count": 8,
                      "final_knowledge_cutoff": 22, "final_source_cursor": 26,
                      "expected_checkpoint_count": 9, "persistent_tracking_api_executed": False,
                      "files": sorted(encoded)}, sort_keys=True))


if __name__ == "__main__":
    main()
