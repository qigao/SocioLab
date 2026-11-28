"""Actual-provider tests; run with the pinned ConvoKit source available."""

from copy import deepcopy
from hashlib import sha256
import unittest
from unittest.mock import patch

from sociolab.chinese_politeness import extract_chinese_politeness


def inputs(sentences):
    text = "".join(word for sentence in sentences for word in sentence)
    data = text.encode("utf-8")
    content = {"interaction_record_id": "i1", "content_ref": "private-ref",
               "content_revision": "r1", "content_hash": "sha256:" + sha256(data).hexdigest(),
               "language": "zh", "length": {"unicode_codepoint": len(text), "utf8_byte": len(data)}}
    position, offsets = 0, []
    for sentence in sentences:
        spans = []
        for word in sentence:
            end = position + len(word)
            spans.append({"start": position, "end": end})
            position = end
        offsets.append(spans)
    return content, data, offsets


def extract(sentences):
    return extract_chinese_politeness("c1", *inputs(sentences))


class ChinesePolitenessTests(unittest.TestCase):
    def test_actual_gratitude_and_honorific(self):
        result = extract([["谢谢", "您", "。"]])
        self.assertEqual(len(result["features"]), 26)
        self.assertEqual({k for k, v in result["features"].items() if v}, {"gratitude", "you_honorific"})
        self.assertEqual(result["marker_token_coordinates"]["gratitude"], {"layout": "token_groups", "entries": [[[0, 0]]]})

    def test_actual_regex_layout(self):
        result = extract([["你", "可以", "考虑", "吗", "？"]])
        self.assertEqual(result["features"]["can_you"], 1)
        self.assertEqual(result["marker_token_coordinates"]["can_you"], {"layout": "flat_tokens", "entries": [[0, 0], [0, 1], [0, 2], [0, 3]]})

    def test_segmentation_changes_feature_and_identity(self):
        word = extract([["谢谢", "您", "。"]])
        chars = extract([["谢", "谢", "您", "。"]])
        self.assertEqual(word["content_hash"], chars["content_hash"])
        self.assertNotEqual(word["segmentation"]["hash"], chars["segmentation"]["hash"])
        self.assertEqual((word["features"]["gratitude"], chars["features"]["gratitude"]), (1, 0))

    def test_negation_is_not_commitment(self):
        result = extract([["我", "不", "保证", "。"]])
        self.assertEqual(result["features"]["promise"], 1)
        self.assertFalse(result["semantic_annotation_created"])
        self.assertEqual(result["qualification_status"], "NOT_ESTABLISHED")

    def test_disagreement_not_a_politeness_label(self):
        result = extract([["我", "不同意", "这个", "方案", "。"]])
        self.assertEqual({k for k, v in result["features"].items() if v}, {"start_i"})
        self.assertNotIn("label", result)

    def test_multiple_sentences_keep_positions(self):
        result = extract([["谢谢", "。"], ["抱歉", "。"]])
        self.assertEqual(result["marker_token_coordinates"]["apologetic"]["entries"], [[[1, 0]]])

    def test_exact_bytes_checked_before_provider(self):
        content, data, spans = inputs([["谢谢", "。"]])
        with patch("sociolab.chinese_politeness._provider") as provider:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                extract_chinese_politeness("c1", content, "抱歉。".encode(), spans)
            provider.assert_not_called()

    def test_language_checked_before_provider(self):
        content, data, spans = inputs([["谢谢", "。"]])
        content["language"] = "en"
        with patch("sociolab.chinese_politeness._provider") as provider:
            with self.assertRaisesRegex(ValueError, "language zh"):
                extract_chinese_politeness("c1", content, data, spans)
            provider.assert_not_called()

    def test_segmentation_rejects_omission_overlap_and_boolean(self):
        content, data, _ = inputs([["谢谢", "您", "。"]])
        for spans in ([[]], [[{"start": 1, "end": 4}]], [[{"start": 0, "end": 2}]],
                      [[{"start": 0, "end": 3}, {"start": 2, "end": 4}]],
                      [[{"start": False, "end": 4}]]):
            with self.subTest(spans=spans), self.assertRaises(ValueError):
                extract_chinese_politeness("c1", content, data, spans)

    def test_whitespace_may_be_omitted_not_inside_token(self):
        content, data, spans = inputs([["谢谢", " ", "您", "。"]])
        with self.assertRaisesRegex(ValueError, "contains whitespace"):
            extract_chinese_politeness("c1", content, data, spans)
        result = extract_chinese_politeness("c1", content, data, [[spans[0][i] for i in (0, 2, 3)]])
        self.assertEqual(result["features"]["gratitude"], 1)

    def test_deterministic_private_result_and_unmodified_inputs(self):
        args = inputs([["谢谢", "您", "。"]])
        before = deepcopy(args)
        first = extract_chinese_politeness("c1", *args)
        self.assertEqual(first, extract_chinese_politeness("c1", *args))
        self.assertEqual(args, before)
        self.assertNotIn("谢谢", str(first))
        self.assertNotIn("private-ref", str(first))
        self.assertNotEqual(first["content_hash_of_result"], extract_chinese_politeness("c2", *args)["content_hash_of_result"])

    def test_mismatched_upstream_files_fail(self):
        from unittest.mock import Mock
        root = Mock()
        root.joinpath.return_value.read_bytes.return_value = b"different"
        with patch("sociolab.chinese_politeness.resources.files", return_value=root):
            with self.assertRaisesRegex(ValueError, "source blob mismatch"):
                extract([["谢谢", "。"]])


if __name__ == "__main__":
    unittest.main()
