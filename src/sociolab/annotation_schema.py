"""Shared strict annotation metadata; no text inference or event-state access."""

from __future__ import annotations

import math
import re


TAXONOMY = {"id": "sociolab.social-actions", "version": "1"}
LABELS = frozenset({
    "disagreement", "insult", "threat", "cooperation_commitment",
    "mediation", "support", "neutral", "uncertain",
})
CONTENT_FIELDS = frozenset({
    "interaction_record_id", "content_ref", "content_revision", "content_hash",
    "language", "length",
})
ANNOTATION_FIELDS = frozenset({
    "target_record_id", "target_content_revision", "target_content_hash",
    "method", "taxonomy", "label", "subject", "topic", "evidence", "score",
})
_UNITS = frozenset({"unicode_codepoint", "utf8_byte"})


def _fields(value: object, fields: set[str] | frozenset[str], name: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{name} requires exactly its declared fields")


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonempty, trimmed text")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"{name} must be valid UTF-8 text") from error
    return value


def _choice(value: object, choices: set[str] | frozenset[str], name: str) -> None:
    if type(value) is not str or value not in choices:
        raise ValueError(f"unsupported {name}")


def _integer(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _content_hash(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("content hash must be a lowercase sha256 fingerprint")


def validate_method(value: object) -> dict[str, str]:
    """Return a fresh exact method identity after validation."""
    _fields(value, {"kind", "id", "version"}, "annotation method")
    _choice(value["kind"], {"human", "rule", "model"}, "annotation method kind")
    _text(value["id"], "method ID")
    _text(value["version"], "method version")
    return dict(value)


def validate_taxonomy(value: object) -> dict[str, str]:
    """Admit the registered taxonomy, without accepting arbitrary label systems."""
    _fields(value, {"id", "version"}, "annotation taxonomy")
    if (type(value["id"]) is not str or type(value["version"]) is not str
            or value["id"] != "sociolab.social-actions" or value["version"] != "1"):
        raise ValueError("unsupported annotation taxonomy")
    return dict(value)


def validate_content_payload(value: object) -> None:
    """Validate declared lengths and fingerprints; external bytes stay unverified."""
    _fields(value, CONTENT_FIELDS, "content.observed payload")
    for name in ("interaction_record_id", "content_ref", "content_revision", "language"):
        _text(value[name], name)
    _content_hash(value["content_hash"])
    lengths = value["length"]
    _fields(lengths, _UNITS, "content length")
    for name in _UNITS:
        _integer(lengths[name], f"content length {name}")
    codepoints, octets = lengths["unicode_codepoint"], lengths["utf8_byte"]
    if not codepoints <= octets <= 4 * codepoints:
        raise ValueError("UTF-8 byte length must be between one and four times codepoint length")


def validate_annotation_payload(value: object) -> None:
    """Validate labels and spans; exact parent versions/bounds require the journal."""
    _fields(value, ANNOTATION_FIELDS, "annotation.recorded payload")
    _text(value["target_record_id"], "annotation target record")
    _text(value["target_content_revision"], "annotation target content revision")
    _content_hash(value["target_content_hash"])
    validate_method(value["method"])
    validate_taxonomy(value["taxonomy"])
    _choice(value["label"], LABELS, "annotation label")
    subject = value["subject"]
    _fields(subject, {"kind", "id"}, "annotation subject")
    _choice(subject["kind"], {"person", "topic", "none"}, "annotation subject kind")
    if subject["kind"] == "none":
        if subject["id"] is not None or value["label"] not in {"neutral", "uncertain"}:
            raise ValueError("only neutral/uncertain labels may have a null subject")
    else:
        _text(subject["id"], "annotation subject ID")
    if value["topic"] is not None:
        _text(value["topic"], "annotation topic")
    if subject["kind"] == "topic" and value["topic"] != subject["id"]:
        raise ValueError("a topic subject must match the annotation topic")
    evidence = value["evidence"]
    if type(evidence) is not list:
        raise ValueError("annotation evidence must be a JSON array")
    if not evidence and value["label"] not in {"neutral", "uncertain"}:
        raise ValueError("this annotation label requires evidence spans")
    by_unit: dict[str, list[tuple[int, int]]] = {unit: [] for unit in _UNITS}
    for span in evidence:
        _fields(span, {"unit", "start", "end"}, "evidence span")
        _choice(span["unit"], _UNITS, "evidence span unit")
        _integer(span["start"], "evidence start")
        _integer(span["end"], "evidence end")
        if span["end"] <= span["start"]:
            raise ValueError("evidence span must have positive length")
        by_unit[span["unit"]].append((span["start"], span["end"]))
    for spans in by_unit.values():
        ordered = sorted(spans)
        if any(right[0] < left[1] for left, right in zip(ordered, ordered[1:])):
            raise ValueError("evidence spans must not duplicate or overlap within a unit")
    score = value["score"]
    if score is not None:
        _fields(score, {"kind", "value"}, "annotation score")
        _choice(score["kind"], {"uncalibrated"}, "annotation score kind")
        number = score["value"]
        if type(number) not in (int, float):
            raise ValueError("annotation score must be a finite number")
        try:
            finite = math.isfinite(number)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("annotation score must be a finite number")
