"""Exact review gate tests and replay of genuine archived LLM reports."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

from sociolab.events import ingest_records
from sociolab import semantic_actions as sa
from sociolab import semantic_admission as ad
from sociolab.semantic_llm import _digest, _json, _model_profile, RUNTIME
from test_semantic_actions import fixture, action, raw


ARCHIVE = Path(__file__).resolve().parents[1] / "docs/experiments/2026-11-28-llm/native-run-1-semantic-actions.json"


def decision(actions, status="CANDIDATES"):
    return {"status": status, "actions": actions}


def report(context, frozen, request, binding, candidate, status="VALID_UNQUALIFIED_CANDIDATES", finish="stop"):
    """Authored boundary fixture, not a pretrained model call."""
    model_id, model_hash, alias = _model_profile("qwen3-8b")
    value = {"schema": "sociolab.semantic-actions-result.v1", "profile": sa.PROFILE,
        "context_hash": context["context_hash"], "input_hash": frozen["input_hash"],
        "source_speaker_id": context["entries"][-1]["actor"],
        "target_content_record_id": context["entries"][-1]["content_record_id"],
        "provider": {"model_id": model_id, "model_sha256": model_hash,
            "model_alias": alias, "runtime": RUNTIME, "reasoning_mode": "off"},
        "request_hash": _digest(request), "response_hash": _digest("fictional"),
        "finish_reason": finish, "status": status, "candidate": None if candidate is None else
            sa._validate_output(_json(candidate), *binding),
        "semantic_annotation_created": False, "qualification_status": "NOT_ESTABLISHED"}
    value["result_hash"] = _digest(value)
    return value


def rehash(value):
    value["result_hash"] = _digest({k: v for k, v in value.items() if k != "result_hash"})


def audit_args(prior=None, target=None, case_id=None):
    kwargs = {}
    if prior is not None:
        kwargs["prior"] = prior
    if target is not None:
        kwargs["target"] = target
    if case_id is not None:
        kwargs["case_id"] = case_id
    dataset, context, data, people, topics = fixture(**kwargs)
    frozen = sa.freeze_actions_input(context, people, topics)
    request, *binding = sa._request(context, data, people, topics, model_key="qwen3-8b", reasoning_mode="off")
    reference_input = ad.freeze_review_input(context, people, topics)
    return dataset, context, frozen, data, people, topics, request, binding, reference_input


def reviews(reference_input, cutoff, a, b=None):
    return [{"method": {"kind": "human", "id": rid, "version": "1"},
        "review_input_hash": reference_input["review_input_hash"], "admission_cutoff": cutoff,
        "decision": deepcopy(ref)} for rid, ref in (("fictional-r1", a), ("fictional-r2", a if b is None else b))]


def assess(args, model, refs, *, dataset=None, cutoff=None):
    original, context, frozen, data, people, topics, _, _, ri = args
    return ad.assess_semantic_admission(original if dataset is None else dataset, context, frozen, model,
        original_bytes=data, people=people, topics=topics, model_key="qwen3-8b",
        reasoning_mode="off", admission_cutoff=context["knowledge_cutoff"] if cutoff is None else cutoff,
        reviews=refs)


class AdmissionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.args = audit_args()
        self.dataset, self.context, self.frozen, _, _, _, self.request, self.binding, self.ri = self.args
        self.cutoff = self.context["knowledge_cutoff"]
        self.own = action()
        self.other = action("A3", "disagreement", "T2", "T2", "REPORTED", "小陈反对乙方案")
        self.full = decision([self.own, self.other])

    def model(self, candidate=None):
        return report(self.context, self.frozen, self.request, self.binding,
            self.full if candidate is None else candidate)

    def test_consensus_separates_expression_from_report(self):
        refs = reviews(self.ri, self.cutoff, self.full, decision([self.other, self.own]))
        before = self.dataset.content_hash
        r = assess(self.args, self.model(), refs)
        self.assertEqual(r["reference_status"], "EXACT_DECLARED_REFERENCE_AGREEMENT")
        self.assertEqual(r["exact_matched_action_count"], 2)
        self.assertEqual([row["disposition"] for row in r["rows"]],
            ["REVIEWED_DIRECT_EXPRESSION_CANDIDATE", "REVIEWED_REPORTED_OR_QUOTED_CLAIM"])
        self.assertEqual(len(r["reviewed_direct_expression_candidate_hashes"]), 1)
        self.assertEqual(r["source_speaker_id"], "B")
        self.assertEqual(r["occurred_at"], 2)
        self.assertEqual(r["observation_status"], "NOT_ADMITTED")
        self.assertFalse(r["network_mutated"])
        self.assertEqual(before, self.dataset.content_hash)
        self.assertEqual(r, assess(self.args, self.model(), refs))
        self.assertNotIn("我支持", str(r))

    def test_reference_disagreement_and_unresolved_withhold(self):
        for other, expected in ((decision([self.own]), "REFERENCE_DISAGREEMENT"),
                                (decision([self.own], "UNRESOLVED"), "REVIEW_UNRESOLVED")):
            with self.subTest(expected=expected):
                r = assess(self.args, self.model(), reviews(self.ri, self.cutoff, self.full, other))
                self.assertEqual(r["reference_status"], expected)
                self.assertIsNone(r["agreed_reference_count"])
                self.assertEqual(r["reviewed_direct_expression_candidate_hashes"], [])

    def test_wrong_and_missing_candidates_remain_visible(self):
        r = assess(self.args, self.model(decision([self.other])),
            reviews(self.ri, self.cutoff, decision([self.own])))
        self.assertEqual(r["exact_matched_action_count"], 0)
        self.assertEqual(r["rows"][0]["disposition"], "NOT_IN_AGREED_REFERENCE")
        self.assertEqual(len(r["missing_agreed_reference_hashes"]), 1)
        self.assertEqual(r["reviewed_direct_expression_candidate_hashes"], [])

    def test_polarity_modality_and_quote_are_not_direct_behavior(self):
        for field, value, expected in (("polarity", "NEGATED", "REVIEWED_NEGATED_OR_UNRESOLVED_POLARITY"),
                ("modality", "CONDITIONAL", "REVIEWED_NONASSERTED_OR_UNRESOLVED_MODALITY"),
                ("attribution", "QUOTED", "REVIEWED_REPORTED_OR_QUOTED_CLAIM")):
            with self.subTest(field=field):
                candidate = {**self.own, field: value}
                d = decision([candidate])
                r = assess(self.args, self.model(d), reviews(self.ri, self.cutoff, d))
                self.assertEqual(r["rows"][0]["disposition"], expected)
                self.assertEqual(r["reviewed_direct_expression_candidate_hashes"], [])

    def test_model_unresolved_withholds_even_matched_partial_candidate(self):
        model = self.model(decision([self.own], "UNRESOLVED"))
        r = assess(self.args, model, reviews(self.ri, self.cutoff, decision([self.own])))
        self.assertEqual(r["exact_matched_action_count"], 1)
        self.assertEqual(r["rows"][0]["disposition"], "MODEL_UNRESOLVED")
        self.assertEqual(r["reviewed_direct_expression_candidate_hashes"], [])

    def test_invalid_output_not_reviewed_no_action(self):
        m = report(self.context, self.frozen, self.request, self.binding, None, "INVALID_MODEL_OUTPUT")
        r = assess(self.args, m, reviews(self.ri, self.cutoff, decision([], "NO_IN_SCOPE_ACTION")))
        self.assertEqual(r["model_status"], "INVALID_MODEL_OUTPUT")
        self.assertEqual(r["agreed_reference_count"], 0)
        self.assertEqual(r["observation_status"], "NOT_ADMITTED")

    def test_reviewers_and_exact_input_required(self):
        for change in ("same-id", "model-reviewer", "wrong-hash", "wrong-cutoff"):
            refs = reviews(self.ri, self.cutoff, self.full)
            if change == "same-id":
                refs[1]["method"]["id"] = refs[0]["method"]["id"]
            elif change == "model-reviewer":
                refs[1]["method"]["kind"] = "model"
            elif change == "wrong-hash":
                refs[1]["review_input_hash"] = "wrong"
            else:
                refs[1]["admission_cutoff"] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                assess(self.args, self.model(), refs)

    def test_model_report_rehash_cannot_change_input_or_source_span(self):
        refs = reviews(self.ri, self.cutoff, self.full)
        for field in ("request", "evidence", "actor", "assertion"):
            m = self.model()
            if field == "request":
                m["request_hash"] = "changed"
            elif field == "evidence":
                m["candidate"]["actions"][0]["evidence"][0]["content_revision"] = "2"
            elif field == "actor":
                m["candidate"]["actions"][0]["actor_id"] = "C"
            else:
                m["candidate"]["actions"][0]["assertion_status"] = "ESTABLISHED"
            rehash(m)
            with self.subTest(field=field), self.assertRaises(ValueError):
                assess(self.args, m, refs)

    def test_new_receipt_rebind_and_stale_content(self):
        model = self.model()
        extended = ingest_records(self.dataset,
            [raw("D", "entity.observed", {"entity_id": "D", "entity_type": "person"}, 0)],
            received_at="2026-11-28T08:01:00Z")
        r = assess(self.args, model, reviews(self.ri, self.cutoff+1, self.full),
            dataset=extended, cutoff=self.cutoff+1)
        self.assertEqual(r["extraction_cutoff"], self.cutoff)
        self.assertEqual(r["admission_cutoff"], self.cutoff+1)
        self.assertNotEqual(r["current_context_hash"], r["context_hash"])
        payload = next(r["payload"] for r in self.dataset.records if r["record_id"] == "c2")
        replacement = raw("c2-new", "content.observed", {**payload, "content_revision": "2"}, 2)
        replacement.update(fact_id="c2", supersedes="c2")
        stale = ingest_records(self.dataset, [replacement], received_at="2026-11-28T08:01:00Z")
        with self.assertRaises(ValueError):
            assess(self.args, model, reviews(self.ri, self.cutoff+1, self.full),
                dataset=stale, cutoff=self.cutoff+1)


class ArchivedModelReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = json.loads(ARCHIVE.read_text(encoding="utf-8"))
        summary, = d["summaries"]
        self = cls
        self.rows = {r["case_id"]: r for r in d["rows"]}
        if summary["result_hash"] != _digest({k: v for k, v in summary.items() if k != "result_hash"}):
            raise ValueError("archive summary digest mismatch")
        if summary["case_hashes"] != [r["result"]["result_hash"] for r in d["rows"]]:
            raise ValueError("archive case hash mismatch")

    def replay(self, case_id, target, authored):
        args = audit_args(target=target, case_id=case_id)
        ref = reviews(args[-1], args[1]["knowledge_cutoff"], authored)
        return assess(args, self.rows[case_id]["result"], ref)

    def test_real_reported_and_own_output_remains_two_different_dispositions(self):
        own = action()
        other = action("A3", "disagreement", "T2", "T2", "REPORTED", "小陈反对乙方案")
        r = self.replay("reported-and-own", "小陈反对乙方案，我支持甲方案。", decision([own, other]))
        self.assertEqual(r["exact_matched_action_count"], 2)
        self.assertEqual(len(r["reviewed_direct_expression_candidate_hashes"]), 1)
        self.assertEqual([row["disposition"] for row in r["rows"]],
            ["REVIEWED_REPORTED_OR_QUOTED_CLAIM", "REVIEWED_DIRECT_EXPRESSION_CANDIDATE"])

    def test_real_negation_error_rejected_by_reference(self):
        a = action(label="disagreement", quote="我没有反对甲方案。")
        a["polarity"] = "NEGATED"
        r = self.replay("negated", "我没有反对甲方案。", decision([a]))
        self.assertEqual(r["rows"][0]["action"]["action"], "support")
        self.assertEqual(r["rows"][0]["disposition"], "NOT_IN_AGREED_REFERENCE")
        self.assertEqual(r["reviewed_direct_expression_candidate_hashes"], [])

    def test_real_conditional_kept_without_behavior_admission(self):
        a = action(quote="如果甲方案通过，我就支持它。")
        a["modality"] = "CONDITIONAL"
        r = self.replay("conditional", "如果甲方案通过，我就支持它。", decision([a]))
        self.assertEqual(r["exact_matched_action_count"], 1)
        self.assertEqual(r["rows"][0]["disposition"], "REVIEWED_NONASSERTED_OR_UNRESOLVED_MODALITY")

    def test_real_invalid_output_retains_missing_reference(self):
        a = action()
        b = action(label="disagreement", subject="T2", topic="T2", quote="反对乙方案")
        r = self.replay("two-topics", "我支持甲方案，但反对乙方案。", decision([a,b]))
        self.assertEqual(r["model_status"], "INVALID_MODEL_OUTPUT")
        self.assertEqual(r["agreed_reference_count"], 2)
        self.assertEqual(len(r["missing_agreed_reference_hashes"]), 2)
        self.assertEqual(r["rows"], [])
