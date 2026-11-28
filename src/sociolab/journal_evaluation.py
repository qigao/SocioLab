"""Evaluate saved forecasts against declared journal receipt versions.

Each origin reconstructs its own expanding, as-known history. Revisions to old
observations are permitted at later origins and described as aggregate changes.
Targets have separately declared receipt cutoffs. Neither receipts nor these
content hashes authenticate historical availability or prospective issuance.
"""

from __future__ import annotations

from copy import deepcopy

from .behavior_forecast import (
    _fields, _hash, _hash_value, _integer, _runtime, _validate_target,
    score_behavior_forecast,
)
from .events import EventDataset, parse_time
from .forecast_evaluation import _METRICS, _summaries
from .journal_forecast import (
    _validated_spec, make_journal_forecast_history, make_journal_forecast_target,
)
from .panels import LongitudinalPanel

_PROFILE = "journal-receipt-prefix-multi-origin-v1"
_TRAINING_POLICY = "expanding_as_known_receipt_prefix"
_TARGET_POLICY = "latest_effective_at_declared_target_cutoff"
_EVALUATION_POLICY = "all_planned_folds_fixed_roster"
_PLAN_FIELDS = {
    "schema", "kind", "profile", "initial_specification", "schedule", "journal",
    "training_policy", "target_version_policy", "evaluation_policy", "metrics", "scope", "content_hash",
}
_JOURNAL_FIELDS = {
    "envelope", "initial_knowledge_cutoff", "initial_prefix_hash", "initial_history_bundle_hash", "initial_panel_hash",
}
_SCHEDULE_FOLD_FIELDS = {"target_time_index", "target_at", "history_knowledge_cutoff", "target_knowledge_cutoff"}
_BASE_SCOPE = {
    "analysis": "retrospective_receipt_version_multi_origin_evaluation",
    "plan_uses_initial_receipt_prefix_only": True,
    "future_receipt_records_consumed_at_plan_creation": False,
    "receipt_prefix_enforced": True,
    "history_raw_assertion_future_stream_gate_enforced": True,
    "future_stream_scope": "all_matching_system_attribute_assertions_regardless_of_actor_or_active_head",
    "target_fact_ancestry_gate_enforced": True,
    "target_fact_ancestry_policy": "first_receipt_of_source_system_fact_id_after_own_history_cutoff",
    "late_history_revisions_allowed": True,
    "target_versions_fixed_by_schedule": True,
    "previous_target_equals_next_history_required": False,
    "immutable_prefix_evaluator_used": False,
    "historical_as_of_availability_verified": False,
    "receipt_timestamps_externally_authenticated": False,
    "forecast_issued_before_target_observation_verified": False,
    "content_hash_authenticates_author": False,
    "content_hash_proves_prospective_timestamp": False,
    "live_subscription": False,
    "actor_dropping": False,
    "fold_dropping": False,
    "actor_forecast_rows_independent": False,
    "uncertainty_intervals": False,
    "p_values": False,
    "stability_established": False,
    "population_boundary_qualified": False,
    "causal_effect_identified": False,
    "empirical_forecast_validated": False,
}
_PLAN_SCOPE = {**_BASE_SCOPE, "models_fitted_at_plan_creation": False, "contains_private_actor_records": True}
_REPORT_SCOPE = {
    **_BASE_SCOPE,
    "refitting_performed_by_evaluation": False,
    "saved_targets_matched_journal_reconstruction": True,
    "history_revision_summary": "differences_reconstructed_from_same_journal",
    "target_network_materialized": False,
    "historical_networks_replayed": True,
    "contains_private_actor_records": False,
    "output": "aggregate_only",
}


