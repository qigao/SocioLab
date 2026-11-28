"""Frozen upstream binary classifiers for released-archive recurrence.

This bounded comparison does not estimate a relational-event likelihood or
create observation/eligibility declarations. NetworkX owns the graph features;
scikit-learn owns scaling, fitting and probability prediction. Target labels
mean rows in this archive, never verified absence of real communication.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import platform
import warnings

from .archive_features import (
    ArchiveFeatureReplay, DYADIC_FEATURE_NAMES, NETWORK_FEATURE_NAMES,
    _canonical_rows, make_archive_features,
)
from .archive_recurrence import _archive_prediction, _source_audit, load_email_eu_dept3_archive
from .repeat_evaluation import _model_summary, _risk_change
from .repeat_interaction import _MODELS, _probability_bin_models, _probability_bins, _probability_scores
from .snapshots import content_hash


PROTOCOL_FREEZE_COMMIT = "938c8e417def93f6e331f04ce52b6deb42f100d2"
REFERENCE_PROTOCOL_HASH = "sha256:67bcbeac8192d0b6f4e928e2b8d5790c6b9c8ac363a35d446e92fc1d21828661"
REFERENCE_GZIP_SHA256 = "8e8dcdb9049a671f2afcb4bc91ff8ad77423a40612ce8318ef0825aa8b44b53d"
REFERENCE_PAYLOAD_SHA256 = "2488f3de81722acd1a3ed611c3f0f348dc9e9f3e030cb821edb5fd928c53b45f"
MODEL_NAMES = _MODELS + ("training_prevalence", "dyadic_logistic", "network_logistic")
_FITTED = {"dyadic_logistic": "dyadic", "network_logistic": "network"}


def _provider():
    try:
        if version("scikit-learn") != "1.9.1":
            raise ValueError("network comparison requires the reviewed scikit-learn==1.9.1 provider")
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from threadpoolctl import threadpool_limits
    except (ImportError, PackageNotFoundError) as error:
        raise ValueError("network comparison requires the optional network-prediction dependency") from error
    return np, LogisticRegression, StandardScaler, threadpool_limits


def _runtime() -> dict:
    return {"python": platform.python_version(), "packages": {
        name: version(name) for name in (
            "scikit-learn", "numpy", "scipy", "networkx", "joblib", "threadpoolctl", "narwhals",
        )}}


def _prepare_training(history_rows: tuple, measurement: dict) -> tuple[list, dict]:
    """Consume only the rows available before the single declared fit cutoff."""
    history_rows = _canonical_rows(history_rows)
    cutoff, horizon, recent = (measurement[key] for key in ("fit_cutoff", "horizon", "recent_width"))
    if any(row[3] >= cutoff for row in history_rows):
        raise ValueError("training receives rows strictly before the fit cutoff only")
    examples, folds = [], []
    previous_end = None
    for origin in measurement["training_origins"]:
        if origin + horizon > cutoff or (previous_end is not None and origin < previous_end):
            raise ValueError("training targets must not overlap and must close by the fit cutoff")
        previous_end = origin + horizon
        past = tuple(row for row in history_rows if row[3] < origin)
        features = make_archive_features(past, origin=origin, horizon=horizon, recent_width=recent)
        target = tuple(row for row in history_rows if origin <= row[3] < origin + horizon)
        positive = {row[1:3] for row in target if row[1] != row[2]}
        labels = []
        for row in features["rows"]:
            label = int((row["source"], row["target"]) in positive)
            labels.append([row["source"], row["target"], label])
            examples.append({"origin_at_seconds": origin, **deepcopy(row), "label": label})
        risk = {(row["source"], row["target"]) for row in features["rows"]}
        folds.append({
            "origin_at_seconds": origin, "target_end_seconds": origin + horizon,
            "history_rows_hash": features["history_rows_hash"], "feature_hash": features["content_hash"],
            "target_rows_hash": content_hash(target), "labels_hash": content_hash(labels),
            "risk_pairs": len(labels), "archive_positive_pairs": sum(row[2] for row in labels),
            "target_row_count": len(target), "target_positive_pairs_outside_risk": len(positive - risk),
        })
    n, positives = len(examples), sum(row["label"] for row in examples)
    summary = {
        "fit_cutoff_seconds": cutoff, "history_rows_hash": content_hash(history_rows),
        "training_examples_hash": content_hash(examples),
        "pair_origin_count": n, "positive_count": positives, "negative_count": n - positives,
        "prevalence": positives / n if n else None, "folds": folds,
        "validation_or_test_labels_used": False,
    }
    summary["content_hash"] = content_hash(summary)
    return examples, summary


def _parameter_state(scaler, estimator) -> dict:
    return {
        "scaler": {"mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
                   "variance": scaler.var_.tolist(), "n_samples_seen": int(scaler.n_samples_seen_),
                   "n_features_in": int(scaler.n_features_in_), "parameters": scaler.get_params(deep=False)},
        "estimator": {"classes": estimator.classes_.tolist(), "coefficients": estimator.coef_.tolist(),
                      "intercept": estimator.intercept_.tolist(), "n_iter": estimator.n_iter_.tolist(),
                      "n_features_in": int(estimator.n_features_in_),
                      "parameters": estimator.get_params(deep=False)},
    }


@dataclass
class _FittedModel:
    report: dict
    scaler: object = None
    estimator: object = None


def _fit_one(examples: list, training: dict, protocol: dict, model_name: str) -> _FittedModel:
    """Adapt an upstream estimator; preserve planned failures without retries."""
    block = _FITTED[model_name]
    names = DYADIC_FEATURE_NAMES if block == "dyadic" else NETWORK_FEATURE_NAMES
    matrix = [row[block + "_features"] for row in examples]
    labels = [row["label"] for row in examples]
    record = {
        "schema": "sociolab.archive-recurrence-fitted-model.v1", "model": model_name,
        "feature_names": list(names), "training_hash": training["content_hash"],
        "training_feature_matrix_hash": content_hash(matrix), "training_labels_hash": content_hash(labels),
        "protocol_hash": content_hash(protocol), "fit_cutoff_seconds": training["fit_cutoff_seconds"],
        "provider": {"name": "scikit-learn", "version": "1.9.1"},
        "declared_parameters": deepcopy(protocol["estimation"]["parameters"]),
        "training_n": len(labels), "training_positive_count": sum(labels),
        "status": "NOT_ESTIMABLE", "reason": None, "warnings": [],
        "parameter_state": None, "parameter_hash": None,
    }
    scaler = estimator = None
    if not examples:
        record["reason"] = "empty_training_risk_set"
    elif set(labels) != {0, 1}:
        record["reason"] = "training_requires_both_binary_classes"
    else:
        np, LogisticRegression, StandardScaler, threadpool_limits = _provider()
        values = np.asarray(matrix, dtype=np.float64)
        if values.shape != (len(labels), len(names)) or not np.isfinite(values).all():
            raise ValueError("training features must be a finite complete matrix of the declared shape")
        scaler = StandardScaler(**protocol["estimation"]["scaler_parameters"])
        estimator = LogisticRegression(**protocol["estimation"]["parameters"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                with threadpool_limits(limits=protocol["estimation"]["thread_limit"]):
                    standardized = scaler.fit_transform(values)
                    if not np.isfinite(standardized).all():
                        raise ValueError("upstream scaler produced nonfinite training features")
                    estimator.fit(standardized, np.asarray(labels, dtype=np.int64))
                state = _parameter_state(scaler, estimator)
                coefficients = state["estimator"]["coefficients"]
                if (state["estimator"]["classes"] != [0, 1]
                        or np.asarray(coefficients).shape != (1, len(names))
                        or not np.isfinite(estimator.coef_).all()
                        or not np.isfinite(estimator.intercept_).all()
                        or not np.isfinite(scaler.scale_).all() or not (scaler.scale_ > 0).all()):
                    raise ValueError("upstream fitted parameters do not satisfy the declared binary profile")
                record.update(status="FITTED", parameter_state=state, parameter_hash=content_hash(state))
            except (ValueError, ArithmeticError, RuntimeError) as error:
                record.update(status="FAILED", reason=f"{type(error).__name__}: {error}")
        record["warnings"] = [{"category": item.category.__name__, "message": str(item.message)} for item in caught]
        if record["warnings"]:
            record.update(status="FAILED", reason="upstream_fit_emitted_warning_no_retry")
    if record["status"] != "FITTED":
        scaler = estimator = None
    record["content_hash"] = content_hash(record)
    return _FittedModel(record, scaler, estimator)


def _predict_one(fitted: _FittedModel, features: dict) -> list[float] | None:
    report = fitted.report
    if report["content_hash"] != content_hash({k: v for k, v in report.items() if k != "content_hash"}):
        raise ValueError("fitted model record changed after fitting")
    if features["origin_at_seconds"] < report["fit_cutoff_seconds"]:
        raise ValueError("fitted model cannot predict before its training-label cutoff")
    if report["status"] != "FITTED":
        return None
    block = _FITTED[report["model"]]
    if features["feature_names"][block] != report["feature_names"]:
        raise ValueError("prediction feature order does not match the fitted model")
    before = _parameter_state(fitted.scaler, fitted.estimator)
    if content_hash(before) != report["parameter_hash"]:
        raise ValueError("upstream model or scaler changed after fitting")
    if not features["rows"]:
        return []
    np, _, _, threadpool_limits = _provider()
    values = np.asarray([row[block + "_features"] for row in features["rows"]], dtype=np.float64)
    if values.shape != (len(features["rows"]), len(report["feature_names"])) or not np.isfinite(values).all():
        raise ValueError("prediction features must be a finite matrix of the fitted shape")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with threadpool_limits(limits=1):
            probabilities = fitted.estimator.predict_proba(fitted.scaler.transform(values))
    if caught or probabilities.shape != (len(values), 2) or not np.isfinite(probabilities).all():
        raise ValueError("upstream probability prediction failed its shape/finite/warning contract")
    if not ((probabilities >= 0) & (probabilities <= 1)).all():
        raise ValueError("upstream probabilities are outside [0,1]")
    if content_hash(_parameter_state(fitted.scaler, fitted.estimator)) != report["parameter_hash"]:
        raise ValueError("upstream model changed during probability prediction")
    return probabilities[:, 1].tolist()  # classes [0,1] are bound in parameter_hash.


def _forecast(history_rows: tuple, features: dict, fitted: dict, training: dict, protocol: dict) -> dict:
    if features["origin_at_seconds"] < training["fit_cutoff_seconds"]:
        raise ValueError("archive forecast cannot precede the training-label cutoff")
    measurement = protocol["measurement"]
    baseline = _archive_prediction(history_rows, origin=features["origin_at_seconds"],
                                   horizon=measurement["horizon"], recent_width=measurement["recent_width"])
    if baseline["content_hash"] != features["baseline_forecast_hash"]:
        raise ValueError("baseline and network features do not share the same historical records")
    probabilities = {name: _predict_one(model, features) for name, model in fitted.items()}
    rows = deepcopy(baseline["predictions"])
    for index, row in enumerate(rows):
        if training["prevalence"] is not None:
            row["probabilities"]["training_prevalence"] = training["prevalence"]
        for name, values in probabilities.items():
            if values is not None:
                row["probabilities"][name] = values[index]
    result = {
        "schema": "sociolab.archive-network-prediction.v1",
        "origin_at_seconds": features["origin_at_seconds"],
        "target_end_seconds": features["origin_at_seconds"] + measurement["horizon"],
        "baseline_forecast_hash": baseline["content_hash"], "feature_hash": features["content_hash"],
        "training_hash": training["content_hash"],
        "fitted_model_hashes": {name: model.report["content_hash"] for name, model in fitted.items()},
        "available_models": [name for name in MODEL_NAMES if name in _MODELS
                             or (name == "training_prevalence" and training["prevalence"] is not None)
                             or (name in probabilities and probabilities[name] is not None)],
        "predictions": rows, "contains_private_actor_records": True,
    }
    result["content_hash"] = content_hash(result)
    return result


def _score_fold(forecast: dict, target_rows: tuple, edges: list) -> tuple[dict, dict, set]:
    origin, end = forecast["origin_at_seconds"], forecast["target_end_seconds"]
    if any(not origin <= row[3] < end for row in target_rows):
        raise ValueError("network comparison target rows must be inside the frozen window")
    positive = {row[1:3] for row in target_rows if row[1] != row[2]}
    risk = {(row["source"], row["target"]) for row in forecast["predictions"]}
    scored = [(row, int((row["source"], row["target"]) in positive)) for row in forecast["predictions"]]
    scores, bins = {}, {}
    for name in MODEL_NAMES:
        usable = scored if name in forecast["available_models"] else []
        scores.update(_probability_scores(usable, model_names=(name,)))
        bins.update(_probability_bin_models(usable, edges, model_names=(name,)))
        if name not in forecast["available_models"]:
            scores[name]["status"] = "MODEL_NOT_AVAILABLE"
    report = {
        "origin_at_seconds": origin, "target_end_seconds": end,
        "forecast_hash": forecast["content_hash"], "feature_hash": forecast["feature_hash"],
        "fitted_model_hashes": deepcopy(forecast["fitted_model_hashes"]),
        "available_models": list(forecast["available_models"]),
        "risk_pairs": len(risk), "archive_positive_pairs": len(risk & positive),
        "archive_negative_pairs": len(risk - positive), "target_row_count": len(target_rows),
        "target_positive_pairs_outside_risk": len(positive - risk), "target_rows_hash": content_hash(target_rows),
        "always_zero_brier": len(risk & positive) / len(risk) if risk else None,
        "models": scores, "probability_diagnostics": bins,
    }
    return report, {"score": {"models": scores}, "models": bins}, risk


def _split_summary(reports: list, diagnostics: list, edges: list) -> dict:
    n, positives = sum(r["risk_pairs"] for r in reports), sum(r["archive_positive_pairs"] for r in reports)
    models = {name: _model_summary(diagnostics, name, len(reports), edges) for name in MODEL_NAMES}
    for name, summary in models.items():
        summary["planned_origins"] = len(reports)
        summary["scored_origins"] = sum(r["models"][name]["n"] > 0 for r in reports)
        summary["unscored_pair_origins"] = n - summary["n"]
        summary["full_planned_risk_scored"] = n > 0 and summary["n"] == n
    # A paired difference is reported only when both models cover the full plan.
    network, dyadic = models["network_logistic"], models["dyadic_logistic"]
    comparable = n > 0 and network["n"] == dyadic["n"] == n
    zero = positives / n if n else None
    return {
        "planned_origins": len(reports), "risk_pair_origin_count": n,
        "archive_positive_pair_origin_count": positives, "archive_negative_pair_origin_count": n - positives,
        "models": models, "always_zero_brier": zero,
        "network_minus_dyadic_pooled_brier": network["pooled_brier"] - dyadic["pooled_brier"] if comparable else None,
        "network_dyadic_common_pair_origins": n if comparable else 0,
        "model_brier_minus_always_zero": {
            name: item["pooled_brier"] - zero if n and item["n"] == n else None for name, item in models.items()},
    }


def _comparison_report(rows: tuple, protocol: dict) -> dict:
    rows = _canonical_rows(rows)
    measurement = protocol["measurement"]
    horizon, recent, cutoff = (measurement[key] for key in ("horizon", "recent_width", "fit_cutoff"))
    training_rows = tuple(row for row in rows if row[3] < cutoff)
    examples, training = _prepare_training(training_rows, measurement)
    fitted = {name: _fit_one(examples, training, protocol, name) for name in _FITTED}
    # No validation/test labels have been assembled or scored before this point.
    edges = _probability_bins(protocol["analysis"]["probability_bins"])
    replay = ArchiveFeatureReplay(horizon=horizon, recent_width=recent)
    reports, split_diagnostics, previous_risk = [], {"validation": [], "test": []}, None
    previous_end = cutoff
    for split in ("validation", "test"):
        for origin in measurement[split + "_origins"]:
            if origin < previous_end:
                raise ValueError("validation/test origins must follow fitting with disjoint target windows")
            previous_end = origin + horizon
            past = tuple(row for row in rows if row[3] < origin)
            features = make_archive_features(past, origin=origin, horizon=horizon, recent_width=recent)
            interval = tuple(row for row in rows if replay.origin <= row[3] < origin)
            replayed = replay.advance(origin, interval)
            if features != replayed:
                raise ValueError("batch and source-time replay feature artifacts differ")
            forecast = _forecast(past, features, fitted, training, protocol)
            target = tuple(row for row in rows if origin <= row[3] < origin + horizon)
            report, diagnostic, risk = _score_fold(forecast, target, edges)
            report.update(split=split, history_rows_hash=features["history_rows_hash"],
                          history_row_count=features["history_row_count"],
                          batch_replay_feature_hash_equal=True, risk_change=_risk_change(risk, previous_risk))
            reports.append(report)
            split_diagnostics[split].append(diagnostic)
            previous_risk = risk
    result = {
        "schema": "sociolab.archive-network-comparison.v1", "study_id": protocol["study_id"],
        "profile": "dept2-released-archive-network-recurrence-v1", "protocol_hash": content_hash(protocol),
        "protocol_freeze_commit": PROTOCOL_FREEZE_COMMIT,
        "measurement": deepcopy(measurement), "training": training,
        "fitted_models": {name: model.report for name, model in fitted.items()},
        "folds": reports, "probability_bins": edges,
        "splits": {split: _split_summary([r for r in reports if r["split"] == split], split_diagnostics[split], edges)
                   for split in ("validation", "test")},
        "scope": {**deepcopy(protocol["scope"]), "contains_private_actor_records": False,
                  "all_planned_origins_retained": True, "fit_before_target_scoring": True,
                  "parameters_frozen_across_prediction_origins": True, "batch_source_time_replay_equal": True,
                  "external_live_subscriber_implemented": False, "uncertainty_intervals": False},
    }
    return result


def email_eu_dept2_network_report(path: str | Path, protocol: dict) -> dict:
    """Execute the pre-acquisition frozen comparison on its reviewed payload."""
    if content_hash(protocol) != REFERENCE_PROTOCOL_HASH:
        raise ValueError("Dept2 network study requires the frozen pre-acquisition protocol")
    _provider()  # Explicit optional runtime failure before consuming source records.
    # The bounded released-email integer/gzip parser is shared with the Dept3 case.
    archive = load_email_eu_dept3_archive(path)
    if archive.payload_sha256 != REFERENCE_PAYLOAD_SHA256:
        raise ValueError("Dept2 network study requires the reviewed released payload fingerprint")
    audit, admission = _source_audit(archive), protocol["admission"]
    if (audit["row_count"] != admission["required_rows"] or audit["node_count"] != admission["required_nodes"]
            or audit["maximum_relative_second"] < admission["minimum_archive_max_time"]):
        raise ValueError("Dept2 source does not match the frozen metadata/extent admission")
    result = _comparison_report(archive.rows, protocol)
    result.update(
        source={**deepcopy(protocol["source"]), **audit, "reviewed_payload_matches": True,
                "reviewed_compressed_bytes_match": archive.compressed_sha256 == REFERENCE_GZIP_SHA256,
                "attribution": "Ashwin Paranjape, Austin R. Benson and Jure Leskovec, Motifs in Temporal Networks, WSDM 2017, 601-610."},
        runtime=_runtime(),
        admission={"status": "ADMITTED_FOR_RELEASED_ARCHIVE_RECURRENCE",
                   "strict_complete_observation_r1_status": "NOT_ADMITTED",
                   "artifact_extent_check_is_real_followup_closure": False},
    )
    result["content_hash"] = content_hash(result)
    return result
