"""Immutable tracking semantics through original ingestion and snapshot APIs."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.changes import compare_snapshots
from sociolab.events import EventDataset, ingest_records, load_event_dataset
from sociolab.network_tracking import (
    initialize_network_tracking, apply_network_tracking_batch, validate_network_tracking_state,
)
from sociolab.snapshots import NetworkSnapshot, content_hash, load_view, materialize_snapshot
from test_journal_forecast import ACTORS, ALIAS, LATER, fixture, observation, raw


def registration(*times):
    return {"schema": "sociolab.network-tracking-spec.v1", "views": [
        {"view_id": f"friendship-at-{time}", "view": {
            "schema": "sociolab.view.v1", "population": "cohort", "layer": "friendship",
            "mode": "state", "directed": True, "at": time,
        }, "analysis": {}} for time in (times or (0, 10))
    ]}


def initial_state(*times):
    dataset, _ = fixture()
    return initialize_network_tracking(dataset, registration(*times))


def revision_record(state, old_id, new_id, *, retract=False, **updates):
    old = next(record for record in state["dataset"]["records"] if record["record_id"] == old_id)
    record = deepcopy({key: value for key, value in old.items() if key not in {"recorded_at", "ingest_seq"}})
    record.update(record_id=new_id, supersedes=old_id, operation="retract" if retract else "assert")
    record["source"] = {**record["source"], "record_id": new_id, "revision": "corrected"}
    if retract:
        record["payload"] = None
    record.update(deepcopy(updates))
    return record


def rehash(state):
    state["content_hash"] = content_hash({key: value for key, value in state.items() if key != "content_hash"})
    return state


def population_dataset(count, *, participation=False):
    actors = [f"person-{index:03}" for index in range(count)]
    dataset = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "bounded-tracking-fixture", "origin": "synthetic",
        "source_revision": "fixed-envelope", "clock": {"kind": "ticks", "run_id": "tracking-fixture"}, "records": [],
    })
    records = [raw("declare-" + actor, "entity.observed", {"entity_id": actor, "entity_type": "person"}) for actor in actors]
    records.extend(raw("member-" + actor, "membership.observed", {
        "actor": actor, "population": "cohort", "status": "present"}, interval=[0, None]) for actor in actors)
    layer = "participation" if participation else "friendship"
    records.append(raw("coverage", "coverage.observed", {"population": "cohort", "layer": layer, "actors": actors, "status": "complete"}, interval=[0, None]))
    if participation:
        records.extend([
            raw("declare-activity", "entity.observed", {"entity_id": "meeting", "entity_type": "activity"}),
            raw("held-activity", "activity.observed", {"activity": "meeting", "activity_type": "invented", "status": "held"}, at=1),
        ])
        records.extend(raw("attend-" + actor, "participation.observed", {
            "actor": actor, "activity": "meeting", "role": "participant", "status": "attended"}, at=1) for actor in actors)
    return ingest_records(dataset, records, received_at=LATER), actors


class NetworkTrackingTests(unittest.TestCase):
    def test_initialization_normalizes_registration_and_replays_retained_snapshots(self):
        dataset, _ = fixture()
        registered = registration(0, 10)
        before_registration = deepcopy(registered)
        state = initialize_network_tracking(dataset, registered)
        self.assertEqual(registered, before_registration)
        self.assertEqual(state["sequence"], 0)
        self.assertIsNone(state["previous_state_hash"])
        self.assertEqual(state["knowledge_cutoff"], len(dataset.records))
        self.assertEqual(state["registration"]["views"][0]["analysis"]["algorithm"], "greedy")
        self.assertEqual(state["registration_hash"], content_hash(state["registration"]))
        with patch("sociolab.network_tracking.materialize_snapshot", wraps=materialize_snapshot) as materializer:
            validated = validate_network_tracking_state(state)
        self.assertEqual(materializer.call_count, 2)
        self.assertEqual(validated, state)
        self.assertIsNot(validated, state)
        self.assertIsNot(validated["dataset"], state["dataset"])
        registered["views"][0]["view"]["at"] = 100
        self.assertEqual(state["registration"]["views"][0]["view"]["at"], 0)

    def test_unrelated_receipt_creates_new_checkpoint_without_false_network_or_evidence_change(self):
        state = initial_state()
        before = deepcopy(state)
        batch = [observation("unrelated", ACTORS[0], "new note", 5, name="untracked_attribute")]
        with patch("sociolab.network_tracking.materialize_snapshot", wraps=materialize_snapshot) as materializer, \
                patch("sociolab.network_tracking.compare_snapshots", wraps=compare_snapshots) as compare:
            result = apply_network_tracking_batch(state, batch, received_at=LATER)
        self.assertEqual(state, before)
        self.assertEqual(materializer.call_count, 4)  # replay two old, reconstruct two new
        compare.assert_not_called()
        self.assertEqual(result["state"]["sequence"], 1)
        self.assertEqual(result["state"]["previous_state_hash"], state["content_hash"])
        self.assertEqual(result["state"]["knowledge_cutoff"], state["knowledge_cutoff"] + 1)
        self.assertEqual(result["transition"]["status"], "APPLIED")
        self.assertEqual(result["transition"]["source"]["appended_record_count"], 1)
        for view in result["transition"]["views"]:
            self.assertNotEqual(view["before_snapshot_hash"], view["after_snapshot_hash"])
            for flag in ("observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed"):
                self.assertFalse(view[flag])
            self.assertEqual(view["comparison"], {"status": "NOT_RUN", "reason": "no_observable_change"})

    def test_equal_strength_revision_changes_evidence_without_graph_change(self):
        state = initial_state()
        record = revision_record(state, "tie-AB", "tie-AB-same-value")
        record["payload"]["strength"] = 1.0
        with patch("sociolab.network_tracking.compare_snapshots", wraps=compare_snapshots) as compare:
            result = apply_network_tracking_batch(state, [record], received_at=LATER)
        compare.assert_not_called()
        first, second = result["transition"]["views"]
        self.assertFalse(first["observed_graph_changed"])
        self.assertTrue(first["evidence_changed"])
        self.assertFalse(second["observed_graph_changed"])
        self.assertFalse(second["evidence_changed"])
        self.assertEqual(first["before_fingerprints"]["graph"], first["after_fingerprints"]["graph"])
        self.assertEqual(result["transition"]["source"]["revised_assertion_count"], 1)

    def test_late_corrected_event_time_or_endpoint_uses_real_comparison_and_keeps_old_version(self):
        for update in ("time", "endpoint"):
            with self.subTest(update=update):
                state = initial_state()
                before = deepcopy(state)
                record = revision_record(state, "tie-AB", "tie-AB-corrected")
                if update == "time":
                    record["occurred_at"] = 5
                else:
                    record["payload"]["target"] = ACTORS[2]
                with patch("sociolab.network_tracking.compare_snapshots", wraps=compare_snapshots) as compare:
                    result = apply_network_tracking_batch(state, [record], received_at=LATER)
                self.assertEqual(state, before)
                self.assertEqual(compare.call_count, 1)
                first, second = result["transition"]["views"]
                self.assertTrue(first["observed_graph_changed"])
                self.assertEqual(first["comparison"]["status"], "OK")
                self.assertEqual(first["comparison"]["report"]["engine"], "networkx")
                self.assertEqual(len(first["comparison"]["report"]["relations"]["removed"]), 1)
                self.assertFalse(second["observed_graph_changed"])
                self.assertEqual(result["transition"]["before_state_hash"], before["content_hash"])
                self.assertEqual(result["transition"]["after_state_hash"], result["state"]["content_hash"])

    def test_retraction_is_separate_from_receipt_availability_and_old_graph_stays_intact(self):
        state = initial_state(0)
        original_edges = deepcopy(state["views"][0]["snapshot"]["edges"])
        result = apply_network_tracking_batch(state, [revision_record(state, "tie-AB", "tie-AB-retracted", retract=True)], received_at=LATER)
        self.assertEqual(result["transition"]["source"]["retraction_count"], 1)
        report = result["transition"]["views"][0]["comparison"]["report"]
        self.assertEqual(len(report["source_changes"]["retracted_records"]), 1)
        self.assertEqual(report["source_changes"]["records_only_before"], [])
        self.assertEqual(state["views"][0]["snapshot"]["edges"], original_edges)
        self.assertEqual(len(result["state"]["views"][0]["snapshot"]["edges"]), len(original_edges) - 1)

    def test_unknown_membership_and_recovery_use_the_immediate_predecessor(self):
        original = initial_state(0)
        with patch("sociolab.network_tracking.compare_snapshots", wraps=compare_snapshots) as compare:
            unknown = apply_network_tracking_batch(original, [raw("new-person", "entity.observed", {
                "entity_id": "new-person", "entity_type": "person"})], received_at=LATER)
            recovered = apply_network_tracking_batch(unknown["state"], [raw("known-absence", "membership.observed", {
                "actor": "new-person", "population": "cohort", "status": "absent"}, interval=[0, None])], received_at=LATER)
        compare.assert_not_called()
        first = unknown["transition"]["views"][0]
        self.assertFalse(first["observed_graph_changed"])
        self.assertTrue(first["population_changed"])
        self.assertTrue(first["coverage_changed"])
        self.assertTrue(first["before_complete"])
        self.assertFalse(first["after_complete"])
        second = recovered["transition"]["views"][0]
        self.assertFalse(second["before_complete"])
        self.assertTrue(second["after_complete"])
        self.assertEqual(second["before_snapshot_hash"], unknown["state"]["views"][0]["snapshot"]["content_hash"])
        self.assertEqual(second["comparison"], {"status": "NOT_RUN", "reason": "incomplete_before_or_after_coverage"})

    def test_coverage_change_is_not_reported_as_a_graph_change(self):
        state = initial_state(0)
        record = revision_record(state, "coverage", "partial-coverage")
        record["payload"]["status"] = "partial"
        result = apply_network_tracking_batch(state, [record], received_at=LATER)
        view = result["transition"]["views"][0]
        self.assertFalse(view["observed_graph_changed"])
        self.assertFalse(view["population_changed"])
        self.assertTrue(view["coverage_changed"])
        self.assertTrue(view["evidence_changed"])
        self.assertEqual(view["comparison"]["reason"], "incomplete_before_or_after_coverage")

    def test_alias_correction_changes_resolved_network_without_mutating_prior_snapshot(self):
        dataset, _ = fixture()
        value = dataset.to_dict()
        next(record for record in value["records"] if record["record_id"] == "tie-AB")["payload"]["source"] = ALIAS
        state = initialize_network_tracking(EventDataset.from_mapping(value), registration(0))
        original = deepcopy(state)
        mapping = revision_record(state, "identity-A", "identity-A-corrected", payload={"alias": ALIAS, "canonical": ACTORS[3]})
        result = apply_network_tracking_batch(state, [mapping], received_at=LATER)
        self.assertTrue(result["transition"]["views"][0]["observed_graph_changed"])
        self.assertEqual(state, original)
        edges = result["state"]["views"][0]["snapshot"]["edges"]
        self.assertIn((ACTORS[3], ACTORS[1]), [(edge["source"], edge["target"]) for edge in edges])

    def test_empty_and_duplicate_batches_preserve_exact_state_and_mixed_retry_replays_from_new_tail(self):
        state = initial_state(0)
        duplicate = {key: value for key, value in state["dataset"]["records"][0].items() if key not in {"recorded_at", "ingest_seq"}}
        for batch in ([], [duplicate], [duplicate, deepcopy(duplicate)]):
            result = apply_network_tracking_batch(state, batch, received_at=LATER)
            self.assertEqual(json.dumps(result["state"], sort_keys=True), json.dumps(state, sort_keys=True))
            self.assertEqual(result["transition"]["status"], "NO_NEW_RECORDS")
            self.assertEqual(result["transition"]["before_state_hash"], result["transition"]["after_state_hash"])
            self.assertEqual(result["transition"]["source"]["appended_record_count"], 0)
        fresh = observation("fresh-untracked", ACTORS[0], 1, 5, name="not_the_network")
        mixed = apply_network_tracking_batch(state, [duplicate, fresh, deepcopy(duplicate)], received_at=LATER)
        replayed = apply_network_tracking_batch(state, [fresh], received_at=LATER)
        self.assertEqual(mixed, replayed)
        self.assertEqual(mixed["transition"]["source"]["record_ids"], ["fresh-untracked"])

    def test_ingestion_materialization_and_analysis_errors_leave_inputs_unchanged(self):
        state = initial_state(0)
        original = deepcopy(state)
        reused = {key: value for key, value in state["dataset"]["records"][0].items() if key not in {"recorded_at", "ingest_seq"}}
        reused["source"] = {**reused["source"], "revision": "different-content"}
        conflict = raw("conflicting-tie", "relation.changed", {
            "layer": "friendship", "source": ACTORS[0], "target": ACTORS[1], "directed": True, "strength": 2})
        for batch, receipt in (([reused], LATER), ([conflict], LATER),
                               ([observation("early-receipt", ACTORS[0], 1, 5)], "2025-01-01T00:00:00Z")):
            with self.assertRaises(ValueError):
                apply_network_tracking_batch(state, batch, received_at=receipt)
            self.assertEqual(state, original)
        correction = revision_record(state, "tie-AB", "new-time", occurred_at=5)
        with patch("sociolab.network_tracking.compare_snapshots", side_effect=RuntimeError("upstream failure")):
            with self.assertRaisesRegex(RuntimeError, "upstream failure"):
                apply_network_tracking_batch(state, [correction], received_at=LATER)
        self.assertEqual(state, original)

    def test_hash_valid_derived_snapshot_tampering_fails_real_source_replay(self):
        state = initial_state(0)
        edited = deepcopy(state)
        snapshot = edited["views"][0]["snapshot"]
        snapshot.pop("content_hash")
        snapshot["edges"][0]["strength"] = 2
        edited["views"][0]["snapshot"] = NetworkSnapshot.create(snapshot).to_dict()
        rehash(edited)
        with self.assertRaisesRegex(ValueError, "does not match replay"):
            validate_network_tracking_state(edited)
        edited = deepcopy(state)
        edited["registration"]["views"][0]["view"]["at"] = 1
        edited["registration_hash"] = content_hash(edited["registration"])
        rehash(edited)
        with self.assertRaisesRegex(ValueError, "does not match replay"):
            validate_network_tracking_state(edited)
        edited = deepcopy(state)
        edited["views"][0]["fingerprints"]["graph"] = "sha256:" + "a" * 64
        rehash(edited)
        with self.assertRaisesRegex(ValueError, "fingerprints"):
            validate_network_tracking_state(edited)

    def test_whole_analysis_node_budget_is_independent_of_group_selection_settings(self):
        dataset, actors = population_dataset(201)
        registered = registration(0)
        registered["views"][0]["analysis"] = {"max_nodes": 10000, "max_edges": 100000}
        state = initialize_network_tracking(dataset, registered)
        added = raw("edge", "relation.changed", {"layer": "friendship", "source": actors[0], "target": actors[1], "directed": True, "strength": 1})
        with patch("sociolab.network_tracking.compare_snapshots", side_effect=AssertionError("hard budget must precede graph analysis")):
            result = apply_network_tracking_batch(state, [added], received_at=LATER)
        self.assertEqual(result["transition"]["views"][0]["comparison"], {"status": "NOT_RUN", "reason": "analysis_budget_exceeded"})
        self.assertEqual(len(result["state"]["views"][0]["snapshot"]["persons"]), 201)

    def test_dense_upstream_projection_obeys_the_whole_analysis_edge_budget(self):
        dataset, actors = population_dataset(67, participation=True)
        registered = {"schema": "sociolab.network-tracking-spec.v1", "views": [{
            "view_id": "attendance", "view": {"schema": "sociolab.view.v1", "population": "cohort",
                "layer": "participation", "mode": "participation", "directed": False, "start": 0, "end": 10},
            "analysis": {"projection": "count"},
        }]}
        state = initialize_network_tracking(dataset, registered)
        correction = revision_record(state, "attend-" + actors[-1], "attendance-retracted", retract=True)
        from sociolab.affiliations import affiliation_report
        with patch("sociolab.network_tracking.affiliation_report", wraps=affiliation_report) as projection, \
                patch("sociolab.network_tracking.compare_snapshots", side_effect=AssertionError("dense projection cannot reach graph analysis")):
            result = apply_network_tracking_batch(state, [correction], received_at=LATER)
        self.assertGreaterEqual(projection.call_count, 1)
        self.assertEqual(result["transition"]["views"][0]["comparison"], {"status": "NOT_RUN", "reason": "analysis_budget_exceeded"})
        self.assertEqual(len(state["views"][0]["snapshot"]["edges"]), 67)
        self.assertEqual(len(result["state"]["views"][0]["snapshot"]["edges"]), 66)

    def test_annotation_summary_is_retained_as_unqualified_evidence(self):
        examples = Path(__file__).resolve().parents[1] / "examples" / "annotations"
        dataset = load_event_dataset(examples / "events.json")
        view = load_view(examples / "conflict-before.view.json", dataset.clock)
        state = initialize_network_tracking(dataset, {"schema": "sociolab.network-tracking-spec.v1", "views": [{
            "view_id": "source-coded-labels", "view": view, "analysis": {},
        }]})
        updated = revision_record(state, "human-m1", "human-m1-reconfirmed")
        result = apply_network_tracking_batch(state, [updated], received_at="2026-11-28T00:00:00Z")
        change = result["transition"]["views"][0]
        self.assertTrue(change["evidence_changed"])
        self.assertFalse(change["observed_graph_changed"])
        summary = result["state"]["views"][0]["snapshot"]["annotation_summary"]
        self.assertFalse(summary["automatic_annotation_qualified"])
        self.assertEqual(summary["measurement_status"], "UNVALIDATED_SOURCE_LABELS")
        self.assertFalse(result["transition"]["scope"]["automatic_annotation_qualified"])

    def test_registration_and_checkpoint_contracts_are_strict(self):
        dataset, _ = fixture()
        invalid_registrations = []
        for mutate in (
            lambda value: value.update(extra=True),
            lambda value: value.update(views=[]),
            lambda value: value.update(views=value["views"] * 9),
            lambda value: value["views"][1].update(view_id=value["views"][0]["view_id"]),
            lambda value: value["views"][0]["analysis"].update(seed=True),
            lambda value: value["views"][0]["analysis"].update(resolution=float("inf")),
            lambda value: value["views"][0]["analysis"].update(projection="count"),
            lambda value: value["views"][0]["analysis"].update(extra=True),
            lambda value: value["views"][0]["analysis"].update(group_members=["A", "A"]),
            lambda value: value["views"][0]["analysis"].update(group_members=["A"], group_size=2),
        ):
            value = registration()
            mutate(value)
            invalid_registrations.append(value)
        for value in invalid_registrations:
            with self.assertRaises(ValueError):
                initialize_network_tracking(dataset, value)
        state = initial_state(0)
        for mutate in (
            lambda value: value.update(extra=True),
            lambda value: value.update(sequence=True),
            lambda value: value.update(previous_state_hash="sha256:" + "a" * 64),
            lambda value: value.update(knowledge_cutoff=value["knowledge_cutoff"] - 1),
            lambda value: value["scope"].update(causal_effect_identified=True),
            lambda value: value["scope"].update(receipt_driven=1),
            lambda value: value["views"][0].update(view_id="unregistered"),
        ):
            changed = deepcopy(state)
            mutate(changed)
            rehash(changed)
            with self.assertRaises(ValueError):
                validate_network_tracking_state(changed)
        with self.assertRaises(TypeError):
            initialize_network_tracking(dataset.to_dict(), registration())


if __name__ == "__main__":
    unittest.main()
