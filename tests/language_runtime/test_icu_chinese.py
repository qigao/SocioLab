"""Actual ICU tests; the library path is explicit trusted configuration."""

from copy import deepcopy
from hashlib import sha256
import os
import unittest
from unittest.mock import patch

from sociolab.chinese_politeness import _digest, _tokens, extract_chinese_politeness
from sociolab.icu_chinese import segment_icu_chinese, extract_icu_chinese_politeness


def inputs(text):
    data = text.encode("utf-8")
    return {"interaction_record_id": "i1", "content_ref": "private-ref", "content_revision": "r1",
            "content_hash": "sha256:" + sha256(data).hexdigest(), "language": "zh",
            "length": {"unicode_codepoint": len(text), "utf8_byte": len(data)}}, data


def segment(text, record="c1"):
    return segment_icu_chinese(record, *inputs(text), library_path=os.environ["SOCIOLAB_ICU_LIBRARY"])


def words(text, report):
    return [[text[t["start"]:t["end"]] for t in s] for s in report["sentences"]]


class IcuChineseTests(unittest.TestCase):
    def test_actual_dictionary_words(self):
        text = "谢谢您。我们一起讨论。"
        report = segment(text)
        self.assertEqual(words(text, report), [["谢谢", "您", "。"], ["我们", "一起", "讨论", "。"]])
        self.assertEqual(report["provider"]["icu_version"], [76, 1, 0, 0])
        self.assertEqual(report["provider"]["unicode_version"], [16, 0, 0, 0])

    def test_actual_utf16_offsets_after_supplementary_chars(self):
        text = "🙂谢谢您。\r\n我们一起讨论。𠀀！"
        report = segment(text)
        self.assertEqual(words(text, report), [["🙂", "谢谢", "您", "。"], ["我们", "一起", "讨论", "。"], ["𠀀", "！"]])
        self.assertEqual(report["sentences"][0][1], {"start": 1, "end": 3})
        self.assertEqual("".join(w for s in words(text, report) for w in s), "".join(c for c in text if not c.isspace()))

    def test_negation_segmented_without_semantic_claim(self):
        text = "我不保证。"
        report = segment(text)
        self.assertEqual(words(text, report), [["我不", "保证", "。"]])
        self.assertEqual(report["qualification_status"], "NOT_ESTABLISHED")
        self.assertNotIn("label", report)

    def test_exact_source_offsets_combining_whitespace_and_punctuation(self):
        for text in ("\t你好 e\u0301！\n🙂", "  谢谢\r\n您。 ", "你\x00好！", "👩\u200d💻中文。"):
            with self.subTest(text=text):
                report = segment(text)
                _tokens(text, report["sentences"])
                self.assertEqual("".join(w for s in words(text, report) for w in s), "".join(c for c in text if not c.isspace()))
                self.assertEqual(report["source_sentences"][0]["start"], 0)
                self.assertEqual(report["source_sentences"][-1]["end"], len(text))

    def test_locale_resolution_reported(self):
        report = segment("谢谢。")
        for row in [report["sentence_break"], report["source_sentences"][0]["word_break"]]:
            self.assertEqual(row["valid_locale"], "zh")
            self.assertIn("actual_locale", row)
            self.assertLessEqual(row["open_status"], 0)

    def test_result_bound_to_input_and_private(self):
        content, data = inputs("谢谢您。")
        before = deepcopy(content)
        report = segment_icu_chinese("c1", content, data, library_path=os.environ["SOCIOLAB_ICU_LIBRARY"])
        self.assertEqual(content, before)
        self.assertEqual(report, segment("谢谢您。"))
        self.assertNotEqual(report["content_hash_of_result"], segment("谢谢您。", "c2")["content_hash_of_result"])
        self.assertEqual(report["segmentation_hash"], _digest(report["sentences"]))
        self.assertNotIn("谢谢", str(report))
        self.assertNotIn("private-ref", str(report))

    def test_hash_and_language_checked_before_library(self):
        content, data = inputs("谢谢。")
        with patch("sociolab.icu_chinese._Icu") as provider:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                segment_icu_chinese("c1", content, "抱歉。".encode(), library_path="invalid")
            content["language"] = "en"
            with self.assertRaisesRegex(ValueError, "language zh"):
                segment_icu_chinese("c1", content, data, library_path="invalid")
            provider.assert_not_called()

    def test_blank_oversize_and_missing_library_fail(self):
        for text in ("", " \r\n\t", "a" * 1_048_577):
            with self.subTest(length=len(text)), self.assertRaisesRegex(ValueError, "nonblank text"):
                segment(text)
        content, data = inputs("谢谢。")
        with self.assertRaisesRegex(ValueError, "absolute library path"):
            segment_icu_chinese("c1", content, data, library_path="libicuuc.so")
        with self.assertRaises(FileNotFoundError):
            segment_icu_chinese("c1", content, data, library_path="/no-such-sociolab-icu.so")

    def test_actual_composed_providers(self):
        text = "谢谢您。我们一起讨论。"
        content, data = inputs(text)
        result = extract_icu_chinese_politeness("c1", content, data, library_path=os.environ["SOCIOLAB_ICU_LIBRARY"])
        features = result["features"]
        self.assertEqual({k for k, v in features["features"].items() if v}, {"gratitude", "together", "you_honorific"})
        self.assertEqual(features["segmentation"]["hash"], result["segmentation"]["segmentation_hash"])
        self.assertEqual(features, extract_chinese_politeness("c1", content, data, result["segmentation"]["sentences"]))
        self.assertFalse(features["semantic_annotation_created"])

    def test_actual_character_baseline_changes_features(self):
        text = "谢谢您。"
        content, data = inputs(text)
        result = extract_icu_chinese_politeness("c1", content, data, library_path=os.environ["SOCIOLAB_ICU_LIBRARY"])
        baseline = extract_chinese_politeness("c1", content, data, [[{"start": i, "end": i + 1} for i in range(len(text))]])
        self.assertEqual((result["features"]["features"]["gratitude"], baseline["features"]["gratitude"]), (1, 0))
        self.assertEqual(result["features"]["content_hash"], baseline["content_hash"])

    def test_actual_negated_promise_and_disagreement(self):
        for text, expected in (("我不保证。", {"promise"}), ("我不同意这个方案。", set())):
            with self.subTest(text=text):
                result = extract_icu_chinese_politeness("c1", *inputs(text), library_path=os.environ["SOCIOLAB_ICU_LIBRARY"])
                self.assertEqual({k for k, v in result["features"]["features"].items() if v}, expected)
                self.assertFalse(result["features"]["semantic_annotation_created"])

    def test_composition_preserves_existing_feature_input(self):
        content, data = inputs("谢谢您。")
        expected = segment("谢谢您。")
        # This test checks only composition; no mock result is treated as
        # actual language feature execution.
        with patch("sociolab.icu_chinese.extract_chinese_politeness", return_value={"fixture": True}) as feature:
            result = extract_icu_chinese_politeness("c1", content, data, library_path=os.environ["SOCIOLAB_ICU_LIBRARY"])
            feature.assert_called_once_with("c1", content, data, expected["sentences"])
        self.assertEqual(result["segmentation"], expected)
        self.assertEqual(result["features"], {"fixture": True})
        self.assertEqual(result["qualification_status"], "NOT_ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
