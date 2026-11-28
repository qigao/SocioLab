"""Past-only behavioral forecasts with a separate, aggregate scoring boundary.

This small fixed profile is a descriptive prediction comparison, not an influence
estimator. The issuer accepts only a history prefix and a predeclared spec. Its
private artifact is an ordinary JSON object with an integrity hash, not a signed
or independently timestamped assertion of historical availability.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import re

import networkx as nx
import numpy as np

from ._json import unique_object
from .panels import LongitudinalPanel

_PROFILE = "own-lag-outgoing-gap-ols-v1"
_MODEL_IDS = ("persistence", "own_lag_ols", "network_lag_ols")
_FEATURES = {
    "persistence": ["own_lag"],
    "own_lag_ols": ["intercept", "own_lag"],
    "network_lag_ols": ["intercept", "own_lag", "outgoing_mean_minus_own"],
}
_MODEL_FIELDS = {
    "status", "reason", "algorithm", "feature_names", "training_row_count",
    "coefficients", "rank", "singular_values", "residual_sum_squares",
    "condition_number", "raw_predictions", "clipped_predictions", "clipping_count",
}
_ARTIFACT_FIELDS = {
    "schema", "kind", "profile", "dataset", "actors", "history", "specification",
    "specification_hash", "training", "forecast_input_hashes", "models", "runtime",
    "scope", "content_hash",
}
_TARGET_FIELDS = {
    "schema", "dataset_id", "origin", "source_reference", "behavior_variable",
    "time_index", "source_revision", "behavior",
}
_SCOPE = {
    "analysis": "retrospective_temporal_holdout",
    "forecast_uses_history_prefix_only": True,
    "target_observations_consumed_at_creation": False,
    "target_network_consumed": False,
    "neighbor_direction": "outgoing_successors_in_each_known_wave",
    "no_outgoing_neighbor_gap": 0.0,
    "no_outgoing_neighbor_convention": "structural_zero_gap_not_missing_value_imputation",
    "actor_dropping": False,
    "behavior_imputation": False,
    "preprocessing_fitted": False,
    "historical_receipt_availability": "unknown",
    "historical_as_of_availability_verified": False,
    "population_boundary_qualified": False,
    "fixed_roster_contract": "same_supplied_actors_in_every_history_wave_and_target",
    "wave_time_unit": "wave_index_not_calendar_duration",
    "ordinal_values_treated_as_numeric": True,
    "scale_endpoints_required_in_history": False,
    "condition_number_threshold": None,
    "null_condition_number": "zero_smallest_singular_value_or_nonfinite_ratio",
    "coefficient_inference": False,
    "probabilistic_forecast": False,
    "calibration_status": "NOT_ESTIMATED",
    "prediction_intervals": None,
    "causal_effect_identified": False,
    "empirical_forecast_validated": False,
    "content_hash_authenticates_author": False,
    "content_hash_proves_prospective_timestamp": False,
    "prediction_artifact_contains_private_actor_records": True,
}
_SCORE_SCOPE = {**_SCOPE, "score_output": "aggregate_only", "target_used_only_for_scoring": True}


def _hash(value: object) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError("forecast values must have finite, canonical JSON representations") from exc
    return "sha256:" + sha256(raw).hexdigest()


def _fields(value: object, expected: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} must use exact fields")


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonempty, trimmed text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{name} must be UTF-8 text") from exc
    return value


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: object, name: str) -> float:
    if type(value) not in (float, int):
        raise ValueError(f"{name} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not finite:
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _hash_value(value: object, name: str) -> None:
    if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a canonical SHA-256 hash")


def _origin(origin: object, reference: object) -> None:
    if origin == "synthetic":
        if reference is not None:
            raise ValueError("synthetic data cannot claim an external source")
    elif origin == "external_observation":
        if type(reference) is not str or re.fullmatch(r"https://[^\s]+", reference) is None:
            raise ValueError("external observations require an HTTPS source reference")
        _text(reference, "source_reference")
    else:
        raise ValueError("unsupported forecast origin")


def _validate_spec(spec: object) -> dict:
    _fields(spec, {"schema", "profile", "behavior", "target_time_index", "research_question"},
            "forecast specification")
    if spec["schema"] != "sociolab.behavior-forecast.v1" or spec["profile"] != _PROFILE:
        raise ValueError("unsupported behavioral forecast schema or profile")
    behavior = spec["behavior"]
    _fields(behavior, {"variable", "minimum", "maximum", "measurement_reference"}, "behavior scale")
    _text(behavior["variable"], "behavior variable")
    _text(behavior["measurement_reference"], "measurement_reference")
    low = _integer(behavior["minimum"], "behavior minimum")
    high = _integer(behavior["maximum"], "behavior maximum")
    if high <= low or high - low + 1 > 100:
        raise ValueError("behavior scale must have between 2 and 100 declared integer levels")
    # Every admitted level must survive the float64 solver input conversion.
    for level in range(low, high + 1):
        if int(_number(level, "behavior level")) != level:
            raise ValueError("every behavior scale level must be exactly representable in float64")
    _integer(spec["target_time_index"], "target_time_index")
    _text(spec["research_question"], "research_question")
    _hash(spec)
    return deepcopy(spec)


def _runtime() -> dict:
    return {"python": platform.python_version(), "numpy": np.__version__, "networkx": nx.__version__}


def _condition_number(singular_values: list[float]) -> float | None:
    if not singular_values or singular_values[-1] == 0:
        return None
    ratio = singular_values[0] / singular_values[-1]
    return ratio if math.isfinite(ratio) else None


def _predictions(raw: np.ndarray, low: int, high: int) -> tuple[list[float], list[float], int]:
    if not np.isfinite(raw).all():
        raise ValueError("forecast predictions must be finite")
    clipped = np.clip(raw, low, high)
    return raw.tolist(), clipped.tolist(), int(np.count_nonzero(raw != clipped))


def _features(history: LongitudinalPanel) -> list[dict[str, np.ndarray]]:
    waves = []
    for wave in history.waves:
        values = dict(wave.behavior)
        graph = nx.DiGraph()
        graph.add_nodes_from(history.actors)
        graph.add_edges_from(wave.edges)
        rows = []
        for actor in history.actors:
            own = float(values[actor])
            neighbors = tuple(graph.successors(actor))
            gap = math.fsum(float(values[neighbor]) for neighbor in neighbors) / len(neighbors) - own if neighbors else 0.0
            rows.append([1.0, own, gap])
        network = np.asarray(rows, dtype=np.float64)
        waves.append({"own_lag_ols": network[:, :2].copy(), "network_lag_ols": network})
    return waves


def make_behavior_forecast(history: LongitudinalPanel, spec: dict) -> dict:
    """Freeze three fixed forecasts from a complete prefix, without target input.

    Returned actor IDs and predictions are private local scoring material. JSON
    consumers must preserve the artifact intact; its hash detects content changes
    but does not establish who created it or when it existed.
    """
    if not isinstance(history, LongitudinalPanel):
        raise TypeError("history must be a LongitudinalPanel prefix")
    specification = _validate_spec(spec)
    if len(history.actors) > 200 or len(history.waves) > 32:
        raise ValueError("forecast budget is at most 200 actors and 32 history waves")
    # Revalidate the dataclass contract at this public boundary as well.
    LongitudinalPanel.from_mapping(history.to_dict())
    if any(not wave.network_complete for wave in history.waves):
        raise ValueError("all history networks must be explicitly complete")
    scale = specification["behavior"]
    if history.behavior_variable != scale["variable"]:
        raise ValueError("history behavior variable does not match the specification")
    low, high = scale["minimum"], scale["maximum"]
    if any(type(value) is not int or not low <= value <= high
           for wave in history.waves for _, value in wave.behavior):
        raise ValueError("all history behavior must be known integer levels within the declared scale")
    times = [wave.time_index for wave in history.waves]
    gap = times[1] - times[0]
    if any(right - left != gap for left, right in zip(times, times[1:])):
        raise ValueError("history waves must have a constant positive wave-index gap")
    if specification["target_time_index"] != times[-1] + gap:
        raise ValueError("target must be the next wave after the history prefix at the same gap")

    features = _features(history)
    train = {name: np.concatenate([wave[name] for wave in features[:-1]], axis=0)
             for name in ("own_lag_ols", "network_lag_ols")}
    labels = np.asarray([float(value) for wave in history.waves[1:] for _, value in wave.behavior],
                        dtype=np.float64)
    last = features[-1]
    raw, clipped, clipping_count = _predictions(last["own_lag_ols"][:, 1], low, high)
    models = {
        "persistence": {
            "status": "OK", "reason": None, "algorithm": "last_observed_behavior",
            "feature_names": list(_FEATURES["persistence"]), "training_row_count": 0,
            "coefficients": None, "rank": None, "singular_values": None,
            "residual_sum_squares": None, "condition_number": None,
            "raw_predictions": raw, "clipped_predictions": clipped, "clipping_count": clipping_count,
        }
    }
    for name, matrix in train.items():
        coefficients, residuals, rank, singular_values = np.linalg.lstsq(matrix, labels, rcond=None)
        if not all(np.isfinite(array).all() for array in (coefficients, residuals, singular_values)):
            raise ValueError("least-squares diagnostics must be finite")
        row_count, column_count = matrix.shape
        reason = ("insufficient_training_rows" if row_count <= column_count else
                  "rank_deficient_training_design" if rank != column_count else None)
        raw, clipped, clipping_count = (None, None, None)
        if reason is None:
            raw, clipped, clipping_count = _predictions(last[name] @ coefficients, low, high)
        singular = singular_values.tolist()
        models[name] = {
            "status": "OK" if reason is None else "NOT_ESTIMABLE", "reason": reason,
            "algorithm": "numpy.linalg.lstsq", "feature_names": list(_FEATURES[name]),
            "training_row_count": row_count, "coefficients": coefficients.tolist(),
            "rank": int(rank), "singular_values": singular, "residual_sum_squares": residuals.tolist(),
            "condition_number": _condition_number(singular),
            "raw_predictions": raw, "clipped_predictions": clipped, "clipping_count": clipping_count,
        }
    artifact = {
        "schema": "sociolab.behavior-forecast-artifact.v1", "kind": "BEHAVIOR_FORECAST", "profile": _PROFILE,
        "dataset": {"dataset_id": history.dataset_id, "origin": history.origin,
                    "source_reference": history.source_reference, "relation": history.relation,
                    "behavior_variable": history.behavior_variable},
        "actors": list(history.actors),
        "history": {"content_hash": history.content_hash, "wave_time_indices": times,
                    "wave_source_revisions": [wave.source_revision for wave in history.waves],
                    "origin_time_index": times[-1], "wave_gap": gap, "transition_count": len(times) - 1},
        "specification": specification, "specification_hash": _hash(specification),
        "training": {"row_count": len(labels),
                     "feature_hashes": {name: _hash(matrix.tolist()) for name, matrix in train.items()},
                     "label_hash": _hash(labels.tolist())},
        "forecast_input_hashes": {name: _hash(matrix.tolist()) for name, matrix in last.items()},
        "models": models, "runtime": _runtime(), "scope": deepcopy(_SCOPE),
    }
    artifact["content_hash"] = _hash(artifact)
    return artifact


def _numeric_list(value: object, length: int, name: str, *, nonnegative: bool = False) -> list[float]:
    if type(value) is not list or len(value) != length:
        raise ValueError(f"{name} must be a list of length {length}")
    result = [_number(item, name) for item in value]
    if nonnegative and any(item < 0 for item in result):
        raise ValueError(f"{name} must be nonnegative")
    return result


def _validate_model(model: object, name: str, row_count: int, actor_count: int, low: int, high: int) -> None:
    _fields(model, _MODEL_FIELDS, f"{name} model")
    if model["feature_names"] != _FEATURES[name]:
        raise ValueError("unexpected model feature names or order")
    if name == "persistence":
        if model["algorithm"] != "last_observed_behavior" or model["status"] != "OK" or model["reason"] is not None:
            raise ValueError("persistence status or algorithm is invalid")
        if _integer(model["training_row_count"], "persistence training_row_count") != 0:
            raise ValueError("persistence must not claim fitted rows")
        if any(model[key] is not None for key in
               ("coefficients", "rank", "singular_values", "residual_sum_squares", "condition_number")):
            raise ValueError("persistence must not claim fitted diagnostics")
    else:
        if model["algorithm"] != "numpy.linalg.lstsq":
            raise ValueError("unexpected least-squares algorithm")
        if _integer(model["training_row_count"], "training_row_count") != row_count:
            raise ValueError("model training row count does not match history")
        columns = len(_FEATURES[name])
        _numeric_list(model["coefficients"], columns, "coefficients")
        rank = _integer(model["rank"], "rank")
        if not 1 <= rank <= min(row_count, columns):
            raise ValueError("least-squares rank is invalid for an intercept design")
        singular = _numeric_list(model["singular_values"], min(row_count, columns), "singular_values", nonnegative=True)
        if singular != sorted(singular, reverse=True) or singular[0] == 0:
            raise ValueError("singular values must be positive-leading and descending")
        residual_length = 1 if row_count > columns and rank == columns else 0
        _numeric_list(model["residual_sum_squares"], residual_length, "residual_sum_squares", nonnegative=True)
        condition = model["condition_number"]
        if condition is not None:
            _number(condition, "condition_number")
        if condition != _condition_number(singular):
            raise ValueError("condition number does not match singular values")
        reason = ("insufficient_training_rows" if row_count <= columns else
                  "rank_deficient_training_design" if rank != columns else None)
        if model["reason"] != reason or model["status"] != ("OK" if reason is None else "NOT_ESTIMABLE"):
            raise ValueError("model status does not match its training scope")
    if model["status"] == "NOT_ESTIMABLE":
        if any(model[key] is not None for key in ("raw_predictions", "clipped_predictions", "clipping_count")):
            raise ValueError("not estimable models cannot supply predictions")
        return
    raw = _numeric_list(model["raw_predictions"], actor_count, "raw_predictions")
    clipped = _numeric_list(model["clipped_predictions"], actor_count, "clipped_predictions")
    if clipped != [min(max(value, low), high) for value in raw]:
        raise ValueError("clipped predictions do not match the declared scale")
    count = _integer(model["clipping_count"], "clipping_count")
    if count != sum(left != right for left, right in zip(raw, clipped)):
        raise ValueError("clipping count does not match predictions")
    if name == "persistence" and (count != 0 or any(value != int(value) for value in raw)):
        raise ValueError("persistence predictions must be known integer behavior levels")


def _validate_forecast(forecast: object) -> dict:
    _fields(forecast, _ARTIFACT_FIELDS, "forecast artifact")
    if (forecast["schema"] != "sociolab.behavior-forecast-artifact.v1" or
            forecast["kind"] != "BEHAVIOR_FORECAST" or forecast["profile"] != _PROFILE):
        raise ValueError("unsupported forecast artifact schema, kind or profile")
    _hash_value(forecast["content_hash"], "content_hash")
    if forecast["content_hash"] != _hash({key: value for key, value in forecast.items() if key != "content_hash"}):
        raise ValueError("forecast content hash does not match its contents")
    spec = _validate_spec(forecast["specification"])
    if forecast["specification_hash"] != _hash(spec):
        raise ValueError("specification hash does not match its contents")
    dataset = forecast["dataset"]
    _fields(dataset, {"dataset_id", "origin", "source_reference", "relation", "behavior_variable"}, "dataset")
    _text(dataset["dataset_id"], "dataset_id")
    _origin(dataset["origin"], dataset["source_reference"])
    if dataset["relation"] != "directed_observed_social_tie" or dataset["behavior_variable"] != spec["behavior"]["variable"]:
        raise ValueError("dataset relation or behavior variable does not match profile")
    actors = forecast["actors"]
    if type(actors) is not list or not 2 <= len(actors) <= 200:
        raise ValueError("forecast must contain between 2 and 200 actors")
    for actor in actors:
        _text(actor, "actor")
    if actors != sorted(set(actors)):
        raise ValueError("forecast actors must be unique and sorted")
    history = forecast["history"]
    _fields(history, {"content_hash", "wave_time_indices", "wave_source_revisions", "origin_time_index",
                      "wave_gap", "transition_count"}, "history metadata")
    _hash_value(history["content_hash"], "history content_hash")
    times = history["wave_time_indices"]
    if type(times) is not list or not 2 <= len(times) <= 32:
        raise ValueError("forecast history must contain between 2 and 32 waves")
    for time in times:
        _integer(time, "wave_time_index")
    gap = _integer(history["wave_gap"], "wave_gap", 1)
    if any(right - left != gap for left, right in zip(times, times[1:])):
        raise ValueError("forecast history times must have the stated positive gap")
    if (_integer(history["origin_time_index"], "origin_time_index") != times[-1] or
            _integer(history["transition_count"], "transition_count", 1) != len(times) - 1 or
            spec["target_time_index"] != times[-1] + gap):
        raise ValueError("forecast origin, target or transition count does not match history")
    revisions = history["wave_source_revisions"]
    if type(revisions) is not list or len(revisions) != len(times):
        raise ValueError("forecast needs a source revision for every history wave")
    for revision in revisions:
        _text(revision, "wave_source_revision")
    if len(set(revisions)) != len(revisions):
        raise ValueError("history wave revisions must be distinct")
    training = forecast["training"]
    _fields(training, {"row_count", "feature_hashes", "label_hash"}, "training metadata")
    row_count = len(actors) * (len(times) - 1)
    if _integer(training["row_count"], "training row_count") != row_count:
        raise ValueError("training row count must include every actor in every adjacent transition")
    _hash_value(training["label_hash"], "label_hash")
    for hash_mapping in (training["feature_hashes"], forecast["forecast_input_hashes"]):
        _fields(hash_mapping, {"own_lag_ols", "network_lag_ols"}, "feature hashes")
        for value in hash_mapping.values():
            _hash_value(value, "feature hash")
    _fields(forecast["models"], set(_MODEL_IDS), "models")
    for name in _MODEL_IDS:
        _validate_model(forecast["models"][name], name, row_count, len(actors),
                        spec["behavior"]["minimum"], spec["behavior"]["maximum"])
    _fields(forecast["runtime"], {"python", "numpy", "networkx"}, "runtime")
    for name, value in forecast["runtime"].items():
        _text(value, f"runtime {name}")
    if forecast["scope"] != _SCOPE or _hash(forecast["scope"]) != _hash(_SCOPE):
        raise ValueError("forecast scope flags do not match the fixed profile")
    return forecast


def _validate_target(target: object) -> dict:
    _fields(target, _TARGET_FIELDS, "behavior target")
    if target["schema"] != "sociolab.behavior-target.v1":
        raise ValueError("unsupported behavior target schema")
    _text(target["dataset_id"], "dataset_id")
    _text(target["behavior_variable"], "behavior_variable")
    _text(target["source_revision"], "source_revision")
    _origin(target["origin"], target["source_reference"])
    _integer(target["time_index"], "target time_index")
    behavior = target["behavior"]
    if type(behavior) is not dict or not 2 <= len(behavior) <= 200:
        raise ValueError("target behavior must cover between 2 and 200 actors")
    for actor, value in behavior.items():
        _text(actor, "target actor")
        _integer(value, "target behavior")
    _hash(target)
    return target


def _errors(predictions: list[float], target: np.ndarray) -> dict[str, float]:
    difference = np.asarray(predictions, dtype=np.float64) - target
    with np.errstate(over="ignore", invalid="ignore"):
        result = {"mae": float(np.mean(np.abs(difference))), "rmse": float(np.sqrt(np.mean(difference ** 2)))}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("forecast scoring metrics must be finite")
    return result


def score_behavior_forecast(forecast: dict, target: dict) -> dict:
    """Score an intact private artifact against a separate known target wave.

    The output contains aggregate losses and hashes only; no actor IDs, individual
    predictions, target values, or individual errors are copied into it.
    """
    artifact = _validate_forecast(forecast)
    observed = _validate_target(target)
    for field in ("dataset_id", "origin", "source_reference", "behavior_variable"):
        if observed[field] != artifact["dataset"][field]:
            raise ValueError(f"target {field} does not match the forecast")
    if observed["time_index"] != artifact["specification"]["target_time_index"]:
        raise ValueError("target time does not match the forecast horizon")
    if set(observed["behavior"]) != set(artifact["actors"]):
        raise ValueError("target roster must exactly match the forecast roster")
    scale = artifact["specification"]["behavior"]
    if any(not scale["minimum"] <= value <= scale["maximum"] for value in observed["behavior"].values()):
        raise ValueError("target behavior is outside the predeclared scale")
    actual = np.asarray([observed["behavior"][actor] for actor in artifact["actors"]], dtype=np.float64)
    models = {}
    for name, model in artifact["models"].items():
        estimable = model["status"] == "OK"
        models[name] = {
            "status": model["status"], "reason": model["reason"],
            "n_evaluated": len(actual) if estimable else 0, "clipping_count": model["clipping_count"],
            "raw": _errors(model["raw_predictions"], actual) if estimable else None,
            "clipped": _errors(model["clipped_predictions"], actual) if estimable else None,
        }
    comparisons = {}
    for comparison, baseline in (("network_vs_own", "own_lag_ols"), ("network_vs_persistence", "persistence")):
        network, reference = models["network_lag_ols"], models[baseline]
        estimable = network["status"] == reference["status"] == "OK"
        comparisons[comparison] = {
            "status": "OK" if estimable else "NOT_ESTIMABLE",
            "reason": None if estimable else "required_forecast_not_estimable",
            "n_evaluated": len(actual) if estimable else 0,
            "direction": "network_minus_baseline_negative_favors_network",
            **{variant: {f"{metric}_difference": network[variant][metric] - reference[variant][metric]
                         for metric in ("mae", "rmse")} if estimable else None
               for variant in ("raw", "clipped")},
        }
    return {
        "schema": "sociolab.behavior-forecast-score.v1", "kind": "BEHAVIOR_FORECAST_SCORE", "profile": _PROFILE,
        "dataset_id": artifact["dataset"]["dataset_id"], "behavior_variable": artifact["dataset"]["behavior_variable"],
        "forecast_hash": artifact["content_hash"], "history_prefix_hash": artifact["history"]["content_hash"],
        "specification_hash": artifact["specification_hash"], "target_behavior_hash": _hash(observed),
        "target_source_revision": observed["source_revision"], "target_time_index": observed["time_index"],
        "actor_count": len(actual), "models": models, "comparisons": comparisons,
        "metrics": {"primary": "mae", "secondary": "rmse", "primary_prediction": "clipped",
                    "raw_metrics_reported": True, "rounding": "none", "same_actor_comparison": True,
                    "unit": "declared_behavior_level", "uncertainty_intervals": False},
        "scope": deepcopy(_SCORE_SCOPE), "runtime": _runtime(),
    }


def _load_json(path: str | Path) -> object:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=unique_object)


def load_behavior_forecast_spec(path: str | Path) -> dict:
    """Read a strict, predeclared forecast specification."""
    return _validate_spec(_load_json(path))


def load_behavior_forecast(path: str | Path) -> dict:
    """Read and validate a private forecast artifact and its integrity hash."""
    return _validate_forecast(_load_json(path))


def load_behavior_target(path: str | Path) -> dict:
    """Read a target without fitting or creating any forecast."""
    return _validate_target(_load_json(path))
