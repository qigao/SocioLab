"""Real Stanza+NLI diagnostic, using authored inputs only."""
import json
import os
from pathlib import Path
import unittest

from sociolab.chinese_syntax import LocalChineseSyntax
from sociolab.disagreement_nli import LocalNliProvider, _digest
from sociolab.language_context import bind_language_context
from sociolab.predicate_nli import collect_predicate_nli, screen_global_candidate
from test_disagreement_nli_pretrained import fixture
from test_disagreement_nli_attribution import CASES, PRIOR, PROPOSAL
from test_chinese_syntax_pretrained import EXTRA
from test_chinese_predicate_frames_pretrained import CASES as FRAME_CASES


FRESH = (
    ("fresh-disagree-synonym", "我不赞成这个提议。", True),
    ("fresh-deny-saying", "我不是说我反对这个提议。", False),
    ("fresh-hearsay", "我听说小陈反对这个提议。", False),
    ("fresh-different-object", "我赞成周三迁移数据，但反对加班。", False),
    ("fresh-explicit-object", "我反对周三迁移数据。", True),
    ("fresh-conditional-self", "如果我反对这个提议，你会怎么办？", False),
    ("fresh-question-self", "我会反对这个提议吗？", False),
    ("fresh-reject-attribution", "小陈说我反对这个提议，但那不是我的意思。", False),
)


class JointNativeTests(unittest.TestCase):
    def test_stanza_nli_screen(self):
        syntax = LocalChineseSyntax(os.environ["SOCIOLAB_STANZA_MODEL_DIR"])
        nli = LocalNliProvider(os.environ["SOCIOLAB_NLI_MODEL_DIR"])
        root = Path(__file__).resolve().parents[2]
        archived = json.loads((root / "docs/experiments/2026-11-28-nli/native-run-7-attribution.json").read_text(encoding="utf-8"))["report"]
        self.assertEqual(archived["result_hash"], _digest({k: v for k, v in archived.items() if k != "result_hash"}))
        baseline = {r["case_id"]: r for r in archived["rows"] if r["mode"] == "with_context"
            and r["template"] == "named" and r["subject"] == "speaker"}
        self.assertEqual(len(baseline), 12)
        cases = [(cid, text, own, "replay") for cid, text, own, other in CASES]
        cases += [(cid, text, None, "structural") for cid, text in EXTRA]
        cases += [(cid, text, None, "structural") for cid, text, _ in FRAME_CASES]
        cases += [(cid, text, expected, "fresh") for cid, text, expected in FRESH]
        rows = []
        for cid, target, expected, group in cases:
            dataset, data, case = fixture(cid, "test", PRIOR, target, ["migration"])
            ctx = case["context"]
            ids = [e["content_record_id"] for e in ctx["entries"]]
            conversation = {k: ctx["conversation"][k] for k in
                ("id", "revision", "source_ref", "interaction_record_ids")}
            self.assertEqual(bind_language_context(dataset, knowledge_cutoff=ctx["knowledge_cutoff"],
                target_record_id=ids[-1], preceding_record_ids=ids[:-1],
                conversation=conversation, original_bytes=data), ctx)
            record = next(r for r in dataset.records if r["record_id"] == ids[-1])
            evidence = syntax.extract(ids[-1], record["payload"], data[ids[-1]])
            local = collect_predicate_nli(ids[-1], record["payload"], data[ids[-1]], evidence, nli)
            # Use the original named/context hypothesis for direct comparability.
            prior, text = [data[rid].decode("utf-8") for rid in ids]
            premise = "前文：小周对小林说：" + prior + "\n目标消息：小林对小周说：" + text
            hypothesis = "小林反对" + PROPOSAL + "。"
            global_row = {"pair_hash": _digest([premise, hypothesis]), **nli.score(premise, hypothesis)}
            self.assertEqual(global_row["status"], "SCORED")
            if group == "replay":
                self.assertEqual(global_row["pair_hash"], baseline[cid]["pair_hash"])
                self.assertEqual(expected, baseline[cid]["expected_entailment"])
            screen = screen_global_candidate(global_row, local["rows"])
            self.assertEqual(screen["joint_topic_binding"], "NOT_ESTABLISHED")
            self.assertFalse(local["semantic_annotation_created"])
            report = {"case_id": cid, "group": group, "expected_explicit_opposition": expected,
                "target": target, "context_hash": ctx["context_hash"], "global_nli": global_row,
                "syntax": evidence, "predicate_nli": local, "screen": screen}
            report["report_hash"] = _digest(report)
            rows.append(report)
            print("JOINT_PREDICATE_CASE_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
        self.assertEqual(len(rows), 32)
        summary = []
        for group in ("replay", "fresh"):
            selected = [r for r in rows if r["group"] == group]
            for profile in ("global_only", "screened"):
                positive = lambda r: (r["screen"]["global_native_entailment"] if profile == "global_only"
                    else r["screen"]["status"] == "RETAINED_UNQUALIFIED_CANDIDATE")
                counts = {"retained_reference_positive": 0, "retained_reference_nonpositive": 0,
                    "unresolved_reference_positive": 0, "unresolved_reference_nonpositive": 0}
                for r in selected:
                    key = ("retained_" if positive(r) else "unresolved_") + (
                        "reference_positive" if r["expected_explicit_opposition"] else "reference_nonpositive")
                    counts[key] += 1
                summary.append({"group": group, "profile": profile, "count": len(selected), **counts})
        result = {"schema": "sociolab.joint-predicate-diagnostic.v1",
            "comparison_status": "AUTHORED_POST_RESULT_NOT_INDEPENDENT", "case_count": len(rows),
            "predicate_pair_count": sum(len(r["predicate_nli"]["rows"]) for r in rows),
            "case_hashes": [r["report_hash"] for r in rows], "summaries": summary,
            "syntax_provider": syntax.identity, "nli_provider": nli.identity,
            "semantic_annotation_created": False, "qualification_status": "NOT_ESTABLISHED"}
        result["result_hash"] = _digest(result)
        print("JOINT_PREDICATE_SUMMARY_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
