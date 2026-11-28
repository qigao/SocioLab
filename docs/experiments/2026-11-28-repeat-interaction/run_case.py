"""Execute the frozen fictional repeat-pair CLI case once, preserving evidence."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
FIXTURE = ROOT / "examples/repeat-interaction/generate_fixture.py"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def source_hashes():
    paths = list((ROOT/"src/sociolab").glob("*.py"))
    paths += [ROOT/"tests/test_repeat_interaction.py", FIXTURE, FIXTURE.parent/"README.md",
              Path(__file__).resolve(), CASE/"independent_case_check.py", CASE/"protocol.json"]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def aggregate_only(value):
    forbidden = {"actors", "persons", "edges", "records", "record_ids", "predictions", "payload", "record_history", "selected_records"}
    if isinstance(value, dict):
        if forbidden.intersection(value):
            raise ValueError("private source or prediction rows cannot enter public evidence")
        for child in value.values(): aggregate_only(child)
    elif isinstance(value, list):
        for child in value: aggregate_only(child)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    private = args.output.absolute()
    resolved = private.resolve()
    if private.exists() or private.is_symlink() or resolved == ROOT or ROOT in resolved.parents or resolved in ROOT.parents:
        parser.error("output must be fresh, outside and not containing the checkout")
    if any((CASE/n).exists() for n in ("execution.json", "case-report.json", "failure.json")):
        parser.error("this case already has execution evidence; no overwrite or automatic retry")
    protocol = read(CASE/"protocol.json")
    if protocol["fixture_generator_sha256"] != digest(FIXTURE) or protocol["independent_checker_sha256"] != digest(CASE/"independent_case_check.py"):
        raise ValueError("fixture/checker differs from frozen protocol")
    before = source_hashes()
    private.mkdir(mode=0o700)
    start = time.monotonic()
    started = datetime.now(timezone.utc).isoformat()
    seals, commands = {}, []
    environment = dict(os.environ, PYTHONPATH=str(ROOT/"src"), PYTHONHASHSEED="0")

    def remember(path):
        name, current = str(path.relative_to(private)), digest(path)
        if name in seals and seals[name] != current:
            raise ValueError("a previously saved private artifact changed")
        if name not in seals: seals[name] = current

    def execute(label, arguments, output_name):
        step = {"label": label, "arguments": [str(a) for a in arguments], "exit_code": None}
        commands.append(step)
        try:
            result = subprocess.run([sys.executable]+[str(a) for a in arguments], cwd=ROOT,
                                    env=environment, capture_output=True, timeout=30)
            stdout, stderr = result.stdout, result.stderr
            step["exit_code"] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            step["timed_out"] = True
            result = None
        for name, raw in ((output_name, stdout), (label+".stderr.log", stderr)):
            path = private/name
            with path.open("xb") as stream: stream.write(raw)
            remember(path)
        if result is None or result.returncode != 0 or stderr:
            raise ValueError("case CLI step failed: "+label)
        return json.loads(stdout)

    try:
        execute("generate-fixture", [FIXTURE, private/"inputs"], "fixture-execution.json")
        for path in sorted((private/"inputs").iterdir()): remember(path)
        metadata = read(private/"inputs/metadata.json")
        for name, wanted in metadata["input_file_sha256"].items():
            if digest(private/"inputs"/name) != wanted: raise ValueError("generated fixture hash mismatch")
        inp = private/"inputs"
        forecast = execute("forecast-create", ["-m", "sociolab", "forecast", "interaction-create",
            inp/"history.events.json", inp/"specification.json"], "forecast.json")
        forecast_bytes_hash = digest(private/"forecast.json")
        scores = {}
        for scenario in protocol["scenario_order"]:
            dataset = "partial" if scenario == "incomplete" else scenario
            scores[scenario] = execute("score-"+scenario, ["-m", "sociolab", "forecast", "interaction-score",
                inp/(dataset+".events.json"), private/"forecast.json", inp/(scenario+".target.json")], "score-"+scenario+".json")
            if digest(private/"forecast.json") != forecast_bytes_hash: raise ValueError("saved forecast changed during scoring")
        execute("forecast-replayed", ["-m", "sociolab", "forecast", "interaction-create",
            inp/"retracted.events.json", inp/"specification.json"], "forecast-replayed.json")
        execute("score-partial-replayed", ["-m", "sociolab", "forecast", "interaction-score",
            inp/"retracted.events.json", private/"forecast.json", inp/"partial.target.json"], "score-partial-replayed.json")
        for name, dataset, view in (
            ("target-window", "complete", "target-window"), ("empty-window", "complete", "empty-window"),
            ("active-state", "complete", "cooperation-state"), ("ended-state", "terminated", "cooperation-state")):
            execute(name, ["-m", "sociolab", "snapshot", inp/(dataset+".events.json"), inp/(view+".view.json")], name+".snapshot.json")
        independent = execute("independent-check", [CASE/"independent_case_check.py", private,
            "--output", private/"independent-check.json"], "independent-execution.json")
        remember(private/"independent-check.json")
        final_hashes = {str(p.relative_to(private)): digest(p) for p in sorted(private.rglob("*")) if p.is_file()}
        if final_hashes != seals: raise ValueError("private artifacts changed or file inventory differs")
        after = source_hashes()
        if after != before: raise ValueError("implementation, protocol or fixture changed during execution")
        report = {"kind": "FICTIONAL_REPEAT_INTERACTION_CASE", "status": "PASS", "origin": "synthetic",
            "history_knowledge_cutoff": 17, "risk_pair_count": 3, "forecast_hash": forecast["content_hash"],
            "forecast_file_unchanged": True, "scenario_order": protocol["scenario_order"],
            "scenarios": {name: {k: score[k] for k in ("status", "counts", "unscored_reasons", "models", "content_hash")} for name, score in scores.items()},
            "replay": {"forecast_bytes_identical": True, "original_partial_score_bytes_identical": True},
            "separate_state_control": {"complete_empty_recent_event_edge_count": 0, "active_cooperation_edge_count": 1,
                "explicit_zero_cooperation_edge_count": 0, "window_expiry_terminated_relationship": False},
            "independent_check": independent,
            "scope": {"all_source_values_invented": True, "target_scenarios_authored_before_execution": True,
                "real_source_qualified": False, "prospective_issuance_demonstrated": False,
                "calibration_or_predictive_effectiveness_validated": False, "causal_effect_identified": False}}
        execution = {"kind": "FICTIONAL_REPEAT_INTERACTION_EXECUTION", "status": "PASS", "started_at": started,
            "elapsed_seconds": time.monotonic()-start, "command_count": len(commands),
            "commands": [{"label": x["label"], "exit_code": x["exit_code"]} for x in commands],
            "protocol_file_sha256": digest(CASE/"protocol.json"),
            "fixture_metadata_file_sha256": digest(inp/"metadata.json"),
            "source_hashes_before": before, "source_hashes_after": after,
            "private_artifact_creation_hashes": dict(seals), "private_artifact_final_hashes": final_hashes,
            "private_artifacts_unchanged": True, "private_artifact_hash_exclusions": ["execution-private.json"],
            "exclusion_reason": "final execution manifest is excluded to avoid a recursive self-hash",
            "forecast_saved_before_score_commands": True, "automatic_retry_performed": False}
        for value in (report, execution, independent): aggregate_only(value)
        save(private/"execution-private.json", execution)
        save(CASE/"case-report.json", report)
        save(CASE/"execution.json", execution)
        save(CASE/"independent-check.json", independent)
        print(json.dumps({"status": "PASS", "command_count": len(commands), "scenario_count": len(scores),
                          "maximum_absolute_numeric_error": independent["maximum_absolute_numeric_error"]}, sort_keys=True))
        return 0
    except BaseException as error:
        details = {"status": "FAIL", "type": type(error).__name__, "message": str(error),
                   "traceback": traceback.format_exc(), "commands": commands, "first_saved_hashes": seals,
                   "source_hashes_before": before, "automatic_retry_performed": False}
        save(private/"failure-private.json", details)
        public = {"kind": "FICTIONAL_REPEAT_INTERACTION_CASE", "status": "FAIL", "error_type": type(error).__name__,
                  "completed_command_count": sum(x["exit_code"] == 0 for x in commands),
                  "automatic_retry_performed": False, "private_failure_sha256": digest(private/"failure-private.json")}
        save(CASE/"failure.json", public)
        print(json.dumps(public, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
