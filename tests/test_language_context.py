"""Exercise context selection and its real journal integration separately."""
from copy import deepcopy
from hashlib import sha256
import unittest

from sociolab.language_context import _select, bind_language_context, MAX_BYTES


def fixture():
    texts = {"c1": "我建议方案甲。".encode(), "c2": "我不同意这个方案。".encode()}
    records, rows = {}, []
    for i, (rid, data) in enumerate(texts.items(), 1):
        parent = f"i{i}"
        payload = {"interaction_record_id": parent, "content_ref": f"private:{rid}",
            "content_revision": "1", "content_hash": "sha256:" + sha256(data).hexdigest(),
            "language": "zh", "length": {"unicode_codepoint": len(data.decode()), "utf8_byte": len(data)}}
        records[rid] = {"payload": payload}
        rows.append({"record_id": rid, "interaction_record_id": parent, "occurred_at": i,
            "actor": "A" if i == 1 else "B", "addressee": "B" if i == 1 else "A",
            "interaction_topic": "proposal-A", "interaction_action": "utterance"})
    report = {"current_contents": rows, "input": {"dataset": {"dataset_id": "fictional", "known_records_hash": "prefix"}}}
    args = {"knowledge_cutoff": 6, "target_record_id": "c2", "preceding_record_ids": ["c1"],
        "conversation": {"id": "conv", "revision": "1", "source_ref": "declared:1", "interaction_record_ids": ["i1", "i2"]},
        "original_bytes": texts}
    return report, records, args


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.report, self.records, self.args = fixture()

    def run_selection(self):
        return _select(self.report, self.records, parse_source_time=int, **self.args)

    def test_order_binding_private_and_no_semantic_claim(self):
        old = deepcopy((self.report, self.records, self.args))
        result = self.run_selection()
        self.assertEqual([e["role"] for e in result["entries"]], ["preceding", "target"])
        self.assertEqual([e["actor"] for e in result["entries"]], ["A", "B"])
        self.assertEqual(result["entries"][1]["interaction_topic"], "proposal-A")
        self.assertFalse(result["semantic_annotation_created"])
        self.assertEqual(result["conversation"]["membership_status"], "CALLER_DECLARED_NOT_AUTHENTICATED")
        self.assertNotIn("不同意", str(result))
        self.assertNotIn("private:c1", str(result))
        self.assertEqual(old, (self.report, self.records, self.args))
        self.assertEqual(result, self.run_selection())

    def test_unresolved_current_content(self):
        self.report["current_contents"].pop(0)
        with self.assertRaisesRegex(ValueError, "not current"):
            self.run_selection()

    def test_future_and_equal_time(self):
        for at in (2, 3):
            self.report["current_contents"][0]["occurred_at"] = at
            with self.subTest(at=at), self.assertRaisesRegex(ValueError, "strictly preceding"):
                self.run_selection()

    def test_other_conversation(self):
        self.args["conversation"]["interaction_record_ids"][0] = "foreign"
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.run_selection()

    def test_extra_or_missing_bytes(self):
        saved = self.args["original_bytes"].copy()
        for value in ({"c2": saved["c2"]}, {**saved, "future": b"x"}):
            self.args["original_bytes"] = value
            with self.assertRaisesRegex(ValueError, "exact authorized"):
                self.run_selection()

    def test_tampered_bytes(self):
        for rid in ("c1", "c2"):
            old = self.args["original_bytes"][rid]
            self.args["original_bytes"][rid] = b"x" * len(old)
            with self.subTest(rid=rid), self.assertRaisesRegex(ValueError, "hash mismatch"):
                self.run_selection()
            self.args["original_bytes"][rid] = old

    def test_duplicate_and_limit(self):
        self.args["preceding_record_ids"] = ["c2"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_selection()
        self.args["preceding_record_ids"] = ["c1"] * 9
        with self.assertRaisesRegex(ValueError, "limit"):
            self.run_selection()

    def test_byte_budget_and_type(self):
        self.args["original_bytes"]["c1"] = bytearray(b"x")
        with self.assertRaisesRegex(ValueError, "exact bytes"):
            self.run_selection()
        self.args["original_bytes"]["c1"] = b"x" * MAX_BYTES
        with self.assertRaisesRegex(ValueError, "byte limit"):
            self.run_selection()

    def test_target_language_and_blank(self):
        self.records["c2"]["payload"]["language"] = "en"
        with self.assertRaisesRegex(ValueError, "language zh"):
            self.run_selection()
        self.records["c2"]["payload"]["language"] = "zh"
        data = b"  "
        self.args["original_bytes"]["c1"] = data
        self.records["c1"]["payload"].update(content_hash="sha256:" + sha256(data).hexdigest(),
            length={"unicode_codepoint": 2, "utf8_byte": 2})
        with self.assertRaisesRegex(ValueError, "blank"):
            self.run_selection()

    def test_target_only_and_hash_changes(self):
        original = self.run_selection()
        self.args["preceding_record_ids"] = []
        self.args["conversation"]["interaction_record_ids"] = ["i2"]
        self.args["original_bytes"].pop("c1")
        result = self.run_selection()
        self.assertEqual(len(result["entries"]), 1)
        self.assertNotEqual(original["context_hash"], result["context_hash"])
        self.args["conversation"]["revision"] = "2"
        self.assertNotEqual(result["context_hash"], self.run_selection()["context_hash"])


class JournalIntegrationTests(unittest.TestCase):
    def setUp(self):
        from sociolab.events import EventDataset, ingest_records
        _, records, self.args = fixture()
        def raw(rid, kind, payload, at):
            return {"record_id": rid, "fact_id": rid, "operation": "assert", "supersedes": None,
                "kind": kind, "occurred_at": at, "valid_interval": None, "payload": payload,
                "source": {"system": "fictional", "record_id": rid, "revision": "1", "evidence_ref": "test:" + rid}}
        self.raw = raw
        data = EventDataset.from_mapping({"schema": "sociolab.events.v1", "dataset_id": "fictional",
            "origin": "synthetic", "source_revision": "1", "clock": {"kind": "ticks", "run_id": "test"}, "records": []})
        batch = [raw(p, "entity.observed", {"entity_id": p, "entity_type": "person"}, 0) for p in ("A", "B")]
        for i, actor, addressee in ((1, "A", "B"), (2, "B", "A")):
            batch.append(raw(f"i{i}", "interaction.observed", {"actor": actor, "target": addressee,
                "action": "utterance", "topic": "proposal-A"}, i))
            batch.append(raw(f"c{i}", "content.observed", records[f"c{i}"]["payload"], i))
        self.dataset = ingest_records(data, batch, received_at="2026-11-28T08:00:00Z")

    def test_receipt_cutoff_and_same_bytes_revision(self):
        from sociolab.events import ingest_records
        old = bind_language_context(self.dataset, **self.args)
        with self.assertRaisesRegex(ValueError, "not current"):
            bind_language_context(self.dataset, **{**self.args, "knowledge_cutoff": 5})
        payload = self.dataset.records[3]["payload"]
        correction = self.raw("c1-new", "content.observed", {**payload, "content_revision": "2"}, 1)
        correction.update(fact_id="c1", supersedes="c1")
        extended = ingest_records(self.dataset, [correction], received_at="2026-11-28T08:01:00Z")
        self.assertEqual(old, bind_language_context(extended, **self.args))
        with self.assertRaisesRegex(ValueError, "not current"):
            bind_language_context(extended, **{**self.args, "knowledge_cutoff": 7})

    def test_ambiguous_content_rejected(self):
        from sociolab.events import ingest_records
        payload = self.dataset.records[3]["payload"]
        competing = self.raw("c1-extra", "content.observed", payload, 1)
        extended = ingest_records(self.dataset, [competing], received_at="2026-11-28T08:01:00Z")
        with self.assertRaisesRegex(ValueError, "not current"):
            bind_language_context(extended, **{**self.args, "knowledge_cutoff": 7})