def _schedule(value: object, initial: dict, clock: dict) -> dict:
    _fields(value, {"schema", "folds"}, "journal forecast schedule")
    if value["schema"] != "sociolab.journal-forecast-schedule.v1":
        raise ValueError("unsupported journal forecast schedule schema")
    folds = value["folds"]
    if type(folds) is not list or len(folds) < 2:
        raise ValueError("journal evaluation requires at least two planned folds")
    if len(initial["waves"]) + len(folds) - 1 > 32:
        raise ValueError("last planned history would exceed 32 waves")
    index_gap = initial["waves"][1]["time_index"] - initial["waves"][0]["time_index"]
    source_gap = parse_time(initial["waves"][1]["at"], clock) - parse_time(initial["waves"][0]["at"], clock)
    first_index = initial["forecast_specification"]["target_time_index"]
    first_source_time = parse_time(initial["target_at"], clock)
    previous_history_cutoff = None
    for index, fold in enumerate(folds):
        _fields(fold, _SCHEDULE_FOLD_FIELDS, "scheduled fold")
        history_cutoff = _integer(fold["history_knowledge_cutoff"], "history_knowledge_cutoff")
        target_cutoff = _integer(fold["target_knowledge_cutoff"], "target_knowledge_cutoff")
        if index == 0 and history_cutoff != initial["knowledge_cutoff"]:
            raise ValueError("first history cutoff must equal the initial specification cutoff")
        if previous_history_cutoff is not None and history_cutoff <= previous_history_cutoff:
            raise ValueError("history cutoffs must strictly increase across origins")
        if target_cutoff <= history_cutoff:
            raise ValueError("each target cutoff must be strictly after its own history cutoff")
        if (_integer(fold["target_time_index"], "target_time_index") != first_index + index * index_gap or
                parse_time(fold["target_at"], clock) != first_source_time + index * source_gap):
            raise ValueError("target source times and indices must consecutively extend the initial schedule")
        previous_history_cutoff = history_cutoff
    normalized = deepcopy(value)
    # Equivalent UTC representations denote the same instant. Keep the first
    # origin byte-for-byte consistent with the separately bound initial spec.
    normalized["folds"][0]["target_at"] = initial["target_at"]
    _hash(normalized)
    return normalized


def _future_stream_gate(dataset: EventDataset, spec: dict) -> None:
    """Check every raw assertion, including superseded/retracted bad values."""
    cutoff = spec["knowledge_cutoff"]
    dataset.as_known(cutoff)  # validate the explicit receipt prefix
    threshold = parse_time(spec["target_at"], dataset.clock)
    for record in dataset.records[:cutoff]:
        if record["operation"] != "assert" or record["kind"] != "actor.attribute.observed":
            continue
        if (record["source"]["system"] != spec["behavior_source"]["system"] or
                record["payload"]["name"] != spec["behavior_source"]["attribute"]):
            continue
        future = parse_time(record["occurred_at"], dataset.clock) >= threshold
        interval = record["valid_interval"]
        if interval is not None:
            future |= interval[1] is None or parse_time(interval[1], dataset.clock) > threshold
        if future:
            raise ValueError("history receipt prefix already contains a target-or-later assertion in the declared measurement stream")


def _target_ancestry_gate(dataset: EventDataset, target_bundle: dict, history_cutoff: int, target_cutoff: int) -> None:
    earliest = {}
    for record in dataset.records[:target_cutoff]:
        key = (record["source"]["system"], record["fact_id"])
        earliest.setdefault(key, record["ingest_seq"])
    for item in target_bundle["provenance"]["behavior_evidence"]:
        record = item["record"]
        key = (record["source"]["system"], record["fact_id"])
        if earliest[key] <= history_cutoff:
            raise ValueError("a selected target fact was first received at or before its forecast history cutoff")


def _binding(bundle: dict) -> dict:
    return {
        "envelope": deepcopy(bundle["provenance"]["prefix_envelope"]),
        "initial_knowledge_cutoff": bundle["specification"]["knowledge_cutoff"],
        "initial_prefix_hash": bundle["provenance"]["prefix_content_hash"],
        "initial_history_bundle_hash": bundle["content_hash"],
        "initial_panel_hash": LongitudinalPanel.from_mapping(bundle["history"]).content_hash,
    }


def make_journal_forecast_plan(dataset: EventDataset, initial_spec: dict, schedule: dict) -> dict:
    """Declare receipt versions while only the exact initial prefix is supplied."""
    initial = _validated_spec(dataset, initial_spec)
    if len(dataset.records) != initial["knowledge_cutoff"]:
        raise ValueError("plan creation requires the journal to contain exactly its initial receipt prefix")
    declared_schedule = _schedule(schedule, initial, dataset.clock)
    _future_stream_gate(dataset, initial)
    bundle = make_journal_forecast_history(dataset, initial)
    plan = {
        "schema": "sociolab.journal-forecast-plan.v1", "kind": "JOURNAL_FORECAST_PLAN", "profile": _PROFILE,
        "initial_specification": initial, "schedule": declared_schedule, "journal": _binding(bundle),
        "training_policy": _TRAINING_POLICY, "target_version_policy": _TARGET_POLICY,
        "evaluation_policy": _EVALUATION_POLICY, "metrics": deepcopy(_METRICS), "scope": deepcopy(_PLAN_SCOPE),
    }
    plan["content_hash"] = _hash(plan)
    return plan


