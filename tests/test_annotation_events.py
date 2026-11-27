"""Exact annotation targets, retained history and strict metadata admission."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.annotation_schema import LABELS, TAXONOMY, validate_method, validate_taxonomy
from sociolab.events import EventDataset, ingest_records, load_event_dataset
from test_events import RECEIPT, LATER, entity_record, interaction, populated_dataset, raw_record


HASH = "sha256:" + "a" * 64
METHOD = {"kind": "human", "id": "coder-1", "version": "1"}


def content_record(record_id="content-1", *, interaction_id="speech", revision="v1",
                   content_hash=HASH, **record_fields):
    return raw_record(record_id, "content.observed", {
        "interaction_record_id": interaction_id,
        "content_ref": "source:utterance/1", "content_revision": revision,
        "content_hash": content_hash, "language": "zh",
        "length": {"unicode_codepoint": 4, "utf8_byte": 12},
    }, **record_fields)


def annotation_record(record_id="annotation-1", *, target="content-1", revision="v1",
                      content_hash=HASH, **record_fields):
    return raw_record(record_id, "annotation.recorded", {
        "target_record_id": target, "target_content_revision": revision,
        "target_content_hash": content_hash,
        "method": dict(METHOD), "taxonomy": dict(TAXONOMY),
        "label": "disagreement", "subject": {"kind": "person", "id": "bob"},
        "topic": None,
        "evidence": [{"unit": "unicode_codepoint", "start": 0, "end": 2}],
        "score": None,
    }, **record_fields)


def speech_dataset():
    return ingest_records(populated_dataset(), [interaction(occurred_at=5)], received_at=RECEIPT)


def content_dataset():
    return ingest_records(speech_dataset(), [content_record(occurred_at=20)], received_at=LATER)


class AnnotationEventTest(unittest.TestCase):
    def test_shared_method_and_taxonomy_validation_returns_fresh_dicts(self):
        method = dict(METHOD)
        validated = validate_method(method)
        validated["version"] = "changed"
        self.assertEqual(method, METHOD)
        taxonomy = validate_taxonomy(dict(TAXONOMY))
        taxonomy["version"] = "changed"
        self.assertEqual(TAXONOMY["version"], "1")
        self.assertEqual(len(LABELS), 8)
        for value in (None, [], {**METHOD, "text": "not admitted"}, {**METHOD, "kind": []}, {**METHOD, "id": " "}):
            with self.subTest(method=value), self.assertRaises(ValueError):
                validate_method(value)
        for value in ([], {"id": "other", "version": "1"}, {"id": TAXONOMY["id"], "version": 1}, {**TAXONOMY, "labels": []}):
            with self.subTest(taxonomy=value), self.assertRaises(ValueError):
                validate_taxonomy(value)

    def test_import_cutoff_metadata_time_and_idempotence(self):
        dataset = content_dataset()
        before = len(dataset.records)
        annotation = annotation_record(occurred_at=90)
        imported = ingest_records(dataset, [annotation], received_at=LATER)
        self.assertFalse(any(r["kind"] == "annotation.recorded" for r in imported.as_known(before)))
        self.assertEqual(imported.as_known()[-1]["occurred_at"], 90)
        source = next(r for r in imported.records if r["record_id"] == "speech")
        self.assertEqual(source["occurred_at"], 5)
        self.assertIs(ingest_records(imported, [annotation], received_at=LATER), imported)
        self.assertEqual(EventDataset.from_mapping(imported.to_dict()).content_hash, imported.content_hash)
        changed = deepcopy(annotation)
        changed["payload"]["label"] = "support"
        with self.assertRaisesRegex(ValueError, "different source content"):
            ingest_records(imported, [changed], received_at=LATER)

    def test_target_correction_and_retraction_do_not_delete_historical_annotations(self):
        dataset = ingest_records(content_dataset(), [annotation_record()], received_at=LATER)
        cutoff = len(dataset.records)
        corrected = interaction("speech-v2", fact_id="speech", supersedes="speech", occurred_at=6)
        dataset = ingest_records(dataset, [corrected], received_at=LATER)
        withdrawn = raw_record("speech-withdrawn", "interaction.observed", None,
                               fact_id="speech", supersedes="speech-v2", operation="retract")
        dataset = ingest_records(dataset, [withdrawn], received_at=LATER)
        self.assertIn("annotation-1", {r["record_id"] for r in dataset.as_known()})
        self.assertIn("speech", {r["record_id"] for r in dataset.as_known(cutoff)})
        self.assertFalse(any(r["kind"] == "interaction.observed" for r in dataset.as_known()))
        # Content may be recorded later about an exact, now-withdrawn assertion.
        corrected_content = content_record("content-v2", revision="v2", fact_id="content-1", supersedes="content-1")
        dataset = ingest_records(dataset, [corrected_content], received_at=LATER)
        withdrawn_content = raw_record("content-withdrawn", "content.observed", None,
                                       fact_id="content-1", supersedes="content-v2", operation="retract")
        dataset = ingest_records(dataset, [withdrawn_content], received_at=LATER)
        historical = annotation_record("historical-annotation")
        historical["payload"]["method"]["id"] = "second-coder"
        dataset = ingest_records(dataset, [historical, entity_record("carol")], received_at=LATER)
        active = {r["record_id"]: r for r in dataset.as_known()}
        self.assertIn("annotation-1", active)
        self.assertEqual(active["historical-annotation"]["payload"]["target_record_id"], "content-1")
        self.assertFalse(any(r["kind"] == "content.observed" for r in active.values()))

    def test_same_hash_with_new_content_revision_still_requires_exact_new_target(self):
        dataset = ingest_records(content_dataset(), [annotation_record()], received_at=LATER)
        cutoff = len(dataset.records)
        updated = content_record("content-v2", revision="v2", fact_id="content-1", supersedes="content-1")
        dataset = ingest_records(dataset, [updated], received_at=LATER)
        old_annotation = next(r for r in dataset.as_known() if r["kind"] == "annotation.recorded")
        self.assertEqual(old_annotation["payload"]["target_record_id"], "content-1")
        self.assertEqual(old_annotation["payload"]["target_content_revision"], "v1")
        self.assertIn("content-1", {r["record_id"] for r in dataset.as_known(cutoff)})
        with self.assertRaisesRegex(ValueError, "exact target content revision and hash"):
            ingest_records(dataset, [annotation_record("bad", target="content-v2")], received_at=LATER)
        new = annotation_record("new", target="content-v2", revision="v2")
        dataset = ingest_records(dataset, [new], received_at=LATER)
        self.assertEqual(dataset.as_known()[-1]["payload"]["target_record_id"], "content-v2")

    def test_target_must_be_an_earlier_assertion_of_the_right_kind(self):
        with self.assertRaisesRegex(ValueError, "earlier receipt"):
            ingest_records(populated_dataset(), [content_record(), interaction()], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "earlier receipt"):
            ingest_records(speech_dataset(), [annotation_record(), content_record()], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "asserted interaction.observed"):
            ingest_records(speech_dataset(), [content_record(interaction_id="declare-alice")], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "asserted content.observed"):
            ingest_records(content_dataset(), [annotation_record(target="speech")], received_at=LATER)
        withdrawn = raw_record("withdrawn", "interaction.observed", None,
                               fact_id="speech", supersedes="speech", operation="retract")
        dataset = ingest_records(speech_dataset(), [withdrawn], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "asserted interaction.observed"):
            ingest_records(dataset, [content_record(interaction_id="withdrawn")], received_at=LATER)
        content_withdrawal = raw_record("withdrawn-content", "content.observed", None,
                                        fact_id="content-1", supersedes="content-1", operation="retract")
        dataset = ingest_records(content_dataset(), [content_withdrawal], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "asserted content.observed"):
            ingest_records(dataset, [annotation_record(target="withdrawn-content")], received_at=LATER)

    def test_content_targets_only_utterance_or_reply(self):
        for action in ("reply", "delivery", "cooperation", "conflict"):
            source = interaction("action")
            source["payload"]["action"] = action
            dataset = ingest_records(populated_dataset(), [source], received_at=LATER)
            content = content_record(interaction_id="action")
            if action == "reply":
                self.assertEqual(ingest_records(dataset, [content], received_at=LATER).records[-1]["kind"], "content.observed")
            else:
                with self.subTest(action=action), self.assertRaisesRegex(ValueError, "utterance or reply"):
                    ingest_records(dataset, [content], received_at=LATER)

    def test_hashes_and_declared_unicode_lengths_are_strict(self):
        invalid_hashes = ["a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha256:" + "g" * 64, []]
        for digest in invalid_hashes:
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                ingest_records(speech_dataset(), [content_record(content_hash=digest)], received_at=LATER)
        lengths = [
            {"unicode_codepoint": True, "utf8_byte": 1},
            {"unicode_codepoint": 4.0, "utf8_byte": 12},
            {"unicode_codepoint": -1, "utf8_byte": 0},
            {"unicode_codepoint": 4, "utf8_byte": 3},
            {"unicode_codepoint": 4, "utf8_byte": 17},
            {"unicode_codepoint": 0, "utf8_byte": 1},
            {"unicode_codepoint": 4},
        ]
        for length in lengths:
            content = content_record()
            content["payload"]["length"] = length
            with self.subTest(length=length), self.assertRaises(ValueError):
                ingest_records(speech_dataset(), [content], received_at=LATER)
        mismatch = annotation_record(content_hash="sha256:" + "b" * 64)
        with self.assertRaisesRegex(ValueError, "exact target content revision and hash"):
            ingest_records(content_dataset(), [mismatch], received_at=LATER)

    def test_empty_content_allows_only_labels_without_required_spans(self):
        content = content_record()
        content["payload"]["length"] = {"unicode_codepoint": 0, "utf8_byte": 0}
        dataset = ingest_records(speech_dataset(), [content], received_at=LATER)
        neutral = annotation_record()
        neutral["payload"].update(label="neutral", subject={"kind": "none", "id": None}, evidence=[])
        self.assertEqual(ingest_records(dataset, [neutral], received_at=LATER).records[-1]["payload"]["label"], "neutral")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            ingest_records(dataset, [annotation_record()], received_at=LATER)

    def test_evidence_units_bounds_duplicates_and_overlaps(self):
        annotation = annotation_record()
        annotation["payload"]["evidence"] = [
            {"unit": "unicode_codepoint", "start": 0, "end": 2},
            {"unit": "unicode_codepoint", "start": 2, "end": 4},
            {"unit": "utf8_byte", "start": 0, "end": 6},
        ]
        # Cross-unit spans are allowed; no correspondence with unseen bytes is inferred.
        result = ingest_records(content_dataset(), [annotation], received_at=LATER)
        self.assertEqual(len(result.records[-1]["payload"]["evidence"]), 3)
        invalid = [
            [],
            [{"unit": "unicode_codepoint", "start": 0, "end": 5}],
            [{"unit": "utf8_byte", "start": 0, "end": 13}],
            [{"unit": "utf16", "start": 0, "end": 1}],
            [{"unit": "unicode_codepoint", "start": True, "end": 1}],
            [{"unit": "unicode_codepoint", "start": 1, "end": 1}],
            [{"unit": "unicode_codepoint", "start": 0, "end": 2}] * 2,
            [{"unit": "unicode_codepoint", "start": 0, "end": 2}, {"unit": "unicode_codepoint", "start": 1, "end": 3}],
            [{"unit": "unicode_codepoint", "start": 0, "end": 1, "text": "private"}],
        ]
        for evidence in invalid:
            bad = annotation_record()
            bad["payload"]["evidence"] = evidence
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                ingest_records(content_dataset(), [bad], received_at=LATER)

    def test_label_subject_and_topic_domains_do_not_coerce_topics_to_people(self):
        for label in LABELS:
            annotation = annotation_record()
            annotation["payload"]["label"] = label
            if label in {"neutral", "uncertain"}:
                annotation["payload"].update(subject={"kind": "none", "id": None}, evidence=[])
            with self.subTest(label=label):
                self.assertEqual(ingest_records(content_dataset(), [annotation], received_at=LATER).records[-1]["payload"]["label"], label)
        topic = annotation_record()
        topic["payload"].update(subject={"kind": "topic", "id": "alice"}, topic="alice")
        self.assertEqual(ingest_records(content_dataset(), [topic], received_at=LATER).records[-1]["payload"]["subject"]["kind"], "topic")
        changes = [
            {"label": "hostility"}, {"label": []},
            {"subject": {"kind": "none", "id": None}},
            {"subject": {"kind": "person", "id": None}},
            {"subject": {"kind": "topic", "id": "proposal"}, "topic": None},
            {"subject": {"kind": "topic", "id": "proposal"}, "topic": "different"},
            {"taxonomy": {"id": TAXONOMY["id"], "version": "2"}},
            {"method": {"kind": "llm", "id": "model", "version": "1"}},
        ]
        for change in changes:
            bad = annotation_record()
            bad["payload"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                ingest_records(content_dataset(), [bad], received_at=LATER)

    def test_person_subjects_need_live_person_identity_and_no_canonical_self_target(self):
        for subject in ("alice", "meeting", "unknown"):
            annotation = annotation_record()
            annotation["payload"]["subject"]["id"] = subject
            with self.subTest(subject=subject), self.assertRaises(ValueError):
                ingest_records(content_dataset(), [annotation], received_at=LATER)
        aliased = annotation_record()
        aliased["payload"]["subject"]["id"] = "alice-alias"
        dataset = ingest_records(content_dataset(), [aliased], received_at=LATER)
        merge = raw_record("merge", "identity.mapped", {"alias": "alice-alias", "canonical": "alice"})
        with self.assertRaisesRegex(ValueError, "annotation person subject.*self-target"):
            ingest_records(dataset, [merge], received_at=LATER)

    def test_stale_annotation_does_not_require_historical_speaker_to_stay_active(self):
        dataset = ingest_records(content_dataset(), [annotation_record()], received_at=LATER)
        retract_speech = raw_record("retract-speech", "interaction.observed", None,
                                    fact_id="speech", supersedes="speech", operation="retract")
        dataset = ingest_records(dataset, [retract_speech], received_at=LATER)
        retract_alice = raw_record("retract-alice", "entity.observed", None,
                                   fact_id="declare-alice", supersedes="declare-alice", operation="retract")
        result = ingest_records(dataset, [retract_alice], received_at=LATER)
        self.assertNotIn("alice", result.entities_at())
        self.assertIn("annotation-1", {r["record_id"] for r in result.as_known()})
        retract_bob = raw_record("retract-bob", "entity.observed", None,
                                 fact_id="declare-bob", supersedes="declare-bob", operation="retract")
        with self.assertRaisesRegex(ValueError, "known person"):
            ingest_records(result, [retract_bob], received_at=LATER)
        merge = raw_record("merge", "identity.mapped", {"alias": "bob", "canonical": "alice"})
        with self.assertRaisesRegex(ValueError, "annotation person subject.*self-target"):
            ingest_records(dataset, [merge], received_at=LATER)

    def test_scores_are_finite_uncalibrated_values_not_probabilities(self):
        for number in (-5.0, 0, 2.5):
            annotation = annotation_record()
            annotation["payload"]["score"] = {"kind": "uncalibrated", "value": number}
            result = ingest_records(content_dataset(), [annotation], received_at=LATER)
            self.assertEqual(result.records[-1]["payload"]["score"]["value"], number)
        invalid = [
            {"kind": "probability", "value": 0.9}, {"kind": "uncalibrated", "value": True},
            {"kind": "uncalibrated", "value": "0.9"}, {"kind": "uncalibrated", "value": float("nan")},
            {"kind": "uncalibrated", "value": float("inf")}, {"kind": "uncalibrated", "value": 10 ** 1000},
            {"kind": "uncalibrated", "value": 0.9, "calibrated": True},
        ]
        for score in invalid:
            annotation = annotation_record()
            annotation["payload"]["score"] = score
            with self.subTest(score_type=type(score["value"]).__name__), self.assertRaises(ValueError):
                ingest_records(content_dataset(), [annotation], received_at=LATER)

    def test_no_raw_text_extra_references_or_duration_records(self):
        for kind in ("content", "annotation"):
            raw = content_record() if kind == "content" else annotation_record()
            dataset = speech_dataset() if kind == "content" else content_dataset()
            for extra in ("text", "raw_text", "references"):
                bad = deepcopy(raw)
                bad["payload"][extra] = "not admitted"
                with self.subTest(kind=kind, extra=extra), self.assertRaises(ValueError):
                    ingest_records(dataset, [bad], received_at=LATER)
            raw["valid_interval"] = [0, 1]
            with self.assertRaisesRegex(ValueError, "instantaneous"):
                ingest_records(dataset, [raw], received_at=LATER)
        with tempfile.TemporaryDirectory() as directory:
            dataset = ingest_records(content_dataset(), [annotation_record()], received_at=LATER)
            path = Path(directory) / "annotations.json"
            serialized = json.dumps(dataset.to_dict())
            path.write_text(serialized, encoding="utf-8")
            self.assertEqual(load_event_dataset(path).content_hash, dataset.content_hash)
            path.write_text(serialized.replace('"kind": "human"', '"kind": "model", "kind": "human"', 1), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                load_event_dataset(path)


if __name__ == "__main__":
    unittest.main()
