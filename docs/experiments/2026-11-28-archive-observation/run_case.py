"""Audit both previously analyzed archives and independently check the results.

Usage: python run_case.py DEPT3_ARCHIVE DEPT2_ARCHIVE NEW_OUTPUT_DIRECTORY
No source acquisition, model fitting, private forecast recovery or retuning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: run_case.py DEPT3_ARCHIVE DEPT2_ARCHIVE NEW_OUTPUT_DIRECTORY")
    dept3, dept2, output = [Path(value).resolve() for value in sys.argv[1:]]
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    checker = here / "independent_check.py"
    cases = [
        ("dept3", "email-eu-dept3", dept3, root / "docs/experiments/2026-11-28-dept3-archive/case-report.json"),
        ("dept2", "email-eu-dept2-network", dept2, root / "docs/experiments/2026-11-28-dept2-network/case-report.json"),
    ]
    names = ["execution.json"]
    for label, _, _, _ in cases:
        names.extend([f"{label}-observation-report.json", f"{label}-independent-check.json",
                      f"{label}-audit.stderr.log", f"{label}-checker.stderr.log"])
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in names):
        raise SystemExit("use a new output directory; prior audit evidence is not overwritten")
    retained = [path for _, _, _, case in cases for path in (case, case.parent / "protocol.json")]
    tracked = sorted([*root.joinpath("src").rglob("*.py"), root / "pyproject.toml", *retained,
                      checker, Path(__file__).resolve(), here / "analysis-plan.json", here / "source-review.json"])
    before = {str(path.relative_to(root)): digest(path) for path in tracked}
    source_before = {label: digest(archive) for label, _, archive, _ in cases}
    records = []
    for label, profile, archive, case in cases:
        report = output / f"{label}-observation-report.json"
        commands = [
            [sys.executable, "-m", "sociolab", "study", "archive-observation", profile, str(archive), str(case)],
            [sys.executable, str(checker), profile, str(archive), str(case), str(report),
             str(output / f"{label}-independent-check.json")],
        ]
        failed = False
        for index, command in enumerate(commands):
            started = datetime.now(timezone.utc).isoformat()
            process = subprocess.run(command, cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")},
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            records.append({"profile": profile, "step": "audit" if index == 0 else "independent_check",
                            "command": command, "started_at_utc": started,
                            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                            "exit_code": process.returncode,
                            "stdout_sha256": sha256(process.stdout.encode()).hexdigest(),
                            "stderr_sha256": sha256(process.stderr.encode()).hexdigest()})
            (output / f"{label}-{'audit' if index == 0 else 'checker'}.stderr.log").write_text(process.stderr, encoding="utf-8")
            if index == 0 and process.returncode == 0:
                json.loads(process.stdout)
                report.write_text(process.stdout, encoding="utf-8")
            if process.returncode:
                failed = True
                break
        if failed:
            break
    after = {str(path.relative_to(root)): digest(path) for path in tracked}
    source_after = {label: digest(archive) for label, _, archive, _ in cases}
    success = len(records) == 4 and all(record["exit_code"] == 0 for record in records)
    original_unchanged = all(before[str(path.relative_to(root))] == after[str(path.relative_to(root))] for path in retained)
    execution = {
        "schema": "sociolab.archive-observation-execution.v1",
        "analysis_status": "POST_RESULT_OBSERVATION_AUDIT_AND_EXPLORATORY_WEIGHTING",
        "source_code_original_cases_plan_checker_hashes_before": before,
        "source_code_original_cases_plan_checker_hashes_after": after,
        "tracked_files_unchanged": before == after,
        "archive_sha256_before": source_before, "archive_sha256_after": source_after,
        "archives_unchanged": source_before == source_after, "original_studies_unchanged": original_unchanged,
        "subprocesses": records, "all_subprocesses_succeeded": success,
        "artifacts": {name: digest(output / name) for name in names if name != "execution.json" and (output / name).exists()},
        "new_source_acquired": False, "new_dependency_installed": False,
        "real_source_models_fitted_or_refitted": False, "private_predictions_reconstructed": False,
        "original_labels_or_primary_results_changed": False,
        "raw_source_or_private_forecasts_published": False,
        "real_coverage_or_gap_cause_established": False, "installer_or_consumer_test_suite_run": False,
    }
    (output / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"success": success, "subprocess_count": len(records), "tracked_files_unchanged": before == after,
                      "archives_unchanged": source_before == source_after, "original_studies_unchanged": original_unchanged}))
    return 0 if success and before == after and source_before == source_after and original_unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
