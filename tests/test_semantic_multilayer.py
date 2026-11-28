"""Aligned expression, participation and explicit activity-context evidence."""
import unittest
from copy import deepcopy

from sociolab.events import ingest_records
from sociolab.semantic_llm import _digest
from sociolab import semantic_observations as so
from sociolab import semantic_multilayer as ml
from test_semantic_actions import action, raw
from test_semantic_admission import audit_args, decision
from test_semantic_observations import (bind_args, create_model, snapshot, content_payload,
    AUTHORITY, T1, T2, T3)


def interval(record, lo, hi):
    return {**record, "valid_interval": [lo, hi]}


def setup():
    original = audit_args()
    dataset = ingest_records(original[0], [
        raw("workshop-entity", "entity.observed", {"entity_id":"workshop", "entity_type":"activity"}, 0),
        *[interval(raw("membership-"+p, "membership.observed",
            {"actor":p,"population":"team","status":"present"}, 0), 0, 10)
            for p in ("A","B","C")],
        interval(raw("coverage", "coverage.observed",
            {"population":"team","layer":"participation","actors":["A","B","C"],"status":"complete"},0),0,10),
        interval(raw("workshop-desc","activity.observed",
            {"activity":"workshop","activity_type":"meeting","status":"held"},1),1,5),
        raw("attendance-A","participation.observed",
            {"actor":"A","activity":"workshop","role":"participant","status":"attended"},2),
    ], received_at="2026-11-28T08:01:00Z")
    args = bind_args(dataset, original[3], original[4], original[5],
        "c2", ["c1"], ["i1","i2"], "multi-layer")
    d = decision([action()])
    store = snapshot(so.SemanticObservationStore.empty(dataset), args, create_model(args,d), d,
        revision_id="r1", received_at=T1)
    return dataset, store, args


class MultilayerTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.store, self.args = setup()
        self.cutoff = len(self.dataset.records)
        base = so.project_reviewed_expressions(self.dataset,self.store,
            journal_cutoff=self.cutoff,observation_cutoff=1,start=0,end=5)
        self.eid = base["events"][0]["event_id"]
        self.links = [{"event_id":self.eid,"activity_record_id":"workshop-desc",
            "evidence_ref":"fictional:explicit-meeting-context"}]
        self.plan = self.freeze()
        self.spec = {"journal_cutoff":self.cutoff,"observation_cutoff":1,"as_of":T1,
            "start":0,"end":5,"population":"team","roles":[],
            "activity_links":self.plan,"affiliation_projection":"count","max_pairs":10}

    def freeze(self, **changes):
        args = {"journal_cutoff":self.cutoff,"observation_cutoff":1,"as_of":T1,
            "start":0,"end":5,"authority":AUTHORITY,"links":self.links}
        return ml.freeze_activity_links(self.dataset,self.store,**{**args,**changes})

    def frame(self, dataset=None, **changes):
        return ml.build_multilayer_frame(self.dataset if dataset is None else dataset,
            self.store, **{**self.spec,**changes})

    def late_attendance(self):
        return ingest_records(self.dataset, [
            raw("attendance-B","participation.observed",
                {"actor":"B","activity":"workshop","role":"participant","status":"attended"},3),
        ], received_at="2026-11-28T08:15:00Z")

    def test_independent_expression_activity_and_attendance_layers(self):
        result = self.frame()
        self.assertTrue(result["participation"]["coverage"]["complete"])
        self.assertEqual(result["expression"]["edges"][0]["target"], {"kind":"topic","id":"alpha"})
        self.assertEqual([(e["source"],e["target"]) for e in result["participation"]["edges"]],
            [("A","workshop")])
        self.assertEqual(len(result["activity_context_edges"]), 2)
        self.assertEqual({e["layer"] for e in result["activity_context_edges"]},
            {"PERSON_ACTIVITY_EXPRESSION_CONTEXT","TOPIC_ACTIVITY_EXPRESSION_CONTEXT"})
        self.assertEqual(result["activity_context_links"][0]["attendance_in_window"],"NO_SELECTED_INCIDENCE")
        self.assertEqual(result["affiliation"]["projected_edge_count"],0)
        self.assertFalse(result["causal_effect_identified"])
        self.assertEqual(result,self.frame())

    def test_no_implicit_association_without_explicit_plan(self):
        r = self.frame(activity_links=None)
        self.assertEqual(r["activity_context_edges"],[])
        self.assertEqual(r["activity_context_links"],[])
        self.assertEqual(len(r["expression"]["events"]),1)
        self.assertEqual(len(r["participation"]["edges"]),1)
        empty = self.frame(activity_links=self.freeze(links=[]))
        self.assertEqual(empty["activity_context_links"],[])
        self.assertIsNotNone(empty["activity_link_plan_hash"])

    def test_late_attendance_and_upstream_coattendance_projection(self):
        updated = self.late_attendance()
        after_spec = {**self.spec,"journal_cutoff":len(updated.records),"as_of":T2}
        before, after = self.frame(), ml.build_multilayer_frame(updated,self.store,**after_spec)
        self.assertEqual(before,self.frame(updated))
        self.assertEqual(after["activity_context_links"][0]["attendance_in_window"],"SELECTED_INCIDENCE")
        self.assertEqual(after["affiliation"]["projected_edge_count"],1)
        edge, = after["affiliation"]["projected_edges"]
        self.assertEqual((edge["source"],edge["target"],edge["strength"]),("A","B",1))
        change = ml.compare_multilayer_frames(updated,self.store,before=self.spec,after=after_spec)
        self.assertEqual(change["comparison"],"FIXED_WINDOW_RECEIPT_OR_SELECTION_CHANGE")
        self.assertEqual(len(change["changes"]),1)
        row, = change["changes"]
        self.assertEqual(row["layer"],"PERSON_ACTIVITY_ATTENDANCE")
        self.assertEqual((row["before_count"],row["after_count"]),(0,1))
        self.assertEqual(row["change"],"ADDED_TO_VIEW")

    def test_activity_revision_withholds_old_link_not_expression(self):
        replacement = interval(raw("workshop-desc-new","activity.observed",
            {"activity":"workshop","activity_type":"revised-meeting","status":"held"},1),1,5)
        replacement.update(fact_id="workshop-desc",supersedes="workshop-desc")
        updated = ingest_records(self.dataset,[replacement],received_at="2026-11-28T08:15:00Z")
        r = self.frame(updated,journal_cutoff=len(updated.records),as_of=T2)
        self.assertEqual(len(r["expression"]["events"]),1)
        self.assertEqual(r["activity_context_edges"],[])
        self.assertEqual(r["withheld_activity_links"],[
            {"event_id":self.eid,"reason":"ACTIVITY_DESCRIPTION_NOT_CURRENT"}])
        self.assertEqual(len(r["participation"]["edges"]),1)
        self.assertEqual(self.frame(updated),self.frame())

    def test_corrected_source_withholds_link_and_expression(self):
        text = "我反对甲方案。".encode()
        replacement = raw("c2-new","content.observed",content_payload("i2",text,"2"),2)
        replacement.update(fact_id="c2",supersedes="c2")
        updated = ingest_records(self.dataset,[replacement],received_at="2026-11-28T08:15:00Z")
        r = self.frame(updated,journal_cutoff=len(updated.records),as_of=T2)
        self.assertEqual(r["expression"]["events"],[])
        self.assertEqual(r["activity_context_edges"],[])
        self.assertEqual(r["withheld_activity_links"],[{"event_id":self.eid,"reason":"EXPRESSION_NOT_CURRENT"}])
        self.assertEqual(len(r["participation"]["edges"]),1)

    def test_source_window_evolution_not_relation_dissolution(self):
        before = {**self.spec,"start":0,"end":3}
        after = {**self.spec,"start":3,"end":5}
        result = ml.compare_multilayer_frames(self.dataset,self.store,before=before,after=after)
        self.assertEqual(result["comparison"],"ORDERED_WINDOW_DESCRIPTIVE_CHANGE")
        self.assertEqual(len(result["changes"]),4)
        self.assertTrue(all(r["change"]=="REMOVED_FROM_VIEW" for r in result["changes"]))
        self.assertFalse(result["causal_effect_identified"])
        self.assertIn("NOT_RELATIONSHIP",result["interpretation"])

    def test_future_source_and_expression_and_link_receipts_rejected(self):
        with self.assertRaisesRegex(ValueError,"expression prefix"):
            self.frame(as_of="2026-11-28T08:05:00Z")
        with self.assertRaisesRegex(ValueError,"journal prefix"):
            self.frame(as_of="2026-11-28T08:00:00Z")
        with self.assertRaisesRegex(ValueError,"link plan is unavailable"):
            self.frame(activity_links=self.freeze(as_of=T2))
        with self.assertRaisesRegex(ValueError,"link plan is unavailable"):
            self.frame(observation_cutoff=0)

    def test_invalid_link_requires_current_exact_event_and_activity_record(self):
        for patch, message in (({"event_id":"wrong"},"selected expression"),
                ({"activity_record_id":"missing"},"ACTIVITY_DESCRIPTION_NOT_CURRENT")):
            with self.subTest(patch=patch),self.assertRaisesRegex(ValueError,message):
                self.freeze(links=[{**self.links[0],**patch}])
        with self.assertRaisesRegex(ValueError,"one explicit"):
            self.freeze(links=self.links*2)

    def test_activity_time_and_status_are_required_for_binding(self):
        for name, status, span, error in (
            ("future","held",[3,5],"ACTIVITY_OUTSIDE_EXPRESSION_TIME"),
            ("scheduled","scheduled",[1,5],"ACTIVITY_NOT_HELD")):
            new = ingest_records(self.dataset,[
                raw(name+"-entity","entity.observed",{"entity_id":name,"entity_type":"activity"},0),
                interval(raw(name+"-desc","activity.observed",{"activity":name,
                    "activity_type":"meeting","status":status},span[0]),*span),
            ],received_at="2026-11-28T08:15:00Z")
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,error):
                ml.freeze_activity_links(new,self.store,journal_cutoff=len(new.records),
                    observation_cutoff=1,as_of=T2,start=0,end=5,authority=AUTHORITY,
                    links=[{**self.links[0],"activity_record_id":name+"-desc"}])

    def test_rehashed_plan_cannot_change_canonical_binding(self):
        p = deepcopy(self.plan)
        p["links"][0]["activity_id"]="made-up"
        p["link_hash"] = _digest({k:v for k,v in p.items() if k!="link_hash"})
        with self.assertRaisesRegex(ValueError,"do not replay"):
            self.frame(activity_links=p)

    def test_incomplete_participation_coverage_preserves_unknown(self):
        replacement = interval(raw("coverage-new","coverage.observed",
            {"population":"team","layer":"participation","actors":["A","B","C"],"status":"partial"},0),0,10)
        replacement.update(fact_id="coverage",supersedes="coverage")
        updated=ingest_records(self.dataset,[replacement],received_at="2026-11-28T08:15:00Z")
        result=self.frame(updated,journal_cutoff=len(updated.records),as_of=T2)
        self.assertFalse(result["participation"]["coverage"]["complete"])
        self.assertIsNone(result["affiliation"])
        self.assertEqual(result["affiliation_status"],"NOT_RUN_INCOMPLETE_PARTICIPATION_COVERAGE")
        self.assertEqual(result["activity_context_links"][0]["attendance_in_window"],"UNKNOWN_OR_OUTSIDE_PARTICIPATION_SCOPE")

    def test_comparison_rejects_scope_and_time_mismatch(self):
        for changes, error in (({"roles":["chair"]},"identical participation"),
                ({"start":2,"end":6},"nonoverlapping"),({"as_of":T1,"observation_cutoff":0,
                    "activity_links":None},"nondecreasing")):
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,error):
                ml.compare_multilayer_frames(self.dataset,self.store,before=self.spec,
                    after={**self.spec,**changes})
