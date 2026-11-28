"""Independently check saved multi-origin forecast arithmetic and input binding.

Run only after the plan, forecasts, targets and evaluation have been retained.
This standard-library-only checker never imports SocioLab, fits a model, or
fetches observations. It computes errors directly from saved predictions and
targets, then pools the individual errors instead of aggregating reported RMSEs.
Output contains only aggregate results, counts, hashes and fixed check labels.
Passing does not authenticate sources, prove issuance time, or validate a model.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import sys


_PROFILE = "own-lag-outgoing-gap-ols-v1"
_MODELS = ("persistence", "own_lag_ols", "network_lag_ols")
_COMPARISONS = {"network_vs_own": "own_lag_ols", "network_vs_persistence": "persistence"}
_VARIANTS = ("raw", "clipped")
_ATOL = _RTOL = 1e-12
_DIRECTION = "network_minus_baseline_negative_favors_network"
_DATASET_FIELDS = {"dataset_id", "origin", "source_reference", "relation", "behavior_variable"}
_METRICS = {
    "primary": "mae", "secondary": "rmse", "primary_prediction": "clipped",
    "primary_aggregation": "pooled",
    "prediction_variants": ["raw", "clipped"], "aggregations": ["pooled", "macro"],
    "pooled_weight": "actor_forecast_count", "macro_weight": "equal_fold_weight",
    "difference_direction": _DIRECTION, "rounding": "none", "unit": "declared_behavior_level",
}
_PLAN_SCOPE = {
    "analysis": "retrospective_multi_origin_evaluation", "plan_uses_initial_history_only": True,
    "future_observations_consumed_at_plan_creation": False, "models_fitted_at_plan_creation": False,
    "fixed_roster_source": "initial_history", "late_revisions_in_same_plan_allowed": False,
    "historical_receipt_availability": "unknown", "historical_as_of_availability_verified": False,
    "forecast_issuance_before_target_observation_verified": False,
    "content_hash_authenticates_author": False, "content_hash_proves_prospective_timestamp": False,
    "wave_time_unit": "wave_index_not_calendar_duration", "ordinal_values_treated_as_numeric": True,
    "population_boundary_qualified": False, "actor_forecast_rows_independent": False,
    "uncertainty_intervals": False, "p_values": False, "calibration_status": "NOT_ESTIMATED",
    "prediction_intervals": None, "stability_established": False,
    "causal_effect_identified": False, "empirical_forecast_validated": False,
}
_EVALUATION_SCOPE = {
    **_PLAN_SCOPE, "full_prefix_extension_verified": True,
    "previous_target_matches_next_history": True, "refitting_performed_by_evaluation": False,
    "scores_recomputed_from_saved_forecasts_and_targets": True,
    "target_network_used_for_scoring": False, "fold_dropping": False,
    "actor_dropping": False, "output": "aggregate_only",
}
_FORECAST_SCOPE = {
    "analysis": "retrospective_temporal_holdout", "forecast_uses_history_prefix_only": True,
    "target_observations_consumed_at_creation": False, "target_network_consumed": False,
    "neighbor_direction": "outgoing_successors_in_each_known_wave", "no_outgoing_neighbor_gap": 0.0,
    "no_outgoing_neighbor_convention": "structural_zero_gap_not_missing_value_imputation",
    "actor_dropping": False, "behavior_imputation": False, "preprocessing_fitted": False,
    "historical_receipt_availability": "unknown", "historical_as_of_availability_verified": False,
    "population_boundary_qualified": False,
    "fixed_roster_contract": "same_supplied_actors_in_every_history_wave_and_target",
    "wave_time_unit": "wave_index_not_calendar_duration", "ordinal_values_treated_as_numeric": True,
    "scale_endpoints_required_in_history": False, "condition_number_threshold": None,
    "null_condition_number": "zero_smallest_singular_value_or_nonfinite_ratio",
    "coefficient_inference": False, "probabilistic_forecast": False,
    "calibration_status": "NOT_ESTIMATED", "prediction_intervals": None,
    "causal_effect_identified": False, "empirical_forecast_validated": False,
    "content_hash_authenticates_author": False, "content_hash_proves_prospective_timestamp": False,
    "prediction_artifact_contains_private_actor_records": True,
}
_SCORE_SCOPE = {**_FORECAST_SCOPE, "score_output": "aggregate_only", "target_used_only_for_scoring": True}
_SCORE_METRICS = {
    "primary": "mae", "secondary": "rmse", "primary_prediction": "clipped",
    "raw_metrics_reported": True, "rounding": "none", "same_actor_comparison": True,
    "unit": "declared_behavior_level", "uncertainty_intervals": False,
}


class CheckError(ValueError):
    """A fixed nonidentifying error code; never include supplied values."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CheckError(code)


