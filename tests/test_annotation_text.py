from copy import deepcopy
from hashlib import sha256
import unittest

from sociolab.annotation_text import verify_annotation_evidence, verify_content_bytes


TEXT = "中A🙂e\u0301\r\n"
DATA = TEXT.encode("utf-8")


def content(data=DATA, count=len(TEXT)):
    return {
        "interaction_record_id": "fictional-interaction", "content_ref": "private-reference",
        "content_revision": "r1", "content_hash": "sha256:" + sha256(data).hexdigest(),
        "language": "zh", "length": {"unicode_codepoint": count, "utf8_byte": len(data)},
    }


def annotation(spans, metadata=None):
    metadata = content() if metadata is None else metadata
    return {
        "target_record_id": "fictional-content", "target_content_revision": metadata["content_revision"],
        "target_content_hash": metadata["content_hash"],
        "method": {"kind": "human", "id": "fixture", "version": "1"},
        "taxonomy": {"id": "sociolab.social-actions", "version": "1"},
        "label": "uncertain", "subject": {"kind": "none", "id": None},
        "topic": None, "evidence": spans, "score": None,
    }


def verify(spans, metadata=None, data=DATA):
    metadata = content() if metadata is None else metadata
    return verify_annotation_evidence("fictional-content", metadata, data, annotation(spans, metadata))


class AnnotationTextTests(unittest.TestCase):
    def test_exact_bytes(self):
        self.assertEqual(verify_content_bytes(content(), DATA), TEXT)

    def test_empty_text(self):
        self.assertEqual(verify_content_bytes(content(b"", 0), b""), "")
        self.assertEqual(verify([], content(b"", 0), b""), [])

    def test_preserve_bom_crlf_and_combining_characters(self):
        text = "\ufeff你\r\ne\u0301"
        self.assertEqual(verify_content_bytes(content(text.encode(), len(text)), text.encode()), text)

    def test_wrong_byte_length(self):
        with self.assertRaisesRegex(ValueError, "byte length mismatch"):
            verify_content_bytes(content(), DATA[:-1])

    def test_wrong_hash_same_lengths(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_content_bytes(content(), DATA.replace(b"A", b"B"))

    def test_invalid_utf8_with_matching_hash(self):
        with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
            verify_content_bytes(content(b"\xff", 1), b"\xff")

    def test_wrong_declared_codepoint_length(self):
        with self.assertRaisesRegex(ValueError, "codepoint length mismatch"):
            verify_content_bytes(content(DATA, len(TEXT) + 1), DATA)

    def test_no_implicit_text_or_mutable_buffer(self):
        for value in (TEXT, bytearray(DATA), memoryview(DATA)):
            with self.subTest(type=type(value)), self.assertRaisesRegex(ValueError, "exact bytes"):
                verify_content_bytes(content(), value)

    def test_metadata_schema_is_reused(self):
        metadata = content()
        metadata["text"] = TEXT
        with self.assertRaisesRegex(ValueError, "declared fields"):
            verify_content_bytes(metadata, DATA)

    def test_exact_record_and_revision_and_hash(self):
        for field, replacement in (("target_record_id", "another-record"),
                                   ("target_content_revision", "r2"),
                                   ("target_content_hash", "sha256:" + "0" * 64)):
            candidate = annotation([])
            candidate[field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "exact content record"):
                verify_annotation_evidence("fictional-content", content(), DATA, candidate)

    def test_all_valid_spans_in_both_units(self):
        for start in range(len(TEXT)):
            for end in range(start + 1, len(TEXT) + 1):
                bs, be = len(TEXT[:start].encode()), len(TEXT[:end].encode())
                for unit, s, e in (("unicode_codepoint", start, end), ("utf8_byte", bs, be)):
                    with self.subTest(unit=unit, start=start, end=end):
                        self.assertEqual(verify([{"unit": unit, "start": s, "end": e}]), [{
                            "declared_unit": unit, "unicode_codepoint": {"start": start, "end": end},
                            "utf8_byte": {"start": bs, "end": be},
                        }])
                        self.assertEqual(DATA[bs:be].decode(), TEXT[start:end])

    def test_every_interior_byte_rejected_at_either_boundary(self):
        boundaries = {len(TEXT[:i].encode()) for i in range(len(TEXT) + 1)}
        for i in set(range(1, len(DATA))) - boundaries:
            for start, end in ((0, i), (i, len(DATA))):
                with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, "splits a UTF-8 codepoint"):
                    verify([{"unit": "utf8_byte", "start": start, "end": end}])

    def test_out_of_bounds(self):
        for unit, limit in content()["length"].items():
            with self.subTest(unit=unit), self.assertRaisesRegex(ValueError, "exceeds source content length"):
                verify([{"unit": unit, "start": 0, "end": limit + 1}])

    def test_original_order_and_cross_unit_equivalence(self):
        spans = [{"unit": "utf8_byte", "start": 4, "end": 8},
                 {"unit": "unicode_codepoint", "start": 2, "end": 3}]
        result = verify(spans)
        self.assertEqual([row["declared_unit"] for row in result], ["utf8_byte", "unicode_codepoint"])
        self.assertEqual(result[0]["utf8_byte"], result[1]["utf8_byte"])
        self.assertEqual(result[0]["unicode_codepoint"], result[1]["unicode_codepoint"])

    def test_annotation_schema_is_reused(self):
        spans = [{"unit": "utf8_byte", "start": 0, "end": 4},
                 {"unit": "utf8_byte", "start": 3, "end": 8}]
        with self.assertRaisesRegex(ValueError, "duplicate or overlap"):
            verify(spans)

    def test_inputs_not_modified_and_no_text_in_offsets(self):
        metadata = content()
        candidate = annotation([{"unit": "unicode_codepoint", "start": 0, "end": 1}], metadata)
        before = deepcopy((metadata, candidate))
        result = verify_annotation_evidence("fictional-content", metadata, DATA, candidate)
        self.assertEqual((metadata, candidate), before)
        self.assertEqual(set(result[0]), {"declared_unit", "unicode_codepoint", "utf8_byte"})
        self.assertEqual(result[0]["utf8_byte"], {"start": 0, "end": 3})


if __name__ == "__main__":
    unittest.main()
