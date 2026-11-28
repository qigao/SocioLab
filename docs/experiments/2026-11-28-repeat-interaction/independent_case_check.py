"""Independent stdlib closed-form expectations for the fixed fictional case."""

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def check_case(directory):
    largest_error = 0.0

    def require(condition, message):
        if not condition:
            raise ValueError("independent expectation failed: " + message)

    def close(actual, expected):
        nonlocal largest_error
        require(type(actual) in (int, float) and math.isfinite(actual), "finite numeric result")
        error = abs(actual - expected)
        largest_error = max(largest_error, error)
        require(error <= 1e-12, "closed-form agreement")

    def valid_hash(value):
        raw = json.dumps({k: v for k, v in value.items() if k != "content_hash"},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        require(value["content_hash"] == "sha256:" + sha256(raw).hexdigest(), "canonical artifact hash")

    forecast = read(directory / "forecast.json")
    valid_hash(forecast)
    authored = {("A", "B"): (3, 1, 1), ("A", "C"): (1, 0, 15), ("B", "D"): (2, 1, 5)}
    predictions = {(p["source"], p["target"]): p for p in forecast["predictions"]}
    require(set(predictions) == set(authored), "exact fixed historical risk set")
    probabilities = {}
    for pair, (n, recent, age) in authored.items():
        actual = predictions[pair]
        require((actual["history_count"], actual["recent_count"], actual["last_event_age"]) == (n, recent, age), "history/recent counts and age")
        probabilities[pair] = {"historical_poisson": 1 - math.exp(-n * 10 / 20),
                               "recent_poisson": 1 - math.exp(-recent * 10 / 5),
                               "recent_occurrence": float(recent > 0)}
        for model, expected in probabilities[pair].items():
            close(actual["probabilities"][model], expected)
    ab, ac, bd = ("A", "B"), ("A", "C"), ("B", "D")
    scenarios = {
        "complete": ({ab: 1, ac: 0, bd: 1}, 2, {}, "SCORED"),
        "incomplete": ({}, 2, {"followup_not_closed": 3}, "UNSCORED"),
        "partial": ({ab: 1}, 3, {"coverage_incomplete": 1, "membership_not_full_horizon": 1}, "PARTIALLY_SCORED"),
        "restored": ({ab: 1, ac: 1}, 3, {"membership_not_full_horizon": 1}, "PARTIALLY_SCORED"),
        "retracted": ({ab: 1, ac: 0}, 2, {"membership_not_full_horizon": 1}, "PARTIALLY_SCORED"),
    }
    score_hashes = []
    for name, (labels, positive, reasons, status) in scenarios.items():
        score = read(directory / ("score-" + name + ".json"))
        valid_hash(score)
        require(score["forecast_hash"] == forecast["content_hash"], "same frozen prediction across targets")
        n, scored_positive = len(labels), sum(labels.values())
        require(score["status"] == status, "scenario status")
        require(score["counts"] == {"risk_pairs": 3, "scorable_pairs": n, "unscored_pairs": 3-n,
            "known_positive_pairs": positive, "scorable_positive_pairs": scored_positive,
            "scorable_negative_pairs": n-scored_positive, "known_positive_unscored_pairs": positive-scored_positive}, "scenario evidence/scoring counts")
        require(score["unscored_reasons"] == {k: reasons.get(k, 0) for k in (
            "followup_not_closed", "membership_unknown", "membership_not_full_horizon", "coverage_incomplete")}, "exclusive exclusion reasons")
        for model, values in score["models"].items():
            require(values["n"] == n and values["status"] == ("SCORED" if n else "UNSCORED"), "same model scoring population")
            if not n:
                require(all(values[k] is None for k in ("brier", "mean_predicted_probability", "observed_fraction")), "null metrics without outcomes")
            else:
                close(values["brier"], sum((probabilities[p][model]-y)**2 for p, y in labels.items())/n)
                close(values["mean_predicted_probability"], sum(probabilities[p][model] for p in labels)/n)
                close(values["observed_fraction"], scored_positive/n)
        score_hashes.append(score["content_hash"])
    require(len(set(score_hashes)) == len(scenarios), "separately bound target-version scores")
    require((directory/"forecast.json").read_bytes() == (directory/"forecast-replayed.json").read_bytes(), "old forecast byte replay after appends")
    require((directory/"score-partial.json").read_bytes() == (directory/"score-partial-replayed.json").read_bytes(), "old target-cutoff score byte replay")
    target = read(directory/"target-window.snapshot.json")
    require({(e["source"], e["target"], e["strength"]) for e in target["edges"]} == {("A", "B", 1), ("B", "D", 1)}, "target includes tick20 and excludes tick30")
    empty = read(directory/"empty-window.snapshot.json")
    active, ended = (read(directory/name) for name in ("active-state.snapshot.json", "ended-state.snapshot.json"))
    require(empty["coverage"]["complete"] and not empty["edges"], "complete empty recent communication window")
    require(active["coverage"]["complete"] and len(active["edges"]) == 1 and active["edges"][0]["strength"] == 1, "independently active relationship")
    require(ended["coverage"]["complete"] and not ended["edges"], "explicit zero terminates state edge")
    return {"kind": "INDEPENDENT_FICTIONAL_REPEAT_INTERACTION_CHECK", "status": "PASS",
            "method": "stdlib authored scenario labels and closed-form probability/Brier arithmetic",
            "scenario_names": list(scenarios), "risk_pair_count": 3, "model_count": 3,
            "maximum_absolute_numeric_error": largest_error,
            "old_forecast_byte_replay": True, "old_score_byte_replay": True,
            "half_open_target_boundary_verified": True, "event_expiry_separate_from_relation_zero": True,
            "sociolab_imported": False, "model_fitted": False, "real_source_qualified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check_case(args.directory)
    with args.output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(report, sort_keys=True))
