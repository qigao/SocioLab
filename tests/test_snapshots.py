"""Temporal selection and knowledge isolation through the real event importer."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.cli import main
from sociolab.events import EventDataset, ingest_records, load_event_dataset
from sociolab.snapshots import NetworkSnapshot, load_snapshot, load_view, materialize_snapshot, validate_view_spec
from sociolab.affiliations import affiliation_report
from sociolab.changes import compare_snapshots


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "dynamic"
RECEIPT = "2026-11-27T13:00:00Z"


def raw(record_id, kind, payload, *, at=0, interval=None):
    return {"record_id": record_id, "fact_id": record_id, "operation": "assert", "supersedes": None,
            "kind": kind, "occurred_at": at, "valid_interval": interval,
            "source": {"system": "invented-example", "record_id": record_id, "revision": "example-2", "evidence_ref": "synthetic:" + record_id},
            "payload": payload}


def revision(dataset, previous, new_id, *, retract=False, **updates):
    original = next(r for r in dataset.records if r["record_id"] == previous)
    record = {k: v for k, v in original.items() if k not in {"recorded_at", "ingest_seq"}}
    record.update(record_id=new_id, supersedes=previous, operation="retract" if retract else "assert")
    record["source"] = {**record["source"], "record_id": new_id, "revision": "example-2"}
    if retract:
        record["payload"] = None
    record.update(updates)
    return ingest_records(dataset, [record], received_at=RECEIPT)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.dataset = load_event_dataset(EXAMPLES / "events.json")

    def view(self, name, **updates):
        return {**load_view(EXAMPLES / (name + ".view.json"), self.dataset.clock), **updates}

    def snapshot(self, name, dataset=None, cutoff=None, **updates):
        return materialize_snapshot(self.dataset if dataset is None else dataset, self.view(name, **updates), cutoff)

    def test_explicit_relationship_ending_changes_only_the_selected_state_layer(self):
        before = self.snapshot("cooperation-before")
        after = self.snapshot("cooperation-after")
        self.assertTrue(before.coverage_complete)
        self.assertTrue(after.coverage_complete)
        self.assertEqual(before.to_graph().number_of_edges(), 7)
        self.assertEqual(after.to_graph().number_of_edges(), 6)
        report = compare_snapshots(before, after, algorithm="greedy", group_members=["C", "D"])
        self.assertEqual(report["structure"]["before"]["reachable_count"]["A"], 5)
        self.assertEqual(report["structure"]["after"]["reachable_count"]["A"], 2)
        self.assertTrue(report["communities"]["lineage"]["membership_stability"]["same_partition"])
        # The recorded conflict at time 8 and attribute at time 9 did not end the tie.
        self.assertIn(("C", "D"), self.snapshot("cooperation-before", at=9).to_graph().edges())
        conflict = self.snapshot("conflict")
        self.assertEqual(list(conflict.to_graph().edges()), [("C", "D")])
        self.assertTrue(conflict.directed)

    def test_midwindow_departure_preserves_prior_action_and_partial_exposure(self):
        snapshot = self.snapshot("communication")
        self.assertIn("F", snapshot.persons)
        self.assertEqual(snapshot.to_dict()["population"]["exposure"]["F"], 5)
        self.assertEqual(snapshot.to_dict()["edges"], [{"source": "F", "target": "A", "strength": 1, "evidence": ["reply-FA"]}])
        self.assertTrue(snapshot.coverage_complete)
        # Explicit source state at 0 initializes this much later window.
        self.assertEqual(snapshot.to_dict()["population"]["exposure"]["A"], 10)
        self.assertNotIn("F", self.snapshot("cooperation-before", at=26).persons)

    def test_halfopen_windows_and_event_time_correction_with_stable_historical_hash(self):
        self.assertEqual(self.snapshot("communication", start=20, end=22).to_graph().number_of_edges(), 0)
        original = self.snapshot("communication")
        corrected = revision(self.dataset, "reply-FA", "reply-FA-corrected", occurred_at=18)
        current = self.snapshot("communication", dataset=corrected)
        earlier = self.snapshot("communication", dataset=corrected, cutoff=len(self.dataset.records))
        self.assertEqual(current.to_graph().number_of_edges(), 0)
        self.assertEqual(earlier.to_dict(), original.to_dict())
        self.assertEqual(earlier.content_hash, original.content_hash)
        self.assertEqual(self.snapshot("communication", start=22, end=23).to_graph().number_of_edges(), 1)

    def test_identity_and_catalog_added_later_do_not_change_earlier_snapshot(self):
        original = self.snapshot("cooperation-before")
        later = ingest_records(self.dataset, [
            raw("alias-declaration", "entity.observed", {"entity_id": "C-alias", "entity_type": "person"}),
            raw("alias-map", "identity.mapped", {"alias": "C-alias", "canonical": "C"}),
        ], received_at=RECEIPT)
        earlier = self.snapshot("cooperation-before", dataset=later, cutoff=len(self.dataset.records))
        self.assertEqual(earlier.to_dict(), original.to_dict())
        current = self.snapshot("cooperation-before", dataset=later)
        self.assertEqual(current.persons, original.persons)
        self.assertEqual(current.to_dict()["edges"], original.to_dict()["edges"])
        self.assertTrue(current.coverage_complete)

    def test_attribute_only_import_does_not_change_edges(self):
        later = ingest_records(self.dataset, [raw("new-attribute", "actor.attribute.observed", {
            "actor": "C", "name": "self_reported_position", "value": "changed"}, at=4)], received_at=RECEIPT)
        self.assertEqual(self.snapshot("cooperation-before", dataset=later).to_dict()["edges"],
                         self.snapshot("cooperation-before").to_dict()["edges"])

    def test_activity_projection_and_cancellation_revision(self):
        original = self.snapshot("participation")
        report = affiliation_report(original.to_graph(), original.persons, projection="newman")
        self.assertEqual(report["incidence_count"], 6)
        self.assertEqual(report["projected_edge_count"], 15)
        self.assertTrue(all(e["strength"] == 0.2 and e["activities"] == ["workshop"] for e in report["projected_edges"]))
        cancelled = revision(self.dataset, "workshop-description", "workshop-cancelled", payload={
            "activity": "workshop", "status": "cancelled", "activity_type": "workshop"})
        with self.assertRaisesRegex(ValueError, "cancelled activity"):
            self.snapshot("participation", dataset=cancelled)
        for actor in "ABCDEF":
            cancelled = revision(cancelled, "attendance-" + actor, "attendance-withdrawn-" + actor, retract=True)
        current = self.snapshot("participation", dataset=cancelled)
        self.assertEqual(current.to_graph().number_of_edges(), 0)
        self.assertEqual(current.persons, original.persons)
        self.assertEqual(self.snapshot("participation", dataset=cancelled, cutoff=len(self.dataset.records)).to_dict(), original.to_dict())

    def test_overlapping_absence_and_attendance_require_correction(self):
        absent = raw("absence-A", "participation.observed", {
            "actor": "A", "activity": "workshop", "role": "participant", "status": "absent"}, at=5)
        conflicting = ingest_records(self.dataset, [absent], received_at=RECEIPT)
        with self.assertRaisesRegex(ValueError, "conflicting attended/absent"):
            self.snapshot("participation", dataset=conflicting)
        absent["occurred_at"] = 7
        disjoint = ingest_records(self.dataset, [absent], received_at=RECEIPT)
        self.assertEqual(self.snapshot("participation", dataset=disjoint).to_graph().number_of_edges(), 6)

    def test_attendance_duration_is_clipped_to_membership_and_window(self):
        earlier_departure = revision(self.dataset, "leave-F", "leave-F-earlier", occurred_at=5)
        overlapping = self.snapshot("participation", dataset=earlier_departure)
        self.assertIn(("F", "workshop"), overlapping.to_graph().edges())
        self.assertEqual(overlapping.to_dict()["population"]["exposure"]["F"], 1)
        after = self.snapshot("participation", dataset=earlier_departure, start=5, end=6)
        self.assertNotIn("F", after.persons)
        self.assertEqual(after.to_graph().number_of_edges(), 5)

    def test_point_activity_cannot_be_silently_extended_to_duration(self):
        point = revision(self.dataset, "workshop-description", "workshop-point", valid_interval=None)
        with self.assertRaisesRegex(ValueError, "point-only activity"):
            self.snapshot("participation", dataset=point)

    def test_point_relation_observation_does_not_persist(self):
        dataset = ingest_records(self.dataset, [raw("point-trust", "relation.observed", {
            "layer": "trust", "source": "A", "target": "B", "directed": True, "strength": 0.7}, at=2)], received_at=RECEIPT)
        at = self.snapshot("cooperation-before", dataset=dataset, layer="trust", directed=True, at=2)
        later = self.snapshot("cooperation-before", dataset=dataset, layer="trust", directed=True, at=3)
        self.assertEqual(at.to_graph().number_of_edges(), 1)
        self.assertEqual(later.to_graph().number_of_edges(), 0)
        self.assertFalse(at.coverage_complete)  # no trust-specific coverage was asserted

    def test_unknown_membership_is_not_absence_or_zero(self):
        missing = revision(self.dataset, "join-A", "join-A-withdrawn", retract=True)
        snapshot = self.snapshot("cooperation-before", dataset=missing)
        self.assertEqual(snapshot.to_dict()["population"]["unknown"], ["A"])
        self.assertNotIn("A", snapshot.to_dict()["population"]["absent"])
        self.assertFalse(snapshot.coverage_complete)
        with self.assertRaisesRegex(ValueError, "complete declared coverage"):
            snapshot.require_complete()

    def test_partial_observation_retains_positive_evidence_but_blocks_comparison(self):
        partial = revision(self.dataset, "coverage-communication", "coverage-communication-partial", payload={
            "population": "team", "layer": "communication", "actors": list("ABCDEF"), "status": "partial"})
        snapshot = self.snapshot("communication", dataset=partial)
        self.assertEqual(snapshot.to_graph().number_of_edges(), 1)
        self.assertFalse(snapshot.coverage_complete)
        with self.assertRaises(ValueError):
            compare_snapshots(self.snapshot("communication"), snapshot)

    def test_explicit_unobserved_coverage_conflicts_with_recorded_evidence(self):
        unavailable = revision(self.dataset, "coverage-communication", "coverage-communication-unobserved", payload={
            "population": "team", "layer": "communication", "actors": list("ABCDEF"), "status": "unobserved"})
        with self.assertRaisesRegex(ValueError, "unobserved coverage contradicts"):
            self.snapshot("communication", dataset=unavailable)
        # An absent declaration is different: keep known positives with unknown coverage.
        missing = revision(self.dataset, "coverage-communication", "coverage-communication-withdrawn", retract=True)
        snapshot = self.snapshot("communication", dataset=missing)
        self.assertEqual(snapshot.to_graph().number_of_edges(), 1)
        self.assertFalse(snapshot.coverage_complete)

    def test_conflicting_simultaneous_state_does_not_use_receipt_order(self):
        conflicting = ingest_records(self.dataset, [raw("contradict-A", "membership.changed", {
            "actor": "A", "population": "team", "status": "absent"})], received_at=RECEIPT)
        with self.assertRaisesRegex(ValueError, "conflicting membership"):
            self.snapshot("cooperation-before", dataset=conflicting)

    def test_pre_epoch_utc_unknown_membership_keeps_exact_signed_time(self):
        empty = EventDataset.from_mapping({"schema": "sociolab.events.v1", "dataset_id": "historical",
            "origin": "synthetic", "source_revision": "1", "clock": {"kind": "utc"}, "records": []})
        dataset = ingest_records(empty, [raw("p", "entity.observed", {"entity_id": "A", "entity_type": "person"}, at="1960-01-01T00:00:00Z")], received_at=RECEIPT)
        view = {"schema": "sociolab.view.v1", "population": "team", "layer": "communication", "mode": "events",
                "directed": True, "start": "1960-01-01T00:00:00Z", "end": "1960-01-02T00:00:00Z", "actions": ["reply"]}
        snapshot = materialize_snapshot(dataset, view)
        interval = snapshot.to_dict()["population"]["unknown_intervals"]["A"][0]
        self.assertLess(interval[0], 0)
        self.assertEqual(interval[1] - interval[0], 86_400_000_000)
        self.assertFalse(snapshot.coverage_complete)

    def test_snapshot_roundtrip_hash_and_defensive_public_graph(self):
        snapshot = self.snapshot("cooperation-before")
        data = snapshot.to_dict()
        self.assertEqual(NetworkSnapshot.from_mapping(data).content_hash, snapshot.content_hash)
        snapshot.to_graph().remove_node("A")
        snapshot.to_dict()["persons"].remove("A")
        self.assertIn("A", snapshot.persons)
        data["edges"][0]["strength"] = 2
        with self.assertRaisesRegex(ValueError, "content hash"):
            NetworkSnapshot.from_mapping(data)
        for field in ("content_hash", "policy_hash"):
            bad = snapshot.to_dict()
            bad[field] = None
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "non-null SHA-256"):
                NetworkSnapshot.from_mapping(bad)

    def test_malformed_view_and_snapshot_types_fail_explicitly(self):
        for field, bad_value in (("mode", []), ("directed", 1), ("actions", "reply"), ("at", True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_view_spec(self.view("cooperation-before", **{field: bad_value}), self.dataset.clock)
        for field, bad_value in (("origin", []), ("clock", [])):
            data = self.snapshot("cooperation-before").to_dict()
            data["dataset"][field] = bad_value
            with self.subTest(field=field), self.assertRaises(ValueError):
                NetworkSnapshot.from_mapping(data)

        for value in (True, float("nan"), float("inf"), 10 ** 400, -1):
            data = self.snapshot("cooperation-before").to_dict()
            data["edges"][0]["strength"] = value
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                NetworkSnapshot.from_mapping(data)

    def test_complete_serialized_coverage_requires_effective_typed_evidence(self):
        for evidence in ([], ["join-A"], ["coverage-communication"]):
            data = self.snapshot("cooperation-before").to_dict()
            data.pop("content_hash")
            data["coverage"]["evidence"] = evidence
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, "coverage evidence"):
                NetworkSnapshot.create(data)

    def test_cli_executes_import_snapshot_analysis_and_change_pipeline(self):
        def run(args):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(args), 0)
            return json.loads(output.getvalue())
        self.assertTrue(run(["events", "validate", str(EXAMPLES / "events.json")])["valid"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("cooperation-before", "cooperation-after", "participation"):
                report = run(["snapshot", str(EXAMPLES / "events.json"), str(EXAMPLES / (name + ".view.json"))])
                (root / (name + ".json")).write_text(json.dumps(report), encoding="utf-8")
            before, after = str(root / "cooperation-before.json"), str(root / "cooperation-after.json")
            self.assertEqual(load_snapshot(before).to_graph().number_of_edges(), 7)
            self.assertEqual(run(["communities", "analyze", before])["community_count"], 2)
            selected = run(["keyplayers", "select", before, "--size", "2"])
            self.assertAlmostEqual(selected["score"], 2 / 3)
            self.assertEqual(run(["keyplayers", "score", after, "--members", "C", "D"])["score"], 0)
            self.assertEqual(run(["affiliations", "analyze", str(root / "participation.json"), "--projection", "newman"])["projected_edge_count"], 15)
            changed = run(["changes", before, after, "--algorithm", "greedy", "--group-members", "C", "D"])
            self.assertEqual(changed["kind"], "DESCRIPTIVE_NETWORK_CHANGE")
            self.assertEqual(changed["structure"]["after"]["component_count"], 2)
            self.assertTrue(run(["communities", "compare", before, after])["communities"]["lineage"]["membership_stability"]["same_partition"])
            empty = run(["events", "init", "--dataset-id", "new", "--origin", "synthetic", "--source-revision", "1", "--clock", "ticks", "--run-id", "run"])
            (root / "empty.json").write_text(json.dumps(empty), encoding="utf-8")
            (root / "batch.json").write_text(json.dumps([raw("p", "entity.observed", {"entity_id": "A", "entity_type": "person"})]), encoding="utf-8")
            imported = run(["events", "import", str(root / "empty.json"), str(root / "batch.json"), "--received-at", RECEIPT])
            self.assertEqual(imported["records"][0]["ingest_seq"], 1)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["keyplayers", "select", after])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
