#!/usr/bin/env python3
"""Write hand-authored journal inputs and validate real importer/snapshot replay.

This fixture does not simulate people, fit a model, issue predictions, or score
outcomes. Its target values are already known to the fixture author and script.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import sys


DIRECTORY = Path(__file__).resolve().parent
REPOSITORY = DIRECTORY.parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from sociolab.events import EventDataset, ingest_records
from sociolab.snapshots import materialize_snapshot


ACTORS = ("A", "B", "C", "D")
POPULATION = "invented-cohort"
LAYER = "directed_observed_social_tie"
SYSTEM = "invented-journal-fixture"
ATTRIBUTE = "invented_behavior_level_0_to_5"
SOURCE_REVISION = "invented-journal-source-v1"
STAGES = (
    ("initial", "initial.batch.json", "2026-11-28T00:00:00Z"),
    ("late_history", "late-history.batch.json", "2026-11-28T00:01:00Z"),
    ("target", "target.batch.json", "2026-11-28T00:02:00Z"),
    ("revised_target", "revised-target.batch.json", "2026-11-28T00:03:00Z"),
)


def _record(record_id, kind, payload, *, at=0, interval=None,
            fact_id=None, supersedes=None, operation="assert", revision="batch-1"):
    """Raw importer input: receipt fields are intentionally absent."""
    return {
        "record_id": record_id,
        "fact_id": record_id if fact_id is None else fact_id,
        "operation": operation,
        "supersedes": supersedes,
        "kind": kind,
        "occurred_at": at,
        "valid_interval": interval,
        "source": {
            "system": SYSTEM,
            "record_id": record_id,
            "revision": revision,
            "evidence_ref": "synthetic:" + record_id,
        },
        "payload": payload,
    }


def _behavior(record_id, actor, value, *, at, **revision):
    return _record(record_id, "actor.attribute.observed", {
        "actor": actor, "name": ATTRIBUTE, "value": value,
    }, at=at, **revision)


def _relation(record_id, source, target, *, at, strength=1, **revision):
    return _record(record_id, "relation.observed", {
        "layer": LAYER, "source": source, "target": target,
        "directed": True, "strength": strength,
    }, at=at, **revision)


def fixture_inputs():
    empty = {
        "schema": "sociolab.events.v1",
        "dataset_id": "synthetic-journal-forecast-example",
        "origin": "synthetic",
        "source_revision": SOURCE_REVISION,
        "clock": {"kind": "ticks", "run_id": "journal-forecast-example"},
        "records": [],
    }
    initial = [
        _record("declare-" + actor, "entity.observed", {
            "entity_id": actor, "entity_type": "person",
        }) for actor in ACTORS
    ]
    initial.extend(
        _record("membership-" + actor, "membership.changed", {
            "actor": actor, "population": POPULATION, "status": "present",
        }) for actor in ACTORS
    )
    # Adjacent half-open intervals cover [0,20), never the target instant 20.
    for wave, at in ((0, 0), (1, 10)):
        initial.append(_record("coverage-wave-" + str(wave), "coverage.observed", {
            "population": POPULATION, "layer": LAYER,
            "actors": list(ACTORS), "status": "complete",
        }, at=at, interval=[at, at + 10]))
    for wave, at, pairs in (
        (0, 0, (("A", "B"), ("B", "C"), ("C", "A"))),
        (1, 10, (("A", "C"), ("B", "A"), ("C", "D"))),
    ):
        initial.extend(
            _relation(f"relation-wave-{wave}-{source}-{target}", source, target, at=at)
            for source, target in pairs
        )
    for wave, at, values in ((0, 0, (1, 2, 3, 4)), (1, 10, (2, 3, 2, 4))):
        initial.extend(
            _behavior(f"behavior-wave-{wave}-{actor}", actor, value, at=at)
            for actor, value in zip(ACTORS, values)
        )

    late = [
        _record("declare-C-alias", "entity.observed", {
            "entity_id": "C_alias", "entity_type": "person",
        }, revision="batch-2"),
        _record("map-C-alias", "identity.mapped", {
            "alias": "C_alias", "canonical": "C",
        }, revision="batch-2"),
        _behavior("behavior-wave-1-C-corrected", "C_alias", 3, at=10,
                  fact_id="behavior-wave-1-C", supersedes="behavior-wave-1-C",
                  revision="batch-2"),
        _record("relation-wave-1-B-A-retracted", "relation.observed", None, at=10,
                fact_id="relation-wave-1-B-A", supersedes="relation-wave-1-B-A",
                operation="retract", revision="batch-2"),
        # A distinct source fact explicitly confirms zero after withdrawal of
        # the erroneous positive. Withdrawal alone is not proof of no relation.
        _relation("relation-wave-1-B-A-zero", "B", "A", at=10, strength=0,
                  revision="batch-2"),
    ]
    target = [
        _behavior(f"behavior-wave-2-{actor}", actor, value, at=20, revision="batch-3")
        for actor, value in zip(ACTORS, (3, 2, 3, 4))
    ]
    revised_target = [
        _behavior("behavior-wave-2-D-corrected", "D", 1, at=20,
                  fact_id="behavior-wave-2-D", supersedes="behavior-wave-2-D",
                  revision="batch-4"),
    ]
    history_spec = {
        "schema": "sociolab.journal-forecast-history.v1",
        "knowledge_cutoff": len(initial),
        "source_reference": None,
        "actors": list(ACTORS),
        "population": POPULATION,
        "layer": LAYER,
        "behavior_source": {"system": SYSTEM, "attribute": ATTRIBUTE},
        "waves": [{"time_index": 0, "at": 0}, {"time_index": 1, "at": 10}],
        "target_at": 20,
        "forecast_specification": {
            "schema": "sociolab.behavior-forecast.v1",
            "profile": "own-lag-outgoing-gap-ols-v1",
            "behavior": {
                "variable": ATTRIBUTE, "minimum": 0, "maximum": 5,
                "measurement_reference": "synthetic:hand-authored-journal-levels",
            },
            "target_time_index": 2,
            "research_question": "Check receipt-cutoff isolation with manually authored inputs; no empirical performance claim.",
        },
    }
    return {
        "empty.events.json": empty,
        "initial.batch.json": initial,
        "late-history.batch.json": late,
        "target.batch.json": target,
        "revised-target.batch.json": revised_target,
        "history.spec.json": history_spec,
    }


def _view(at):
    return {
        "schema": "sociolab.view.v1", "population": POPULATION,
        "layer": LAYER, "mode": "state", "directed": True,
        "actions": [], "roles": [], "topics": [], "at": at,
    }


def _behavior_at(dataset, at, cutoff):
    """Fixture assertions only; this is not the journal export implementation."""
    identities = dataset.identity_map_at(cutoff)
    result = {}
    for record in dataset.as_known(cutoff):
        if (record["kind"] != "actor.attribute.observed"
                or record["source"]["system"] != SYSTEM
                or record["occurred_at"] != at):
            continue
        payload = record["payload"]
        if payload["name"] != ATTRIBUTE:
            continue
        actor = identities.get(payload["actor"], payload["actor"])
        assert record["valid_interval"] is None
        assert actor in ACTORS and actor not in result
        assert type(payload["value"]) is int and 0 <= payload["value"] <= 5
        result[actor] = payload["value"]
    return dict(sorted(result.items()))


def _determinant3(rows):
    a, b, c = rows
    return (a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def validate_fixture(inputs):
    """Exercise actual ingestion and snapshots; never import forecasting APIs."""
    dataset = EventDataset.from_mapping(inputs["empty.events.json"])
    stages, journals = {}, {}
    for name, filename, received_at in STAGES:
        dataset = ingest_records(dataset, inputs[filename], received_at=received_at)
        assert dataset.source_revision == SOURCE_REVISION
        stages[name] = {
            "batch": filename, "received_at": received_at,
            "record_count": len(inputs[filename]),
            "knowledge_cutoff": len(dataset.records),
        }
        journals[name] = dataset
    assert [stages[name]["knowledge_cutoff"] for name, _, _ in STAGES] == [24, 29, 33, 34]
    assert inputs["history.spec.json"]["knowledge_cutoff"] == stages["initial"]["knowledge_cutoff"]

    history_snapshots = {}
    for stage, expected_behavior, expected_edges in (
        ("initial", {"A": 2, "B": 3, "C": 2, "D": 4}, {("A", "C"), ("B", "A"), ("C", "D")}),
        ("late_history", {"A": 2, "B": 3, "C": 3, "D": 4}, {("A", "C"), ("C", "D")}),
    ):
        journal = journals[stage]
        cutoff = stages[stage]["knowledge_cutoff"]
        snapshots = [materialize_snapshot(journal, _view(at), cutoff) for at in (0, 10)]
        for snapshot in snapshots:
            assert snapshot.persons == ACTORS
            assert snapshot.directed and snapshot.coverage_complete
            assert all(edge["strength"] == 1 for edge in snapshot.to_dict()["edges"])
        assert set(snapshots[0].to_graph().edges()) == {("A", "B"), ("B", "C"), ("C", "A")}
        assert snapshots[0].to_graph().degree("D") == 0
        assert set(snapshots[1].to_graph().edges()) == expected_edges
        assert _behavior_at(journal, 0, cutoff) == dict(zip(ACTORS, (1, 2, 3, 4)))
        assert _behavior_at(journal, 10, cutoff) == expected_behavior
        assert _behavior_at(journal, 20, cutoff) == {}
        history_snapshots[stage] = snapshots

    assert journals["initial"].identity_map_at(24) == {}
    assert dataset.identity_map_at(29) == {"C_alias": "C"}
    intermediate = materialize_snapshot(dataset, _view(10), 25)
    assert not intermediate.coverage_complete
    assert intermediate.to_dict()["population"]["unknown"] == ["C_alias"]
    late_zero = "relation-wave-1-B-A-zero"
    assert late_zero in history_snapshots["late_history"][1].to_dict()["provenance"]["selected_records"]

    for stage in ("initial", "late_history"):
        cutoff = stages[stage]["knowledge_cutoff"]
        for at, original in zip((0, 10), history_snapshots[stage]):
            replay = materialize_snapshot(dataset, _view(at), cutoff)
            assert replay.to_dict() == original.to_dict()
            assert _json_bytes(replay.to_dict()) == _json_bytes(original.to_dict())
            assert _behavior_at(dataset, at, cutoff) == _behavior_at(journals[stage], at, cutoff)

    original_target = {"A": 3, "B": 2, "C": 3, "D": 4}
    assert _behavior_at(journals["target"], 20, 33) == original_target
    assert _behavior_at(dataset, 20, 33) == original_target
    assert _behavior_at(dataset, 20, 34) == {**original_target, "D": 1}
    for stage in ("target", "revised_target"):
        cutoff = stages[stage]["knowledge_cutoff"]
        target_snapshot = materialize_snapshot(journals[stage], _view(20), cutoff)
        assert target_snapshot.persons == ACTORS
        assert not target_snapshot.coverage_complete
        assert target_snapshot.to_dict()["coverage"]["evidence"] == []

    # An exact nonzero 3x3 minor proves rank 3 for the four-row training
    # feature design. This checks feasibility without estimating coefficients.
    graph = history_snapshots["initial"][0].to_graph()
    behavior = _behavior_at(journals["initial"], 0, 24)
    rows = []
    for actor in ACTORS:
        neighbors = tuple(graph.successors(actor))
        gap = (Fraction(sum(behavior[n] for n in neighbors), len(neighbors)) - behavior[actor]
               if neighbors else Fraction(0))
        rows.append((Fraction(1), Fraction(behavior[actor]), gap))
    assert _determinant3(rows[:3]) == -3

    return {
        "stages": stages,
        "verification": {
            "real_ingest_records_used": True,
            "real_materialize_snapshot_used": True,
            "fixed_cutoff_snapshot_bytes_unchanged_after_all_appends": True,
            "fixed_cutoff_behavior_unchanged_after_all_appends": True,
            "all_history_snapshots_complete_with_four_actors": True,
            "target_time_network_coverage_complete": False,
            "network_training_row_count": 4,
            "network_training_column_count": 3,
            "network_training_rank": 3,
            "rank_check": "exact_integer_determinant_of_three_row_minor_is_minus_3",
            "panel_or_manifest_export_performed": False,
            "predictions_created": False,
            "scores_computed": False,
        },
    }


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate and compare existing files without writing")
    args = parser.parse_args()
    inputs = fixture_inputs()
    validation = validate_fixture(inputs)
    encoded = {name: _json_bytes(value) for name, value in inputs.items()}
    metadata = {
        "schema": "sociolab.journal-forecast-fixture.v1",
        "origin": "synthetic",
        "description": "Manually authored inputs for four invented people; no generated social process or real observations.",
        "stage_order": [name for name, _, _ in STAGES],
        "stages": validation["stages"],
        "input_file_sha256": {name: sha256(raw).hexdigest() for name, raw in encoded.items()},
        "generator_file_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "verification": validation["verification"],
        "expected_downstream_checks": {
            "old_cutoff": 24,
            "corrected_history_cutoff": 29,
            "first_target_cutoff": 33,
            "revised_target_cutoff": 34,
            "old_panel_manifest_and_forecast_bytes_unchanged": "to_be_verified_by_separate_case_runner",
            "revised_history_is_separate_artifact": True,
            "target_revision_rescores_saved_forecast_without_refitting": "to_be_verified_by_separate_case_runner",
        },
        "scope": {
            "engineering_fixture_only": True,
            "real_data_used": False,
            "receipt_timestamps_are_invented": True,
            "future_values_predeclared_in_fixture": True,
            "target_blinding_demonstrated": False,
            "prospective_validation": False,
            "empirical_predictive_advantage_validated": False,
            "causal_effect_identified": False,
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
    print(json.dumps({
        "status": "PASS", "mode": "check" if args.check else "write",
        "files": sorted(encoded),
        "knowledge_cutoffs": [validation["stages"][name]["knowledge_cutoff"] for name, _, _ in STAGES],
        "predictions_created": False, "scores_computed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
