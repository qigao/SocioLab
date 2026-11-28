"""Independently check the frozen Dept3 archive study using the standard library.

Usage: python independent_check.py ARCHIVE PROTOCOL REPORT OUTPUT

Numerical expectations use independently counted physical lines and 1-exp(-x).
The documented expm1 floating-point expression is used separately, only to
reconstruct the exact serialized forecast hash. No SocioLab code is imported.
Only aggregate checks and fingerprints are written; individual rows stay in
memory. This checks the released-record study, not real communication coverage.
"""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import zlib


PROTOCOL_HASH = "sha256:d3f841be83127fdcaa4c6ca26129d845ac276c32e6e527b0324aa90c1e8da7e0"
PAYLOAD_SHA256 = "87f766b9e9547cb315c2fc1e49ed6eff2c60c121579b22d095079a401bbb3eb9"
GZIP_SHA256 = "b1f92288e855044bbc74bacac39d42b12e59ec2a0130ad8df419786eb46a7bff"
FREEZE_COMMIT = "4c93277b7098d2e98e6a4d22874c8e0b9f976d5b"
MODELS = ("historical_poisson", "recent_poisson", "recent_occurrence")
TOLERANCE = 1e-12


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON field")
        result[name] = value
    return result


def reject_constant(_value):
    raise ValueError("nonfinite JSON number")


def read_json(path):
    raw = Path(path).read_bytes()
    return json.loads(raw, object_pairs_hook=unique_fields,
                      parse_constant=reject_constant), sha256(raw).hexdigest()


def source_rows(path, admission):
    """Read physical lines without deduplication, sorting or zero-point shifts."""
    with Path(path).open("rb") as stream:
        compressed = stream.read(admission["maximum_compressed_bytes"] + 1)
    if not compressed or len(compressed) > admission["maximum_compressed_bytes"]:
        raise ValueError("compressed archive size is outside the frozen limit")
    with gzip.GzipFile(fileobj=BytesIO(compressed)) as stream:
        payload = stream.read(admission["maximum_decompressed_bytes"] + 1)
    if not payload or len(payload) > admission["maximum_decompressed_bytes"]:
        raise ValueError("archive payload size is outside the frozen limit")
    if sha256(payload).hexdigest() != PAYLOAD_SHA256:
        raise ValueError("payload fingerprint differs from the reviewed release")
    lines = payload.decode("ascii").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not 0 < len(lines) <= admission["maximum_rows"]:
        raise ValueError("archive line count is outside the frozen limit")
    rows = []
    for line_number, line in enumerate(lines, 1):
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("archive line does not have exactly three fields")
        numbers = []
        for field in fields:
            if not field or any(char not in "0123456789" for char in field):
                raise ValueError("archive field is not a nonnegative ASCII integer")
            if len(field) > 19 or (len(field) > 1 and field.startswith("0")):
                raise ValueError("archive field is not a canonical bounded integer")
            numbers.append(int(field))
        if max(numbers[:2]) > 2**31 - 1 or numbers[2] > 2**63 - 1:
            raise ValueError("archive node or timestamp exceeds the declared numeric range")
        rows.append([line_number, *numbers])
    return rows, compressed, payload


