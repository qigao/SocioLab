#!/usr/bin/env python3
"""Write a hand-authored receipt-aware two-origin evaluation fixture.

Validation uses the actual event importer and snapshot materializer, plus exact
arithmetic for design rank. It does not create plans, panels, forecasts, scores,
or evaluation reports. All invented future values are known to this script.
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
SYSTEM = "invented-journal-evaluation"
ATTRIBUTE = "invented_behavior_level_0_to_5"
SOURCE_REVISION = "invented-journal-evaluation-source-v1"
STAGES = (
    ("initial", "initial.batch.json", "2026-11-28T00:00:00Z"),
    ("target_first", "target-first.batch.json", "2026-11-28T00:01:00Z"),
    ("second_history", "second-history.batch.json", "2026-11-28T00:02:00Z"),
    ("target_second", "target-second.batch.json", "2026-11-28T00:03:00Z"),
    ("revised_target", "revised-target.batch.json", "2026-11-28T00:04:00Z"),
)
INITIAL_PAIRS = (
    (("A", "B"), ("B", "C"), ("C", "A")),
    (("A", "C"), ("B", "A"), ("C", "D")),
)
SECOND_HISTORY_PAIRS = (("A", "D"), ("B", "C"), ("D", "A"))


def _record(record_id, kind, payload, *, at=0, interval=None,
            fact_id=None, supersedes=None, revision="batch-1"):
    """Source input only: ingestion supplies the sequence and receipt fields."""
    return {
        "record_id": record_id,
        "fact_id": record_id if fact_id is None else fact_id,
        "operation": "assert",
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


def _relation(record_id, source, target, *, at, **revision):
    return _record(record_id, "relation.observed", {
        "layer": LAYER, "source": source, "target": target,
        "directed": True, "strength": 1,
    }, at=at, **revision)


def _coverage(wave, at, *, revision):
    return _record(f"coverage-wave-{wave}", "coverage.observed", {
        "population": POPULATION, "layer": LAYER,
        "actors": list(ACTORS), "status": "complete",
    }, at=at, interval=[at, at + 10], revision=revision)


def _schedule(first_target_cutoff):
    return {
        "schema": "sociolab.journal-forecast-schedule.v1",
        "folds": [
            {"target_time_index": 2, "target_at": 20,
             "history_knowledge_cutoff": 24, "target_knowledge_cutoff": first_target_cutoff},
            {"target_time_index": 3, "target_at": 30,
             "history_knowledge_cutoff": 36, "target_knowledge_cutoff": 40},
        ],
    }


def fixture_inputs():
    empty = {
        "schema": "sociolab.events.v1",
        "dataset_id": "synthetic-journal-evaluation-example",
        "origin": "synthetic",
        "source_revision": SOURCE_REVISION,
        "clock": {"kind": "ticks", "run_id": "journal-evaluation-example"},
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
    initial.extend(_coverage(wave, at, revision="batch-1") for wave, at in ((0, 0), (1, 10)))
    for wave, pairs in enumerate(INITIAL_PAIRS):
        initial.extend(
            _relation(f"relation-wave-{wave}-{source}-{target}", source, target, at=wave * 10)
            for source, target in pairs
        )
    for wave, values in enumerate(((1, 2, 3, 4), (2, 3, 2, 4))):
        initial.extend(
            _behavior(f"behavior-wave-{wave}-{actor}", actor, value, at=wave * 10)
            for actor, value in zip(ACTORS, values)
        )

    first_target = [
        _behavior(f"behavior-wave-2-{actor}", actor, value, at=20, revision="batch-2")
        for actor, value in zip(ACTORS, (3, 2, 3, 4))
    ]
    second_history = [
        _record("declare-C-alias", "entity.observed", {
            "entity_id": "C_alias", "entity_type": "person",
        }, revision="batch-3"),
        _record("map-C-alias", "identity.mapped", {
            "alias": "C_alias", "canonical": "C",
        }, revision="batch-3"),
        _behavior("behavior-wave-1-C-corrected", "C_alias", 3, at=10,
                  fact_id="behavior-wave-1-C", supersedes="behavior-wave-1-C",
                  revision="batch-3"),
        _behavior("behavior-wave-2-D-before-origin-2", "D", 1, at=20,
                  fact_id="behavior-wave-2-D", supersedes="behavior-wave-2-D",
                  revision="batch-3"),
        _coverage(2, 20, revision="batch-3"),
    ]
    second_history.extend(
        _relation(f"relation-wave-2-{source}-{target}", source, target, at=20, revision="batch-3")
        for source, target in SECOND_HISTORY_PAIRS
    )
    second_target = [
        _behavior(f"behavior-wave-3-{actor}", actor, value, at=30, revision="batch-4")
        for actor, value in zip(ACTORS, (2, 3, 4, 2))
    ]
    revised_target = [
        _behavior("behavior-wave-2-D-after-origin-2", "D", 2, at=20,
                  fact_id="behavior-wave-2-D", supersedes="behavior-wave-2-D-before-origin-2",
                  revision="batch-5"),
    ]
    initial_spec = {
        "schema": "sociolab.journal-forecast-history.v1",
        "knowledge_cutoff": 24,
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
            "research_question": "Check two receipt-selected forecast origins and predeclared target versions using invented observations.",
        },
    }
    return {
        "empty.events.json": empty,
        "initial.batch.json": initial,
        "target-first.batch.json": first_target,
        "second-history.batch.json": second_history,
        "target-second.batch.json": second_target,
        "revised-target.batch.json": revised_target,
        "initial-history.spec.json": initial_spec,
        "schedule.json": _schedule(28),
        "revised-target.schedule.json": _schedule(41),
    }


def _view(at):
    return {
        "schema": "sociolab.view.v1", "population": POPULATION,
        "layer": LAYER, "mode": "state", "directed": True,
        "actions": [], "roles": [], "topics": [], "at": at,
    }


def _behavior_evidence_at(dataset, at, cutoff):
    """Fixture assertions only; production export is owned by the adapter."""
    identities = dataset.identity_map_at(cutoff)
    selected = {}
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
        assert actor in ACTORS and actor not in selected
        assert type(payload["value"]) is int and 0 <= payload["value"] <= 5
        selected[actor] = record
    return dict(sorted(selected.items()))


def _behavior_at(dataset, at, cutoff):
    return {actor: record["payload"]["value"]
            for actor, record in _behavior_evidence_at(dataset, at, cutoff).items()}


def _determinant3(rows):
    a, b, c = rows
    return (a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def _feature_rows(snapshot, behavior):
    graph, rows = snapshot.to_graph(), []
    for actor in ACTORS:
        neighbors = tuple(graph.successors(actor))
        gap = (Fraction(sum(behavior[n] for n in neighbors), len(neighbors)) - behavior[actor]
               if neighbors else Fraction(0))
        rows.append((Fraction(1), Fraction(behavior[actor]), gap))
    return rows


def validate_fixture(inputs):
    """Validate only ingestion, observation semantics and exact design rank."""
    dataset = EventDataset.from_mapping(inputs["empty.events.json"])
    stages, journals = {}, {}
    for name, filename, received_at in STAGES:
        dataset = ingest_records(dataset, inputs[filename], received_at=received_at)
        assert dataset.source_revision == SOURCE_REVISION and dataset.origin == "synthetic"
        stages[name] = {
            "batch": filename, "received_at": received_at,
            "record_count": len(inputs[filename]), "knowledge_cutoff": len(dataset.records),
        }
        journals[name] = dataset
    assert [stages[name]["knowledge_cutoff"] for name, _, _ in STAGES] == [24, 28, 36, 40, 41]
    assert inputs["initial-history.spec.json"]["knowledge_cutoff"] == 24
    assert inputs["schedule.json"] == _schedule(28)
    assert inputs["revised-target.schedule.json"] == _schedule(41)

    expected = {
        "initial": ((0, 10), ((1, 2, 3, 4), (2, 3, 2, 4)), INITIAL_PAIRS),
        "second_history": ((0, 10, 20), ((1, 2, 3, 4), (2, 3, 3, 4), (3, 2, 3, 1)),
                           (*INITIAL_PAIRS, SECOND_HISTORY_PAIRS)),
    }
    history_snapshots, designs = {}, []
    for stage, (times, values, pairs) in expected.items():
        journal, cutoff = journals[stage], stages[stage]["knowledge_cutoff"]
        snapshots, behaviors = [], []
        for at, levels, edges in zip(times, values, pairs):
            snapshot = materialize_snapshot(journal, _view(at), cutoff)
            behavior = _behavior_at(journal, at, cutoff)
            assert snapshot.persons == ACTORS and snapshot.directed and snapshot.coverage_complete
            assert all(edge["strength"] == 1 for edge in snapshot.to_dict()["edges"])
            assert set(snapshot.to_graph().edges()) == set(edges)
            assert behavior == dict(zip(ACTORS, levels))
            snapshots.append(snapshot)
            behaviors.append(behavior)
            replay = materialize_snapshot(dataset, _view(at), cutoff)
            assert _json_bytes(snapshot.to_dict()) == _json_bytes(replay.to_dict())
            assert _behavior_evidence_at(journal, at, cutoff) == _behavior_evidence_at(dataset, at, cutoff)
        assert snapshots[0].to_graph().degree("D") == 0
        assert _behavior_at(journal, times[-1] + 10, cutoff) == {}
        history_snapshots[stage] = snapshots
        rows = [row for snapshot, behavior in zip(snapshots[:-1], behaviors[:-1])
                for row in _feature_rows(snapshot, behavior)]
        assert len(rows) == 4 * (len(times) - 1)
        assert _determinant3(rows[:3]) == -3
        designs.append({"origin_time_index": len(times) - 1, "row_count": len(rows),
                        "column_count": 3, "rank": 3, "three_row_minor_determinant": -3})

    target_first = dict(zip(ACTORS, (3, 2, 3, 4)))
    target_second = dict(zip(ACTORS, (2, 3, 4, 2)))
    assert _behavior_at(journals["target_first"], 20, 28) == target_first
    assert _behavior_at(dataset, 20, 28) == target_first
    assert _behavior_evidence_at(journals["target_first"], 20, 28) == _behavior_evidence_at(dataset, 20, 28)
    assert _behavior_at(dataset, 20, 36) == {**target_first, "D": 1}
    assert _behavior_at(dataset, 20, 41) == {**target_first, "D": 2}
    assert _behavior_at(journals["target_second"], 30, 40) == target_second
    assert _behavior_evidence_at(journals["target_second"], 30, 40) == _behavior_evidence_at(dataset, 30, 40)

    for stage, at in (("target_first", 20), ("target_second", 30), ("revised_target", 30)):
        cutoff = stages[stage]["knowledge_cutoff"]
        snapshot = materialize_snapshot(journals[stage], _view(at), cutoff)
        assert snapshot.persons == ACTORS and not snapshot.coverage_complete
        assert snapshot.to_dict()["coverage"]["evidence"] == []
    assert history_snapshots["second_history"][-1].coverage_complete
    assert dataset.identity_map_at(28) == {}
    assert dataset.identity_map_at(36) == {"C_alias": "C"}
    intermediate = materialize_snapshot(dataset, _view(10), 29)
    assert not intermediate.coverage_complete
    assert intermediate.to_dict()["population"]["unknown"] == ["C_alias"]

    # The target identity stays canonical at both scoring cutoffs. The newly
    # introduced alias is used only for an older historical wave's correction.
    for at, cutoff in ((20, 28), (20, 41), (30, 40)):
        assert all(record["payload"]["actor"] == actor for actor, record in
                   _behavior_evidence_at(dataset, at, cutoff).items())
    revisions = {record["record_id"]: record for record in dataset.records}
    chain = [revisions[name] for name in (
        "behavior-wave-2-D", "behavior-wave-2-D-before-origin-2", "behavior-wave-2-D-after-origin-2",
    )]
    assert [record["payload"]["value"] for record in chain] == [4, 1, 2]
    assert [record["supersedes"] for record in chain] == [None, chain[0]["record_id"], chain[1]["record_id"]]
    assert {record["fact_id"] for record in chain} == {"behavior-wave-2-D"}
    assert {record["source"]["system"] for record in chain} == {SYSTEM}

    return {
        "stages": stages,
        "verification": {
            "real_ingest_records_used": True,
            "real_materialize_snapshot_used": True,
            "fixed_cutoff_history_snapshot_bytes_unchanged_after_all_appends": True,
            "fixed_cutoff_behavior_evidence_unchanged_after_all_appends": True,
            "history_actor_count": 4,
            "history_wave_counts": [2, 3],
            "behavior_wave_count": 4,
            "complete_network_wave_count_at_final_cutoff": 3,
            "first_target_receipt_network_coverage_complete": False,
            "first_target_network_complete_at_second_history_cutoff": True,
            "second_target_network_coverage_complete": False,
            "primary_previous_scored_target_matches_next_history": False,
            "primary_previous_target_next_history_changed_actor_count": 1,
            "later_target_revision_changed_actor_count": 1,
            "training_designs": designs,
            "rank_method": "exact_rational_determinant_of_three_row_minor",
            "plans_panels_or_manifests_exported": False,
            "predictions_created": False,
            "scores_or_evaluation_reports_computed": False,
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
        "schema": "sociolab.journal-evaluation-fixture.v1",
        "origin": "synthetic",
        "description": "Four invented people, two forecast origins, and two predeclared target-version schedules; all values are manually authored.",
        "stage_order": [name for name, _, _ in STAGES],
        "stages": validation["stages"],
        "input_file_sha256": {name: sha256(raw).hexdigest() for name, raw in encoded.items()},
        "generator_file_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "verification": validation["verification"],
        "expected_downstream_checks": {
            "history_receipt_cutoffs": [24, 36],
            "primary_target_receipt_cutoffs": [28, 40],
            "revised_target_receipt_cutoffs": [41, 40],
            "predeclared_plan_count": 2,
            "forecast_origin_count": 2,
            "actor_forecast_count_per_report": 8,
            "both_plans_saved_before_any_forecast": "to_be_verified_by_separate_case_runner",
            "predictions_saved_before_each_corresponding_target_batch": "to_be_verified_by_separate_case_runner",
            "primary_report_replay_bytes_unchanged_after_receipt_41": "to_be_verified_by_separate_case_runner",
            "same_saved_forecasts_reused_for_both_target_version_plans": "to_be_verified_by_separate_case_runner",
        },
        "scope": {
            "engineering_fixture_only": True,
            "real_data_used": False,
            "receipt_timestamps_are_invented": True,
            "all_fixture_values_known_before_execution": True,
            "target_version_cutoffs_chosen_after_errors": False,
            "target_blinding_demonstrated": False,
            "prospective_validation": False,
            "actor_forecast_rows_independent": False,
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
        "predictions_created": False, "scores_or_evaluation_reports_computed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
