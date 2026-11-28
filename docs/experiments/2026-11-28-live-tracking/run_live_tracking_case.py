"""Run the frozen live UTC case once; retain actual inputs and stores privately."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import selectors
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
FIXTURE = ROOT / "examples/live-tracking/generate_fixture.py"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def micros(value):
    delta = datetime.fromisoformat(value.replace("Z", "+00:00")) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def source_hashes():
    paths = list((ROOT / "src/sociolab").glob("*.py"))
    paths += list((ROOT / "tests").glob("test_*tracking*.py"))
    paths += [FIXTURE, CASE / "protocol.json", Path(__file__).resolve(),
              CASE / "independent_live_tracking_check.py"]
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def assert_public(value):
    forbidden = {"actors", "persons", "edges", "records", "record_ids", "payload",
                 "predictions", "behavior", "targets", "selected_records", "record_history"}
    if isinstance(value, dict):
        if forbidden.intersection(value):
            raise ValueError("individual source values cannot enter public execution evidence")
        for item in value.values():
            assert_public(item)
    elif isinstance(value, list):
        for item in value:
            assert_public(item)


class PrivateArtifacts:
    """Freeze each completed non-store file once; never refresh its first hash."""

    def __init__(self, root):
        self.root = root
        self.creation = {}

    def save_bytes(self, name, data):
        if Path(name).name != name or name in self.creation:
            raise ValueError("private artifact must have a new flat filename")
        path = self.root / name
        with path.open("xb") as stream:
            stream.write(data)
        self.creation[name] = digest(path)

    def save_json(self, name, value):
        encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                              indent=2, allow_nan=False) + "\n").encode("utf-8")
        self.save_bytes(name, encoded)

    def inventory(self, *, exclusions=("execution-private.json",)):
        current = {}
        for path in sorted(self.root.iterdir()):
            if path.name == "store":
                if path.is_symlink() or not path.is_dir():
                    raise ValueError("private store must remain a nonsymlink directory")
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError("private artifact must remain a regular nonsymlink file")
            if path.name not in exclusions:
                current[path.name] = digest(path)
        return current

    def validate(self):
        current = self.inventory()
        if current != self.creation:
            raise ValueError("private artifact bytes or file inventory changed after first save")
        return current


class LiveSession:
    def __init__(self, number, command, environment, private, receipts, observe, interval_ms, artifacts):
        self.number, self.private = number, private
        self.receipts, self.observe, self.artifacts = receipts, observe, artifacts
        self.started_at = stamp()
        self.first = len(receipts)
        self.process = subprocess.Popen(
            command + ["tracking", "live", str(private / "store"), "--interval-ms", str(interval_ms)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, cwd=ROOT, env=environment,
        )
        self.selector = selectors.DefaultSelector()
        for stream in (self.process.stdout, self.process.stderr):
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ)
        self.raw = {self.process.stdout: bytearray(), self.process.stderr: bytearray()}
        self.pending = bytearray()
        self.stdin_bytes = bytearray()
        self.input_writes = []
        self.write_errors = []
        self.close_errors = []
        self.termination = "ABORTED"
        self.observed_before_close = None
        self.closed = False

    def poll_output(self, timeout, *, parse_receipts=True):
        for key, _ in self.selector.select(timeout):
            try:
                data = os.read(key.fileobj.fileno(), 65536)
            except BlockingIOError:
                continue
            if not data:
                self.selector.unregister(key.fileobj)
                continue
            self.raw[key.fileobj].extend(data)
            if key.fileobj is self.process.stdout:
                self.pending.extend(data)
                while parse_receipts and b"\n" in self.pending:
                    line, _, tail = self.pending.partition(b"\n")
                    self.pending = bytearray(tail)
                    receipt = json.loads(line.decode("utf-8"))
                    if receipt.get("kind") != "NETWORK_TRACKING_RECEIPT":
                        raise ValueError("live output is not an ordinary tracking receipt")
                    self.receipts.append(receipt)
                    self.observe()

    def until(self, predicate, *, start=None):
        index = len(self.receipts) if start is None else start
        deadline = time.monotonic() + 30
        while True:
            while index < len(self.receipts):
                if predicate(self.receipts[index]):
                    return index
                index += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("predeclared live-case phase timed out")
            if self.process.poll() is not None:
                raise ValueError("live process exited before completing its phase")
            self.poll_output(min(remaining, 1))

    def send(self, value):
        if self.process.poll() is not None or self.process.stdin.closed:
            raise ValueError("input process is not live")
        entry = {"index": len(self.input_writes) + 1, "offset": len(self.stdin_bytes),
                 "requested_byte_count": len(value), "byte_count": None,
                 "started_at": stamp(), "write_succeeded": False}
        try:
            sent = self.process.stdin.write(value)
            if type(sent) is int and 0 <= sent <= len(value):
                entry["byte_count"] = sent
                self.stdin_bytes.extend(value[:sent])
            else:
                raise ValueError("stdin write did not report an accepted byte count")
            if sent != len(value):
                raise ValueError("case input was not fully delivered")
            self.process.stdin.flush()
            entry["write_succeeded"] = True
        except BaseException as error:
            self.write_errors.append({"index": entry["index"], "type": type(error).__name__, "message": str(error)})
            raise
        finally:
            entry["finished_at"] = stamp()
            self.input_writes.append(entry)

    def drain(self, *, parse_receipts):
        deadline = time.monotonic() + 10
        while self.selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("live process did not close its output")
            self.poll_output(min(remaining, 1), parse_receipts=parse_receipts)

    def finish(self, *, kill):
        self.observed_before_close = len(self.receipts) - self.first
        self.termination = "SIGKILL" if kill else "EOF"
        try:
            if kill:
                self.process.kill()
            self.process.stdin.close()
            self.drain(parse_receipts=True)
            code = self.process.wait(timeout=10)
            if code != (-9 if kill else 0):
                raise ValueError("live process exit differs from SIGKILL/EOF protocol")
            if self.raw[self.process.stderr]:
                raise ValueError("live process unexpectedly produced stderr")
            if not kill and self.pending:
                raise ValueError("normal EOF left an incomplete output line")
        finally:
            self.close()
        if self.close_errors:
            raise ValueError("live session evidence could not be preserved completely")
        return self.summary()

    def summary(self):
        stdout_name = f"stdout-session{self.number}.bin"
        stderr_name = f"stderr-session{self.number}.txt"
        stdin_name = f"stdin-session{self.number}.bin"
        writes_name = f"stdin-session{self.number}-writes.json"
        return {
            "index": self.number, "started_at": self.started_at, "finished_at": self.finished_at,
            "exit_code": self.process.poll(), "termination": self.termination,
            "receipt_start_index": self.first, "receipt_end_index_exclusive": self.end,
            "observed_before_stdin_close_count": self.observed_before_close,
            "stdout_file": stdout_name, "stdout_sha256": self.artifacts.creation.get(stdout_name),
            "stderr_file": stderr_name, "stderr_sha256": self.artifacts.creation.get(stderr_name),
            "stdin_file": stdin_name, "stdin_sha256": self.artifacts.creation.get(stdin_name),
            "stdin_writes_file": writes_name, "stdin_writes_sha256": self.artifacts.creation.get(writes_name),
            "input_writes": list(self.input_writes),
            "unterminated_stdout_bytes": len(self.pending),
        }

    def close(self):
        if self.closed:
            return

        def preserve(action):
            try:
                action()
            except BaseException as error:
                self.close_errors.append({"type": type(error).__name__, "message": str(error)})

        if self.observed_before_close is None:
            self.observed_before_close = len(self.receipts) - self.first
        if self.process.poll() is None:
            preserve(self.process.kill)
        if not self.process.stdin.closed:
            preserve(self.process.stdin.close)
        # On failures, drain bytes without reparsing malformed output or
        # repeating a failed checkpoint assertion. Preserve even a partial tail.
        preserve(lambda: self.drain(parse_receipts=False))
        preserve(lambda: self.process.wait(timeout=10))
        preserve(lambda: self.artifacts.save_bytes(f"stdout-session{self.number}.bin", self.raw[self.process.stdout]))
        preserve(lambda: self.artifacts.save_bytes(f"stderr-session{self.number}.txt", self.raw[self.process.stderr]))
        preserve(lambda: self.artifacts.save_bytes(f"stdin-session{self.number}.bin", self.stdin_bytes))
        preserve(lambda: self.artifacts.save_json(f"stdin-session{self.number}-writes.json", self.input_writes))
        preserve(self.selector.close)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if not stream.closed:
                preserve(stream.close)
        self.finished_at = stamp()
        self.end = len(self.receipts)
        self.closed = True


def run_case(private, protocol, before, started_at, started_clock, artifacts, active_sessions, attempt):
    spec = importlib.util.spec_from_file_location("invented_live_fixture", FIXTURE)
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    anchor = stamp()
    fixture = fixture_module.build_fixture(anchor)
    filenames = {"dataset": "initial.events.json", "registration": "registration.json",
                 "late_batch": "late.batch.json", "metadata": "fixture-metadata.json"}
    for key, name in filenames.items():
        artifacts.save_json(name, fixture[key])
    input_hashes = {name: digest(private / name) for name in filenames.values()}
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONHASHSEED="0")
    command = [sys.executable, "-m", "sociolab"]
    store = private / "store"
    receipts, sessions, creation, phases, simple_commands = [], [], {}, {}, []
    attempt.update(receipts=receipts, sessions=sessions, checkpoints=creation,
                   phases=phases, simple_commands=simple_commands)

    def observe():
        current = {path.name: digest(path) for path in sorted(store.glob("[0-9]*.json"))}
        if any(current.get(name) != value for name, value in creation.items()):
            raise ValueError("a retained checkpoint changed or disappeared")
        creation.update(current)
        return current

    def simple(arguments, expected=0):
        number = len(simple_commands) + 1
        item = {"index": number, "command": list(arguments), "started_at": stamp()}
        simple_commands.append(item)
        try:
            result = subprocess.run(command + arguments, capture_output=True,
                                    cwd=ROOT, env=environment, timeout=30)
        except subprocess.TimeoutExpired as error:
            artifacts.save_bytes(f"stdout-command{number}.bin", error.stdout or b"")
            artifacts.save_bytes(f"stderr-command{number}.bin", error.stderr or b"")
            item.update(finished_at=stamp(), timed_out=True)
            raise
        artifacts.save_bytes(f"stdout-command{number}.bin", result.stdout)
        artifacts.save_bytes(f"stderr-command{number}.bin", result.stderr)
        item.update(finished_at=stamp(), exit_code=result.returncode, timed_out=False)
        result.stdout, result.stderr = result.stdout.decode("utf-8"), result.stderr.decode("utf-8")
        if result.returncode != expected or (expected == 0 and result.stderr):
            raise ValueError(f"case CLI command failed with exit {result.returncode}")
        return result

    def view(receipt, identifier):
        return next(item for item in receipt["views"] if item["view_id"] == identifier)

    initial = json.loads(simple(["tracking", "init", str(private / "initial.events.json"),
                                 str(private / "registration.json"), str(store)]).stdout)
    artifacts.save_json("initial-receipt.json", initial)
    observe()
    if initial["knowledge_cutoff"] != 13 or view(initial, "communication")["edge_count"] != 1:
        raise ValueError("initial snapshot differs from frozen fixture")
    initial_journal = read(store / "00000000.json")["state"]["dataset"]
    expiry = micros(anchor) + 2_000_000
    first = LiveSession(1, command, environment, private, receipts, observe, protocol["interval_ms"], artifacts)
    active_sessions.append(first)
    try:
        expired = first.until(lambda r: r["status"] == "APPLIED" and r["transition_cause"] == "source_time_advance" and r["cursor_value"] > expiry,
                              start=first.first)
        if receipts[expired]["knowledge_cutoff"] != 13 or view(receipts[expired], "communication")["edge_count"] != 0:
            raise ValueError("idle clock did not expire the event at unchanged K")
        phases["idle_expiry"] = {"receipt_index": expired, "expiry_boundary_utc": fixture["metadata"]["expiry_boundary_utc"]}
        competing = simple(["tracking", "inspect", str(store)], expected=2)
        competing_rejected = "already in use" in competing.stderr and not competing.stdout
        if not competing_rejected:
            raise ValueError("simultaneous store access was not rejected")

        encoded = (json.dumps(fixture["late_batch"], ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        artifacts.save_bytes("late-input.jsonl", encoded)
        split = len(encoded) // 2
        partial = {"sent_after_receipt_count": len(receipts), "first_chunk_bytes": split,
                   "total_line_bytes": len(encoded)}
        first.send(encoded[:split])
        partial["started_at"] = stamp()
        partial_us = micros(partial["started_at"])
        progressed = []
        start = len(receipts)
        for _ in range(2):
            index = first.until(lambda r: r["status"] == "APPLIED" and r["transition_cause"] == "source_time_advance" and r["cursor_value"] >= partial_us,
                                start=start)
            progressed.append(index)
            if receipts[index]["knowledge_cutoff"] != 13:
                raise ValueError("partial input created a source receipt")
            checkpoint = read(store / f"{receipts[index]['sequence']:08d}.json")
            if checkpoint["state"]["dataset"] != initial_journal:
                raise ValueError("idle time update changed the complete journal")
            start = index + 1
        partial["observed_receipt_indices"] = progressed
        partial["finished_at"] = stamp()
        phases["partial_line"] = partial
        first.send(encoded[split:])
        correction = first.until(lambda r: r["transition_cause"] == "receipt_batch", start=start)
        if receipts[correction]["status"] != "APPLIED" or receipts[correction]["knowledge_cutoff"] != 14:
            raise ValueError("late correction was not appended once")
        saved = read(store / f"{receipts[correction]['sequence']:08d}.json")
        if saved["transition"]["before_cursor"] != saved["transition"]["after_cursor"]:
            raise ValueError("receipt correction moved source cursor")
        if not view(receipts[correction], "cooperation")["changes"]["observed_graph_changed"]:
            raise ValueError("late correction did not change the cooperation graph")
        phases["correction"] = {"receipt_index": correction}
        first.until(lambda r: r["status"] == "APPLIED" and r["transition_cause"] == "source_time_advance" and r["knowledge_cutoff"] == 14,
                    start=correction + 1)
        phases["sigkill"] = {"last_observed_receipt_index": len(receipts) - 1, "killed_at": stamp()}
        sessions.append(first.finish(kill=True))
    finally:
        first.close()

    restart = json.loads(simple(["tracking", "inspect", str(store)]).stdout)
    artifacts.save_json("restart-inspect.json", restart)
    observe()
    acknowledged = {r["sequence"] for r in receipts if r["status"] == "APPLIED"}
    unacknowledged = set(range(1, restart["sequence"] + 1)) - acknowledged
    if restart["sequence"] < max(acknowledged) or restart["knowledge_cutoff"] != 14:
        raise ValueError("restart lost an acknowledged version or changed K")
    for sequence in unacknowledged:
        item = read(store / f"{sequence:08d}.json")
        if item["transition"]["cause"] != "source_time_advance":
            raise ValueError("an unacknowledged published checkpoint was not a time advance")
    phases["sigkill"].update({
        "recovered_sequence": restart["sequence"], "recovered_knowledge_cutoff": restart["knowledge_cutoff"],
        "recovered_cursor": restart["cursor"], "recovered_checkpoint_hash": restart["checkpoint_hash"],
        "unacknowledged_published_count": len(unacknowledged),
    })
    second = LiveSession(2, command, environment, private, receipts, observe, protocol["interval_ms"], artifacts)
    active_sessions.append(second)
    try:
        advanced = second.until(lambda r: r["status"] == "APPLIED" and r["transition_cause"] == "source_time_advance" and r["cursor_value"] > restart["cursor_value"],
                                start=second.first)
        phases["restart"] = {"first_auto_receipt_index": advanced}
        sent_at_count = len(receipts)
        second.send(encoded)
        duplicate = second.until(lambda r: r["transition_cause"] == "receipt_batch", start=sent_at_count)
        if receipts[duplicate]["status"] != "NO_NEW_RECORDS" or receipts[duplicate]["knowledge_cutoff"] != 14:
            raise ValueError("restarted receipt retry did not remain idempotent")
        phases["duplicate"] = {"receipt_index": duplicate}
        phases["eof"] = {"sent_after_receipt_count": len(receipts)}
        sessions.append(second.finish(kill=False))
    finally:
        second.close()

    final = json.loads(simple(["tracking", "inspect", str(store)]).stdout)
    artifacts.save_json("final-inspect.json", final)
    artifacts.save_json("receipts.json", receipts)
    if final["knowledge_cutoff"] != 14 or view(final, "communication")["edge_count"] != 0:
        raise ValueError("final observed state differs from the frozen expectation")
    if final["checkpoint_hash"] != receipts[-1]["checkpoint_hash"]:
        raise ValueError("normal EOF did not acknowledge its final committed version")
    after = source_hashes()
    if before != after:
        raise ValueError("executed implementation, fixture or protocol changed")
    input_hashes_after = {name: digest(private / name) for name in input_hashes}
    if input_hashes_after != input_hashes:
        raise ValueError("runtime inputs changed after their initial save")
    private_hashes_final = artifacts.validate()
    final_checkpoints = observe()
    execution = {
        "kind": "LIVE_NETWORK_TRACKING_EXECUTION", "status": "PASS",
        "started_at": started_at, "finished_at": stamp(), "elapsed_seconds": time.monotonic() - started_clock,
        "anchor_utc": anchor, "protocol_file_sha256": digest(CASE / "protocol.json"),
        "input_file_sha256": input_hashes, "source_hashes_before": before, "source_hashes_after": after,
        "input_file_sha256_after": input_hashes_after,
        "private_artifact_creation_hashes": dict(artifacts.creation),
        "private_artifact_final_hashes": private_hashes_final, "private_artifacts_unchanged": True,
        "private_artifact_hash_exclusions": ["execution-private.json"],
        "private_artifact_hash_exclusion_reason": "execution-private.json is the final self-describing manifest; including its own hash would be recursive",
        "checkpoint_creation_hashes": dict(creation), "checkpoints_final_hashes": final_checkpoints,
        "sessions": sessions, "phases": phases, "competing_writer_rejected": competing_rejected,
        "runtime": {"python": platform.python_version(), "networkx": version("networkx")},
    }
    report = {
        "kind": "SYNTHETIC_LIVE_NETWORK_TRACKING_CASE", "status": "PASS", "origin": "synthetic",
        "initial_knowledge_cutoff": 13, "final_knowledge_cutoff": final["knowledge_cutoff"],
        "final_sequence": final["sequence"], "final_cursor": final["cursor"],
        "source_time_unit": "microsecond", "interval_ms": protocol["interval_ms"],
        "window_width_microseconds": 3_000_000, "registered_view_count": len(final["views"]),
        "checkpoint_count": len(creation), "observed_receipt_count": len(receipts),
        "applied_time_ack_count": sum(r["status"] == "APPLIED" and r["transition_cause"] == "source_time_advance" for r in receipts),
        "applied_receipt_ack_count": sum(r["status"] == "APPLIED" and r["transition_cause"] == "receipt_batch" for r in receipts),
        "no_new_records_count": sum(r["status"] == "NO_NEW_RECORDS" for r in receipts),
        "no_time_advance_count": sum(r["status"] == "NO_TIME_ADVANCE" for r in receipts),
        "unacknowledged_published_count": len(unacknowledged), "partial_input_timer_progress_count": len(progressed),
        "recovery_after_sigkill": True, "competing_writer_rejected": competing_rejected,
        "all_retained_checkpoint_bytes_unchanged": execution["checkpoint_creation_hashes"] == execution["checkpoints_final_hashes"],
        "initial_view_edge_counts": {v["view_id"]: v["edge_count"] for v in initial["views"]},
        "final_view_edge_counts": {v["view_id"]: v["edge_count"] for v in final["views"]},
        "receipts": receipts, "final_checkpoint_hash": final["checkpoint_hash"],
        "protocol_file_sha256": execution["protocol_file_sha256"],
        "scope": {
            "engineering_fixture_only": True, "real_social_observations_used": False,
            "actual_local_wall_clock_driver": True, "source_timestamps_invented_relative_to_anchor": True,
            "receipt_timestamps_invented": True, "source_authenticity_verified": False,
            "source_cursor_is_completeness_watermark": False, "external_source_subscription": False,
            "physical_power_loss_experiment": False, "latency_sla_validated": False,
            "exactly_once_output_delivery_claimed": False, "empirical_prediction_validated": False,
            "causal_effect_identified": False,
        },
    }
    for value in (execution, report):
        assert_public(value)
    save(private / "execution-private.json", execution)
    artifacts.validate()  # also reject unexpected files after the manifest is saved
    save(CASE / "execution.json", execution)
    save(CASE / "report.json", report)
    print(json.dumps({key: report[key] for key in ("status", "checkpoint_count", "observed_receipt_count", "final_knowledge_cutoff", "partial_input_timer_progress_count")}, sort_keys=True))
    return 0


def retain_failure(private, artifacts, active_sessions, attempt, error, before, started_at):
    """Retain detailed failures privately and publish only aggregate FAIL state."""
    for session in active_sessions:
        session.close()
    preservation_errors = []

    def capture(action, fallback):
        try:
            return action()
        except BaseException as problem:
            preservation_errors.append({"type": type(problem).__name__, "message": str(problem)})
            return fallback

    exclusions = ["execution-private.json", "failure-private.json"]
    final_hashes = capture(lambda: artifacts.inventory(exclusions=exclusions), None)
    after = capture(source_hashes, None)
    checkpoint_hashes = capture(
        lambda: {path.name: digest(path) for path in sorted((private / "store").glob("[0-9]*.json"))}, None)
    details = {
        "kind": "LIVE_NETWORK_TRACKING_FAILED_ATTEMPT", "status": "FAIL",
        "started_at": started_at, "finished_at": stamp(),
        "error": {"type": type(error).__name__, "message": str(error),
                  "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))},
        "source_hashes_before": before, "source_hashes_after": after,
        "private_artifact_creation_hashes": dict(artifacts.creation),
        "private_artifact_final_hashes": final_hashes,
        "private_artifact_hash_exclusions": exclusions,
        "private_artifact_hash_exclusion_reason": "final self-describing execution/failure manifests are excluded to avoid recursive hashes",
        "checkpoint_creation_hashes": dict(attempt.get("checkpoints", {})),
        "checkpoints_final_hashes": checkpoint_hashes,
        "attempt": attempt,
        "live_sessions": [{"summary": session.summary(), "write_errors": session.write_errors,
                           "preservation_errors": session.close_errors} for session in active_sessions],
        "preservation_errors": preservation_errors,
        "automatic_retry_performed": False,
    }
    capture(lambda: save(private / "failure-private.json", details), None)
    failure_manifest_hash = capture(lambda: digest(private / "failure-private.json"), None)
    public = {
        "kind": "LIVE_NETWORK_TRACKING_FAILED_ATTEMPT", "status": "FAIL",
        "started_at": started_at, "finished_at": stamp(), "error_type": type(error).__name__,
        "session_count": len(active_sessions),
        "observed_receipt_count": len(attempt.get("receipts", [])),
        "retained_checkpoint_count": None if checkpoint_hashes is None else len(checkpoint_hashes),
        "retained_private_artifact_count": None if final_hashes is None else len(final_hashes),
        "private_artifacts_unchanged": final_hashes is not None and final_hashes == artifacts.creation,
        "source_hashes_unchanged": after is not None and before == after,
        "preservation_error_count": len(preservation_errors) + sum(len(s.close_errors) for s in active_sessions),
        "private_failure_manifest_sha256": failure_manifest_hash,
        "automatic_retry_performed": False, "existing_outputs_overwritten": False,
    }
    assert_public(public)
    capture(lambda: save(CASE / "failure.json", public), None)
    print(json.dumps({"status": "FAIL", "error_type": type(error).__name__,
                      "automatic_retry_performed": False, "failure_evidence_error_count": len(preservation_errors)}, sort_keys=True))
    return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    args = parser.parse_args()
    private = args.private_root.absolute()
    resolved = private.resolve()
    if private.exists() or private.is_symlink() or resolved == ROOT or ROOT in resolved.parents or resolved in ROOT.parents:
        parser.error("private root must be fresh, outside and not containing the repository")
    if any((CASE / name).exists() for name in ("execution.json", "report.json", "failure.json")):
        parser.error("recorded case outputs already exist; evidence is never overwritten or retried")
    protocol = read(CASE / "protocol.json")
    if protocol["fixture_generator_sha256"] != digest(FIXTURE):
        raise ValueError("fixture generator differs from the frozen protocol")
    if protocol["independent_checker_sha256"] != digest(CASE / "independent_live_tracking_check.py"):
        raise ValueError("checker differs from the frozen protocol")
    before, started_at, started_clock = source_hashes(), stamp(), time.monotonic()
    private.mkdir(mode=0o700)
    artifacts, active_sessions, attempt = PrivateArtifacts(private), [], {}
    try:
        return run_case(private, protocol, before, started_at, started_clock,
                        artifacts, active_sessions, attempt)
    except BaseException as error:
        return retain_failure(private, artifacts, active_sessions, attempt, error, before, started_at)


if __name__ == "__main__":
    raise SystemExit(main())
