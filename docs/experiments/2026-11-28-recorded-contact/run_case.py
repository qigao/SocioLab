"""Record the unchanged source-specific CLI output and execution fingerprints.

Supply the reviewed original TSV gzip locally. This runner does not download,
modify, redistribute, or complete the source records. See the case-study guide.
"""

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
SOURCE_PATHS = (
    "src/sociolab/recorded_contacts.py", "src/sociolab/contact_analysis.py",
    "src/sociolab/communities.py", "src/sociolab/keyplayers.py",
    "src/sociolab/_graphs.py", "src/sociolab/cli.py",
    str(Path(__file__).relative_to(ROOT)),
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def run(archive, output):
    output.mkdir(parents=True, exist_ok=True)
    hashes = {name: digest(ROOT / name) for name in SOURCE_PATHS}
    command = [sys.executable, "-m", "sociolab", "study", "hypertext2009", str(archive.resolve())]
    started = datetime.now(timezone.utc).isoformat()
    begin = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, capture_output=True)
    elapsed = time.perf_counter() - begin
    (output / "case-report.json").write_bytes(result.stdout)
    (output / "case-stderr.log").write_bytes(result.stderr)
    if hashes != {name: digest(ROOT / name) for name in SOURCE_PATHS}:
        raise ValueError("analysis source changed during execution")
    execution = {
        "kind": "RECORDED_CONTACT_CLI_EXECUTION", "started_utc": started,
        "command": ["python", "-m", "sociolab", "study", "hypertext2009", "<reviewed-local-archive>"],
        "exit_code": result.returncode, "wall_time_seconds": elapsed,
        "archive_sha256": digest(archive), "source_sha256": hashes,
        "protocol_sha256": digest(HERE / "protocol.json"),
        "stdout_sha256": sha256(result.stdout).hexdigest(),
        "stderr_sha256": sha256(result.stderr).hexdigest(),
        "runtime": {"python": sys.version.split()[0], "platform": platform.platform(),
                    "packages": {name: version(name) for name in ("networkx", "pandas", "numpy")}},
    }
    (output / "case-execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n")
    if result.returncode or result.stderr:
        raise ValueError("case CLI failed; inspect preserved output and execution record")
    report = json.loads(result.stdout)
    if report.get("kind") != "RECORDED_CONTACT_CASE_STUDY":
        raise ValueError("CLI did not produce the expected case report")
    print(json.dumps({"exit_code": result.returncode, "wall_time_seconds": elapsed,
                      "archive_nodes": report["source"]["node_count"],
                      "source_rows": report["source"]["row_count"],
                      "scenario_count": len(report["analysis"]["scenarios"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.archive, args.output)
