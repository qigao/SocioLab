"""Agreement bookkeeping through genuine journal ingestion and annotation status."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.annotation_evaluation import evaluate_annotations
from sociolab.annotation_schema import TAXONOMY
from sociolab.events import EventDataset, ingest_records


REFERENCE = {"kind": "human", "id": "coder", "version": "1"}
CANDIDATE = {"kind": "model", "id": "candidate", "version": "1"}
RECEIPT = "2026-11-27T12:00:00Z"
CONTENT_HASH = "sha256:" + sha256(b"test").hexdigest()


def _empty():
    return EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "annotation-evaluation",
        "origin": "synthetic", "source_revision": "fixture-1",
        "clock": {"kind": "ticks", "run_id": "case"}, "records": [],
    })


def _raw(record_id, kind, payload, *, at=1, fact_id=None, supersedes=None):
    return {
        "record_id": record_id, "fact_id": record_id if fact_id is None else fact_id,
        "operation": "assert", "supersedes": supersedes, "kind": kind,
        "occurred_at": at, "valid_interval": None,
        "source": {"system": "fixture", "record_id": record_id,
                   "revision": "1", "evidence_ref": "synthetic:" + record_id},
        "payload": payload,
    }


def _content(record_id, interaction_id, *, revision="v1", fact_id=None, supersedes=None):
    return _raw(record_id, "content.observed", {
        "interaction_record_id": interaction_id, "content_ref": "source:" + record_id,
        "content_revision": revision, "content_hash": CONTENT_HASH, "language": "en",
        "length": {"unicode_codepoint": 4, "utf8_byte": 4},
    }, fact_id=fact_id, supersedes=supersedes)


def _base(count):
    records = [_raw("person-" + actor, "entity.observed", {
        "entity_id": actor, "entity_type": "person",
    }, at=0) for actor in ("A", "B")]
    contents = []
    for index in range(1, count + 1):
        interaction_id = "speech-" + str(index)
        records.append(_raw(interaction_id, "interaction.observed", {
            "actor": "A", "target": "B", "action": "utterance", "topic": None,
        }))
        content = _content("content-" + str(index), interaction_id)
        contents.append(content)
        records.append(content)
    return ingest_records(_empty(), records, received_at=RECEIPT), contents


def _annotation(record_id, content, label, method, *, subject=None, topic=None, score=None):
    payload = content["payload"]
    return _raw(record_id, "annotation.recorded", {
        "target_record_id": content["record_id"],
        "target_content_revision": payload["content_revision"],
        "target_content_hash": payload["content_hash"],
        "method": dict(method), "taxonomy": dict(TAXONOMY), "label": label,
        "subject": {"kind": "person", "id": "B"} if subject is None else dict(subject),
        "topic": topic, "evidence": [{"unit": "unicode_codepoint", "start": 0, "end": 2}],
        "score": score,
    })


def _append(dataset, *records):
    return ingest_records(dataset, list(records), received_at=RECEIPT)


def _evaluate(dataset, **kwargs):
    return evaluate_annotations(
        dataset, reference_method=REFERENCE, candidate_method=CANDIDATE, **kwargs,
    )


class AnnotationEvaluationTest(unittest.TestCase):
    def test_hand_computed_confusion_and_coverage_keep_abstentions_unresolved(self):
        dataset, contents = _base(8)
        reference_labels = ["support", "support", "neutral", "threat", "support", "neutral", "uncertain", None]
        candidate_labels = ["support", "neutral", "neutral", "support", "uncertain", None, "neutral", "support"]
        records = []
        for index, (content, reference, candidate) in enumerate(zip(contents, reference_labels, candidate_labels), 1):
            if reference is not None:
                records.append(_annotation("ref-" + str(index), content, reference, REFERENCE))
            if candidate is not None:
                records.append(_annotation("cand-" + str(index), content, candidate, CANDIDATE,
                                           score={"kind": "uncalibrated", "value": 1.7}))
        report = _evaluate(_append(dataset, *records))
        self.assertEqual((report["current_content_count"], report["reference_count"], report["matched_count"]), (8, 6, 4))
        self.assertEqual(report["agreement"]["label_accuracy"], {"numerator": 2, "denominator": 4, "value": 0.5})
        self.assertEqual(report["agreement"]["semantic_target_topic_accuracy"]["value"], 1)
        self.assertEqual(report["coverage"]["matched_over_reference"]["value"], 4 / 6)
        self.assertEqual(report["coverage"]["joint_correct_over_reference"]["value"], 2 / 6)
        self.assertEqual(report["coverage"]["missing_candidate_ids"], ["content-6"])
        self.assertEqual(report["coverage"]["missing_reference_ids"], ["content-8"])
        self.assertEqual(report["coverage"]["reference_targets_by_status"]["UNCERTAIN"], ["content-7"])
        self.assertEqual(report["coverage"]["candidate_targets_by_status"]["ABSTAINED"], ["content-5"])
        self.assertEqual(report["coverage"]["unresolved_reference_ids"], ["content-5", "content-6"])
        self.assertEqual(report["annotation_audit"]["candidate"]["uncertain_current"]["annotation_record_ids"], ["cand-5"])
        self.assertEqual(report["confusion"], [
            {"reference_label": "neutral", "candidate_label": "neutral", "count": 1},
            {"reference_label": "support", "candidate_label": "neutral", "count": 1},
            {"reference_label": "support", "candidate_label": "support", "count": 1},
            {"reference_label": "threat", "candidate_label": "support", "count": 1},
        ])
        labels = {item["label"]: item for item in report["per_label"]}
        self.assertEqual(labels["support"]["support"], 2)
        self.assertEqual(labels["support"]["eligible_reference_support"], 3)
        self.assertEqual(labels["support"]["unscored_reference_count"], 1)
        self.assertEqual(labels["support"]["precision"], 0.5)
        self.assertEqual(labels["support"]["recall"], 0.5)
        self.assertEqual(labels["support"]["f1"], 0.5)
        self.assertEqual(labels["neutral"]["f1"], 2 / 3)
        self.assertIsNone(labels["threat"]["precision"])
        self.assertEqual(labels["threat"]["recall"], 0)
        self.assertEqual(labels["threat"]["f1"], 0)
        self.assertIsNone(labels["mediation"]["f1"])
        self.assertEqual(sum(row["support"] for row in report["per_label"]), 4)
        self.assertEqual(report["qualification_status"], "NOT_ESTABLISHED")
        for field in ("reference_is_ground_truth", "train_test_independence_established", "empirical_validation_established",
                      "deployment_qualified", "automatic_annotation_qualified", "calibration_estimated", "raw_content_loaded"):
            self.assertFalse(report[field])
        self.assertEqual(report["input"]["dataset"]["origin"], "synthetic")
        self.assertEqual(report["candidate_method"], CANDIDATE)
        json.dumps(report, allow_nan=False)

    def test_matching_labels_do_not_hide_wrong_subject_or_topic(self):
        dataset, contents = _base(2)
        dataset = _append(dataset,
            _annotation("ref-1", contents[0], "disagreement", REFERENCE, subject={"kind": "topic", "id": "P"}, topic="P"),
            _annotation("cand-1", contents[0], "disagreement", CANDIDATE, subject={"kind": "person", "id": "B"}, topic="P"),
            _annotation("ref-2", contents[1], "threat", REFERENCE, topic="P"),
            _annotation("cand-2", contents[1], "threat", CANDIDATE, topic="Q"),
        )
        report = _evaluate(dataset)
        self.assertEqual(report["agreement"]["label_accuracy"]["value"], 1)
        self.assertEqual(report["agreement"]["subject_accuracy"]["value"], 0.5)
        self.assertEqual(report["agreement"]["topic_accuracy"]["value"], 0.5)
        self.assertEqual(report["agreement"]["semantic_target_topic_accuracy"]["value"], 0)
        self.assertEqual(report["agreement"]["joint_accuracy"]["value"], 0)
        first = report["matched_pairs"][0]
        self.assertTrue(first["label_agrees"])
        self.assertFalse(first["subject_agrees"])
        self.assertEqual(first["reference_subject"], {"kind": "topic", "id": "P"})

    def test_exact_content_revision_required_even_when_hash_is_unchanged(self):
        dataset, contents = _base(1)
        original = _append(dataset, _annotation("ref-old", contents[0], "support", REFERENCE))
        historical = _evaluate(original)
        corrected = _content("content-revised", "speech-1", revision="v2", fact_id="content-1", supersedes="content-1")
        later = _append(original, corrected, _annotation("cand-new", corrected, "support", CANDIDATE))
        report = _evaluate(later)
        self.assertEqual(report["current_contents"][0]["content_hash"], CONTENT_HASH)
        self.assertEqual(report["reference_count"], 0)
        self.assertEqual(report["matched_count"], 0)
        self.assertEqual(report["coverage"]["missing_reference_ids"], ["content-revised"])
        stale = report["annotation_audit"]["reference"]["stale"]
        self.assertEqual(stale["annotation_record_ids"], ["ref-old"])
        self.assertEqual(stale["content_record_ids"], ["content-1"])
        self.assertEqual(_evaluate(later, knowledge_cutoff=len(original.records)), historical)

    def test_identical_hashes_on_different_interactions_never_form_a_pair(self):
        dataset, contents = _base(2)
        dataset = _append(dataset,
            _annotation("ref", contents[0], "support", REFERENCE),
            _annotation("cand", contents[1], "support", CANDIDATE),
        )
        report = _evaluate(dataset)
        self.assertEqual(report["reference_count"], 1)
        self.assertEqual(report["matched_count"], 0)
        self.assertEqual(report["coverage"]["missing_candidate_ids"], ["content-1"])
        self.assertEqual(report["coverage"]["missing_reference_ids"], ["content-2"])
        self.assertIsNone(report["agreement"]["joint_accuracy"]["value"])
        self.assertEqual(report["coverage"]["joint_correct_over_reference"]["value"], 0)

    def test_ambiguous_candidate_is_unresolved_without_last_record_winning(self):
        dataset, contents = _base(1)
        dataset = _append(dataset,
            _annotation("ref", contents[0], "support", REFERENCE),
            _annotation("cand-one", contents[0], "support", CANDIDATE),
            _annotation("cand-two", contents[0], "neutral", CANDIDATE),
        )
        report = _evaluate(dataset)
        self.assertEqual(report["matched_count"], 0)
        self.assertEqual(report["coverage"]["candidate_targets_by_status"]["AMBIGUOUS"], ["content-1"])
        self.assertEqual(report["coverage"]["missing_candidate_ids"], [])
        self.assertEqual(report["targets"][0]["unresolved_reasons"], ["candidate_ambiguous"])
        ambiguous = report["annotation_audit"]["candidate"]["ambiguous"]
        self.assertEqual(ambiguous["annotation_count"], 2)
        self.assertEqual(ambiguous["content_count"], 1)
        self.assertEqual(ambiguous["annotation_record_ids"], ["cand-one", "cand-two"])

    def test_ambiguous_human_reference_is_not_resolved_by_candidate_agreement(self):
        dataset, contents = _base(1)
        dataset = _append(dataset,
            _annotation("ref-one", contents[0], "support", REFERENCE),
            _annotation("ref-two", contents[0], "neutral", REFERENCE),
            _annotation("cand", contents[0], "support", CANDIDATE),
        )
        report = _evaluate(dataset)
        self.assertEqual(report["reference_count"], 0)
        self.assertEqual(report["coverage"]["reference_targets_by_status"]["AMBIGUOUS"], ["content-1"])
        self.assertEqual(report["annotation_audit"]["reference"]["ambiguous"]["annotation_count"], 2)
        self.assertIsNone(report["coverage"]["matched_over_reference"]["value"])

    def test_candidate_versions_are_explicit_and_never_pooled(self):
        dataset, contents = _base(1)
        old_method = {**CANDIDATE, "version": "0"}
        dataset = _append(dataset,
            _annotation("ref", contents[0], "support", REFERENCE),
            _annotation("cand-old", contents[0], "support", old_method),
        )
        report = _evaluate(dataset)
        self.assertEqual(report["matched_count"], 0)
        self.assertEqual(report["annotation_audit"]["other_method_record_ids"], ["cand-old"])
        updated = _append(dataset, _annotation("cand-current", contents[0], "support", CANDIDATE))
        report = _evaluate(updated)
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(report["matched_pairs"][0]["candidate_annotation_id"], "cand-current")
        self.assertEqual(report["annotation_audit"]["other_method_record_ids"], ["cand-old"])

    def test_stale_interaction_labels_remain_visible_outside_current_coverage(self):
        dataset, contents = _base(1)
        dataset = _append(dataset,
            _annotation("ref", contents[0], "support", REFERENCE),
            _annotation("cand", contents[0], "support", CANDIDATE),
        )
        revised = _raw("speech-revised", "interaction.observed", {
            "actor": "A", "target": "B", "action": "utterance", "topic": "corrected",
        }, fact_id="speech-1", supersedes="speech-1")
        report = _evaluate(_append(dataset, revised))
        self.assertEqual(report["current_content_count"], 0)
        self.assertEqual(report["matched_count"], 0)
        self.assertEqual(report["content_issues"][0]["status"], "STALE_INTERACTION")
        for side in ("reference", "candidate"):
            self.assertEqual(report["annotation_audit"][side]["by_status"]["STALE_INTERACTION"]["annotation_count"], 1)
            self.assertEqual(report["annotation_audit"][side]["outside_current_contents"]["content_record_ids"], ["content-1"])

    def test_ambiguous_content_is_reported_instead_of_scored(self):
        dataset, contents = _base(1)
        dataset = _append(dataset,
            _annotation("ref", contents[0], "support", REFERENCE),
            _annotation("cand", contents[0], "support", CANDIDATE),
            _content("competing-content", "speech-1"),
        )
        report = _evaluate(dataset)
        self.assertEqual(report["current_content_count"], 0)
        self.assertEqual(len(report["content_issues"]), 2)
        self.assertEqual(report["annotation_audit"]["candidate"]["by_status"]["AMBIGUOUS_CONTENT"]["annotation_count"], 1)
        self.assertEqual(report["confusion"], [])

    def test_reference_must_be_human_and_self_evaluation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "human"):
            evaluate_annotations(_empty(), reference_method=CANDIDATE,
                                 candidate_method={"kind": "rule", "id": "other", "version": "1"})
        with self.assertRaisesRegex(ValueError, "self-evaluation"):
            evaluate_annotations(_empty(), reference_method=REFERENCE, candidate_method=deepcopy(REFERENCE))
        with self.assertRaisesRegex(ValueError, "method"):
            evaluate_annotations(_empty(), reference_method=REFERENCE, candidate_method={"kind": "model", "id": "no-version"})

    def test_empty_evaluation_has_null_undefined_metrics_and_no_qualification(self):
        report = _evaluate(_empty())
        self.assertEqual((report["current_content_count"], report["reference_count"], report["matched_count"]), (0, 0, 0))
        for metric in report["agreement"].values():
            self.assertEqual(metric, {"numerator": 0, "denominator": 0, "value": None})
        self.assertIsNone(report["coverage"]["matched_over_reference"]["value"])
        for row in report["per_label"]:
            self.assertIsNone(row["precision"])
            self.assertIsNone(row["recall"])
            self.assertIsNone(row["f1"])
        self.assertEqual(report["qualification_status"], "NOT_ESTABLISHED")
        json.dumps(report, allow_nan=False)

    def test_subjects_use_cutoff_resolved_identity_without_rewriting_source_labels(self):
        dataset, contents = _base(1)
        dataset = _append(dataset,
            _raw("alias", "entity.observed", {"entity_id": "B-alias", "entity_type": "person"}),
            _raw("mapping", "identity.mapped", {"alias": "B-alias", "canonical": "B"}),
            _annotation("ref", contents[0], "support", REFERENCE),
            _annotation("cand", contents[0], "support", CANDIDATE, subject={"kind": "person", "id": "B-alias"}),
        )
        report = _evaluate(dataset)
        self.assertEqual(report["agreement"]["joint_accuracy"]["value"], 1)
        self.assertEqual(report["matched_pairs"][0]["candidate_subject"], {"kind": "person", "id": "B"})
        self.assertEqual(report["annotation_audit"]["candidate"]["annotations"][0]["source_subject"], {"kind": "person", "id": "B-alias"})


if __name__ == "__main__":
    unittest.main()