def _digest(raw: bytes) -> str:
    return "sha256:" + sha256(raw).hexdigest()


def _hash(value: object) -> str:
    try:
        return _digest(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as error:
        raise CheckError("NONCANONICAL_JSON") from error


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _invalid_constant(_value):
    raise CheckError("NONFINITE_JSON_NUMBER")


def _load(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    _require(0 < len(raw) <= 30_000_000, "JSON_INPUT_SIZE")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CheckError("INVALID_JSON") from error
    _require(type(value) is dict, "JSON_OBJECT_REQUIRED")
    _hash(value)
    return value, _digest(raw)


def _fields(value, expected: set[str]) -> None:
    _require(type(value) is dict and set(value) == expected, "UNEXPECTED_OBJECT_FIELDS")


def _integer(value, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, "INVALID_INTEGER")
    return value


def _text(value) -> str:
    _require(type(value) is str and bool(value) and value.strip() == value, "INVALID_TEXT")
    return value


def _numbers(values, count: int) -> list[float]:
    _require(type(values) is list and len(values) == count, "NUMERIC_ARRAY_SHAPE")
    _require(all(type(value) in (int, float) and math.isfinite(value) for value in values),
             "NUMERIC_ARRAY_DOMAIN")
    return [float(value) for value in values]


class Checks:
    def __init__(self):
        self.count = 0
        self.numeric_count = 0
        self.max_absolute_error = 0.0
        self.failures = []

    def record(self, success: bool, name: str) -> None:
        self.count += 1
        if not success:
            self.failures.append(name)

    def exact(self, actual, expected, name: str) -> None:
        # Canonical equality also distinguishes booleans from numbers. Private
        # mappings are compared here as a whole; their actor keys are not logged.
        self.record(_hash(actual) == _hash(expected), name)

    def compare(self, actual, expected, name: str) -> None:
        if type(expected) is dict:
            valid = type(actual) is dict and set(actual) == set(expected)
            self.record(valid, name + ".fields")
            if valid:
                for key in sorted(expected):
                    self.compare(actual[key], expected[key], name + "." + key)
        elif type(expected) is list:
            valid = type(actual) is list and len(actual) == len(expected)
            self.record(valid, name + ".length")
            if valid:
                for index, item in enumerate(expected):
                    self.compare(actual[index], item, name + f".{index}")
        elif type(expected) is float:
            valid = type(actual) in (int, float) and math.isfinite(actual)
            if valid:
                error = abs(actual - expected)
                self.numeric_count += 1
                if math.isfinite(error):
                    self.max_absolute_error = max(self.max_absolute_error, error)
                valid = math.isclose(actual, expected, rel_tol=_RTOL, abs_tol=_ATOL)
            self.record(valid, name)
        else:
            self.record(type(actual) is type(expected) and actual == expected, name)


def _check_content_hash(value: dict, checks: Checks, name: str) -> None:
    checks.exact(value.get("content_hash"),
                 _hash({key: item for key, item in value.items() if key != "content_hash"}), name)


def _specification(spec: dict) -> tuple[int, int]:
    _fields(spec, {"schema", "profile", "behavior", "target_time_index", "research_question"})
    _require(spec["schema"] == "sociolab.behavior-forecast.v1" and spec["profile"] == _PROFILE,
             "UNSUPPORTED_SPECIFICATION")
    scale = spec["behavior"]
    _fields(scale, {"variable", "minimum", "maximum", "measurement_reference"})
    low, high = _integer(scale["minimum"]), _integer(scale["maximum"])
    _require(2 <= high - low + 1 <= 100, "INVALID_SCALE")
    _require(all(int(float(level)) == level for level in range(low, high + 1)), "INEXACT_SCALE")
    _text(scale["variable"])
    _text(scale["measurement_reference"])
    _text(spec["research_question"])
    _integer(spec["target_time_index"])
    return low, high


def _validate_history(history: dict, low: int, high: int) -> None:
    _fields(history, {"schema", *_DATASET_FIELDS, "actors", "waves"})
    _require(history["schema"] == "sociolab.longitudinal.v1", "UNSUPPORTED_HISTORY")
    actors = history["actors"]
    _require(type(actors) is list and 2 <= len(actors) <= 200, "INVALID_ROSTER")
    for actor in actors:
        _text(actor)
    _require(actors == sorted(set(actors)), "INVALID_ROSTER_ORDER")
    waves = history["waves"]
    _require(type(waves) is list and 2 <= len(waves) <= 32, "INVALID_HISTORY_LENGTH")
    times, revisions = [], []
    for wave in waves:
        _fields(wave, {"time_index", "source_revision", "network_complete", "edges", "behavior"})
        times.append(_integer(wave["time_index"]))
        revisions.append(_text(wave["source_revision"]))
        _require(wave["network_complete"] is True, "INCOMPLETE_HISTORY_NETWORK")
        edges = wave["edges"]
        _require(type(edges) is list, "INVALID_HISTORY_EDGES")
        pairs = []
        for edge in edges:
            _require(type(edge) is list and len(edge) == 2, "INVALID_HISTORY_EDGE")
            _require(all(type(node) is str and node in actors for node in edge)
                     and edge[0] != edge[1], "INVALID_HISTORY_ENDPOINT")
            pairs.append(tuple(edge))
        _require(pairs == sorted(set(pairs)), "INVALID_EDGE_ORDER")
        behavior = wave["behavior"]
        _require(type(behavior) is dict and set(behavior) == set(actors), "INVALID_BEHAVIOR_ROSTER")
        _require(all(type(value) is int and low <= value <= high for value in behavior.values()),
                 "INVALID_BEHAVIOR_LEVEL")
    _require(len(set(revisions)) == len(revisions), "REPEATED_HISTORY_REVISION")
    gap = times[1] - times[0]
    _require(gap > 0 and all(b - a == gap for a, b in zip(times, times[1:])), "INVALID_HISTORY_GAP")


def _features(history: dict) -> tuple[dict, dict]:
    """Reconstruct only input hashes using adjacency lists; do not fit or predict."""
    actors = history["actors"]
    matrices = []
    for wave in history["waves"]:
        adjacency = {actor: [] for actor in actors}
        for source, target in wave["edges"]:
            adjacency[source].append(target)
        own, network = [], []
        for actor in actors:
            value = float(wave["behavior"][actor])
            neighbors = adjacency[actor]
            gap = (math.fsum(float(wave["behavior"][other]) for other in neighbors) / len(neighbors)
                   - value) if neighbors else 0.0
            own.append([1.0, value])
            network.append([1.0, value, gap])
        matrices.append({"own_lag_ols": own, "network_lag_ols": network})
    training = {name: [row for matrix in matrices[:-1] for row in matrix[name]]
                for name in ("own_lag_ols", "network_lag_ols")}
    labels = [float(wave["behavior"][actor]) for wave in history["waves"][1:] for actor in actors]
    return ({"row_count": len(labels), "feature_hashes": {name: _hash(rows) for name, rows in training.items()},
             "label_hash": _hash(labels)}, {name: _hash(rows) for name, rows in matrices[-1].items()})


def _loss(errors: list[float]) -> dict:
    _require(bool(errors), "EMPTY_ERROR_ARRAY")
    value = {"mae": math.fsum(abs(error) for error in errors) / len(errors),
             "rmse": math.sqrt(math.fsum(error * error for error in errors) / len(errors))}
    _require(all(math.isfinite(item) for item in value.values()), "NONFINITE_LOSS")
    return value


def _model_errors(model: dict, name: str, history: dict, target: dict,
                  low: int, high: int, checks: Checks, label: str) -> tuple[dict, dict | None]:
    _fields(model, {"status", "reason", "algorithm", "feature_names", "training_row_count", "coefficients",
                    "rank", "singular_values", "residual_sum_squares", "condition_number", "raw_predictions",
                    "clipped_predictions", "clipping_count"})
    actors = history["actors"]
    _require(model["status"] in ("OK", "NOT_ESTIMABLE"), "INVALID_MODEL_STATUS")
    features = (["own_lag"] if name == "persistence" else ["intercept", "own_lag"]
                + (["outgoing_mean_minus_own"] if name == "network_lag_ols" else []))
    checks.exact(model["feature_names"], features, label + ".features")
    if name == "persistence":
        checks.exact(model["algorithm"], "last_observed_behavior", label + ".algorithm")
        checks.exact(model["training_row_count"], 0, label + ".training_rows")
        for key in ("coefficients", "rank", "singular_values", "residual_sum_squares", "condition_number"):
            checks.exact(model[key], None, label + "." + key)
        reason = None
    else:
        rows, columns = len(actors) * (len(history["waves"]) - 1), len(features)
        checks.exact(model["algorithm"], "numpy.linalg.lstsq", label + ".algorithm")
        checks.exact(model["training_row_count"], rows, label + ".training_rows")
        rank = _integer(model["rank"], 1)
        _require(rank <= min(rows, columns), "INVALID_RETAINED_RANK")
        _numbers(model["coefficients"], columns)
        singular = _numbers(model["singular_values"], min(rows, columns))
        _require(singular == sorted(singular, reverse=True) and singular[0] > 0 and singular[-1] >= 0,
                 "INVALID_RETAINED_SINGULAR_VALUES")
        residuals = _numbers(model["residual_sum_squares"], 1 if rows > columns and rank == columns else 0)
        _require(all(value >= 0 for value in residuals), "INVALID_RETAINED_RESIDUALS")
        condition = singular[0] / singular[-1] if singular[-1] > 0 else None
        if condition is not None and not math.isfinite(condition):
            condition = None
        checks.compare(model["condition_number"], condition, label + ".condition_number")
        reason = ("insufficient_training_rows" if rows <= columns else
                  "rank_deficient_training_design" if rank < columns else None)
    checks.exact(model["status"], "OK" if reason is None else "NOT_ESTIMABLE", label + ".status")
    checks.exact(model["reason"], reason, label + ".reason")
    if model["status"] == "NOT_ESTIMABLE":
        for key in ("raw_predictions", "clipped_predictions", "clipping_count"):
            checks.exact(model[key], None, label + "." + key)
        return ({"status": "NOT_ESTIMABLE", "reason": model["reason"], "n_evaluated": 0,
                 "clipping_count": None, "raw": None, "clipped": None}, None)
    raw = _numbers(model["raw_predictions"], len(actors))
    clipped = _numbers(model["clipped_predictions"], len(actors))
    checks.exact(clipped, [min(max(value, float(low)), float(high)) for value in raw], label + ".clipping")
    count = sum(a != b for a, b in zip(raw, clipped))
    checks.exact(model["clipping_count"], count, label + ".clipping_count")
    if name == "persistence":
        checks.exact(raw, [float(history["waves"][-1]["behavior"][actor]) for actor in actors],
                     label + ".last_observation_binding")
    actual = [float(target["behavior"][actor]) for actor in actors]
    errors = {variant: [prediction - observed for prediction, observed in zip(values, actual)]
              for variant, values in (("raw", raw), ("clipped", clipped))}
    return ({"status": "OK", "reason": model["reason"], "n_evaluated": len(actors),
             "clipping_count": count, **{variant: _loss(errors[variant]) for variant in _VARIANTS}}, errors)


def _score(forecast: dict, history: dict, target: dict, low: int, high: int,
           runtime: dict, checks: Checks, label: str) -> tuple[dict, dict]:
    _fields(target, {"schema", "dataset_id", "origin", "source_reference", "behavior_variable",
                     "time_index", "source_revision", "behavior"})
    _require(target["schema"] == "sociolab.behavior-target.v1", "UNSUPPORTED_TARGET")
    _text(target["source_revision"])
    checks.exact(target["time_index"], forecast["specification"]["target_time_index"], label + ".target_time")
    for field in ("dataset_id", "origin", "source_reference", "behavior_variable"):
        checks.exact(target[field], history[field], label + ".target_" + field)
    _require(type(target["behavior"]) is dict and set(target["behavior"]) == set(history["actors"]),
             "TARGET_ROSTER_MISMATCH")
    _require(all(type(value) is int and low <= value <= high for value in target["behavior"].values()),
             "INVALID_TARGET_LEVEL")
    _fields(forecast["models"], set(_MODELS))
    models, errors = {}, {}
    for name in _MODELS:
        models[name], errors[name] = _model_errors(forecast["models"][name], name, history, target,
                                                  low, high, checks, label + "." + name)
    comparisons = {}
    for name, baseline in _COMPARISONS.items():
        available = models["network_lag_ols"]["status"] == models[baseline]["status"] == "OK"
        comparisons[name] = {
            "status": "OK" if available else "NOT_ESTIMABLE",
            "reason": None if available else "required_forecast_not_estimable",
            "n_evaluated": len(history["actors"]) if available else 0, "direction": _DIRECTION,
            **{variant: {metric + "_difference": models["network_lag_ols"][variant][metric]
                         - models[baseline][variant][metric] for metric in ("mae", "rmse")}
               if available else None for variant in _VARIANTS},
        }
    score = {
        "schema": "sociolab.behavior-forecast-score.v1", "kind": "BEHAVIOR_FORECAST_SCORE", "profile": _PROFILE,
        "dataset_id": history["dataset_id"], "behavior_variable": history["behavior_variable"],
        "forecast_hash": forecast["content_hash"], "history_prefix_hash": _hash(history),
        "specification_hash": _hash(forecast["specification"]), "target_behavior_hash": _hash(target),
        "target_source_revision": target["source_revision"], "target_time_index": target["time_index"],
        "actor_count": len(history["actors"]), "models": models, "comparisons": comparisons,
        "metrics": _SCORE_METRICS, "scope": _SCORE_SCOPE, "runtime": runtime,
    }
    return score, errors


def _aggregate(scores: list[dict], errors: list[dict], times: list[int], actors: int) -> tuple[dict, dict]:
    def coverage(names):
        failed = [time for time, score in zip(times, scores)
                  if any(score["models"][name]["status"] != "OK" for name in names)]
        available = len(times) - len(failed)
        return {"expected_fold_count": len(times), "available_fold_count": available,
                "expected_actor_forecast_count": len(times) * actors,
                "available_actor_forecast_count": available * actors, "failed_target_time_indices": failed}

    models = {}
    for name in _MODELS:
        covered = coverage((name,))
        complete = not covered["failed_target_time_indices"]
        variants = {variant: None for variant in _VARIANTS}
        if complete:
            for variant in _VARIANTS:
                # Pool original individual errors, not retained scores or fold RMSEs.
                pooled = _loss([error for fold in errors for error in fold[name][variant]])
                macro = {metric: math.fsum(score["models"][name][variant][metric] for score in scores)
                         / len(scores) for metric in ("mae", "rmse")}
                variants[variant] = {"pooled": pooled, "macro": macro}
        models[name] = {
            "status": "OK" if complete else "NOT_ESTIMABLE",
            "reason": None if complete else "not_estimable_in_all_planned_folds", **covered,
            "clipping_count": sum(score["models"][name]["clipping_count"] for score in scores) if complete else None,
            **variants,
        }
    comparisons = {}
    for name, baseline in _COMPARISONS.items():
        covered = coverage(("network_lag_ols", baseline))
        complete = not covered["failed_target_time_indices"]
        comparisons[name] = {
            "status": "OK" if complete else "NOT_ESTIMABLE",
            "reason": None if complete else "required_model_not_estimable_in_all_planned_folds",
            **covered, "direction": _DIRECTION,
            **{variant: {aggregation: {
                metric + "_difference": models["network_lag_ols"][variant][aggregation][metric]
                - models[baseline][variant][aggregation][metric] for metric in ("mae", "rmse")}
                for aggregation in ("pooled", "macro")} if complete else None for variant in _VARIANTS},
        }
    return models, comparisons


def check(plan_path: Path, manifest_path: Path, report_path: Path) -> dict:
    plan, plan_bytes_hash = _load(plan_path)
    manifest, manifest_bytes_hash = _load(manifest_path)
    report, report_bytes_hash = _load(report_path)
    checks = Checks()
    _fields(plan, {"schema", "kind", "profile", "dataset", "initial_history", "specification",
                   "target_time_indices", "wave_gap", "training_policy", "evaluation_policy",
                   "metrics", "scope", "content_hash"})
    _require(plan["schema"] == "sociolab.behavior-forecast-plan.v1" and plan["kind"] == "BEHAVIOR_FORECAST_PLAN"
             and plan["profile"] == _PROFILE, "UNSUPPORTED_PLAN")
    _check_content_hash(plan, checks, "plan.content_hash")
    low, high = _specification(plan["specification"])
    _fields(plan["dataset"], _DATASET_FIELDS)
    _fields(plan["initial_history"], {"content_hash", "actor_count", "actor_roster_hash", "wave_time_indices",
                                      "wave_source_revisions"})
    times = plan["target_time_indices"]
    _require(type(times) is list and 2 <= len(times) <= 31, "INVALID_TARGET_SCHEDULE")
    for time in times:
        _integer(time)
    gap = _integer(plan["wave_gap"], 1)
    checks.exact(times, [times[0] + index * gap for index in range(len(times))], "plan.consecutive_targets")
    checks.exact(times[0], plan["specification"]["target_time_index"], "plan.first_target")
    checks.exact(plan["metrics"], _METRICS, "plan.metrics")
    checks.exact(plan["scope"], _PLAN_SCOPE, "plan.scope")
    checks.exact(plan["training_policy"], "expanding_immutable_prefix", "plan.training_policy")
    checks.exact(plan["evaluation_policy"], "all_planned_folds_fixed_roster", "plan.evaluation_policy")
    _fields(manifest, {"schema", "folds"})
    _require(manifest["schema"] == "sociolab.behavior-forecast-fold-manifest.v1", "UNSUPPORTED_MANIFEST")
    _require(type(manifest["folds"]) is list and len(manifest["folds"]) == len(times), "INCOMPLETE_MANIFEST")
    _require(type(report.get("folds")) is list and len(report["folds"]) == len(times), "INCOMPLETE_REPORT")
    _fields(report["runtime"], {"python", "numpy", "networkx"})
    for version in report["runtime"].values():
        _text(version)
    _check_content_hash(report, checks, "evaluation.content_hash")
    expected_folds, all_errors, inputs = [], [], []
    previous_history = previous_target = None
    actors = None
    for index, (entry, time, retained) in enumerate(zip(manifest["folds"], times, report["folds"]), start=1):
        label = f"fold.{index}"
        _fields(entry, {"history", "forecast", "target"})
        objects, hashes = {}, {}
        for name in ("history", "forecast", "target"):
            path = Path(_text(entry[name]))
            if not path.is_absolute():
                path = manifest_path.parent / path
            objects[name], hashes[name + "_file_sha256"] = _load(path)
        history, forecast, target = (objects[name] for name in ("history", "forecast", "target"))
        _validate_history(history, low, high)
        dataset = {key: history[key] for key in _DATASET_FIELDS}
        checks.exact(dataset, plan["dataset"], label + ".dataset")
        checks.exact(history["relation"], "directed_observed_social_tie", label + ".relation")
        checks.exact(history["behavior_variable"], plan["specification"]["behavior"]["variable"], label + ".variable")
        wave_times = [wave["time_index"] for wave in history["waves"]]
        revisions = [wave["source_revision"] for wave in history["waves"]]
        initial = {"content_hash": _hash(history), "actor_count": len(history["actors"]),
                   "actor_roster_hash": _hash(history["actors"]), "wave_time_indices": wave_times,
                   "wave_source_revisions": revisions}
        if previous_history is None:
            checks.exact(initial, plan["initial_history"], label + ".initial_history")
            actors = len(history["actors"])
        else:
            checks.exact(history["actors"], previous_history["actors"], label + ".fixed_roster")
            checks.exact(history["waves"][:-1], previous_history["waves"], label + ".full_prefix_extension")
            checks.exact(history["waves"][-1]["time_index"], previous_target["time_index"], label + ".prior_target_time")
            checks.exact(history["waves"][-1]["behavior"], previous_target["behavior"], label + ".prior_target_values")
        checks.exact(wave_times[-1] + gap, time, label + ".one_step_horizon")
        checks.exact(wave_times[1] - wave_times[0], gap, label + ".wave_gap")
        _fields(forecast, {"schema", "kind", "profile", "dataset", "actors", "history", "specification",
                           "specification_hash", "training", "forecast_input_hashes", "models", "runtime",
                           "scope", "content_hash"})
        _check_content_hash(forecast, checks, label + ".forecast_hash")
        checks.exact(forecast["schema"], "sociolab.behavior-forecast-artifact.v1", label + ".forecast_schema")
        checks.exact(forecast["kind"], "BEHAVIOR_FORECAST", label + ".forecast_kind")
        checks.exact(forecast["profile"], _PROFILE, label + ".forecast_profile")
        checks.exact(forecast["actors"], history["actors"], label + ".forecast_roster")
        checks.exact(forecast["dataset"], dataset, label + ".forecast_dataset")
        checks.exact(forecast["specification"], {**plan["specification"], "target_time_index": time}, label + ".specification")
        checks.exact(forecast["specification_hash"], _hash(forecast["specification"]), label + ".specification_hash")
        checks.exact(forecast["scope"], _FORECAST_SCOPE, label + ".forecast_scope")
        checks.exact(forecast["history"], {
            "content_hash": _hash(history), "wave_time_indices": wave_times, "wave_source_revisions": revisions,
            "origin_time_index": wave_times[-1], "wave_gap": gap, "transition_count": len(wave_times) - 1,
        }, label + ".history_binding")
        training, forecast_inputs = _features(history)
        checks.exact(forecast["training"], training, label + ".training_input_hashes")
        checks.exact(forecast["forecast_input_hashes"], forecast_inputs, label + ".forecast_input_hashes")
        score, errors = _score(forecast, history, target, low, high, report["runtime"], checks, label)
        _fields(retained, {"fold_index", "origin_time_index", "target_time_index", "history_prefix_hash",
                           "forecast_hash", "score_hash", "score"})
        expected_folds.append({
            "fold_index": index, "origin_time_index": wave_times[-1], "target_time_index": time,
            "history_prefix_hash": _hash(history), "forecast_hash": forecast["content_hash"],
            # The retained score's exact hash is checked separately from its
            # approximately equal independent floating-point recalculation.
            "score_hash": _hash(retained["score"]), "score": score,
        })
        all_errors.append(errors)
        inputs.append({"fold_index": index, **hashes, "history_content_hash": _hash(history),
                       "forecast_content_hash": forecast["content_hash"], "target_content_hash": _hash(target),
                       "retained_score_hash": _hash(retained["score"])})
        previous_history, previous_target = history, target
    models, comparisons = _aggregate([fold["score"] for fold in expected_folds], all_errors, times, actors)
    expected = {
        "schema": "sociolab.behavior-forecast-evaluation.v1", "kind": "BEHAVIOR_FORECAST_EVALUATION",
        "profile": _PROFILE, "plan_hash": plan["content_hash"], "dataset": plan["dataset"],
        "actor_count": actors, "fold_count": len(times), "actor_forecast_count": actors * len(times),
        "target_time_indices": times, "wave_gap": gap, "training_policy": "expanding_immutable_prefix",
        "evaluation_policy": "all_planned_folds_fixed_roster", "folds": expected_folds,
        "models": models, "comparisons": comparisons, "metrics": _METRICS,
        "scope": _EVALUATION_SCOPE, "runtime": report["runtime"],
    }
    checks.compare({key: value for key, value in report.items() if key != "content_hash"}, expected, "evaluation")
    result = {
        "schema": "sociolab.independent-forecast-evaluation-check.v1",
        "kind": "INDEPENDENT_BEHAVIOR_FORECAST_EVALUATION_CHECK",
        "status": "PASS" if not checks.failures else "FAIL",
        "method": "stdlib_saved_prediction_error_arithmetic_no_refit",
        "inputs": {"plan_file_sha256": plan_bytes_hash, "manifest_file_sha256": manifest_bytes_hash,
                   "evaluation_file_sha256": report_bytes_hash, "plan_content_hash": plan["content_hash"],
                   "evaluation_content_hash": report["content_hash"], "folds": inputs},
        "actor_count": actors, "fold_count": len(times), "actor_forecast_count": actors * len(times),
        "comparisons": {"check_count": checks.count, "numeric_comparison_count": checks.numeric_count,
                        "failed_count": len(checks.failures), "failed_checks": checks.failures,
                        "max_absolute_error": checks.max_absolute_error,
                        "absolute_tolerance": _ATOL, "relative_tolerance": _RTOL},
        "recomputed": {"models": models, "comparisons": comparisons},
        "scope": {"sociolab_imported": False, "models_refitted": False, "raw_data_fetched": False,
                  "original_errors_pooled_directly": True, "feature_hashes_reconstructed_from_adjacency": True,
                  "coefficients_independently_verified": False, "solver_rank_independently_verified": False,
                  "retained_diagnostic_consistency_checked": True, "hashes_prove_authenticity_or_issuance_time": False,
                  "historical_as_of_availability_verified": False, "causal_effect_identified": False,
                  "empirical_forecast_validated": False, "output": "aggregate_only"},
        "runtime": {"python": platform.python_version(), "third_party_dependencies": []},
        "checker_sha256": _digest(Path(__file__).read_bytes()),
    }
    result["content_hash"] = _hash(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "manifest", "report", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    arguments = parser.parse_args()
    try:
        _require(not arguments.output.exists(), "OUTPUT_ALREADY_EXISTS")
        result = check(arguments.plan, arguments.manifest, arguments.report)
        with arguments.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        print(json.dumps({"status": result["status"], "check_count": result["comparisons"]["check_count"],
                          "failed_count": result["comparisons"]["failed_count"]}, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except CheckError as error:
        print("independent check rejected: " + str(error), file=sys.stderr)
    except OSError:
        print("independent check rejected: FILE_ACCESS_ERROR", file=sys.stderr)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        print("independent check rejected: INVALID_INPUT_STRUCTURE_OR_ARITHMETIC", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