def source_audit(rows, compressed, payload):
    triple_frequency, time_frequency = {}, {}
    nodes, pairs, nonself_pairs = set(), set(), set()
    self_rows = decreases = 0
    last_time = None
    for _line, sender, recipient, when in rows:
        triple = (sender, recipient, when)
        triple_frequency[triple] = triple_frequency.get(triple, 0) + 1
        time_frequency[when] = time_frequency.get(when, 0) + 1
        nodes.update((sender, recipient))
        pairs.add((sender, recipient))
        if sender == recipient:
            self_rows += 1
        else:
            nonself_pairs.add((sender, recipient))
        if last_time is not None and when < last_time:
            decreases += 1
        last_time = when
    return {
        "compressed_sha256": sha256(compressed).hexdigest(),
        "payload_sha256": sha256(payload).hexdigest(),
        "compressed_bytes": len(compressed), "payload_bytes": len(payload),
        "row_count": len(rows), "node_count": len(nodes),
        "distinct_directed_pairs": len(pairs), "distinct_nonself_pairs": len(nonself_pairs),
        "self_pair_rows": self_rows,
        "duplicate_triple_groups": len([n for n in triple_frequency.values() if n > 1]),
        "duplicate_triple_additional_rows": len(rows) - len(triple_frequency),
        "timestamp_tie_groups": len([n for n in time_frequency.values() if n > 1]),
        "timestamp_tie_additional_rows": len(rows) - len(time_frequency),
        "time_decreases_in_file_order": decreases,
        "minimum_relative_second": min(time_frequency), "maximum_relative_second": max(time_frequency),
        "all_rows_parsed": True, "duplicate_rows_dropped": 0,
        "original_line_numbers_retained": True, "file_order_used_as_receipt_order": False,
    }


def probabilities(history_count, recent_count, origin, recent_width, horizon, *, for_hash=False):
    if for_hash:
        # Match documented serialization arithmetic, not the numerical oracle.
        historical = -math.expm1(-(history_count * (horizon / origin)))
        recent = -math.expm1(-(recent_count * (horizon / recent_width)))
    else:
        historical = 1.0 - math.exp(-(history_count * horizon / origin))
        recent = 1.0 - math.exp(-(recent_count * horizon / recent_width))
    return {"historical_poisson": historical, "recent_poisson": recent,
            "recent_occurrence": float(recent_count > 0)}


def statistics(values):
    """Values are independent (probability, binary archive label) calculations."""
    count = len(values)
    return {
        "status": "SCORED" if count else "UNSCORED", "n": count,
        "brier": math.fsum((probability - label) ** 2 for probability, label in values) / count if count else None,
        "mean_predicted_probability": math.fsum(probability for probability, _ in values) / count if count else None,
        "observed_fraction": sum(label for _, label in values) / count if count else None,
    }


def probability_bins(values, boundaries):
    result = []
    for index in range(len(boundaries) - 1):
        lower, upper = boundaries[index:index + 2]
        final = index == len(boundaries) - 2
        selected = [(probability, label) for probability, label in values
                    if lower <= probability and (probability < upper or (final and probability == upper))]
        count = len(selected)
        predicted_sum = math.fsum(probability for probability, _ in selected)
        positive_count = sum(label for _, label in selected)
        error_sum = math.fsum((probability - label) ** 2 for probability, label in selected)
        result.append({
            "lower": lower, "upper": upper, "upper_inclusive": final,
            "count": count, "sum_predicted_probability": predicted_sum,
            "positive_count": positive_count, "sum_squared_error": error_sum,
            "mean_predicted_probability": predicted_sum / count if count else None,
            "observed_fraction": positive_count / count if count else None,
            "brier": error_sum / count if count else None,
        })
    if sum(item["count"] for item in result) != len(values):
        raise ValueError("independent probability bins did not partition all observations")
    return result


