#!/usr/bin/env python3
"""Run two declared receipt-version plans on the same invented forecasts.

All synthetic input batches, including future targets, are known beforehand.
This validates saved-artifact and version-selection behavior, not empirical or
prospective prediction. Existing outputs are never overwritten.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter


REPOSITORY = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
EXAMPLES = REPOSITORY / "examples/journal-evaluation"
PUBLIC_NAMES = (
    "evaluation-original.json", "evaluation-revised-target.json", "execution.json", "report.json",
    "score-2-original.json", "score-3-original.json", "score-2-revised-target.json",
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def aggregate_only(value, actors):
    if isinstance(value, str) and value in actors:
        raise ValueError("public output contains an actor identity")
    if isinstance(value, dict):
        if {"actors", "edges", "records", "raw_predictions", "clipped_predictions", "behavior_evidence"} & set(value):
            raise ValueError("public output contains individual records")
        for key, item in value.items():
            aggregate_only(key, actors)
            aggregate_only(item, actors)
    elif isinstance(value, list):
        for item in value:
            aggregate_only(item, actors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    private, output = args.private_directory.resolve(), args.output.resolve()
    if private.is_relative_to(REPOSITORY):
        parser.error("private artifacts must stay outside the repository")
    if private.is_relative_to(output) or output.is_relative_to(private):
        parser.error("private and public output directories must be separate")
    if private.exists() and (not private.is_dir() or any(private.iterdir())):
        parser.error("private directory must be fresh; saved artifacts are never overwritten")
    if output.exists() and not output.is_dir():
        parser.error("public output must be a directory")
    if any((output / name).exists() for name in PUBLIC_NAMES):
        parser.error("public output paths must be fresh")
    protocol_path = EXPERIMENT / "protocol.json"
    protocol = read(protocol_path)
    for relative, expected in protocol["input_file_sha256"].items():
        if digest(REPOSITORY / relative) != expected:
            parser.error("inputs differ from the fixed protocol")
    initial_spec = read(EXAMPLES / "initial-history.spec.json")
    schedules = {"original": read(EXAMPLES / "schedule.json"),
                 "revised-target": read(EXAMPLES / "revised-target.schedule.json")}
    if (read(EXAMPLES / "empty.events.json")["origin"] != "synthetic"
            or initial_spec["source_reference"] is not None or len(initial_spec["actors"]) != 4
            or len(initial_spec["waves"]) != 2):
        parser.error("this runner admits only its fixed invented four-person example")
    if protocol["stage_order"] != ["initial", "target_first", "second_history", "target_second", "revised_target"]:
        parser.error("the declared receipt schedule changed")
    expected = ((2, 20, 24, 28), (3, 30, 36, 40))
    actual = tuple(tuple(row[key] for key in ("target_time_index", "target_at", "history_knowledge_cutoff", "target_knowledge_cutoff"))
                   for row in schedules["original"]["folds"])
    if actual != expected:
        parser.error("the fixed original schedule changed")
    changed_schedule = deepcopy(schedules["original"])
    changed_schedule["folds"][0]["target_knowledge_cutoff"] = 41
    if schedules["revised-target"] != changed_schedule:
        parser.error("target sensitivity must change only the predeclared first target cutoff")
    sources = tuple(protocol["implementation_files"]) + tuple(protocol["input_file_sha256"]) + (
        "docs/experiments/2026-11-28-journal-evaluation/protocol.json",
        "docs/experiments/2026-11-28-journal-evaluation/run_receipt_evaluation.py",
    )
    source_before = {name: digest(REPOSITORY / name) for name in sources}
    private.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY / "src")
    environment["PYTHONHASHSEED"] = "0"
    frozen, steps, issuance_records, plan_records = {}, [], [], []
    actors = set(initial_spec["actors"]) | {"C_alias"}
    started, clock = now(), perf_counter()

    def save_private(name, value):
        path = private / name
        save(path, value)
        frozen[name] = digest(path)
        return path

    def execute(command, name):
        destination = private / name
        invocation = [sys.executable, "-m", "sociolab", *command]
        step_start, step_clock = now(), perf_counter()
        with destination.open("xb") as stream:
            result = subprocess.run(invocation, cwd=private, env=environment, stdout=stream,
                                    stderr=subprocess.PIPE, check=False)
        frozen[name] = digest(destination)
        step = {"order": len(steps) + 1, "command": invocation, "output_name": name,
                "started_at_utc": step_start, "finished_at_utc": now(),
                "wall_seconds": perf_counter() - step_clock, "exit_code": result.returncode,
                "stdout_sha256": frozen[name], "stderr_sha256": sha256(result.stderr).hexdigest(),
                "stderr_empty": not result.stderr}
        steps.append(step)
        with (private / f"step-{step['order']:02d}.stderr.log").open("xb") as stream:
            stream.write(result.stderr)
        if result.returncode or result.stderr:
            raise RuntimeError("receipt evaluation CLI failed; private stderr retained")
        return read(destination)

    def publish(name, value):
        aggregate_only(value, actors)
        with (output / name).open("xb") as stream:
            stream.write((private / name).read_bytes())

    def ingest(stage, previous):
        entry = protocol["stages"][stage]
        name = f"journal-{stage}.json"
        journal = execute(["events", "import", str(previous), str(EXAMPLES / entry["batch"]),
                           "--received-at", entry["received_at"]], name)
        if len(journal["records"]) != entry["knowledge_cutoff"]:
            raise ValueError("journal receipt count differs from the frozen batch schedule")
        return private / name

    def issue(journal, index):
        row = schedules["original"]["folds"][index]
        time = row["target_time_index"]
        target_stage = "target_first" if index == 0 else "target_second"
        if (private / f"journal-{target_stage}.json").exists():
            raise ValueError("the target batch was already ingested before its prediction")
        spec = deepcopy(initial_spec)
        spec["knowledge_cutoff"] = row["history_knowledge_cutoff"]
        for earlier in schedules["original"]["folds"][:index]:
            spec["waves"].append({"time_index": earlier["target_time_index"], "at": earlier["target_at"]})
        spec["target_at"] = row["target_at"]
        spec["forecast_specification"]["target_time_index"] = time
        spec_path = save_private(f"history-{time}.spec.json", spec)
        bundle = execute(["forecast", "journal-history", str(journal), str(spec_path)], f"history-{time}.bundle.json")
        panel_path = save_private(f"history-{time}.json", bundle["history"])
        forecast_spec = save_private(f"forecast-{time}.spec.json", spec["forecast_specification"])
        forecast = execute(["forecast", "create", str(panel_path), str(forecast_spec)], f"forecast-{time}.json")
        issuance_records.append({"target_time_index": time, "history_knowledge_cutoff": row["history_knowledge_cutoff"],
                                 "saved_at_utc": now(), "forecast_hash": forecast["content_hash"],
                                 "forecast_file_sha256": frozen[f"forecast-{time}.json"],
                                 "target_batch_not_yet_ingested": True})
        return spec_path, private / f"forecast-{time}.json", bundle, forecast

    def target_and_score(journal, spec_path, forecast_path, target_time, cutoff, label):
        bundle_name = f"target-{target_time}-{label}.bundle.json"
        bundle = execute(["forecast", "journal-target", str(journal), str(spec_path), str(forecast_path),
                          "--knowledge-cutoff", str(cutoff)], bundle_name)
        target_path = save_private(f"target-{target_time}-{label}.json", bundle["target"])
        score_name = f"score-{target_time}-{label}.json"
        score = execute(["forecast", "score", str(forecast_path), str(target_path)], score_name)
        publish(score_name, score)
        return target_path, bundle, score

    def evaluate(label, journal, manifest, *, replay=False):
        name = "evaluation-original-replay.json" if replay else f"evaluation-{label}.json"
        value = execute(["forecast", "journal-evaluate", str(private / f"plan-{label}.json"),
                         str(journal), str(manifest)], name)
        if not replay:
            publish(name, value)
        return value

    initial = ingest("initial", EXAMPLES / "empty.events.json")
    for label, file in (("original", "schedule.json"), ("revised-target", "revised-target.schedule.json")):
        if any(private.glob("forecast-[0-9]*.json")):
            raise ValueError("both target-version plans must be saved before prediction")
        name = f"plan-{label}.json"
        plan = execute(["forecast", "journal-plan", str(initial), str(EXAMPLES / "initial-history.spec.json"),
                        str(EXAMPLES / file)], name)
        plan_records.append({"label": label, "saved_at_utc": now(), "plan_hash": plan["content_hash"],
                             "plan_file_sha256": frozen[name], "before_first_prediction": True})
    first_spec, first_forecast, first_history, first_prediction = issue(initial, 0)
    first_target_journal = ingest("target_first", initial)
    first_target, _, first_score = target_and_score(first_target_journal, first_spec, first_forecast, 2, 28, "original")
    second_journal = ingest("second_history", first_target_journal)
    second_spec, second_forecast, second_history, second_prediction = issue(second_journal, 1)
    second_target_journal = ingest("target_second", second_journal)
    second_target, _, second_score = target_and_score(second_target_journal, second_spec, second_forecast, 3, 40, "original")
    entries = [{"forecast": first_forecast.name, "target": first_target.name},
               {"forecast": second_forecast.name, "target": second_target.name}]
    manifest = save_private("folds-original.json", {"schema": "sociolab.journal-forecast-fold-manifest.v1", "folds": entries})
    original = evaluate("original", second_target_journal, manifest)
    final = ingest("revised_target", second_target_journal)
    replay = evaluate("original", final, manifest, replay=True)
    if (private / "evaluation-original-replay.json").read_bytes() != (private / "evaluation-original.json").read_bytes():
        raise ValueError("appending beyond the original plan cutoffs changed its evaluation")
    revised_target, _, revised_score = target_and_score(final, first_spec, first_forecast, 2, 41, "revised-target")
    revised_entries = deepcopy(entries)
    revised_entries[0]["target"] = revised_target.name
    revised_manifest = save_private("folds-revised-target.json", {
        "schema": "sociolab.journal-forecast-fold-manifest.v1", "folds": revised_entries,
    })
    revised = evaluate("revised-target", final, revised_manifest)
    if [fold["score"] for fold in original["folds"]] != [first_score, second_score]:
        raise ValueError("original evaluation differs from separately saved scores")
    if [fold["score"] for fold in revised["folds"]] != [revised_score, second_score]:
        raise ValueError("revised target evaluation differs from separately saved scores")
    if ([fold["forecast_hash"] for fold in original["folds"]] != [fold["forecast_hash"] for fold in revised["folds"]]
            or original["plan_hash"] == revised["plan_hash"]
            or original["folds"][0]["target_hash"] == revised["folds"][0]["target_hash"]):
        raise ValueError("target version sensitivity must use distinct plans and the same saved forecasts")
    revision = original["folds"][1]["history_revision"]
    if (revision["behavior_changed_actor_wave_count"] != 1
            or revision["previous_target_comparison"]["changed_actor_count"] != 1):
        raise ValueError("the declared historical and previous-target revisions were not exposed")
    if len(steps) != protocol["expected_cli_steps"] or original["actor_forecast_count"] != 8:
        raise ValueError("the declared execution coverage changed")
    source_after = {name: digest(REPOSITORY / name) for name in sources}
    if source_before != source_after:
        raise ValueError("implementation, protocol or fixture changed during execution")
    final_hashes = {path.name: digest(path) for path in sorted(private.glob("*.json"))}
    if frozen != final_hashes:
        raise ValueError("a private JSON artifact changed after creation or was not sealed")
    report = {
        "schema": "sociolab.receipt-evaluation-example-report.v1", "kind": "SYNTHETIC_RECEIPT_EVALUATION_EXECUTION",
        "actor_count": 4, "forecast_origin_count": 2, "actor_forecast_count": 8,
        "source_behavior_wave_count": 4, "complete_history_network_wave_count": 3,
        "receipt_cutoffs": {name: protocol["stages"][name]["knowledge_cutoff"] for name in protocol["stage_order"]},
        "original_evaluation_hash": original["content_hash"], "revised_target_evaluation_hash": revised["content_hash"],
        "original_plan_hash": original["plan_hash"], "revised_target_plan_hash": revised["plan_hash"],
        "original_plan_replay_after_later_revision_byte_identical": True,
        "same_saved_forecasts_in_both_evaluations": True, "all_private_json_artifacts_unchanged": True,
        "private_json_artifact_count": len(frozen), "history_revision_at_second_origin": revision,
        "separately_saved_scores_match_evaluations": True, "target_versions_predeclared_before_forecasts": True,
        "target_version_sensitivity_only": True, "new_forecasts_created_for_target_revision": False,
        "real_data_used": False, "engineering_example_only": True, "all_fixture_batches_known_before_execution": True,
        "historical_as_of_availability_verified": False, "prospective_validation": False,
        "empirical_prediction_validated": False, "causal_effect_identified": False,
        "realtime_subscription_implemented": False,
    }
    aggregate_only(report, actors)
    save(output / "report.json", report)
    execution = {
        "kind": "SYNTHETIC_RECEIPT_EVALUATION_EXECUTION_RECORD", "started_at_utc": started,
        "finished_at_utc": now(), "wall_seconds": perf_counter() - clock, "protocol_sha256": digest(protocol_path),
        "steps": steps, "plan_records": plan_records, "issuance_records": issuance_records,
        "private_input_file_sha256": final_hashes, "creation_file_sha256": frozen,
        "source_hashes_at_start": source_before, "source_hashes_at_finish": source_after,
        "public_file_sha256": {name: digest(output / name) for name in PUBLIC_NAMES if name != "execution.json"},
        "all_inputs_unchanged": True, "case_runs": 1, "automatic_retry": False, "tuning_after_scores": False,
        "all_fixture_batches_known_before_execution": True, "execution_order_authenticates_availability": False,
        "model_creation_steps": 2, "evaluation_refits": 0, "engineering_example_only": True,
        "environment": {"PYTHONPATH": environment["PYTHONPATH"], "PYTHONHASHSEED": "0"},
    }
    aggregate_only(execution, actors)
    save(output / "execution.json", execution)
    print(json.dumps({"status": "OK", "cli_steps": len(steps), "actor_forecast_count": 8,
                      "private_json_artifact_count": len(frozen), "original_evaluation_replay_byte_identical": True,
                      "target_version_sensitivity_uses_same_forecasts": True, "engineering_example_only": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
