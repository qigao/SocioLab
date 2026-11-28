"""Post-result archive-presence audit and common-weight score sensitivity.

Archive row presence is separate from real observation coverage. This module
fits no model, changes no labels, and creates no coverage events. Sensitivity
uses saved aggregate errors only; it cannot identify unknown-label bounds.
"""

from __future__ import annotations

from hashlib import sha256
from fractions import Fraction
from itertools import combinations
import json
import math
from pathlib import Path

from ._json import unique_object
from .archive_observation import audit_archive_windows
from .archive_recurrence import _source_audit, load_email_eu_dept3_archive
from .repeat_interaction import _MODELS
from .snapshots import content_hash


WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
_REFERENCE = "always_zero_reference"
_TOLERANCE = 1e-12
_DAY = 86400
_REFERENCES = {
    "email-eu-dept3": {
        "study_commit": "1b02eb04ab76bb8419684e25a717dea023c891db",
        "report_file_sha256": "db93205b0bcb62b1266e324ca79d22cd15d955b55ad40b804621c798b3ff5650",
        "report_content_hash": "sha256:89eb806b93c3305323f0f97180ed7c5ca26cd26f6aeb53ff3bf0e22b5f158545",
        "payload_sha256": "87f766b9e9547cb315c2fc1e49ed6eff2c60c121579b22d095079a401bbb3eb9",
        "protocol_hash": "sha256:d3f841be83127fdcaa4c6ca26129d845ac276c32e6e527b0324aa90c1e8da7e0",
        "schema": "sociolab.released-archive-recurrence-study.v1",
        "study_id": "email-eu-dept3-180d-90d-v1",
        "origins_days": (180, 270, 360, 450, 540, 630),
        "primary_split": "study", "models": _MODELS,
    },
    "email-eu-dept2-network": {
        "study_commit": "1458252b0cec45699dd06a439f9a298339aa6b40",
        "report_file_sha256": "8805a5dca552a9e81e44f7486db1355edccb67dce69d1da0207c37344e470862",
        "report_content_hash": "sha256:02c236fc36c42bbeda9c5e1dfb07705b8a2cc39e4eccc05f99a08c312e941c28",
        "payload_sha256": "2488f3de81722acd1a3ed611c3f0f348dc9e9f3e030cb821edb5fd928c53b45f",
        "protocol_hash": "sha256:67bcbeac8192d0b6f4e928e2b8d5790c6b9c8ac363a35d446e92fc1d21828661",
        "schema": "sociolab.archive-network-comparison.v1",
        "study_id": "email-eu-dept2-frozen-network-recurrence-v1",
        "origins_days": (270, 360, 450, 540, 630),
        "primary_split": "test", "models": _MODELS + ("training_prevalence", "dyadic_logistic", "network_logistic"),
    },
}


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be an explicit nonnegative integer")
    return value


def _finite(value, label):
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number, not a boolean")
    try:
        normalized = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} must be finite") from error
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be finite")
    return normalized


def _ranking(a, b, nonempty_n, empty_n):
    """Classify a linear error-difference numerator on its defined domain."""
    result = {"nonempty_error_difference": a, "empty_error_difference": b,
              "equality_weight": None, "root_below_zero": False, "root_above_one": False,
              "at_weight_zero": a / nonempty_n if nonempty_n else None,
              "at_weight_one": (a + b) / (nonempty_n + empty_n) if nonempty_n + empty_n else None,
              "numerator_at_zero": a, "numerator_at_one": a + b}
    if not nonempty_n + empty_n:
        result["status"] = "NO_RISK"
    elif a == 0 and b == 0:
        result["status"] = "TIED_ALL_DEFINED_WEIGHTS"
    elif b == 0:
        result["status"] = "NO_CROSSING_CONSTANT_SIGN"
    else:
        # Compare the exact ratio of the stored floats before rounding it for
        # output. A subnormal ratio must not become a false endpoint equality.
        exact_root = -Fraction(a) / Fraction(b)
        result.update(root_below_zero=exact_root < 0, root_above_one=exact_root > 1)
        if 0 <= exact_root <= 1 and nonempty_n + exact_root * empty_n > 0:
            root = float(exact_root)
            if exact_root not in (0, 1) and root in (0, 1):
                result["status"] = "NUMERICALLY_UNRESOLVED_EQUALITY"
            else:
                result["equality_weight"] = root
                result["status"] = "ENDPOINT_EQUALITY" if exact_root in (0, 1) else "INTERIOR_CROSSING"
        else:
            result["status"] = "NO_CROSSING_ON_DEFINED_DOMAIN"
    return result