def _validated_plan(plan: object, dataset: EventDataset) -> dict:
    if not isinstance(dataset, EventDataset):
        raise TypeError("journal evaluation requires an EventDataset")
    _fields(plan, _PLAN_FIELDS, "journal forecast plan")
    if (plan["schema"] != "sociolab.journal-forecast-plan.v1" or
            plan["kind"] != "JOURNAL_FORECAST_PLAN" or plan["profile"] != _PROFILE):
        raise ValueError("unsupported journal forecast plan schema, kind or profile")
    _hash_value(plan["content_hash"], "plan content_hash")
    if plan["content_hash"] != _hash({key: value for key, value in plan.items() if key != "content_hash"}):
        raise ValueError("journal plan content hash does not match its contents")
    initial = _validated_spec(dataset, plan["initial_specification"])
    declared_schedule = _schedule(plan["schedule"], initial, dataset.clock)
    if _hash(declared_schedule) != _hash(plan["schedule"]):
        raise ValueError("stored schedule must use the normalized first target time")
    journal = plan["journal"]
    _fields(journal, _JOURNAL_FIELDS, "initial journal binding")
    _integer(journal["initial_knowledge_cutoff"], "initial_knowledge_cutoff")
    if journal["initial_knowledge_cutoff"] != initial["knowledge_cutoff"]:
        raise ValueError("plan initial cutoffs disagree")
    for field in ("initial_prefix_hash", "initial_history_bundle_hash", "initial_panel_hash"):
        _hash_value(journal[field], field)
    envelope = dataset.to_dict()
    envelope.pop("records")
    if _hash(journal["envelope"]) != _hash(envelope):
        raise ValueError("evaluation must use the same journal envelope, source and clock as the plan")
    for field, fixed in (("training_policy", _TRAINING_POLICY), ("target_version_policy", _TARGET_POLICY),
                         ("evaluation_policy", _EVALUATION_POLICY), ("metrics", _METRICS), ("scope", _PLAN_SCOPE)):
        if plan[field] != fixed or _hash(plan[field]) != _hash(fixed):
            raise ValueError(f"journal plan {field} does not match its fixed policy")
    return plan


def _fold_spec(initial: dict, schedule: dict, index: int) -> dict:
    spec = deepcopy(initial)
    scheduled = schedule["folds"][index]
    spec["knowledge_cutoff"] = scheduled["history_knowledge_cutoff"]
    spec["target_at"] = scheduled["target_at"]
    spec["forecast_specification"]["target_time_index"] = scheduled["target_time_index"]
    spec["waves"].extend({"time_index": earlier["target_time_index"], "at": earlier["target_at"]}
                         for earlier in schedule["folds"][:index])
    return spec


def _history_difference(before: dict | None, after: dict, previous_target: dict | None) -> dict | None:
    if before is None:
        return None
    old_waves, new_waves = before["waves"], after["waves"][:-1]
    if len(old_waves) != len(new_waves):
        raise ValueError("receipt evaluation must expand history by exactly one wave")
    behavior_counts = [sum(old["behavior"][actor] != new["behavior"][actor] for actor in before["actors"])
                       for old, new in zip(old_waves, new_waves)]
    network_counts = [len({tuple(edge) for edge in old["edges"]} ^ {tuple(edge) for edge in new["edges"]})
                      for old, new in zip(old_waves, new_waves)]
    def values(waves):
        return [{key: wave[key] for key in ("time_index", "edges", "behavior")} for wave in waves]
    appended = after["waves"][-1]
    return {
        "overlap_wave_count": len(old_waves),
        "behavior_changed_wave_count": sum(count > 0 for count in behavior_counts),
        "behavior_changed_actor_wave_count": sum(behavior_counts),
        "network_changed_wave_count": sum(count > 0 for count in network_counts),
        "network_changed_edge_wave_count": sum(network_counts),
        "source_revision_changed_wave_count": sum(old["source_revision"] != new["source_revision"]
                                                  for old, new in zip(old_waves, new_waves)),
        "old_waves_before_hash": _hash(values(old_waves)), "old_waves_after_hash": _hash(values(new_waves)),
        "previous_target_comparison": {
            "target_time_index": previous_target["time_index"],
            "changed_actor_count": sum(previous_target["behavior"][actor] != appended["behavior"][actor]
                                       for actor in after["actors"]),
            "prior_target_behavior_hash": _hash(previous_target["behavior"]),
            "appended_behavior_hash": _hash(appended["behavior"]),
        },
    }


