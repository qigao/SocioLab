"""Post-result exploratory diagnostics; authored contrasts, not a held-out benchmark."""
import json
import os
import unittest

from sociolab.disagreement_nli import LocalNliProvider, _pairs, _digest, freeze_nli_inputs
from sociolab.disagreement_study import freeze_disagreement_plan
from sociolab.language_context import bind_language_context
from test_disagreement_nli_pretrained import fixture


class NliDiagnosticsTests(unittest.TestCase):
    def test_format_hypothesis_and_decomposition(self):
        provider = LocalNliProvider(os.environ["SOCIOLAB_NLI_MODEL_DIR"])
        descriptions = {"dev": "调整会议议程", "alpha": "周一上线", "beta": "周五上线"}
        specifications = [
            ("direct-alpha", "甲方案是周一上线。", "我不同意这个方案。"),
            ("direct-beta", "乙方案是周五上线。", "我不同意这个方案。"),
            ("attributed", "甲方案是周一上线。", "他说他不同意这个方案。"),
            ("negated", "甲方案是周一上线。", "我并不是不同意这个方案。"),
        ]
        fixtures = [fixture("dev", "development", "我建议调整会议议程。", "可以继续讨论。", ["dev"])]
        fixtures += [fixture(cid, "test", prior, target, ["alpha", "beta"]) for cid, prior, target in specifications]
        plan = freeze_disagreement_plan([case for _, _, case in fixtures])
        frozen = freeze_nli_inputs(plan, descriptions)
        rows = []

        def probe(case, profile, premise, hypothesis, **metadata):
            scores = provider.score(premise, hypothesis)
            self.assertEqual(scores["status"], "SCORED")
            self.assertAlmostEqual(sum(scores["scores"].values()), 1.0)
            # These inputs are exclusively authored fictional diagnostics.
            rows.append({"case_id": case, "profile": profile, **metadata,
                "premise": premise, "hypothesis": hypothesis,
                "pair_hash": _digest([premise, hypothesis]), **scores})

        for dataset, data, case in fixtures[1:]:
            expected = case["context"]
            ids = [e["content_record_id"] for e in expected["entries"]]
            conversation = {k: expected["conversation"][k] for k in ("id", "revision", "source_ref", "interaction_record_ids")}
            context = bind_language_context(dataset, knowledge_cutoff=expected["knowledge_cutoff"],
                target_record_id=ids[-1], preceding_record_ids=ids[:-1], conversation=conversation, original_bytes=data)
            self.assertEqual(context, expected)
            proposals = {p["id"]: descriptions[p["id"]] for p in case["proposals"]}
            cid = case["case_id"]
            for mode in ("target_only", "with_context"):
                for pid, original, original_hyp in _pairs(context, data, proposals, mode):
                    messages = json.loads(original)
                    speaker = messages[-1]["说话者"]
                    plain = "\n".join(f'{m["角色"]}：{m["说话者"]}对{m["听话者"]}说：{m["内容"]}' for m in messages)
                    concise_hyp = f"{speaker}反对{proposals[pid]}。"
                    for format_name, premise in (("json", original), ("plain", plain)):
                        for template, hypothesis in (("original", original_hyp), ("concise", concise_hyp)):
                            probe(cid, "factorial", premise, hypothesis, mode=mode, format=format_name,
                                template=template, proposal_id=pid)
            # Deliberately separate speaker stance from antecedent identity.
            # Antecedent probes use only the single prior utterance in these
            # fixtures; no general-purpose coreference resolution is claimed.
            target = data[ids[-1]].decode("utf-8")
            prior = data[ids[0]].decode("utf-8")
            probe(cid, "stance_only", target, "我反对这个方案。")
            for pid, description in proposals.items():
                probe(cid, "antecedent_only", prior, f"这个方案是{description}。", proposal_id=pid)

        for cid, premise, hypothesis in [
            ("control-entailment", "我不同意周一上线。", "我反对周一上线。"),
            ("control-contradiction", "我同意周一上线。", "我反对周一上线。"),
            ("control-neutral", "我今天吃了午饭。", "我反对周一上线。"),
            ("control-attributed", "他说他不同意周一上线。", "我反对周一上线。"),
            ("control-negated", "我并不是不同意周一上线。", "我反对周一上线。"),
            ("control-explicit", "我反对周一上线。", "我反对周一上线。"),
        ]:
            probe(cid, "native_control", premise, hypothesis)

        self.assertEqual(len(rows), 82)
        self.assertEqual(sum(r["profile"] == "factorial" for r in rows), 64)
        result = {"schema": "sociolab.nli-exploratory-diagnostics.v1",
            "comparison_status": "POST_RESULT_EXPLORATORY_NOT_HELD_OUT",
            "input_plan_hash": frozen["input_plan_hash"], "provider": provider.identity,
            "rows": rows, "semantic_annotation_created": False,
            "qualification_status": "NOT_ESTABLISHED"}
        result["result_hash"] = _digest(result)
        print("NLI_DIAGNOSTICS_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
