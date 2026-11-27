"""Describe source-supplied annotations bound to exact historical content.

No raw text is read and no classifier is run. A current label is an available
source decision, not an independently validated fact about a person or relation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json

from .annotation_schema import LABELS, TAXONOMY, validate_method, validate_taxonomy
from .events import EventDataset


_STATUSES = (
    "CURRENT", "STALE_CONTENT", "STALE_INTERACTION",
    "AMBIGUOUS_CONTENT", "AMBIGUOUS_ANNOTATION",
)


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _profile(payload: dict) -> tuple[str, ...]:
    method, taxonomy = payload["method"], payload["taxonomy"]
    return (payload["target_record_id"], method["kind"], method["id"], method["version"],
            taxonomy["id"], taxonomy["version"])


def annotation_report(
    dataset: EventDataset, *, knowledge_cutoff: int | None = None,
    method: dict | None = None, taxonomy: dict | None = None,
) -> dict[str, object]:
    """Report effective annotations and current exact contents at one receipt prefix.

    Filters match the complete method/taxonomy objects, including versions.
    Content availability and duplicate decisions are assessed before filtering.
    A new record ID invalidates the old binding even if its content hash matches.

    ``annotations`` contains only effective annotation assertions. Withdrawn
    content/interaction records remain available as historical context. When
    several conditions apply, the primary status is stale content, stale
    interaction, ambiguous content, then ambiguous annotation; ``issues`` keeps
    every applicable condition. Displayed event time is the interaction's time.
    """
    if not isinstance(dataset, EventDataset):
        raise ValueError("annotation analysis requires an EventDataset")
    selected_method = None if method is None else validate_method(method)
    selected_taxonomy = None if taxonomy is None else validate_taxonomy(taxonomy)
    records = dataset.records
    cutoff = len(records) if knowledge_cutoff is None else knowledge_cutoff
    active = dataset.as_known(cutoff)  # Also validates the exact receipt cutoff.
    prefix = list(records[:cutoff])
    by_id = {record["record_id"]: record for record in prefix}
    active_ids = {record["record_id"] for record in active}
    identities = dataset.identity_map_at(cutoff)
    successors, fact_heads = {}, {}
    for record in prefix:
        if record["supersedes"] is not None:
            successors[record["supersedes"]] = record
        fact_heads[(record["source"]["system"], record["fact_id"])] = record

    active_annotations = [r for r in active if r["kind"] == "annotation.recorded"]
    active_contents = [r for r in active if r["kind"] == "content.observed"]
    contents_by_interaction = defaultdict(list)
    for record in active_contents:
        interaction_id = record["payload"]["interaction_record_id"]
        if interaction_id in active_ids:
            contents_by_interaction[interaction_id].append(record["record_id"])
    annotations_by_profile = defaultdict(list)
    for record in active_annotations:
        annotations_by_profile[_profile(record["payload"])].append(record["record_id"])

    def canonical(actor: str) -> str:
        return identities.get(actor, actor)

    def withdrawn_issue(record: dict, parent: str) -> dict | None:
        if record["record_id"] in active_ids:
            return None
        successor = successors.get(record["record_id"])
        head = fact_heads[(record["source"]["system"], record["fact_id"])]
        # The immutable direct successor explains how this exact record stopped
        # being effective, even if a later head was itself replaced/retracted.
        reason = "retracted" if successor is not None and successor["operation"] == "retract" else "superseded"
        return {
            "status": f"STALE_{parent.upper()}", "reason": f"{parent}_{reason}",
            "record_id": record["record_id"],
            "invalidated_by_record_id": None if successor is None else successor["record_id"],
            "fact_head_record_id": head["record_id"], "fact_head_operation": head["operation"],
        }

    def describe_content(record: dict) -> dict:
        payload = record["payload"]
        interaction = by_id[payload["interaction_record_id"]]
        action = interaction["payload"]
        issues = []
        for parent, subject_record in (("content", record), ("interaction", interaction)):
            issue = withdrawn_issue(subject_record, parent)
            if issue is not None:
                issues.append(issue)
        competing = contents_by_interaction.get(interaction["record_id"], [])
        if record["record_id"] in active_ids and len(competing) > 1:
            issues.append({
                "status": "AMBIGUOUS_CONTENT",
                "reason": "multiple_effective_contents_for_interaction",
                "interaction_record_id": interaction["record_id"],
                "conflicting_content_record_ids": list(competing),
            })
        return {
            "status": issues[0]["status"] if issues else "CURRENT",
            "reason": issues[0]["reason"] if issues else None, "issues": issues,
            "record_id": record["record_id"], "fact_id": record["fact_id"],
            "interaction_record_id": interaction["record_id"],
            "actor": canonical(action["actor"]), "addressee": canonical(action["target"]),
            "source_actor": action["actor"], "source_addressee": action["target"],
            "occurred_at": interaction["occurred_at"],
            "interaction_action": action["action"], "interaction_topic": action["topic"],
            "content_ref": payload["content_ref"], "content_revision": payload["content_revision"],
            "content_hash": payload["content_hash"], "language": payload["language"],
            "length": deepcopy(payload["length"]), "source": deepcopy(record["source"]),
            "evidence_record_ids": [interaction["record_id"], record["record_id"]],
        }

    # Include inactive metadata only when an effective annotation still refers
    # to it. All active metadata are reported, including unlabelled contents.
    relevant_content_ids = {r["record_id"] for r in active_contents}
    relevant_content_ids.update(r["payload"]["target_record_id"] for r in active_annotations)
    descriptions = {
        record_id: describe_content(by_id[record_id])
        for record_id in sorted(relevant_content_ids, key=lambda rid: by_id[rid]["ingest_seq"])
    }
    current_contents = [deepcopy(row) for row in descriptions.values() if row["status"] == "CURRENT"]
    content_issues = [deepcopy(row) for row in descriptions.values() if row["status"] != "CURRENT"]

    rows = []
    for record in active_annotations:
        payload = record["payload"]
        if selected_method is not None and payload["method"] != selected_method:
            continue
        if selected_taxonomy is not None and payload["taxonomy"] != selected_taxonomy:
            continue
        content = descriptions[payload["target_record_id"]]
        issues = deepcopy(content["issues"])
        competing = annotations_by_profile[_profile(payload)]
        if content["status"] == "CURRENT" and len(competing) > 1:
            issues.append({
                "status": "AMBIGUOUS_ANNOTATION",
                "reason": "multiple_effective_annotations_for_profile",
                "target_record_id": payload["target_record_id"],
                "conflicting_annotation_record_ids": list(competing),
            })
        subject = deepcopy(payload["subject"])
        if subject["kind"] == "person":
            subject["id"] = canonical(subject["id"])
        rows.append({
            "status": issues[0]["status"] if issues else "CURRENT",
            "reason": issues[0]["reason"] if issues else None, "issues": issues,
            "record_id": record["record_id"], "fact_id": record["fact_id"],
            "target_record_id": payload["target_record_id"],
            "target_content_revision": payload["target_content_revision"],
            "target_content_hash": payload["target_content_hash"],
            "interaction_record_id": content["interaction_record_id"],
            "actor": content["actor"], "addressee": content["addressee"],
            "source_actor": content["source_actor"], "source_addressee": content["source_addressee"],
            "occurred_at": content["occurred_at"],
            "interaction_action": content["interaction_action"], "interaction_topic": content["interaction_topic"],
            "content_ref": content["content_ref"], "content_revision": content["content_revision"],
            "content_hash": content["content_hash"], "language": content["language"],
            "method": deepcopy(payload["method"]), "taxonomy": deepcopy(payload["taxonomy"]),
            "label": payload["label"], "subject": subject,
            "source_subject": deepcopy(payload["subject"]), "topic": payload["topic"],
            "evidence": deepcopy(payload["evidence"]), "score": deepcopy(payload["score"]),
            "source": deepcopy(record["source"]),
            "evidence_record_ids": [*content["evidence_record_ids"], record["record_id"]],
            "annotation_occurred_at": record["occurred_at"],
            "ingest_seq": record["ingest_seq"], "recorded_at": record["recorded_at"],
        })

    status_counts = Counter(row["status"] for row in rows)
    current = [row for row in rows if row["status"] == "CURRENT"]
    label_counts = Counter(row["label"] for row in current)
    annotated = {row["target_record_id"] for row in current}
    current_content_ids = [row["record_id"] for row in current_contents]
    prefix_dataset = dataset.to_dict()
    prefix_dataset["records"] = prefix
    return {
        "kind": "ANNOTATION_REPORT", "interpretation_status": "UNVALIDATED_SOURCE_LABELS",
        "input": {
            "dataset": {
                "dataset_id": dataset.dataset_id, "origin": dataset.origin,
                "source_revision": dataset.source_revision, "clock": dataset.clock,
                "content_hash": _hash(prefix_dataset), "known_records_hash": _hash(prefix),
            },
            "knowledge_cutoff": cutoff,
        },
        "filters": {"method": selected_method, "taxonomy": selected_taxonomy},
        "taxonomy_profile": deepcopy(TAXONOMY),
        "annotations": rows, "current_contents": current_contents, "content_issues": content_issues,
        "summary": {
            "active_annotation_count": len(active_annotations), "selected_annotation_count": len(rows),
            "status_counts": {status: status_counts[status] for status in _STATUSES},
            "current_annotation_count": len(current),
            "label_counts_current": {label: label_counts[label] for label in sorted(LABELS)},
            "current_content_count": len(current_contents), "content_issue_count": len(content_issues),
            "current_annotated_content_count": len(annotated),
            "current_contents_without_selected_current_annotation": [
                record_id for record_id in current_content_ids if record_id not in annotated
            ],
            "counting_unit": "annotation decisions, not independent interactions or interpersonal edges",
        },
        "raw_content_loaded": False, "source_events_not_modified": True,
        "automatic_annotation_qualified": False, "causal_effect_identified": False,
    }