def expected_report(rows, audit, protocol):
    measurement = protocol["measurement"]
    horizon, recent_width = measurement["horizon"], measurement["recent_width"]
    boundaries = [float(value) for value in protocol["analysis"]["probability_bins"]]
    reports, previous_risk = [], None
    all_values = {model: [] for model in MODELS}
    oracle_formula_difference = 0.0
    for index, origin in enumerate(measurement["origins"]):
        history, targets = [], []
        counts, recent_counts, target_pairs, historical_nodes = {}, {}, set(), set()
        history_nonself = target_nonself = recent_nonself = 0
        for row in rows:
            _line, sender, recipient, when = row
            pair = sender, recipient
            if 0 <= when < origin:
                history.append(row)
                if sender != recipient:
                    historical_nodes.update(pair)
                    history_nonself += 1
                    counts[pair] = counts.get(pair, 0) + 1
                    if origin - recent_width <= when:
                        recent_nonself += 1
                        recent_counts[pair] = recent_counts.get(pair, 0) + 1
            elif origin <= when < origin + horizon:
                targets.append(row)
                if sender != recipient:
                    target_nonself += 1
                    target_pairs.add(pair)
        risk = set(counts)
        values = {model: [] for model in MODELS}
        serialization_predictions = []
        for pair in sorted(risk):
            recent = recent_counts.get(pair, 0)
            numeric = probabilities(counts[pair], recent, origin, recent_width, horizon)
            serialized = probabilities(counts[pair], recent, origin, recent_width, horizon, for_hash=True)
            label = int(pair in target_pairs)
            for model in MODELS:
                values[model].append((numeric[model], label))
                oracle_formula_difference = max(oracle_formula_difference, abs(numeric[model] - serialized[model]))
            serialization_predictions.append({
                "source": pair[0], "target": pair[1], "history_count": counts[pair],
                "recent_count": recent, "probabilities": serialized,
            })
        serialized_forecast = {
            "schema": "sociolab.released-archive-prediction.v1",
            "origin_at_seconds": origin, "history_start_seconds": 0,
            "recent_start_seconds": origin - recent_width, "target_end_seconds": origin + horizon,
            "history_rows_hash": digest(history), "history_row_count": len(history),
            "history_nonself_row_count": history_nonself, "recent_nonself_row_count": recent_nonself,
            "history_actor_count": len(historical_nodes), "predictions": serialization_predictions,
            "scope": {"contains_private_actor_records": True, "target": "matching_released_archive_row",
                      "source_time_history_only": True, "real_receipt_history_reconstructed": False,
                      "prospective_issuance_verified": False},
        }
        positive_count = sum(pair in target_pairs for pair in risk)
        report = {
            "index": index, "origin_at_seconds": origin,
            "recent_start_seconds": origin - recent_width, "target_end_seconds": origin + horizon,
            "history_rows_hash": digest(history), "history_row_count": len(history),
            "history_nonself_row_count": history_nonself, "recent_nonself_row_count": recent_nonself,
            "history_actor_count": len(historical_nodes),
            "status": "ARCHIVE_LABELS_SCORED" if risk else "EMPTY_RISK_SET",
            "forecast_hash": digest(serialized_forecast), "target_rows_hash": digest(targets),
            "target_row_count": len(targets), "target_nonself_row_count": target_nonself,
            "risk_pairs": len(risk), "archive_positive_pairs": positive_count,
            "archive_negative_pairs": len(risk) - positive_count,
            "target_positive_pairs_outside_risk": len(target_pairs.difference(risk)),
            "models": {model: statistics(values[model]) for model in MODELS},
            "probability_diagnostics": {model: {"bins": probability_bins(values[model], boundaries)} for model in MODELS},
            "always_zero_brier": positive_count / len(risk) if risk else None,
            "risk_change": {
                "risk_set_hash": digest(sorted(risk)),
                "compared_with_previous_planned_origin": previous_risk is not None,
                "retained_pairs": None if previous_risk is None else len(risk.intersection(previous_risk)),
                "new_pairs": None if previous_risk is None else len(risk.difference(previous_risk)),
                "removed_pairs": None if previous_risk is None else len(previous_risk.difference(risk)),
            },
        }
        reports.append(report)
        for model in MODELS:
            all_values[model].extend(values[model])
        previous_risk = risk
    total = sum(report["risk_pairs"] for report in reports)
    positives = sum(report["archive_positive_pairs"] for report in reports)
    models = {}
    for model in MODELS:
        pooled = statistics(all_values[model])
        models[model] = {
            "n": total, "pooled_brier": pooled["brier"],
            "macro_brier": (math.fsum(report["models"][model]["brier"] for report in reports) / len(reports)
                            if all(report["risk_pairs"] for report in reports) else None),
            "mean_predicted_probability": pooled["mean_predicted_probability"],
            "observed_fraction": pooled["observed_fraction"],
            "bins": probability_bins(all_values[model], boundaries),
        }
    zero_reference = positives / total if total else None
    result = {
        "schema": "sociolab.released-archive-recurrence-study.v1", "kind": "RELEASED_ARCHIVE_RECURRENCE_STUDY",
        "profile": "email-eu-dept3-released-record-recurrence-v1", "study_id": protocol["study_id"],
        "protocol_hash": digest(protocol), "protocol_freeze_commit": FREEZE_COMMIT,
        "source": {
            **protocol["source"], **audit, "reviewed_payload_matches": True,
            "reviewed_compressed_bytes_match": audit["compressed_sha256"] == GZIP_SHA256,
            "attribution": "Ashwin Paranjape, Austin R. Benson and Jure Leskovec, Motifs in Temporal Networks, WSDM 2017, 601-610.",
        },
        "measurement": measurement,
        "admission": {"status": "ADMITTED_FOR_RELEASED_ARCHIVE_RECURRENCE",
                      "strict_complete_observation_r1_status": "NOT_ADMITTED",
                      "artifact_extent_check_is_real_followup_closure": False},
        "counts": {"planned_origins": len(reports), "scored_origins": sum(report["risk_pairs"] > 0 for report in reports),
                   "risk_pair_origin_count": total, "scored_pair_origin_count": total,
                   "archive_positive_pair_origin_count": positives, "archive_negative_pair_origin_count": total - positives},
        "folds": reports, "probability_bins": boundaries, "models": models,
        "reference": {"always_zero_brier": zero_reference,
                      "model_brier_minus_always_zero": {
                          model: models[model]["pooled_brier"] - zero_reference if total else None for model in MODELS}},
        "scope": {
            **protocol["scope"], "released_record_temporal_holdout_executed": True,
            "real_communication_forecast_validated": False,
            "source_membership_or_coverage_assertions_created": False,
            "all_models_use_same_archive_labels": True, "contains_private_actor_records": False,
            "sample_unit": "ordered_pair_origin_not_independent_relationship",
            "target_information_used_to_refit": False, "confidence_intervals": False,
            "dependent_pairs_treated_as_iid": False,
        },
    }
    return result, oracle_formula_difference


