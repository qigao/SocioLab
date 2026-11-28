"""Deterministic fd framing, independent clocks and durable live operations."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sociolab.events import EventDataset, ingest_records, parse_time
from sociolab.live_tracking import consume_live_tracking_stream
from sociolab.tracking_store import (
    ADVANCE_SCHEMA, BATCH_SCHEMA, _load_store, initialize_tracking_store, inspect_tracking_store,
)
from test_temporal_tracking_store import temporal_inputs
from test_tracking_store import inputs as fixed_inputs, saved_bytes


BASE = datetime(2026, 11, 28, tzinfo=timezone.utc)
BASE_US = parse_time("2026-11-28T00:00:00Z", {"kind": "utc"})


def at(microseconds=0):
    return (BASE + timedelta(microseconds=microseconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def raw(identifier, kind, payload, *, when=-10_000_000, interval=None):
    return {
        "record_id": identifier, "fact_id": identifier, "operation": "assert", "supersedes": None,
        "kind": kind, "occurred_at": at(when), "valid_interval": interval,
        "source": {"system": "invented-live-test", "record_id": identifier,
                   "revision": "v1", "evidence_ref": "synthetic:" + identifier}, "payload": payload,
    }


def inputs():
    empty = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "invented-live-test", "origin": "synthetic",
        "source_revision": "fixed-envelope", "clock": {"kind": "utc"}, "records": [],
    })
    records = [raw("person-" + p, "entity.observed", {"entity_id": p, "entity_type": "person"}) for p in "AB"]
    records += [raw("join-" + p, "membership.changed", {"actor": p, "population": "team", "status": "present"}) for p in "AB"]
    records.append(raw("coverage", "coverage.observed", {
        "population": "team", "layer": "communication", "actors": list("AB"), "status": "complete"}, interval=[at(-10_000_000), None]))
    records.append(raw("message", "interaction.observed", {"actor": "A", "target": "B", "action": "utterance", "topic": None}, when=-500_000))
    dataset = ingest_records(empty, records, received_at=at())
    registration = {"schema": "sociolab.temporal-tracking-spec.v1", "initial_cursor": at(), "source_time_unit": "microsecond", "views": [{
        "view_id": "communication", "view": {"schema": "sociolab.view.v1", "population": "team", "layer": "communication",
            "mode": "events", "directed": True, "actions": ["utterance"]}, "window_width": 1_000_000, "analysis": {},
    }]}
    return dataset, registration


def batch(identifier="note", value="invented"):
    return {"schema": BATCH_SCHEMA, "records": [raw(identifier, "actor.attribute.observed", {
        "actor": "A", "name": "note", "value": value}, when=-100_000)], "received_at": at()}


def encoded(value, *, newline=True):
    return (json.dumps(value, ensure_ascii=False) + ("\n" if newline else "")).encode("utf-8")


class FakeIO:
    """Timed descriptor readiness with separately adjustable wall-clock offset.

    Events are (monotonic milliseconds, bytes/exception/None, optional UTC offset
    milliseconds). None means an idle wake, while b'' means observed EOF.
    """

    def __init__(self, events, *, offset_ms=0):
        self.events = [list(event) for event in events]
        self.now = 0
        self.offset = offset_ms * 1_000_000
        self.select_calls = []
        self.read_sizes = []
        self.returned_bytes = 0

    def monotonic_ns(self):
        return self.now

    def time_ns(self):
        return BASE_US * 1000 + self.now + self.offset

    def select(self, readers, writers, errors, timeout):
        self.select_calls.append((self.now, timeout))
        if len(self.select_calls) > 1000:
            raise AssertionError("loop failed to reach the scripted EOF")
        end = self.now + round(timeout * 1_000_000_000)
        if self.events and self.events[0][0] * 1_000_000 <= end:
            event = self.events[0]
            self.now = max(self.now, event[0] * 1_000_000)
            if len(event) == 3:
                self.offset = event[2] * 1_000_000
            if event[1] is None:
                self.events.pop(0)
                return [], [], []
            return readers, [], []
        self.now = end
        return [], [], []

    def read(self, descriptor, size):
        self.read_sizes.append(size)
        event = self.events[0]
        data = event[1]
        if isinstance(data, BaseException):
            self.events.pop(0)
            raise data
        chunk, rest = data[:size], data[size:]
        if rest:
            event[1] = rest
        else:
            self.events.pop(0)
        self.returned_bytes += len(chunk)
        return chunk


class Output(io.StringIO):
    def __init__(self, clock=None, *, receipt_delay_ms=0, timer_delay_ms=0):
        super().__init__()
        self.clock = clock
        self.receipt_delay_ms, self.timer_delay_ms = receipt_delay_ms, timer_delay_ms
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        if self.clock:
            receipt = json.loads(self.getvalue().splitlines()[-1])
            delay = self.timer_delay_ms if receipt["transition_cause"] == "source_time_advance" else self.receipt_delay_ms
            self.clock.now += delay * 1_000_000
        super().flush()


class LiveTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "live"
        self.initial = initialize_tracking_store(self.store, *inputs())
        self.read_fd, self.write_fd = os.pipe()
        self.addCleanup(os.close, self.read_fd)
        self.addCleanup(os.close, self.write_fd)

    def run_live(self, clock, output=None, **kwargs):
        if output is None:
            output = Output()
        with ExitStack() as stack:
            stack.enter_context(patch("sociolab.live_tracking.time.monotonic_ns", side_effect=clock.monotonic_ns))
            stack.enter_context(patch("sociolab.live_tracking.time.time_ns", side_effect=clock.time_ns))
            stack.enter_context(patch("sociolab.live_tracking.select.select", side_effect=clock.select))
            stack.enter_context(patch("sociolab.live_tracking.os.read", side_effect=clock.read))
            count = consume_live_tracking_stream(self.store, self.read_fd, output, **kwargs)
        return count, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_idle_open_input_advances_and_expires_event_without_receipts_or_startup_output(self):
        clock = FakeIO([(2500, b"")])
        output = Output()
        before = json.loads((self.store / "00000000.json").read_text())
        with patch("sociolab.live_tracking._load_store", wraps=_load_store) as replay:
            count, receipts = self.run_live(clock, output)
        replay.assert_called_once()
        self.assertEqual(count, 0)
        self.assertEqual(output.flushes, 2)
        self.assertEqual([r["cursor_value"] - BASE_US for r in receipts], [1_000_000, 2_000_000])
        self.assertEqual([r["transition_cause"] for r in receipts], ["source_time_advance"] * 2)
        self.assertEqual([r["knowledge_cutoff"] for r in receipts], [6, 6])
        self.assertTrue(receipts[0]["views"][0]["changes"]["observed_graph_changed"])
        self.assertEqual(receipts[0]["views"][0]["edge_count"], 0)
        final = json.loads((self.store / "00000002.json").read_text())
        self.assertEqual(final["state"]["dataset"], before["state"]["dataset"])
        self.assertEqual(inspect_tracking_store(self.store)["checkpoint_hash"], receipts[-1]["checkpoint_hash"])
        self.assertTrue(os.get_blocking(self.read_fd))
        os.fstat(self.read_fd)  # caller still owns an open descriptor

    def test_partial_line_and_split_utf8_do_not_block_timers_or_decode_before_newline(self):
        data = encoded(batch(value="汉🙂"))
        split = data.index("🙂".encode()) + 2
        clock = FakeIO([(0, data[:split]), (1500, data[split:-1]), (2500, b"\n"), (2600, b"")])
        count, receipts = self.run_live(clock)
        self.assertEqual(count, 1)
        self.assertEqual([r["transition_cause"] for r in receipts], ["source_time_advance", "source_time_advance", "receipt_batch"])
        self.assertEqual([r["knowledge_cutoff"] for r in receipts], [6, 6, 7])
        self.assertEqual(receipts[-1]["cursor_value"], BASE_US + 2_000_000)
        final = json.loads((self.store / "00000003.json").read_text())
        self.assertEqual(final["state"]["dataset"]["records"][-1]["payload"]["value"], "汉🙂")
        self.assertEqual(final["state"]["dataset"]["records"][-1]["recorded_at"], at())

    def test_busy_buffered_input_checks_timer_between_lines_without_starving_input(self):
        data = b"".join(encoded(batch("note-" + str(i))) for i in range(4))
        clock = FakeIO([(0, data), (5000, b"")])
        output = Output(clock, receipt_delay_ms=600, timer_delay_ms=200)
        count, receipts = self.run_live(clock, output)
        self.assertEqual(count, 4)
        self.assertEqual([r["transition_cause"] for r in receipts], [
            "receipt_batch", "receipt_batch", "source_time_advance", "receipt_batch", "receipt_batch", "source_time_advance", "source_time_advance",
        ])
        self.assertEqual([r["cursor_value"] - BASE_US for r in receipts if r["transition_cause"] == "source_time_advance"], [1_200_000, 2_600_000, 3_800_000])
        self.assertEqual([r["knowledge_cutoff"] for r in receipts if r["transition_cause"] == "receipt_batch"], [7, 8, 9, 10])

    def test_timer_completion_sets_next_delay_and_does_not_catch_up_missed_intervals(self):
        clock = FakeIO([(4000, b"")])
        output = Output(clock, timer_delay_ms=2500)
        count, receipts = self.run_live(clock, output)
        self.assertEqual(count, 0)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["cursor_value"], BASE_US + 1_000_000)
        self.assertEqual(clock.select_calls[-1], (3_500_000_000, 1.0))

    def test_due_timer_follows_non_eof_ready_read_and_precedes_its_receipt(self):
        clock = FakeIO([(1000, encoded(batch())), (1500, b"")])
        count, receipts = self.run_live(clock)
        self.assertEqual(count, 1)
        self.assertEqual([r["transition_cause"] for r in receipts], ["source_time_advance", "receipt_batch"])
        self.assertEqual([r["cursor_value"] for r in receipts], [BASE_US + 1_000_000] * 2)
        self.assertEqual([r["knowledge_cutoff"] for r in receipts], [6, 7])

    def test_observed_empty_eof_at_due_time_wins_and_emits_no_record(self):
        original = saved_bytes(self.store)
        count, receipts = self.run_live(FakeIO([(1000, b"")]))
        self.assertEqual((count, receipts), (0, []))
        self.assertEqual(saved_bytes(self.store), original)

    def test_eof_drains_valid_unterminated_final_line_without_a_due_timer(self):
        clock = FakeIO([(0, encoded(batch(), newline=False)), (1000, b"")])
        count, receipts = self.run_live(clock)
        self.assertEqual(count, 1)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["transition_cause"], "receipt_batch")
        self.assertEqual(receipts[0]["cursor_value"], BASE_US)

    def test_forward_utc_jump_is_one_sample_and_equal_utc_is_idempotent(self):
        clock = FakeIO([(1000, None, 3_600_000), (1500, b"")])
        _, receipts = self.run_live(clock)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["cursor_value"], BASE_US + 3_601_000_000)
        sealed = saved_bytes(self.store)
        # Restart's initial sample equals the previously retained large cursor.
        equal = FakeIO([(1000, None, 3_600_000), (1500, b"")], offset_ms=3_601_000)
        _, retries = self.run_live(equal)
        self.assertEqual(retries[0]["status"], "NO_TIME_ADVANCE")
        self.assertEqual(retries[0]["cursor_value"], receipts[0]["cursor_value"])
        self.assertEqual(saved_bytes(self.store), sealed)

    def test_startup_backward_clock_fails_before_input_or_fd_changes(self):
        old = saved_bytes(self.store)
        clock = FakeIO([(0, encoded(batch()))], offset_ms=-1)
        with self.assertRaisesRegex(ValueError, "wall clock is behind"):
            self.run_live(clock)
        self.assertEqual(clock.select_calls, [])
        self.assertEqual(clock.read_sizes, [])
        self.assertEqual(saved_bytes(self.store), old)
        self.assertTrue(os.get_blocking(self.read_fd))

    def test_later_clock_rollback_preserves_prior_receipt_commit_and_restores_fd(self):
        clock = FakeIO([(0, encoded(batch())), (1000, None, -2000)])
        output = Output()
        with self.assertRaisesRegex(ValueError, "wall clock is behind"):
            self.run_live(clock, output)
        receipts = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(inspect_tracking_store(self.store)["sequence"], 1)
        self.assertEqual(inspect_tracking_store(self.store)["cursor_value"], BASE_US)
        self.assertTrue(os.get_blocking(self.read_fd))

    def test_later_bad_utf8_in_same_read_does_not_erase_earlier_valid_commit(self):
        clock = FakeIO([(0, encoded(batch()) + b"\xff\n" + encoded(batch("unread"))), (10, b"")])
        output = Output()
        with self.assertRaisesRegex(ValueError, "input line 2"):
            self.run_live(clock, output)
        self.assertEqual(output.flushes, 1)
        self.assertEqual(inspect_tracking_store(self.store)["sequence"], 1)
        saved = json.loads((self.store / "00000001.json").read_text())
        self.assertEqual(saved["state"]["dataset"]["records"][-1]["record_id"], "note")

    def test_invalid_eof_fragment_is_line_numbered_after_prior_complete_line(self):
        clock = FakeIO([(0, encoded(batch()) + b'{"schema":'), (100, b"")])
        output = Output()
        with self.assertRaisesRegex(ValueError, "input line 2"):
            self.run_live(clock, output)
        self.assertEqual(output.flushes, 1)
        self.assertEqual(inspect_tracking_store(self.store)["sequence"], 1)

    def test_decoded_character_limit_includes_newline_not_utf8_byte_count(self):
        line = encoded(batch(value="汉" * 100))
        limit = len(line.decode("utf-8"))
        self.assertGreater(len(line), limit)
        # First is exactly the character limit; the next adds one character.
        clock = FakeIO([(0, line + line[:-1] + b" \n"), (100, b"")])
        output = Output()
        with patch("sociolab.live_tracking.MAX_LINE_CHARACTERS", limit):
            with self.assertRaisesRegex(ValueError, "input line 2.*character limit"):
                self.run_live(clock, output)
        self.assertEqual(output.flushes, 1)
        self.assertEqual(inspect_tracking_store(self.store)["sequence"], 1)

    def test_incomplete_line_byte_buffer_is_bounded_and_read_chunks_capped(self):
        clock = FakeIO([(0, b"x" * 2000)])
        old = saved_bytes(self.store)
        with patch("sociolab.live_tracking.MAX_LINE_CHARACTERS", 256):
            with self.assertRaisesRegex(ValueError, "input line 1.*UTF-8 byte limit"):
                self.run_live(clock)
        self.assertEqual(clock.returned_bytes, 4 * 256 + 1)
        self.assertLessEqual(max(clock.read_sizes), 65_536)
        self.assertEqual(saved_bytes(self.store), old)

    def test_live_rejects_manual_time_controls_extra_fields_blank_and_duplicate_json_keys(self):
        original = saved_bytes(self.store)
        invalid = [encoded({"schema": ADVANCE_SCHEMA, "cursor": at(1_000_000)}),
                   encoded({**batch(), "cursor": at()}), b"\n", b'{"schema":"a","schema":"b"}\n']
        for data in invalid:
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "input line 1"):
                self.run_live(FakeIO([(0, data), (100, b"")]))
            self.assertEqual(saved_bytes(self.store), original)

    def test_invalid_interval_fd_and_non_utc_stores_fail_without_consuming_input(self):
        for interval in (True, 0, -1, 1.0, 86_400_001):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                consume_live_tracking_stream(self.store, self.read_fd, Output(), interval_ms=interval)
        for descriptor in (True, -1, "0"):
            with self.assertRaises(ValueError):
                consume_live_tracking_stream(self.store, descriptor, Output())
        for name, fixture in (("fixed", fixed_inputs), ("ticks", temporal_inputs)):
            self.store = self.root / name
            initialize_tracking_store(self.store, *fixture())
            original = saved_bytes(self.store)
            clock = FakeIO([(0, encoded(batch()))])
            with self.assertRaisesRegex(ValueError, "UTC temporal"):
                self.run_live(clock)
            self.assertEqual(clock.read_sizes, [])
            self.assertEqual(saved_bytes(self.store), original)

    def test_nonblocking_read_race_and_existing_nonblocking_mode_are_preserved(self):
        os.set_blocking(self.read_fd, False)
        clock = FakeIO([(0, BlockingIOError()), (0, encoded(batch())), (100, b"")])
        count, receipts = self.run_live(clock)
        self.assertEqual(count, 1)
        self.assertEqual(len(receipts), 1)
        self.assertFalse(os.get_blocking(self.read_fd))
        os.fstat(self.read_fd)

    def test_output_failure_preserves_durable_timer_checkpoint_and_restores_descriptor(self):
        class BrokenOutput(Output):
            def write(self, text):
                raise BrokenPipeError("lost output")

        with self.assertRaisesRegex(OSError, "may already be committed"):
            self.run_live(FakeIO([(1500, b"")]), BrokenOutput())
        self.assertTrue(os.get_blocking(self.read_fd))
        current = inspect_tracking_store(self.store)
        self.assertEqual((current["sequence"], current["knowledge_cutoff"]), (1, 6))
        self.assertEqual(current["cursor_value"], BASE_US + 1_000_000)


if __name__ == "__main__":
    unittest.main()