def evaluate_journal_forecasts(plan: dict, dataset: EventDataset, folds: list[dict]) -> dict:
    """Reconstruct each declared receipt version and score its saved artifacts."""
    declared = _validated_plan(plan, dataset)
    scheduled_folds = declared["schedule"]["folds"]
    if type(folds) is not list or len(folds) != len(scheduled_folds):
        raise ValueError("saved folds must exactly cover every planned origin in order")
    reports = []
    previous_history = previous_target = None
    for index, (fold, scheduled) in enumerate(zip(folds, scheduled_folds)):
        _fields(fold, {"forecast", "target"}, "saved journal forecast fold")
        spec = _fold_spec(declared["initial_specification"], declared["schedule"], index)
        _future_stream_gate(dataset, spec)
        history_bundle = make_journal_forecast_history(dataset, spec)
        if index == 0 and _binding(history_bundle) != declared["journal"]:
            raise ValueError("initial journal prefix and historical reconstruction do not match the plan")
        target_bundle = make_journal_forecast_target(dataset, spec, fold["forecast"], scheduled["target_knowledge_cutoff"])
        _target_ancestry_gate(dataset, target_bundle, spec["knowledge_cutoff"], scheduled["target_knowledge_cutoff"])
        saved_target = _validate_target(fold["target"])
        if _hash(saved_target) != _hash(target_bundle["target"]):
            raise ValueError("saved target must exactly match its declared journal receipt version, including its revision")
        score = score_behavior_forecast(fold["forecast"], saved_target)
        history = history_bundle["history"]
        reports.append({
            "fold_index": index + 1, "origin_time_index": history["waves"][-1]["time_index"],
            "origin_at": spec["waves"][-1]["at"], "target_time_index": scheduled["target_time_index"],
            "target_at": spec["target_at"], "history_knowledge_cutoff": spec["knowledge_cutoff"],
            "target_knowledge_cutoff": scheduled["target_knowledge_cutoff"],
            "history_journal_prefix_hash": history_bundle["provenance"]["prefix_content_hash"],
            "target_journal_prefix_hash": target_bundle["provenance"]["prefix_content_hash"],
            "history_bundle_hash": history_bundle["content_hash"],
            "history_panel_hash": LongitudinalPanel.from_mapping(history).content_hash,
            "forecast_hash": fold["forecast"]["content_hash"], "target_hash": _hash(saved_target),
            "score_hash": _hash(score), "score": score,
            "history_revision": _history_difference(previous_history, history, previous_target),
        })
        previous_history, previous_target = history, saved_target
    scores = [fold["score"] for fold in reports]
    models, comparisons = _summaries(scores)
    report = {
        "schema": "sociolab.journal-forecast-evaluation.v1", "kind": "JOURNAL_FORECAST_EVALUATION", "profile": _PROFILE,
        "plan_hash": declared["content_hash"], "journal_envelope_hash": _hash(declared["journal"]["envelope"]),
        "initial_prefix_hash": declared["journal"]["initial_prefix_hash"],
        "dataset": {key: previous_history[key] for key in
                    ("dataset_id", "origin", "source_reference", "relation", "behavior_variable")},
        "actor_count": len(declared["initial_specification"]["actors"]), "fold_count": len(reports),
        "actor_forecast_count": sum(score["actor_count"] for score in scores),
        "target_time_indices": [fold["target_time_index"] for fold in scheduled_folds],
        "training_policy": _TRAINING_POLICY, "target_version_policy": _TARGET_POLICY, "evaluation_policy": _EVALUATION_POLICY,
        "folds": reports, "models": models, "comparisons": comparisons, "metrics": deepcopy(_METRICS),
        "scope": deepcopy(_REPORT_SCOPE), "runtime": _runtime(),
    }
    report["content_hash"] = _hash(report)
    return report
