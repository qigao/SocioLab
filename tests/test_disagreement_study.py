from copy import deepcopy
from hashlib import sha256
import unittest

from sociolab.language_context import _select
from sociolab.disagreement_study import freeze_disagreement_plan, evaluate_disagreement


def case(cid, partition, text, topic=None, preceding=None):
    data = text.encode()
    payload = {"interaction_record_id": "i-"+cid, "content_ref": "private:"+cid,
        "content_revision": "1", "content_hash": "sha256:"+sha256(data).hexdigest(),
        "language": "zh", "length": {"unicode_codepoint": len(text), "utf8_byte": len(data)}}
    row = {"record_id": cid, "interaction_record_id": "i-"+cid, "occurred_at": 1,
        "actor": "A", "addressee": "B", "interaction_topic": topic, "interaction_action": "utterance"}
    rows, records, texts, previous = [row], {cid: {"payload": payload}}, {cid: data}, []
    if preceding is not None:
        pid = "previous-"+cid
        earlier, earlier_input = case(pid, partition, preceding)
        prior = earlier["context"]["entries"][-1]
        rows.insert(0, {"record_id": pid, **{k: prior[k] for k in row if k != "record_id" and k != "occurred_at"}, "occurred_at": 0})
        records[pid] = {"payload": earlier_input["payload"]}
        texts[pid] = earlier_input["data"]
        previous.append(pid)
    context = _select({"current_contents": rows, "input": {"dataset": {"dataset_id": "fictional"}}},
        records, parse_source_time=int, knowledge_cutoff=len(rows),
        target_record_id=cid, preceding_record_ids=previous, original_bytes=texts,
        conversation={"id": "conv-"+cid, "revision": "1", "source_ref": "fictional", "interaction_record_ids": [r["interaction_record_id"] for r in rows]})
    return {"case_id": cid, "partition": partition, "context": context,
        "proposals": [{"id": "proposal-"+cid, "family": "family-"+cid}]}, {"content_record_id": cid, "payload": payload, "data": data}


def decision(state, pid=None, evidence=None):
    return {"state": state, "proposal_id": pid, "evidence": [] if evidence is None else evidence}


