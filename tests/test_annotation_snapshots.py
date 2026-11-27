"""Real event → annotation → derived snapshot and CLI integration."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.annotations import annotation_report
from sociolab.changes import compare_snapshots
from sociolab.cli import main
from sociolab.events import ingest_records, load_event_dataset
from sociolab.snapshots import NetworkSnapshot, load_view, materialize_snapshot, validate_view_spec


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "annotations"
RECEIPT = "2026-11-27T15:00:00Z"


def source_record(dataset, record_id):
    return next(r for r in dataset.records if r["record_id"] == record_id)


def revise(dataset, previous, new_id, *, retract=False, new_fact=False, **updates):
    original = source_record(dataset, previous)
    record = {k: v for k, v in original.items() if k not in {"recorded_at", "ingest_seq"}}
    record.update(record_id=new_id, supersedes=None if new_fact else previous,
                  operation="retract" if retract else "assert")
    if new_fact:
        record["fact_id"] = new_id
    if retract:
        record["payload"] = None
    record["source"] = {**record["source"], "record_id": new_id, "revision": "example-2"}
    record.update(updates)
    return ingest_records(dataset, [record], received_at=RECEIPT)


class AnnotationSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.dataset = load_event_dataset(EXAMPLES / "events.json")

    def view(self, name="conflict-before", **updates):
        return {**load_view(EXAMPLES / (name + ".view.json"), self.dataset.clock), **updates}

    def snapshot(self, name="conflict-before", dataset=None, cutoff=None, **updates):
        return materialize_snapshot(self.dataset if dataset is None else dataset, self.view(name, **updates), cutoff)

    def test_source_event_time_and_single_method_define_the_derived_count(self):
        snapshot = self.snapshot()
        data = snapshot.to_dict()
        self.assertTrue(snapshot.coverage_complete)
        self.assertEqual(data["weight_semantics"], "annotation_count")
        self.assertEqual(data["edges"], [{"source": "B", "target": "A", "strength": 1,
                                         "evidence": ["content-m2", "human-m2", "m2"]}])
        self.assertEqual(data["annotation_summary"]["counts"], {
            "source_events": 4, "resolved": 4, "unresolved": 0, "projected_events": 1, "topic_decisions": 1})
        self.assertEqual(source_record(self.dataset, "human-m2")["occurred_at"], 50)
        self.assertFalse(data["annotation_summary"]["automatic_annotation_qualified"])
        # Human and model both annotate m2; selecting one method counts it once.
        self.assertEqual(annotation_report(self.dataset)["summary"]["active_annotation_count"], 11)

    def test_topic_disagreement_does_not_become_person_edge(self):
        snapshot = self.snapshot("disagreement")
        self.assertTrue(snapshot.coverage_complete)
        self.assertEqual(snapshot.to_graph().number_of_edges(), 0)
        row = next(r for r in snapshot.to_dict()["annotation_summary"]["decisions"] if r["interaction_record_id"] == "m1")
        self.assertEqual(row["subject"], {"kind": "topic", "id": "proposal-P"})
        self.assertEqual(row["outcome"], "topic")
        self.assertIsNone(row["subject_eligible_at_event"])

    def test_uncertain_labels_remain_unresolved_even_when_label_topic_filtered(self):
        snapshot = self.snapshot("model-disagreement", topics=["proposal-P"])
        data = snapshot.to_dict()
        self.assertFalse(snapshot.coverage_complete)
        self.assertTrue(data["annotation_summary"]["source_coverage_complete"])
        self.assertEqual(data["annotation_summary"]["unresolved"][0]["reason"], "uncertain")
        self.assertEqual(data["annotation_summary"]["unresolved"][0]["interaction_record_id"], "m4")
        self.assertEqual(data["edges"][0]["source"], "A")
        self.assertEqual(data["edges"][0]["target"], "B")
        with self.assertRaises(ValueError):
            snapshot.require_complete()

    def test_resolved_external_labels_remain_unqualified_measurements(self):
        payload = source_record(self.dataset, "model-m4")["payload"]
        payload["label"] = "neutral"
        resolved = revise(self.dataset, "model-m4", "model-m4-resolved", payload=payload)
        snapshot = self.snapshot("model-disagreement", dataset=resolved)
        self.assertTrue(snapshot.coverage_complete)
        summary = snapshot.to_dict()["annotation_summary"]
        self.assertEqual(summary["measurement_status"], "UNVALIDATED_SOURCE_LABELS")
        self.assertFalse(summary["automatic_annotation_qualified"])
        self.assertEqual(snapshot.to_graph().number_of_edges(), 1)  # labels describe a claim, not verified hostility

    def test_missing_annotation_blocks_completeness_including_neutral_items(self):
        missing = revise(self.dataset, "human-m4", "human-m4-withdrawn", retract=True)
        snapshot = self.snapshot(dataset=missing)
        self.assertFalse(snapshot.coverage_complete)
        unresolved = snapshot.to_dict()["annotation_summary"]["unresolved"]
        self.assertEqual(unresolved[0]["reason"], "missing_annotation")
        self.assertEqual(unresolved[0]["interaction_record_id"], "m4")
        self.assertEqual(snapshot.to_graph().number_of_edges(), 1)

    def test_missing_content_is_not_a_zero_label(self):
        missing = revise(self.dataset, "content-m4", "content-m4-withdrawn", retract=True)
        snapshot = self.snapshot(dataset=missing)
        self.assertFalse(snapshot.coverage_complete)
        self.assertEqual(snapshot.to_dict()["annotation_summary"]["unresolved"][0]["reason"], "missing_content")
        historical = self.snapshot(dataset=missing, cutoff=len(self.dataset.records))
        self.assertEqual(historical.to_dict(), self.snapshot().to_dict())

    def test_identical_hash_new_content_requires_exact_reconfirmation(self):
        original = self.snapshot()
        corrected = revise(self.dataset, "content-m2", "content-m2-corrected")
        stale = self.snapshot(dataset=corrected)
        self.assertFalse(stale.coverage_complete)
        self.assertEqual(stale.to_graph().number_of_edges(), 0)
        self.assertEqual(stale.to_dict()["annotation_summary"]["unresolved"][0]["reason"], "stale_annotation")
        self.assertEqual(self.snapshot(dataset=corrected, cutoff=len(self.dataset.records)).to_dict(), original.to_dict())
        payload = source_record(corrected, "human-m2")["payload"]
        payload["target_record_id"] = "content-m2-corrected"
        reconfirmed = revise(corrected, "human-m2", "human-m2-reconfirmed", payload=payload)
        current = self.snapshot(dataset=reconfirmed)
        self.assertTrue(current.coverage_complete)
        self.assertEqual(current.to_graph().number_of_edges(), 1)
        # The other method still has a stale historical issue; that cannot block this repaired method.
        self.assertGreater(annotation_report(reconfirmed)["summary"]["content_issue_count"], 0)
        changed = compare_snapshots(original, current)
        self.assertEqual(changed["relations"]["removed"], [])
        self.assertEqual(changed["relations"]["added"], [])
        self.assertEqual(len(changed["relations"]["evidence_changed"]), 1)

    def test_interaction_correction_updates_window_eligibility_without_label_transfer(self):
        later = revise(self.dataset, "m2", "m2-corrected", occurred_at=14)
        earlier_window = self.snapshot(dataset=later)
        self.assertTrue(earlier_window.coverage_complete)  # all three remaining source events are classified
        self.assertEqual(earlier_window.to_graph().number_of_edges(), 0)
        later_window = self.snapshot("conflict-after", dataset=later)
        self.assertFalse(later_window.coverage_complete)
        self.assertIn("m2-corrected", later_window.to_dict()["annotation_summary"]["source_event_ids"])
        self.assertEqual(later_window.to_dict()["annotation_summary"]["unresolved"][0]["reason"], "missing_content")
        self.assertEqual(self.snapshot(dataset=later, cutoff=len(self.dataset.records)).content_hash, self.snapshot().content_hash)

    def test_same_method_duplicate_decisions_and_duplicate_content_are_ambiguous(self):
        for previous, expected in (("human-m2", "ambiguous_annotation"), ("content-m2", "ambiguous_content")):
            duplicated = revise(self.dataset, previous, previous + "-duplicate", new_fact=True)
            snapshot = self.snapshot(dataset=duplicated)
            with self.subTest(previous=previous):
                self.assertFalse(snapshot.coverage_complete)
                self.assertEqual(snapshot.to_dict()["annotation_summary"]["unresolved"][0]["reason"], expected)
                self.assertEqual(snapshot.to_graph().number_of_edges(), 0)

    def test_multiple_spans_and_uncalibrated_scores_do_not_multiply_counts(self):
        payload = source_record(self.dataset, "human-m2")["payload"]
        payload["evidence"] = [{"unit": "unicode_codepoint", "start": 0, "end": 3},
                               {"unit": "unicode_codepoint", "start": 4, "end": 8}]
        payload["score"] = {"kind": "uncalibrated", "value": 1000}
        dataset = revise(self.dataset, "human-m2", "human-m2-spans", payload=payload)
        self.assertEqual(self.snapshot(dataset=dataset).to_dict()["edges"][0]["strength"], 1)

    def test_semantic_subject_membership_is_checked_at_the_source_event(self):
        payload = source_record(self.dataset, "human-m1")["payload"]
        payload["subject"] = {"kind": "person", "id": "D"}
        dataset = revise(self.dataset, "human-m1", "human-m1-person", payload=payload)
        membership = source_record(dataset, "join-D")["payload"]
        membership["status"] = "absent"
        dataset = revise(dataset, "join-D", "leave-D", new_fact=True, payload=membership, occurred_at=4)
        snapshot = self.snapshot("disagreement", dataset=dataset)
        self.assertTrue(snapshot.coverage_complete)
        self.assertIn("D", snapshot.persons)
        self.assertEqual(snapshot.to_dict()["population"]["exposure"]["D"], 4)
        row = next(r for r in snapshot.to_dict()["annotation_summary"]["decisions"] if r["interaction_record_id"] == "m1")
        self.assertEqual(row["outcome"], "outside_population")
        self.assertFalse(row["subject_eligible_at_event"])
        self.assertEqual(snapshot.to_graph().number_of_edges(), 0)

    def test_method_version_is_part_of_comparison_policy(self):
        dataset = self.dataset
        for message in range(1, 7):
            previous = f"human-m{message}"
            payload = source_record(dataset, previous)["payload"]
            payload["method"]["version"] = "2"
            dataset = revise(dataset, previous, previous + "-v2", new_fact=True, payload=payload)
        new_method = {**self.view()["method"], "version": "2"}
        new = self.snapshot(dataset=dataset, method=new_method)
        self.assertTrue(new.coverage_complete)
        self.assertEqual(new.to_graph().number_of_edges(), 1)
        with self.assertRaisesRegex(ValueError, "same view policy"):
            compare_snapshots(self.snapshot(), new)

    def test_source_coverage_is_required_even_with_every_decision_present(self):
        payload = source_record(self.dataset, "coverage-communication")["payload"]
        payload["status"] = "partial"
        partial = revise(self.dataset, "coverage-communication", "coverage-partial", payload=payload)
        snapshot = self.snapshot(dataset=partial)
        self.assertFalse(snapshot.coverage_complete)
        self.assertEqual(snapshot.to_dict()["annotation_summary"]["counts"]["unresolved"], 0)
        self.assertFalse(snapshot.to_dict()["annotation_summary"]["source_coverage_complete"])

    def test_annotations_do_not_modify_observed_cooperation(self):
        state_view = {"schema": "sociolab.view.v1", "population": "team", "mode": "state", "layer": "cooperation", "directed": False, "at": 8}
        with_annotations = materialize_snapshot(self.dataset, state_view)
        without_annotations = materialize_snapshot(self.dataset, state_view, 25)
        self.assertEqual(with_annotations.to_dict()["edges"], without_annotations.to_dict()["edges"])
        self.assertEqual(with_annotations.to_graph().number_of_edges(), 3)

    def test_empty_source_window_can_be_complete_without_invented_labels(self):
        empty = self.snapshot(start=30, end=40)
        self.assertTrue(empty.coverage_complete)
        self.assertEqual(empty.to_dict()["annotation_summary"]["counts"]["source_events"], 0)
        self.assertEqual(empty.to_graph().number_of_edges(), 0)

    def test_serialized_outcomes_and_qualification_flags_are_self_consistent(self):
        original = self.snapshot().to_dict()
        self.assertEqual(NetworkSnapshot.from_mapping(original).to_dict(), original)
        for outcome in ("neutral", "topic", "label_filtered", "topic_filtered", "outside_population"):
            data = deepcopy(original)
            data.pop("content_hash")
            row = next(r for r in data["annotation_summary"]["decisions"] if r["interaction_record_id"] == "m2")
            row["outcome"] = outcome
            data["edges"] = []
            data["annotation_summary"]["counts"]["projected_events"] = 0
            with self.subTest(outcome=outcome), self.assertRaisesRegex(ValueError, "outcome contradicts"):
                NetworkSnapshot.create(data)
        data = deepcopy(original)
        data.pop("content_hash")
        data["annotation_summary"]["automatic_annotation_qualified"] = True
        with self.assertRaisesRegex(ValueError, "does not load content or qualify"):
            NetworkSnapshot.create(data)

    def test_annotation_view_admission_rejects_implicit_or_misnamed_conversions(self):
        for updates in ({"layer": "trust"}, {"source_layer": "conflict"}, {"directed": False},
                        {"labels": ["neutral"]}, {"actions": ["delivery"]}, {"labels": []}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_view_spec(self.view(**updates), self.dataset.clock)

    def test_actual_cli_reports_annotation_quality_and_derived_change(self):
        def run(args):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(args), 0)
            return json.loads(output.getvalue())
        path = str(EXAMPLES / "events.json")
        inspection = run(["annotations", "inspect", path, "--method", str(EXAMPLES / "human.method.json")])
        self.assertEqual(inspection["summary"]["current_annotation_count"], 6)
        evaluation = run(["annotations", "evaluate", path, "--reference-method", str(EXAMPLES / "human.method.json"),
                          "--candidate-method", str(EXAMPLES / "model.method.json")])
        self.assertEqual(evaluation["qualification_status"], "NOT_ESTABLISHED")
        self.assertEqual(evaluation["reference_count"], 6)
        self.assertEqual(evaluation["matched_count"], 4)
        self.assertEqual(evaluation["agreement"]["label_accuracy"]["value"], 0.75)
        self.assertEqual(evaluation["agreement"]["joint_accuracy"]["value"], 0.5)
        self.assertEqual(evaluation["coverage"]["missing_candidate_ids"], ["content-m6"])
        with tempfile.TemporaryDirectory() as temp:
            paths = {}
            for name in ("conflict-before", "conflict-after", "model-disagreement"):
                value = run(["snapshot", path, str(EXAMPLES / (name + ".view.json"))])
                p = Path(temp) / (name + ".json")
                p.write_text(json.dumps(value), encoding="utf-8")
                paths[name] = str(p)
            changed = run(["changes", paths["conflict-before"], paths["conflict-after"]])
            self.assertEqual(changed["measurement_basis"], "derived_from_annotations")
            self.assertFalse(changed["automatic_annotation_qualified"])
            community = run(["communities", "analyze", paths["conflict-before"]])
            self.assertEqual(community["input"]["annotation_summary"]["counts"]["projected_events"], 1)
            self.assertFalse(community["automatic_annotation_qualified"])
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["communities", "analyze", paths["model-disagreement"]])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
