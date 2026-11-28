"""Independent, aggregate-only verification of the frozen s50 forecast case.

This script is intended to run only after predictions and scores have been
frozen. It reads the supplied original ZIP at that point, never imports
SocioLab, and recomputes forecasts with SciPy's QR-based GELSY driver rather
than the production NumPy least-squares route. No input data, actor IDs,
per-actor predictions, or target observations are emitted.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
import json
import math
from pathlib import Path, PurePosixPath
import sys
from zipfile import BadZipFile, ZipFile

import numpy as np
from scipy.linalg import lstsq, svdvals


_N = 50
_LOWER = 1
_UPPER = 5
_ATOL = 1e-9
_RTOL = 1e-9
_MEMBERS = ("s50-network1.dat", "s50-network2.dat", "s50-alcohol.dat")
_OFFICIAL_ARCHIVE_SHA256 = "sha256:57dfd0d2a5f924f36cb1ff0c70d2e3a83370e142400af4edc28f4c5c29fea955"
_SOURCE_URL = "https://www.stats.ox.ac.uk/~snijders/siena/s50_data.htm"
_DATASET_ID = "teenage-friends-s50-numerical-example"
_BEHAVIOR_VARIABLE = "alcohol_consumption_ordinal_1_to_5"
_PROFILE = "own-lag-outgoing-gap-ols-v1"
_RESEARCH_QUESTION = (
    "In the s50 numerical teaching example, does adding origin-wave outgoing-neighbor "
    "behavior improve next-wave behavior-code point predictions over own-lag OLS and persistence?"
)


class CheckError(ValueError):
    """Use a fixed nonidentifying error code, never an input-value message."""


def _digest(raw: bytes) -> str:
    return "sha256:" + sha256(raw).hexdigest()


def _canonical_hash(value: object) -> str:
    return _digest(json.dumps(value, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CheckError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise CheckError("NONFINITE_JSON_NUMBER")


def _load_json(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    if not raw or len(raw) > 10_000_000:
        raise CheckError("JSON_INPUT_SIZE")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CheckError("INVALID_JSON") from error
    if type(value) is not dict:
        raise CheckError("JSON_OBJECT_REQUIRED")
    return value, raw


def _parse_integer_matrix(raw: bytes, columns: int, allowed: set[int]) -> list[list[int]]:
    try:
        rows = raw.decode("ascii").splitlines()
    except UnicodeError as error:
        raise CheckError("SOURCE_ENCODING") from error
    if len(rows) != _N:
        raise CheckError("SOURCE_ROW_COUNT")
    result = []
    for row in rows:
        tokens = row.split()
        if len(tokens) != columns or any(not token.isdecimal() for token in tokens):
            raise CheckError("SOURCE_INTEGER_MATRIX")
        values = [int(token) for token in tokens]
        if any(value not in allowed for value in values):
            raise CheckError("SOURCE_VALUE_DOMAIN")
        result.append(values)
    return result


def _read_original_archive(path: Path) -> dict:
    raw = path.read_bytes()
    if not raw or len(raw) > 2_000_000:
        raise CheckError("SOURCE_ARCHIVE_SIZE")
    selected = {}
    try:
        with ZipFile(BytesIO(raw)) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                name = PurePosixPath(entry.filename)
                if name.is_absolute() or ".." in name.parts or "\\" in entry.filename:
                    raise CheckError("SOURCE_MEMBER_PATH")
                if name.name not in _MEMBERS:
                    continue
                if name.name in selected or entry.file_size > 160_000:
                    raise CheckError("SOURCE_MEMBER_DUPLICATE_OR_SIZE")
                selected[name.name] = archive.read(entry)
    except BadZipFile as error:
        raise CheckError("SOURCE_ZIP_INVALID") from error
    if set(selected) != set(_MEMBERS):
        raise CheckError("SOURCE_MEMBERS_MISSING")
    networks = [_parse_integer_matrix(selected[name], _N, {0, 1}) for name in _MEMBERS[:2]]
    for network in networks:
        if any(row[index] != 0 or sum(row) > 12 for index, row in enumerate(network)):
            raise CheckError("SOURCE_NETWORK_CONTRACT")
    behavior = _parse_integer_matrix(selected["s50-alcohol.dat"], 3, set(range(1, 6)))
    return {
        "archive_sha256": _digest(raw),
        "member_sha256": {name: _digest(content) for name, content in selected.items()},
        "actors": [f"p{index:03d}" for index in range(1, _N + 1)],
        "networks": networks,
        "behavior": behavior,
    }


def _features(network: list[list[int]], behavior: list[int]) -> dict:
    """Use directed adjacency rows directly, without a graph-library adapter."""
    gap = []
    neighbor_mean = []
    outdegree = []
    for ego, row in enumerate(network):
        alters = [alter for alter, present in enumerate(row) if present == 1]
        outdegree.append(len(alters))
        mean = sum(behavior[alter] for alter in alters) / len(alters) if alters else None
        neighbor_mean.append(mean)
        gap.append(0.0 if mean is None else mean - behavior[ego])
    own = np.array([[1.0, value] for value in behavior], dtype=np.float64)
    network_design = np.column_stack((own, np.asarray(gap, dtype=np.float64)))
    return {
        "own_design": own, "network_design": network_design,
        "neighbor_gap": gap, "neighbor_mean": neighbor_mean, "outdegree": outdegree,
    }


def _fit_qr(design: np.ndarray, target: np.ndarray, forecast: np.ndarray) -> dict:
    if design.shape[0] <= design.shape[1] or not np.isfinite(design).all():
        raise CheckError("INDEPENDENT_TRAINING_DESIGN_INVALID")
    # Use an explicit cutoff corresponding to NumPy's declared rcond=None;
    # GELSY's rank-revealing QR remains an independent numerical route.
    cutoff = np.finfo(np.float64).eps * max(design.shape)
    coefficients, _, rank, _ = lstsq(design, target, cond=cutoff,
                                     lapack_driver="gelsy", check_finite=True)
    singular = svdvals(design, check_finite=True)
    raw = forecast @ coefficients
    if not np.isfinite(coefficients).all() or not np.isfinite(raw).all():
        raise CheckError("INDEPENDENT_SOLUTION_NONFINITE")
    condition = float(singular[0] / singular[-1]) if singular[-1] > 0 else None
    if condition is not None and not math.isfinite(condition):
        condition = None
    return {
        "status": "OK" if rank == design.shape[1] else "NOT_ESTIMABLE",
        "reason": None if rank == design.shape[1] else "rank_deficient_training_design",
        "coefficients": coefficients, "rank": int(rank),
        "singular_values": singular,
        "condition_number": condition,
        "residual_sum_squares": float(np.sum((target - design @ coefficients) ** 2)),
        "rcond_effective": float(cutoff), "raw": raw if rank == design.shape[1] else None,
        "clipped": np.clip(raw, _LOWER, _UPPER) if rank == design.shape[1] else None,
    }


def _independent_case(source: dict) -> dict:
    columns = [[row[index] for row in source["behavior"]] for index in range(3)]
    train = _features(source["networks"][0], columns[0])
    forecast = _features(source["networks"][1], columns[1])
    target_train = np.asarray(columns[1], dtype=np.float64)
    persistence = np.asarray(columns[1], dtype=np.float64)
    return {
        "train": train, "forecast": forecast,
        "target": np.asarray(columns[2], dtype=np.float64),
        "columns": columns,
        "models": {
            "persistence": {"status": "OK", "reason": None,
                            "raw": persistence, "clipped": persistence.copy()},
            "own_lag_ols": _fit_qr(train["own_design"], target_train, forecast["own_design"]),
            "network_lag_ols": _fit_qr(train["network_design"], target_train,
                                      forecast["network_design"]),
        },
    }


def _source_objects(source: dict) -> tuple[dict, dict, str]:
    actors = source["actors"]
    waves = []
    for index, network in enumerate(source["networks"]):
        values = [row[index] for row in source["behavior"]]
        edges = [[actors[ego], actors[alter]] for ego, row in enumerate(network)
                 for alter, present in enumerate(row) if present]
        waves.append({
            "time_index": index,
            "source_revision": _canonical_hash({"network": network, "behavior": values}),
            "network_complete": True, "edges": edges,
            "behavior": dict(zip(actors, values, strict=True)),
        })
    history = {
        "schema": "sociolab.longitudinal.v1", "dataset_id": _DATASET_ID,
        "origin": "external_observation", "source_reference": _SOURCE_URL,
        "actors": actors, "relation": "directed_observed_social_tie",
        "behavior_variable": _BEHAVIOR_VARIABLE, "waves": waves,
    }
    target_values = [row[2] for row in source["behavior"]]
    target = {
        "schema": "sociolab.behavior-target.v1", "dataset_id": _DATASET_ID,
        "origin": "external_observation", "source_reference": _SOURCE_URL,
        "behavior_variable": _BEHAVIOR_VARIABLE, "time_index": 2,
        "source_revision": _canonical_hash(target_values),
        "behavior": dict(zip(actors, target_values, strict=True)),
    }
    prefix_hash = _canonical_hash({"networks": source["networks"],
                                   "behavior": [row[:2] for row in source["behavior"]]})
    return history, target, prefix_hash


def _metrics(prediction: np.ndarray, target: np.ndarray) -> dict:
    errors = prediction - target
    return {"mae": float(np.mean(np.abs(errors))),
            "rmse": float(np.sqrt(np.mean(errors ** 2)))}


def _expected_specification() -> dict:
    return {
        "schema": "sociolab.behavior-forecast.v1", "profile": _PROFILE,
        "behavior": {"variable": _BEHAVIOR_VARIABLE, "minimum": _LOWER,
                     "maximum": _UPPER, "measurement_reference": _SOURCE_URL},
        "target_time_index": 2, "research_question": _RESEARCH_QUESTION,
    }


def _expected_scope() -> dict:
    return {
        "analysis": "retrospective_temporal_holdout",
        "forecast_uses_history_prefix_only": True,
        "target_observations_consumed_at_creation": False,
        "target_network_consumed": False,
        "neighbor_direction": "outgoing_successors_in_each_known_wave",
        "no_outgoing_neighbor_gap": 0.0,
        "no_outgoing_neighbor_convention": "structural_zero_gap_not_missing_value_imputation",
        "actor_dropping": False, "behavior_imputation": False,
        "preprocessing_fitted": False, "historical_receipt_availability": "unknown",
        "historical_as_of_availability_verified": False,
        "population_boundary_qualified": False,
        "fixed_roster_contract": "same_supplied_actors_in_every_history_wave_and_target",
        "wave_time_unit": "wave_index_not_calendar_duration",
        "ordinal_values_treated_as_numeric": True,
        "scale_endpoints_required_in_history": False,
        "condition_number_threshold": None,
        "null_condition_number": "zero_smallest_singular_value_or_nonfinite_ratio",
        "coefficient_inference": False, "probabilistic_forecast": False,
        "calibration_status": "NOT_ESTIMATED", "prediction_intervals": None,
        "causal_effect_identified": False, "empirical_forecast_validated": False,
        "content_hash_authenticates_author": False,
        "content_hash_proves_prospective_timestamp": False,
        "prediction_artifact_contains_private_actor_records": True,
    }


class Comparisons:
    def __init__(self):
        self.checks = []

    def exact(self, name: str, actual: object, expected: object) -> None:
        self.checks.append({"check": name, "passed": actual == expected,
                            "comparison_count": 1, "max_absolute_error": None})

    def numeric(self, name: str, actual: object, expected: object) -> None:
        try:
            left = np.asarray(actual)
            right = np.asarray(expected)
            if (left.dtype.kind not in "iuf" or right.dtype.kind not in "iuf"
                    or left.shape != right.shape):
                raise ValueError
            left = left.astype(np.float64)
            right = right.astype(np.float64)
            if not np.isfinite(left).all() or not np.isfinite(right).all():
                raise ValueError
        except (TypeError, ValueError):
            self.checks.append({"check": name, "passed": False,
                                "comparison_count": 0, "max_absolute_error": None})
            return
        error = float(np.max(np.abs(left - right))) if left.size else 0.0
        self.checks.append({"check": name,
                            "passed": bool(np.allclose(left, right, rtol=_RTOL, atol=_ATOL)),
                            "comparison_count": int(left.size), "max_absolute_error": error})

    def report(self) -> dict:
        errors = [check["max_absolute_error"] for check in self.checks
                  if check["max_absolute_error"] is not None]
        return {
            "status": "PASSED" if all(check["passed"] for check in self.checks) else "FAILED",
            "check_count": len(self.checks),
            "comparison_count": sum(check["comparison_count"] for check in self.checks),
            "max_absolute_error": max(errors, default=0.0),
            "tolerance": {"rtol": _RTOL, "atol": _ATOL},
            "checks": self.checks,
        }


def _compare_identity(check: Comparisons, artifact: dict, score: dict,
                      source: dict, case: dict, history: dict, target: dict) -> None:
    specification = _expected_specification()
    dataset = {key: history[key] for key in (
        "dataset_id", "origin", "source_reference", "relation", "behavior_variable",
    )}
    history_hash = _canonical_hash(history)
    spec_hash = _canonical_hash(specification)
    check.exact("original_archive_fingerprint", source["archive_sha256"], _OFFICIAL_ARCHIVE_SHA256)
    check.exact("forecast_schema", artifact["schema"], "sociolab.behavior-forecast-artifact.v1")
    check.exact("forecast_kind", artifact["kind"], "BEHAVIOR_FORECAST")
    check.exact("forecast_profile", artifact["profile"], _PROFILE)
    check.exact("forecast_dataset", artifact["dataset"], dataset)
    check.exact("fixed_source_row_order", artifact["actors"], source["actors"])
    check.exact("forecast_specification", artifact["specification"], specification)
    check.exact("forecast_specification_hash", artifact["specification_hash"], spec_hash)
    check.exact("forecast_history_identity", artifact["history"], {
        "content_hash": history_hash, "wave_time_indices": [0, 1],
        "wave_source_revisions": [wave["source_revision"] for wave in history["waves"]],
        "origin_time_index": 1, "wave_gap": 1, "transition_count": 1,
    })
    payload = {key: value for key, value in artifact.items() if key != "content_hash"}
    check.exact("forecast_content_integrity", artifact["content_hash"], _canonical_hash(payload))
    check.exact("training_row_count", artifact["training"]["row_count"], _N)
    train_hashes = {
        "own_lag_ols": _canonical_hash(case["train"]["own_design"].tolist()),
        "network_lag_ols": _canonical_hash(case["train"]["network_design"].tolist()),
    }
    forecast_hashes = {
        "own_lag_ols": _canonical_hash(case["forecast"]["own_design"].tolist()),
        "network_lag_ols": _canonical_hash(case["forecast"]["network_design"].tolist()),
    }
    check.exact("consumed_training_feature_hashes", artifact["training"]["feature_hashes"], train_hashes)
    check.exact("consumed_training_label_hash", artifact["training"]["label_hash"],
                _canonical_hash(np.asarray(case["columns"][1], dtype=np.float64).tolist()))
    check.exact("consumed_forecast_feature_hashes", artifact["forecast_input_hashes"], forecast_hashes)
    check.exact("score_schema", score["schema"], "sociolab.behavior-forecast-score.v1")
    check.exact("score_kind", score["kind"], "BEHAVIOR_FORECAST_SCORE")
    for field, expected in (
        ("forecast_hash", artifact["content_hash"]), ("history_prefix_hash", history_hash),
        ("specification_hash", spec_hash), ("target_behavior_hash", _canonical_hash(target)),
        ("target_source_revision", target["source_revision"]),
        ("target_time_index", 2), ("actor_count", _N),
    ):
        check.exact("score_" + field, score[field], expected)
    check.exact("score_profile", score["profile"], _PROFILE)
    check.exact("score_dataset", score["dataset_id"], _DATASET_ID)
    check.exact("score_behavior_variable", score["behavior_variable"], _BEHAVIOR_VARIABLE)
    check.exact("forecast_scope", artifact["scope"], _expected_scope())
    check.exact("forecast_scope_types", _canonical_hash(artifact["scope"]), _canonical_hash(_expected_scope()))
    expected_score_scope = {**_expected_scope(), "score_output": "aggregate_only",
                            "target_used_only_for_scoring": True}
    check.exact("score_scope", score["scope"], expected_score_scope)
    check.exact("score_scope_types", _canonical_hash(score["scope"]), _canonical_hash(expected_score_scope))
    check.exact("score_metric_policy", score["metrics"], {
        "primary": "mae", "secondary": "rmse", "primary_prediction": "clipped",
        "raw_metrics_reported": True, "rounding": "none", "same_actor_comparison": True,
        "unit": "declared_behavior_level", "uncertainty_intervals": False,
    })


def _compare_models(check: Comparisons, artifact: dict, case: dict) -> None:
    features = {
        "persistence": ["own_lag"],
        "own_lag_ols": ["intercept", "own_lag"],
        "network_lag_ols": ["intercept", "own_lag", "outgoing_mean_minus_own"],
    }
    check.exact("forecast_model_set", sorted(artifact["models"]), sorted(case["models"]))
    for name, expected in case["models"].items():
        actual = artifact["models"][name]
        check.exact(name + "_status", actual["status"], expected["status"])
        check.exact(name + "_reason", actual["reason"], expected["reason"])
        check.exact(name + "_feature_order", actual["feature_names"], features[name])
        check.exact(name + "_training_rows", actual["training_row_count"], 0 if name == "persistence" else _N)
        check.exact(name + "_declared_algorithm", actual["algorithm"],
                    "last_observed_behavior" if name == "persistence" else "numpy.linalg.lstsq")
        if name == "persistence":
            for field in ("coefficients", "rank", "singular_values", "residual_sum_squares", "condition_number"):
                check.exact(name + "_" + field + "_absent", actual[field], None)
        else:
            check.exact(name + "_rank", actual["rank"], expected["rank"])
            for field in ("coefficients", "singular_values"):
                check.numeric(name + "_" + field, actual[field], expected[field])
            if expected["condition_number"] is None:
                check.exact(name + "_condition_number", actual["condition_number"], None)
            else:
                check.numeric(name + "_condition_number", actual["condition_number"], expected["condition_number"])
            residuals = [expected["residual_sum_squares"]] if expected["status"] == "OK" else []
            check.numeric(name + "_training_residual_sum_squares", actual["residual_sum_squares"], residuals)
        estimable = expected["status"] == "OK"
        for field, key in (("raw_predictions", "raw"), ("clipped_predictions", "clipped")):
            if estimable:
                check.numeric(name + "_" + field, actual[field], expected[key])
            else:
                check.exact(name + "_" + field + "_absent", actual[field], None)
        count = int(np.count_nonzero(expected["raw"] != expected["clipped"])) if estimable else None
        check.exact(name + "_clipping_count", actual["clipping_count"], count)


def _compare_metric_results(check: Comparisons, score: dict, case: dict) -> dict:
    computed = {}
    check.exact("score_model_set", sorted(score["models"]), sorted(case["models"]))
    for name, model in case["models"].items():
        recorded = score["models"][name]
        check.exact(name + "_score_status", recorded["status"], model["status"])
        check.exact(name + "_score_reason", recorded["reason"], model["reason"])
        eligible = model["status"] == "OK"
        check.exact(name + "_score_denominator", recorded["n_evaluated"], _N if eligible else 0)
        clipped_count = int(np.count_nonzero(model["raw"] != model["clipped"])) if eligible else None
        check.exact(name + "_score_clipping_count", recorded["clipping_count"], clipped_count)
        computed[name] = {"status": model["status"], "n_evaluated": _N if eligible else 0,
                          "clipping_count": clipped_count}
        for prediction_kind in ("raw", "clipped"):
            if not eligible:
                check.exact(name + "_" + prediction_kind + "_metrics_absent", recorded[prediction_kind], None)
                computed[name][prediction_kind] = None
                continue
            metrics = _metrics(model[prediction_kind], case["target"])
            computed[name][prediction_kind] = metrics
            check.exact(name + "_" + prediction_kind + "_metric_set",
                        sorted(recorded[prediction_kind]), sorted(metrics))
            for metric, value in metrics.items():
                check.numeric(name + "_" + prediction_kind + "_" + metric,
                              recorded[prediction_kind][metric], value)
    comparisons = {"network_vs_own": "own_lag_ols", "network_vs_persistence": "persistence"}
    check.exact("score_comparison_set", sorted(score["comparisons"]), sorted(comparisons))
    for name, baseline in comparisons.items():
        recorded = score["comparisons"][name]
        eligible = all(case["models"][model]["status"] == "OK"
                       for model in ("network_lag_ols", baseline))
        check.exact(name + "_status", recorded["status"], "OK" if eligible else "NOT_ESTIMABLE")
        check.exact(name + "_reason", recorded["reason"], None if eligible else "required_forecast_not_estimable")
        check.exact(name + "_direction", recorded["direction"],
                    "network_minus_baseline_negative_favors_network")
        check.exact(name + "_denominator", recorded["n_evaluated"], _N if eligible else 0)
        for prediction_kind in ("raw", "clipped"):
            if not eligible:
                check.exact(name + "_" + prediction_kind + "_metrics_absent", recorded[prediction_kind], None)
                continue
            expected = {
                metric + "_difference": computed["network_lag_ols"][prediction_kind][metric]
                                        - computed[baseline][prediction_kind][metric]
                for metric in ("mae", "rmse")
            }
            check.exact(name + "_" + prediction_kind + "_metric_set",
                        sorted(recorded[prediction_kind]), sorted(expected))
            for metric, value in expected.items():
                check.numeric(name + "_" + prediction_kind + "_" + metric,
                              recorded[prediction_kind][metric], value)
    return computed


def verify(archive_path: Path, forecast_path: Path, score_path: Path) -> dict:
    """Read actual targets only when explicitly invoked after the case is frozen."""
    artifact, forecast_bytes = _load_json(forecast_path)
    score, score_bytes = _load_json(score_path)
    source = _read_original_archive(archive_path)
    case = _independent_case(source)
    history, target, prefix_hash = _source_objects(source)
    check = Comparisons()
    _compare_identity(check, artifact, score, source, case, history, target)
    _compare_models(check, artifact, case)
    independent_metrics = _compare_metric_results(check, score, case)
    return {
        "kind": "INDEPENDENT_BEHAVIOR_FORECAST_CHECK",
        **check.report(),
        "scope": "frozen retrospective s50 forecast arithmetic and input identity only",
        "source_archive_sha256": source["archive_sha256"],
        "source_members_read_sha256": source["member_sha256"],
        "source_prefix_values_sha256": prefix_hash,
        "history_prefix_hash": _canonical_hash(history),
        "target_behavior_hash": _canonical_hash(target),
        "forecast_file_sha256": _digest(forecast_bytes),
        "score_file_sha256": _digest(score_bytes),
        "checker_source_sha256": _digest(Path(__file__).read_bytes()),
        "actor_count": _N,
        "source_actor_order_hash": _canonical_hash(source["actors"]),
        "feature_summary": {
            "training_rows": _N, "forecast_rows": _N,
            "own_design_columns": 2, "network_design_columns": 3,
            "past_wave_edge_counts": [sum(map(sum, network)) for network in source["networks"]],
            "past_wave_zero_outdegree_counts": [values["outdegree"].count(0)
                                                for values in (case["train"], case["forecast"])],
            "outgoing_neighbors_from_original_adjacency_rows": True,
            "isolate_network_gap": 0.0,
        },
        "independent_model_metrics": independent_metrics,
        "solver": {"function": "scipy.linalg.lstsq", "lapack_driver": "gelsy",
                   "rank_cutoff": "float64_epsilon_times_max_design_dimension",
                   "diagnostic_singular_values": "scipy.linalg.svdvals",
                   "production_model_function_imported": False,
                   "production_solver_called": False},
        "runtime": {"python": sys.version.split()[0], "numpy": version("numpy"), "scipy": version("scipy")},
        "output_contains_actor_identifiers": False,
        "output_contains_row_predictions_or_targets": False,
        "future_network_read": False,
        "probability_calibration_established": False,
        "prospective_validation": False,
        "population_generalization_validated": False,
        "causal_effect_identified": False,
        "historical_receipt_availability_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--forecast", required=True, type=Path,
                        help="previously frozen private forecast artifact")
    parser.add_argument("--score", required=True, type=Path,
                        help="previously produced aggregate score")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("the aggregate output already exists; choose a fresh output path")
    try:
        report = verify(args.archive, args.forecast, args.score)
        exit_code = 0 if report["status"] == "PASSED" else 1
    except CheckError as error:
        report = {"kind": "INDEPENDENT_BEHAVIOR_FORECAST_CHECK", "status": "ERROR",
                  "error_code": str(error), "input_values_emitted": False}
        exit_code = 2
    except Exception as error:
        # Even malformed private artifacts cannot cause their values or keys
        # to appear in public exception messages or stack traces.
        report = {"kind": "INDEPENDENT_BEHAVIOR_FORECAST_CHECK", "status": "ERROR",
                  "error_code": "INPUT_OR_SOLVER_CONTRACT", "error_type": type(error).__name__,
                  "input_values_emitted": False}
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    print(encoded, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
