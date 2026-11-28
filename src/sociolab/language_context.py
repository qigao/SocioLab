"""Private, receipt-bound language input selection; no semantic inference."""

from __future__ import annotations

from hashlib import sha256
import json

from .annotation_text import verify_content_bytes


MAX_PRECEDING = 8
MAX_BYTES = 1_048_576


def _digest(value: object) -> str:
    return "sha256:" + sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _identifier(value: object) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("expected a nonempty trimmed identifier")
    value.encode("utf-8", errors="strict")


def _select(report: dict, records: dict, *, parse_source_time, knowledge_cutoff: int,
            target_record_id: str, preceding_record_ids: list[str], conversation: dict,
            original_bytes: dict[str, bytes]) -> dict:
    """Internal selection over an authoritative report and its exact prefix."""
    _identifier(target_record_id)
    if type(preceding_record_ids) is not list or len(preceding_record_ids) > MAX_PRECEDING:
        raise ValueError("preceding context exceeds the declared limit")
    ids = [*preceding_record_ids, target_record_id]
    for rid in ids:
        _identifier(rid)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate selected content record")
    if type(original_bytes) is not dict or set(original_bytes) != set(ids):
        raise ValueError("exact authorized bytes required for each selected record only")
    if any(type(data) is not bytes for data in original_bytes.values()):
        raise ValueError("source content must be exact bytes")
    if sum(map(len, original_bytes.values())) > MAX_BYTES:
        raise ValueError("selected content exceeds the declared byte limit")
    fields = {"id", "revision", "source_ref", "interaction_record_ids"}
    if type(conversation) is not dict or set(conversation) != fields:
        raise ValueError("explicit conversation membership declaration required")
    for name in ("id", "revision", "source_ref"):
        _identifier(conversation[name])
    members = conversation["interaction_record_ids"]
    if type(members) is not list:
        raise ValueError("conversation members must be an ordered list")
    for member in members:
        _identifier(member)
    current = {row["record_id"]: row for row in report["current_contents"]}
    if any(rid not in current for rid in ids):
        raise ValueError("selected content is not current and unambiguous at the cutoff")
    if members != [current[rid]["interaction_record_id"] for rid in ids]:
        raise ValueError("declared conversation members must exactly match selected interactions")
    if len(set(members)) != len(members):
        raise ValueError("duplicate selected interaction")
    previous = None
    entries = []
    for rid in ids:
        row = current[rid]
        occurred = parse_source_time(row["occurred_at"])
        if previous is not None and occurred <= previous:
            raise ValueError("context requires strictly preceding source times; ties are unresolved")
        previous = occurred
        payload = records[rid]["payload"]
        text = verify_content_bytes(payload, original_bytes[rid])
        if not text.strip():
            raise ValueError("selected content is blank")
        if rid == target_record_id and payload["language"] != "zh":
            raise ValueError("target requires declared language zh")
        entries.append({
            "role": "target" if rid == target_record_id else "preceding",
            "content_record_id": rid, "interaction_record_id": row["interaction_record_id"],
            "content_revision": payload["content_revision"], "content_hash": payload["content_hash"],
            "language": payload["language"], "length": dict(payload["length"]),
            "occurred_at": row["occurred_at"], "actor": row["actor"], "addressee": row["addressee"],
            "interaction_topic": row["interaction_topic"], "interaction_action": row["interaction_action"],
        })
    result = {
        "schema": "sociolab.language-context.v1", "knowledge_cutoff": knowledge_cutoff,
        "dataset": dict(report["input"]["dataset"]),
        "conversation": {"id": conversation["id"], "revision": conversation["revision"],
            "source_ref": conversation["source_ref"], "interaction_record_ids": list(members),
            "membership_status": "CALLER_DECLARED_NOT_AUTHENTICATED"},
        "entries": entries, "context_completeness": "NOT_ESTABLISHED",
        "qualification_status": "NOT_ESTABLISHED", "semantic_annotation_created": False,
    }
    result["context_hash"] = _digest(result)
    return result


def bind_language_context(dataset, *, knowledge_cutoff: int, target_record_id: str,
                          preceding_record_ids: list[str], conversation: dict,
                          original_bytes: dict[str, bytes]) -> dict:
    """Bind selected current records and explicit past context at one receipt prefix.

    No content retrieval, conversation inference or raw text in the result. The
    caller declares membership; the journal has no conversation identity field.
    A later cutoff may yield retrospective, not occurrence-time, evidence.
    """
    from .annotations import annotation_report
    from .events import EventDataset, parse_time

    if not isinstance(dataset, EventDataset) or type(knowledge_cutoff) is not int:
        raise ValueError("an EventDataset and explicit integer receipt cutoff are required")
    report = annotation_report(dataset, knowledge_cutoff=knowledge_cutoff)
    records = {r["record_id"]: r for r in dataset.records[:knowledge_cutoff]}
    clock = dataset.clock
    return _select(report, records, parse_source_time=lambda value: parse_time(value, clock),
        knowledge_cutoff=knowledge_cutoff, target_record_id=target_record_id,
        preceding_record_ids=preceding_record_ids, conversation=conversation,
        original_bytes=original_bytes)