class DisagreementStudyTests(unittest.TestCase):
    def setUp(self):
        self.dev, _ = case("dev", "development", "我支持方案甲。")
        self.a, ai = case("a", "test", "我不同意这个方案。", "unverified-topic", preceding="建议采用方案甲。")
        self.b, bi = case("b", "test", "他说他不同意。")
        self.c, ci = case("c", "test", "我反对。")
        self.d, di = case("d", "test", "我不同意方案乙。")
        self.cases = [self.dev, self.a, self.b, self.c, self.d]
        self.inputs = dict(a=ai, b=bi, c=ci, d=di)
        self.pos = decision("DISAGREEMENT", "proposal-a", [{"start": 0, "end": 8}])
        self.neg = decision("NO_DISAGREEMENT")
        self.unknown = decision("UNRESOLVED")
        self.posd = decision("DISAGREEMENT", "proposal-d", [{"start": 0, "end": 8}])
        self.reviewers = [{"id": "r1", "decisions": {"a": self.pos, "b": self.neg, "c": self.unknown, "d": self.posd}},
                          {"id": "r2", "decisions": {"a": self.pos, "b": self.neg, "c": self.unknown, "d": self.posd}}]
        self.plan = freeze_disagreement_plan(self.cases)
        for reviewer in self.reviewers:
            reviewer["plan_hash"] = self.plan["plan_hash"]

    def score(self, predictions):
        candidate = {"method": {"kind": "rule", "id": "fictional", "version": "1"},
            "plan_hash": self.plan["plan_hash"], "decisions": predictions}
        return evaluate_disagreement(self.plan, target_inputs=self.inputs, reviewers=self.reviewers, candidate=candidate)

    def test_scores_with_abstention_and_missing(self):
        r = self.score({"a": self.pos, "b": self.unknown})
        self.assertEqual(r["reference_coverage"]["value"], .75)
        self.assertEqual(r["candidate_coverage"]["value"], 1/3)
        self.assertEqual(r["joint_accuracy_matched"]["value"], 1)
        self.assertEqual(r["joint_positive_recall"]["value"], .5)
        self.assertEqual(r["joint_correct_over_reference"]["value"], 1/3)
        self.assertEqual(r["rows"][2]["reference_status"], "UNRESOLVED")
        self.assertNotIn("不同意", str(r))

    def test_abstain_baseline(self):
        r = self.score({cid: self.unknown for cid in self.inputs})
        self.assertEqual(r["candidate_coverage"]["value"], 0)
        self.assertIsNone(r["joint_accuracy_matched"]["value"])
        self.assertEqual(r["joint_positive_recall"]["value"], 0)

    def test_reference_disagreement_and_missing(self):
        self.reviewers[1]["decisions"]["a"] = self.neg
        del self.reviewers[1]["decisions"]["b"]
        r = self.score({"a": self.pos, "b": self.neg})
        self.assertEqual([x["reference_status"] for x in r["rows"]], ["DISAGREED", "MISSING", "UNRESOLVED", "AGREED"])
        self.assertEqual(r["eligible_reference_count"], 1)

    def test_wrong_proposal_is_not_correct_label(self):
        self.a["proposals"].append({"id": "other", "family": "other-family"})
        self.plan = freeze_disagreement_plan(self.cases)
        for reviewer in self.reviewers:
            reviewer["plan_hash"] = self.plan["plan_hash"]
        wrong = decision("DISAGREEMENT", "other", [{"start": 0, "end": 8}])
        r = self.score({"a": wrong})
        self.assertEqual(r["joint_positive_precision"]["value"], 0)
        self.assertTrue(r["rows"][0]["label_correct"])
        self.assertFalse(r["rows"][0]["joint_correct"])

    def test_evidence_is_separate(self):
        self.reviewers[1]["decisions"]["a"] = decision("DISAGREEMENT", "proposal-a", [{"start": 1, "end": 8}])
        r = self.score({"a": self.pos})
        self.assertTrue(r["rows"][0]["joint_correct"])
        self.assertFalse(r["rows"][0]["reviewer_exact_evidence_agreement"])
        self.assertFalse(r["rows"][0]["candidate_exact_evidence_both"])

    def test_split_exact_duplicate_and_family(self):
        duplicate, _ = case("duplicate", "test", "我支持方案甲。")
        with self.assertRaisesRegex(ValueError, "content-hash"):
            freeze_disagreement_plan([self.dev, duplicate])
        overlap, _ = case("overlap", "test", "其他内容。", preceding="我支持方案甲。")
        with self.assertRaisesRegex(ValueError, "content-hash"):
            freeze_disagreement_plan([self.dev, overlap])
        self.a["proposals"][0]["family"] = "family-dev"
        with self.assertRaisesRegex(ValueError, "proposal-family"):
            freeze_disagreement_plan([self.dev, self.a])

    def test_tampered_context_and_plan(self):
        self.a["context"]["entries"][0]["actor"] = "X"
        with self.assertRaisesRegex(ValueError, "context digest"):
            freeze_disagreement_plan(self.cases)
        self.plan["plan_hash"] = "changed"
        with self.assertRaisesRegex(ValueError, "plan identity"):
            self.score({})

    def test_wrong_bytes_and_revision(self):
        original = self.inputs["a"]["data"]
        self.inputs["a"]["data"] = b"x" * len(original)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.score({})
        self.inputs["a"]["data"] = original
        self.inputs["a"]["payload"]["content_revision"] = "2"
        with self.assertRaisesRegex(ValueError, "frozen content"):
            self.score({})

    def test_bad_decisions_fail(self):
        for bad in (None, decision("DISAGREEMENT", "unverified-topic", [{"start": 0, "end": 1}]),
                    decision("DISAGREEMENT", "proposal-a", [{"start": 0, "end": 99}]),
                    decision("NO_DISAGREEMENT", "proposal-a")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.score({"a": bad})
        with self.assertRaisesRegex(ValueError, "only to test"):
            self.score({"dev": self.neg})
        self.reviewers[1]["id"] = "r1"
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.score({})

    def test_method_and_plan_identity(self):
        self.reviewers[0]["plan_hash"] = "wrong"
        with self.assertRaisesRegex(ValueError, "reviewer plan"):
            self.score({})
        self.reviewers[0]["plan_hash"] = self.plan["plan_hash"]
        candidate = {"method": {"kind": "model", "id": "example", "version": "1"},
            "plan_hash": "wrong", "decisions": {}}
        with self.assertRaisesRegex(ValueError, "candidate plan"):
            evaluate_disagreement(self.plan, target_inputs=self.inputs, reviewers=self.reviewers, candidate=candidate)
        self.inputs["a"]["content_record_id"] = "other"
        with self.assertRaisesRegex(ValueError, "target record"):
            self.score({})

    def test_deterministic_no_mutation(self):
        before = deepcopy((self.plan, self.inputs, self.reviewers))
        self.assertEqual(self.score({"a": self.pos}), self.score({"a": self.pos}))
        self.assertEqual(before, (self.plan, self.inputs, self.reviewers))
