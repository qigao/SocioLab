"""Single-writer, append-only local storage for receipt-driven tracking.

A final numbered file is the commit marker. There is no mutable HEAD and no
rollback after publishing that file. Outputs can be retried with the same raw
records if a process exits after commit but before delivering its receipt.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat
from typing import TextIO
from uuid import uuid4

from ._json import unique_object
from .events import EventDataset
from .network_tracking import initialize_network_tracking, apply_network_tracking_batch
from .temporal_tracking import initialize_temporal_tracking, apply_temporal_tracking_batch, advance_temporal_tracking
from .snapshots import content_hash


CHECKPOINT_SCHEMA = "sociolab.network-tracking-checkpoint.v1"
BATCH_SCHEMA = "sociolab.network-tracking-batch.v1"
ADVANCE_SCHEMA = "sociolab.network-tracking-advance.v1"
TEMPORAL_STATE_SCHEMA = "sociolab.temporal-tracking-state.v1"
MAX_LINE_CHARACTERS = 1_048_576
_FINAL = re.compile(r"[0-9]{8}\.json\Z")
_PENDING = re.compile(r"\.pending-[0-9a-f]{32}\.json\Z")
_FLAGS = ("observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed")


def _initial_state(dataset: EventDataset, registration: dict) -> dict:
    if type(registration) is not dict:
        raise ValueError("tracking registration must be an object")
    if registration.get("schema") == "sociolab.network-tracking-spec.v1":
        return initialize_network_tracking(dataset, registration)
    if registration.get("schema") == "sociolab.temporal-tracking-spec.v1":
        return initialize_temporal_tracking(dataset, registration)
    raise ValueError("unsupported tracking registration schema")


def _apply_input(state: dict, request: dict) -> dict:
    if type(request) is not dict:
        raise ValueError("tracking input must be a JSON object")
    temporal = state["schema"] == TEMPORAL_STATE_SCHEMA
    if request.get("schema") == BATCH_SCHEMA:
        if set(request) != {"schema", "records", "received_at"}:
            raise ValueError("tracking batch requires schema, records and received_at")
        apply = apply_temporal_tracking_batch if temporal else apply_network_tracking_batch
        return apply(state, request["records"], received_at=request["received_at"])
    if request.get("schema") == ADVANCE_SCHEMA:
        if set(request) != {"schema", "cursor"}:
            raise ValueError("tracking advance requires only schema and cursor")
        if not temporal:
            raise ValueError("source-time advance requires a temporal tracking registration")
        return advance_temporal_tracking(state, request["cursor"])
    raise ValueError("unsupported tracking input schema")


def _json_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _locked_store(path: str | Path, *, create: bool = False):
    # flock releases automatically on process exit, including an abrupt exit.
    # Import here so unrelated SocioLab commands remain usable on other OSes.
    try:
        import fcntl
    except ImportError as error:
        raise ValueError("local tracking storage requires POSIX flock support") from error
    root = Path(path).absolute()
    if create:
        root.mkdir(mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("tracking store must be an existing, nonsymlink directory")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root / ".writer.lock", flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("tracking lock must be a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("tracking store is already in use by another process") from error
        try:
            yield root
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _checkpoint(state: dict, transition: dict | None, previous_hash: str | None) -> dict:
    value = {
        "schema": CHECKPOINT_SCHEMA, "sequence": state["sequence"],
        "previous_checkpoint_hash": previous_hash,
        "state": deepcopy(state), "transition": deepcopy(transition),
    }
    return {**value, "content_hash": content_hash(value)}


def _publish(root: Path, checkpoint: dict) -> None:
    sequence = checkpoint["sequence"]
    if type(sequence) is not int or not 0 <= sequence <= 99_999_999:
        raise ValueError("tracking checkpoint sequence exceeds the local filename scope")
    target = root / f"{sequence:08d}.json"
    pending = root / f".pending-{uuid4().hex}.json"
    published = False
    try:
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(_json_text(checkpoint))
            stream.flush()
            os.fsync(stream.fileno())
        # Unlike replace/rename, hard-link publication cannot overwrite an
        # existing final checkpoint. Both names are in the same directory.
        os.link(pending, target)
        published = True
        pending.unlink()
        _fsync_directory(root)
    except OSError as error:
        if published:
            raise OSError(
                "checkpoint was published but durability confirmation failed; "
                "inspect the store and retry the same records before sending new ones"
            ) from error
        raise
    finally:
        # Only this call's uncommitted temporary name may be removed. A final
        # file is authoritative even if fsync or output delivery later fails.
        try:
            if pending.exists():
                pending.unlink()
        except OSError:
            # A recognizable leftover is ignored on restart. Cleanup must not
            # hide the original error or remove an already published commit.
            pass


def _load_store(root: Path) -> dict:
    paths = []
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError("tracking store entries must be regular, nonsymlink files")
        if _FINAL.fullmatch(path.name):
            paths.append(path)
        elif path.name != ".writer.lock" and not _PENDING.fullmatch(path.name):
            raise ValueError("tracking store contains an unexpected filename")
    paths.sort()
    if not paths:
        raise ValueError("tracking store has no committed initial checkpoint")
    previous = None
    for sequence, path in enumerate(paths):
        if path.name != f"{sequence:08d}.json":
            raise ValueError("tracking checkpoint sequence has a gap")
        with path.open(encoding="utf-8") as stream:
            saved = json.load(stream, object_pairs_hook=unique_object)
        fields = {"schema", "sequence", "previous_checkpoint_hash", "state", "transition", "content_hash"}
        if type(saved) is not dict or set(saved) != fields or saved["schema"] != CHECKPOINT_SCHEMA:
            raise ValueError("invalid tracking checkpoint schema")
        if type(saved["sequence"]) is not int or saved["sequence"] != sequence:
            raise ValueError("tracking checkpoint sequence disagrees with its filename")
        if saved["content_hash"] != content_hash({k: v for k, v in saved.items() if k != "content_hash"}):
            raise ValueError("tracking checkpoint content hash mismatch")
        state = saved["state"]
        if type(state) is not dict or type(state.get("dataset")) is not dict:
            raise ValueError("tracking checkpoint requires a complete state and journal")
        journal = EventDataset.from_mapping(state["dataset"])
        if previous is None:
            if saved["previous_checkpoint_hash"] is not None or saved["transition"] is not None:
                raise ValueError("initial tracking checkpoint cannot have a predecessor or transition")
            expected_state = _initial_state(journal, state.get("registration"))
            expected_transition = None
        else:
            before = previous["state"]
            if saved["previous_checkpoint_hash"] != previous["content_hash"]:
                raise ValueError("tracking checkpoint predecessor hash mismatch")
            old_data, new_data = before["dataset"], journal.to_dict()
            old_records, new_records = old_data["records"], new_data["records"]
            if ({k: v for k, v in old_data.items() if k != "records"}
                    != {k: v for k, v in new_data.items() if k != "records"}
                    or len(new_records) < len(old_records)
                    or new_records[:len(old_records)] != old_records):
                raise ValueError("tracking journal must retain its exact envelope and complete receipt prefix")
            tail = new_records[len(old_records):]
            temporal = before["schema"] == TEMPORAL_STATE_SCHEMA
            transition = saved["transition"]
            if temporal and (type(transition) is not dict or transition.get("cause") not in {"receipt_batch", "source_time_advance"}):
                raise ValueError("temporal checkpoint requires an explicit transition cause")
            if temporal and transition["cause"] == "source_time_advance":
                if tail:
                    raise ValueError("source-time advance cannot append journal receipts")
                replay = advance_temporal_tracking(before, state.get("cursor"))
                if replay["transition"]["status"] != "APPLIED":
                    raise ValueError("a saved time checkpoint must advance its source cursor")
            else:
                if not tail:
                    raise ValueError("a saved receipt checkpoint must append new records")
                received_at = tail[0]["recorded_at"]
                if any(record["recorded_at"] != received_at for record in tail):
                    raise ValueError("one tracking commit must contain one receipt batch")
                raw = [{k: v for k, v in record.items() if k not in {"ingest_seq", "recorded_at"}}
                       for record in tail]
                apply = apply_temporal_tracking_batch if temporal else apply_network_tracking_batch
                replay = apply(before, raw, received_at=received_at)
            expected_state, expected_transition = replay["state"], replay["transition"]
        # Replay includes snapshots and upstream comparison reports at every
        # retained version. A changed runtime may require an explicit migration;
        # it must not silently rewrite or bless previously saved results.
        if _json_text(state) != _json_text(expected_state):
            raise ValueError("tracking state differs from replay of its journal and fixed registration")
        if _json_text(saved["transition"]) != _json_text(expected_transition):
            raise ValueError("tracking transition differs from replay of its committed receipt batch")
        previous = saved
    return previous


def _receipt(checkpoint: dict, *, status: str, request_transition: dict | None = None) -> dict:
    state = checkpoint["state"]
    transition = checkpoint["transition"] if request_transition is None else request_transition
    temporal = state["schema"] == TEMPORAL_STATE_SCHEMA
    changed = {} if transition is None or status != "APPLIED" else {
        row["view_id"]: row for row in transition["views"]
    }
    views = []
    for view in state["views"]:
        snapshot = view["snapshot"]
        update = changed.get(view["view_id"])
        comparison = None if update is None else update["comparison"]
        summary = {
            "view_id": view["view_id"], "snapshot_hash": snapshot["content_hash"],
            "person_count": len(snapshot["persons"]), "activity_count": len(snapshot["activities"]),
            "edge_count": len(snapshot["edges"]), "complete": snapshot["coverage"]["complete"],
            "changes": None if update is None else {name: update[name] for name in _FLAGS},
            "comparison_status": None if comparison is None else comparison["status"],
            "comparison_reason": None if comparison is None else comparison.get("reason"),
        }
        if temporal:
            summary["source_time"] = {key: snapshot["view"][key] for key in ("at", "start", "end") if key in snapshot["view"]}
        views.append(summary)
    receipt = {
        "kind": "NETWORK_TRACKING_RECEIPT", "status": status,
        "sequence": state["sequence"], "knowledge_cutoff": state["knowledge_cutoff"],
        "state_hash": state["content_hash"], "checkpoint_hash": checkpoint["content_hash"],
        "registration_hash": state["registration_hash"], "views": views,
        "fixed_source_views": not temporal, "source_authenticity_verified": False,
        "causal_effect_identified": False,
    }
    if temporal:
        receipt.update({
            "cursor": state["cursor"], "cursor_value": state["cursor_value"],
            "source_time_unit": state["registration"]["source_time_unit"],
            "view_templates_fixed": True,
            "transition_cause": None if request_transition is None else request_transition["cause"],
        })
    return receipt


def initialize_tracking_store(path: str | Path, dataset: EventDataset, registration: dict) -> dict:
    """Create a new private directory and its initial immutable checkpoint."""
    state = _initial_state(dataset, registration)
    checkpoint = _checkpoint(state, None, None)
    with _locked_store(path, create=True) as root:
        _publish(root, checkpoint)
        try:
            _fsync_directory(root.parent)
        except OSError as error:
            raise OSError("initial checkpoint was published but parent-directory durability confirmation failed; inspect the store") from error
    return _receipt(checkpoint, status="INITIALIZED")


def inspect_tracking_store(path: str | Path) -> dict:
    """Replay every committed version without replacing any saved file."""
    with _locked_store(path) as root:
        checkpoint = _load_store(root)
    return _receipt(checkpoint, status="INSPECTED")


def _commit_request(root: Path, checkpoint: dict, request: dict) -> tuple[dict, dict]:
    """Apply one input under the caller's writer lock and retain its result."""
    result = _apply_input(checkpoint["state"], request)
    status = result["transition"]["status"]
    if status == "APPLIED":
        new_checkpoint = _checkpoint(result["state"], result["transition"], checkpoint["content_hash"])
        _publish(root, new_checkpoint)
        checkpoint = new_checkpoint
    elif status not in {"NO_NEW_RECORDS", "NO_TIME_ADVANCE"}:
        raise ValueError("unsupported tracking transition status")
    return checkpoint, _receipt(checkpoint, status=status, request_transition=result["transition"])


