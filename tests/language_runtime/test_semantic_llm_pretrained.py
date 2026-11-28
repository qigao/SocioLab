"""Real local LLM semantic parsing on authored contrasts, not empirical qualification."""
import json
import os
from pathlib import Path
import unittest

from sociolab.disagreement_study import freeze_disagreement_plan
from sociolab.semantic_llm import LocalLlamaSemanticProvider, freeze_llm_inputs, score_semantic_case, _digest, _request
from test_disagreement_nli_pretrained import fixture


D, N, U = "DISAGREEMENT", "NO_DISAGREEMENT", "UNRESOLVED"
CASES = (
    ("direct-alpha", "甲方案是周一上线。", "我不同意这个方案。", D, "alpha"),
    ("direct-beta", "乙方案是周五上线。", "我不同意这个方案。", D, "beta"),
    ("reported", "甲方案是周一上线。", "小陈反对这个方案。", N, None),
    ("quoted", "甲方案是周一上线。", "小陈说：“我反对这个方案。”", N, None),
    ("both", "甲方案是周一上线。", "小陈反对这个方案，我也反对。", D, "alpha"),
    ("negated", "甲方案是周一上线。", "我并不是不同意这个方案。", N, None),
    ("conditional", "甲方案是周一上线。", "如果我反对这个方案，你会怎么办？", N, None),
    ("different-target", "甲方案是周一上线。", "我赞成周一上线，但反对加班。", N, None),
    ("ambiguous", "现在有两个方案：周一上线或周五上线。", "我不同意这个方案。", U, None),
    ("quote-then-own", "甲方案是周一上线。", "小陈说：“我反对。”我支持这个方案。", N, None),
    ("nested", "甲方案是周一上线。", "小周说：“小陈说：‘我反对这个方案。’”", N, None),
    ("implicit-synonym", "乙方案是周五上线。", "我不赞成周五上线。", D, "beta"),
)