def weight_sensitivity(folds: list[dict], model_names: tuple, weights: tuple = WEIGHTS) -> dict:
    """Vary the common weight of whole empty archive windows, never labels.

    A model receives an all-plan score only if every fold's n equals that
    fold's declared risk count. Missing/failed slots stay visible without an
    automatic intersection or an invented zero-error result.
    """
    if type(folds) is not list or not 1 <= len(folds) <= 100:
        raise ValueError("weight sensitivity requires 1 to 100 planned folds")
    if (type(model_names) not in (tuple, list) or not 1 <= len(model_names) <= 16
            or any(type(name) is not str or not 1 <= len(name) <= 100 for name in model_names)
            or len(set(model_names)) != len(model_names) or _REFERENCE in model_names):
        raise ValueError("supply unique nonempty model names excluding the derived zero reference")
    if type(weights) not in (tuple, list) or not 2 <= len(weights) <= 21:
        raise ValueError("supply 2 to 21 ordered weights including zero and one")
    weights = [_finite(value, "weight") for value in weights]
    if weights[0] != 0 or weights[-1] != 1 or any(a >= b for a, b in zip(weights, weights[1:])):
        raise ValueError("weights must strictly increase from zero to one")
    names = tuple(model_names) + (_REFERENCE,)
    buckets = {key: {"planned_origins": 0, "risk_pair_origins": 0, "positive_pair_origins": 0}
               for key in ("nonempty", "empty")}
    data = {name: {"nonempty": [], "empty": [], "unavailable_or_partial_origins": []} for name in names}
    for index, fold in enumerate(folds):
        if type(fold) is not dict or not {"risk_pairs", "archive_positive_pairs", "target_row_count", "models"} <= fold.keys():
            raise ValueError("each fold must declare risk, positive, row counts and model slots")
        risk = _count(fold["risk_pairs"], "risk_pairs")
        positive = _count(fold["archive_positive_pairs"], "archive_positive_pairs")
        row_count = _count(fold["target_row_count"], "target_row_count")
        if risk > 2000 or positive > risk or positive > row_count:
            raise ValueError("fold risk/positive/row counts are inconsistent with the bounded archive profile")
        group = "nonempty" if row_count else "empty"
        buckets[group]["planned_origins"] += 1
        buckets[group]["risk_pair_origins"] += risk
        buckets[group]["positive_pair_origins"] += positive
        if type(fold.get("models")) is not dict:
            raise ValueError("fold models must be a mapping of explicit scoring slots")
        for name in names:
            slot = ({"n": risk, "brier": positive / risk if risk else None}
                    if name == _REFERENCE else fold["models"].get(name))
            if slot is None:
                n, error = 0, 0.0
                data[name]["unavailable_or_partial_origins"].append(index)
            else:
                if type(slot) is not dict or not {"n", "brier"} <= slot.keys():
                    raise ValueError("model scoring slot must declare n and brier")
                n = _count(slot["n"], "model n")
                if n > risk or (n == 0 and slot["brier"] is not None):
                    raise ValueError("model score count or empty metric is inconsistent")
                brier = _finite(slot["brier"], "Brier") if n else 0.0
                if not 0 <= brier <= 1:
                    raise ValueError("Brier must lie in [0,1]")
                error = float(positive) if name == _REFERENCE else brier * n
                if n < risk:
                    data[name]["unavailable_or_partial_origins"].append(index)
            data[name][group].append((n, error))
    nonempty_n, empty_n = (buckets[key]["risk_pair_origins"] for key in ("nonempty", "empty"))
    n = nonempty_n + empty_n
    models = {}
    for name, values in data.items():
        groups = {key: {"scored_pair_origins": sum(item[0] for item in values[key]),
                        "sum_squared_error": math.fsum(item[1] for item in values[key])}
                  for key in ("nonempty", "empty")}
        complete = not values["unavailable_or_partial_origins"]
        models[name] = {
            "status": "NO_RISK" if not n else "COMPLETE_PLAN" if complete else "INCOMPLETE_MODEL_COVERAGE",
            "complete_plan_coverage": complete and n > 0,
            "scored_pair_origins": sum(group["scored_pair_origins"] for group in groups.values()),
            "unscored_pair_origins": n - sum(group["scored_pair_origins"] for group in groups.values()),
            "unavailable_or_partial_origins": values["unavailable_or_partial_origins"],
            "strata": groups,
            "grid": [{"empty_window_weight": w, "effective_risk_weight": nonempty_n + w * empty_n,
                      "weighted_brier": ((groups["nonempty"]["sum_squared_error"] + w * groups["empty"]["sum_squared_error"])
                                         / (nonempty_n + w * empty_n)
                                         if complete and nonempty_n + w * empty_n > 0 else None)} for w in weights],
        }
    comparisons = []
    for name_a, name_b in combinations(names, 2):
        left, right = models[name_a], models[name_b]
        record = {"model_a": name_a, "model_b": name_b, "difference": "a_minus_b_lower_is_better"}
        if not n:
            record.update(status="NO_RISK", ranking=None, grid_differences=[None for _ in weights])
        elif not left["complete_plan_coverage"] or not right["complete_plan_coverage"]:
            record.update(status="INCOMPLETE_MODEL_COVERAGE", ranking=None, grid_differences=[None for _ in weights])
        else:
            a = left["strata"]["nonempty"]["sum_squared_error"] - right["strata"]["nonempty"]["sum_squared_error"]
            b = left["strata"]["empty"]["sum_squared_error"] - right["strata"]["empty"]["sum_squared_error"]
            record.update(status="COMPARABLE_FULL_PLAN", ranking=_ranking(a, b, nonempty_n, empty_n),
                          grid_differences=[(a + w * b) / (nonempty_n + w * empty_n)
                                            if nonempty_n + w * empty_n else None for w in weights])
        comparisons.append(record)
    result = {
        "schema": "sociolab.archive-empty-window-weight-sensitivity.v1",
        "analysis_status": "POST_RESULT_EXPLORATORY_WEIGHTING",
        "weights": weights, "primary_empty_window_weight": 1.0,
        "planned_origins": len(folds), "risk_pair_origins": n, "strata": buckets,
        "defined_weight_domain": "NONE" if not n else "[0,1]" if nonempty_n else "(0,1]",
        "models": models, "pairwise_comparisons": comparisons,
        "scope": {"model_refitted": False, "archive_labels_changed": False, "model_selected": False,
                  "real_coverage_correction": False, "unknown_label_bounds": False,
                  "confidence_interval": False, "dependent_observations_treated_as_iid": False,
                  "selected_windows_removed_from_primary": False,
                  "zero_weight_is_nonempty_archive_subset_not_qualified_coverage": True,
                  "ranking_uses_stored_floating_point_aggregate_errors": True},
    }
    result["content_hash"] = content_hash(result)
    return result


