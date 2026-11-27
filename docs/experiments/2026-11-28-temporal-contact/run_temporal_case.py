"""Record actual reviewed-source temporal CLI output and execution hashes.

The original source stays outside the repository. This runner neither changes
the source nor supplies alternate outputs when the original analysis fails.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCES = (
    "src/sociolab/recorded_contacts.py", "src/sociolab/contact_analysis.py",
    "src/sociolab/temporal_contacts.py", "src/sociolab/contact_temporal_study.py",
    "src/sociolab/cli.py", str(Path(__file__).relative_to(ROOT)),
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def run(archive, output):
    output.mkdir(parents=True, exist_ok=True)
    before = {name: digest(ROOT / name) for name in SOURCES}
    command = [sys.executable, "-m", "sociolab", "study", "hypertext2009-temporal", str(archive.resolve())]
    started = datetime.now(timezone.utc).isoformat()
    begin = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, capture_output=True)
    elapsed = time.perf_counter() - begin
    (output / "temporal-report.json").write_bytes(result.stdout)
    (output / "temporal-stderr.log").write_bytes(result.stderr)
    if before != {name: digest(ROOT / name) for name in SOURCES}:
        raise ValueError("temporal analysis source changed during execution")
    execution = {
        "kind": "RECORDED_CONTACT_TEMPORAL_CLI_EXECUTION", "started_utc": started,
        "command": ["python", "-m", "sociolab", "study", "hypertext2009-temporal", "<reviewed-local-archive>"],
        "exit_code": result.returncode, "wall_time_seconds": elapsed,
        "archive_sha256": digest(archive), "source_sha256": before,
        "protocol_sha256": digest(HERE / "protocol.json"),
        "stdout_sha256": sha256(result.stdout).hexdigest(),
        "stderr_sha256": sha256(result.stderr).hexdigest(),
        "runtime": {"python": sys.version.split()[0], "platform": platform.platform(),
                    "packages": {name: version(name) for name in ("networkx", "pandas", "numpy")}},
    }
    (output / "temporal-execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n")
    if result.returncode or result.stderr:
        raise ValueError("temporal CLI failed; inspect the retained execution and output")
    report = json.loads(result.stdout)
    if report.get("kind") != "RECORDED_CONTACT_TEMPORAL_STUDY":
        raise ValueError("unexpected temporal CLI report kind")
    print(json.dumps({"exit_code": result.returncode, "wall_time_seconds": elapsed,
                      "archive_nodes": report["source"]["node_count"],
                      "source_rows": report["source"]["row_count"],
                      "scenario_count": len(report["scenarios"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.archive, args.output)
