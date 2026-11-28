"""Actual local persistence boundaries, independent of installer/consumer paths."""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sociolab.events import EventDataset, ingest_records
from sociolab.snapshots import content_hash
from sociolab.tracking_store import (
    BATCH_SCHEMA, MAX_LINE_CHARACTERS, _locked_store,
    initialize_tracking_store, inspect_tracking_store, consume_tracking_stream,
)


def raw(identifier, kind, payload, *, at=0):
    return {
        "record_id": identifier, "fact_id": identifier, "operation": "assert", "supersedes": None,
        "kind": kind, "occurred_at": at, "valid_interval": None,
        "source": {"system": "invented-store-test", "record_id": identifier,
                   "revision": "v1", "evidence_ref": "synthetic:" + identifier},
        "payload": payload,
    }


def inputs():
    empty = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "invented-store-test", "origin": "synthetic",
        "source_revision": "v1", "clock": {"kind": "ticks", "run_id": "store-test"}, "records": [],
    })
    records = [raw("person-" + p, "entity.observed", {"entity_id": p, "entity_type": "person"}) for p in "ABCD"]
    records += [raw("join-" + p, "membership.changed", {"actor": p, "population": "team", "status": "present"}) for p in "ABCD"]
    coverage = raw("coverage", "coverage.observed", {"population": "team", "layer": "cooperation", "actors": list("ABCD"), "status": "complete"})
    coverage["valid_interval"] = [0, 20]
    records.append(coverage)
    records += [raw("edge-" + pair, "relation.changed", {"source": pair[0], "target": pair[1], "directed": False, "layer": "cooperation", "strength": 1}) for pair in ("AB", "CD")]
    dataset = ingest_records(empty, records, received_at="2026-11-28T00:00:00Z")
    registration = {"schema": "sociolab.network-tracking-spec.v1", "views": [{
        "view_id": "cooperation", "view": {"schema": "sociolab.view.v1", "population": "team", "layer": "cooperation", "mode": "state", "directed": False, "at": 5}, "analysis": {},
    }]}
    return dataset, registration


def batch(identifier="attribute", *, received_at="2026-11-28T00:01:00Z"):
    return {"schema": BATCH_SCHEMA, "received_at": received_at, "records": [
        raw(identifier, "actor.attribute.observed", {"actor": "A", "name": "invented_level", "value": 1}, at=1),
    ]}


def lines(*batches):
    return io.StringIO("".join(json.dumps(value) + "\n" for value in batches))


def saved_bytes(path):
    return {p.name: p.read_bytes() for p in path.glob("[0-9]*.json")}


def rehash(value):
    value["content_hash"] = content_hash({key: item for key, item in value.items() if key != "content_hash"})


class TrackingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "store"
        dataset, registration = inputs()
        self.initial = initialize_tracking_store(self.path, dataset, registration)

    def apply(self, *batches):
        output = io.StringIO()
        count = consume_tracking_stream(self.path, lines(*batches), output)
        self.assertEqual(count, len(batches))
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_initialization_is_private_and_never_overwrites_an_existing_directory(self):
        original = saved_bytes(self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.path / "00000000.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            initialize_tracking_store(self.path, *inputs())
        self.assertEqual(saved_bytes(self.path), original)

    def test_ack_is_flushed_before_the_next_line_is_requested_and_versions_are_retained(self):
        outer = self
        original = saved_bytes(self.path)

        class Output(io.StringIO):
            flushes = 0

            def flush(self):
                self.flushes += 1
                super().flush()

        output = Output()

        class Source:
            calls = 0

            def readline(self, limit):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps(batch()) + "\n"
                outer.assertEqual(output.flushes, self.calls - 1)
                outer.assertEqual(len(output.getvalue().splitlines()), self.calls - 1)
                if self.calls == 2:
                    return json.dumps(batch("second", received_at="2026-11-28T00:02:00Z")) + "\n"
                return ""

        self.assertEqual(consume_tracking_stream(self.path, Source(), output), 2)
        self.assertEqual(saved_bytes(self.path)["00000000.json"], original["00000000.json"])
        inspected = inspect_tracking_store(self.path)
        self.assertEqual(inspected["sequence"], 2)
        self.assertEqual(inspected["knowledge_cutoff"], 13)

    def test_record_retry_and_empty_batch_do_not_create_versions_even_with_other_receipt_times(self):
        first = self.apply(batch())[0]
        original = saved_bytes(self.path)
        retry = batch(received_at="2020-01-01T00:00:00Z")
        empty = {"schema": BATCH_SCHEMA, "records": [], "received_at": None}
        for receipt in self.apply(retry, empty):
            self.assertEqual(receipt["status"], "NO_NEW_RECORDS")
            self.assertEqual(receipt["checkpoint_hash"], first["checkpoint_hash"])
            self.assertIsNone(receipt["views"][0]["changes"])
        self.assertEqual(saved_bytes(self.path), original)

    def test_mixed_duplicate_and_new_records_replay_from_only_the_appended_tail(self):
        self.apply(batch())
        mixed = batch("second", received_at="2026-11-28T00:02:00Z")
        mixed["records"].insert(0, batch()["records"][0])
        receipt = self.apply(mixed)[0]
        self.assertEqual(receipt["knowledge_cutoff"], 13)
        self.assertEqual(inspect_tracking_store(self.path)["checkpoint_hash"], receipt["checkpoint_hash"])

    def test_bad_line_stops_after_prior_commit_and_does_not_read_following_delivery(self):
        source = io.StringIO(json.dumps(batch()) + "\n{bad json\n" + json.dumps(batch("unread")) + "\n")
        output = io.StringIO()
        with self.assertRaisesRegex(ValueError, "input line 2"):
            consume_tracking_stream(self.path, source, output)
        self.assertIn("unread", source.read())
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(inspect_tracking_store(self.path)["sequence"], 1)

    def test_conflicting_record_id_and_nonmonotonic_new_receipt_leave_all_versions_unchanged(self):
        self.apply(batch())
        old = saved_bytes(self.path)
        conflicting = batch()
        conflicting["records"][0]["payload"]["value"] = 2
        for invalid in (conflicting, batch("new", received_at="2020-01-01T00:00:00Z")):
            with self.assertRaises(ValueError):
                self.apply(invalid)
            self.assertEqual(saved_bytes(self.path), old)

    def test_failure_before_final_link_leaves_the_committed_history_unchanged(self):
        old = saved_bytes(self.path)
        with patch("sociolab.tracking_store.os.link", side_effect=OSError("injected precommit failure")):
            with self.assertRaisesRegex(OSError, "precommit failure"):
                self.apply(batch())
        self.assertEqual(saved_bytes(self.path), old)
        self.assertEqual(list(self.path.glob(".pending-*")), [])
        self.assertEqual(inspect_tracking_store(self.path)["sequence"], 0)

    def test_failure_after_link_does_not_remove_commit_and_retry_recovers(self):
        actual_fsync = os.fsync
        calls = 0

        def fail_directory(descriptor):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected directory durability failure")
            return actual_fsync(descriptor)

        with patch("sociolab.tracking_store.os.fsync", side_effect=fail_directory):
            with self.assertRaisesRegex(OSError, "checkpoint was published"):
                self.apply(batch())
        self.assertEqual(inspect_tracking_store(self.path)["sequence"], 1)
        before_retry = saved_bytes(self.path)
        self.assertEqual(self.apply(batch())[0]["status"], "NO_NEW_RECORDS")
        self.assertEqual(saved_bytes(self.path), before_retry)

    def test_output_failure_after_commit_is_recoverable_by_record_retry(self):
        class BrokenOutput(io.StringIO):
            def write(self, text):
                raise BrokenPipeError("injected lost receipt")

        with self.assertRaisesRegex(OSError, "may already be committed"):
            consume_tracking_stream(self.path, lines(batch()), BrokenOutput())
        self.assertEqual(inspect_tracking_store(self.path)["sequence"], 1)
        self.assertEqual(self.apply(batch())[0]["status"], "NO_NEW_RECORDS")

    def test_active_second_writer_is_rejected_and_lock_releases(self):
        with _locked_store(self.path):
            with self.assertRaisesRegex(ValueError, "already in use"):
                inspect_tracking_store(self.path)
        self.assertEqual(inspect_tracking_store(self.path)["sequence"], 0)

    def test_recognized_incomplete_temporary_file_is_not_promoted_to_a_commit(self):
        pending = self.path / (".pending-" + "a" * 32 + ".json")
        pending.write_text("{incomplete", encoding="utf-8")
        self.assertEqual(inspect_tracking_store(self.path)["sequence"], 0)
        self.apply(batch())
        self.assertEqual(pending.read_text(), "{incomplete")

    def test_missing_intermediate_checkpoint_and_corrupt_final_json_are_rejected(self):
        self.apply(batch(), batch("second", received_at="2026-11-28T00:02:00Z"))
        middle = self.path / "00000001.json"
        saved = middle.read_bytes()
        middle.unlink()
        with self.assertRaisesRegex(ValueError, "gap"):
            inspect_tracking_store(self.path)
        middle.write_bytes(saved)
        (self.path / "00000002.json").write_text("{incomplete", encoding="utf-8")
        with self.assertRaises(ValueError):
            inspect_tracking_store(self.path)

    def test_unexpected_file_and_symlink_are_rejected(self):
        unexpected = self.path / "latest.json"
        unexpected.write_text("{}")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            inspect_tracking_store(self.path)
        unexpected.unlink()
        unexpected.symlink_to(self.path / "00000000.json")
        with self.assertRaisesRegex(ValueError, "nonsymlink"):
            inspect_tracking_store(self.path)

    def test_rehashed_older_transition_tampering_is_detected_by_full_replay(self):
        self.apply(batch(), batch("second", received_at="2026-11-28T00:02:00Z"))
        first_path, second_path = self.path / "00000001.json", self.path / "00000002.json"
        first, second = json.loads(first_path.read_text()), json.loads(second_path.read_text())
        first["transition"]["views"][0]["observed_graph_changed"] = True
        rehash(first["transition"])
        rehash(first)
        second["previous_checkpoint_hash"] = first["content_hash"]
        rehash(second)
        first_path.write_text(json.dumps(first), encoding="utf-8")
        second_path.write_text(json.dumps(second), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "transition differs from replay"):
            inspect_tracking_store(self.path)

    def test_full_raw_prefix_is_checked_even_if_receipt_history_metadata_is_unchanged(self):
        self.apply(batch())
        path = self.path / "00000001.json"
        checkpoint = json.loads(path.read_text())
        checkpoint["state"]["dataset"]["records"][0]["source"]["revision"] = "changed-old-source"
        rehash(checkpoint["state"])
        rehash(checkpoint)
        path.write_text(json.dumps(checkpoint), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "complete receipt prefix"):
            inspect_tracking_store(self.path)

    def test_strict_stream_contract_rejects_duplicate_keys_blank_lines_and_oversized_lines(self):
        old = saved_bytes(self.path)
        bad_lines = ["\n", '{"schema":"x","schema":"y"}\n', " " * (MAX_LINE_CHARACTERS + 1)]
        for text in bad_lines:
            with self.assertRaises(ValueError):
                consume_tracking_stream(self.path, io.StringIO(text), io.StringIO())
            self.assertEqual(saved_bytes(self.path), old)


if __name__ == "__main__":
    unittest.main()
