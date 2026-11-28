"""Two held-out synthetic origins with separately supplied outcome observations."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from sociolab.events import EventDataset, ingest_records
from sociolab.semantic_llm import _digest
from sociolab.semantic_panel import freeze_semantic_panel, start_semantic_panel, append_semantic_wave
from sociolab import semantic_forecast as sf
from test_semantic_actions import raw
from test_semantic_multilayer import setup, interval
from test_semantic_observations import T1, T2, T3

T4 = "2026-11-28T08:40:00Z"
T5 = "2026-11-28T08:50:00Z"
SOURCE = {"system":"fictional-independent-observer","attribute":"task_completion_level",
    "minimum":0,"maximum":6,"measurement_reference":"fictional:separate-observer"}
ACTORS = ("A","B","C")
OUTCOMES = ((1,2,4),(2,3,1),(3,4,2),(2,5,3),(4,4,2))


def observation(record_id, actor, at, value, *, attribute=None):
    r = raw(record_id,"actor.attribute.observed",
        {"actor":actor,"name":SOURCE["attribute"] if attribute is None else attribute,"value":value},at)
    r["source"]["system"] = SOURCE["system"]
    return r


def batch(wave):
    return [observation(f"out-{wave}-{a}",a,3+2*wave,v)
        for a,v in zip(ACTORS,OUTCOMES[wave])]


def rehash(value, field):
    value[field] = _digest({k:v for k,v in value.items() if k!=field})


class SemanticForecastTests(unittest.TestCase):
    def setUp(self):
        self.dataset,self.store,_ = setup()
        self.schedule = [{"wave_id":f"w{i+1}","start":1+2*i,"end":3+2*i,"as_of":t}
            for i,t in enumerate((T1,T2,T3,T4,T5))]
        self.settings = {"actors":list(ACTORS),"actions":["support","insult"],
            "population":"team","roles":[],"affiliation_projection":"count",
            "max_pairs":10,"seed":0,"resolution":1.0,"max_nodes":10,"max_edges":20}
        self.panel_plan = freeze_semantic_panel(self.dataset,self.store,registered_at=T1,
            schedule=self.schedule,settings=self.settings)
        empty = EventDataset.from_mapping({"schema":"sociolab.events.v1",
            "dataset_id":"independent-outcomes","origin":"synthetic","source_revision":"1",
            "clock":self.dataset.clock,"records":[]})
        self.outcomes = ingest_records(empty,[raw("entity-"+a,"entity.observed",
            {"entity_id":a,"entity_type":"person"},0) for a in ACTORS]+batch(0),received_at=T1)
        self.plan = self.freeze()
        self.first = append_semantic_wave(self.dataset,self.store,self.panel_plan,
            start_semantic_panel(self.dataset,self.store,self.panel_plan),wave_id="w1",activity_links=None)

    def freeze(self, **kwargs):
        return sf.freeze_semantic_forecast_plan(self.dataset,self.store,self.panel_plan,self.outcomes,
            **{**{"outcome_source":SOURCE,"action":"support","initial_history_waves":3},**kwargs})

    def history(self, *, incomplete=False):
        additions = [
            raw("attendance-A-later","participation.observed",
                {"actor":"A","activity":"workshop","role":"participant","status":"attended"},4),
            raw("attendance-B","participation.observed",
                {"actor":"B","activity":"workshop","role":"participant","status":"attended"},4)]
        if incomplete:
            coverage = interval(raw("coverage-partial","coverage.observed",
                {"population":"team","layer":"participation","actors":list(ACTORS),"status":"partial"},0),0,10)
            coverage.update(fact_id="coverage",supersedes="coverage")
            additions.append(coverage)
        dataset = ingest_records(self.dataset,additions,received_at=T2)
        second = append_semantic_wave(dataset,self.store,self.panel_plan,self.first,
            wave_id="w2",activity_links=None)
        third = append_semantic_wave(dataset,self.store,self.panel_plan,second,
            wave_id="w3",activity_links=None)
        outcomes = ingest_records(self.outcomes,batch(1),received_at=T2)
        outcomes = ingest_records(outcomes,batch(2),received_at=T3)
        return dataset,third,outcomes

    def issue(self,dataset,panel,outcomes,fold="w4"):
        return sf.issue_semantic_forecast(dataset,self.store,self.panel_plan,panel,outcomes,self.plan,fold_id=fold)

    def score(self,dataset,panel,outcomes,forecast,cutoff=None):
        return sf.score_semantic_forecast(dataset,self.store,self.panel_plan,panel,outcomes,
            self.plan,forecast,target_cutoff=len(outcomes.records) if cutoff is None else cutoff)

    def test_two_origin_actual_ols_and_aggregate(self):
        dataset,panel,outcomes = self.history()
        first = self.issue(dataset,panel,outcomes)
        self.assertEqual(first["input"]["training_row_count"],6)
        self.assertEqual(first["models"]["persistence"]["raw_predictions"],[3.0,4.0,2.0])
        self.assertTrue(all(m["status"]=="OK" for m in first["models"].values()))
        self.assertEqual(first["models"]["language_network_ols"]["rank"],4)
        target4 = ingest_records(outcomes,batch(3),received_at=T4)
        saved_cutoff = len(target4.records)
        with patch("numpy.linalg.lstsq",side_effect=AssertionError("scoring must not fit")):
            score4 = self.score(dataset,panel,target4,first)
        fourth = append_semantic_wave(dataset,self.store,self.panel_plan,panel,
            wave_id="w4",activity_links=None)
        second = self.issue(dataset,fourth,target4,fold="w5")
        target5 = ingest_records(target4,batch(4),received_at=T5)
        manifest = [{"panel":panel,"forecast":first,"target_cutoff":saved_cutoff},
                    {"panel":fourth,"forecast":second,"target_cutoff":len(target5.records)}]
        with patch("numpy.linalg.lstsq",side_effect=AssertionError("evaluation must not fit")):
            report = sf.evaluate_semantic_forecasts(dataset,self.store,self.panel_plan,target5,self.plan,manifest)
        self.assertEqual(report["scores"][0],score4)
        self.assertEqual(report["actor_forecast_count"],6)
        self.assertTrue(all(m["status"]=="OK" for m in report["models"].values()))
        self.assertTrue(all(m["n_evaluated"]==6 for m in report["models"].values()))
        self.assertAlmostEqual(report["models"]["persistence"]["metrics"]["clipped"]["mae"],1.5)
        self.assertFalse(report["empirical_accuracy_established"])
        self.assertFalse(report["causal_effect_identified"])
        print("SEMANTIC_FORECAST_EVALUATION_JSON="+json.dumps(report,sort_keys=True),flush=True)
        self.assertEqual(report,sf.evaluate_semantic_forecasts(dataset,self.store,self.panel_plan,target5,self.plan,manifest))
        with self.assertRaisesRegex(ValueError,"all planned"):
            sf.evaluate_semantic_forecasts(dataset,self.store,self.panel_plan,target5,self.plan,manifest[:1])
        with self.assertRaisesRegex(ValueError,"frozen order"):
            sf.evaluate_semantic_forecasts(dataset,self.store,self.panel_plan,target5,self.plan,manifest[::-1])

    def test_unknown_network_feature_is_not_zero_or_fallback(self):
        dataset,panel,outcomes = self.history(incomplete=True)
        forecast = self.issue(dataset,panel,outcomes)
        self.assertEqual(forecast["models"]["own_lag_ols"]["status"],"OK")
        self.assertEqual(forecast["models"]["language_ols"]["status"],"OK")
        m = forecast["models"]["language_network_ols"]
        self.assertEqual(m["reason"],"missing_required_feature")
        self.assertIsNone(m["raw_predictions"])
        target = ingest_records(outcomes,batch(3),received_at=T4)
        score = self.score(dataset,panel,target,forecast)
        self.assertEqual(score["models"]["language_network_ols"]["n_evaluated"],0)
        self.assertIsNone(score["models"]["language_network_ols"]["clipped"])

    def test_missing_and_ambiguous_behavior_are_rejected(self):
        dataset,panel,outcomes = self.history()
        missing = ingest_records(outcomes,[{**observation("withdraw","C",7,2),
            "fact_id":"out-2-C","operation":"retract","supersedes":"out-2-C","payload":None}],
            received_at=T3)
        with self.assertRaisesRegex(ValueError,"exactly one"):
            self.issue(dataset,panel,missing)
        dup = ingest_records(outcomes,[observation("duplicate","A",7,3)],received_at=T3)
        with self.assertRaisesRegex(ValueError,"exactly one"):
            self.issue(dataset,panel,dup)

    def test_raw_target_or_later_assertion_even_if_retracted_rejected(self):
        dataset,panel,outcomes = self.history()
        early = observation("early-target","A",9,5)
        withdrawal = {**early,"record_id":"early-withdraw","operation":"retract",
            "supersedes":"early-target","payload":None}
        withdrawal["source"]={**early["source"],"record_id":"early-withdraw","revision":"2"}
        contaminated = ingest_records(outcomes,[early,withdrawal],received_at=T3)
        with self.assertRaisesRegex(ValueError,"target-or-later assertion"):
            self.issue(dataset,panel,contaminated)

    def test_future_receipt_and_already_received_target_rejected(self):
        dataset,panel,outcomes = self.history()
        later = ingest_records(outcomes,batch(3),received_at=T4)
        with self.assertRaisesRegex(ValueError,"unavailable"):
            self.issue(dataset,panel,later)
        forecast = self.issue(dataset,panel,outcomes)
        backdated = ingest_records(outcomes,batch(3),received_at=T3)
        with self.assertRaisesRegex(ValueError,"receipt timestamp must follow"):
            self.score(dataset,panel,backdated,forecast)
        with self.assertRaisesRegex(ValueError,"unavailable"):
            self.score(dataset,panel,ingest_records(outcomes,batch(3),received_at=T5),forecast)

    def test_renamed_target_fact_ancestry_rejected(self):
        dataset,panel,outcomes = self.history()
        pre = observation("old-fact","A",7,2,attribute="unrelated")
        known = ingest_records(outcomes,[pre],received_at=T3)
        forecast = self.issue(dataset,panel,known)
        revised = observation("target-revision","A",9,2)
        revised.update(fact_id="old-fact",supersedes="old-fact")
        revised["source"]["revision"]="2"
        target = ingest_records(known,[revised,*batch(3)[1:]],received_at=T4)
        with self.assertRaisesRegex(ValueError,"first received"):
            self.score(dataset,panel,target,forecast)

    def test_target_correction_preserves_selected_scoring_version(self):
        dataset,panel,outcomes = self.history()
        forecast = self.issue(dataset,panel,outcomes)
        original = ingest_records(outcomes,batch(3),received_at=T4)
        score = self.score(dataset,panel,original,forecast)
        correction = observation("corrected-target","A",9,4)
        correction.update(fact_id="out-3-A",supersedes="out-3-A")
        correction["source"]["revision"]="2"
        changed = ingest_records(original,[correction],received_at=T4)
        self.assertEqual(score,self.score(dataset,panel,changed,forecast,len(original.records)))
        self.assertNotEqual(score["target_evidence_hash"],self.score(dataset,panel,changed,forecast)["target_evidence_hash"])
        self.assertEqual(score["forecast_hash"],forecast["forecast_hash"])

    def test_forecast_scope_and_plan_binding(self):
        for kwargs in ({"action":"threat"},{"initial_history_waves":2},{"initial_history_waves":4},
                       {"outcome_source":{**SOURCE,"maximum":True}}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                self.freeze(**kwargs)
        with self.assertRaisesRegex(ValueError,"separate synthetic"):
            sf.freeze_semantic_forecast_plan(self.dataset,self.store,self.panel_plan,self.dataset,
                outcome_source=SOURCE,action="support",initial_history_waves=3)
        forged = deepcopy(self.plan)
        forged["registration_outcome_prefix_hash"]="unrelated"
        rehash(forged,"plan_hash")
        dataset,panel,outcomes=self.history()
        with self.assertRaisesRegex(ValueError,"plan does not replay"):
            sf.issue_semantic_forecast(dataset,self.store,self.panel_plan,panel,outcomes,forged,fold_id="w4")

    def test_rehashed_prediction_tampering_and_future_panel_fail(self):
        dataset,panel,outcomes=self.history()
        forecast=self.issue(dataset,panel,outcomes)
        target=ingest_records(outcomes,batch(3),received_at=T4)
        forged=deepcopy(forecast)
        forged["models"]["own_lag_ols"]["raw_predictions"][0]+=1
        rehash(forged,"forecast_hash")
        with self.assertRaisesRegex(ValueError,"saved predictions"):
            self.score(dataset,panel,target,forged)
        later=append_semantic_wave(dataset,self.store,self.panel_plan,panel,wave_id="w4",activity_links=None)
        with self.assertRaisesRegex(ValueError,"exact issued history"):
            self.score(dataset,later,target,forecast)

    def test_rank_deficient_design_is_visible(self):
        dataset,panel,outcomes=self.history()
        # Keep the same labels but select an action with no historical expressions.
        plan=sf.freeze_semantic_forecast_plan(self.dataset,self.store,self.panel_plan,self.outcomes,
            outcome_source=SOURCE,action="insult",initial_history_waves=3)
        forecast=sf.issue_semantic_forecast(dataset,self.store,self.panel_plan,panel,outcomes,plan,fold_id="w4")
        self.assertEqual(forecast["models"]["own_lag_ols"]["status"],"OK")
        self.assertEqual(forecast["models"]["language_ols"]["reason"],"rank_deficient_training_design")
        self.assertIsNone(forecast["models"]["language_ols"]["clipped_predictions"])
