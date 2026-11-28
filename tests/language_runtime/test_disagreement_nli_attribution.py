"""Attribution contrasts authored after R3h; not a held-out corpus."""
import json
import os
import unittest

from sociolab.disagreement_nli import LocalNliProvider, _digest, freeze_nli_inputs
from sociolab.disagreement_study import freeze_disagreement_plan
from sociolab.language_context import bind_language_context
from test_disagreement_nli_pretrained import fixture


# Expected entailment of explicitly expressed opposition attributed to each
# named person in the target message, not their actual private beliefs.
# No model scores were used to select these new texts or expectations.
CASES = (
    ("direct", "我反对这个提议。", True, False),
    ("reported", "小陈反对这个提议。", False, True),
    ("quoted", "小陈说：‘我反对这个提议。’", False, True),
    ("both", "小陈反对这个提议，我也反对。", True, True),
    ("other-opposes-self-supports", "小陈反对这个提议，但我支持。", False, True),
    ("self-opposes-other-supports", "小陈支持这个提议，但我反对。", True, False),
    ("denial", "我没有反对这个提议。", False, False),
    ("unidentified", "听说有人反对这个提议。", False, False),
    ("question", "小陈反对这个提议吗？", False, False),
    ("conditional", "如果小陈反对这个提议，我就再考虑。", False, False),
    ("reported-own-answer", "小陈问我是否反对这个提议，我说我反对。", True, False),
    ("explicit-no-position", "小陈说他反对这个提议，我还没有决定。", False, True),
)
PRIOR = "我们提议周三迁移数据。"
PROPOSAL = "周三迁移数据"
TEMPLATES = {
    "named": "{name}反对{proposal}。",
    "attribution": "目标消息明确将反对{proposal}的意见归于{name}。",
}


class NliAttributionTests(unittest.TestCase):
    def test_named_source_contrasts(self):
        provider = LocalNliProvider(os.environ["SOCIOLAB_NLI_MODEL_DIR"])
        descriptions = {"dev": "缩短会议时间", "migration": PROPOSAL}
        fixtures = [fixture("development", "development", "建议缩短会议时间。", "请大家考虑。", ["dev"])]
        fixtures += [fixture(cid, "test", PRIOR, target, ["migration"])
            for cid, target, _, _ in CASES]
        plan = freeze_disagreement_plan([case for _, _, case in fixtures])
        frozen = freeze_nli_inputs(plan, descriptions)
        expected = {cid: {"speaker": own, "reported_person": other}
            for cid, _, own, other in CASES}
        rows = []
        for dataset, data, case in fixtures[1:]:
            context = case["context"]
            ids = [e["content_record_id"] for e in context["entries"]]
            conversation = {k: context["conversation"][k] for k in
                ("id", "revision", "source_ref", "interaction_record_ids")}
            self.assertEqual(bind_language_context(dataset,
                knowledge_cutoff=context["knowledge_cutoff"], target_record_id=ids[-1],
                preceding_record_ids=ids[:-1], conversation=conversation,
                original_bytes=data), context)
            # Fixed fictional display names. No source name extraction or
            # resolution of a real third-party identity is implemented here.
            self.assertEqual([e["actor"] for e in context["entries"]], ["A", "B"])
            prior, target = [data[rid].decode("utf-8") for rid in ids]
            target_line = "目标消息：小林对小周说：" + target
            for mode, premise in (("target_only", target_line),
                    ("with_context", "前文：小周对小林说：" + prior + "\n" + target_line)):
                for template, pattern in TEMPLATES.items():
                    for subject, name in (("speaker", "小林"), ("reported_person", "小陈")):
                        hypothesis = pattern.format(name=name, proposal=PROPOSAL)
                        result = provider.score(premise, hypothesis)
                        self.assertEqual(result["status"], "SCORED")
                        self.assertAlmostEqual(sum(result["scores"].values()), 1.0)
                        rows.append({"case_id": case["case_id"], "context_hash": context["context_hash"],
                            "mode": mode, "template": template, "subject": subject,
                            "expected_entailment": expected[case["case_id"]][subject],
                            "premise": premise, "hypothesis": hypothesis,
                            "pair_hash": _digest([premise, hypothesis]), **result})
        self.assertEqual(len(rows), 96)
        summaries = []
        for mode in ("target_only", "with_context"):
            for template in TEMPLATES:
                group = [r for r in rows if r["mode"] == mode and r["template"] == template]
                self.assertEqual(len(group), 24)
                for subject in ("speaker", "reported_person"):
                    subset = [r for r in group if r["subject"] == subject]
                    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
                    for r in subset:
                        # Diagnostic of native NLI argmax only; not a social
                        # annotation decision policy or a calibrated cutoff.
                        entailment = (r["scores"]["entailment"] >
                            max(r["scores"]["neutral"], r["scores"]["contradiction"]))
                        key = ("tp" if entailment else "fn") if r["expected_entailment"] else (
                            "fp" if entailment else "tn")
                        counts[key] += 1
                    summaries.append({"mode": mode, "template": template, "subject": subject,
                        **counts, "count": len(subset)})
        result = {"schema": "sociolab.nli-attribution-diagnostics.v1",
            "comparison_status": "POST_RESULT_AUTHORED_NOT_HELD_OUT",
            "input_plan_hash": frozen["input_plan_hash"], "provider": provider.identity,
            "rows": rows, "native_argmax_diagnostics": summaries,
            "semantic_annotation_created": False, "qualification_status": "NOT_ESTABLISHED"}
        result["result_hash"] = _digest(result)
        print("NLI_ATTRIBUTION_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