def _write_receipt(output: TextIO, receipt: dict) -> None:
    try:
        output.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        output.flush()
    except OSError as error:
        raise OSError(
            "tracking output delivery failed; the checkpoint may already be committed; "
            "inspect the store and retry the same records"
        ) from error


def consume_tracking_stream(path: str | Path, source: TextIO, output: TextIO) -> int:
    """Commit one strict receipt batch or source-time control per line.

    EOF ends the process normally. While the input remains open, a successful
    line is committed and acknowledged before the next line is requested.
    Duplicate records yield NO_NEW_RECORDS at the current head; this is record
    idempotence, not a batch-ID ledger or exactly-once output delivery. Temporal
    stores also accept forward source-time controls; they keep the journal/K
    unchanged. An equal cursor yields NO_TIME_ADVANCE without a checkpoint.
    """
    processed = 0
    with _locked_store(path) as root:
        checkpoint = _load_store(root)
        while True:
            line = source.readline(MAX_LINE_CHARACTERS + 1)
            if not line:
                return processed
            processed += 1
            try:
                if len(line) > MAX_LINE_CHARACTERS:
                    raise ValueError("tracking batch line exceeds the character limit")
                request = json.loads(line, object_pairs_hook=unique_object)
                checkpoint, receipt = _commit_request(root, checkpoint, request)
            except ValueError as error:
                raise ValueError(f"tracking input line {processed}: {error}") from error
            except OSError as error:
                raise OSError(f"tracking input line {processed}: {error}") from error
            _write_receipt(output, receipt)
