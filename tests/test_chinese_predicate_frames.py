"""Replay real published syntax output; tests of structure, not held-out accuracy."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest

from sociolab.chinese_predicate_frames import collect_predicate_frames, _quote_ranges
from sociolab.chinese_syntax import _hash


ARCHIVE = Path(__file__).resolve().parents[1] / "docs/experiments/2026-11-28-syntax/native-run-1.json"


def archive_rows():
    report = json.loads(ARCHIVE.read_text(encoding="utf-8"))["report"]
    if report["result_hash"] != _hash({k: v for k, v in report.items() if k != "result_hash"}):
        raise ValueError("archived syntax run identity mismatch")
    return {row["case_id"]: row for row in report["rows"]}


def inputs(row):
    data = row["target"].encode("utf-8")
    evidence = row["evidence"]
    content = {"interaction_record_id": evidence["interaction_record_id"],
        "content_ref": "fictional-archive", "content_revision": evidence["content_revision"],
        "content_hash": "sha256:" + sha256(data).hexdigest(), "language": "zh",
        "length": {"unicode_codepoint": len(row["target"]), "utf8_byte": len(data)}}
    return evidence["content_record_id"], content, data, evidence


def collect(row):
    return collect_predicate_frames(*inputs(row))


def surface(row, coord):
    return row["target"][coord["start"]:coord["end"]]


def frames_for(row, predicate):
    return [f for f in collect(row)["frames"] if surface(row, f["predicate"]) == predicate]


class QuoteRangeTests(unittest.TestCase):
    def test_nested_and_separate_quotes(self):
        text = "“甲‘乙’丙”与「丁」"
        result = _quote_ranges(text)
        self.assertEqual(result["status"], "BALANCED")
        self.assertEqual([text[q["start"]:q["end"]] for q in result["ranges"]],
                         ["“甲‘乙’丙”", "‘乙’", "「丁」"])

    def test_unbalanced_or_unsupported_not_guessed(self):
        for text in ("“甲", "‘甲”", "甲’"):
            self.assertEqual(_quote_ranges(text), {"status": "UNBALANCED", "ranges": []})
        self.assertEqual(_quote_ranges('"甲"')["status"], "UNSUPPORTED_DELIMITER")


class RealParseReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = archive_rows()

    def test_all_18_exact_outputs_replayed(self):
        self.assertEqual(len(self.rows), 18)
        for cid, row in self.rows.items():
            with self.subTest(cid=cid):
                result = collect(row)
                self.assertTrue(result["frames"])
                self.assertFalse(result["semantic_annotation_created"])
                self.assertEqual(result["syntax_result_hash"], row["evidence"]["result_hash"])
                self.assertTrue(all(f["assertion_status"] == "NOT_ESTABLISHED" and
                    f["semantic_topic"] is None for f in result["frames"]))
                self.assertEqual(result, collect(row))
                self.assertNotIn(row["target"], json.dumps(result, ensure_ascii=False))

    def test_direct_and_named_subject_candidates(self):
        direct, reported = self.rows["direct"], self.rows["reported"]
        a, = frames_for(direct, "反对")
        b, = frames_for(reported, "反对")
        self.assertEqual(a["holder_candidate"]["role"], "SOURCE_SPEAKER_CANDIDATE")
        self.assertEqual(surface(direct, a["holder_candidate"]["coordinate"]), "我")
        self.assertEqual(b["holder_candidate"]["role"], "EXPLICIT_SUBJECT_HEAD")
        self.assertEqual(surface(reported, b["holder_candidate"]["coordinate"]), "小陈")

    def test_quote_crosses_parser_sentence_boundary(self):
        row = self.rows["quoted"]
        self.assertEqual(len(row["evidence"]["sentences"]), 2)
        frame, = frames_for(row, "反对")
        self.assertEqual(surface(row, frame["direct_subjects"][0]), "我")
        self.assertEqual(frame["holder_candidate"]["role"], "QUOTE_GOVERNOR_SUBJECT_CANDIDATE")
        self.assertEqual(surface(row, frame["holder_candidate"]["coordinate"]), "小陈")
        self.assertEqual(surface(row, frame["quote_ranges"][0]), "‘我反对这个提议。’")

    def test_multiple_predicates_and_embedded_scope(self):
        row = self.rows["both"]
        first, second = frames_for(row, "反对")
        self.assertEqual(first["holder_candidate"]["role"], "EXPLICIT_SUBJECT_HEAD")
        self.assertEqual(second["holder_candidate"]["role"], "SOURCE_SPEAKER_CANDIDATE")
        row = self.rows["reported-negation"]
        frame, = frames_for(row, "反对")
        self.assertEqual(frame["holder_candidate"]["role"], "UNRESOLVED")
        self.assertEqual(surface(row, frame["direct_subjects"][0]), "他")

    def test_negation_and_modality_retained_not_interpreted(self):
        row = self.rows["explicit-disagreement"]
        frame, = frames_for(row, "同意")
        self.assertIn("不", [surface(row, w) for w in frame["modifiers"]])
        row = self.rows["denial"]
        frame, = frames_for(row, "反对")
        self.assertEqual(frame["holder_candidate"]["role"], "UNRESOLVED")
        self.assertEqual(surface(row, frame["ancestors"][0]["head"]), "没有")
        row = self.rows["conditional"]
        frame, = frames_for(row, "反对")
        self.assertIn("如果", [surface(row, w) for w in frame["modifiers"]])
        self.assertEqual(frame["assertion_status"], "NOT_ESTABLISHED")

    def test_digest_revision_and_rehashed_bad_tree(self):
        rid, payload, data, evidence = inputs(self.rows["direct"])
        with self.assertRaisesRegex(ValueError, "exact content"):
            collect_predicate_frames("different", payload, data, evidence)
        altered = deepcopy(evidence)
        altered["sentences"][0][0]["head"] = 1
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            collect_predicate_frames(rid, payload, data, altered)
        altered["result_hash"] = _hash({k: v for k, v in altered.items() if k != "result_hash"})
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            collect_predicate_frames(rid, payload, data, altered)
        changed = {**payload, "content_revision": "2"}
        with self.assertRaisesRegex(ValueError, "exact content"):
            collect_predicate_frames(rid, changed, data, evidence)
