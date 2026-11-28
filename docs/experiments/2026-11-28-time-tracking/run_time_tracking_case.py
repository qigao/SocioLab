"""Execute the invented two-clock tracking case once, keeping stores private."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import selectors
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
FIXTURE = ROOT / "examples/time-tracking"
FLAGS = ("observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def source_hashes():
    names = [
        "src/sociolab/events.py", "src/sociolab/snapshots.py", "src/sociolab/changes.py",
        "src/sociolab/communities.py", "src/sociolab/keyplayers.py", "src/sociolab/affiliations.py",
        "src/sociolab/network_tracking.py", "src/sociolab/temporal_tracking.py", "src/sociolab/tracking_store.py", "src/sociolab/cli.py",
        "src/sociolab/_json.py", "tests/test_network_tracking.py", "tests/test_tracking_store.py",
        "tests/test_tracking_cli.py", "tests/test_temporal_tracking.py",
        "tests/test_temporal_tracking_store.py", "tests/test_temporal_tracking_cli.py",
    ]
    paths = [ROOT / name for name in names]
    paths += [path for path in FIXTURE.iterdir() if path.suffix in {".json", ".jsonl", ".py"}]
    paths += [CASE / "protocol.json", Path(__file__).resolve(), CASE / "independent_time_tracking_check.py"]
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def assert_public(value):
    forbidden = {"actors", "persons", "edges", "records", "record_ids", "payload", "predictions", "behavior", "targets", "selected_records", "record_history"}
    if isinstance(value, dict):
        if forbidden.intersection(value):
            raise ValueError("individual source data must not enter a public execution artifact")
        for item in value.values():
            assert_public(item)
    elif isinstance(value, list):
        for item in value:
            assert_public(item)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    arguments = parser.parse_args()
    private = arguments.private_root.absolute()
    resolved = private.resolve()
    if private.exists() or private.is_symlink() or resolved == ROOT or ROOT in resolved.parents or resolved in ROOT.parents:
        parser.error("private root must be a fresh directory outside and not containing the repository")
    for name in ("report.json", "execution.json"):
        if (CASE / name).exists():
            parser.error("recorded case outputs already exist; this runner never overwrites evidence")
    protocol, metadata = read(CASE / "protocol.json"), read(FIXTURE / "metadata.json")
    if protocol["fixture_metadata_file_sha256"] != digest(FIXTURE / "metadata.json"):
        raise ValueError("fixture differs from the protocol frozen before execution")
    for name, expected in metadata["input_file_sha256"].items():
        if digest(FIXTURE / name) != expected:
            raise ValueError("fixture input hash mismatch")
    before = source_hashes()
    started = datetime.now(timezone.utc).isoformat()
    start_clock = time.monotonic()
    private.mkdir(mode=0o700)
    store = private / "store"
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONHASHSEED="0")
    command = [sys.executable, "-m", "sociolab"]
    steps, receipts, sessions, creation_hashes = [], [], [], {}

    def observe_checkpoints():
        current = {path.name: digest(path) for path in sorted(store.glob("[0-9]*.json"))}
        if any(current.get(name) != checksum for name, checksum in creation_hashes.items()):
            raise ValueError("a retained checkpoint changed after creation")
        creation_hashes.update(current)
        return current

    def simple(label, arguments, *, source=None, expected=0):
        result = subprocess.run(command + arguments, input=source, capture_output=True, text=True,
                                cwd=ROOT, env=environment, timeout=30)
        if result.returncode != expected:
            raise ValueError(f"{label} returned {result.returncode}: {result.stderr}")
        if expected == 0 and result.stderr:
            raise ValueError(f"{label} unexpectedly wrote stderr")
        steps.append({"label": label, "command": arguments[:2], "exit_code": result.returncode})
        return result

    initial = json.loads(simple("initialize", ["tracking", "init", str(FIXTURE / metadata["initial_dataset"]),
                                               str(FIXTURE / metadata["registration"]), str(store)]).stdout)
    save(private / "initial-receipt.json", initial)
    observe_checkpoints()
    deliveries = [json.loads(line) for line in (FIXTURE / metadata["streams"]["all"]).read_text().splitlines()]
    if len(deliveries) != metadata["delivery_count"]:
        raise ValueError("delivery count differs from frozen metadata")
    competing_writer_rejected = False

    def check_receipt(receipt, number):
        label = metadata["stage_order"][number - 1]
        expected = metadata["stages"][label]
        if (receipt["status"] != expected["expected_receipt_status"]
                or receipt["sequence"] != expected["sequence"]
                or receipt["knowledge_cutoff"] != expected["knowledge_cutoff"]
                or receipt["cursor"] != expected["source_cursor"]
                or receipt["cursor_value"] != expected["source_cursor"]
                or receipt["source_time_unit"] != metadata["source_time_unit"]
                or receipt["transition_cause"] != expected["expected_transition_cause"]):
            raise ValueError("receipt differs from the predeclared cutoff/sequence/status")
        for view in receipt["views"]:
            reference = expected["views"][view["view_id"]]
            for field in ("person_count", "activity_count", "edge_count", "complete", "source_time", "snapshot_hash"):
                if view[field] != reference[field]:
                    raise ValueError("view summary differs from the fixed fixture expectation")
            if receipt["status"] in {"NO_NEW_RECORDS", "NO_TIME_ADVANCE"}:
                if view["changes"] is not None or view["comparison_status"] is not None:
                    raise ValueError("duplicate delivery fabricated a new view transition")
            else:
                flags = {name: reference[name] for name in FLAGS}
                if view["changes"] != flags:
                    raise ValueError("view change flags differ from predeclared semantics")
                if (view["comparison_status"] != reference["tracking_comparison_status"]
                        or view["comparison_reason"] != reference["tracking_comparison_reason"]):
                    raise ValueError("scheduled comparison differs from the fixed completeness/change policy")

    def live_session(first, last, *, kill):
        nonlocal competing_writer_rejected
        process = subprocess.Popen(command + ["tracking", "run", str(store)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   bufsize=1, cwd=ROOT, env=environment)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        acknowledged = 0
        try:
            for number in range(first, last + 1):
                if process.poll() is not None or process.stdin.closed:
                    raise ValueError("stream process exited before the next delivery")
                process.stdin.write(json.dumps(deliveries[number - 1], ensure_ascii=False, allow_nan=False) + "\n")
                process.stdin.flush()
                if not selector.select(timeout=15):
                    raise ValueError("no immediate receipt arrived while stdin remained open")
                line = process.stdout.readline()
                if not line:
                    raise ValueError("stream closed before acknowledging its delivery")
                receipt = json.loads(line)
                if process.stdin.closed or process.poll() is not None:
                    raise ValueError("receipt did not come from an ongoing open-input process")
                check_receipt(receipt, number)
                receipts.append(receipt)
                acknowledged += 1
                observe_checkpoints()
                if number == 1:
                    competing = simple("reject_competing_writer", ["tracking", "inspect", str(store)], expected=2)
                    competing_writer_rejected = "already in use" in competing.stderr and competing.stdout == ""
                    if not competing_writer_rejected:
                        raise ValueError("concurrent store access was not rejected cleanly")
            if kill:
                process.kill()
                exit_code = process.wait(timeout=10)
                process.stdin.close()
                if exit_code != -9:
                    raise ValueError("the first stream was not stopped by SIGKILL")
            else:
                process.stdin.close()
                exit_code = process.wait(timeout=10)
                if exit_code != 0:
                    raise ValueError("the restarted stream did not finish normally at EOF")
            if process.stdout.read() or process.stderr.read():
                raise ValueError("stream produced unexpected extra output")
            sessions.append({"index": len(sessions) + 1, "delivery_start_1based": first,
                             "delivery_end_1based": last, "acknowledged_before_eof_count": acknowledged,
                             "exit_code": exit_code, "termination": "SIGKILL" if kill else "EOF"})
            steps.append({"label": "live_session_" + str(len(sessions)), "command": ["tracking", "run"],
                          "exit_code": exit_code, "deliveries": acknowledged})
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()

    split = metadata["restart_after_delivery"]
    live_session(1, split, kill=True)
    restart = json.loads(simple("inspect_after_kill", ["tracking", "inspect", str(store)]).stdout)
    if restart["checkpoint_hash"] != receipts[-1]["checkpoint_hash"]:
        raise ValueError("restart did not retain the last acknowledged checkpoint")
    save(private / "restart-inspect.json", restart)
    observe_checkpoints()
    live_session(split + 1, len(deliveries), kill=False)
    rejected_controls = []
    for negative in metadata["negative_cases"]:
        before_rejection = observe_checkpoints()
        rejected = simple(negative["expected"], ["tracking", "run", str(store)],
                          source=(FIXTURE / negative["file"]).read_text(), expected=2)
        if rejected.stdout or "tracking input line 1" not in rejected.stderr:
            raise ValueError("invalid control was not rejected at its input boundary")
        if observe_checkpoints() != before_rejection:
            raise ValueError("a rejected control modified the committed store")
        current = read(store / f"{receipts[-1]['sequence']:08d}.json")
        if current["content_hash"] != receipts[-1]["checkpoint_hash"]:
            raise ValueError("rejected control changed the current checkpoint")
        rejected_controls.append({"file": negative["file"], "expected": negative["expected"],
                                  "exit_code": rejected.returncode, "checkpoint_hash_preserved": True,
                                  "checkpoint_files_preserved": True})
    final = json.loads(simple("inspect_final", ["tracking", "inspect", str(store)]).stdout)
    if final["checkpoint_hash"] != receipts[-1]["checkpoint_hash"]:
        raise ValueError("final inspection changed the last acknowledged checkpoint")
    if len(creation_hashes) != metadata["expected_checkpoint_count_including_initial"]:
        raise ValueError("checkpoint count differs from the frozen protocol")
    after = source_hashes()
    if before != after:
        raise ValueError("implementation or inputs changed during execution")
    save(private / "final-inspect.json", final)
    save(private / "receipts.json", receipts)
    execution = {
        "kind": "TEMPORAL_NETWORK_TRACKING_EXECUTION", "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.monotonic() - start_clock,
        "source_hashes_before": before, "source_hashes_after": after,
        "checkpoint_creation_hashes": creation_hashes, "checkpoints_final_hashes": observe_checkpoints(),
        "sessions": sessions, "competing_writer_rejected": competing_writer_rejected,
        "rejected_controls": rejected_controls,
        "steps": steps, "runtime": {"python": platform.python_version(), "networkx": version("networkx")},
        "protocol_file_sha256": digest(CASE / "protocol.json"), "status": "PASS",
    }
    save(private / "execution-private.json", execution)
    report = {
        "kind": "SYNTHETIC_TEMPORAL_NETWORK_TRACKING_CASE", "origin": "synthetic", "status": "PASS",
        "delivery_count": len(receipts), "applied_count": sum(r["status"] == "APPLIED" for r in receipts),
        "no_new_records_count": sum(r["status"] == "NO_NEW_RECORDS" for r in receipts),
        "no_time_advance_count": sum(r["status"] == "NO_TIME_ADVANCE" for r in receipts),
        "applied_receipt_batch_count": sum(r["status"] == "APPLIED" and r["transition_cause"] == "receipt_batch" for r in receipts),
        "applied_source_time_advance_count": sum(r["status"] == "APPLIED" and r["transition_cause"] == "source_time_advance" for r in receipts),
        "checkpoint_count": len(creation_hashes), "registered_view_count": len(final["views"]),
        "final_knowledge_cutoff": final["knowledge_cutoff"], "final_sequence": final["sequence"],
        "final_cursor": final["cursor"], "source_time_unit": final["source_time_unit"],
        "acknowledgments_observed_before_eof": sum(session["acknowledged_before_eof_count"] for session in sessions),
        "forced_process_exit_recovered": sessions[0]["exit_code"] == -9,
        "all_retained_checkpoint_bytes_unchanged": execution["checkpoint_creation_hashes"] == execution["checkpoints_final_hashes"],
        "competing_writer_rejected": competing_writer_rejected, "rejected_controls": rejected_controls,
        "receipts": [{"stage": label, **receipt} for label, receipt in zip(metadata["stage_order"], receipts)],
        "scope": metadata["scope"], "protocol_file_sha256": execution["protocol_file_sha256"],
        "final_checkpoint_hash": final["checkpoint_hash"],
    }
    for value in (execution, report):
        assert_public(value)
    save(CASE / "execution.json", execution)
    save(CASE / "report.json", report)
    print(json.dumps({key: report[key] for key in ("status", "delivery_count", "checkpoint_count", "final_knowledge_cutoff", "final_cursor")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
