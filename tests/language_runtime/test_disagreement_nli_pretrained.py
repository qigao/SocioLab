"""Explicit native-runtime smoke; requires the real offline snapshot and dependencies."""
from hashlib import sha256
import json
import os
import unittest

from sociolab.disagreement_nli import LocalNliProvider, freeze_nli_inputs, score_case
from sociolab.disagreement_study import freeze_disagreement_plan
from sociolab.events import EventDataset, ingest_records
from sociolab.language_context import bind_language_context


def raw(rid, kind, payload, at):
    return {"record_id": rid, "fact_id": rid, "operation": "assert", "supersedes": None,
        "kind": kind, "occurred_at": at, "valid_interval": None, "payload": payload,
        "source": {"system": "fictional-nli-smoke", "record_id": rid,
            "revision": "1", "evidence_ref": "test:" + rid}}


def fixture(cid, partition, prior, target, proposals):
    dataset = EventDataset.from_mapping({"schema": "sociolab.events.v1", "dataset_id": cid,
        "origin": "synthetic", "source_revision": "1", "clock": {"kind": "ticks", "run_id": cid}, "records": []})
    batch = [raw(p, "entity.observed", {"entity_id": p, "entity_type": "person"}, 0) for p in ("A", "B")]
    originals = {}
    for i, (text, actor, addressee) in enumerate(((prior, "A", "B"), (target, "B", "A")), 1):
        iid, content_id = f"i{i}", f"c{i}"
        data = originals[content_id] = text.encode("utf-8")
        batch.append(raw(iid, "interaction.observed", {"actor": actor, "target": addressee,
            "action": "utterance", "topic": "meeting"}, i))
        batch.append(raw(content_id, "content.observed", {"interaction_record_id": iid,
            "content_ref": "fictional:" + content_id, "content_revision": "1",
            "content_hash": "sha256:" + sha256(data).hexdigest(), "language": "zh",
            "length": {"unicode_codepoint": len(text), "utf8_byte": len(data)}}, i))
    dataset = ingest_records(dataset, batch, received_at="2026-11-28T08:00:00Z")
    context = bind_language_context(dataset, knowledge_cutoff=6, target_record_id="c2", preceding_record_ids=["c1"],
        conversation={"id": cid, "revision": "1", "source_ref": "fictional:" + cid,
            "interaction_record_ids": ["i1", "i2"]}, original_bytes=originals)
    case = {"case_id": cid, "partition": partition, "context": context,
        "proposals": [{"id": pid, "family": pid} for pid in proposals]}
    return dataset, originals, case


class PretrainedSmokeTests(unittest.TestCase):
    def test_fictional_context_contrasts(self):
        provider = LocalNliProvider(os.environ["SOCIOLAB_NLI_MODEL_DIR"])
        descriptions = {"dev": "调整会议议程", "alpha": "周一上线", "beta": "周五上线"}
        fixtures = [fixture("dev", "development", "我建议调整会议议程。", "可以继续讨论。", ["dev"])]
        for cid, prior, target in [
            ("direct-alpha", "甲方案是周一上线。", "我不同意这个方案。"),
            ("direct-beta", "乙方案是周五上线。", "我不同意这个方案。"),
            ("attributed", "甲方案是周一上线。", "他说他不同意这个方案。"),
            ("negated", "甲方案是周一上线。", "我并不是不同意这个方案。"),
        ]:
            fixtures.append(fixture(cid, "test", prior, target, ["alpha", "beta"]))
        plan = freeze_disagreement_plan([case for _, _, case in fixtures])
        frozen = freeze_nli_inputs(plan, descriptions)
        for dataset, data, case in fixtures[1:]:
            for mode in ("target_only", "with_context"):
                report = score_case(dataset, plan, frozen, case["case_id"], original_bytes=data,
                    proposal_texts=descriptions, provider=provider, mode=mode)
                self.assertFalse(report["semantic_annotation_created"])
                self.assertEqual([r["proposal_id"] for r in report["rows"]], ["alpha", "beta"])
                for row in report["rows"]:
                    self.assertEqual(row["status"], "SCORED")
                    self.assertAlmostEqual(sum(row["scores"].values()), 1.0)
                # Fictional inputs only. Do not print reports for real participants.
                print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        # Actual scores, not a benchmark: no assumed semantic accuracy assertions.
