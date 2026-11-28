"""Persistent source-time controls must never masquerade as new receipts."""

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from sociolab.events import EventDataset, ingest_records
from sociolab.snapshots import content_hash
from sociolab.tracking_store import (
    ADVANCE_SCHEMA, _checkpoint, initialize_tracking_store,
    inspect_tracking_store, consume_tracking_stream,
)
from test_tracking_store import inputs as fixed_inputs, batch, saved_bytes, rehash


def temporal_inputs():
    dataset, fixed = fixed_inputs()
    view = deepcopy(fixed["views"][0])
    del view["view"]["at"]
    view["window_width"] = None
    return dataset, {"schema": "sociolab.temporal-tracking-spec.v1", "initial_cursor": 5,
                     "source_time_unit": "tick", "views": [view]}


def advance(cursor):
    return {"schema": ADVANCE_SCHEMA, "cursor": cursor}


class TemporalTrackingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "temporal"
        self.initial = initialize_tracking_store(self.store, *temporal_inputs())

    def apply(self, *requests):
        output = io.StringIO()
        count = consume_tracking_stream(self.store, io.StringIO("".join(json.dumps(r) + "\n" for r in requests)), output)
        self.assertEqual(count, len(requests))
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def checkpoint(self, sequence):
        path = self.store / f"{sequence:08d}.json"
        return path, json.loads(path.read_text())

    def rewrite(self, path, value):
        rehash(value["state"])
        rehash(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_time_only_checkpoint_restarts_at_same_k_even_if_all_semantic_flags_are_false(self):
        original = saved_bytes(self.store)
        receipt = self.apply(advance(6))[0]
        self.assertEqual(receipt["status"], "APPLIED")
        self.assertEqual(receipt["transition_cause"], "source_time_advance")
        self.assertEqual(receipt["sequence"], 1)
        self.assertEqual(receipt["knowledge_cutoff"], self.initial["knowledge_cutoff"])
        self.assertEqual(receipt["cursor"], 6)
        self.assertEqual(receipt["views"][0]["source_time"], {"at": 6})
        self.assertFalse(any(receipt["views"][0]["changes"].values()))
        _, initial = self.checkpoint(0)
        _, advanced = self.checkpoint(1)
        self.assertEqual(initial["state"]["dataset"], advanced["state"]["dataset"])
        self.assertEqual(advanced["transition"]["source"]["appended_record_count"], 0)
        self.assertEqual(saved_bytes(self.store)["00000000.json"], original["00000000.json"])
        inspected = inspect_tracking_store(self.store)
        self.assertEqual(inspected["checkpoint_hash"], receipt["checkpoint_hash"])
        self.assertEqual(inspected["cursor"], 6)
        self.assertIsNone(inspected["transition_cause"])

    def test_receipt_and_time_retries_report_requested_cause_without_repeating_old_changes(self):
        added, timed = self.apply(batch(), advance(6))
        self.assertEqual(added["transition_cause"], "receipt_batch")
        self.assertEqual(added["cursor"], 5)
        self.assertEqual(added["knowledge_cutoff"], self.initial["knowledge_cutoff"] + 1)
        sealed = saved_bytes(self.store)
        retry, equal = self.apply(batch(), advance(6))
        self.assertEqual(retry["status"], "NO_NEW_RECORDS")
        self.assertEqual(retry["transition_cause"], "receipt_batch")
        self.assertEqual(equal["status"], "NO_TIME_ADVANCE")
        self.assertEqual(equal["transition_cause"], "source_time_advance")
        for receipt in (retry, equal):
            self.assertEqual(receipt["checkpoint_hash"], timed["checkpoint_hash"])
            self.assertEqual(receipt["cursor"], 6)
            self.assertIsNone(receipt["views"][0]["changes"])
            self.assertIsNone(receipt["views"][0]["comparison_status"])
        self.assertEqual(saved_bytes(self.store), sealed)

    def test_backwards_bad_types_and_mixed_controls_do_not_commit(self):
        self.apply(advance(7))
        old = saved_bytes(self.store)
        invalid = [advance(6), advance("8"), advance(True), {**advance(8), "records": []},
                   {**batch(), "cursor": 8}]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.apply(request)
            self.assertEqual(saved_bytes(self.store), old)

    def test_fixed_store_rejects_time_controls_without_changing_its_existing_contract(self):
        fixed = self.root / "fixed"
        initial = initialize_tracking_store(fixed, *fixed_inputs())
        old = saved_bytes(fixed)
        with self.assertRaisesRegex(ValueError, "temporal tracking"):
            consume_tracking_stream(fixed, io.StringIO(json.dumps(advance(6)) + "\n"), io.StringIO())
        self.assertEqual(saved_bytes(fixed), old)
        inspected = inspect_tracking_store(fixed)
        self.assertTrue(inspected["fixed_source_views"])
        self.assertNotIn("cursor", inspected)
        self.assertEqual(inspected["checkpoint_hash"], initial["checkpoint_hash"])

    def test_fixed_store_still_rejects_a_rehashed_checkpoint_without_new_receipts(self):
        fixed = self.root / "fixed"
        initialize_tracking_store(fixed, *fixed_inputs())
        initial = json.loads((fixed / "00000000.json").read_text())
        state = deepcopy(initial["state"])
        state["sequence"] = 1
        state["previous_state_hash"] = initial["state"]["content_hash"]
        rehash(state)
        value = _checkpoint(state, {}, initial["content_hash"])
        (fixed / "00000001.json").write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "receipt checkpoint must append"):
            inspect_tracking_store(fixed)

    def test_rehashed_time_checkpoint_cannot_smuggle_new_journal_receipts(self):
        self.apply(advance(6))
        path, saved = self.checkpoint(1)
        dataset = ingest_records(EventDataset.from_mapping(saved["state"]["dataset"]), batch()["records"],
                                 received_at=batch()["received_at"])
        saved["state"]["dataset"] = dataset.to_dict()
        saved["state"]["knowledge_cutoff"] = len(dataset.records)
        self.rewrite(path, saved)
        with self.assertRaisesRegex(ValueError, "advance cannot append journal"):
            inspect_tracking_store(self.store)

    def test_rehashed_receipt_checkpoint_cannot_advance_cursor(self):
        self.apply(batch())
        path, saved = self.checkpoint(1)
        saved["state"]["cursor"] = 6
        saved["state"]["cursor_value"] = 6
        self.rewrite(path, saved)
        with self.assertRaisesRegex(ValueError, "state differs from replay"):
            inspect_tracking_store(self.store)

    def test_saved_equal_time_control_and_wrong_cause_are_rejected_by_replay(self):
        self.apply(advance(6))
        path, saved = self.checkpoint(1)
        original = deepcopy(saved)
        saved["state"]["cursor"] = 5
        saved["state"]["cursor_value"] = 5
        self.rewrite(path, saved)
        with self.assertRaisesRegex(ValueError, "must advance its source cursor"):
            inspect_tracking_store(self.store)
        original["transition"]["cause"] = "receipt_batch"
        rehash(original["transition"])
        self.rewrite(path, original)
        with self.assertRaisesRegex(ValueError, "receipt checkpoint must append"):
            inspect_tracking_store(self.store)

    def test_rehashed_registration_change_cannot_modify_window_rules_mid_history(self):
        self.apply(advance(6))
        path, saved = self.checkpoint(1)
        saved["state"]["registration"]["views"][0]["analysis"]["seed"] = 17
        saved["state"]["registration_hash"] = content_hash(saved["state"]["registration"])
        self.rewrite(path, saved)
        with self.assertRaisesRegex(ValueError, "state differs from replay"):
            inspect_tracking_store(self.store)


if __name__ == "__main__":
    unittest.main()
