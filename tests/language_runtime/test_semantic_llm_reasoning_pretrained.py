"""Controlled local Qwen3-8B reasoning contrast, not a held-out benchmark."""
import json
import os
from pathlib import Path
import unittest

from sociolab.disagreement_study import freeze_disagreement_plan
from sociolab.semantic_llm import LocalLlamaSemanticProvider, freeze_llm_inputs, score_semantic_case, _digest, _request
from test_disagreement_nli_pretrained import fixture
from test_semantic_llm_pretrained import CASES, U


class SemanticReasoningNativeTests(unittest.TestCase):
    def test_explicit_reasoning_profile(self):
        mode = os.environ["SOCIOLAB_LLM_REASONING_MODE"]
        self.assertIn(mode, ("off", "on"))
        provider = LocalLlamaSemanticProvider(int(os.environ["SOCIOLAB_LLM_PORT"]),
            os.environ["SOCIOLAB_LLM_MODEL_FILE"], model_key="qwen3-8b", reasoning_mode=mode)
        path = Path(__file__).resolve().parents[2] / "docs/experiments/2026-11-28-llm/native-run-1-qwen3-8b.json"
        archive = json.loads(path.read_text(encoding="utf-8"))
        old_summary = archive["summary"]
        self.assertEqual(old_summary["result_hash"], _digest({k: v for k, v in old_summary.items() if k != "result_hash"}))
        self.assertEqual(old_summary["case_hashes"], [r["result"]["result_hash"] for r in archive["rows"]])
        baseline = {r["case_id"]: r for r in archive["rows"]}
        self.assertEqual(set(baseline), {c[0] for c in CASES})
        descriptions = {"dev": "缩短会议时间", "alpha": "周一上线", "beta": "周五上线"}
        fixtures = [fixture("development", "development", "我们提议缩短会议时间。", "可以再讨论。", ["dev"])]
        fixtures += [fixture(cid, "test", prior, target, ["alpha", "beta"])
            for cid, prior, target, _, _ in CASES]
        plan = freeze_disagreement_plan([case for _, _, case in fixtures])
        old_plan = freeze_llm_inputs(plan, descriptions, model_key="qwen3-8b")
        frozen = freeze_llm_inputs(plan, descriptions, model_key="qwen3-8b", reasoning_mode=mode)
        rows = []
        for dataset, data, case in fixtures[1:]:
            cid = case["case_id"]
            previous = baseline[cid]
            old = previous["result"]
            self.assertEqual(old["result_hash"], _digest({k: v for k, v in old.items() if k != "result_hash"}))
            self.assertEqual(old["context_hash"], case["context"]["context_hash"])
            self.assertEqual(old["input_plan_hash"], old_plan["input_plan_hash"])
            proposals = {p["id"]: descriptions[p["id"]] for p in case["proposals"]}
            original, _, _ = _request(case["context"], data, proposals, model_key="qwen3-8b")
            self.assertEqual(old["request_hash"], _digest(original))
            current, _, _ = _request(case["context"], data, proposals, model_key="qwen3-8b", reasoning_mode=mode)
            normalized = {k: v for k, v in current.items() if k != "reasoning_format"}
            normalized.update(max_tokens=original["max_tokens"], chat_template_kwargs=original["chat_template_kwargs"])
            self.assertEqual(normalized, original)
            result = score_semantic_case(dataset, plan, frozen, cid, original_bytes=data,
                proposal_texts=descriptions, provider=provider)
            self.assertEqual(result["request_hash"], _digest(current))
            self.assertEqual(result["context_hash"], old["context_hash"])
            self.assertFalse(result["semantic_annotation_created"])
            self.assertEqual(result["qualification_status"], "NOT_ESTABLISHED")
            candidate = result["candidate"]
            expected = (previous["authored_expected_state"], previous["authored_expected_proposal"])
            actual = None if candidate is None else (candidate["decision"]["state"], candidate["decision"]["proposal_id"])
            holder_match = candidate is not None and candidate["holder"] == previous["authored_expected_holder"]
            row = {"case_id": cid, "reasoning_mode": mode, "authored_expected_state": expected[0],
                "authored_expected_proposal": expected[1], "authored_expected_holder": previous["authored_expected_holder"],
                "joint_match": actual == expected, "holder_match": holder_match,
                "legacy_8b_result_hash": old["result_hash"], "result": result}
            rows.append(row)
            print("SEMANTIC_REASONING_CASE_JSON=" + json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
        self.assertEqual(len(rows), 12)
        valid = sum(r["result"]["candidate"] is not None for r in rows)
        reasoning_present = sum(r["result"]["completion_telemetry"]["reasoning_present"] for r in rows)
        report = {"schema": "sociolab.semantic-reasoning-native-diagnostics.v1",
            "comparison_status": "AUTHORED_DIAGNOSTICS_NOT_INDEPENDENT",
            "reasoning_mode": mode, "case_count": len(rows), "valid_outputs": valid,
            "resolved_outputs": sum(r["result"]["candidate"] is not None and
                r["result"]["candidate"]["decision"]["state"] != U for r in rows),
            "joint_matches": sum(r["joint_match"] for r in rows),
            "holder_matches": sum(r["holder_match"] for r in rows),
            "state_proposal_holder_matches": sum(r["joint_match"] and r["holder_match"] for r in rows),
            "reasoning_present_count": reasoning_present,
            "case_hashes": [r["result"]["result_hash"] for r in rows],
            "provider": provider.identity, "qualification_status": "NOT_ESTABLISHED",
            "semantic_annotation_created": False}
        report["result_hash"] = _digest(report)
        print("SEMANTIC_REASONING_SUMMARY_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        self.assertGreater(valid, 0)
        # Actual reasoning extraction must be observed, not inferred from a config flag.
        if mode == "on":
            self.assertGreater(reasoning_present, 0)
        else:
            self.assertEqual(reasoning_present, 0)
