"""Independent standard-library observation and weighting audit.

The completed companion report is required before source rows are read. This
checker does not fit models, generate real-coverage declarations, repair labels,
or alter the original study. Only aggregate checks and identities are written.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re


ABSOLUTE_TOLERANCE = 1e-12
WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]
ZERO = "always_zero_reference"
BASELINES = ("historical_poisson", "recent_poisson", "recent_occurrence")
REFERENCES = {
    "email-eu-dept3": {
        "study_commit": "1b02eb04ab76bb8419684e25a717dea023c891db",
        "report_file_sha256": "db93205b0bcb62b1266e324ca79d22cd15d955b55ad40b804621c798b3ff5650",
        "report_content_hash": "sha256:89eb806b93c3305323f0f97180ed7c5ca26cd26f6aeb53ff3bf0e22b5f158545",
        "payload_sha256": "87f766b9e9547cb315c2fc1e49ed6eff2c60c121579b22d095079a401bbb3eb9",
        "protocol_hash": "sha256:d3f841be83127fdcaa4c6ca26129d845ac276c32e6e527b0324aa90c1e8da7e0",
        "schema": "sociolab.released-archive-recurrence-study.v1",
        "study_id": "email-eu-dept3-180d-90d-v1",
        "origins_days": [180, 270, 360, 450, 540, 630], "primary_split": "study",
        "models": BASELINES,
    },
    "email-eu-dept2-network": {
        "study_commit": "1458252b0cec45699dd06a439f9a298339aa6b40",
        "report_file_sha256": "8805a5dca552a9e81e44f7486db1355edccb67dce69d1da0207c37344e470862",
        "report_content_hash": "sha256:02c236fc36c42bbeda9c5e1dfb07705b8a2cc39e4eccc05f99a08c312e941c28",
        "payload_sha256": "2488f3de81722acd1a3ed611c3f0f348dc9e9f3e030cb821edb5fd928c53b45f",
        "protocol_hash": "sha256:67bcbeac8192d0b6f4e928e2b8d5790c6b9c8ac363a35d446e92fc1d21828661",
        "schema": "sociolab.archive-network-comparison.v1",
        "study_id": "email-eu-dept2-frozen-network-recurrence-v1",
        "origins_days": [270, 360, 450, 540, 630], "primary_split": "test",
        "models": BASELINES + ("training_prevalence", "dyadic_logistic", "network_logistic"),
    },
}


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(raw).hexdigest()


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("nonfinite JSON number")


def read_json(path):
    raw = Path(path).read_bytes()
    return json.loads(raw, object_pairs_hook=unique_fields, parse_constant=reject_constant), sha256(raw).hexdigest()


class Checks:
    def __init__(self):
        self.exact_count = 0
        self.numeric_count = 0
        self.maximum_difference = 0.0
        self.mismatches = []

    def exact(self, label, actual, expected):
        self.exact_count += 1
        if actual != expected:
            self.mismatches.append({"field": label, "kind": "exact_mismatch"})

    def numeric(self, label, actual, expected):
        self.numeric_count += 1
        if (type(actual) not in (int, float) or type(expected) not in (int, float)
                or not math.isfinite(actual) or not math.isfinite(expected)):
            self.mismatches.append({"field": label, "kind": "nonfinite_or_nonnumeric"})
            return
        difference = abs(actual - expected)
        self.maximum_difference = max(self.maximum_difference, difference)
        if difference > ABSOLUTE_TOLERANCE:
            self.mismatches.append({"field": label, "kind": "numeric_mismatch",
                                    "absolute_difference": difference})

    def tree(self, label, actual, expected):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                self.exact(label + ".type", type(actual).__name__, "dict")
                return
            self.exact(label + ".keys", sorted(actual), sorted(expected))
            for key, value in expected.items():
                if key in actual:
                    self.tree(label + "." + key, actual[key], value)
        elif isinstance(expected, (list, tuple)):
            if not isinstance(actual, (list, tuple)):
                self.exact(label + ".type", type(actual).__name__, "list")
                return
            self.exact(label + ".length", len(actual), len(expected))
            for index, (observed, value) in enumerate(zip(actual, expected)):
                self.tree(f"{label}[{index}]", observed, value)
        elif isinstance(expected, float):
            self.numeric(label, actual, expected)
        else:
            self.exact(label, actual, expected)

    def identity(self, label, record):
        self.exact(label, record["content_hash"],
                   digest({key: value for key, value in record.items() if key != "content_hash"}))


def read_archive(path):
    with Path(path).open("rb") as stream:
        compressed = stream.read(2_000_001)
    if not compressed or len(compressed) > 2_000_000:
        raise ValueError("compressed archive exceeds bounded source contract")
    with gzip.GzipFile(fileobj=BytesIO(compressed)) as stream:
        payload = stream.read(8_000_001)
    if not payload or len(payload) > 8_000_000:
        raise ValueError("archive payload exceeds bounded source contract")
    lines = payload.decode("ascii").split("\n")
    if lines[-1] == "":
        lines.pop()
    if not 0 < len(lines) <= 100_000:
        raise ValueError("source row count exceeds bounded source contract")
    rows = []
    for index, line in enumerate(lines, 1):
        fields = line.split()
        if len(fields) != 3 or any(not re.fullmatch(r"0|[1-9][0-9]{0,18}", x) for x in fields):
            raise ValueError("noncanonical source row")
        source, target, when = map(int, fields)
        if max(source, target) > 2**31 - 1 or when > 2**63 - 1:
            raise ValueError("source integer outside bounded source contract")
        rows.append((index, source, target, when))
    actors = {actor for row in rows for actor in row[1:3]}
    pairs = {row[1:3] for row in rows if row[1] != row[2]}
    if len(actors) > 200 or len(pairs) > 2000:
        raise ValueError("source actor/pair count exceeds bounded source contract")
    return tuple(rows), {"compressed_sha256": sha256(compressed).hexdigest(),
                         "payload_sha256": sha256(payload).hexdigest(),
                         "compressed_bytes": len(compressed), "payload_bytes": len(payload)}


def observation_oracle(rows, windows):
    """Use direct filtering and adjacent distinct source times, without SocioLab."""
    rows = tuple(sorted(rows))
    times = sorted({row[3] for row in rows})
    gap = {
        "status": "NOT_AVAILABLE", "maximum_elapsed_seconds": None,
        "tied_maximum_count": 0, "first_20_intervals": [], "intervals_truncated": False,
        "interval_boundary": "open_both_record_endpoints_excluded",
        "meaning": "between_record_elapsed_time_not_verified_unobserved_duration",
    }
    adjacent = [(left, right) for left, right in zip(times, times[1:])]
    if adjacent:
        maximum = max(right - left for left, right in adjacent)
        maxima = [(left, right) for left, right in adjacent if right - left == maximum]
        gap.update(status="AVAILABLE", maximum_elapsed_seconds=maximum,
                   tied_maximum_count=len(maxima), intervals_truncated=len(maxima) > 20,
                   first_20_intervals=[{"left_record_seconds": left, "right_record_seconds": right,
                                        "elapsed_seconds": maximum,
                                        "interior_integer_seconds": max(maximum - 1, 0)}
                                       for left, right in maxima[:20]])
    reports = []
    for window in windows:
        start, end = window["start"], window["end"]
        selected = tuple(row for row in rows if start <= row[3] < end)
        nonself = [row for row in selected if row[1] != row[2]]
        before = [value for value in times if value < start]
        after = [value for value in times if value >= end]
        within = [value for value in times if start <= value < end]
        previous, following = (before[-1] if before else None), (after[0] if after else None)
        reports.append({
            "id": window["id"], "start_seconds": start, "end_seconds": end,
            "row_count": len(selected), "nonself_row_count": len(nonself),
            "distinct_actor_count": len({actor for row in selected for actor in row[1:3]}),
            "distinct_nonself_pair_count": len({row[1:3] for row in nonself}),
            "target_rows_hash": digest(selected),
            "archive_row_status": "ARCHIVE_ROWS_PRESENT" if selected else "NO_ARCHIVE_ROWS",
            "real_coverage_status": "UNKNOWN", "real_coverage_evidence": [],
            "membership_eligibility_verified": False,
            "strict_complete_observation_r1_status": "NOT_ADMITTED",
            "previous_record_at_seconds": previous, "next_record_at_seconds": following,
            "empty_window_internally_bounded": not selected and previous is not None and following is not None,
            "first_record_in_window_seconds": within[0] if within else None,
            "last_record_in_window_seconds": within[-1] if within else None,
        })
    result = {
        "schema": "sociolab.archive-observation-audit.v1", "source_rows_hash": digest(rows),
        "source_row_count": len(rows), "distinct_record_time_count": len(times),
        "first_record_seconds": times[0] if times else None, "last_record_seconds": times[-1] if times else None,
        "windows": reports, "longest_between_record_gap": gap,
        "scope": {
            "analysis": "retrospective_full_released_archive_record_presence",
            "source_time_unit": "relative_seconds", "window_boundary": "left_closed_right_open",
            "contains_private_actor_records": False, "past_only_forecast": False,
            "later_archive_records_used_for_gap_boundaries": True,
            "calendar_mapping_verified": False, "recording_start_or_end_inferred": False,
            "real_observation_coverage_inferred": False, "coverage_events_created": False,
            "archive_gap_cause": "UNKNOWN", "recording_outage_inferred": False,
            "real_communication_absence_inferred": False, "relationship_termination_inferred": False,
        },
    }
    result["content_hash"] = digest(result)
    return result


def source_audit(rows, identities):
    triples = Counter(row[1:] for row in rows)
    times = Counter(row[3] for row in rows)
    return {
        **identities, "row_count": len(rows),
        "node_count": len({actor for row in rows for actor in row[1:3]}),
        "distinct_directed_pairs": len({row[1:3] for row in rows}),
        "distinct_nonself_pairs": len({row[1:3] for row in rows if row[1] != row[2]}),
        "self_pair_rows": sum(row[1] == row[2] for row in rows),
        "duplicate_triple_groups": sum(n > 1 for n in triples.values()),
        "duplicate_triple_additional_rows": sum(n - 1 for n in triples.values()),
        "timestamp_tie_groups": sum(n > 1 for n in times.values()),
        "timestamp_tie_additional_rows": sum(n - 1 for n in times.values()),
        "time_decreases_in_file_order": sum(rows[i][3] < rows[i - 1][3] for i in range(1, len(rows))),
        "minimum_relative_second": min(times), "maximum_relative_second": max(times),
        "all_rows_parsed": True, "duplicate_rows_dropped": 0,
        "original_line_numbers_retained": True, "file_order_used_as_receipt_order": False,
    }


def ranking_oracle(nonempty_error_difference, empty_error_difference, nonempty_n, empty_n):
    """Analytical linear numerator on the positive-denominator weight domain."""
    a, b = nonempty_error_difference, empty_error_difference
    total = nonempty_n + empty_n
    root, below, above = None, False, False
    if total == 0:
        status = "NO_RISK"
    elif a == 0 and b == 0:
        status = "TIED_ALL_DEFINED_WEIGHTS"
    elif b == 0:
        status = "NO_CROSSING_CONSTANT_SIGN"
    else:
        # Integer cross-products classify the exact ratio of the stored floats;
        # this does not use the production Fraction-based implementation.
        a_num, a_den = float(a).as_integer_ratio()
        b_num, b_den = float(b).as_integer_ratio()
        numerator, denominator = -a_num * b_den, a_den * b_num
        if denominator < 0:
            numerator, denominator = -numerator, -denominator
        below, above = numerator < 0, numerator > denominator
        defined = nonempty_n * denominator + numerator * empty_n > 0
        if not below and not above and defined:
            candidate = numerator / denominator
            endpoint = numerator == 0 or numerator == denominator
            if not endpoint and candidate in (0, 1):
                status = "NUMERICALLY_UNRESOLVED_EQUALITY"
            else:
                root = candidate
                status = "ENDPOINT_EQUALITY" if endpoint else "INTERIOR_CROSSING"
        else:
            status = "NO_CROSSING_ON_DEFINED_DOMAIN"
    return {
        "nonempty_error_difference": a, "empty_error_difference": b,
        "equality_weight": root, "root_below_zero": below, "root_above_one": above,
        "at_weight_zero": a / nonempty_n if nonempty_n else None,
        "at_weight_one": (a + b) / total if total else None,
        "numerator_at_zero": a, "numerator_at_one": a + b, "status": status,
    }


def weight_oracle(folds, model_names, weights=WEIGHTS):
    """Direct per-fold weighted sums, preserving every planned model slot."""
    models = tuple(model_names) + (ZERO,)
    group_indices = {name: [index for index, fold in enumerate(folds)
                            if bool(fold["target_row_count"]) == (name == "nonempty")]
                     for name in ("nonempty", "empty")}
    strata = {
        name: {"planned_origins": len(indices),
               "risk_pair_origins": sum(folds[i]["risk_pairs"] for i in indices),
               "positive_pair_origins": sum(folds[i]["archive_positive_pairs"] for i in indices)}
        for name, indices in group_indices.items()
    }
    nonempty_n, empty_n = (strata[name]["risk_pair_origins"] for name in ("nonempty", "empty"))
    total = nonempty_n + empty_n
    results = {}
    for name in models:
        counts, errors, missing = [], [], []
        for index, fold in enumerate(folds):
            if name == ZERO:
                n, error = fold["risk_pairs"], float(fold["archive_positive_pairs"])
            else:
                slot = fold["models"].get(name)
                if slot is None:
                    n, error = 0, 0.0
                    missing.append(index)
                else:
                    n = slot["n"]
                    error = slot["brier"] * n if n else 0.0
                    if n < fold["risk_pairs"]:
                        missing.append(index)
            counts.append(n)
            errors.append(error)
        complete = not missing
        group_results = {
            group: {"scored_pair_origins": sum(counts[i] for i in indices),
                    "sum_squared_error": math.fsum(errors[i] for i in indices)}
            for group, indices in group_indices.items()
        }
        grid = []
        for weight in weights:
            coefficients = [weight if not fold["target_row_count"] else 1.0 for fold in folds]
            denominator = math.fsum(c * fold["risk_pairs"] for c, fold in zip(coefficients, folds))
            numerator = math.fsum(c * error for c, error in zip(coefficients, errors))
            grid.append({"empty_window_weight": weight, "effective_risk_weight": denominator,
                         "weighted_brier": numerator / denominator if complete and denominator > 0 else None})
        results[name] = {
            "status": "NO_RISK" if total == 0 else "COMPLETE_PLAN" if complete else "INCOMPLETE_MODEL_COVERAGE",
            "complete_plan_coverage": complete and total > 0,
            "scored_pair_origins": sum(counts), "unscored_pair_origins": total - sum(counts),
            "unavailable_or_partial_origins": missing, "strata": group_results, "grid": grid,
        }
    comparisons = []
    for a_index, name_a in enumerate(models):
        for name_b in models[a_index + 1:]:
            left, right = results[name_a], results[name_b]
            record = {"model_a": name_a, "model_b": name_b, "difference": "a_minus_b_lower_is_better"}
            if total == 0:
                record.update(status="NO_RISK", ranking=None, grid_differences=[None] * len(weights))
            elif not left["complete_plan_coverage"] or not right["complete_plan_coverage"]:
                record.update(status="INCOMPLETE_MODEL_COVERAGE", ranking=None,
                              grid_differences=[None] * len(weights))
            else:
                differences = [left["strata"][group]["sum_squared_error"] - right["strata"][group]["sum_squared_error"]
                               for group in ("nonempty", "empty")]
                grid_differences = [None if a["weighted_brier"] is None else a["weighted_brier"] - b["weighted_brier"]
                                    for a, b in zip(left["grid"], right["grid"])]
                record.update(status="COMPARABLE_FULL_PLAN",
                              ranking=ranking_oracle(*differences, nonempty_n, empty_n),
                              grid_differences=grid_differences)
            comparisons.append(record)
    return {
        "schema": "sociolab.archive-empty-window-weight-sensitivity.v1",
        "analysis_status": "POST_RESULT_EXPLORATORY_WEIGHTING", "weights": list(weights),
        "primary_empty_window_weight": 1.0, "planned_origins": len(folds), "risk_pair_origins": total,
        "strata": strata, "defined_weight_domain": "NONE" if not total else "[0,1]" if nonempty_n else "(0,1]",
        "models": results, "pairwise_comparisons": comparisons,
        "scope": {"model_refitted": False, "archive_labels_changed": False, "model_selected": False,
                  "real_coverage_correction": False, "unknown_label_bounds": False,
                  "confidence_interval": False, "dependent_observations_treated_as_iid": False,
                  "selected_windows_removed_from_primary": False,
                  "zero_weight_is_nonempty_archive_subset_not_qualified_coverage": True,
                  "ranking_uses_stored_floating_point_aggregate_errors": True},
    }


def check_report(profile, rows, source_identity, original, original_file_sha, report):
    checks = Checks()
    reference = REFERENCES[profile]
    checks.exact("report.keys", sorted(report), sorted({
        "schema", "profile", "analysis_status", "prior_study", "source", "observation_audit",
        "study_windows", "weight_sensitivity", "primary_score_reproduction",
        "primary_score_absolute_tolerance", "scope", "content_hash",
    }))
    checks.identity("original.content_hash", original)
    checks.exact("original.file_sha256", original_file_sha, reference["report_file_sha256"])
    for field in ("schema", "study_id", "protocol_hash"):
        checks.exact("original." + field, original[field], reference[field])
    checks.exact("original.content_identity", original["content_hash"], reference["report_content_hash"])
    checks.exact("source.payload_identity", source_identity["payload_sha256"], reference["payload_sha256"])
    source = source_audit(rows, source_identity)
    checks.tree("source", report["source"], source)
    for field, expected in source.items():
        if field not in ("compressed_sha256", "compressed_bytes"):
            checks.exact("original.source." + field, original["source"][field], expected)
    checks.identity("report.content_hash", report)
    for field, expected in {
        "schema": "sociolab.bound-archive-observation-report.v1", "profile": profile,
        "analysis_status": "POST_RESULT_OBSERVATION_AUDIT_AND_WEIGHTING",
        "primary_score_absolute_tolerance": ABSOLUTE_TOLERANCE,
        "prior_study": {"study_id": reference["study_id"], "commit": reference["study_commit"],
                        "report_file_sha256": original_file_sha, "report_content_hash": original["content_hash"],
                        "protocol_hash": reference["protocol_hash"], "primary_split": reference["primary_split"]},
        "scope": {"contains_private_actor_records": False, "source_time_unit": "relative_seconds",
                  "full_release_retrospective_audit": True, "live_outage_detector": False,
                  "real_coverage_status": "UNKNOWN", "gap_cause": "UNKNOWN",
                  "calendar_alignment_between_departments": "UNESTABLISHED",
                  "membership_eligibility_verified": False, "coverage_events_created": False,
                  "strict_complete_observation_r1_status": "NOT_ADMITTED",
                  "models_refitted_or_private_predictions_reconstructed": False,
                  "original_study_files_or_labels_changed": False, "primary_results_replaced": False,
                  "relationship_termination_or_causality_inferred": False},
    }.items():
        checks.tree("report." + field, report[field], expected)
    folds = original["folds"]
    origins = [day * 86400 for day in reference["origins_days"]]
    checks.exact("original.origins", [fold["origin_at_seconds"] for fold in folds], origins)
    windows, linked = [], []
    for index, fold in enumerate(folds):
        origin, end = fold["origin_at_seconds"], fold["target_end_seconds"]
        split = "study" if profile == "email-eu-dept3" else "validation" if index == 0 else "test"
        checks.exact(f"original.folds[{index}].split", fold.get("split", "study"), split)
        checks.exact(f"original.folds[{index}].target_end", end, origin + 90 * 86400)
        identifier = f"{split}:{origin}"
        windows.append({"id": identifier, "start": origin, "end": end})
        past = tuple(row for row in rows if row[3] < origin)
        target = tuple(row for row in rows if origin <= row[3] < end)
        risk = {row[1:3] for row in past if row[1] != row[2]}
        observed_pairs = {row[1:3] for row in target if row[1] != row[2]}
        evidence = {"target_row_count": len(target), "target_rows_hash": digest(target),
                    "history_rows_hash": digest(past), "risk_pairs": len(risk),
                    "archive_positive_pairs": len(risk & observed_pairs),
                    "archive_negative_pairs": len(risk - observed_pairs),
                    "target_positive_pairs_outside_risk": len(observed_pairs - risk)}
        for field, expected in evidence.items():
            checks.exact(f"original.folds[{index}]." + field, fold[field], expected)
        linked.append({"window_id": identifier, "split": split, "forecast_hash": fold["forecast_hash"],
                       **evidence, "real_absence_of_interaction_established": False,
                       "archive_negative_labels_are_verified_real_negatives": False})
    observation = observation_oracle(rows, windows)
    checks.tree("observation_audit", report["observation_audit"], observation)
    checks.tree("study_windows", report["study_windows"], linked)
    selected = [fold for fold in folds if fold.get("split", "study") == reference["primary_split"]]
    expected = weight_oracle(selected, reference["models"])
    checks.identity("weight_sensitivity.content_hash", report["weight_sensitivity"])
    checks.tree("weight_sensitivity", {k: v for k, v in report["weight_sensitivity"].items() if k != "content_hash"}, expected)
    primary_models = original["models"] if reference["primary_split"] == "study" else original["splits"]["test"]["models"]
    primary = {}
    original_zero = (original["reference"]["always_zero_brier"] if reference["primary_split"] == "study"
                     else original["splits"]["test"]["always_zero_brier"])
    for model in reference["models"] + (ZERO,):
        actual = expected["models"][model]["grid"][-1]["weighted_brier"]
        saved = original_zero if model == ZERO else primary_models[model]["pooled_brier"]
        primary[model] = {"saved_primary_pooled_brier": saved, "weight_one_pooled_brier": actual,
                          "absolute_difference": abs(actual - saved) if actual is not None else None}
        if saved is not None:
            checks.numeric("original.primary_reproduced." + model, actual, saved)
        else:
            checks.exact("original.primary_reproduced." + model, actual, None)
    checks.tree("primary_score_reproduction", report["primary_score_reproduction"], primary)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=sorted(REFERENCES))
    for name in ("archive", "original_case", "audit_report", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    # A completed report must exist before any source rows are read by this checker.
    report, report_sha = read_json(args.audit_report)
    original, original_sha = read_json(args.original_case)
    if original_sha != REFERENCES[args.profile]["report_file_sha256"]:
        raise ValueError("original case file differs from its published fixed identity")
    rows, source_identity = read_archive(args.archive)
    if source_identity["payload_sha256"] != REFERENCES[args.profile]["payload_sha256"]:
        raise ValueError("archive differs from the reviewed source payload")
    checks = check_report(args.profile, rows, source_identity, original, original_sha, report)
    original_after = sha256(args.original_case.read_bytes()).hexdigest()
    archive_after = sha256(args.archive.read_bytes()).hexdigest()
    report_after = sha256(args.audit_report.read_bytes()).hexdigest()
    checks.exact("original.file_unchanged", original_after, original_sha)
    checks.exact("archive.file_unchanged", archive_after, source_identity["compressed_sha256"])
    checks.exact("audit_report.file_unchanged", report_after, report_sha)
    result = {
        "schema": "sociolab.archive-observation-independent-check.v1",
        "profile": args.profile, "status": "PASS" if not checks.mismatches else "FAIL",
        "original_case_file_sha256": original_sha, "original_case_content_hash": original["content_hash"],
        "source_compressed_sha256": source_identity["compressed_sha256"],
        "source_payload_sha256": source_identity["payload_sha256"],
        "audit_report_file_sha256": report_sha, "audit_report_content_hash": report["content_hash"],
        "checker_file_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "exact_comparisons": checks.exact_count, "numeric_comparisons": checks.numeric_count,
        "absolute_numeric_tolerance": ABSOLUTE_TOLERANCE,
        "maximum_absolute_numeric_difference": checks.maximum_difference,
        "mismatch_count": len(checks.mismatches), "mismatches": checks.mismatches,
        "source_and_original_case_unchanged": original_after == original_sha and archive_after == source_identity["compressed_sha256"],
        "scope": {
            "stdlib_only": True, "sociolab_or_model_provider_imported": False,
            "models_refitted": False, "private_predictions_reconstructed": False,
            "original_prediction_probabilities_independently_verified": False,
            "source_window_counts_gaps_and_hashes_reconstructed": True,
            "aggregate_weighted_scores_and_ranking_equalities_checked": True,
            "original_primary_scores_preserved": True, "real_coverage_established": False,
            "gap_cause_or_calendar_alignment_identified": False,
            "unknown_label_bounds_or_causal_inference": False,
            "raw_source_or_private_actor_records_written": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in (
        "profile", "status", "exact_comparisons", "numeric_comparisons", "mismatch_count",
        "maximum_absolute_numeric_difference")}))
    return 0 if not checks.mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
