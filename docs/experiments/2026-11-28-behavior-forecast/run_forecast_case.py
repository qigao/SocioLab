#!/usr/bin/env python3
"""Freeze s50 point forecasts before separately extracting/scoring the target.

Source data, historical panels, target observations and actor-level predictions
stay outside the checkout. The report directory receives aggregate evidence.
This is a retrospective teaching exercise, not a prospective evaluation.
"""

from __future__ import annotations

import argparse
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
EXPECTED_ARCHIVE = "57dfd0d2a5f924f36cb1ff0c70d2e3a83370e142400af4edc28f4c5c29fea955"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def check_no_actor_strings(value: object, actors: set[str]) -> None:
    if isinstance(value, str) and value in actors:
        raise ValueError("public output includes an actor identifier")
    if isinstance(value, dict):
        for key, item in value.items():
            check_no_actor_strings(key, actors)
            check_no_actor_strings(item, actors)
    elif isinstance(value, list):
        for item in value:
            check_no_actor_strings(item, actors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--private-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    private = args.private_directory.resolve()
    output = args.output.resolve()
    if private.is_relative_to(REPOSITORY):
        parser.error("private source/prediction artifacts must stay outside the repository")
    if archive.is_relative_to(REPOSITORY):
        parser.error("the source archive must stay outside the repository")
    if private.is_relative_to(output) or output.is_relative_to(private):
        parser.error("private and public output directories must be separate")
    if digest(archive) != EXPECTED_ARCHIVE:
        parser.error("this recorded case requires the reviewed original s50 archive fingerprint")
    protocol_path = EXPERIMENT / "protocol.json"
    specification = REPOSITORY / "examples/forecast/s50.spec.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    private.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    history = private / "s50.history.json"
    prediction = private / "s50.prediction.json"
    target = private / "s50.target.json"
    score_path = output / "score.json"
    summary_path = output / "forecast-summary.json"
    execution_path = output / "execution.json"
    generated = (history, prediction, target, score_path, summary_path, execution_path)
    if any(path.exists() for path in generated):
        parser.error("use fresh output paths; retained predictions and evidence are not overwritten")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY / "src")
    environment["PYTHONHASHSEED"] = "0"
    source_paths = (
        "src/sociolab/behavior_forecast.py", "src/sociolab/s50_forecast.py",
        "src/sociolab/panels.py", "src/sociolab/s50.py",
        "src/sociolab/cli.py", "src/sociolab/_json.py",
        "examples/forecast/s50.spec.json",
        "docs/experiments/2026-11-28-behavior-forecast/protocol.json",
        "docs/experiments/2026-11-28-behavior-forecast/run_forecast_case.py",
    )
    before_hashes = {name: digest(REPOSITORY / name) for name in source_paths}
    steps: list[dict[str, object]] = []

    def execute(action: str, inputs: list[Path], destination: Path) -> None:
        command = [sys.executable, "-m", "sociolab", "forecast", action]
        command.extend(str(path) for path in inputs)
        started_at = timestamp()
        clock = perf_counter()
        with destination.open("xb") as stream:
            process = subprocess.run(command, cwd=private, env=environment, stdout=stream,
                                     stderr=subprocess.PIPE, check=False)
        elapsed = perf_counter() - clock
        stderr_path = private / (action + ".stderr.log")
        with stderr_path.open("xb") as stream:
            stream.write(process.stderr)
        steps.append({
            "order": len(steps) + 1, "action": action, "command": command,
            "started_at_utc": started_at, "finished_at_utc": timestamp(),
            "wall_seconds": elapsed, "exit_code": process.returncode,
            "stdout_sha256": digest(destination),
            "stderr_sha256": sha256(process.stderr).hexdigest(),
            "stderr_empty": not process.stderr,
        })
        if process.returncode != 0:
            raise RuntimeError(f"forecast {action} failed with exit {process.returncode}; private stderr retained")
        if process.stderr:
            raise RuntimeError(f"forecast {action} wrote unexpected stderr; inspect the retained private log")

    started_at = timestamp()
    total_clock = perf_counter()
    execute("s50-history", [archive], history)
    history_data = json.loads(history.read_text(encoding="utf-8"))
    if [wave["time_index"] for wave in history_data["waves"]] != [0, 1]:
        raise ValueError("source history must contain exactly the two declared known waves")
    if target.exists():
        raise ValueError("target artifact exists before prediction")
    execute("create", [history, specification], prediction)
    prediction_file_hash = digest(prediction)
    forecast = json.loads(prediction.read_text(encoding="utf-8"))
    frozen_at = timestamp()
    seal = {
        "kind": "LOCAL_FORECAST_FILE_RECORD", "saved_at_utc": frozen_at,
        "forecast_content_hash": forecast["content_hash"],
        "prediction_file_sha256": prediction_file_hash,
        "history_file_sha256": digest(history),
        "target_artifact_existed_at_save": target.exists(),
        "scope": "local ordering evidence and integrity; not external timestamp authentication or a blind experiment",
    }
    save_json(private / "prediction-file-record.json", seal)

    # The prediction subprocess has finished and its output is saved before
    # any target extraction or scoring subprocess is started.
    execute("s50-target", [archive], target)
    execute("score", [prediction, target], score_path)
    score = json.loads(score_path.read_text(encoding="utf-8"))
    if digest(prediction) != prediction_file_hash:
        raise ValueError("scoring changed the saved prediction")
    if score["forecast_hash"] != forecast["content_hash"]:
        raise ValueError("score does not bind the saved forecast")
    if score["actor_count"] != 50:
        raise ValueError("scoring changed the fixed case denominator")
    actor_set = set(history_data["actors"])
    check_no_actor_strings(score, actor_set)
    diagnostics = {
        name: {key: value for key, value in model.items()
               if key not in {"raw_predictions", "clipped_predictions"}}
        for name, model in forecast["models"].items()
    }
    summary = {
        "kind": "BEHAVIOR_FORECAST_CASE_SUMMARY",
        "evaluation_scope": "retrospective_single_transition_holdout",
        "forecast_content_hash": forecast["content_hash"],
        "prediction_file_sha256": prediction_file_hash,
        "history_prefix_hash": forecast["history"]["content_hash"],
        "specification_hash": forecast["specification_hash"],
        "actor_count": len(actor_set),
        "history": forecast["history"],
        "training": forecast["training"],
        "forecast_input_hashes": forecast["forecast_input_hashes"],
        "models": diagnostics, "runtime": forecast["runtime"],
        "scope": forecast["scope"],
        "original_actor_ids_exported": False,
        "per_actor_predictions_exported": False,
        "source_usage": protocol["source"]["source_usage"],
        "prior_three_wave_retrospective_use": True,
        "population_generalization_validated": False,
        "cooperation_or_attendance_prediction_validated": False,
    }
    check_no_actor_strings(summary, actor_set)
    save_json(summary_path, summary)
    after_hashes = {name: digest(REPOSITORY / name) for name in source_paths}
    if before_hashes != after_hashes or digest(archive) != EXPECTED_ARCHIVE:
        raise ValueError("source or implementation changed during execution")
    execution = {
        "kind": "BEHAVIOR_FORECAST_CASE_EXECUTION",
        "started_at_utc": started_at, "finished_at_utc": timestamp(),
        "wall_seconds": perf_counter() - total_clock,
        "source_archive_sha256": EXPECTED_ARCHIVE,
        "protocol_sha256": before_hashes["docs/experiments/2026-11-28-behavior-forecast/protocol.json"],
        "protocol_created_at_utc": protocol["created_at_utc"],
        "source_hashes_at_start": before_hashes,
        "source_hashes_at_finish": after_hashes,
        "implementation_unchanged_during_execution": True,
        "environment": {"PYTHONPATH": environment["PYTHONPATH"], "PYTHONHASHSEED": "0"},
        "steps": steps,
        "prediction_saved_at_utc": frozen_at,
        "prediction_file_sha256_before_scoring": prediction_file_hash,
        "prediction_file_sha256_after_scoring": digest(prediction),
        "prediction_process_inputs": ["history prefix", "fixed specification"],
        "target_file_absent_before_prediction": True,
        "target_extraction_started_after_prediction_saved": True,
        "future_network_used": False,
        "score_sha256": digest(score_path),
        "forecast_summary_sha256": digest(summary_path),
        "automatic_retry": False, "tuning_after_score": False,
        "publicly_preregistered": False, "prospective_validation": False,
        "historical_receipt_availability_verified": False,
        "source_data_and_actor_level_outputs_committed": False,
    }
    save_json(execution_path, execution)
    print(json.dumps({"status": "OK", "actor_count": score["actor_count"],
                      "forecast_hash": forecast["content_hash"],
                      "score": str(score_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
