"""A local UTC wall-clock driver for the existing immutable temporal store.

One synchronous writer accepts receipt batches and samples UTC at fixed-delay
monotonic deadlines. Input, analysis, durable writes and output share this loop;
backpressure can delay a sample, and skipped instants are never reconstructed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import time
from typing import TextIO

from ._json import unique_object
from .temporal_tracking import _format_time
from .tracking_store import (
    ADVANCE_SCHEMA, BATCH_SCHEMA, MAX_LINE_CHARACTERS, TEMPORAL_STATE_SCHEMA,
    _commit_request, _load_store, _locked_store, _write_receipt,
)

_READ_CHUNK_BYTES = 65_536


def _sample_cursor(state: dict) -> str:
    # The wall clock supplies a UTC query position, while monotonic time only
    # schedules when to sample it. No receipt or source timestamp is rewritten.
    value = time.time_ns() // 1_000
    if value < state["cursor_value"]:
        raise ValueError("UTC wall clock is behind the saved source-time cursor; no backward advance is allowed")
    return _format_time(value, state["dataset"]["clock"])


def _request(line: bytes) -> dict:
    text = line.decode("utf-8")
    if len(text) > MAX_LINE_CHARACTERS:
        raise ValueError("tracking batch line exceeds the character limit")
    request = json.loads(text, object_pairs_hook=unique_object)
    if type(request) is not dict or request.get("schema") != BATCH_SCHEMA:
        raise ValueError("live tracking input accepts receipt batches only")
    return request


def consume_live_tracking_stream(path: str | Path, source_fd: int, output: TextIO,
                                 *, interval_ms: int = 1000) -> int:
    """Drive a UTC temporal store until stdin EOF, returning its request count.

    Only receipt batches are accepted from the descriptor. An equal sampled UTC
    emits the existing NO_TIME_ADVANCE receipt; a backward wall clock fails.
    Each timer uses current UTC, and its next deadline is completion + interval.

    A partial line does not block the timer. Observed EOF stops further timers
    and drains buffered lines, accepting a valid final JSON line without LF.
    The caller's descriptor stays open and its blocking mode is restored.
    """
    if type(interval_ms) is not int or not 1 <= interval_ms <= 86_400_000:
        raise ValueError("interval_ms must be an integer from 1 through 86400000")
    if type(source_fd) is not int or source_fd < 0:
        raise ValueError("source_fd must be a nonnegative integer descriptor")
    interval_ns = interval_ms * 1_000_000
    # UTF-8 needs at most four bytes per character. One extra byte permits
    # detecting an oversized incomplete line without an unbounded read/queue.
    max_line_bytes = 4 * MAX_LINE_CHARACTERS
    processed = 0
    with _locked_store(path) as root:
        checkpoint = _load_store(root)
        state = checkpoint["state"]
        if state["schema"] != TEMPORAL_STATE_SCHEMA or state["dataset"]["clock"]["kind"] != "utc":
            raise ValueError("live tracking requires a UTC temporal tracking store")
        _sample_cursor(state)  # fail before consuming input or publishing a version
        was_blocking = os.get_blocking(source_fd)
        os.set_blocking(source_fd, False)
        try:
            deadline = time.monotonic_ns() + interval_ns
            pending = bytearray()
            eof = False
            while True:
                if eof and not pending:
                    return processed
                if not eof:
                    # With complete buffered lines, poll once rather than wait.
                    # At a due deadline, probe readiness before timing so an
                    # observed EOF wins over a simultaneous timer opportunity.
                    timeout = 0.0 if b"\n" in pending else max(0, deadline - time.monotonic_ns()) / 1_000_000_000
                    ready, _, _ = select.select([source_fd], [], [], timeout)
                    capacity = max_line_bytes + 1 - len(pending)
                    if ready and capacity > 0:
                        try:
                            chunk = os.read(source_fd, min(_READ_CHUNK_BYTES, capacity))
                        except BlockingIOError:
                            chunk = None
                        if chunk == b"":
                            eof = True
                        elif chunk is not None:
                            pending.extend(chunk)
                    if not eof and time.monotonic_ns() >= deadline:
                        cursor = _sample_cursor(checkpoint["state"])
                        checkpoint, receipt = _commit_request(
                            root, checkpoint, {"schema": ADVANCE_SCHEMA, "cursor": cursor},
                        )
                        _write_receipt(output, receipt)
                        deadline = time.monotonic_ns() + interval_ns

                if eof and not pending:
                    return processed
                newline = pending.find(b"\n")
                if newline >= 0:
                    line = bytes(pending[:newline + 1])
                    del pending[:newline + 1]
                elif eof:
                    line = bytes(pending)
                    pending.clear()
                else:
                    if len(pending) > max_line_bytes:
                        raise ValueError(f"tracking input line {processed + 1}: incomplete line exceeds the UTF-8 byte limit")
                    continue

                # Decode only this line. A malformed later line from the same
                # os.read chunk must not erase an earlier successful commit.
                processed += 1
                try:
                    request = _request(line)
                    checkpoint, receipt = _commit_request(root, checkpoint, request)
                except ValueError as error:
                    raise ValueError(f"tracking input line {processed}: {error}") from error
                except OSError as error:
                    raise OSError(f"tracking input line {processed}: {error}") from error
                _write_receipt(output, receipt)
        finally:
            os.set_blocking(source_fd, was_blocking)
