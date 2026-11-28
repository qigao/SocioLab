#!/usr/bin/env python3
"""Run the declared invented multi-origin example through saved CLI files.

This is engineering evidence, not a prospective or empirical prediction study.
Each prediction is saved before its separate target artifact is constructed.
The evaluator receives saved histories, predictions and targets and never fits.
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
EXAMPLES = REPOSITORY / "examples/forecast-evaluation"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def assert_aggregate(value: object, actors: set[str]) -> None:
    if isinstance(value, str) and value in actors:
        raise ValueError("public report contains an actor identifier")
    if isinstance(value, dict):
        if {"actors", "edges", "raw_predictions", "clipped_predictions"} & set(value):
            raise ValueError("public report contains actor-level fields")
        for key, item in value.items():
            assert_aggregate(key, actors)
            assert_aggregate(item, actors)
    elif isinstance(value, list):
        for item in value:
            assert_aggregate(item, actors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    private, output = args.private_directory.resolve(), args.output.resolve()
    if private.is_relative_to(REPOSITORY):
        parser.error("private prediction artifacts must stay outside the repository")
    if private.is_relative_to(output) or output.is_relative_to(private):
        parser.error("private and public output directories must be separate")
    if private.exists() and any(private.iterdir()):
        parser.error("the private directory must be fresh; no saved artifact is overwritten")
    if any((output / name).exists() for name in ("plan.json", "evaluation.json", "execution.json")):
        parser.error("use fresh public output paths; existing evidence is not overwritten")
    protocol_path = EXPERIMENT / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    fixture_path = EXAMPLES / "synthetic.panel.json"
    initial_history = EXAMPLES / "initial.history.json"
    initial_specification = EXAMPLES / "initial.spec.json"
    for path, key in ((fixture_path, "fixture_sha256"), (initial_history, "initial_history_sha256"),
                      (initial_specification, "initial_specification_sha256")):
        if digest(path) != protocol["source"][key]:
            parser.error("the invented fixture/specification differs from the fixed protocol")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    specification = json.loads(initial_specification.read_text(encoding="utf-8"))
    if fixture["origin"] != "synthetic" or fixture["source_reference"] is not None:
        parser.error("this runner admits only the checked-in invented example")
    targets = protocol["plan"]["target_time_indices"]
    if targets != [2, 3, 4, 5] or len(fixture["waves"]) != 6 or len(fixture["actors"]) != 4:
        parser.error("the fixed engineering example requires six waves and four invented actors")

    private.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.json"
    evaluation_path = output / "evaluation.json"
    manifest_path = private / "fold-manifest.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY / "src")
    environment["PYTHONHASHSEED"] = "0"
    source_paths = (
        "src/sociolab/forecast_evaluation.py", "src/sociolab/behavior_forecast.py",
        "src/sociolab/panels.py", "src/sociolab/cli.py", "src/sociolab/_json.py",
        "examples/forecast-evaluation/synthetic.panel.json",
        "examples/forecast-evaluation/initial.history.json",
        "examples/forecast-evaluation/initial.spec.json",
        "docs/experiments/2026-11-28-forecast-evaluation/protocol.json",
        "docs/experiments/2026-11-28-forecast-evaluation/run_synthetic_evaluation.py",
    )
    before = {name: digest(REPOSITORY / name) for name in source_paths}
    steps = []

    def execute(action: str, arguments: list[str], destination: Path) -> None:
        command = [sys.executable, "-m", "sociolab", "forecast", action, *arguments]
        started, clock = now(), perf_counter()
        with destination.open("xb") as stream:
            result = subprocess.run(command, cwd=private, env=environment, stdout=stream,
                                    stderr=subprocess.PIPE, check=False)
        step = {"order": len(steps) + 1, "action": action, "command": command,
                "started_at_utc": started, "finished_at_utc": now(),
                "wall_seconds": perf_counter() - clock, "exit_code": result.returncode,
                "stdout_sha256": digest(destination),
                "stderr_sha256": sha256(result.stderr).hexdigest(),
                "stderr_empty": not result.stderr}
        steps.append(step)
        with (private / f"step-{step['order']:02d}.stderr.log").open("xb") as stream:
            stream.write(result.stderr)
        if result.returncode or result.stderr:
            raise RuntimeError(f"forecast {action} failed; private stderr is retained")

    started, clock = now(), perf_counter()
    execute("plan", [str(initial_history), str(initial_specification), "--targets",
                     *(str(time) for time in targets)], plan_path)
    plan_file_hash = digest(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert_aggregate(plan, set(fixture["actors"]))
    plan_saved_at = now()
    entries, seals, score_paths, frozen_hashes = [], [], [], {}
    for time in targets:
        paths = {name: private / f"{name}-{time}.json"
                 for name in ("history", "specification", "forecast", "target", "score")}
        save(paths["history"], {**fixture, "waves": fixture["waves"][:time]})
        save(paths["specification"], {**specification, "target_time_index": time})
        if paths["target"].exists():
            raise ValueError("target artifact exists before prediction")
        execute("create", [str(paths["history"]), str(paths["specification"])], paths["forecast"])
        frozen_hashes[paths["forecast"].name] = digest(paths["forecast"])
        forecast = json.loads(paths["forecast"].read_text(encoding="utf-8"))
        seal = {"target_time_index": time, "prediction_saved_at_utc": now(),
                "forecast_content_hash": forecast["content_hash"],
                "prediction_file_sha256": digest(paths["forecast"]),
                "target_artifact_existed_when_prediction_saved": paths["target"].exists()}
        save(private / f"prediction-file-record-{time}.json", seal)
        # The complete source is a known invented fixture. This later step
        # constructs the target artifact only after the create process exits.
        target = {"schema": "sociolab.behavior-target.v1",
                  **{key: fixture[key] for key in
                     ("dataset_id", "origin", "source_reference", "behavior_variable")},
                  "time_index": time, "source_revision": f"invented-target-{time}",
                  "behavior": fixture["waves"][time]["behavior"]}
        save(paths["target"], target)
        seal["target_artifact_created_at_utc"] = now()
        execute("score", [str(paths["forecast"]), str(paths["target"])], paths["score"])
        seals.append(seal)
        score_paths.append(paths["score"])
        entries.append({name: paths[name].name for name in ("history", "forecast", "target")})
    save(manifest_path, {"schema": "sociolab.behavior-forecast-fold-manifest.v1", "folds": entries})
    input_hashes = {path.name: digest(path) for path in private.glob("*.json")}
    execute("evaluate", [str(plan_path), str(manifest_path)], evaluation_path)
    report = json.loads(evaluation_path.read_text(encoding="utf-8"))
    if report["plan_hash"] != plan["content_hash"] or report["actor_forecast_count"] != 16:
        raise ValueError("evaluation does not match the fixed plan")
    if len(report["folds"]) != len(targets):
        raise ValueError("evaluation changed the declared fold count")
    if any(fold["score"] != json.loads(path.read_text(encoding="utf-8"))
           for fold, path in zip(report["folds"], score_paths)):
        raise ValueError("evaluation changed a separately saved score")
    if any(digest(private / name) != value for name, value in input_hashes.items()):
        raise ValueError("evaluation changed a saved private input")
    if digest(plan_path) != plan_file_hash:
        raise ValueError("the saved plan changed during prediction or evaluation")
    if any(digest(private / name) != value for name, value in frozen_hashes.items()):
        raise ValueError("an issued prediction changed")
    assert_aggregate(report, set(fixture["actors"]))
    after = {name: digest(REPOSITORY / name) for name in source_paths}
    if before != after:
        raise ValueError("implementation, protocol or fixtures changed during execution")
    execution = {
        "kind": "SYNTHETIC_MULTI_ORIGIN_FORECAST_EXECUTION",
        "started_at_utc": started, "finished_at_utc": now(), "wall_seconds": perf_counter() - clock,
        "protocol_created_at_utc": protocol["created_at_utc"], "protocol_sha256": digest(protocol_path),
        "plan_saved_at_utc": plan_saved_at, "plan_file_sha256": plan_file_hash,
        "plan_file_sha256_before_evaluation": plan_file_hash,
        "plan_file_sha256_after_evaluation": digest(plan_path),
        "plan_hash": plan["content_hash"], "steps": steps, "prediction_records": seals,
        "private_input_file_sha256": input_hashes,
        "source_hashes_at_start": before, "source_hashes_at_finish": after,
        "implementation_and_fixtures_unchanged": True,
        "all_prediction_files_unchanged": True, "all_evaluation_inputs_unchanged": True,
        "separately_saved_scores_match_evaluation": True,
        "evaluation_file_sha256": digest(evaluation_path), "evaluation_hash": report["content_hash"],
        "environment": {"PYTHONPATH": environment["PYTHONPATH"], "PYTHONHASHSEED": "0"},
        "actor_count": 4, "fold_count": 4, "actor_forecast_count": 16,
        "automatic_retry": False, "tuning_after_scores": False, "real_data_used": False,
        "execution_proves_prospective_availability": False,
        "engineering_example_only": True, "empirical_prediction_validated": False,
        "causal_effect_identified": False,
    }
    assert_aggregate(execution, set(fixture["actors"]))
    save(output / "execution.json", execution)
    print(json.dumps({"status": "OK", "fold_count": 4, "actor_forecast_count": 16,
                      "evaluation_hash": report["content_hash"], "engineering_example_only": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