def _read_bound_case(path: str | Path, reference: dict) -> tuple[dict, str]:
    with Path(path).open("rb") as stream:
        raw = stream.read(2_000_001)
    if not raw or len(raw) > 2_000_000:
        raise ValueError("saved case report must be nonempty and within the byte budget")
    fingerprint = sha256(raw).hexdigest()
    if fingerprint != reference["report_file_sha256"]:
        raise ValueError("observation audit requires the exact previously published case report bytes")
    report = json.loads(raw, object_pairs_hook=unique_object)
    if (type(report) is not dict or report.get("content_hash") != reference["report_content_hash"]
            or report["content_hash"] != content_hash({k: v for k, v in report.items() if k != "content_hash"})
            or report.get("protocol_hash") != reference["protocol_hash"]
            or report.get("schema") != reference["schema"] or report.get("study_id") != reference["study_id"]):
        raise ValueError("case report identity does not match the bound study")
    return report, fingerprint


def archive_observation_report(profile: str, archive_path: str | Path, case_path: str | Path) -> dict:
    """Audit reviewed source windows without reissuing predictions or fitting."""
    if type(profile) is not str or profile not in _REFERENCES:
        raise ValueError("observation audit supports only the reviewed Dept2 and Dept3 studies")
    reference = _REFERENCES[profile]
    report, report_sha = _read_bound_case(case_path, reference)
    archive = load_email_eu_dept3_archive(archive_path)
    if archive.payload_sha256 != reference["payload_sha256"]:
        raise ValueError("observation audit requires the reviewed archive payload")
    source = _source_audit(archive)
    # Recompression is acceptable. The saved release identity still names the
    # original compressed file; the actual supplied compressed hash is separate.
    for key, value in source.items():
        if key not in ("compressed_sha256", "compressed_bytes") and report["source"].get(key) != value:
            raise ValueError("saved case source audit differs from the supplied payload")
    folds = report["folds"]
    origins = [day * _DAY for day in reference["origins_days"]]
    if [fold["origin_at_seconds"] for fold in folds] != origins:
        raise ValueError("saved origins differ from the bound study schedule")
    windows = []
    for index, fold in enumerate(folds):
        origin, end = fold["origin_at_seconds"], fold["target_end_seconds"]
        if end != origin + 90 * _DAY:
            raise ValueError("saved target horizon differs from the bound study")
        split = fold.get("split", "study")
        expected_split = "study" if profile == "email-eu-dept3" else "validation" if index == 0 else "test"
        if split != expected_split:
            raise ValueError("saved validation/test split differs from the bound study")
        windows.append({"id": f"{split}:{origin}", "start": origin, "end": end})
    audit = audit_archive_windows(archive.rows, windows)
    linked = []
    for fold, window in zip(folds, audit["windows"]):
        origin, end = fold["origin_at_seconds"], fold["target_end_seconds"]
        history = tuple(row for row in archive.rows if row[3] < origin)
        target = tuple(row for row in archive.rows if origin <= row[3] < end)
        risk = {row[1:3] for row in history if row[1] != row[2]}
        positives = {row[1:3] for row in target if row[1] != row[2]}
        expected = {"target_row_count": window["row_count"], "target_rows_hash": window["target_rows_hash"],
                    "history_rows_hash": content_hash(history), "risk_pairs": len(risk),
                    "archive_positive_pairs": len(risk & positives), "archive_negative_pairs": len(risk - positives),
                    "target_positive_pairs_outside_risk": len(positives - risk)}
        if any(fold.get(key) != value for key, value in expected.items()):
            raise ValueError("saved target/history/count evidence differs from the source window")
        linked.append({"window_id": window["id"], "split": fold.get("split", "study"),
                       "forecast_hash": fold["forecast_hash"], **expected,
                       "real_absence_of_interaction_established": False,
                       "archive_negative_labels_are_verified_real_negatives": False})
    selected = [fold for fold in folds if fold.get("split", "study") == reference["primary_split"]]
    sensitivity = weight_sensitivity(selected, reference["models"])
    original = report["models"] if reference["primary_split"] == "study" else report["splits"]["test"]["models"]
    original_zero = (report["reference"]["always_zero_brier"] if reference["primary_split"] == "study"
                     else report["splits"]["test"]["always_zero_brier"])
    primary = {}
    for name in reference["models"] + (_REFERENCE,):
        actual = sensitivity["models"][name]["grid"][-1]["weighted_brier"]
        saved = original_zero if name == _REFERENCE else original[name]["pooled_brier"]
        if (actual is None) != (saved is None) or (actual is not None and abs(actual - saved) > _TOLERANCE):
            raise ValueError("weight one does not reproduce the saved primary pooled score")
        primary[name] = {"saved_primary_pooled_brier": saved, "weight_one_pooled_brier": actual,
                         "absolute_difference": abs(actual - saved) if actual is not None else None}
    result = {
        "schema": "sociolab.bound-archive-observation-report.v1", "profile": profile,
        "analysis_status": "POST_RESULT_OBSERVATION_AUDIT_AND_WEIGHTING",
        "prior_study": {"study_id": report["study_id"], "commit": reference["study_commit"],
                        "report_file_sha256": report_sha, "report_content_hash": report["content_hash"],
                        "protocol_hash": report["protocol_hash"], "primary_split": reference["primary_split"]},
        "source": source, "observation_audit": audit, "study_windows": linked,
        "weight_sensitivity": sensitivity, "primary_score_reproduction": primary,
        "primary_score_absolute_tolerance": _TOLERANCE,
        "scope": {"contains_private_actor_records": False, "source_time_unit": "relative_seconds",
                  "full_release_retrospective_audit": True, "live_outage_detector": False,
                  "real_coverage_status": "UNKNOWN", "gap_cause": "UNKNOWN",
                  "calendar_alignment_between_departments": "UNESTABLISHED",
                  "membership_eligibility_verified": False, "coverage_events_created": False,
                  "strict_complete_observation_r1_status": "NOT_ADMITTED",
                  "models_refitted_or_private_predictions_reconstructed": False,
                  "original_study_files_or_labels_changed": False, "primary_results_replaced": False,
                  "relationship_termination_or_causality_inferred": False},
    }
    result["content_hash"] = content_hash(result)
    return result
