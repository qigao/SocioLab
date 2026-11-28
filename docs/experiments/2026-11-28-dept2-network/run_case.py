"""Run the frozen Dept2 comparison and its independent numerical audit.

Usage: python run_case.py /path/to/email-Eu-core-temporal-Dept2.txt.gz OUTPUT_DIR
The source is acquired separately; this runner neither downloads nor retunes.
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
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_case.py ARCHIVE OUTPUT_DIR")
    archive, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    protocol, checker = here / "protocol.json", here / "independent_check.py"
    if digest(protocol) != "947b7a1856ee199e7bcdb959eba667d3f6f593df67f325583e90d16a7d684de7":
        raise SystemExit("frozen protocol bytes changed")
    output.mkdir(parents=True, exist_ok=True)
    names = ("case-report.json", "independent-check.json", "execution.json", "study.stderr.log", "checker.stderr.log")
    if any((output / name).exists() for name in names):
        raise SystemExit("use a new output directory; retained execution evidence is not overwritten")
    tracked = sorted([*root.joinpath("src").rglob("*.py"), root / "pyproject.toml",
                      protocol, checker, Path(__file__).resolve()])
    before = {str(path.relative_to(root)): digest(path) for path in tracked}
    archive_before = digest(archive)
    commands = [
        [sys.executable, "-m", "sociolab", "study", "email-eu-dept2-network", str(archive), str(protocol)],
        [sys.executable, str(checker), str(archive), str(protocol),
         str(output / "case-report.json"), str(output / "independent-check.json")],
    ]
    records = []
    for index, command in enumerate(commands):
        started = datetime.now(timezone.utc).isoformat()
        process = subprocess.run(command, cwd=root, env={
            **os.environ, "PYTHONPATH": str(root / "src"),
            "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        }, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        records.append({"command": command, "started_at_utc": started,
                        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "exit_code": process.returncode,
                        "stdout_sha256": sha256(process.stdout.encode()).hexdigest(),
                        "stderr_sha256": sha256(process.stderr.encode()).hexdigest()})
        (output / ("study.stderr.log" if index == 0 else "checker.stderr.log")).write_text(process.stderr, encoding="utf-8")
        if index == 0 and process.returncode == 0:
            json.loads(process.stdout)
            (output / "case-report.json").write_text(process.stdout, encoding="utf-8")
        if process.returncode:
            break
    after = {str(path.relative_to(root)): digest(path) for path in tracked}
    archive_after = digest(archive)
    success = len(records) == 2 and all(record["exit_code"] == 0 for record in records)
    execution = {
        "schema": "sociolab.archive-network-study-execution.v1",
        "protocol_freeze_commit": "938c8e417def93f6e331f04ce52b6deb42f100d2",
        "protocol_file_sha256": digest(protocol),
        "archive_sha256_before": archive_before, "archive_sha256_after": archive_after,
        "source_protocol_checker_hashes_before": before, "source_protocol_checker_hashes_after": after,
        "source_protocol_checker_unchanged": before == after, "archive_unchanged": archive_before == archive_after,
        "subprocesses": records,
        "artifacts": {name: digest(output / name) for name in names if name != "execution.json" and (output / name).exists()},
        "all_subprocesses_succeeded": success, "hyperparameters_retuned": False,
        "raw_source_or_private_forecasts_published": False,
        "new_optional_provider": "scikit-learn==1.9.1",
        "installer_or_consumer_test_suite_run": False,
        "real_communication_or_causal_validation_claimed": False,
    }
    (output / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output_directory": str(output), "subprocess_count": len(records),
                      "success": success, "source_unchanged": before == after,
                      "archive_unchanged": archive_before == archive_after}))
    return 0 if success and before == after and archive_before == archive_after else 1


if __name__ == "__main__":
    raise SystemExit(main())
