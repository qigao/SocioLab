"""Check the frozen Dept2 comparison with standard-library arithmetic only.

Usage: python independent_check.py ARCHIVE PROTOCOL CASE_REPORT OUTPUT

The independent oracle counts physical archive rows, derives graph covariates
with sets, checks training-only population scaling, and evaluates saved fitted
coefficients with scalar sigmoid arithmetic. It neither imports SocioLab nor
refits or verifies scikit-learn's optimizer. Numerical baseline expectations use
1-exp(-x); expm1 is used separately only for exact feature-artifact identities.
Private prediction rows are not published, so exact upstream floating-point
forecast hashes cannot be independently reconstructed here. Scores, bins and
all available source/feature/training/parameter identities are checked instead.
Only aggregate results and fingerprints leave memory. This is not a test of
real communication coverage, causal interpretation or calibrated probabilities.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re


PROTOCOL_HASH = "sha256:67bcbeac8192d0b6f4e928e2b8d5790c6b9c8ac363a35d446e92fc1d21828661"
PAYLOAD_SHA256 = "2488f3de81722acd1a3ed611c3f0f348dc9e9f3e030cb821edb5fd928c53b45f"
GZIP_SHA256 = "8e8dcdb9049a671f2afcb4bc91ff8ad77423a40612ce8318ef0825aa8b44b53d"
FREEZE_COMMIT = "938c8e417def93f6e331f04ce52b6deb42f100d2"
MODELS = ("historical_poisson", "recent_poisson", "recent_occurrence",
          "training_prevalence", "dyadic_logistic", "network_logistic")
FITTED_BLOCKS = {"dyadic_logistic": "dyadic", "network_logistic": "network"}
ABSOLUTE_TOLERANCE = 1e-10
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")


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
    return (json.loads(raw, object_pairs_hook=unique_fields, parse_constant=reject_constant),
            sha256(raw).hexdigest())


class Checks:
    def __init__(self):
        self.exact_count = 0
        self.numeric_count = 0
        self.maximum_difference = 0.0
        self.mismatches = []

    def exact(self, label, actual, expected):
        self.exact_count += 1
        if actual != expected:
            # Values might contain private source rows; only field paths leave memory.
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


def read_archive(path, protocol):
    limits = protocol["admission"]
    with Path(path).open("rb") as stream:
        compressed = stream.read(limits["maximum_compressed_bytes"] + 1)
    if not compressed or len(compressed) > limits["maximum_compressed_bytes"]:
        raise ValueError("compressed size exceeds frozen limit")
    with gzip.GzipFile(fileobj=BytesIO(compressed)) as stream:
        payload = stream.read(limits["maximum_decompressed_bytes"] + 1)
    if not payload or len(payload) > limits["maximum_decompressed_bytes"]:
        raise ValueError("decompressed size exceeds frozen limit")
    if sha256(payload).hexdigest() != PAYLOAD_SHA256:
        raise ValueError("source payload differs from reviewed source")
    lines = payload.decode("ascii").split("\n")
    if lines[-1] == "":
        lines.pop()
    if not 0 < len(lines) <= limits["maximum_rows"]:
        raise ValueError("row count outside frozen limit")
    rows = []
    for number, line in enumerate(lines, 1):
        fields = line.split()
        if len(fields) != 3 or any(not re.fullmatch(r"0|[1-9][0-9]{0,18}", x) for x in fields):
            raise ValueError("noncanonical source row")
        sender, receiver, when = map(int, fields)
        if max(sender, receiver) > 2**31 - 1 or when > 2**63 - 1:
            raise ValueError("source integer outside declared bounds")
        rows.append((number, sender, receiver, when))
    actors = {actor for row in rows for actor in row[1:3]}
    pairs = {row[1:3] for row in rows}
    nonself_pairs = {pair for pair in pairs if pair[0] != pair[1]}
    if len(actors) > limits["maximum_nodes"] or len(nonself_pairs) > limits["maximum_nonself_pairs"]:
        raise ValueError("source actor or pair count outside frozen limit")
    triples, times = Counter(row[1:] for row in rows), Counter(row[3] for row in rows)
    audit = {
        "compressed_sha256": sha256(compressed).hexdigest(), "payload_sha256": sha256(payload).hexdigest(),
        "compressed_bytes": len(compressed), "payload_bytes": len(payload),
        "row_count": len(rows), "node_count": len(actors), "distinct_directed_pairs": len(pairs),
        "distinct_nonself_pairs": len(nonself_pairs), "self_pair_rows": sum(a == b for _, a, b, _ in rows),
        "duplicate_triple_groups": sum(count > 1 for count in triples.values()),
        "duplicate_triple_additional_rows": sum(count - 1 for count in triples.values()),
        "timestamp_tie_groups": sum(count > 1 for count in times.values()),
        "timestamp_tie_additional_rows": sum(count - 1 for count in times.values()),
        "time_decreases_in_file_order": sum(rows[i][3] < rows[i - 1][3] for i in range(1, len(rows))),
        "minimum_relative_second": min(times), "maximum_relative_second": max(times),
        "all_rows_parsed": True, "duplicate_rows_dropped": 0,
        "original_line_numbers_retained": True, "file_order_used_as_receipt_order": False,
    }
    return tuple(rows), audit


def feature_snapshot(history, origin, protocol):
    """Independent covariates from sets; no NetworkX or fitted model is used."""
    horizon, recent_width = (protocol["measurement"][key] for key in ("horizon", "recent_width"))
    history = tuple(sorted(history))
    counts, recent, last = Counter(), Counter(), {}
    outgoing, incoming = defaultdict(set), defaultdict(set)
    for _, source, target, when in history:
        if not 0 <= when < origin:
            raise ValueError("oracle history includes a future row")
        if source == target:
            continue
        pair = source, target
        counts[pair] += 1
        if when >= origin - recent_width:
            recent[pair] += 1
        last[pair] = max(last.get(pair, when), when)
        outgoing[source].add(target)
        incoming[target].add(source)
    feature_rows, identity_predictions, probabilities = [], [], {}
    for pair in sorted(counts):
        source, target = pair
        history_expected = counts[pair] * horizon / origin
        recent_expected = recent[pair] * horizon / recent_width
        local = [math.log1p(history_expected), math.log1p(recent_expected),
                 math.log1p((origin - last[pair]) / horizon)]
        network = local + [math.log1p(counts[target, source] * horizon / origin),
                           math.log1p(recent[target, source] * horizon / recent_width),
                           math.log1p(len(outgoing[source])), math.log1p(len(incoming[target])),
                           math.log1p(len((outgoing[source] & incoming[target]) - {source, target}))]
        feature_rows.append({"source": source, "target": target,
                             "dyadic_features": local, "network_features": network})
        # Separate numeric oracle, not exact floating-point hash reconstruction.
        probabilities[pair] = {"historical_poisson": 1.0 - math.exp(-history_expected),
                               "recent_poisson": 1.0 - math.exp(-recent_expected),
                               "recent_occurrence": float(recent[pair] > 0)}
        identity_predictions.append({
            "source": source, "target": target, "history_count": counts[pair], "recent_count": recent[pair],
            "probabilities": {"historical_poisson": -math.expm1(-(counts[pair] * (horizon / origin))),
                              "recent_poisson": -math.expm1(-(recent[pair] * (horizon / recent_width))),
                              "recent_occurrence": float(recent[pair] > 0)},
        })
    baseline = {
        "schema": "sociolab.released-archive-prediction.v1", "origin_at_seconds": origin,
        "history_start_seconds": 0, "recent_start_seconds": origin - recent_width,
        "target_end_seconds": origin + horizon, "history_rows_hash": digest(history),
        "history_row_count": len(history), "history_nonself_row_count": sum(counts.values()),
        "recent_nonself_row_count": sum(recent.values()),
        "history_actor_count": len({actor for pair in counts for actor in pair}),
        "predictions": identity_predictions,
        "scope": {"contains_private_actor_records": True, "target": "matching_released_archive_row",
                  "source_time_history_only": True, "real_receipt_history_reconstructed": False,
                  "prospective_issuance_verified": False},
    }
    names = {"dyadic": protocol["features"]["dyadic"],
             "network": protocol["features"]["dyadic"] + protocol["features"]["network_additions"]}
    features = {
        "schema": "sociolab.archive-network-features.v1", "baseline_forecast_hash": digest(baseline),
        "history_rows_hash": digest(history), "history_row_count": len(history),
        "origin_at_seconds": origin, "horizon_seconds": horizon, "recent_width_seconds": recent_width,
        "feature_names": names, "rows": feature_rows,
        "scope": {"contains_private_actor_records": True, "target": "matching_released_archive_row",
                  "source_time_history_only": True, "source_time_unit": "relative_seconds",
                  "historical_receipt_availability_verified": False,
                  "source_membership_or_coverage_assertions_created": False,
                  "graph_provider": "networkx.DiGraph", "graph_edges": "binary_nonself_history_pairs",
                  "target_information_consumed": False},
    }
    features["content_hash"] = digest(features)
    return features, probabilities


def reconstruct_training(rows, protocol):
    measurement = protocol["measurement"]
    cutoff, horizon = measurement["fit_cutoff"], measurement["horizon"]
    available = tuple(row for row in rows if row[3] < cutoff)
    examples, folds = [], []
    for origin in measurement["training_origins"]:
        if origin + horizon > cutoff:
            raise ValueError("training labels extend past fit cutoff")
        features, _ = feature_snapshot(tuple(row for row in available if row[3] < origin), origin, protocol)
        target = tuple(row for row in available if origin <= row[3] < origin + horizon)
        positive = {row[1:3] for row in target if row[1] != row[2]}
        labels = []
        for item in features["rows"]:
            label = int((item["source"], item["target"]) in positive)
            labels.append([item["source"], item["target"], label])
            examples.append({"origin_at_seconds": origin, **item, "label": label})
        risk = {(item["source"], item["target"]) for item in features["rows"]}
        folds.append({
            "origin_at_seconds": origin, "target_end_seconds": origin + horizon,
            "history_rows_hash": features["history_rows_hash"], "feature_hash": features["content_hash"],
            "target_rows_hash": digest(target), "labels_hash": digest(labels), "risk_pairs": len(risk),
            "archive_positive_pairs": len(risk & positive), "target_row_count": len(target),
            "target_positive_pairs_outside_risk": len(positive - risk),
        })
    n, positives = len(examples), sum(item["label"] for item in examples)
    summary = {"fit_cutoff_seconds": cutoff, "history_rows_hash": digest(available),
               "training_examples_hash": digest(examples), "pair_origin_count": n,
               "positive_count": positives, "negative_count": n - positives,
               "prevalence": positives / n if n else None, "folds": folds,
               "validation_or_test_labels_used": False}
    summary["content_hash"] = digest(summary)
    return examples, summary


def check_fitted_models(checks, records, examples, training, protocol):
    checks.exact("fitted_models.names", sorted(records), sorted(FITTED_BLOCKS))
    for name, block in FITTED_BLOCKS.items():
        record, label = records[name], "fitted_models." + name
        matrix = [item[block + "_features"] for item in examples]
        labels = [item["label"] for item in examples]
        names = protocol["features"]["dyadic"] + (protocol["features"]["network_additions"] if block == "network" else [])
        for key, value in {
            "schema": "sociolab.archive-recurrence-fitted-model.v1", "model": name,
            "feature_names": names, "training_hash": training["content_hash"],
            "training_feature_matrix_hash": digest(matrix), "training_labels_hash": digest(labels),
            "protocol_hash": digest(protocol), "fit_cutoff_seconds": training["fit_cutoff_seconds"],
            "provider": {"name": "scikit-learn", "version": "1.9.1"},
            "declared_parameters": protocol["estimation"]["parameters"],
            "training_n": len(labels), "training_positive_count": sum(labels),
        }.items():
            checks.exact(label + "." + key, record[key], value)
        checks.identity(label + ".content_hash", record)
        checks.exact(label + ".status_supported", record["status"] in ("FITTED", "NOT_ESTIMABLE", "FAILED"), True)
        if record["parameter_state"] is not None:
            checks.exact(label + ".parameter_hash", record["parameter_hash"], digest(record["parameter_state"]))
        if record["status"] != "FITTED":
            checks.exact(label + ".failure_has_reason", bool(record["reason"]), True)
            continue
        checks.exact(label + ".warnings", record["warnings"], [])
        checks.exact(label + ".reason", record["reason"], None)
        state = record["parameter_state"]
        scaling, estimator = state["scaler"], state["estimator"]
        checks.exact(label + ".classes", estimator["classes"], [0, 1])
        checks.exact(label + ".class_support", set(labels), {0, 1})
        checks.exact(label + ".scaler.n_samples_seen", scaling["n_samples_seen"], len(matrix))
        checks.exact(label + ".scaler.n_features_in", scaling["n_features_in"], len(names))
        checks.exact(label + ".estimator.n_features_in", estimator["n_features_in"], len(names))
        checks.exact(label + ".coefficient_shape", [len(x) for x in estimator["coefficients"]], [len(names)])
        checks.exact(label + ".intercept_length", len(estimator["intercept"]), 1)
        checks.exact(label + ".iteration_length", len(estimator["n_iter"]), 1)
        checks.exact(label + ".iteration_budget", 0 < estimator["n_iter"][0] <= protocol["estimation"]["parameters"]["max_iter"], True)
        for key, value in protocol["estimation"]["parameters"].items():
            checks.exact(label + ".estimator.parameters." + key, estimator["parameters"][key], value)
        for key, value in protocol["estimation"]["scaler_parameters"].items():
            checks.exact(label + ".scaler.parameters." + key, scaling["parameters"][key], value)
        for field in ("mean", "scale", "variance"):
            checks.exact(label + ".scaler." + field + ".length", len(scaling[field]), len(names))
        for index in range(len(names)):
            column = [row[index] for row in matrix]
            mean = math.fsum(column) / len(column)
            variance = math.fsum((value - mean) ** 2 for value in column) / len(column)
            # StandardScaler uses population variance and protects numerically constant columns.
            eps = 2.220446049250313e-16
            constant_bound = len(column) * eps * variance + (len(column) * mean * eps) ** 2
            scale = 1.0 if variance <= constant_bound else math.sqrt(variance)
            checks.numeric(f"{label}.scaler.mean[{index}]", scaling["mean"][index], mean)
            checks.numeric(f"{label}.scaler.variance[{index}]", scaling["variance"][index], variance)
            checks.numeric(f"{label}.scaler.scale[{index}]", scaling["scale"][index], scale)
        finite = all(math.isfinite(value) for row in estimator["coefficients"] for value in row)
        finite = finite and all(math.isfinite(value) for value in estimator["intercept"])
        checks.exact(label + ".finite_coefficients", finite, True)


def fitted_probability(feature_row, record):
    block = FITTED_BLOCKS[record["model"]]
    state = record["parameter_state"]
    scaler, estimator = state["scaler"], state["estimator"]
    products = [((value - mean) / scale) * coefficient for value, mean, scale, coefficient in zip(
        feature_row[block + "_features"], scaler["mean"], scaler["scale"], estimator["coefficients"][0])]
    linear = math.fsum(products) + estimator["intercept"][0]
    if linear >= 0:
        return 1.0 / (1.0 + math.exp(-linear))
    exponential = math.exp(linear)
    return exponential / (1.0 + exponential)


def scores(values, edges, available):
    n, positives = len(values), sum(label for _, label in values)
    score = {"status": ("SCORED" if n else "UNSCORED") if available else "MODEL_NOT_AVAILABLE",
             "n": n, "brier": math.fsum((p - y) ** 2 for p, y in values) / n if n else None,
             "mean_predicted_probability": math.fsum(p for p, _ in values) / n if n else None,
             "observed_fraction": positives / n if n else None}
    bins = []
    for index, (lower, upper) in enumerate(zip(edges, edges[1:])):
        final = index == len(edges) - 2
        selected = [(p, y) for p, y in values if lower <= p and (p < upper or (final and p == upper))]
        count, positive = len(selected), sum(y for _, y in selected)
        total = math.fsum(p for p, _ in selected)
        error = math.fsum((p - y) ** 2 for p, y in selected)
        bins.append({"lower": lower, "upper": upper, "upper_inclusive": final,
                     "count": count, "sum_predicted_probability": total, "positive_count": positive,
                     "sum_squared_error": error, "mean_predicted_probability": total / count if count else None,
                     "observed_fraction": positive / count if count else None,
                     "brier": error / count if count else None})
    return score, {"bins": bins}


def split_summary(folds, model_rows, edges):
    n, positives = sum(row["risk_pairs"] for row in folds), sum(row["archive_positive_pairs"] for row in folds)
    summaries = {}
    for name in MODELS:
        values = [item for fold in folds for item in model_rows[fold["origin_at_seconds"]][name]]
        score, bins = scores(values, edges, True)
        fold_scores = [fold["models"][name] for fold in folds]
        nonempty = [item for item in fold_scores if item["n"]]
        summaries[name] = {
            "n": len(values), "pooled_brier": score["brier"],
            "macro_brier": math.fsum(item["brier"] for item in nonempty) / len(folds) if len(nonempty) == len(folds) else None,
            "mean_predicted_probability": score["mean_predicted_probability"],
            "observed_fraction": score["observed_fraction"], "bins": bins["bins"],
            "planned_origins": len(folds), "scored_origins": len(nonempty),
            "unscored_pair_origins": n - len(values), "full_planned_risk_scored": n > 0 and len(values) == n,
        }
    network, dyadic = summaries["network_logistic"], summaries["dyadic_logistic"]
    comparable = n > 0 and network["n"] == dyadic["n"] == n
    zero = positives / n if n else None
    return {
        "planned_origins": len(folds), "risk_pair_origin_count": n,
        "archive_positive_pair_origin_count": positives, "archive_negative_pair_origin_count": n - positives,
        "models": summaries, "always_zero_brier": zero,
        "network_minus_dyadic_pooled_brier": network["pooled_brier"] - dyadic["pooled_brier"] if comparable else None,
        "network_dyadic_common_pair_origins": n if comparable else 0,
        "model_brier_minus_always_zero": {name: model["pooled_brier"] - zero if n and model["n"] == n else None
                                         for name, model in summaries.items()},
    }


def check_report(rows, audit, protocol, report):
    checks = Checks()
    checks.identity("report.content_hash", report)
    for key, expected in {
        "schema": "sociolab.archive-network-comparison.v1", "study_id": protocol["study_id"],
        "profile": "dept2-released-archive-network-recurrence-v1", "protocol_hash": digest(protocol),
        "protocol_freeze_commit": FREEZE_COMMIT, "measurement": protocol["measurement"],
        "admission": {"status": "ADMITTED_FOR_RELEASED_ARCHIVE_RECURRENCE",
                      "strict_complete_observation_r1_status": "NOT_ADMITTED",
                      "artifact_extent_check_is_real_followup_closure": False},
    }.items():
        checks.exact("report." + key, report[key], expected)
    for key, expected in {**protocol["source"], **audit}.items():
        checks.exact("source." + key, report["source"][key], expected)
    checks.exact("source.reviewed_payload_matches", report["source"]["reviewed_payload_matches"], True)
    checks.exact("source.reviewed_compressed_bytes_match", report["source"]["reviewed_compressed_bytes_match"],
                 audit["compressed_sha256"] == GZIP_SHA256)
    checks.exact("runtime.provider", report["runtime"]["packages"]["scikit-learn"], "1.9.1")
    for key, expected in protocol["scope"].items():
        checks.exact("scope." + key, report["scope"][key], expected)
    for key, expected in {"contains_private_actor_records": False, "all_planned_origins_retained": True,
                          "fit_before_target_scoring": True, "parameters_frozen_across_prediction_origins": True,
                          "batch_source_time_replay_equal": True, "external_live_subscriber_implemented": False,
                          "uncertainty_intervals": False}.items():
        checks.exact("scope." + key, report["scope"][key], expected)
    examples, training = reconstruct_training(rows, protocol)
    checks.tree("training", report["training"], training)
    check_fitted_models(checks, report["fitted_models"], examples, training, protocol)
    edges = [float(value) for value in protocol["analysis"]["probability_bins"]]
    checks.exact("probability_bins", report["probability_bins"], edges)
    measurement, models = protocol["measurement"], report["fitted_models"]
    schedule = [(split, origin) for split in ("validation", "test") for origin in measurement[split + "_origins"]]
    checks.exact("folds.length", len(report["folds"]), len(schedule))
    all_model_rows, oracle_folds, previous_risk = {}, [], None
    model_hashes = {name: record["content_hash"] for name, record in models.items()}
    available = [name for name in MODELS if name in MODELS[:3]
                 or (name == "training_prevalence" and training["prevalence"] is not None)
                 or (name in models and models[name]["status"] == "FITTED")]
    for index, ((split, origin), actual) in enumerate(zip(schedule, report["folds"])):
        label = f"folds[{index}]"
        history = tuple(row for row in rows if row[3] < origin)
        features, probabilities = feature_snapshot(history, origin, protocol)
        target = tuple(row for row in rows if origin <= row[3] < origin + measurement["horizon"])
        positive = {row[1:3] for row in target if row[1] != row[2]}
        risk = set(probabilities)
        values = {name: [] for name in MODELS}
        for item in features["rows"]:
            pair = item["source"], item["target"]
            outcome = int(pair in positive)
            probabilities[pair]["training_prevalence"] = training["prevalence"]
            for name, model in models.items():
                if model["status"] == "FITTED":
                    probabilities[pair][name] = fitted_probability(item, model)
            for name in available:
                values[name].append((probabilities[pair][name], outcome))
        all_model_rows[origin] = values
        risk_change = {"risk_set_hash": digest(sorted(risk)),
                       "compared_with_previous_planned_origin": previous_risk is not None,
                       "retained_pairs": len(risk & previous_risk) if previous_risk is not None else None,
                       "new_pairs": len(risk - previous_risk) if previous_risk is not None else None,
                       "removed_pairs": len(previous_risk - risk) if previous_risk is not None else None}
        expected = {"origin_at_seconds": origin, "target_end_seconds": origin + measurement["horizon"],
                    "feature_hash": features["content_hash"], "fitted_model_hashes": model_hashes,
                    "available_models": available, "risk_pairs": len(risk),
                    "archive_positive_pairs": len(risk & positive), "archive_negative_pairs": len(risk - positive),
                    "target_row_count": len(target), "target_positive_pairs_outside_risk": len(positive - risk),
                    "target_rows_hash": digest(target), "always_zero_brier": len(risk & positive) / len(risk) if risk else None,
                    "split": split, "history_rows_hash": digest(history), "history_row_count": len(history),
                    "batch_replay_feature_hash_equal": True, "risk_change": risk_change,
                    "models": {}, "probability_diagnostics": {}}
        for name in MODELS:
            expected["models"][name], expected["probability_diagnostics"][name] = scores(values[name], edges, name in available)
        checks.exact(label + ".forecast_hash_format", bool(_SHA.fullmatch(actual["forecast_hash"])), True)
        for key, value in expected.items():
            checks.tree(label + "." + key, actual[key], value)
        oracle_folds.append(expected)
        previous_risk = risk
    for split in ("validation", "test"):
        selected = [fold for fold in oracle_folds if fold["split"] == split]
        checks.tree("splits." + split, report["splits"][split], split_summary(selected, all_model_rows, edges))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "protocol", "case_report", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    # Require the completed report before reading raw rows: this program never pilots a study.
    report, report_sha = read_json(args.case_report)
    protocol, protocol_sha = read_json(args.protocol)
    if digest(protocol) != PROTOCOL_HASH:
        raise ValueError("protocol differs from the pre-acquisition frozen plan")
    rows, audit = read_archive(args.archive, protocol)
    checks = check_report(rows, audit, protocol, report)
    result = {
        "schema": "sociolab.archive-network-independent-check.v1",
        "status": "PASS" if not checks.mismatches else "FAIL",
        "protocol_content_hash": digest(protocol), "protocol_file_sha256": protocol_sha,
        "protocol_freeze_commit": FREEZE_COMMIT, "source_compressed_sha256": audit["compressed_sha256"],
        "source_payload_sha256": audit["payload_sha256"], "case_report_file_sha256": report_sha,
        "case_report_content_hash": report["content_hash"],
        "checker_file_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "exact_comparisons": checks.exact_count, "numeric_comparisons": checks.numeric_count,
        "absolute_numeric_tolerance": ABSOLUTE_TOLERANCE,
        "maximum_absolute_numeric_difference": checks.maximum_difference,
        "mismatch_count": len(checks.mismatches), "mismatches": checks.mismatches,
        "scope": {
            "stdlib_only": True, "sociolab_or_sklearn_imported": False, "upstream_solver_refitted": False,
            "optimizer_solution_independently_verified": False,
            "source_counts_and_training_labels_reconstructed": True,
            "training_and_history_feature_hashes_reconstructed": True,
            "population_scaler_mean_variance_scale_checked": True,
            "saved_coefficient_scalar_sigmoid_checked_against_aggregate_results": True,
            "exact_private_forecast_hash_reconstructed": False,
            "private_individual_prediction_rows_available": False,
            "private_forecast_hash_format_and_model_identity_only": True,
            "baseline_numeric_oracle": "1-exp(-rate_times_horizon)",
            "expm1_used_only_for_exact_baseline_identity_inside_feature_hash": True,
            "raw_source_or_private_predictions_written": False,
            "real_coverage_calibration_or_causality_verified": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "exact_comparisons", "numeric_comparisons", "mismatch_count",
                                                 "maximum_absolute_numeric_difference")}, allow_nan=False))
    if checks.mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
