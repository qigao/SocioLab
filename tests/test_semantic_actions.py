"""Multi-action contract and exact-journal tests; no learned inference."""
from copy import deepcopy
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from sociolab import semantic_actions as sa
from sociolab.events import EventDataset, ingest_records
from sociolab.language_context import bind_language_context
from sociolab.semantic_llm import LocalLlamaSemanticProvider, _digest


def raw(rid, kind, payload, at):
    return {"record_id": rid, "fact_id": rid, "operation": "assert", "supersedes": None,
        "kind": kind, "occurred_at": at, "valid_interval": None, "payload": payload,
        "source": {"system": "fictional", "record_id": rid, "revision": "1", "evidence_ref": "test:" + rid}}


def fixture(prior="方案甲周一上线，方案乙周五上线。",
            target="我支持甲方案，但小陈反对乙方案。", *, case_id="fictional-actions"):
    data = EventDataset.from_mapping({"schema": "sociolab.events.v1", "dataset_id": case_id,
        "origin": "synthetic", "source_revision": "1", "clock": {"kind": "ticks", "run_id": "test"}, "records": []})
    batch = [raw(p, "entity.observed", {"entity_id": p, "entity_type": "person"}, 0) for p in ("A", "B", "C")]
    texts = {"c1": prior.encode("utf-8"), "c2": target.encode("utf-8")}
    for i, actor, addressee in ((1, "A", "B"), (2, "B", "A")):
        iid, cid = f"i{i}", f"c{i}"
        value = texts[cid]
        batch.append(raw(iid, "interaction.observed", {"actor": actor, "target": addressee,
            "action": "utterance", "topic": "meeting"}, i))
        batch.append(raw(cid, "content.observed", {"interaction_record_id": iid, "content_ref": "private:"+cid,
            "content_revision": "1", "content_hash": "sha256:"+sha256(value).hexdigest(),
            "language": "zh", "length": {"unicode_codepoint": len(value.decode()), "utf8_byte": len(value)}}, i))
    data = ingest_records(data, batch, received_at="2026-11-28T08:00:00Z")
    context = bind_language_context(data, knowledge_cutoff=7, target_record_id="c2",
        preceding_record_ids=["c1"], original_bytes=texts,
        conversation={"id": case_id, "revision": "1", "source_ref": "fictional",
            "interaction_record_ids": ["i1", "i2"]})
    people = {"A": "小周", "B": "小林", "C": "小陈"}
    topics = {"alpha": "方案甲周一上线", "beta": "方案乙周五上线"}
    return data, context, texts, people, topics


def action(actor="A2", label="support", subject="T1", topic="T1",
           attribution="DIRECT", quote="我支持甲方案"):
    return {"actor": actor, "action": label, "subject": subject, "topic": topic,
        "attribution": attribution, "polarity": "AFFIRMED", "modality": "ASSERTED",
        "evidence": [{"message": "M2", "quote": quote}]}


def output(actions, status="CANDIDATES"):
    return json.dumps({"status": status, "actions": actions}, ensure_ascii=False)


class SemanticActionTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.context, self.data, self.people, self.topics = fixture()

    def binding(self):
        return sa._request(self.context, self.data, self.people, self.topics,
            model_key="qwen3-8b", reasoning_mode="off")

    def parse(self, actions, status="CANDIDATES"):
        _, *args = self.binding()
        return sa._validate_output(output(actions, status), *args)

    def test_multiple_actions_with_distinct_people_and_topics(self):
        first = action()
        first["evidence"].append({"message": "M1", "quote": "方案甲周一上线"})
        second = action("A3", "disagreement", "T2", "T2", "REPORTED", "小陈反对乙方案")
        result = self.parse([first, second])
        self.assertEqual([(a["actor_id"], a["action"], a["topic_id"], a["attribution"])
            for a in result["actions"]], [("B", "support", "alpha", "DIRECT"),
            ("C", "disagreement", "beta", "REPORTED")])
        self.assertEqual([s["role"] for s in result["actions"][0]["evidence"]], ["preceding", "target"])
        self.assertEqual(result["actions"][1]["subject"], {"kind": "topic", "id": "beta"})
        for a in result["actions"]:
            self.assertEqual(a["assertion_status"], "NOT_ESTABLISHED")
            for span in a["evidence"]:
                entry = next(e for e in self.context["entries"] if e["content_record_id"] == span["content_record_id"])
                self.assertEqual(span["content_hash"], entry["content_hash"])
                self.assertEqual(span["content_revision"], entry["content_revision"])
        self.assertNotIn("我支持", str(result))

    def test_direct_holder_and_topic_binding(self):
        for candidate in (action(actor="A3"), action(subject="T2", topic="T1"),
                          action(subject="T999"), action(actor="A999")):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.parse([candidate])

    def test_evidence_must_be_exact_and_target_bound(self):
        for evidence in ([{"message": "M1", "quote": "方案甲周一上线"}],
            [{"message": "M2", "quote": "我反对甲方案"}],
            [{"message": "M3", "quote": "我支持甲方案"}],
            [{"message": "M2", "quote": "我支持甲方案"}, {"message": "M2", "quote": "支持甲"}]):
            candidate = action()
            candidate["evidence"] = evidence
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.parse([candidate])

    def test_distinct_modality_and_unresolved_are_preserved(self):
        a = action(actor="UNKNOWN", attribution="UNRESOLVED", subject="UNKNOWN", topic="UNKNOWN")
        a["polarity"], a["modality"] = "NEGATED", "CONDITIONAL"
        result = self.parse([a], "UNRESOLVED")
        candidate = result["actions"][0]
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertIsNone(candidate["actor_id"])
        self.assertEqual(candidate["subject"], {"kind": "unresolved", "id": None})
        self.assertEqual(candidate["topic_status"], "unresolved")
        self.assertEqual((candidate["polarity"], candidate["modality"]), ("NEGATED", "CONDITIONAL"))

    def test_empty_status_and_duplicate_invariants(self):
        self.assertEqual(self.parse([], "NO_IN_SCOPE_ACTION")["actions"], [])
        self.assertEqual(self.parse([], "UNRESOLVED")["status"], "UNRESOLVED")
        for actions, status in (([], "CANDIDATES"), ([action()], "NO_IN_SCOPE_ACTION"),
            ([action(), action()], "CANDIDATES"), ([action()]*9, "CANDIDATES")):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.parse(actions, status)

    def test_stable_catalog_aliases_and_frozen_identity(self):
        args = (self.context, self.people, self.topics)
        a = sa.freeze_actions_input(*args)
        reverse_people = dict(reversed(list(self.people.items())))
        b = sa.freeze_actions_input(self.context, reverse_people, self.topics)
        self.assertEqual(a, b)
        self.assertNotIn("小陈", str(a))
        self.assertNotEqual(a, sa.freeze_actions_input(self.context, self.people, {**self.topics, "alpha": "新描述"}))
        self.assertNotEqual(a, sa.freeze_actions_input(*args, reasoning_mode="on"))
        with self.assertRaisesRegex(ValueError, "participants"):
            sa.freeze_actions_input(self.context, {"A": "小周"}, self.topics)

    def test_actual_context_and_catalog_checks_before_model_call(self):
        provider = LocalLlamaSemanticProvider.__new__(LocalLlamaSemanticProvider)
        provider.model_key, provider.reasoning_mode = "qwen3-8b", "off"
        provider.identity = {"model_alias": "sociolab-qwen3-8b"}
        frozen = sa.freeze_actions_input(self.context, self.people, self.topics)
        before = deepcopy(self.dataset.to_dict())
        with patch.object(provider, "complete_with_metadata",
            return_value=(output([action()]), "stop", {"reasoning_present": False})) as complete:
            result = sa.extract_semantic_actions(self.dataset, self.context, frozen, original_bytes=self.data,
                people=self.people, topics=self.topics, provider=provider)
            self.assertEqual(result["status"], "VALID_UNQUALIFIED_CANDIDATES")
            self.assertFalse(result["semantic_annotation_created"])
            self.assertEqual(result["source_speaker_id"], "B")
            self.assertEqual(self.dataset.to_dict(), before)
            complete.assert_called_once()
            bad_people = {**self.people, "D": "不存在的人"}
            bad_plan = sa.freeze_actions_input(self.context, bad_people, self.topics)
            with self.assertRaisesRegex(ValueError, "known canonical"):
                sa.extract_semantic_actions(self.dataset, self.context, bad_plan, original_bytes=self.data,
                    people=bad_people, topics=self.topics, provider=provider)
            altered = {**self.data, "c2": b"wrong"}
            with self.assertRaises(ValueError):
                sa.extract_semantic_actions(self.dataset, self.context, frozen, original_bytes=altered,
                    people=self.people, topics=self.topics, provider=provider)
            complete.assert_called_once()

    def test_invalid_and_incomplete_results_not_no_action(self):
        provider = LocalLlamaSemanticProvider.__new__(LocalLlamaSemanticProvider)
        provider.model_key, provider.reasoning_mode = "qwen3-8b", "off"
        provider.identity = {"model_alias": "sociolab-qwen3-8b"}
        frozen = sa.freeze_actions_input(self.context, self.people, self.topics)
        for raw, finish, status in (("{}", "stop", "INVALID_MODEL_OUTPUT"),
                                    (output([action()]), "length", "INCOMPLETE_MODEL_OUTPUT")):
            with self.subTest(status=status), patch.object(provider, "complete_with_metadata",
                    return_value=(raw, finish, {})):
                result = sa.extract_semantic_actions(self.dataset, self.context, frozen,
                    original_bytes=self.data, people=self.people, topics=self.topics, provider=provider)
                self.assertEqual(result["status"], status)
                self.assertIsNone(result["candidate"])
