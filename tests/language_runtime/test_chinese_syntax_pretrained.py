"""Actual dependency parses of fictional cases; no inferred semantic labels."""
import json
import os
import unittest

from sociolab.chinese_syntax import LocalChineseSyntax, _hash
from sociolab.language_context import bind_language_context
from test_disagreement_nli_pretrained import fixture
from test_disagreement_nli_attribution import CASES, PRIOR


EXTRA = (
    ("reported-negation", "小陈说他不反对这个提议。"),
    ("nested-speech", "小陈说小周反对这个提议。"),
    ("own-report-of-other", "我说小陈反对这个提议。"),
    ("quoted-question", "小陈问：‘你反对这个提议吗？’"),
    ("different-action", "小陈反对这个提议，我只反对延期。"),
    ("explicit-disagreement", "我不同意这个方案。"),
)


class ChineseSyntaxPretrainedTests(unittest.TestCase):
    def test_real_parser_contrasts(self):
        provider = LocalChineseSyntax(os.environ["SOCIOLAB_STANZA_MODEL_DIR"])
        rows = []
        for cid, target in [(c[0], c[1]) for c in CASES] + list(EXTRA):
            dataset, data, case = fixture(cid, "test", PRIOR, target, ["migration"])
            context = case["context"]
            ids = [e["content_record_id"] for e in context["entries"]]
            conversation = {k: context["conversation"][k] for k in
                ("id", "revision", "source_ref", "interaction_record_ids")}
            self.assertEqual(bind_language_context(dataset, knowledge_cutoff=context["knowledge_cutoff"],
                target_record_id=ids[-1], preceding_record_ids=ids[:-1],
                conversation=conversation, original_bytes=data), context)
            record = next(r for r in dataset.records if r["record_id"] == ids[-1])
            report = provider.extract(ids[-1], record["payload"], data[ids[-1]])
            self.assertFalse(report["semantic_annotation_created"])
            self.assertEqual(report["content_hash"], context["entries"][-1]["content_hash"])
            text = data[ids[-1]].decode("utf-8")
            # Only fictional fixtures: attach readable words to the retained
            # dependency coordinates for inspection, not inferred stance.
            words = [[{"text": text[w["start"]:w["end"]], **w} for w in sentence]
                     for sentence in report["sentences"]]
            rows.append({"case_id": cid, "target": target, "context_hash": context["context_hash"],
                "evidence": report, "readable_words": words})
        self.assertEqual(len(rows), 18)
        result = {"schema": "sociolab.syntax-attribution-diagnostics.v1",
            "status": "AUTHORED_DIAGNOSTICS_NOT_HELD_OUT", "provider": provider.identity,
            "rows": rows, "semantic_annotation_created": False,
            "qualification_status": "NOT_ESTABLISHED"}
        result["result_hash"] = _hash(result)
        print("CHINESE_SYNTAX_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
