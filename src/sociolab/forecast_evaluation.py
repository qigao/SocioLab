"""Evaluate saved forecasts over a fixed, expanding sequence of history prefixes.

Planning never fits a model. Evaluation checks the retained history, prediction,
and independently supplied target for every planned fold, then calls the existing
single-fold scorer without fitting again. These content checks do not establish
when predictions were actually issued or observations historically available.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from ._json import unique_object
from .behavior_forecast import (
    _MODEL_IDS,
    _PROFILE,
    _fields,
    _hash,
    _hash_value,
    _integer,
    _origin,
    _runtime,
    _text,
    _validate_forecast,
    _validate_spec,
    score_behavior_forecast,
)
from .panels import LongitudinalPanel

_TRAINING_POLICY = "expanding_immutable_prefix"
_EVALUATION_POLICY = "all_planned_folds_fixed_roster"
_PLAN_FIELDS = {
    "schema", "kind", "profile", "dataset", "initial_history", "specification",
    "target_time_indices", "wave_gap", "training_policy", "evaluation_policy",
    "metrics", "scope", "content_hash",
}
_DATASET_FIELDS = {"dataset_id", "origin", "source_reference", "relation", "behavior_variable"}
_INITIAL_HISTORY_FIELDS = {
    "content_hash", "actor_count", "actor_roster_hash", "wave_time_indices", "wave_source_revisions",
}
_METRICS = {
    "primary": "mae",
    "secondary": "rmse",
    "primary_prediction": "clipped",
    "primary_aggregation": "pooled",
    "prediction_variants": ["raw", "clipped"],
    "aggregations": ["pooled", "macro"],
    "pooled_weight": "actor_forecast_count",
    "macro_weight": "equal_fold_weight",
    "difference_direction": "network_minus_baseline_negative_favors_network",
    "rounding": "none",
    "unit": "declared_behavior_level",
}
_PLAN_SCOPE = {
    "analysis": "retrospective_multi_origin_evaluation",
    "plan_uses_initial_history_only": True,
    "future_observations_consumed_at_plan_creation": False,
    "models_fitted_at_plan_creation": False,
    "fixed_roster_source": "initial_history",
    "late_revisions_in_same_plan_allowed": False,
    "historical_receipt_availability": "unknown",
    "historical_as_of_availability_verified": False,
    "forecast_issuance_before_target_observation_verified": False,
    "content_hash_authenticates_author": False,
    "content_hash_proves_prospective_timestamp": False,
    "wave_time_unit": "wave_index_not_calendar_duration",
    "ordinal_values_treated_as_numeric": True,
    "population_boundary_qualified": False,
    "actor_forecast_rows_independent": False,
    "uncertainty_intervals": False,
    "p_values": False,
    "calibration_status": "NOT_ESTIMATED",
    "prediction_intervals": None,
    "stability_established": False,
    "causal_effect_identified": False,
    "empirical_forecast_validated": False,
}
_EVALUATION_SCOPE = {
    **_PLAN_SCOPE,
    "full_prefix_extension_verified": True,
    "previous_target_matches_next_history": True,
    "refitting_performed_by_evaluation": False,
    "scores_recomputed_from_saved_forecasts_and_targets": True,
    "target_network_used_for_scoring": False,
    "fold_dropping": False,
    "actor_dropping": False,
    "output": "aggregate_only",
}


def _dataset(history: LongitudinalPanel) -> dict:
    return {
        "dataset_id": history.dataset_id,
        "origin": history.origin,
        "source_reference": history.source_reference,
        "relation": history.relation,
        "behavior_variable": history.behavior_variable,
    }


def _initial_history(history: LongitudinalPanel) -> dict:
    return {
        "content_hash": history.content_hash,
        "actor_count": len(history.actors),
        "actor_roster_hash": _hash(list(history.actors)),
        "wave_time_indices": [wave.time_index for wave in history.waves],
        "wave_source_revisions": [wave.source_revision for wave in history.waves],
    }


def _validate_history(history: object, spec: dict) -> LongitudinalPanel:
    if not isinstance(history, LongitudinalPanel):
        raise TypeError("fold history must be a LongitudinalPanel prefix")
    if len(history.actors) > 200 or len(history.waves) > 32:
        raise ValueError("forecast evaluation budget is at most 200 actors and 32 history waves")
    LongitudinalPanel.from_mapping(history.to_dict())
    if any(not wave.network_complete for wave in history.waves):
        raise ValueError("all history networks must be explicitly complete")
    scale = spec["behavior"]
    if history.behavior_variable != scale["variable"]:
        raise ValueError("history behavior variable does not match the fixed specification")
    if any(type(value) is not int or not scale["minimum"] <= value <= scale["maximum"]
           for wave in history.waves for _, value in wave.behavior):
        raise ValueError("history behavior must be known integer levels within the fixed scale")
    times = [wave.time_index for wave in history.waves]
    gap = times[1] - times[0]
    if any(right - left != gap for left, right in zip(times, times[1:])):
        raise ValueError("history waves must have one constant positive gap")
    if spec["target_time_index"] != times[-1] + gap:
        raise ValueError("planned target must immediately follow the history prefix at the same gap")
    return history


def _validate_targets(targets: object, times: list[int], gap: int, spec: dict) -> None:
    if type(targets) is not list or len(targets) < 2:
        raise ValueError("evaluation needs at least two planned target times")
    if len(times) + len(targets) - 1 > 32:
        raise ValueError("last planned fold would exceed the 32-history-wave budget")
    for target in targets:
        _integer(target, "planned target_time_index")
    expected = [times[-1] + gap * (index + 1) for index in range(len(targets))]
    if targets != expected or spec["target_time_index"] != targets[0]:
        raise ValueError("planned target times must consecutively extend the initial prefix at the same gap")


def make_behavior_forecast_plan(
    initial_history: LongitudinalPanel,
    specification: dict,
    target_time_indices: list[int],
) -> dict:
    """Declare at least two consecutive folds using only the first history prefix.

    The roster and scale are fixed here; future outcomes cannot be used to select
    actors, infer scale bounds, or choose a subset of folds within this plan.
    No predictions are fitted or issued by this function.
    """
    spec = _validate_spec(specification)
    history = _validate_history(initial_history, spec)
    initial = _initial_history(history)
    times = initial["wave_time_indices"]
    gap = times[1] - times[0]
    _validate_targets(target_time_indices, times, gap, spec)
    plan = {
        "schema": "sociolab.behavior-forecast-plan.v1",
        "kind": "BEHAVIOR_FORECAST_PLAN",
        "profile": _PROFILE,
        "dataset": _dataset(history),
        "initial_history": initial,
        "specification": spec,
        "target_time_indices": list(target_time_indices),
        "wave_gap": gap,
        "training_policy": _TRAINING_POLICY,
        "evaluation_policy": _EVALUATION_POLICY,
        "metrics": deepcopy(_METRICS),
        "scope": deepcopy(_PLAN_SCOPE),
    }
    plan["content_hash"] = _hash(plan)
    return plan


def _validate_plan(plan: object) -> dict:
    _fields(plan, _PLAN_FIELDS, "forecast evaluation plan")
    if (plan["schema"] != "sociolab.behavior-forecast-plan.v1" or
            plan["kind"] != "BEHAVIOR_FORECAST_PLAN" or plan["profile"] != _PROFILE):
        raise ValueError("unsupported forecast evaluation plan schema, kind or profile")
    _hash_value(plan["content_hash"], "plan content_hash")
    if plan["content_hash"] != _hash({key: value for key, value in plan.items() if key != "content_hash"}):
        raise ValueError("plan content hash does not match its contents")
    spec = _validate_spec(plan["specification"])
    dataset = plan["dataset"]
    _fields(dataset, _DATASET_FIELDS, "plan dataset")
    _text(dataset["dataset_id"], "dataset_id")
    _origin(dataset["origin"], dataset["source_reference"])
    if dataset["relation"] != "directed_observed_social_tie" or dataset["behavior_variable"] != spec["behavior"]["variable"]:
        raise ValueError("plan dataset relation or behavior variable does not match the fixed profile")
    initial = plan["initial_history"]
    _fields(initial, _INITIAL_HISTORY_FIELDS, "initial history metadata")
    _hash_value(initial["content_hash"], "initial history content_hash")
    _hash_value(initial["actor_roster_hash"], "actor_roster_hash")
    if not 2 <= _integer(initial["actor_count"], "actor_count") <= 200:
        raise ValueError("planned roster must have between 2 and 200 actors")
    times = initial["wave_time_indices"]
    if type(times) is not list or not 2 <= len(times) <= 32:
        raise ValueError("initial history must contain between 2 and 32 waves")
    for time in times:
        _integer(time, "initial wave_time_index")
    gap = _integer(plan["wave_gap"], "wave_gap", 1)
    if any(right - left != gap for left, right in zip(times, times[1:])):
        raise ValueError("initial history times must have the stated positive gap")
    revisions = initial["wave_source_revisions"]
    if type(revisions) is not list or len(revisions) != len(times):
        raise ValueError("initial history requires one revision per wave")
    for revision in revisions:
        _text(revision, "initial wave_source_revision")
    if len(set(revisions)) != len(revisions):
        raise ValueError("initial wave source revisions must be distinct")
    _validate_targets(plan["target_time_indices"], times, gap, spec)
    if plan["training_policy"] != _TRAINING_POLICY or plan["evaluation_policy"] != _EVALUATION_POLICY:
        raise ValueError("unsupported training or evaluation policy")
    for field, fixed in (("metrics", _METRICS), ("scope", _PLAN_SCOPE)):
        if plan[field] != fixed or _hash(plan[field]) != _hash(fixed):
            raise ValueError(f"plan {field} do not match the fixed profile")
    return plan


def _coverage(scores: list[dict], names: tuple[str, ...]) -> dict:
    available = [score for score in scores if all(score["models"][name]["status"] == "OK" for name in names)]
    failed = [score["target_time_index"] for score in scores
              if any(score["models"][name]["status"] != "OK" for name in names)]
    return {
        "expected_fold_count": len(scores),
        "available_fold_count": len(available),
        "expected_actor_forecast_count": sum(score["actor_count"] for score in scores),
        "available_actor_forecast_count": sum(score["actor_count"] for score in available),
        "failed_target_time_indices": failed,
    }


def _loss_summary(scores: list[dict], name: str, variant: str) -> dict:
    total = sum(score["models"][name]["n_evaluated"] for score in scores)
    weights = [score["models"][name]["n_evaluated"] / total for score in scores]
    losses = [score["models"][name][variant] for score in scores]
    result = {
        "pooled": {
            "mae": math.fsum(weight * loss["mae"] for weight, loss in zip(weights, losses)),
            # hypot computes sqrt(sum(n_f / N * RMSE_f**2)) without overflow
            # from unnecessarily squaring a large finite RMSE first.
            "rmse": math.hypot(*(math.sqrt(weight) * loss["rmse"] for weight, loss in zip(weights, losses))),
        },
        "macro": {metric: math.fsum(loss[metric] / len(losses) for loss in losses)
                  for metric in ("mae", "rmse")},
    }
    if not all(math.isfinite(value) for aggregation in result.values() for value in aggregation.values()):
        raise ValueError("evaluation summary metrics must be finite")
    return result


def _summaries(scores: list[dict]) -> tuple[dict, dict]:
    models = {}
    for name in _MODEL_IDS:
        coverage = _coverage(scores, (name,))
        complete = not coverage["failed_target_time_indices"]
        models[name] = {
            "status": "OK" if complete else "NOT_ESTIMABLE",
            "reason": None if complete else "not_estimable_in_all_planned_folds",
            **coverage,
            "clipping_count": sum(score["models"][name]["clipping_count"] for score in scores) if complete else None,
            **{variant: _loss_summary(scores, name, variant) if complete else None for variant in ("raw", "clipped")},
        }
    comparisons = {}
    for comparison, baseline in (("network_vs_own", "own_lag_ols"), ("network_vs_persistence", "persistence")):
        coverage = _coverage(scores, ("network_lag_ols", baseline))
        complete = not coverage["failed_target_time_indices"]
        comparisons[comparison] = {
            "status": "OK" if complete else "NOT_ESTIMABLE",
            "reason": None if complete else "required_model_not_estimable_in_all_planned_folds",
            **coverage,
            "direction": "network_minus_baseline_negative_favors_network",
            **{variant: {
                aggregation: {
                    f"{metric}_difference": models["network_lag_ols"][variant][aggregation][metric]
                    - models[baseline][variant][aggregation][metric]
                    for metric in ("mae", "rmse")
                } for aggregation in ("pooled", "macro")
            } if complete else None for variant in ("raw", "clipped")},
        }
    return models, comparisons


def evaluate_behavior_forecasts(plan: dict, folds: list[dict]) -> dict:
    """Re-score every saved forecast and evaluate all planned folds, without fit.

    Each fold has exactly ``history``, ``forecast`` and ``target``. History is a
    LongitudinalPanel; the two other values use the existing forecast and target
    schemas. Earlier waves cannot be revised within this plan, and the behavior
    appended for a later fold must equal the preceding fold's independent target.
    """
    declared = _validate_plan(plan)
    if type(folds) is not list or len(folds) != len(declared["target_time_indices"]):
        raise ValueError("folds must exactly cover every planned target time in order")
    fold_reports = []
    previous_history = None
    previous_target = None
    for index, (fold, target_time) in enumerate(zip(folds, declared["target_time_indices"]), start=1):
        _fields(fold, {"history", "forecast", "target"}, "evaluation fold")
        spec = deepcopy(declared["specification"])
        spec["target_time_index"] = target_time
        history = _validate_history(fold["history"], spec)
        initial = _initial_history(history)
        if _dataset(history) != declared["dataset"]:
            raise ValueError("fold dataset and source must match the plan")
        if (initial["actor_count"] != declared["initial_history"]["actor_count"] or
                initial["actor_roster_hash"] != declared["initial_history"]["actor_roster_hash"]):
            raise ValueError("fold roster must exactly match the initial planned roster")
        if index == 1:
            if initial != declared["initial_history"]:
                raise ValueError("first fold history must match the plan's initial history")
        else:
            if len(history.waves) != len(previous_history.waves) + 1 or history.waves[:-1] != previous_history.waves:
                raise ValueError("each fold must append exactly one wave without changing any earlier wave or revision")
            added = history.waves[-1]
            if added.time_index != previous_target["time_index"] or dict(added.behavior) != previous_target["behavior"]:
                raise ValueError("the appended wave behavior must equal the preceding independently scored target")
        forecast = _validate_forecast(fold["forecast"])
        if forecast["dataset"] != declared["dataset"] or forecast["actors"] != list(history.actors):
            raise ValueError("saved forecast dataset or roster does not match its retained history")
        expected_history = {
            "content_hash": history.content_hash,
            "wave_time_indices": initial["wave_time_indices"],
            "wave_source_revisions": initial["wave_source_revisions"],
            "origin_time_index": history.waves[-1].time_index,
            "wave_gap": declared["wave_gap"],
            "transition_count": len(history.waves) - 1,
        }
        if forecast["history"] != expected_history:
            raise ValueError("saved forecast history hash and metadata must match the complete retained prefix")
        if forecast["specification"] != spec:
            raise ValueError("every forecast must use the fixed plan specification and its planned target time")
        # The core scorer validates the target and the intact private artifact.
        # It never creates a forecast or fits coefficients.
        score = score_behavior_forecast(forecast, fold["target"])
        fold_reports.append({
            "fold_index": index,
            "origin_time_index": history.waves[-1].time_index,
            "target_time_index": target_time,
            "history_prefix_hash": history.content_hash,
            "forecast_hash": forecast["content_hash"],
            "score_hash": _hash(score),
            "score": score,
        })
        previous_history, previous_target = history, fold["target"]
    scores = [fold["score"] for fold in fold_reports]
    models, comparisons = _summaries(scores)
    report = {
        "schema": "sociolab.behavior-forecast-evaluation.v1",
        "kind": "BEHAVIOR_FORECAST_EVALUATION",
        "profile": _PROFILE,
        "plan_hash": declared["content_hash"],
        "dataset": deepcopy(declared["dataset"]),
        "actor_count": declared["initial_history"]["actor_count"],
        "fold_count": len(fold_reports),
        "actor_forecast_count": sum(score["actor_count"] for score in scores),
        "target_time_indices": list(declared["target_time_indices"]),
        "wave_gap": declared["wave_gap"],
        "training_policy": _TRAINING_POLICY,
        "evaluation_policy": _EVALUATION_POLICY,
        "folds": fold_reports,
        "models": models,
        "comparisons": comparisons,
        "metrics": deepcopy(_METRICS),
        "scope": deepcopy(_EVALUATION_SCOPE),
        "runtime": _runtime(),
    }
    report["content_hash"] = _hash(report)
    return report


def load_behavior_forecast_plan(path: str | Path) -> dict:
    """Load a strict plan and verify its canonical content hash."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return _validate_plan(json.load(handle, object_pairs_hook=unique_object))
