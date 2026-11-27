"""Exact annotation availability using the real versioned event contract."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.annotation_schema import TAXONOMY
from sociolab.annotations import annotation_report
from sociolab.events import EventDataset, ingest_records


RECEIPT = "2026-11-27T12:00:00Z"
HUMAN = {"kind": "human", "id": "coder-1", "version": "1"}
MODEL = {"kind": "model", "id": "external-model", "version": "1"}
FINGERPRINT = "sha256:" + sha256(b"synthetic content").hexdigest()


def record(record_id, kind, payload, *, at=30, fact_id=None, supersedes=None, retract=False):
    return {
        "record_id": record_id, "fact_id": fact_id or record_id,
        "kind": kind, "operation": "retract" if retract else "assert",
        "supersedes": supersedes, "occurred_at": at, "valid_interval": None,
        "source": {"system": "fixture", "record_id": record_id,
                   "revision": record_id, "evidence_ref": f"source:{record_id}"},
        "payload": None if retract else deepcopy(payload),
    }


def interaction(record_id="speech-1", *, actor="A", addressee="B", at=10):
    return record(record_id, "interaction.observed", {
        "actor": actor, "target": addressee, "action": "utterance", "topic": "proposal-P",
    }, at=at)


def content(record_id="content-1", *, interaction_id="speech-1"):
    return record(record_id, "content.observed", {
        "interaction_record_id": interaction_id,
        "content_ref": "source://not-loaded/exact-content", "content_revision": "1",
        "content_hash": FINGERPRINT, "language": "en",
        "length": {"unicode_codepoint": 17, "utf8_byte": 17},
    }, at=12)


def annotation(record_id="label-1", *, target="content-1", method=None,
               label="threat", subject=None, topic=None, score=None):
    if subject is None:
        subject = {"kind": "none", "id": None} if label in {"neutral", "uncertain"} else {"kind": "person", "id": "C"}
    return record(record_id, "annotation.recorded", {
        "target_record_id": target, "target_content_revision": "1", "target_content_hash": FINGERPRINT,
        "method": HUMAN if method is None else method, "taxonomy": TAXONOMY,
        "label": label, "subject": subject, "topic": topic,
        "evidence": [] if label in {"neutral", "uncertain"} else [
            {"unit": "unicode_codepoint", "start": 0, "end": 5},
        ],
        "score": score,
    })


def append(dataset, *records):
    return ingest_records(dataset, list(records), received_at=RECEIPT)


def journal(*extra, persons=("A", "B", "C")):
    dataset = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "annotation-case", "origin": "synthetic",
        "source_revision": "fixture-1", "clock": {"kind": "ticks", "run_id": "annotations"},
        "records": [],
    })
    declarations = [record(f"person:{person}", "entity.observed", {
        "entity_id": person, "entity_type": "person",
    }, at=0) for person in persons]
    return append(dataset, *declarations, *extra)


def revision(dataset, previous_id, new_id, *, payload=None, retract=False, at=None):
    previous = next(r for r in dataset.records if r["record_id"] == previous_id)
    return append(dataset, record(
        new_id, previous["kind"], previous["payload"] if payload is None else payload,
        fact_id=previous["fact_id"], supersedes=previous_id, retract=retract,
        at=previous["occurred_at"] if at is None else at,
    ))


class AnnotationReportTest(unittest.TestCase):
    def setUp(self):
        self.dataset = journal(interaction(), content(), annotation())

    def test_current_exact_binding_source_time_and_noninference_flags(self):
        original = self.dataset.to_dict()
        report = annotation_report(self.dataset)
        row = report["annotations"][0]
        self.assertEqual(row["status"], "CURRENT")
        self.assertIsNone(row["reason"])
        self.assertEqual(row["record_id"], "label-1")
        self.assertEqual(row["target_record_id"], "content-1")
        self.assertEqual(row["interaction_record_id"], "speech-1")
        self.assertEqual((row["actor"], row["addressee"]), ("A", "B"))
        self.assertEqual(row["subject"], {"kind": "person", "id": "C"})
        self.assertEqual(row["occurred_at"], 10)
        self.assertEqual(row["annotation_occurred_at"], 30)
        self.assertEqual(row["evidence_record_ids"], ["speech-1", "content-1", "label-1"])
        self.assertEqual(row["content_hash"], FINGERPRINT)
        self.assertEqual(report["summary"]["status_counts"]["CURRENT"], 1)
        self.assertEqual(report["interpretation_status"], "UNVALIDATED_SOURCE_LABELS")
        self.assertFalse(report["raw_content_loaded"])
        self.assertFalse(report["automatic_annotation_qualified"])
        self.assertTrue(report["source_events_not_modified"])
        self.assertEqual(self.dataset.to_dict(), original)
        json.dumps(report, allow_nan=False)

    def test_exact_receipt_prefix_is_unchanged_after_later_import(self):
        old = annotation_report(self.dataset)
        cutoff = len(self.dataset.records)
        future = append(self.dataset, annotation("model-label", method=MODEL, label="support"))
        self.assertEqual(annotation_report(future, knowledge_cutoff=cutoff), old)
        self.assertEqual(old["input"]["dataset"]["content_hash"], self.dataset.content_hash)
        self.assertEqual(old["input"]["knowledge_cutoff"], cutoff)
        self.assertEqual(annotation_report(future)["summary"]["current_annotation_count"], 2)
        before_label = annotation_report(future, knowledge_cutoff=cutoff - 1)
        self.assertEqual(before_label["annotations"], [])
        self.assertEqual(before_label["summary"]["current_contents_without_selected_current_annotation"], ["content-1"])

    def test_identical_hash_new_content_record_requires_a_new_annotation(self):
        old = annotation_report(self.dataset)
        replacement = revision(self.dataset, "content-1", "content-2")
        report = annotation_report(replacement)
        stale = report["annotations"][0]
        self.assertEqual(stale["status"], "STALE_CONTENT")
        self.assertEqual(stale["reason"], "content_superseded")
        self.assertEqual(stale["issues"][0]["invalidated_by_record_id"], "content-2")
        self.assertEqual(stale["target_record_id"], "content-1")
        self.assertEqual([row["record_id"] for row in report["current_contents"]], ["content-2"])
        self.assertEqual(report["summary"]["current_contents_without_selected_current_annotation"], ["content-2"])
        self.assertEqual(report["current_contents"][0]["content_hash"], stale["content_hash"])
        relabel = annotation(target="content-2")["payload"]
        fixed = revision(replacement, "label-1", "label-2", payload=relabel)
        self.assertEqual(annotation_report(fixed)["annotations"][0]["status"], "CURRENT")
        self.assertEqual(annotation_report(fixed)["annotations"][0]["record_id"], "label-2")
        self.assertEqual(annotation_report(fixed, knowledge_cutoff=len(self.dataset.records)), old)

    def test_retracted_content_and_direct_successor_reason(self):
        removed = revision(self.dataset, "content-1", "content-withdrawn", retract=True)
        row = annotation_report(removed)["annotations"][0]
        self.assertEqual(row["status"], "STALE_CONTENT")
        self.assertEqual(row["reason"], "content_retracted")
        self.assertEqual(row["issues"][0]["invalidated_by_record_id"], "content-withdrawn")
        replaced = revision(self.dataset, "content-1", "content-2")
        replaced_then_removed = revision(replaced, "content-2", "content-withdrawn", retract=True)
        issue = annotation_report(replaced_then_removed)["annotations"][0]["issues"][0]
        self.assertEqual(issue["reason"], "content_superseded")
        self.assertEqual(issue["invalidated_by_record_id"], "content-2")
        self.assertEqual(issue["fact_head_record_id"], "content-withdrawn")
        self.assertEqual(issue["fact_head_operation"], "retract")

    def test_replaced_interaction_keeps_old_context_and_exposes_unlabelled_new_content(self):
        updated_action = interaction(addressee="C", at=11)["payload"]
        replacement = revision(self.dataset, "speech-1", "speech-2", payload=updated_action, at=11)
        replacement = append(replacement, content("new-interaction-content", interaction_id="speech-2"))
        report = annotation_report(replacement)
        row = report["annotations"][0]
        self.assertEqual(row["status"], "STALE_INTERACTION")
        self.assertEqual(row["reason"], "interaction_superseded")
        self.assertEqual(row["addressee"], "B")
        self.assertEqual(row["occurred_at"], 10)
        current = report["current_contents"][0]
        self.assertEqual(current["interaction_record_id"], "speech-2")
        self.assertEqual(current["content_hash"], row["content_hash"])
        self.assertEqual((current["addressee"], current["occurred_at"]), ("C", 11))
        self.assertEqual(report["summary"]["current_contents_without_selected_current_annotation"], ["new-interaction-content"])

    def test_withdrawn_interaction_does_not_delete_active_historical_annotation(self):
        removed = revision(self.dataset, "speech-1", "speech-withdrawn", retract=True)
        report = annotation_report(removed)
        self.assertEqual(len(report["annotations"]), 1)
        self.assertEqual(report["annotations"][0]["reason"], "interaction_retracted")
        self.assertEqual(report["annotations"][0]["status"], "STALE_INTERACTION")
        self.assertEqual(report["current_contents"], [])
        self.assertEqual(report["content_issues"][0]["status"], "STALE_INTERACTION")
        self.assertEqual(report["summary"]["current_annotation_count"], 0)

    def test_withdrawn_annotations_are_excluded_but_current_content_remains(self):
        removed = revision(self.dataset, "label-1", "label-withdrawn", retract=True)
        report = annotation_report(removed)
        self.assertEqual(report["annotations"], [])
        self.assertEqual(report["summary"]["active_annotation_count"], 0)
        self.assertEqual([row["record_id"] for row in report["current_contents"]], ["content-1"])
        self.assertEqual(report["summary"]["current_contents_without_selected_current_annotation"], ["content-1"])

    def test_duplicate_content_facts_are_ambiguous_even_with_identical_hashes(self):
        duplicate = append(self.dataset, content("duplicate-content"))
        report = annotation_report(duplicate)
        self.assertEqual(report["annotations"][0]["status"], "AMBIGUOUS_CONTENT")
        self.assertEqual(report["current_contents"], [])
        self.assertEqual({r["record_id"] for r in report["content_issues"]}, {"content-1", "duplicate-content"})
        self.assertTrue(all(r["status"] == "AMBIGUOUS_CONTENT" for r in report["content_issues"]))
        repaired = revision(duplicate, "duplicate-content", "duplicate-withdrawn", retract=True)
        self.assertEqual(annotation_report(repaired)["annotations"][0]["status"], "CURRENT")

    def test_single_label_profile_duplicates_are_ambiguous_across_label_and_subject(self):
        duplicate = append(self.dataset, annotation("second-decision", label="neutral"))
        report = annotation_report(duplicate, method=HUMAN, taxonomy=TAXONOMY)
        self.assertEqual([row["status"] for row in report["annotations"]], ["AMBIGUOUS_ANNOTATION"] * 2)
        self.assertEqual(report["summary"]["current_annotation_count"], 0)
        self.assertEqual(report["summary"]["label_counts_current"]["threat"], 0)
        self.assertEqual(report["summary"]["current_content_count"], 1)
        self.assertEqual(report["summary"]["current_contents_without_selected_current_annotation"], ["content-1"])
        repaired = revision(duplicate, "second-decision", "second-withdrawn", retract=True)
        self.assertEqual(annotation_report(repaired)["annotations"][0]["status"], "CURRENT")

    def test_humans_models_and_versions_are_distinct_exact_filters_not_summed_events(self):
        second_human = {**HUMAN, "id": "coder-2"}
        newer_model = {**MODEL, "version": "2"}
        dataset = append(self.dataset,
            annotation("coder-two", method=second_human, label="insult"),
            annotation("model-one", method=MODEL, label="support", score={"kind": "uncalibrated", "value": 7.5}),
            annotation("model-two", method=newer_model, label="uncertain"),
        )
        all_methods = annotation_report(dataset)
        self.assertEqual(all_methods["summary"]["current_annotation_count"], 4)
        self.assertEqual(all_methods["summary"]["current_annotated_content_count"], 1)
        self.assertTrue(all(row["status"] == "CURRENT" for row in all_methods["annotations"]))
        chosen = annotation_report(dataset, method=MODEL, taxonomy=TAXONOMY)
        self.assertEqual([r["record_id"] for r in chosen["annotations"]], ["model-one"])
        self.assertEqual(chosen["annotations"][0]["score"], {"kind": "uncalibrated", "value": 7.5})
        self.assertFalse(chosen["automatic_annotation_qualified"])
        self.assertEqual(chosen["current_contents"], all_methods["current_contents"])
        self.assertEqual(annotation_report(dataset, method=newer_model)["annotations"][0]["label"], "uncertain")
        missing = annotation_report(dataset, method={**MODEL, "version": "missing"})
        self.assertEqual(missing["annotations"], [])
        self.assertEqual(missing["summary"]["current_contents_without_selected_current_annotation"], ["content-1"])

    def test_identity_mapping_is_as_known_and_topic_subject_never_becomes_a_person(self):
        dataset = journal(
            interaction(actor="A-alias", addressee="B-alias"), content(),
            annotation(subject={"kind": "person", "id": "C-alias"}),
            annotation("topic-label", method=MODEL, label="disagreement",
                       subject={"kind": "topic", "id": "C-alias"}, topic="C-alias"),
            persons=("A", "B", "C", "A-alias", "B-alias", "C-alias"),
        )
        before = annotation_report(dataset)
        cutoff = len(dataset.records)
        mapped = append(dataset, *[record(f"map:{actor}", "identity.mapped", {
            "alias": f"{actor}-alias", "canonical": actor,
        }) for actor in "ABC"])
        rows = annotation_report(mapped)["annotations"]
        self.assertEqual((rows[0]["actor"], rows[0]["addressee"]), ("A", "B"))
        self.assertEqual(rows[0]["subject"], {"kind": "person", "id": "C"})
        self.assertEqual(rows[0]["source_subject"], {"kind": "person", "id": "C-alias"})
        self.assertEqual(rows[1]["subject"], {"kind": "topic", "id": "C-alias"})
        self.assertEqual(rows[1]["topic"], "C-alias")
        self.assertEqual(rows[0]["target_record_id"], "content-1")
        self.assertEqual(annotation_report(mapped, knowledge_cutoff=cutoff), before)

    def test_neutral_and_uncertain_are_available_labels_with_no_probability_claim(self):
        for label in ("neutral", "uncertain"):
            dataset = journal(interaction(), content(), annotation(label=label))
            row = annotation_report(dataset)["annotations"][0]
            self.assertEqual(row["status"], "CURRENT")
            self.assertEqual(row["subject"], {"kind": "none", "id": None})
            self.assertEqual(row["evidence"], [])
            self.assertIsNone(row["score"])

    def test_filter_and_result_mutation_cannot_change_the_dataset(self):
        method = deepcopy(HUMAN)
        initial = annotation_report(self.dataset, method=method)
        expected = deepcopy(initial)
        initial["annotations"][0]["subject"]["id"] = "other"
        initial["annotations"][0]["evidence"][0]["end"] = 99
        initial["current_contents"][0]["length"]["utf8_byte"] = 999
        initial["filters"]["method"]["version"] = "changed"
        self.assertEqual(method, HUMAN)
        self.assertEqual(annotation_report(self.dataset, method=method), expected)

    def test_invalid_filter_cutoff_and_dataset_fail_at_the_boundary(self):
        for cutoff in (True, -1, len(self.dataset.records) + 1, 1.0):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                annotation_report(self.dataset, knowledge_cutoff=cutoff)
        for settings in ({"method": "coder-1"}, {"method": {"id": "coder-1"}},
                         {"taxonomy": {"id": "other", "version": "1"}}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                annotation_report(self.dataset, **settings)
        with self.assertRaises(ValueError):
            annotation_report(self.dataset.to_dict())


if __name__ == "__main__":
    unittest.main()
