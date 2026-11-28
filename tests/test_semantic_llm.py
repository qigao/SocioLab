"""Contract tests for local LLM structured candidates (no real model calls)."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

from sociolab import semantic_llm as llm


def output(state="DISAGREEMENT", holder="SPEAKER", proposal="P1", quote="我不同意"):
    return json.dumps({"state": state, "holder": holder, "proposal": proposal,
        "evidence_quote": quote}, ensure_ascii=False)


class SemanticContractTests(unittest.TestCase):
    def test_exact_evidence_and_alias(self):
        result = llm._validate_output(output(), {"P1": "proposal-alpha"}, "🙂我不同意这个方案。")
        self.assertEqual(result, {"holder": "SPEAKER", "decision": {"state": "DISAGREEMENT",
            "proposal_id": "proposal-alpha", "evidence": [{"start": 1, "end": 5}]}})

    def test_reported_speech_is_allowed_as_nonpositive(self):
        result = llm._validate_output(output("NO_DISAGREEMENT", "OTHER", "NONE", "他说"),
            {"P1": "a"}, "他说他反对。")
        self.assertIsNone(result["decision"]["proposal_id"])
        self.assertEqual(result["holder"], "OTHER")
        self.assertEqual(result["decision"]["state"], "NO_DISAGREEMENT")

    def test_unresolved_is_not_negative(self):
        result = llm._validate_output(output("UNRESOLVED", "UNRESOLVED", "NONE", ""),
            {"P1": "a"}, "这个方案呢？")
        self.assertEqual(result["decision"], {"state": "UNRESOLVED", "proposal_id": None, "evidence": []})

    def test_reject_unknown_proposal_holder_and_fields(self):
        for bad in (output(proposal="P2"), output(holder="OTHER"), output(quote=""),
                    output("NO_DISAGREEMENT", "SPEAKER", "NONE", ""),
                    output("UNRESOLVED", "NONE", "NONE", ""),
                    '{"state":"DISAGREEMENT","state":"NO_DISAGREEMENT"}',
                    '{"state":"UNRESOLVED","holder":"UNRESOLVED","proposal":"NONE","evidence_quote":"","extra":1}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                llm._validate_output(bad, {"P1": "a"}, "我不同意")

    def test_reject_fabricated_rewritten_or_repeated_evidence(self):
        for text in ("我反对", "我不同意，我不同意"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "exact unique"):
                llm._validate_output(output(), {"P1": "a"}, text)

    def test_request_preserves_context_and_opaque_aliases(self):
        context = {"entries": [
            {"role": "preceding", "actor": "private-A", "addressee": "private-B", "content_record_id": "c1"},
            {"role": "target", "actor": "private-B", "addressee": "private-A", "content_record_id": "c2"}]}
        data = {"c1": "建议采用甲。".encode(), "c2": "我不同意这个方案。".encode()}
        before = deepcopy((context, data))
        request, aliases, target = llm._request(context, data, {"alpha": "方案甲", "beta": "方案乙"})
        payload = json.loads(request["messages"][1]["content"])
        self.assertEqual(aliases, {"P1": "alpha", "P2": "beta"})
        self.assertEqual(target, "我不同意这个方案。")
        self.assertEqual(payload["target_speaker"], payload["messages"][1]["speaker"])
        self.assertEqual(payload["messages"][0]["addressee"], payload["target_speaker"])
        self.assertNotIn("private-A", json.dumps(request))
        self.assertNotIn("alpha", json.dumps(request))
        self.assertEqual((context, data), before)
        self.assertFalse(request["chat_template_kwargs"]["enable_thinking"])
        self.assertIn("P2", request["response_format"]["schema"]["properties"]["proposal"]["enum"])

    def test_input_limit_is_not_truncation(self):
        ctx = {"entries": [{"role": "target", "actor": "A", "addressee": "B", "content_record_id": "c"}]}
        with self.assertRaisesRegex(ValueError, "no truncation"):
            llm._request(ctx, {"c": "长".encode() * 3000}, {"p": "甲"})

    def test_provider_rejects_bad_file_and_port(self):
        with self.assertRaisesRegex(ValueError, "server port"):
            llm.LocalLlamaSemanticProvider(0, "/not-used")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.gguf"
            path.write_bytes(b"not a model")
            with self.assertRaisesRegex(ValueError, "GGUF hash mismatch"):
                llm.LocalLlamaSemanticProvider(8080, path)

    def test_freeze_proposal_and_prompt_identity(self):
        cases = [{"proposals": [{"id": "p"}]}]
        plan = {"cases": cases, "plan_hash": "fixture"}
        with patch.object(llm, "freeze_disagreement_plan", return_value=plan):
            a = llm.freeze_llm_inputs(plan, {"p": "方案甲"})
            b = llm.freeze_llm_inputs(plan, {"p": "方案乙"})
            self.assertNotEqual(a["input_plan_hash"], b["input_plan_hash"])
            self.assertEqual(a["prompt_hash"], llm._digest(llm.SYSTEM))
            self.assertNotIn("方案甲", str(a))
            with self.assertRaisesRegex(ValueError, "description set"):
                llm.freeze_llm_inputs(plan, {})
