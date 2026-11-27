"""Descriptive agreement with supplied human annotations on exact revisions.

This is count bookkeeping over validated source decisions. It trains no
classifier, reads no content bytes, and establishes no deployment qualification.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .annotation_schema import LABELS, TAXONOMY, validate_method
from .annotations import annotation_report
from .events import EventDataset


_STATUSES = (
    "CURRENT", "STALE_CONTENT", "STALE_INTERACTION",
    "AMBIGUOUS_CONTENT", "AMBIGUOUS_ANNOTATION",
)
_SCORED_LABELS = tuple(sorted(LABELS - {"uncertain"}))


def _fraction(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator, "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _inventory(rows: list[dict], current_ids: set[str]) -> dict:
    def subset(selected: list[dict]) -> dict:
        targets = sorted({row["target_record_id"] for row in selected})
        return {
            "annotation_count": len(selected),
            "annotation_record_ids": sorted(row["record_id"] for row in selected),
            "content_count": len(targets), "content_record_ids": targets,
        }

    return {
        "active_annotation_count": len(rows),
        "by_status": {
            status: subset([row for row in rows if row["status"] == status])
            for status in _STATUSES
        },
        "uncertain_current": subset([
            row for row in rows if row["status"] == "CURRENT" and row["label"] == "uncertain"
        ]),
        "ambiguous": subset([row for row in rows if row["status"].startswith("AMBIGUOUS_")]),
        "stale": subset([row for row in rows if row["status"].startswith("STALE_")]),
        "outside_current_contents": subset([
            row for row in rows if row["target_record_id"] not in current_ids
        ]),
        "annotations": rows,
    }


def _target_state(rows: list[dict], *, reference: bool) -> str:
    if not rows:
        return "MISSING"
    if len(rows) != 1 or rows[0]["status"].startswith("AMBIGUOUS_"):
        return "AMBIGUOUS"
    row = rows[0]
    if row["status"] != "CURRENT":
        return "STALE"
    if row["label"] == "uncertain":
        return "UNCERTAIN" if reference else "ABSTAINED"
    return "ELIGIBLE" if reference else "AVAILABLE"


def evaluate_annotations(
    dataset: EventDataset,
    *,
    reference_method: dict,
    candidate_method: dict,
    knowledge_cutoff: int | None = None,
) -> dict:
    """Compare exact methods on current, unambiguous content record IDs.

    The specified reference must be human, but its labels are not certified
    truth. Human uncertainty excludes that item from the eligible reference
    denominator. Candidate uncertainty abstains, remaining unresolved in the
    reference denominator rather than becoming a neutral/negative prediction.

    Label/semantic agreement and per-label metrics are conditional on matched
    non-abstaining pairs. Coverage and joint-correct/reference are separate
    fractions so missing or unusable annotations remain visible. Undefined
    fractions are None. No threshold qualifies an annotator automatically.
    """
    if not isinstance(dataset, EventDataset):
        raise ValueError("annotation evaluation requires an EventDataset")
    reference_method = validate_method(reference_method)
    candidate_method = validate_method(candidate_method)
    if reference_method["kind"] != "human":
        raise ValueError("reference_method must identify a human annotation method")
    if candidate_method == reference_method:
        raise ValueError("candidate_method must differ from reference_method; self-evaluation is not admitted")

    report = annotation_report(dataset, knowledge_cutoff=knowledge_cutoff)
    all_rows = report["annotations"]
    for row in all_rows:
        if row["status"] not in _STATUSES or row["label"] not in LABELS:
            raise ValueError("annotation report contains an unsupported status or label")
        if row["taxonomy"] != TAXONOMY:
            raise ValueError("annotation evaluation requires the registered taxonomy version")
    reference_rows = [row for row in all_rows if row["method"] == reference_method]
    candidate_rows = [row for row in all_rows if row["method"] == candidate_method]
    reference_by_target, candidate_by_target = defaultdict(list), defaultdict(list)
    for row in reference_rows:
        reference_by_target[row["target_record_id"]].append(row)
    for row in candidate_rows:
        candidate_by_target[row["target_record_id"]].append(row)

    current_contents = report["current_contents"]
    current_ids = {row["record_id"] for row in current_contents}
    if len(current_ids) != len(current_contents):
        raise ValueError("annotation report contains duplicate current content IDs")
    targets, pairs = [], []
    eligible_reference = {}
    reference_states, candidate_states = defaultdict(list), defaultdict(list)
    for target_id in sorted(current_ids):
        refs, candidates = reference_by_target[target_id], candidate_by_target[target_id]
        ref_state = _target_state(refs, reference=True)
        cand_state = _target_state(candidates, reference=False)
        reference_states[ref_state].append(target_id)
        candidate_states[cand_state].append(target_id)
        reasons = []
        if ref_state != "ELIGIBLE":
            reasons.append("reference_" + ref_state.lower())
        else:
            eligible_reference[target_id] = refs[0]
        if cand_state != "AVAILABLE":
            reasons.append("candidate_" + cand_state.lower())
        target = {
            "target_record_id": target_id,
            "reference_status": ref_state, "candidate_status": cand_state,
            "reference_annotation_ids": sorted(row["record_id"] for row in refs),
            "candidate_annotation_ids": sorted(row["record_id"] for row in candidates),
            "scored": not reasons, "unresolved_reasons": reasons,
        }
        targets.append(target)
        if reasons:
            continue
        ref, cand = refs[0], candidates[0]
        label_agrees = ref["label"] == cand["label"]
        subject_agrees = ref["subject"] == cand["subject"]
        topic_agrees = ref["topic"] == cand["topic"]
        pairs.append({
            "target_record_id": target_id,
            "reference_annotation_id": ref["record_id"],
            "candidate_annotation_id": cand["record_id"],
            "reference_label": ref["label"], "candidate_label": cand["label"],
            "reference_subject": ref["subject"], "candidate_subject": cand["subject"],
            "reference_topic": ref["topic"], "candidate_topic": cand["topic"],
            "label_agrees": label_agrees, "subject_agrees": subject_agrees,
            "topic_agrees": topic_agrees,
            "semantic_target_topic_agrees": subject_agrees and topic_agrees,
            "joint_agrees": label_agrees and subject_agrees and topic_agrees,
        })

    reference_count, matched_count = len(eligible_reference), len(pairs)
    counts = Counter((pair["reference_label"], pair["candidate_label"]) for pair in pairs)
    support = Counter(pair["reference_label"] for pair in pairs)
    predicted = Counter(pair["candidate_label"] for pair in pairs)
    eligible_support = Counter(row["label"] for row in eligible_reference.values())
    per_label = []
    for label in _SCORED_LABELS:
        true_positive = counts[(label, label)]
        observed, proposed = support[label], predicted[label]
        per_label.append({
            "label": label, "support": observed, "predicted_count": proposed,
            "eligible_reference_support": eligible_support[label],
            "unscored_reference_count": eligible_support[label] - observed,
            "true_positive": true_positive,
            "false_positive": proposed - true_positive,
            "false_negative": observed - true_positive,
            "precision": true_positive / proposed if proposed else None,
            "recall": true_positive / observed if observed else None,
            "f1": 2 * true_positive / (observed + proposed) if observed + proposed else None,
        })

    agreement_counts = {
        name: sum(pair[field] for pair in pairs)
        for name, field in (
            ("label_accuracy", "label_agrees"),
            ("subject_accuracy", "subject_agrees"),
            ("topic_accuracy", "topic_agrees"),
            ("semantic_target_topic_accuracy", "semantic_target_topic_agrees"),
            ("joint_accuracy", "joint_agrees"),
        )
    }
    unresolved = [target for target in targets if target["reference_status"] == "ELIGIBLE" and not target["scored"]]
    return {
        "kind": "ANNOTATION_EVALUATION",
        "input": report["input"], "taxonomy": dict(TAXONOMY),
        "reference_method": reference_method, "candidate_method": candidate_method,
        "pairing_key": "exact target content record ID; never hash or text matching",
        "current_content_count": len(current_ids),
        "reference_count": reference_count, "matched_count": matched_count,
        "reference_count_meaning": "current unambiguous non-uncertain human reference annotations, one per content revision",
        "matched_count_meaning": "eligible references with one current unambiguous non-abstaining candidate on the same content record ID",
        "coverage": {
            "universe": "all current unambiguous content revisions with an active exact parent interaction",
            "current_content_record_ids": sorted(current_ids),
            "reference_targets_by_status": {
                state: reference_states[state]
                for state in ("ELIGIBLE", "UNCERTAIN", "MISSING", "AMBIGUOUS", "STALE")
            },
            "candidate_targets_by_status": {
                state: candidate_states[state]
                for state in ("AVAILABLE", "ABSTAINED", "MISSING", "AMBIGUOUS", "STALE")
            },
            "missing_reference_ids": reference_states["MISSING"],
            "missing_candidate_ids": candidate_states["MISSING"],
            "unresolved_reference_ids": [target["target_record_id"] for target in unresolved],
            "unresolved_reference_items": unresolved,
            "unresolved_reference_scope": "eligible references lacking a usable candidate; human uncertainty is separately reported under reference_targets_by_status.UNCERTAIN",
            "eligible_reference_over_current_contents": _fraction(reference_count, len(current_ids)),
            "available_candidate_over_current_contents": _fraction(len(candidate_states["AVAILABLE"]), len(current_ids)),
            "matched_over_reference": _fraction(matched_count, reference_count),
            "joint_correct_over_reference": _fraction(agreement_counts["joint_accuracy"], reference_count),
            "joint_correct_over_reference_meaning": "correct matched pairs per eligible reference; unscored items remain unresolved, not predicted errors",
        },
        "agreement": {name: _fraction(count, matched_count) for name, count in agreement_counts.items()},
        "confusion": [
            {"reference_label": ref, "candidate_label": cand, "count": count}
            for (ref, cand), count in sorted(counts.items())
        ],
        "per_label": per_label,
        "label_metric_scope": "matched non-abstaining pairs only; support sums to matched_count",
        "f1_definition": "2 * true_positive / (support + predicted_count); null when denominator is zero",
        "uncertainty_policy": "human uncertain is unresolved and ineligible; candidate uncertain abstains and is never a neutral or negative prediction",
        "targets": targets, "matched_pairs": pairs,
        "current_contents": current_contents, "content_issues": report["content_issues"],
        "annotation_audit": {
            "reference": _inventory(reference_rows, current_ids),
            "candidate": _inventory(candidate_rows, current_ids),
            "other_method_record_ids": sorted(
                row["record_id"] for row in all_rows
                if row["method"] != reference_method and row["method"] != candidate_method
            ),
        },
        "qualification_status": "NOT_ESTABLISHED",
        "reference_is_ground_truth": False,
        "train_test_independence_established": False,
        "empirical_validation_established": False,
        "deployment_qualified": False,
        "automatic_annotation_qualified": False,
        "calibration_estimated": False,
        "score_interpretation": "source-supplied uncalibrated score, not a probability; unused in agreement calculations",
        "raw_content_loaded": False,
        "causal_effect_identified": False,
        "meaning": "descriptive agreement with caller-supplied human reference labels; method identities do not establish independent annotation or held-out evaluation",
    }
