"""Optional ICU 76.1 research tokenizer for verified Chinese utterances."""

from __future__ import annotations

import ctypes as c
from hashlib import sha256
from pathlib import Path
import sys

from .annotation_text import verify_content_bytes
from .chinese_politeness import _digest, _tokens, extract_chinese_politeness


_VERSION = (76, 1, 0, 0)
_UNICODE = (16, 0, 0, 0)
_MAX_BYTES = 1_048_576
_UCHAR = c.POINTER(c.c_uint16)
_ERROR = c.POINTER(c.c_int32)
_VER = c.POINTER(c.c_uint8)


class _Icu:
    def __init__(self, library_path: str | Path):
        # The path is trusted operator configuration, never a content reference.
        path = Path(library_path)
        if not path.is_absolute():
            raise ValueError("ICU requires an explicit absolute library path")
        path = path.resolve(strict=True)
        binary_hash = "sha256:" + sha256(path.read_bytes()).hexdigest()
        self.lib = c.CDLL(str(path))
        self.open = self._fn("ubrk_open", [c.c_int, c.c_char_p, _UCHAR, c.c_int32, _ERROR], c.c_void_p)
        self.close = self._fn("ubrk_close", [c.c_void_p], None)
        self.first = self._fn("ubrk_first", [c.c_void_p], c.c_int32)
        self.next = self._fn("ubrk_next", [c.c_void_p], c.c_int32)
        self.locale = self._fn("ubrk_getLocaleByType", [c.c_void_p, c.c_int, _ERROR], c.c_char_p)
        version = (c.c_uint8 * 4)()
        self._fn("u_getVersion", [_VER], None)(version)
        icu_version = tuple(version)
        self._fn("u_getUnicodeVersion", [_VER], None)(version)
        unicode_version = tuple(version)
        error = c.c_int32()
        self._fn("u_getDataVersion", [_VER, _ERROR], None)(version, c.byref(error))
        self._check(error, "u_getDataVersion")
        data_version = tuple(version)
        if (icu_version, unicode_version, data_version) != (_VERSION, _UNICODE, _VERSION):
            raise ValueError("expected ICU 76.1, Unicode 16.0 and ICU data 76.1")
        default_locale = self._fn("uloc_getDefault", [], c.c_char_p)().decode("ascii")
        self.identity = {
            "id": "icu4c.breakiterator.zh", "icu_version": list(icu_version),
            "unicode_version": list(unicode_version), "data_version": list(data_version),
            "data_version_status": error.value, "library_file_hash": binary_hash,
            "requested_locale": "zh", "default_locale": default_locale,
            "profile": "sentence_then_word_v1",
        }

    def _fn(self, name, args, result):
        fn = getattr(self.lib, name + "_76")
        fn.argtypes, fn.restype = args, result
        return fn

    @staticmethod
    def _check(error, operation):
        # ICU negative codes are warnings, not failures. Retain the warning.
        if error.value > 0:
            raise ValueError(f"ICU {operation} failed: {error.value}")

    def ranges(self, text: str, kind: int):
        utf16 = text.encode("utf-16-le" if sys.byteorder == "little" else "utf-16-be")
        units = (c.c_uint16 * (len(utf16) // 2)).from_buffer_copy(utf16)
        # ICU reports UTF-16 positions, whereas the journal uses codepoints.
        boundaries = {0: 0}
        position = 0
        for index, char in enumerate(text, 1):
            position += 2 if ord(char) > 0xffff else 1
            boundaries[position] = index
        error = c.c_int32()
        iterator = self.open(kind, b"zh", units, len(units), c.byref(error))
        if not iterator:
            raise ValueError(f"ICU ubrk_open failed: {error.value}")
        try:
            self._check(error, "ubrk_open")
            audit = {"open_status": error.value}
            for name, mode in (("actual_locale", 0), ("valid_locale", 1)):
                error = c.c_int32()
                locale = self.locale(iterator, mode, c.byref(error))
                self._check(error, "ubrk_getLocaleByType")
                audit[name] = locale.decode("ascii")
                audit[name + "_status"] = error.value
            start = self.first(iterator)
            if start != 0:
                raise ValueError("ICU first boundary is not zero")
            ranges = []
            while (end := self.next(iterator)) != -1:
                if not start < end or end not in boundaries:
                    raise ValueError("ICU returned invalid UTF-16 boundary")
                ranges.append((boundaries[start], boundaries[end]))
                start = end
            if start != len(units):
                raise ValueError("ICU boundaries do not cover the source")
            return ranges, audit
        finally:
            self.close(iterator)


def segment_icu_chinese(content_record_id: str, content: dict, data: bytes, *, library_path: str | Path) -> dict:
    """Return private token offsets and provider provenance; no text or labels.

    Caller selects the authorized current record. This experimental profile is
    pinned to ICU 76.1; no fallback tokenizer or automatic library discovery.
    """
    if type(content_record_id) is not str or not content_record_id or content_record_id.strip() != content_record_id:
        raise ValueError("content record ID must be nonempty trimmed text")
    text = verify_content_bytes(content, data)
    if content["language"] != "zh":
        raise ValueError("this profile requires declared language zh")
    if len(data) > _MAX_BYTES or not text.strip():
        raise ValueError("ICU profile requires nonblank text of at most 1048576 UTF-8 bytes")
    icu = _Icu(library_path)
    sentence_ranges, sentence_audit = icu.ranges(text, 3)  # UBRK_SENTENCE
    sentences, source_sentences = [], []
    for start, end in sentence_ranges:
        words, audit = icu.ranges(text[start:end], 1)  # UBRK_WORD
        spans = [{"start": start + a, "end": start + b} for a, b in words
                 if not text[start + a:start + b].isspace()]
        source_sentences.append({"start": start, "end": end, "word_break": audit,
                                 "output_sentence_index": len(sentences) if spans else None})
        if spans:
            sentences.append(spans)
    _tokens(text, sentences)  # Use the existing feature input coverage contract.
    result = {
        "schema": "sociolab.icu-chinese-segmentation.v1",
        "content_record_id": content_record_id, "content_revision": content["content_revision"],
        "content_hash": content["content_hash"], "interaction_record_id": content["interaction_record_id"],
        "provider": icu.identity, "unit": "unicode_codepoint", "sentence_break": sentence_audit,
        "source_sentences": source_sentences, "sentences": sentences,
        "segmentation_hash": _digest(sentences), "qualification_status": "NOT_ESTABLISHED",
    }
    result["content_hash_of_result"] = _digest(result)
    return result


def extract_icu_chinese_politeness(content_record_id: str, content: dict, data: bytes, *, library_path: str | Path) -> dict:
    """Compose both upstream providers without changing the original feature schema."""
    segmentation = segment_icu_chinese(content_record_id, content, data, library_path=library_path)
    features = extract_chinese_politeness(content_record_id, content, data, segmentation["sentences"])
    result = {"schema": "sociolab.icu-chinese-politeness.v1", "segmentation": segmentation,
              "features": features, "qualification_status": "NOT_ESTABLISHED"}
    result["content_hash_of_result"] = _digest(result)
    return result