class SemanticLlmNativeTests(unittest.TestCase):
    def test_real_llm_structured_contrasts(self):
        model_key = os.environ.get("SOCIOLAB_LLM_MODEL_KEY", "qwen3-4b")
        provider = LocalLlamaSemanticProvider(int(os.environ["SOCIOLAB_LLM_PORT"]),
            os.environ["SOCIOLAB_LLM_MODEL_FILE"], model_key=model_key)
        baseline_path = Path(__file__).resolve().parents[2] / "docs/experiments/2026-11-28-llm/native-run-1-qwen3-4b.json"
        baseline_report = json.loads(baseline_path.read_text(encoding="utf-8"))
        summary = baseline_report["summary"]
        self.assertEqual(summary["result_hash"], _digest({k: v for k, v in summary.items() if k != "result_hash"}))
        baseline = {r["case_id"]: r for r in baseline_report["rows"]}
        self.assertEqual(set(baseline), {c[0] for c in CASES})
        self.assertEqual(summary["case_hashes"], [r["result"]["result_hash"] for r in baseline_report["rows"]])
        self.assertEqual(summary["joint_matches"], sum(r["joint_match"] for r in baseline_report["rows"]))
        holder_refs = {"direct-alpha": "SPEAKER", "direct-beta": "SPEAKER",
            "reported": "OTHER", "quoted": "OTHER", "both": "BOTH", "negated": "NONE",
            "conditional": "NONE", "different-target": "NONE", "ambiguous": "UNRESOLVED",
            "quote-then-own": "OTHER", "nested": "OTHER", "implicit-synonym": "SPEAKER"}
        descriptions = {"dev": "缩短会议时间", "alpha": "周一上线", "beta": "周五上线"}
        fixtures = [fixture("development", "development", "我们提议缩短会议时间。", "可以再讨论。", ["dev"])]
        fixtures += [fixture(cid, "test", prior, target, ["alpha", "beta"])
            for cid, prior, target, _, _ in CASES]
        plan = freeze_disagreement_plan([case for _, _, case in fixtures])
        frozen = freeze_llm_inputs(plan, descriptions, model_key=model_key)
        frozen_baseline = freeze_llm_inputs(plan, descriptions, model_key="qwen3-4b")
        references = {cid: (state, pid) for cid, _, _, state, pid in CASES}
        rows = []
        for dataset, data, case in fixtures[1:]:
            cid = case["case_id"]
            prior = baseline[cid]
            old_result = prior["result"]
            self.assertEqual(old_result["result_hash"], _digest({k: v for k, v in old_result.items() if k != "result_hash"}))
            self.assertEqual(old_result["context_hash"], case["context"]["context_hash"])
            self.assertEqual(old_result["input_plan_hash"], frozen_baseline["input_plan_hash"])
            proposals = {p["id"]: descriptions[p["id"]] for p in case["proposals"]}
            old_request, _, _ = _request(case["context"], data, proposals, model_key="qwen3-4b")
            self.assertEqual(old_result["request_hash"], _digest(old_request))
            new_request, _, _ = _request(case["context"], data, proposals, model_key=model_key)
            self.assertEqual({**new_request, "model": old_request["model"]}, old_request)
            result = score_semantic_case(dataset, plan, frozen, cid, original_bytes=data,
                proposal_texts=descriptions, provider=provider)
            self.assertFalse(result["semantic_annotation_created"])
            self.assertEqual(result["context_hash"], case["context"]["context_hash"])
            candidate = result["candidate"]
            expected = references[cid]
            self.assertEqual((prior["authored_expected_state"], prior["authored_expected_proposal"]), expected)
            self.assertEqual(result["request_hash"], _digest(new_request))
            if candidate is not None:
                decision = candidate["decision"]
                actual = (decision["state"], decision["proposal_id"])
                self.assertEqual(result["status"], "VALID_UNQUALIFIED_CANDIDATE")
                self.assertTrue(all(0 <= e["start"] < e["end"] <=
                    len(data[case["context"]["entries"][-1]["content_record_id"]].decode("utf-8"))
                    for e in decision["evidence"]))
            else:
                actual = None
                self.assertIn(result["status"], ("INVALID_MODEL_OUTPUT", "INCOMPLETE_MODEL_OUTPUT"))
            rows.append({"case_id": cid, "authored_expected_state": expected[0],
                "authored_expected_proposal": expected[1], "joint_match": actual == expected,
                "authored_expected_holder": holder_refs[cid],
                "holder_match": candidate is not None and candidate["holder"] == holder_refs[cid],
                "baseline_joint_match": prior["joint_match"],
                "baseline_holder_match": old_result["candidate"] is not None and old_result["candidate"]["holder"] == holder_refs[cid],
                "baseline_result_hash": old_result["result_hash"], "result": result})
            print("SEMANTIC_LLM_CASE_JSON=" + json.dumps(rows[-1], ensure_ascii=False, sort_keys=True), flush=True)
        self.assertEqual(len(rows), len(CASES))
        valid = sum(r["result"]["candidate"] is not None for r in rows)
        resolved = sum(r["result"]["candidate"] is not None and
            r["result"]["candidate"]["decision"]["state"] != U for r in rows)
        joint = sum(r["joint_match"] for r in rows)
        result = {"schema": "sociolab.semantic-llm-native-diagnostics.v1",
            "comparison_status": "AUTHORED_DIAGNOSTICS_NOT_INDEPENDENT",
            "case_count": len(rows), "valid_outputs": valid, "resolved_outputs": resolved,
            "joint_matches": joint,
            "holder_matches": sum(r["holder_match"] for r in rows),
            "state_proposal_holder_matches": sum(r["joint_match"] and r["holder_match"] for r in rows),
            "baseline_joint_matches": summary["joint_matches"],
            "baseline_holder_matches": sum(r["baseline_holder_match"] for r in rows),
            "baseline_state_proposal_holder_matches": sum(r["baseline_joint_match"] and r["baseline_holder_match"] for r in rows),
            "improved_state_proposal_cases": [r["case_id"] for r in rows if r["joint_match"] and not r["baseline_joint_match"]],
            "regressed_state_proposal_cases": [r["case_id"] for r in rows if not r["joint_match"] and r["baseline_joint_match"]],
            "case_hashes": [r["result"]["result_hash"] for r in rows],
            "provider": provider.identity, "qualification_status": "NOT_ESTABLISHED",
            "semantic_annotation_created": False}
        result["result_hash"] = _digest(result)
        print("SEMANTIC_LLM_SUMMARY_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        # Require that the actual structured interface works at least once.
        # Wrong and unresolved model outputs remain visible; no target accuracy gate.
        self.assertGreater(valid, 0)
