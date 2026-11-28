"""Fresh real-model structural probes after the archived R3j run."""
import json
import os
import unittest

from sociolab.chinese_syntax import LocalChineseSyntax, _hash
from sociolab.chinese_predicate_frames import collect_predicate_frames
from sociolab.language_context import bind_language_context
from test_disagreement_nli_pretrained import fixture


CASES = (
    ("nested-quotation", "小周说：“小陈说：‘我反对这个提议。’”", "BALANCED"),
    ("unclosed-quotation", "小陈说：“我反对。", "UNBALANCED"),
    ("quote-then-own-clause", "小陈说：“我反对。”我支持。", "BALANCED"),
    ("double-negation", "我并不是不同意这个方案。", "BALANCED"),
    ("different-target", "我反对延期，而不是反对这个提议。", "BALANCED"),
    ("omitted-subject", "反对这个方案。", "BALANCED"),
)


class FreshPredicateFramesTests(unittest.TestCase):
    def test_actual_model_and_structural_frames(self):
        provider = LocalChineseSyntax(os.environ["SOCIOLAB_STANZA_MODEL_DIR"])
        rows = []
        for cid, target, quote_status in CASES:
            dataset, data, case = fixture(cid, "test", "我们提议周三迁移数据。", target, ["migration"])
            context = case["context"]
            ids = [e["content_record_id"] for e in context["entries"]]
            conversation = {k: context["conversation"][k] for k in
                ("id", "revision", "source_ref", "interaction_record_ids")}
            self.assertEqual(bind_language_context(dataset,
                knowledge_cutoff=context["knowledge_cutoff"], target_record_id=ids[-1],
                preceding_record_ids=ids[:-1], conversation=conversation,
                original_bytes=data), context)
            record = next(r for r in dataset.records if r["record_id"] == ids[-1])
            evidence = provider.extract(ids[-1], record["payload"], data[ids[-1]])
            frames = collect_predicate_frames(ids[-1], record["payload"], data[ids[-1]], evidence)
            self.assertEqual(frames["quotation_scan"]["status"], quote_status)
            self.assertFalse(frames["semantic_annotation_created"])
            self.assertTrue(all(f["holder_candidate"]["role"] == "UNRESOLVED"
                for f in frames["frames"] if quote_status != "BALANCED" or len(f["quote_ranges"]) > 1))
            self.assertTrue(all(f["assertion_status"] == "NOT_ESTABLISHED"
                and f["semantic_topic"] is None for f in frames["frames"]))
            rows.append({"case_id": cid, "target": target, "context_hash": context["context_hash"],
                "syntax": evidence, "frames": frames})
        self.assertEqual(len(rows), 6)
        report = {"schema": "sociolab.predicate-frame-diagnostics.v1",
            "status": "AUTHORED_STRUCTURAL_PROBES_NOT_HELD_OUT",
            "provider": provider.identity, "rows": rows,
            "semantic_annotation_created": False, "qualification_status": "NOT_ESTABLISHED"}
        report["result_hash"] = _hash(report)
        print("CHINESE_PREDICATE_FRAMES_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
