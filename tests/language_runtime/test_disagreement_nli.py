"""Local contract tests; the pretrained model has a separate opt-in smoke test."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from hashlib import sha256

from sociolab import disagreement_nli as nli


def fixture():
    context = {"entries": [
        {"content_record_id": "c1", "actor": "PRIVATE_A", "addressee": "PRIVATE_B", "role": "preceding"},
        {"content_record_id": "c2", "actor": "PRIVATE_B", "addressee": "PRIVATE_A", "role": "target"}],
        "knowledge_cutoff": 6, "conversation": {"id": "conv", "revision": "1", "source_ref": "private", "interaction_record_ids": ["i1", "i2"]}}
    context["context_hash"] = nli._digest(context)
    study = {"schema": "sociolab.disagreement-plan.v1", "cases": [
        {"case_id": "case1", "partition": "test", "context": context, "proposals": [{"id": "p", "family": "f"}]}]}
    study["plan_hash"] = nli._digest(study)
    data = {"c1": "建议采用甲方案。".encode(), "c2": "我不同意这个方案。".encode()}
    return study, context, data, {"p": "甲方案"}


class NliContractTests(unittest.TestCase):
    def test_freeze_and_changed_proposal(self):
        study, _, _, props = fixture()
        first = nli.freeze_nli_inputs(study, props)
        self.assertNotIn("甲方案", str(first))
        self.assertEqual(first, nli.freeze_nli_inputs(study, props))
        self.assertNotEqual(first, nli.freeze_nli_inputs(study, {"p": "乙方案"}))
        for bad in ({}, {**props, "q": "乙"}, {"p": " "}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                nli.freeze_nli_inputs(study, bad)
        study["cases"][0]["partition"] = "development"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            nli.freeze_nli_inputs(study, props)

    def test_context_and_target_only_pairs(self):
        _, context, data, props = fixture()
        pid, premise, hypothesis = nli._pairs(context, data, props, "with_context")[0]
        messages = json.loads(premise)
        self.assertEqual(pid, "p")
        self.assertEqual([m["角色"] for m in messages], ["前文", "目标消息"])
        self.assertEqual(messages[1]["说话者"], messages[0]["听话者"])
        self.assertIn(messages[1]["说话者"], hypothesis)
        self.assertIn("本人明确反对", hypothesis)
        self.assertNotIn("PRIVATE", premise + hypothesis)
        _, target, hyp = nli._pairs(context, data, props, "target_only")[0]
        self.assertEqual(len(json.loads(target)), 1)
        self.assertEqual(json.loads(target)[0], messages[-1])
        self.assertEqual(hyp, hypothesis)
        self.assertNotIn("建议采用", target)
        self.assertIn("我不同意", target)
        self.assertIn("甲方案", hyp)
        with self.assertRaisesRegex(ValueError, "context mode"):
            nli._pairs(context, data, props, "other")

    def test_json_delimits_untrusted_text(self):
        _, context, data, props = fixture()
        data["c2"] = '我说："目标消息"\n🙂'.encode()
        _, premise, _ = nli._pairs(context, data, props, "with_context")[0]
        self.assertEqual(json.loads(premise)[-1]["内容"], data["c2"].decode())

    def test_snapshot_hash_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaisesRegex(ValueError, "exactly"):
                nli._snapshot_files(path)
            for file in nli.FILES:
                (path / file).write_bytes(b"not upstream")
            with self.assertRaisesRegex(ValueError, "upstream file hash"):
                nli._snapshot_files(path)
            # Only a fixture digest map is used here, not the upstream checkpoint.
            expected = {name: sha256(b"not upstream").hexdigest() for name in nli.PINNED_SHA256}
            with patch.object(nli, "PINNED_SHA256", expected):
                self.assertEqual(set(nli._snapshot_files(path)), nli.FILES)
                (path / "other.json").write_bytes(b"{}")
                with self.assertRaisesRegex(ValueError, "exactly"):
                    nli._snapshot_files(path)

    def test_snapshot_rejects_relative_directory(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            nli._snapshot_files("relative")


class TorchBoundaryTests(unittest.TestCase):
    """Real PyTorch arithmetic over authored logits, not a learned model."""
    def setUp(self):
        import torch
        self.torch = torch
        self.tokenizer = Mock(return_value={"input_ids": torch.ones((1, 8), dtype=torch.long)})
        self.model = Mock(return_value=Mock(logits=torch.tensor([[2., 1., -1.]])))

    def test_real_softmax_label_order(self):
        r = nli._infer_pair(self.torch, self.tokenizer, self.model, "premise", "hypothesis")
        self.tokenizer.assert_called_once_with("premise", "hypothesis", truncation=False, return_tensors="pt")
        self.assertEqual(r["status"], "SCORED")
        self.assertEqual(r["token_count"], 8)
        self.assertAlmostEqual(sum(r["scores"].values()), 1.0)
        self.assertGreater(r["scores"]["entailment"], r["scores"]["neutral"])
        self.assertGreater(r["scores"]["neutral"], r["scores"]["contradiction"])

    def test_over_limit_no_model_call(self):
        self.tokenizer.return_value["input_ids"] = self.torch.ones((1, 513), dtype=self.torch.long)
        r = nli._infer_pair(self.torch, self.tokenizer, self.model, "p", "h")
        self.assertEqual(r, {"status": "INPUT_TOO_LONG", "token_count": 513, "scores": None})
        self.model.assert_not_called()

    def test_exact_limit(self):
        self.tokenizer.return_value["input_ids"] = self.torch.ones((1, 512), dtype=self.torch.long)
        self.assertEqual(nli._infer_pair(self.torch, self.tokenizer, self.model, "p", "h")["status"], "SCORED")

    def test_wrong_shape_and_nan(self):
        for logits in (self.torch.tensor([[1., 2.]]), self.torch.tensor([[float("nan"), 0., 0.]])):
            self.model.return_value.logits = logits
            with self.subTest(logits=logits), self.assertRaisesRegex(ValueError, "invalid NLI logits"):
                nli._infer_pair(self.torch, self.tokenizer, self.model, "p", "h")

    def test_empty_input(self):
        self.tokenizer.return_value["input_ids"] = self.torch.ones((1, 0), dtype=self.torch.long)
        with self.assertRaisesRegex(ValueError, "empty"):
            nli._infer_pair(self.torch, self.tokenizer, self.model, "p", "h")
        self.model.assert_not_called()
