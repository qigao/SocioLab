"""Longitudinal panel tests: explicit schedule, immutable issued prefixes."""
from copy import deepcopy
import unittest

from sociolab.events import ingest_records
from sociolab.semantic_llm import _digest
from sociolab.semantic_panel import (freeze_semantic_panel, start_semantic_panel,
    append_semantic_wave, verify_semantic_panel)
from sociolab.semantic_multilayer import freeze_activity_links
from sociolab.semantic_observations import project_reviewed_expressions, withdraw_reviewed_snapshot
from test_semantic_actions import action, raw
from test_semantic_admission import decision
from test_semantic_observations import (bind_args, create_model, snapshot, content_payload,
    T1, T2, T3, AUTHORITY)
from test_semantic_multilayer import setup, interval


def rehash(value, field):
    value[field] = _digest({k:v for k,v in value.items() if k!=field})


class SemanticPanelTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.store, self.args = setup()
        self.schedule = [{"wave_id":"w1","start":0,"end":3,"as_of":T1},
            {"wave_id":"w2","start":3,"end":6,"as_of":T2},
            {"wave_id":"w3","start":6,"end":9,"as_of":T3}]
        self.settings = {"actors":["C","B","A"],"actions":["support","insult"],
            "population":"team","roles":[],"affiliation_projection":"count",
            "max_pairs":10,"seed":0,"resolution":1.0,"max_nodes":10,"max_edges":20}
        self.plan = self.freeze()
        self.empty = start_semantic_panel(self.dataset,self.store,self.plan)

    def freeze(self, **overrides):
        return freeze_semantic_panel(self.dataset,self.store,
            **{**{"registered_at":T1,"schedule":self.schedule,"settings":self.settings},**overrides})

    def append(self, panel=None, dataset=None, store=None, wave_id="w1", plan=None, links=None):
        return append_semantic_wave(self.dataset if dataset is None else dataset,
            self.store if store is None else store,self.plan if plan is None else plan,
            self.empty if panel is None else panel,wave_id=wave_id,activity_links=links)

    @staticmethod
    def row(wave, actor):
        return next(r for r in wave["features"]["rows"] if r["actor_id"]==actor)

    def test_frozen_schedule_and_partial_panel(self):
        self.assertEqual(self.plan["settings"]["actors"],["A","B","C"])
        self.assertEqual(self.empty["pending_wave_ids"],["w1","w2","w3"])
        first = self.append()
        self.assertEqual(first["pending_wave_ids"],["w2","w3"])
        self.assertEqual(self.empty["waves"],[])
        b = self.row(first["waves"][0],"B")
        self.assertEqual(b["expression_actions"]["support"]["person_topic"]["selected_expression_count"],1)
        self.assertEqual(b["expression_actions"]["support"]["person_person"]["out_expression_count"],0)
        self.assertEqual(b["attendance"]["complete_view_incidence_count"],0)
        self.assertFalse(first["future_prediction"])
        self.assertFalse(first["external_availability_attested"])
        self.assertEqual(first,verify_semantic_panel(self.dataset,self.store,self.plan,first))

    def test_full_panel_preserves_fixed_cohort_and_equal_windows(self):
        first = self.append()
        second = self.append(first,wave_id="w2")
        third = self.append(second,wave_id="w3")
        self.assertEqual(third["pending_wave_ids"],[])
        self.assertEqual(third["waves"][:2],second["waves"])
        for wave in third["waves"]:
            self.assertEqual([r["actor_id"] for r in wave["features"]["rows"]],["A","B","C"])
        # The third window has declared complete coverage and no activities.
        # Preserve its cohort and valid zero observations, not missing values.
        empty = third["waves"][2]["features"]
        self.assertEqual(empty["attendance"]["structure_status"],"OK")
        self.assertEqual(empty["attendance"]["native_persons"],["A","B","C"])
        self.assertEqual(empty["attendance"]["communities"]["status"],"NO_EDGES")
        for row in empty["rows"]:
            self.assertEqual(row["attendance"]["scope"],"COMPLETE_DECLARED_VIEW")
            self.assertEqual(row["attendance"]["complete_view_incidence_count"],0)
            self.assertEqual(row["attendance"]["coattendance_neighbors"],0)
            self.assertEqual(row["attendance"]["coattendance_weight"],0)
            self.assertEqual(row["attendance"]["coattendance_unweighted_betweenness"],0.0)
        self.assertEqual(third,verify_semantic_panel(self.dataset,self.store,self.plan,third))
        with self.assertRaisesRegex(ValueError,"next scheduled"):
            self.append(third,wave_id="w3")

    def test_late_correction_and_new_expression_do_not_revise_issued_wave(self):
        first = self.append()
        text = "你真是个废物。".encode()
        correction = raw("c2-new","content.observed",content_payload("i2",text,"2"),2)
        correction.update(fact_id="c2",supersedes="c2")
        updated = ingest_records(self.dataset,[
            correction,raw("i3","interaction.observed",{"actor":"B","target":"A",
                "action":"utterance","topic":"meeting"},4),
            raw("c3","content.observed",content_payload("i3",text),4),
            raw("attendance-A-second","participation.observed",
                {"actor":"A","activity":"workshop","role":"participant","status":"attended"},4),
            raw("attendance-B","participation.observed",
                {"actor":"B","activity":"workshop","role":"participant","status":"attended"},4)],
            received_at="2026-11-28T08:15:00Z")
        args = bind_args(updated,{"c1":self.args[3]["c1"],"c3":text},
            self.args[4],self.args[5],"c3",["c1"],["i1","i3"],"panel-second")
        candidate = decision([action(label="insult",subject="A1",topic="NONE",quote="你真是个废物")])
        store = snapshot(self.store,args,create_model(args,candidate),candidate,
            revision_id="r2",received_at=T2)
        second = self.append(first,updated,store,wave_id="w2")
        self.assertEqual(second["waves"][0],first["waves"][0])
        self.assertEqual(second["waves"][1]["observation_cutoff"],2)
        b = self.row(second["waves"][1],"B")
        self.assertEqual(b["expression_actions"]["insult"]["person_person"]["out_expression_count"],1)
        self.assertEqual(b["expression_actions"]["support"]["person_topic"]["selected_expression_count"],0)
        self.assertEqual(b["attendance"]["complete_view_incidence_count"],1)
        self.assertEqual(b["attendance"]["coattendance_neighbors"],1)
        self.assertEqual(b["attendance"]["coattendance_weight"],1)
        self.assertEqual(second,verify_semantic_panel(updated,store,self.plan,second))

    def test_missing_coverage_is_null_not_zero(self):
        first = self.append()
        replacement = interval(raw("coverage-new","coverage.observed",
            {"population":"team","layer":"participation","actors":["A","B","C"],"status":"partial"},0),0,10)
        replacement.update(fact_id="coverage",supersedes="coverage")
        updated = ingest_records(self.dataset,[replacement],received_at="2026-11-28T08:15:00Z")
        second = self.append(first,updated,wave_id="w2")
        b = self.row(second["waves"][1],"B")["attendance"]
        self.assertEqual(b["scope"],"INCOMPLETE_DECLARED_COVERAGE")
        self.assertEqual(b["selected_incidence_count"],0)
        self.assertIsNone(b["complete_view_incidence_count"])
        self.assertIsNone(b["coattendance_neighbors"])
        self.assertEqual(second["waves"][0],first["waves"][0])

    def test_future_journal_or_expression_receipt_rejected(self):
        updated = ingest_records(self.dataset,[raw("attendance-B","participation.observed",
            {"actor":"B","activity":"workshop","role":"participant","status":"attended"},4)],
            received_at=T2)
        with self.assertRaisesRegex(ValueError,"unavailable"):
            self.append(dataset=updated)
        key = self.store.records[0]["key"]
        withdrawn = withdraw_reviewed_snapshot(self.store,self.dataset,key=key,
            revision_id="future",supersedes="r1",journal_cutoff=len(self.dataset.records),
            received_at=T2,authority=AUTHORITY)
        with self.assertRaisesRegex(ValueError,"unavailable"):
            self.append(store=withdrawn)

    def test_explicit_activity_links_bound_to_wave_availability(self):
        event, = project_reviewed_expressions(self.dataset,self.store,
            journal_cutoff=len(self.dataset.records),observation_cutoff=1,start=0,end=3)["events"]
        args = {"journal_cutoff":len(self.dataset.records),"observation_cutoff":1,
            "start":0,"end":3,"authority":AUTHORITY,
            "links":[{"event_id":event["event_id"],"activity_record_id":"workshop-desc",
                      "evidence_ref":"fictional:panel-context"}]}
        early = freeze_activity_links(self.dataset,self.store,as_of=T1,**args)
        first = self.append(links=early)
        self.assertEqual(len(first["waves"][0]["activity_context_links"]),1)
        self.assertEqual(first["waves"][0]["activity_link_plan_hash"],early["link_hash"])
        future = freeze_activity_links(self.dataset,self.store,as_of=T2,**args)
        with self.assertRaisesRegex(ValueError,"unavailable"):
            self.append(links=future)

    def test_budget_preserves_counts_and_skips_costly_structure(self):
        plan = self.freeze(settings={**self.settings,"max_nodes":2})
        empty = start_semantic_panel(self.dataset,self.store,plan)
        first = self.append(empty,plan=plan)
        features = first["waves"][0]["features"]
        self.assertEqual(features["expression"]["support"]["structure_status"],
            "NOT_RUN_STRUCTURE_BUDGET_EXCEEDED")
        self.assertIsNone(features["expression"]["support"]["communities"])
        b = self.row(first["waves"][0],"B")
        self.assertIsNone(b["expression_actions"]["support"]["person_person"]["unweighted_betweenness"])
        self.assertEqual(b["expression_actions"]["support"]["person_topic"]["selected_expression_count"],1)
        self.assertIsNone(b["attendance"]["coattendance_neighbors"])

    def test_noncanonical_cohort_cannot_be_silently_dropped(self):
        first = self.append()
        coverage = interval(raw("coverage-merged","coverage.observed",
            {"population":"team","layer":"participation","actors":["A","B"],"status":"complete"},0),0,10)
        coverage.update(fact_id="coverage",supersedes="coverage")
        updated = ingest_records(self.dataset,[coverage,raw("identity","identity.mapped",
            {"alias":"C","canonical":"A"},3)],received_at="2026-11-28T08:15:00Z")
        with self.assertRaisesRegex(ValueError,"canonical"):
            self.append(first,updated,wave_id="w2")
        self.assertEqual(first,verify_semantic_panel(updated,self.store,self.plan,first))

    def test_schedule_and_order_guards(self):
        for patch in ({"start":2},{"end":7},{"wave_id":"w1"},{"as_of":T1}):
            altered = deepcopy(self.schedule)
            altered[1].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                self.freeze(schedule=altered)
        with self.assertRaisesRegex(ValueError,"next scheduled"):
            self.append(wave_id="w2")

    def test_rehashed_feature_or_registration_tampering_fails_replay(self):
        first = self.append()
        forged = deepcopy(first)
        forged["waves"][0]["features"]["rows"][0]["attendance"]["complete_view_incidence_count"] = 99
        rehash(forged["waves"][0],"wave_hash")
        rehash(forged,"panel_hash")
        with self.assertRaisesRegex(ValueError,"does not replay"):
            verify_semantic_panel(self.dataset,self.store,self.plan,forged)
        plan = deepcopy(self.plan)
        plan["registration"]["journal_prefix_hash"] = "unrelated"
        rehash(plan,"plan_hash")
        with self.assertRaisesRegex(ValueError,"registration does not replay"):
            start_semantic_panel(self.dataset,self.store,plan)
