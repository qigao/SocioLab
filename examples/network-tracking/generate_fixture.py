#!/usr/bin/env python3
"""Write invented receipt batches for fixed-view network tracking.

Only the existing importer, materializer and qualified snapshot comparison are
used for fixture checks. This script does not start the persistent tracker,
subscribe to a source, fit a model, or establish empirical effects.
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
SYSTEM = "invented-network-tracking"
SOURCE_REVISION = "invented-network-tracking-source-v1"
VIEW_IDS = ("cooperation_5", "cooperation_15", "communication")
BATCH_SCHEMA = "sociolab.network-tracking-batch.v1"
RESTART_AFTER_DELIVERY = 8


def _record(record_id, kind, payload, *, at=0, interval=None,
            fact_id=None, supersedes=None, operation="assert", revision="initial"):
    return {
        "record_id": record_id, "fact_id": record_id if fact_id is None else fact_id,
        "operation": operation, "supersedes": supersedes, "kind": kind,
        "occurred_at": at, "valid_interval": interval,
        "source": {"system": SYSTEM, "record_id": record_id, "revision": revision,
                   "evidence_ref": "synthetic:" + record_id},
        "payload": payload,
    }


def _relation(record_id, source, target, *, at, strength=1, **revision):
    return _record(record_id, "relation.changed", {
        "layer": "cooperation", "source": source, "target": target,
        "directed": False, "strength": strength,
    }, at=at, **revision)


def _coverage(record_id, status, *, layer="cooperation", **revision):
    return _record(record_id, "coverage.observed", {
        "population": POPULATION, "layer": layer,
        "actors": list(ACTORS), "status": status,
    }, interval=[0, 20], **revision)


def _registration():
    common = {
        "schema": "sociolab.view.v1", "population": POPULATION,
        "layer": "cooperation", "mode": "state", "directed": False,
        "actions": [], "roles": [], "topics": [],
    }
    communication = {
        **common, "layer": "communication", "mode": "events", "directed": True,
        "actions": ["reply", "utterance"], "start": 0, "end": 20,
    }
    return {
        "schema": "sociolab.network-tracking-spec.v1",
        "views": [
            {"view_id": VIEW_IDS[0], "view": {**common, "at": 5}, "analysis": {}},
            {"view_id": VIEW_IDS[1], "view": {**common, "at": 15}, "analysis": {}},
            {"view_id": VIEW_IDS[2], "view": communication, "analysis": {}},
        ],
    }


def fixture_inputs():
    empty = {
        "schema": "sociolab.events.v1", "dataset_id": "synthetic-network-tracking-example",
        "origin": "synthetic", "source_revision": SOURCE_REVISION,
        "clock": {"kind": "ticks", "run_id": "network-tracking-example"}, "records": [],
    }
    initial = [_record("declare-" + actor, "entity.observed", {
        "entity_id": actor, "entity_type": "person",
    }) for actor in ACTORS]
    initial.extend(_record("membership-" + actor, "membership.changed", {
        "actor": actor, "population": POPULATION, "status": "present",
    }) for actor in ACTORS)
    initial.extend([
        _coverage("coverage-cooperation", "complete"),
        _coverage("coverage-communication", "complete", layer="communication"),
        _relation("cooperation-A-B", "A", "B", at=0),
        _relation("cooperation-C-D", "C", "D", at=0),
        _record("reply-A-D", "interaction.observed", {
            "actor": "A", "target": "D", "action": "reply", "topic": "task",
        }, at=3),
    ])
    new_relation = [_relation("link-v1", "B", "C", at=10, fact_id="link", revision="new-relation")]
    correction = [_relation("link-v2", "B", "D", at=4, fact_id="link", supersedes="link-v1",
                            revision="late-correction")]
    evidence = [_relation("link-v3", "B", "D", at=4, strength=1.0,
                          fact_id="link", supersedes="link-v2", revision="evidence-only")]
    attribute = [_record("attribute-C", "actor.attribute.observed", {
        "actor": "C", "name": "declared_position", "value": "opposes_proposal",
    }, at=8, revision="attribute-only")]
    withdrawal = [
        _record("link-withdrawn", "relation.changed", None, at=4, fact_id="link",
                supersedes="link-v3", operation="retract", revision="withdrawal"),
        _relation("observed-zero-B-D", "B", "D", at=4, strength=0, revision="withdrawal"),
    ]
    partial = [_coverage("coverage-cooperation-partial", "partial", fact_id="coverage-cooperation",
                         supersedes="coverage-cooperation", revision="partial-coverage")]
    recovered = [_coverage("coverage-cooperation-recovered", "complete", fact_id="coverage-cooperation",
                           supersedes="coverage-cooperation-partial", revision="recovered-coverage")]
    post_recovery = [_relation("later-link-B-C", "B", "C", at=12, revision="new-after-recovery")]
    stages = (
        ("initial", initial),
        ("new_relation", new_relation),
        ("late_correction", correction),
        ("evidence_only", evidence),
        ("duplicate_old_link", deepcopy(new_relation)),
        ("attribute_only", attribute),
        ("retract", withdrawal),
        ("coverage_partial", partial),
        ("duplicate_partial_after_restart", deepcopy(partial)),
        ("coverage_recovered", recovered),
        ("post_recovery_relation", post_recovery),
    )
    batches = [{"schema": BATCH_SCHEMA, "records": records,
                "received_at": f"2026-11-28T00:{index:02d}:00Z"}
               for index, (_, records) in enumerate(stages, 1)]
    conflicting = deepcopy(new_relation)
    conflicting[0]["payload"]["strength"] = 2
    negative = {"schema": BATCH_SCHEMA, "records": conflicting, "received_at": "2026-11-28T00:12:00Z"}
    return empty, _registration(), [name for name, _ in stages], batches, negative


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _jsonl_bytes(values):
    return ("".join(json.dumps(value, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False) + "\n" for value in values)).encode("utf-8")


def _observed_graph(snapshot):
    data = snapshot.to_dict()
    # Python numeric equality intentionally treats strength 1 and 1.0 as equal;
    # evidence and receipt metadata are checked separately.
    return (data["persons"], data["activities"], data["directed"], data["bipartite"],
            {(edge["source"], edge["target"]): edge["strength"] for edge in data["edges"]})


def validate_fixture(empty, registration, stage_names, batches, negative):
    dataset = EventDataset.from_mapping(empty)
    views = {entry["view_id"]: entry["view"] for entry in registration["views"]}
    previous = {name: materialize_snapshot(dataset, view, 0) for name, view in views.items()}
    checkpoints = [(0, previous)]
    base, bridge_bc, bridge_bd, communication = {("A", "B"), ("C", "D")}, {("B", "C")}, {("B", "D")}, {("A", "D")}
    expected_edges = (
        (base, base), (base, base | bridge_bc), (base | bridge_bd, base | bridge_bd),
        (base | bridge_bd, base | bridge_bd), (base | bridge_bd, base | bridge_bd),
        (base | bridge_bd, base | bridge_bd), (base, base), (base, base), (base, base),
        (base, base), (base, base | bridge_bc),
    )
    expected_cutoffs = [13, 14, 15, 16, 16, 17, 19, 20, 20, 21, 22]
    expected_sequences = [1, 2, 3, 4, 4, 5, 6, 7, 7, 8, 9]
    selected_changed = (
        (True, True, True), (False, True, False), (True, True, False),
        (True, True, False), (False, False, False), (False, False, False),
        (True, True, False), (True, True, False), (False, False, False),
        (True, True, False), (False, True, False),
    )
    stages, sequence = {}, 0
    for index, (name, batch, edges) in enumerate(zip(stage_names, batches, expected_edges), 1):
        before_dataset = dataset
        before_cutoff = len(dataset.records)
        dataset = ingest_records(dataset, batch["records"], received_at=batch["received_at"])
        added = len(dataset.records) - before_cutoff
        if added:
            sequence += 1
        else:
            assert dataset is before_dataset
        cutoff = len(dataset.records)
        assert cutoff == expected_cutoffs[index - 1] and sequence == expected_sequences[index - 1]
        assert dataset.source_revision == SOURCE_REVISION
        current = {view_id: materialize_snapshot(dataset, view, cutoff) for view_id, view in views.items()}
        expected_complete = index not in (8, 9)
        view_results = {}
        for view_index, view_id in enumerate(VIEW_IDS):
            old, new = previous[view_id], current[view_id]
            old_data, data = old.to_dict(), new.to_dict()
            wanted_edges = communication if view_id == "communication" else edges[view_index]
            assert {(edge["source"], edge["target"]) for edge in data["edges"]} == wanted_edges
            assert tuple(data["persons"]) == ACTORS
            assert new.coverage_complete == (True if view_id == "communication" else expected_complete)
            old_selected, new_selected = old_data["provenance"]["selected_records"], data["provenance"]["selected_records"]
            assert (old_selected != new_selected) == selected_changed[index - 1][view_index]
            graph_changed = _observed_graph(old) != _observed_graph(new)
            qualified = bool(added and old.coverage_complete and new.coverage_complete)
            change_counts = None
            if qualified:
                comparison = compare_snapshots(old, new, algorithm="louvain", seed=0, resolution=1.0)
                relations = comparison["relations"]
                change_counts = {key: len(relations[key]) for key in ("added", "removed", "reweighted", "evidence_changed")}
                if name == "evidence_only":
                    assert not graph_changed
                    assert change_counts["reweighted"] == 0
                    assert change_counts["evidence_changed"] == (0 if view_id == "communication" else 1)
                if name == "attribute_only" or view_id == "communication":
                    assert not graph_changed
                    assert change_counts == {key: 0 for key in change_counts}
            if not added:
                assert _json_bytes(old_data) == _json_bytes(data)
            else:
                assert old.content_hash != new.content_hash
            population_changed = old_data["population"] != data["population"]
            coverage_changed = any(old_data["coverage"][key] != data["coverage"][key]
                                   for key in ("complete", "actors"))
            if not added:
                tracking_status, tracking_reason = None, None
            elif not (graph_changed or population_changed or coverage_changed):
                tracking_status, tracking_reason = "NOT_RUN", "no_observable_change"
            elif not old.coverage_complete or not new.coverage_complete:
                tracking_status, tracking_reason = "NOT_RUN", "incomplete_before_or_after_coverage"
            else:
                tracking_status, tracking_reason = "OK", None
            view_results[view_id] = {
                "person_count": 4, "activity_count": 0, "edge_count": len(data["edges"]),
                "complete": new.coverage_complete,
                "observed_graph_changed": graph_changed,
                "population_changed": population_changed,
                "coverage_changed": coverage_changed,
                "selected_evidence_changed": old_selected != new_selected,
                "receipt_prefix_evidence_changed": bool(added),
                "snapshot_hash_changed": old.content_hash != new.content_hash,
                "comparison_eligible": qualified,
                "qualified_comparison_status": None if not added else ("OK" if qualified else "NOT_RUN"),
                "tracking_comparison_status": tracking_status,
                "tracking_comparison_reason": tracking_reason,
                "qualified_relation_change_counts": change_counts,
            }
        stages[name] = {
            "delivery_index": index, "received_at": batch["received_at"],
            "record_count": len(batch["records"]), "records_added": added,
            "knowledge_cutoff_before": before_cutoff, "knowledge_cutoff": cutoff,
            "accepted_batch_sequence": sequence,
            "expected_receipt_status": "APPLIED" if added else "NO_NEW_RECORDS",
            "views": view_results,
        }
        if added:
            checkpoints.append((cutoff, current))
        if index == RESTART_AFTER_DELIVERY:
            # Journal round-trip only. Actual checkpoint restart and live pipe
            # acknowledgment are separate case-runner checks, not claimed here.
            dataset = EventDataset.from_mapping(json.loads(_json_bytes(dataset.to_dict())))
            for view_id, view in views.items():
                assert _json_bytes(materialize_snapshot(dataset, view, cutoff).to_dict()) == _json_bytes(current[view_id].to_dict())
        previous = current

    assert len(dataset.records) == 22 and sequence == 9
    for cutoff, snapshots in checkpoints:
        for view_id, old in snapshots.items():
            replay = materialize_snapshot(dataset, views[view_id], cutoff)
            assert _json_bytes(replay.to_dict()) == _json_bytes(old.to_dict())
    before_negative = _json_bytes(dataset.to_dict())
    try:
        ingest_records(dataset, negative["records"], received_at=negative["received_at"])
    except ValueError as error:
        assert "record ID reused with different source content" in str(error)
    else:
        raise AssertionError("conflicting retry must be rejected")
    assert _json_bytes(dataset.to_dict()) == before_negative
    return stages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate and compare existing fixture bytes without writing")
    args = parser.parse_args()
    empty, registration, stage_names, batches, negative = fixture_inputs()
    stages = validate_fixture(empty, registration, stage_names, batches, negative)
    encoded = {
        "empty.events.json": _json_bytes(empty),
        "initial.batch.json": _json_bytes(batches[0]),
        "registration.json": _json_bytes(registration),
        "batches.jsonl": _jsonl_bytes(batches),
        "batches-before-restart.jsonl": _jsonl_bytes(batches[:RESTART_AFTER_DELIVERY]),
        "batches-after-restart.jsonl": _jsonl_bytes(batches[RESTART_AFTER_DELIVERY:]),
        "rejected-conflicting-retry.jsonl": _jsonl_bytes([negative]),
    }
    metadata = {
        "schema": "sociolab.network-tracking-fixture.v1",
        "origin": "synthetic", "description": "Four invented people and three fixed source views; all observations are manually authored.",
        "initial_dataset": "empty.events.json", "registration": "registration.json",
        "initial_batch_shape": "full_sociolab.network-tracking-batch.v1_envelope_not_raw_array",
        "streams": {"all": "batches.jsonl", "before_restart": "batches-before-restart.jsonl", "after_restart": "batches-after-restart.jsonl"},
        "stage_order": stage_names, "stages": stages,
        "restart_after_delivery": RESTART_AFTER_DELIVERY,
        "initial_sequence": 0, "initial_knowledge_cutoff": 0,
        "delivery_count": len(batches), "applied_batch_count": 9, "idempotent_delivery_count": 2,
        "final_sequence": 9, "final_knowledge_cutoff": 22,
        "expected_checkpoint_count_including_initial": 10,
        "negative_case": {
            "file": "rejected-conflicting-retry.jsonl", "attempt_after_delivery": 11,
            "expected": "reject_same_record_id_with_changed_source_content",
            "sequence_must_remain": 9, "knowledge_cutoff_must_remain": 22,
        },
        "input_file_sha256": {name: sha256(raw).hexdigest() for name, raw in encoded.items()},
        "generator_file_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "verification": {
            "real_ingest_records_used": True, "real_materialize_snapshot_used": True,
            "real_compare_snapshots_used_only_with_complete_inputs": True,
            "fixed_cutoff_snapshot_bytes_preserved_after_all_appends": True,
            "idempotent_imports_preserve_journal_and_snapshots": True,
            "conflicting_retry_rejected_without_journal_mutation": True,
            "journal_json_round_trip_at_restart_cutoff_checked": True,
            "persistent_tracking_api_executed": False,
            "live_acknowledgment_before_eof_verified": False,
            "disk_restart_verified": False,
        },
        "scope": {
            "engineering_fixture_only": True, "real_data_used": False,
            "receipt_timestamps_invented": True, "all_source_values_known_before_execution": True,
            "source_views_fixed_not_wall_clock_rolling": True, "external_source_subscription": False,
            "source_authenticity_verified": False, "causal_effect_identified": False,
            "empirical_prediction_validated": False,
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
                      "delivery_count": 11, "applied_batch_count": 9, "final_knowledge_cutoff": 22,
                      "persistent_tracking_api_executed": False, "files": sorted(encoded)}, sort_keys=True))


if __name__ == "__main__":
    main()
