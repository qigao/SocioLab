#!/usr/bin/env python3
"""Check the fixed receipt-cutoff evaluation case without importing SocioLab.

This standard-library checker verifies retained input bindings, raw receipt
admission gates, revision summaries and saved-prediction loss arithmetic. It
does not rebuild snapshots, fit coefficients, or authenticate source timestamps.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import sys


REPOSITORY = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL_SHA256 = "e7ade770148d1166d2853b540cd3d55aa34d4527166621636d569be6dc16e485"
MODELS = ("persistence", "own_lag_ols", "network_lag_ols")
BASELINES = {"network_vs_own": "own_lag_ols", "network_vs_persistence": "persistence"}
ATOL = RTOL = 1e-12


class CheckError(ValueError):
    """Only fixed error labels may be emitted; never include private values."""


def require(value, label):
    if not value:
        raise CheckError(label)


def digest(raw):
    return sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value):
    return "sha256:" + digest(canonical(value))


def without_hash(value, field="content_hash"):
    return {key: item for key, item in value.items() if key != field}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def invalid_constant(_value):
    raise CheckError("NONFINITE_JSON_NUMBER")


def load(path):
    raw = path.read_bytes()
    require(0 < len(raw) < 20_000_000, "JSON_SIZE")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    canonical(value)
    return value, raw


class Audit:
    def __init__(self):
        self.count = self.numeric_count = 0
        self.max_absolute_error = 0.0

    def exact(self, actual, expected, label):
        self.count += 1
        require(canonical(actual) == canonical(expected), label)

    def condition(self, value, label):
        self.count += 1
        require(value, label)

    def hashed(self, value, label, field="content_hash"):
        self.exact(value[field], content_hash(without_hash(value, field)), label)

    def compare(self, actual, expected, label):
        if type(expected) is dict:
            self.condition(type(actual) is dict and set(actual) == set(expected), label + ".FIELDS")
            for key in sorted(expected):
                self.compare(actual[key], expected[key], label + "." + key)
        elif type(expected) is float:
            self.condition(type(actual) in (int, float) and math.isfinite(actual), label + ".FINITE")
            self.numeric_count += 1
            self.max_absolute_error = max(self.max_absolute_error, abs(actual - expected))
            self.condition(math.isclose(actual, expected, abs_tol=ATOL, rel_tol=RTOL), label + ".VALUE")
        else:
            self.exact(actual, expected, label)


def prefix(journal, cutoff):
    require(type(cutoff) is int and 0 < cutoff <= len(journal["records"]), "PREFIX_CUTOFF")
    records = journal["records"][:cutoff]
    heads, first, seen = {}, {}, set()
    for sequence, record in enumerate(records, 1):
        require(record["ingest_seq"] == sequence and record["record_id"] not in seen, "RECEIPT_SEQUENCE")
        key = (record["source"]["system"], record["fact_id"])
        preceding = heads.get(key)
        require(record["supersedes"] == (None if preceding is None else preceding["record_id"]), "FACT_CHAIN")
        require(record["operation"] in ("assert", "retract"), "FACT_OPERATION")
        require(preceding is None or preceding["kind"] == record["kind"], "FACT_KIND")
        first.setdefault(key, sequence)
        heads[key] = record
        seen.add(record["record_id"])
    active = {record["record_id"]: record for record in heads.values() if record["operation"] == "assert"}
    envelope = {key: value for key, value in journal.items() if key != "records"}
    return records, active, first, content_hash({**envelope, "records": records})


def gates(journal, specification, target_evidence, history_cutoff, target_cutoff, target_at, audit):
    """Check all raw assertions, including superseded/retracted/invalid values."""
    require(journal["clock"]["kind"] == "ticks", "FIXTURE_TICK_CLOCK_REQUIRED")
    records, _, _, _ = prefix(journal, history_cutoff)
    source = specification["behavior_source"]
    for record in records:
        if record["kind"] != "actor.attribute.observed" or record["operation"] != "assert":
            continue
        payload = record["payload"]
        if record["source"]["system"] != source["system"] or payload["name"] != source["attribute"]:
            continue
        interval = record["valid_interval"]
        future = record["occurred_at"] >= target_at or (
            interval is not None and (interval[1] is None or interval[1] > target_at))
        audit.condition(not future, "RAW_ASSERTION_FUTURE_STREAM_GATE")
    _, _, first, _ = prefix(journal, target_cutoff)
    for row in target_evidence:
        record = row["record"]
        key = (record["source"]["system"], record["fact_id"])
        audit.condition(first[key] > history_cutoff, "TARGET_FACT_ANCESTRY_GATE")


def history_revision(before, after, previous_target):
    old, new = before["waves"], after["waves"][:-1]
    require(len(old) == len(new), "EXPANDING_HISTORY_LENGTH")
    require([wave["time_index"] for wave in old] == [wave["time_index"] for wave in new], "EXPANDING_HISTORY_TIMES")
    clean = lambda waves: [{key: wave[key] for key in ("time_index", "edges", "behavior")} for wave in waves]
    edge_changes = [len({tuple(edge) for edge in left["edges"]} ^ {tuple(edge) for edge in right["edges"]})
                    for left, right in zip(old, new)]
    return {
        "overlap_wave_count": len(old),
        "behavior_changed_wave_count": sum(left["behavior"] != right["behavior"] for left, right in zip(old, new)),
        "behavior_changed_actor_wave_count": sum(left["behavior"][actor] != right["behavior"][actor]
                                                 for left, right in zip(old, new) for actor in before["actors"]),
        "network_changed_wave_count": sum(count > 0 for count in edge_changes),
        "network_changed_edge_wave_count": sum(edge_changes),
        "source_revision_changed_wave_count": sum(left["source_revision"] != right["source_revision"] for left, right in zip(old, new)),
        "old_waves_before_hash": content_hash(clean(old)), "old_waves_after_hash": content_hash(clean(new)),
        "previous_target_comparison": {
            "target_time_index": previous_target["time_index"],
            "changed_actor_count": sum(previous_target["behavior"][actor] != after["waves"][-1]["behavior"][actor]
                                       for actor in before["actors"]),
            "prior_target_behavior_hash": content_hash(previous_target["behavior"]),
            "appended_behavior_hash": content_hash(after["waves"][-1]["behavior"]),
        },
    }


def loss(errors):
    require(bool(errors), "EMPTY_LOSS")
    result = {"mae": math.fsum(abs(error) for error in errors) / len(errors),
              "rmse": math.sqrt(math.fsum(error * error for error in errors) / len(errors))}
    require(all(math.isfinite(value) for value in result.values()), "NONFINITE_LOSS")
    return result


def score_arrays(forecast, target, audit):
    actors = forecast["actors"]
    require(set(target["behavior"]) == set(actors), "SCORE_ROSTER")
    scale = forecast["specification"]["behavior"]
    models, errors = {}, {}
    for name in MODELS:
        model = forecast["models"][name]
        require(model["status"] in ("OK", "NOT_ESTIMABLE"), "MODEL_STATUS")
        available = model["status"] == "OK"
        if available:
            raw, clipped = model["raw_predictions"], model["clipped_predictions"]
            require(all(type(values) is list and len(values) == len(actors) and
                        all(type(value) in (int, float) and math.isfinite(value) for value in values)
                        for values in (raw, clipped)), "PREDICTION_ARRAY")
            audit.exact([float(value) for value in clipped],
                        [min(max(float(value), float(scale["minimum"])), float(scale["maximum"])) for value in raw], "CLIPPING")
            errors[name] = {variant: [float(value) - target["behavior"][actor] for actor, value in zip(actors, values)]
                            for variant, values in (("raw", raw), ("clipped", clipped))}
            count = sum(a != b for a, b in zip(raw, clipped))
            audit.exact(model["clipping_count"], count, "CLIPPING_COUNT")
        else:
            require(all(model[key] is None for key in ("raw_predictions", "clipped_predictions", "clipping_count")), "UNAVAILABLE_ARRAY")
            errors[name], count = None, None
        models[name] = {"status": model["status"], "reason": model["reason"], "n_evaluated": len(actors) if available else 0,
                        "clipping_count": count, **{variant: loss(errors[name][variant]) if available else None for variant in ("raw", "clipped")}}
    return models, errors


def summaries(scores, error_arrays, times, actor_count):
    def coverage(names):
        failed = [time for time, score in zip(times, scores) if any(score[name]["status"] != "OK" for name in names)]
        return {"expected_fold_count": len(times), "available_fold_count": len(times) - len(failed),
                "expected_actor_forecast_count": actor_count * len(times),
                "available_actor_forecast_count": actor_count * (len(times) - len(failed)), "failed_target_time_indices": failed}

    models = {}
    for name in MODELS:
        covered = coverage((name,))
        complete = not covered["failed_target_time_indices"]
        variants = {}
        for variant in ("raw", "clipped"):
            variants[variant] = ({"pooled": loss([error for fold in error_arrays for error in fold[name][variant]]),
                                  "macro": {metric: math.fsum(score[name][variant][metric] for score in scores) / len(scores)
                                            for metric in ("mae", "rmse")}} if complete else None)
        models[name] = {"status": "OK" if complete else "NOT_ESTIMABLE",
                        "reason": None if complete else "not_estimable_in_all_planned_folds", **covered,
                        "clipping_count": sum(score[name]["clipping_count"] for score in scores) if complete else None, **variants}
    comparisons = {}
    for name, baseline in BASELINES.items():
        covered = coverage(("network_lag_ols", baseline))
        complete = not covered["failed_target_time_indices"]
        comparisons[name] = {
            "status": "OK" if complete else "NOT_ESTIMABLE", "reason": None if complete else "required_model_not_estimable_in_all_planned_folds",
            **covered, "direction": "network_minus_baseline_negative_favors_network",
            **{variant: {aggregation: {metric + "_difference": models["network_lag_ols"][variant][aggregation][metric]
                                      - models[baseline][variant][aggregation][metric] for metric in ("mae", "rmse")}
                          for aggregation in ("pooled", "macro")} if complete else None for variant in ("raw", "clipped")},
        }
    return models, comparisons


def evidence_binding(proof, journal, cutoff, audit):
    records, active, _, prefix_hash = prefix(journal, cutoff)
    audit.exact(proof["knowledge_cutoff"], cutoff, "EVIDENCE_CUTOFF")
    audit.exact(proof["prefix_content_hash"], prefix_hash, "EVIDENCE_PREFIX_HASH")
    audit.exact(proof["prefix_records_hash"], content_hash(records), "EVIDENCE_RECORDS_HASH")
    audit.exact(proof["prefix_envelope"], without_hash(journal, "records"), "EVIDENCE_ENVELOPE")
    return active


def selected_behavior(evidence, active, specification, at, behavior, audit):
    expected = {}
    for item in evidence:
        record, actor = item["record"], item["resolved_actor"]
        audit.exact(record, active[record["record_id"]], "SELECTED_EFFECTIVE_RECORD")
        audit.exact(record["kind"], "actor.attribute.observed", "SELECTED_KIND")
        audit.exact(record["source"]["system"], specification["behavior_source"]["system"], "SELECTED_SYSTEM")
        audit.exact(record["payload"]["name"], specification["behavior_source"]["attribute"], "SELECTED_ATTRIBUTE")
        audit.exact(record["occurred_at"], at, "SELECTED_POINT_TIME")
        audit.exact(record["valid_interval"], None, "SELECTED_POINT_ONLY")
        require(actor not in expected and type(record["payload"]["value"]) is int, "SELECTED_UNIQUE_INTEGER")
        expected[actor] = record["payload"]["value"]
    audit.exact(set(expected) == set(specification["actors"]), True, "SELECTED_ROSTER")
    audit.exact(expected, behavior, "SELECTED_BEHAVIOR_VALUES")


def history_binding(bundle, journal, specification, forecast, audit):
    audit.hashed(bundle, "HISTORY_BUNDLE_HASH")
    audit.exact(bundle["specification"], specification, "HISTORY_SPECIFICATION")
    history, proof = bundle["history"], bundle["provenance"]
    cutoff = specification["knowledge_cutoff"]
    active = evidence_binding(proof, journal, cutoff, audit)
    audit.exact(proof["receipt_records"], journal["records"][:cutoff], "HISTORY_RECEIPT_PREFIX")
    audit.exact(history["actors"], specification["actors"], "HISTORY_ROSTER")
    audit.exact(len(history["waves"]), len(specification["waves"]), "HISTORY_WAVE_COUNT")
    audit.exact(len(proof["waves"]), len(history["waves"]), "HISTORY_MANIFEST_COUNT")
    for wave, manifest, coordinate in zip(history["waves"], proof["waves"], specification["waves"]):
        audit.hashed(manifest, "WAVE_MANIFEST_HASH", "manifest_hash")
        audit.exact(wave["source_revision"], manifest["manifest_hash"], "WAVE_REVISION_BINDING")
        audit.exact(wave["time_index"], coordinate["time_index"], "WAVE_INDEX")
        audit.exact(manifest["at"], coordinate["at"], "WAVE_SOURCE_TIME")
        audit.exact(manifest["knowledge_cutoff"], cutoff, "WAVE_CUTOFF")
        audit.exact(manifest["prefix_content_hash"], proof["prefix_content_hash"], "WAVE_PREFIX")
        snapshot = manifest["snapshot"]
        audit.hashed(snapshot, "SNAPSHOT_CONTENT_HASH")
        audit.exact(snapshot["dataset"]["content_hash"], proof["prefix_content_hash"], "SNAPSHOT_PREFIX")
        audit.exact(snapshot["coverage"]["complete"], True, "COMPLETE_HISTORY")
        audit.exact(snapshot["persons"], history["actors"], "SNAPSHOT_ROSTER")
        audit.exact(wave["edges"], [[edge["source"], edge["target"]] for edge in snapshot["edges"]], "PANEL_SNAPSHOT_BINDING")
        require(all(edge["strength"] == 1 for edge in snapshot["edges"]), "UNIT_STRENGTH_HISTORY")
        selected_behavior(manifest["behavior_evidence"], active, specification, coordinate["at"], wave["behavior"], audit)
    audit.hashed(forecast, "FORECAST_CONTENT_HASH")
    audit.exact(forecast["actors"], history["actors"], "FORECAST_ROSTER")
    audit.exact(forecast["specification"], specification["forecast_specification"], "FORECAST_SPECIFICATION")
    audit.exact(forecast["specification_hash"], content_hash(forecast["specification"]), "FORECAST_SPECIFICATION_HASH")
    times = [wave["time_index"] for wave in history["waves"]]
    audit.exact(forecast["history"], {
        "content_hash": content_hash(history), "wave_time_indices": times,
        "wave_source_revisions": [wave["source_revision"] for wave in history["waves"]],
        "origin_time_index": times[-1], "wave_gap": times[1] - times[0], "transition_count": len(times) - 1,
    }, "FORECAST_HISTORY_BINDING")
    return history


def target_binding(bundle, target, journal, specification, forecast, history_bundle, cutoff, audit):
    audit.hashed(bundle, "TARGET_BUNDLE_HASH")
    audit.exact(bundle["target"], target, "SAVED_TARGET_BINDING")
    audit.exact(bundle["forecast_hash"], forecast["content_hash"], "TARGET_FORECAST_BINDING")
    audit.exact(bundle["history_bundle_hash"], history_bundle["content_hash"], "TARGET_HISTORY_BINDING")
    proof = bundle["provenance"]
    active = evidence_binding(proof, journal, cutoff, audit)
    audit.hashed(proof, "TARGET_MANIFEST_HASH", "manifest_hash")
    audit.exact(target["source_revision"], proof["manifest_hash"], "TARGET_REVISION_BINDING")
    audit.exact(proof["history_knowledge_cutoff"], specification["knowledge_cutoff"], "TARGET_ISSUANCE_CUTOFF")
    audit.exact(target["time_index"], specification["forecast_specification"]["target_time_index"], "TARGET_INDEX")
    selected_behavior(proof["behavior_evidence"], active, specification, specification["target_at"], target["behavior"], audit)
    gates(journal, specification, proof["behavior_evidence"], specification["knowledge_cutoff"], cutoff, specification["target_at"], audit)


def check(private, public):
    audit = Audit()
    protocol, protocol_raw = load(EXPERIMENT / "protocol.json")
    require(PROTOCOL_SHA256 is not None, "PROTOCOL_NOT_FROZEN")
    audit.exact(digest(protocol_raw), PROTOCOL_SHA256, "PROTOCOL_HASH")
    execution, execution_raw = load(public / "execution.json")
    public_report, public_report_raw = load(public / "report.json")
    audit.exact(execution["protocol_sha256"], PROTOCOL_SHA256, "EXECUTION_PROTOCOL_HASH")
    audit.exact(execution["source_hashes_at_start"], execution["source_hashes_at_finish"], "SOURCE_HASHES_UNCHANGED")
    for relative, expected in execution["source_hashes_at_start"].items():
        path = (REPOSITORY / relative).resolve()
        require(path.is_relative_to(REPOSITORY), "SOURCE_PATH")
        audit.exact(digest(path.read_bytes()), expected, "SOURCE_FILE_HASH")
    for relative, expected in protocol["input_file_sha256"].items():
        audit.exact(digest((REPOSITORY / relative).read_bytes()), expected, "FIXTURE_FILE_HASH")
    paths = {path.name: path for path in private.glob("*.json")}
    hashes = {name: digest(path.read_bytes()) for name, path in paths.items()}
    audit.exact(hashes, execution["private_input_file_sha256"], "PRIVATE_FILE_INVENTORY")
    audit.exact(hashes, execution["creation_file_sha256"], "PRIVATE_CREATION_HASHES")
    values = {name: load(path)[0] for name, path in paths.items()}
    for name, expected in execution["public_file_sha256"].items():
        require(Path(name).name == name, "PUBLIC_FILE_NAME")
        audit.exact(digest((public / name).read_bytes()), expected, "PUBLIC_FILE_HASH")
        if name in hashes:
            audit.exact(expected, hashes[name], "PRIVATE_PUBLIC_BYTES")
    journal = values["journal-revised_target.json"]
    require(journal["origin"] == "synthetic" and journal["clock"]["kind"] == "ticks", "FIXTURE_SCOPE")
    for stage, cutoff in zip(("initial", "target_first", "second_history", "target_second", "revised_target"), (24, 28, 36, 40, 41)):
        earlier = values[f"journal-{stage}.json"]
        audit.exact(earlier, {**without_hash(journal, "records"), "records": journal["records"][:cutoff]}, "APPEND_ONLY_JOURNAL")
        prefix(earlier, cutoff)
    plans = {label: values[f"plan-{label}.json"] for label in ("original", "revised-target")}
    changed = json.loads(canonical(without_hash(plans["original"])))
    changed["schedule"]["folds"][0]["target_knowledge_cutoff"] = 41
    audit.exact(without_hash(plans["revised-target"]), changed, "TWO_DECLARED_TARGET_VERSION_PLANS")
    audit.exact(plans["original"]["schedule"], {"schema": "sociolab.journal-forecast-schedule.v1", "folds": [
        {"target_time_index": 2, "target_at": 20, "history_knowledge_cutoff": 24, "target_knowledge_cutoff": 28},
        {"target_time_index": 3, "target_at": 30, "history_knowledge_cutoff": 36, "target_knowledge_cutoff": 40},
    ]}, "FIXED_ORIGINAL_SCHEDULE")
    audit.exact(hashes["evaluation-original.json"], hashes["evaluation-original-replay.json"], "OLD_PLAN_REPORT_REPLAY_BYTES")
    forecasts = [values[f"forecast-{time}.json"] for time in (2, 3)]
    histories = [values[f"history-{time}.bundle.json"] for time in (2, 3)]
    evaluated, recalculated = {}, {}
    for label, plan in plans.items():
        audit.hashed(plan, "PLAN_CONTENT_HASH")
        report = values[f"evaluation-{label}.json"]
        audit.hashed(report, "EVALUATION_CONTENT_HASH")
        audit.exact(report["plan_hash"], plan["content_hash"], "EVALUATION_PLAN_BINDING")
        audit.exact(plan["journal"], {
            "envelope": without_hash(journal, "records"), "initial_knowledge_cutoff": 24,
            "initial_prefix_hash": prefix(journal, 24)[3], "initial_history_bundle_hash": histories[0]["content_hash"],
            "initial_panel_hash": content_hash(histories[0]["history"]),
        }, "PLAN_INITIAL_PREFIX_BINDING")
        audit.exact(report["journal_envelope_hash"], content_hash(plan["journal"]["envelope"]), "REPORT_ENVELOPE_HASH")
        audit.exact(report["initial_prefix_hash"], plan["journal"]["initial_prefix_hash"], "REPORT_INITIAL_PREFIX")
        for field, expected in (("training_policy", "expanding_as_known_receipt_prefix"),
                                ("target_version_policy", "latest_effective_at_declared_target_cutoff"),
                                ("evaluation_policy", "all_planned_folds_fixed_roster")):
            audit.exact(plan[field], expected, "PLAN_POLICY")
            audit.exact(report[field], expected, "REPORT_POLICY")
        audit.exact(report["metrics"], plan["metrics"], "FIXED_METRICS")
        audit.exact([report["actor_count"], report["fold_count"], report["actor_forecast_count"]], [4, 2, 8], "COVERAGE_COUNTS")
        audit.exact(report["target_time_indices"], [2, 3], "REPORT_TARGETS")
        manifest = values[f"folds-{label}.json"]
        audit.exact(manifest, {"schema": "sociolab.journal-forecast-fold-manifest.v1", "folds": [
            {"forecast": "forecast-2.json", "target": f"target-2-{label}.json"},
            {"forecast": "forecast-3.json", "target": "target-3-original.json"},
        ]}, "MANIFEST_SAME_FORECASTS_FIXED_TARGETS")
        scores, errors, previous_history, previous_target = [], [], None, None
        audit.exact(len(report["folds"]), 2, "FOLD_COUNT")
        for index, (schedule, retained, forecast, history_bundle) in enumerate(zip(plan["schedule"]["folds"], report["folds"], forecasts, histories)):
            spec = json.loads(canonical(plan["initial_specification"]))
            spec.update(knowledge_cutoff=schedule["history_knowledge_cutoff"], target_at=schedule["target_at"])
            spec["forecast_specification"]["target_time_index"] = schedule["target_time_index"]
            spec["waves"].extend({"time_index": prior["target_time_index"], "at": prior["target_at"]} for prior in plan["schedule"]["folds"][:index])
            history = history_binding(history_bundle, journal, spec, forecast, audit)
            time, variant = schedule["target_time_index"], label if index == 0 else "original"
            audit.exact(values[f"history-{time}.json"], history, "SAVED_HISTORY_PANEL")
            audit.exact(values[f"history-{time}.spec.json"], spec, "SAVED_HISTORY_SPEC")
            target = values[f"target-{time}-{variant}.json"]
            target_bundle = values[f"target-{time}-{variant}.bundle.json"]
            target_binding(target_bundle, target, journal, spec, forecast, history_bundle, schedule["target_knowledge_cutoff"], audit)
            expected_fields = {
                "fold_index": index + 1, "origin_time_index": history["waves"][-1]["time_index"],
                "origin_at": spec["waves"][-1]["at"], "target_time_index": time, "target_at": spec["target_at"],
                "history_knowledge_cutoff": spec["knowledge_cutoff"], "target_knowledge_cutoff": schedule["target_knowledge_cutoff"],
                "history_journal_prefix_hash": prefix(journal, spec["knowledge_cutoff"])[3],
                "target_journal_prefix_hash": prefix(journal, schedule["target_knowledge_cutoff"])[3],
                "history_bundle_hash": history_bundle["content_hash"], "history_panel_hash": content_hash(history),
                "forecast_hash": forecast["content_hash"], "target_hash": content_hash(target),
                "history_revision": None if index == 0 else history_revision(previous_history, history, previous_target),
            }
            audit.exact(without_hash(without_hash(retained, "score"), "score_hash"), expected_fields, "FOLD_BINDINGS_AND_REVISIONS")
            score = values[f"score-{time}-{variant}.json"]
            audit.exact(retained["score"], score, "SEPARATELY_SAVED_SCORE")
            audit.exact(retained["score_hash"], content_hash(score), "SCORE_HASH")
            for field, expected in (("forecast_hash", forecast["content_hash"]), ("target_behavior_hash", content_hash(target)),
                                    ("target_source_revision", target["source_revision"]), ("history_prefix_hash", content_hash(history)),
                                    ("specification_hash", forecast["specification_hash"]), ("target_time_index", time), ("actor_count", 4)):
                audit.exact(score[field], expected, "SCORE_INPUT_BINDING")
            computed, individual_errors = score_arrays(forecast, target, audit)
            audit.compare(score["models"], computed, "FOLD_MODELS")
            for comparison, baseline in BASELINES.items():
                available = computed["network_lag_ols"]["status"] == computed[baseline]["status"] == "OK"
                expected = {"status": "OK" if available else "NOT_ESTIMABLE", "reason": None if available else "required_forecast_not_estimable",
                            "n_evaluated": 4 if available else 0, "direction": "network_minus_baseline_negative_favors_network",
                            **{variant: {metric + "_difference": computed["network_lag_ols"][variant][metric] - computed[baseline][variant][metric]
                                         for metric in ("mae", "rmse")} if available else None for variant in ("raw", "clipped")}}
                audit.compare(score["comparisons"][comparison], expected, "FOLD_COMPARISON")
            scores.append(computed)
            errors.append(individual_errors)
            previous_history, previous_target = history, target
        models, comparisons = summaries(scores, errors, [2, 3], 4)
        audit.compare(report["models"], models, "POOLED_MACRO_MODELS")
        audit.compare(report["comparisons"], comparisons, "POOLED_MACRO_COMPARISONS")
        for field in ("historical_as_of_availability_verified", "receipt_timestamps_externally_authenticated",
                      "forecast_issued_before_target_observation_verified", "refitting_performed_by_evaluation",
                      "future_receipt_records_consumed_at_plan_creation",
                      "target_network_materialized", "previous_target_equals_next_history_required", "causal_effect_identified", "empirical_forecast_validated"):
            audit.exact(report["scope"][field], False, "QUALIFICATION_SCOPE")
        for field in ("history_raw_assertion_future_stream_gate_enforced", "target_fact_ancestry_gate_enforced", "saved_targets_matched_journal_reconstruction"):
            audit.exact(report["scope"][field], True, "GATE_SCOPE")
        evaluated[label], recalculated[label] = report, {"models": models, "comparisons": comparisons}
    original, revised = evaluated["original"], evaluated["revised-target"]
    audit.exact([row["forecast_hash"] for row in original["folds"]], [row["forecast_hash"] for row in revised["folds"]], "SAME_SAVED_FORECASTS")
    audit.condition(original["folds"][0]["target_hash"] != revised["folds"][0]["target_hash"], "FIRST_TARGET_VERSION_CHANGED")
    audit.exact(original["folds"][1]["score"], revised["folds"][1]["score"], "SECOND_SCORE_UNCHANGED")
    audit.exact(public_report["history_revision_at_second_origin"], original["folds"][1]["history_revision"], "PUBLIC_REVISION_SUMMARY")
    for field in ("original_plan_replay_after_later_revision_byte_identical", "same_saved_forecasts_in_both_evaluations",
                  "all_private_json_artifacts_unchanged", "separately_saved_scores_match_evaluations", "target_versions_predeclared_before_forecasts"):
        audit.exact(public_report[field], True, "PUBLIC_ENGINEERING_CLAIM")
    audit.exact(public_report["private_json_artifact_count"], len(hashes), "PUBLIC_PRIVATE_FILE_COUNT")
    audit.exact(len(execution["steps"]), 20, "CLI_STEP_COUNT")
    for index, step in enumerate(execution["steps"], 1):
        audit.exact(step["order"], index, "CLI_STEP_ORDER")
        audit.exact(step["exit_code"], 0, "CLI_EXIT_CODE")
        audit.exact(step["stdout_sha256"], hashes[step["output_name"]], "CLI_OUTPUT_HASH")
        audit.exact(step["stderr_sha256"], digest(b""), "CLI_STDERR_HASH")
        audit.exact((private / f"step-{index:02d}.stderr.log").read_bytes().hex(), "", "CLI_STDERR_EMPTY")
    ordering = {step["output_name"]: step["order"] for step in execution["steps"]}
    audit.condition(max(ordering["plan-original.json"], ordering["plan-revised-target.json"]) < ordering["forecast-2.json"], "BOTH_PLANS_SAVED_BEFORE_PREDICTION")
    for time, stage in ((2, "target_first"), (3, "target_second")):
        audit.condition(ordering[f"forecast-{time}.json"] < ordering[f"journal-{stage}.json"], "PREDICTION_BEFORE_TARGET_IMPORT")
    for field, expected in (("case_runs", 1), ("automatic_retry", False), ("tuning_after_scores", False),
                            ("model_creation_steps", 2), ("evaluation_refits", 0), ("execution_order_authenticates_availability", False)):
        audit.exact(execution[field], expected, "EXECUTION_SCOPE")
    result = {
        "schema": "sociolab.independent-receipt-evaluation-check.v1", "kind": "INDEPENDENT_RECEIPT_EVALUATION_CHECK", "status": "PASS",
        "method": "stdlib_prefix_binding_gates_revision_counts_and_direct_error_pooling",
        "protocol_sha256": PROTOCOL_SHA256, "execution_file_sha256": digest(execution_raw), "report_file_sha256": digest(public_report_raw),
        "checker_sha256": digest(Path(__file__).read_bytes()), "private_file_sha256": hashes,
        "counts": {"checks": audit.count, "numeric_comparisons": audit.numeric_count, "plans": 2, "origins_per_plan": 2,
                   "actor_count": 4, "actor_forecast_count_per_plan": 8, "saved_forecasts": 2, "target_versions": 3, "cli_steps": 20},
        "numeric_comparison": {"max_absolute_error": audit.max_absolute_error, "absolute_tolerance": ATOL, "relative_tolerance": RTOL},
        "recomputed_aggregates": recalculated,
        "scope": {"sociolab_imported": False, "model_fitted_or_refitted": False, "snapshot_algorithm_reimplemented": False,
                  "coefficients_independently_validated": False, "raw_assertion_gate_checked": True, "fact_ancestry_gate_checked": True,
                  "individual_errors_pooled_directly": True, "real_data_used": False, "all_fixture_batches_known_before_execution": True,
                  "historical_as_of_availability_verified": False, "prospective_validation": False, "empirical_forecast_validated": False,
                  "causal_effect_identified": False, "hashes_authenticate_sources_or_times": False, "output": "aggregate_only"},
        "runtime": {"python": platform.python_version(), "third_party_dependencies": []},
    }
    result["content_hash"] = content_hash(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("private-directory", "public-directory", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    arguments = parser.parse_args()
    try:
        require(not arguments.output.exists(), "OUTPUT_ALREADY_EXISTS")
        result = check(arguments.private_directory.resolve(), arguments.public_directory.resolve())
        with arguments.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"status": "PASS", "checks": result["counts"]["checks"],
                          "max_absolute_error": result["numeric_comparison"]["max_absolute_error"]}, sort_keys=True))
        return 0
    except CheckError as error:
        print("independent check rejected: " + str(error), file=sys.stderr)
    except OSError:
        print("independent check rejected: FILE_ACCESS_ERROR", file=sys.stderr)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        print("independent check rejected: INVALID_INPUT_STRUCTURE_OR_ARITHMETIC", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
