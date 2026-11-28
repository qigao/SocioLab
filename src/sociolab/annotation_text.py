"""Private exact-byte verification for the existing annotation contract."""

from __future__ import annotations

from hashlib import sha256

from .annotation_schema import validate_annotation_payload, validate_content_payload


def verify_content_bytes(content: dict, data: bytes) -> str:
    """Return strictly decoded text only after the declared hash and lengths match.

    The caller supplies authorized bytes for an exact content record. This does
    not dereference content_ref, authenticate the source or prove journal currency.
    The returned text is private; do not publish it in reports.
    """
    validate_content_payload(content)
    if type(data) is not bytes:
        raise ValueError("source content must be exact bytes")
    if len(data) != content["length"]["utf8_byte"]:
        raise ValueError("source byte length mismatch")
    if "sha256:" + sha256(data).hexdigest() != content["content_hash"]:
        raise ValueError("source content hash mismatch")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ValueError("source content is not valid UTF-8") from None
    if len(text) != content["length"]["unicode_codepoint"]:
        raise ValueError("source codepoint length mismatch")
    return text


def verify_annotation_evidence(
    content_record_id: str, content: dict, data: bytes, annotation: dict,
) -> list[dict]:
    """Verify exact target binding and map each declared span to both units.

    Keep original span order and unit; cross-unit duplicates remain separate.
    The result contains offsets only, not text or a semantic qualification.
    The caller must independently select current records at its receipt cutoff.
    """
    validate_annotation_payload(annotation)
    text = verify_content_bytes(content, data)
    if (annotation["target_record_id"] != content_record_id
            or annotation["target_content_revision"] != content["content_revision"]
            or annotation["target_content_hash"] != content["content_hash"]):
        raise ValueError("annotation does not bind the exact content record")

    boundaries = [0]
    for char in text:
        boundaries.append(boundaries[-1] + len(char.encode("utf-8")))
    byte_to_codepoint = {offset: i for i, offset in enumerate(boundaries)}
    verified = []
    for span in annotation["evidence"]:
        unit, start, end = span["unit"], span["start"], span["end"]
        if end > content["length"][unit]:
            raise ValueError("annotation evidence exceeds source content length")
        if unit == "unicode_codepoint":
            cp_start, cp_end = start, end
            byte_start, byte_end = boundaries[start], boundaries[end]
        else:
            if start not in byte_to_codepoint or end not in byte_to_codepoint:
                raise ValueError("annotation evidence splits a UTF-8 codepoint")
            byte_start, byte_end = start, end
            cp_start, cp_end = byte_to_codepoint[start], byte_to_codepoint[end]
        verified.append({
            "declared_unit": unit,
            "unicode_codepoint": {"start": cp_start, "end": cp_end},
            "utf8_byte": {"start": byte_start, "end": byte_end},
        })
    return verified
