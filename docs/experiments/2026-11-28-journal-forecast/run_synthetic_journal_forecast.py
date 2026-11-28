#!/usr/bin/env python3
"""Exercise receipt-bound history, immutable predictions and separate rescoring.

All input records are invented and known before execution. Recorded save order
and hashes establish an engineering invariant, not prospective availability.
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
EXAMPLES = REPOSITORY / "examples/journal-forecast"
PUBLIC_FILES = ("report.json", "execution.json", "score-original.json",
                "score-revised-history.json", "score-corrected-target.json")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def aggregate_only(value, actors: set[str]) -> None:
    if isinstance(value, str) and value in actors:
        raise ValueError("public output contains an actor identifier")
    if isinstance(value, dict):
        forbidden = {"actors", "edges", "raw_predictions", "clipped_predictions", "records"}
        if forbidden & set(value):
            raise ValueError("public output contains private individual records")
        for key, item in value.items():
            aggregate_only(key, actors)
            aggregate_only(item, actors)
    elif isinstance(value, list):
        for item in value:
            aggregate_only(item, actors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    private, output = args.private_directory.resolve(), args.output.resolve()
    if private.is_relative_to(REPOSITORY):
        parser.error("private journal and prediction artifacts must stay outside the repository")
    if private.is_relative_to(output) or output.is_relative_to(private):
        parser.error("private and public directories must be separate")
    if private.exists() and (not private.is_dir() or any(private.iterdir())):
        parser.error("private directory must be fresh; existing artifacts are never overwritten")
    if output.exists() and not output.is_dir():
        parser.error("public output must be a directory")
    if any((output / name).exists() for name in PUBLIC_FILES):
        parser.error("public output paths must be fresh; existing evidence is never overwritten")
    protocol_path = EXPERIMENT / "protocol.json"
    protocol = read(protocol_path)
    for relative, expected in protocol["input_file_sha256"].items():
        if digest(REPOSITORY / relative) != expected:
            parser.error("an invented input differs from the fixed protocol")
    specification = read(EXAMPLES / "history.spec.json")
    empty = read(EXAMPLES / "empty.events.json")
    if (empty["origin"] != "synthetic" or specification["source_reference"] is not None
            or len(specification["actors"]) != 4 or len(specification["waves"]) != 2):
        parser.error("this execution accepts only its fixed four-person invented example")
    stages = protocol["stages"]
    if (protocol["stage_order"] != ["initial", "late_history", "target", "revised_target"]
            or set(stages) != set(protocol["stage_order"])):
        parser.error("the frozen batch schedule changed")
    source_paths = tuple(protocol["implementation_files"]) + tuple(protocol["input_file_sha256"]) + (
        "docs/experiments/2026-11-28-journal-forecast/protocol.json",
        "docs/experiments/2026-11-28-journal-forecast/run_synthetic_journal_forecast.py",
    )
    before = {name: digest(REPOSITORY / name) for name in source_paths}
    private.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY / "src")
    environment["PYTHONHASHSEED"] = "0"
    steps, frozen, prediction_records = [], {}, []
    actors = set(specification["actors"]) | {"C_alias"}
    started, clock = now(), perf_counter()

    def save_private(path: Path, value) -> None:
        save(path, value)
        frozen[path.name] = digest(path)

    def execute(command: list[str], destination: Path) -> dict:
        invocation = [sys.executable, "-m", "sociolab", *command]
        step_started, step_clock = now(), perf_counter()
        with destination.open("xb") as stream:
            result = subprocess.run(invocation, cwd=private, env=environment, stdout=stream,
                                    stderr=subprocess.PIPE, check=False)
        step = {"order": len(steps) + 1, "command": invocation,
                "started_at_utc": step_started, "finished_at_utc": now(),
                "wall_seconds": perf_counter() - step_clock, "exit_code": result.returncode,
                "stdout_sha256": digest(destination),
                "stderr_sha256": sha256(result.stderr).hexdigest(), "stderr_empty": not result.stderr}
        steps.append(step)
        with (private / f"step-{step['order']:02d}.stderr.log").open("xb") as stream:
            stream.write(result.stderr)
        if result.returncode or result.stderr:
            raise RuntimeError("journal/forecast CLI failed; private stderr retained")
        if destination.parent == private:
            frozen[destination.name] = digest(destination)
        return read(destination)

    def ingest(stage: str, previous: Path) -> Path:
        entry = stages[stage]
        path = private / f"journal-{stage}.json"
        journal = execute(["events", "import", str(previous), str(EXAMPLES / entry["batch"]),
                           "--received-at", entry["received_at"]], path)
        if len(journal["records"]) != entry["knowledge_cutoff"]:
            raise ValueError("receipt count differs from the fixed batch schedule")
        return path

    def history(journal: Path, spec_path: Path, label: str) -> tuple[Path, dict]:
        bundle_path = private / f"history-{label}.bundle.json"
        bundle = execute(["forecast", "journal-history", str(journal), str(spec_path)], bundle_path)
        panel_path = private / f"history-{label}.json"
        save_private(panel_path, bundle["history"])
        return panel_path, bundle

    def prediction(panel: Path, label: str, *, target_not_received: bool) -> tuple[Path, dict]:
        path = private / f"forecast-{label}.json"
        value = execute(["forecast", "create", str(panel), str(forecast_spec)], path)
        prediction_records.append({"label": label, "saved_at_utc": now(),
                                   "file_sha256": digest(path), "forecast_hash": value["content_hash"],
                                   "target_batch_not_yet_ingested": target_not_received})
        return path, value

    def target(journal: Path, spec_path: Path, forecast: Path, cutoff: int, label: str) -> tuple[Path, dict]:
        bundle_path = private / f"target-{label}.bundle.json"
        bundle = execute(["forecast", "journal-target", str(journal), str(spec_path), str(forecast),
                          "--knowledge-cutoff", str(cutoff)], bundle_path)
        target_path = private / f"target-{label}.json"
        save_private(target_path, bundle["target"])
        return target_path, bundle

    def score(forecast: Path, target_path: Path, name: str) -> dict:
        private_score = private / name
        value = execute(["forecast", "score", str(forecast), str(target_path)], private_score)
        aggregate_only(value, actors)
        # Publish only after checking the complete private result. Retain the
        # exact CLI bytes so execution and public report hashes agree.
        with (output / name).open("xb") as stream:
            stream.write(private_score.read_bytes())
        return value

    old_spec = private / "history-original.spec.json"
    forecast_spec = private / "forecast.spec.json"
    save_private(old_spec, specification)
    save_private(forecast_spec, specification["forecast_specification"])
    initial = ingest("initial", EXAMPLES / "empty.events.json")
    original_panel, original_bundle = history(initial, old_spec, "original")
    original_forecast_path, original_forecast = prediction(original_panel, "original", target_not_received=True)

    late = ingest("late_history", initial)
    replay_panel, replay_bundle = history(late, old_spec, "old-cutoff-replay")
    replay_forecast_path, _ = prediction(replay_panel, "old-cutoff-replay", target_not_received=True)
    if ((private / "history-old-cutoff-replay.bundle.json").read_bytes()
            != (private / "history-original.bundle.json").read_bytes()
            or replay_forecast_path.read_bytes() != original_forecast_path.read_bytes()):
        raise ValueError("late history receipts changed the frozen history or prediction")
    new_spec = private / "history-revised.spec.json"
    changed_spec = deepcopy(specification)
    changed_spec["knowledge_cutoff"] = stages["late_history"]["knowledge_cutoff"]
    save_private(new_spec, changed_spec)
    revised_panel, revised_bundle = history(late, new_spec, "revised")
    revised_forecast_path, revised_forecast = prediction(revised_panel, "revised-history", target_not_received=True)
    old_waves, new_waves = original_bundle["history"]["waves"], revised_bundle["history"]["waves"]
    history_changes = {
        "behavior_values_changed": any(a["behavior"] != b["behavior"] for a, b in zip(old_waves, new_waves)),
        "network_edges_changed": any(a["edges"] != b["edges"] for a, b in zip(old_waves, new_waves)),
        "history_bundle_changed": original_bundle["content_hash"] != revised_bundle["content_hash"],
        "forecast_changed": original_forecast["content_hash"] != revised_forecast["content_hash"],
        "training_label_hash_changed": original_forecast["training"]["label_hash"] != revised_forecast["training"]["label_hash"],
    }
    if not all(history_changes.values()):
        raise ValueError("the new receipt cutoff did not expose the intended changes")

    observed = ingest("target", late)
    history(observed, old_spec, "old-cutoff-after-target")
    first_target_path, first_target_bundle = target(observed, old_spec, original_forecast_path,
                                                  stages["target"]["knowledge_cutoff"], "original")
    first_score = score(original_forecast_path, first_target_path, "score-original.json")
    new_target_path, _ = target(observed, new_spec, revised_forecast_path,
                               stages["target"]["knowledge_cutoff"], "revised-history")
    revised_score = score(revised_forecast_path, new_target_path, "score-revised-history.json")

    final = ingest("revised_target", observed)
    history(final, old_spec, "old-cutoff-after-correction")
    target(final, old_spec, original_forecast_path, stages["target"]["knowledge_cutoff"], "old-cutoff-replay")
    corrected_target_path, corrected_bundle = target(final, old_spec, original_forecast_path,
                                                    stages["revised_target"]["knowledge_cutoff"], "corrected")
    corrected_score = score(original_forecast_path, corrected_target_path, "score-corrected-target.json")
    if (private / "target-old-cutoff-replay.bundle.json").read_bytes() != (private / "target-original.bundle.json").read_bytes():
        raise ValueError("a target correction changed a previously selected receipt prefix")
    for label in ("old-cutoff-replay", "old-cutoff-after-target", "old-cutoff-after-correction"):
        if (private / f"history-{label}.bundle.json").read_bytes() != (private / "history-original.bundle.json").read_bytes():
            raise ValueError("an appended batch changed history at the original cutoff")
    if (first_target_bundle["target"]["behavior"] == corrected_bundle["target"]["behavior"]
            or first_score["target_behavior_hash"] == corrected_score["target_behavior_hash"]
            or first_score["models"] == corrected_score["models"]
            or first_score["forecast_hash"] != corrected_score["forecast_hash"]):
        raise ValueError("target correction did not rescore the same immutable forecast")
    if any(digest(private / name) != expected for name, expected in frozen.items()):
        raise ValueError("a saved input or prediction changed during the execution")
    after = {name: digest(REPOSITORY / name) for name in source_paths}
    if before != after:
        raise ValueError("implementation, protocol or fixtures changed during execution")
    private_hashes = {path.name: digest(path) for path in sorted(private.glob("*.json"))}
    if private_hashes != frozen:
        raise ValueError("every saved private JSON artifact must retain its creation-time hash")
    report = {
        "schema": "sociolab.journal-forecast-example-report.v1",
        "kind": "SYNTHETIC_JOURNAL_FORECAST_EXECUTION", "actor_count": 4,
        "history_wave_count": 2, "target_time_index": specification["forecast_specification"]["target_time_index"],
        "receipt_cutoffs": {name: entry["knowledge_cutoff"] for name, entry in stages.items()},
        "history_changes_at_new_cutoff": history_changes,
        "old_history_replays_byte_identically": True, "old_prediction_replay_byte_identical": True,
        "old_target_replay_byte_identical": True, "all_saved_predictions_unchanged": True,
        "target_correction_rescores_same_forecast": True,
        "original_history_bundle_hash": original_bundle["content_hash"],
        "revised_history_bundle_hash": revised_bundle["content_hash"],
        "original_forecast_hash": original_forecast["content_hash"],
        "revised_history_forecast_hash": revised_forecast["content_hash"],
        "original_target_source_revision": first_target_bundle["target"]["source_revision"],
        "corrected_target_source_revision": corrected_bundle["target"]["source_revision"],
        "score_file_sha256": {name: digest(output / name) for name in PUBLIC_FILES if name.startswith("score-")},
        "target_network_observations_supplied": False, "future_network_used_in_target_selection": False,
        "single_origin_analysis_versions": 2, "independent_real_forecast_origins": 0,
        "historical_as_of_availability_verified": False, "empirical_prediction_validated": False,
        "prospective_validation": False, "causal_effect_identified": False,
        "realtime_subscription_implemented": False, "engineering_example_only": True,
    }
    for value in (report, first_score, revised_score, corrected_score):
        aggregate_only(value, actors)
    save(output / "report.json", report)
    execution = {
        "kind": "SYNTHETIC_JOURNAL_FORECAST_EXECUTION_RECORD",
        "started_at_utc": started, "finished_at_utc": now(), "wall_seconds": perf_counter() - clock,
        "protocol_sha256": digest(protocol_path), "steps": steps, "prediction_records": prediction_records,
        "private_input_file_sha256": private_hashes, "frozen_artifact_file_sha256": frozen,
        "source_hashes_at_start": before, "source_hashes_at_finish": after,
        "implementation_and_inputs_unchanged": True, "frozen_artifacts_unchanged": True,
        "report_file_sha256": digest(output / "report.json"),
        "environment": {"PYTHONPATH": environment["PYTHONPATH"], "PYTHONHASHSEED": "0"},
        "automatic_retry": False, "tuning_after_scores": False, "real_data_used": False,
        "execution_order_authenticates_historical_availability": False,
        "all_fixture_batches_known_before_execution": True, "engineering_example_only": True,
    }
    aggregate_only(execution, actors)
    save(output / "execution.json", execution)
    print(json.dumps({"status": "OK", "cli_steps": len(steps), "receipt_cutoffs": report["receipt_cutoffs"],
                      "old_history_replays_byte_identically": True, "old_prediction_replay_byte_identical": True,
                      "target_correction_rescores_same_forecast": True, "engineering_example_only": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
