"""Actual multi-action LLM smoke on authored dialogue; no empirical qualification."""
import json
import os
import unittest
from collections import Counter

from sociolab.semantic_actions import freeze_actions_input, extract_semantic_actions
from sociolab.semantic_llm import LocalLlamaSemanticProvider, _digest
from test_semantic_actions import fixture


# References are diagnostic expectations, not independent labels.
# Each tuple: actor, action, subject kind/id, topic, attribution, polarity, modality.
def event(actor, action, subject_kind, subject, topic=None,
          attribution="DIRECT", polarity="AFFIRMED", modality="ASSERTED"):
    return (actor, action, subject_kind, subject, topic, attribution, polarity, modality)


CASES = (
    ("two-topics", "我支持甲方案，但反对乙方案。", [
        event("B", "support", "topic", "alpha", "alpha"),
        event("B", "disagreement", "topic", "beta", "beta")]),
    ("reported-and-own", "小陈反对乙方案，我支持甲方案。", [
        event("C", "disagreement", "topic", "beta", "beta", "REPORTED"),
        event("B", "support", "topic", "alpha", "alpha")]),
    ("quoted-and-own", "小陈说：“我反对甲方案。”我支持甲方案。", [
        event("C", "disagreement", "topic", "alpha", "alpha", "QUOTED"),
        event("B", "support", "topic", "alpha", "alpha")]),
    ("commitment", "我答应和你一起完成甲方案。", [
        event("B", "cooperation_commitment", "person", "A", "alpha")]),
    ("negated", "我没有反对甲方案。", [
        event("B", "disagreement", "topic", "alpha", "alpha", polarity="NEGATED")]),
    ("conditional", "如果甲方案通过，我就支持它。", [
        event("B", "support", "topic", "alpha", "alpha", modality="CONDITIONAL")]),
    ("insult", "你真是个废物。", [
        event("B", "insult", "person", "A")]),
    ("mediation", "我来调解你和小陈关于乙方案的分歧。", [
        event("B", "mediation", "topic", "beta", "beta")]),
    ("threat", "我会砸你的电脑。", [
        event("B", "threat", "person", "A")]),
    ("no-action", "今天下午三点开会。", []),
)


def signature(a):
    return (a["actor_id"], a["action"], a["subject"]["kind"], a["subject"]["id"],
        a["topic_id"], a["attribution"], a["polarity"], a["modality"])


class NativeSemanticActionsTests(unittest.TestCase):
    def test_structured_multi_action_extraction(self):
        provider = LocalLlamaSemanticProvider(int(os.environ["SOCIOLAB_LLM_PORT"]),
            os.environ["SOCIOLAB_LLM_MODEL_FILE"], model_key="qwen3-8b", reasoning_mode="off")
        rows = []
        for cid, target, expected in CASES:
            dataset, context, data, people, topics = fixture(target=target, case_id=cid)
            frozen = freeze_actions_input(context, people, topics, model_key="qwen3-8b", reasoning_mode="off")
            before = dataset.content_hash
            result = extract_semantic_actions(dataset, context, frozen, original_bytes=data,
                people=people, topics=topics, provider=provider)
            self.assertEqual(before, dataset.content_hash)
            self.assertFalse(result["semantic_annotation_created"])
            self.assertEqual(result["qualification_status"], "NOT_ESTABLISHED")
            self.assertEqual(result["context_hash"], context["context_hash"])
            self.assertFalse(result["completion_telemetry"]["reasoning_present"])
            candidate = result["candidate"]
            actual = [] if candidate is None else [signature(a) for a in candidate["actions"]]
            if candidate is not None:
                for action in candidate["actions"]:
                    self.assertTrue(any(e["role"] == "target" for e in action["evidence"]))
                    self.assertEqual(action["assertion_status"], "NOT_ESTABLISHED")
            matches = sum((Counter(actual) & Counter(expected)).values())
            row = {"case_id": cid, "expected_actions": expected, "actual_actions": actual,
                "matched_actions": matches,
                "exact_event_set_match": candidate is not None and candidate["status"] != "UNRESOLVED"
                    and Counter(actual) == Counter(expected),
                "result": result}
            rows.append(row)
            print("SEMANTIC_ACTIONS_CASE_JSON=" + json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
        self.assertEqual(len(rows), len(CASES))
        valid = sum(r["result"]["candidate"] is not None for r in rows)
        report = {"schema": "sociolab.semantic-actions-native-diagnostics.v1",
            "comparison_status": "AUTHORED_DIAGNOSTICS_NOT_INDEPENDENT", "case_count": len(rows),
            "valid_outputs": valid, "exact_event_set_matches": sum(r["exact_event_set_match"] for r in rows),
            "expected_action_count": sum(len(r["expected_actions"]) for r in rows),
            "produced_action_count": sum(len(r["actual_actions"]) for r in rows),
            "matched_actions": sum(r["matched_actions"] for r in rows),
            "case_hashes": [r["result"]["result_hash"] for r in rows], "provider": provider.identity,
            "qualification_status": "NOT_ESTABLISHED", "semantic_annotation_created": False}
        report["result_hash"] = _digest(report)
        print("SEMANTIC_ACTIONS_SUMMARY_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        self.assertGreater(valid, 0)
