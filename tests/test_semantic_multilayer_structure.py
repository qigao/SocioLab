"""Native multilayer structural analysis and conservative scope checks."""
from copy import deepcopy
import unittest

from sociolab.events import ingest_records
from sociolab.semantic_multilayer_structure import compare_multilayer_structure
from sociolab.semantic_observations import SemanticObservationStore
from test_semantic_actions import action, raw
from test_semantic_admission import decision
from test_semantic_observations import (bind_args, create_model, snapshot, content_payload,
    T1, T2, T3)
from test_semantic_multilayer import setup, interval


def spec(dataset, store, as_of=T1, **changes):
    return {"journal_cutoff":len(dataset.records),"observation_cutoff":len(store.records),
        "as_of":as_of,"start":0,"end":5,"population":"team","roles":[],
        "activity_links":None,"affiliation_projection":"count","max_pairs":10, **changes}


class MultilayerStructureTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.store, self.args = setup()
        self.before = spec(self.dataset,self.store)
        self.after = deepcopy(self.before)

    def compare(self, dataset=None, store=None, **settings):
        args = {"before":self.before,"after":self.after,"actors":["A","B","C"],
            "actions":["support","insult"],"seed":0,"resolution":1.0,"max_nodes":10,"max_edges":20,
            **settings}
        return compare_multilayer_structure(self.dataset if dataset is None else dataset,
            self.store if store is None else store,**args)

    def test_topic_profile_does_not_create_person_ties(self):
        result = self.compare()
        support = next(row for row in result["expression_analysis"] if row["action"]=="support")
        self.assertEqual(support["person_person"]["structure"]["before"]["edge_count"],0)
        self.assertEqual(support["person_person"]["communities"]["before"]["status"],"NO_EDGES")
        self.assertEqual(support["person_topic"]["before"]["person_counts"]["B"],
            {"distinct_selected_topics":1,"selected_expression_count":1})
        self.assertEqual(support["person_topic"]["before"]["topics"],
            [{"topic_id":"alpha","distinct_selected_actors":1,"selected_expression_count":1}])
        self.assertIsNone(result["combined_score"])
        self.assertFalse(result["causal_effect_identified"])
        self.assertFalse(result["time_respecting_transmission_validated"])
        self.assertEqual(result,self.compare())

    def test_late_attendance_changes_affiliation_not_expression_community(self):
        updated = ingest_records(self.dataset,[raw("attendance-B","participation.observed",
            {"actor":"B","activity":"workshop","role":"participant","status":"attended"},3)],
            received_at="2026-11-28T08:15:00Z")
        r = self.compare(updated,after=spec(updated,self.store,T2))
        support = next(row for row in r["expression_analysis"] if row["action"]=="support")
        self.assertTrue(support["person_person"]["communities"]["lineage"]["membership_stability"]["same_partition"])
        attendance = r["attendance_analysis"]
        self.assertEqual(attendance["analysis_relation"],"derived_co_participation")
        self.assertEqual(attendance["structure"]["before"]["edge_count"],0)
        self.assertEqual(attendance["structure"]["after"]["edge_count"],1)
        self.assertEqual(attendance["activities"]["projected_relation_changes"]["added"][0]["strength"],1)
        self.assertFalse(attendance["communities"]["lineage"]["membership_stability"]["same_partition"])

    def test_expression_correction_and_new_event_change_selected_structure(self):
        text = "你真是个废物。".encode()
        correction = raw("c2-new","content.observed",content_payload("i2",text,"2"),2)
        correction.update(fact_id="c2",supersedes="c2")
        updated = ingest_records(self.dataset,[correction],received_at="2026-11-28T08:15:00Z")
        args = bind_args(updated,{"c1":self.args[3]["c1"],"c2-new":text},
            self.args[4],self.args[5],"c2-new",["c1"],["i1","i2"],"corrected")
        candidate = decision([action(label="insult",subject="A1",topic="NONE",quote="你真是个废物")])
        store = snapshot(self.store,args,create_model(args,candidate),candidate,
            revision_id="r2",supersedes="r1",received_at=T2)
        result = self.compare(updated,store,after=spec(updated,store,T2),expression_group_members=["B"])
        insult = next(r for r in result["expression_analysis"] if r["action"]=="insult")
        s = insult["person_person"]
        self.assertEqual(s["structure"]["before"]["edge_count"],0)
        self.assertEqual(s["structure"]["after"]["edge_count"],1)
        self.assertEqual(s["centrality"]["delta"]["B"]["out_expression_count"],1)
        self.assertEqual(s["centrality"]["delta"]["A"]["in_neighbors"],1)
        self.assertEqual(s["key_groups"]["original"]["before"]["status"],"OK")
        self.assertEqual(s["key_groups"]["new_selection"]["reason"],"directed_group_selection_not_qualified")
        support = next(r for r in result["expression_analysis"] if r["action"]=="support")
        self.assertEqual(support["person_topic"]["after"]["person_counts"]["B"]["selected_expression_count"],0)
        self.assertEqual(result["attendance_analysis"]["structure"]["after"]["edge_count"],0)

    def test_selected_cohort_is_not_attendance_population(self):
        r = self.compare(actors=["A"],actions=["support"])
        support, = r["expression_analysis"]
        self.assertEqual(support["fixed_cohort"],["A"])
        self.assertEqual(len(support["person_topic"]["before"]["outside_cohort_event_ids"]),1)
        self.assertEqual(support["person_topic"]["before"]["topics"],[])
        self.assertEqual(r["attendance_analysis"]["population"]["before_person_count"],3)

    def test_incomplete_attendance_skips_native_analysis_only(self):
        replacement = interval(raw("coverage-new","coverage.observed",
            {"population":"team","layer":"participation","actors":["A","B","C"],"status":"partial"},0),0,10)
        replacement.update(fact_id="coverage",supersedes="coverage")
        updated = ingest_records(self.dataset,[replacement],received_at="2026-11-28T08:15:00Z")
        r = self.compare(updated,after=spec(updated,self.store,T2))
        self.assertEqual(r["attendance_analysis"],{"status":"NOT_RUN","reason":"incomplete_declared_participation_coverage"})
        self.assertTrue(all(x["person_person"]["status"]=="OK" for x in r["expression_analysis"]))

    def test_budget_skips_structure_without_changing_cohort(self):
        r = self.compare(max_nodes=2)
        self.assertTrue(all(x["person_person"]["reason"]=="expression_structure_budget_exceeded"
            for x in r["expression_analysis"]))
        self.assertEqual(r["attendance_analysis"]["reason"],"attendance_structure_budget_exceeded")
        self.assertEqual(r["settings"]["actors"],["A","B","C"])

    def test_explicit_no_affiliation_projection_does_not_invent_person_graph(self):
        before = {**self.before,"affiliation_projection":"none"}
        r = self.compare(before=before,after=before)
        self.assertEqual(r["attendance_analysis"]["structure"]["before"]["reason"],
            "person_graph_projection_not_requested")

    def test_unknown_duplicate_or_noncanonical_cohort_rejected(self):
        for actors in (["A","A"],["D"],["workshop"],[]):
            with self.subTest(actors=actors),self.assertRaises(ValueError):
                self.compare(actors=actors)
        mapping = raw("identity","identity.mapped",{"alias":"C","canonical":"A"},3)
        # The existing coverage declaration names both A and C. Correct it
        # before the identity merge, preserving the journal's duplicate guard.
        with self.assertRaisesRegex(ValueError,"coverage actors duplicate"):
            ingest_records(self.dataset,[mapping],received_at="2026-11-28T08:15:00Z")
        coverage = interval(raw("coverage-merged","coverage.observed",
            {"population":"team","layer":"participation","actors":["A","B"],"status":"complete"},0),0,10)
        coverage.update(fact_id="coverage",supersedes="coverage")
        updated = ingest_records(self.dataset,[coverage,mapping],received_at="2026-11-28T08:15:00Z")
        with self.assertRaisesRegex(ValueError,"canonical"):
            self.compare(updated,after=spec(updated,self.store,T2))

    def test_scope_and_group_options_are_explicit(self):
        for settings in ({"actions":["invalid"]},{"expression_group_members":["D"]},
            {"expression_group_members":["A","B"]},{"seed":-1},{"resolution":float("nan")},
            {"max_edges":-1},{"attendance_group_size":0}):
            with self.subTest(settings=settings),self.assertRaises(ValueError):
                self.compare(**settings)
        with self.assertRaisesRegex(ValueError,"nonoverlapping"):
            self.compare(after={**self.after,"start":1,"end":6})

    def test_connected_coattendance_runs_original_group_selection(self):
        updated = ingest_records(self.dataset,[
            raw("attendance-B","participation.observed",
                {"actor":"B","activity":"workshop","role":"participant","status":"attended"},3),
            raw("second-entity","entity.observed",{"entity_id":"second","entity_type":"activity"},0),
            interval(raw("second-desc","activity.observed",
                {"activity":"second","activity_type":"meeting","status":"held"},3),3,5),
            raw("attendance-B-second","participation.observed",
                {"actor":"B","activity":"second","role":"participant","status":"attended"},4),
            raw("attendance-C-second","participation.observed",
                {"actor":"C","activity":"second","role":"participant","status":"attended"},4),
            ],received_at="2026-11-28T08:15:00Z")
        r = self.compare(updated,after=spec(updated,self.store,T2),attendance_group_size=1)
        groups = r["attendance_analysis"]["key_groups"]
        self.assertEqual(groups["original"]["before"]["reason"],"disconnected_group_selection_not_qualified")
        selected = groups["new_selection"]
        self.assertEqual(selected["kind"],"GROUP_SELECTION")
        self.assertEqual(selected["algorithm"],"networkx.prominent_group")
        self.assertEqual(selected["members"],["B"])
        self.assertAlmostEqual(selected["score"],1.0)
        self.assertFalse(selected["global_optimum_claim"])