def compare(expected, actual, path, checks):
    """Record aggregate mismatches without emitting observed values or IDs."""
    if type(expected) is dict:
        if type(actual) is not dict:
            checks["mismatches"].append(path + ": object required")
            return
        if set(expected) != set(actual):
            checks["mismatches"].append(path + ": exact field set mismatch")
        for key in expected.keys() & actual.keys():
            compare(expected[key], actual[key], path + "." + key, checks)
    elif type(expected) is list:
        if type(actual) is not list or len(expected) != len(actual):
            checks["mismatches"].append(path + ": array length/type mismatch")
            return
        for index, (wanted, found) in enumerate(zip(expected, actual)):
            compare(wanted, found, path + "[" + str(index) + "]", checks)
    elif type(expected) is float:
        checks["numeric_comparisons"] += 1
        if type(actual) not in (int, float):
            checks["mismatches"].append(path + ": finite numeric value required")
            return
        try:
            difference = abs(expected - actual)
            finite = math.isfinite(actual) and math.isfinite(difference)
        except OverflowError:
            finite = False
        if not finite:
            checks["mismatches"].append(path + ": nonfinite value or difference")
            return
        checks["max_absolute_numeric_difference"] = max(checks["max_absolute_numeric_difference"], difference)
        if difference > TOLERANCE:
            checks["mismatches"].append(path + ": numeric tolerance exceeded")
    else:
        checks["exact_comparisons"] += 1
        if type(expected) is not type(actual) or expected != actual:
            checks["mismatches"].append(path + ": exact value/type mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("protocol")
    parser.add_argument("report")
    parser.add_argument("output")
    args = parser.parse_args()
    checks = {"numeric_comparisons": 0, "exact_comparisons": 0,
              "max_absolute_numeric_difference": 0.0, "mismatches": []}
    result = {
        "schema": "sociolab.dept3-independent-check.v1", "status": "FAILED",
        "checker_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "absolute_numeric_tolerance": TOLERANCE,
        "numerical_oracle": "independent physical-line counts and 1 - math.exp(-count * horizon / duration)",
        "forecast_hash_reconstruction": "separate documented -math.expm1(-count * (horizon / duration)) serialization only",
        "imports_sociolab": False, "contains_private_actor_records": False,
        "validates_real_communication_coverage": False, "validates_causality": False,
        "input_fingerprints": {}, "counts": {},
    }
    stage = "read_protocol_and_report"
    try:
        protocol, protocol_file_hash = read_json(args.protocol)
        report, report_file_hash = read_json(args.report)
        result["input_fingerprints"].update(protocol_file_sha256=protocol_file_hash, report_file_sha256=report_file_hash)
        if digest(protocol) != PROTOCOL_HASH:
            raise ValueError("protocol differs from the frozen pre-acquisition plan")
        if type(report) is not dict or "content_hash" not in report:
            raise ValueError("study report requires its integrity hash")
        body = {key: value for key, value in report.items() if key != "content_hash"}
        result["input_fingerprints"].update(protocol_content_hash=digest(protocol), report_content_hash=digest(body))
        if report["content_hash"] != digest(body):
            raise ValueError("study report integrity hash does not match")
        stage = "parse_complete_archive"
        rows, compressed, payload = source_rows(args.archive, protocol["admission"])
        audit = source_audit(rows, compressed, payload)
        result["input_fingerprints"].update(archive_compressed_sha256=audit["compressed_sha256"],
                                              archive_payload_sha256=audit["payload_sha256"])
        admission = protocol["admission"]
        if (audit["row_count"] != admission["required_rows"] or audit["node_count"] != admission["required_nodes"]
                or audit["node_count"] > admission["maximum_nodes"]
                or audit["distinct_nonself_pairs"] > admission["maximum_nonself_risk_pairs"]
                or audit["maximum_relative_second"] < admission["minimum_archive_max_time"]):
            raise ValueError("archive fails a frozen source-admission condition")
        stage = "independent_expectations_and_comparison"
        expected, formula_difference = expected_report(rows, audit, protocol)
        compare(expected, body, "report", checks)
        result["counts"] = {
            "source_rows": len(rows), "source_nodes": audit["node_count"],
            "planned_origins": expected["counts"]["planned_origins"],
            "risk_pair_origin_observations": expected["counts"]["risk_pair_origin_count"],
            "forecast_hashes_compared": len(expected["folds"]),
            "history_row_hashes_compared": len(expected["folds"]),
            "target_row_hashes_compared": len(expected["folds"]),
        }
        result["max_probability_formula_difference"] = formula_difference
        result["status"] = "PASS" if not checks["mismatches"] else "FAILED"
    except (ValueError, TypeError, KeyError, OSError, EOFError, zlib.error) as error:
        result["failure_stage"] = stage
        result["failure_kind"] = type(error).__name__
        # Do not copy exception arguments: malformed inputs can contain IDs.
        checks["mismatches"].append("input or contract validation failed at " + stage)
    result.update({key: value for key, value in checks.items() if key != "mismatches"})
    result["mismatch_count"] = len(checks["mismatches"])
    result["mismatch_paths"] = sorted(checks["mismatches"])[:50]
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "mismatch_count": result["mismatch_count"],
                      "max_absolute_numeric_difference": result["max_absolute_numeric_difference"]}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
