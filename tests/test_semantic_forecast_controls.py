"""Synthetic positive/negative controls; no model fitting or measurement claim about people.

Build real journal/sidecar/panel features once. Generate each outcome stream
from an independently specified arithmetic law, not from extracted features.
The law is intentionally inside the frozen model family: recovery validates
mechanics, not generalization to a social process.
"""
from datetime import datetime, timedelta, timezone
import json
import unittest

from sociolab.events import EventDataset, ingest_records
from sociolab.semantic_llm import _digest
from sociolab.semantic_observations import SemanticObservationStore
from sociolab.semantic_panel import freeze_semantic_panel, start_semantic_panel, append_semantic_wave
from sociolab.semantic_forecast import (freeze_semantic_forecast_plan, issue_semantic_forecast,
    evaluate_semantic_forecasts)
from test_semantic_actions import raw, action
from test_semantic_admission import decision
from test_semantic_observations import bind_args, create_model, snapshot, content_payload
from test_semantic_multilayer import interval


ACTORS = ("A", "B", "C", "D")
# Six origin feature waves; the seventh wave is a final outcome only.
SUPPORT = (("A","C"), ("B","D"), ("A","B"), ("C","D"), ("A","D"), ("B","C"))
ATTEND = (("A","B"), ("B","C","D"), ("A","C","D"), ("B","D"), ACTORS, ())
COEFFICIENTS = {"own_only": (0,0), "language_only": (2,0),
                "network_only": (0,1), "joint": (2,1)}
SOURCE = {"system":"fictional-control-outcome","attribute":"constructed_level",
    "minimum":0,"maximum":99,"measurement_reference":"synthetic:known-control-law"}
SETTINGS = {"actors":list(ACTORS),"actions":["support"],"population":"control-team",
    "roles":[],"affiliation_projection":"count","max_pairs":20,"seed":0,
    "resolution":1.0,"max_nodes":20,"max_edges":50}
PEOPLE = {a:"人物"+a for a in ACTORS}
TOPICS = {"alpha":"甲方案"}
TEXT = "我支持甲方案。".encode("utf-8")


def utc(minutes):
    return (datetime(2026,11,28,8,tzinfo=timezone.utc)+timedelta(minutes=minutes)).isoformat().replace("+00:00","Z")


SCHEDULE = [{"wave_id":f"w{i+1}","start":4*i,"end":4*(i+1),"as_of":utc(10*(i+1))}
    for i in range(7)]


def empty(dataset_id):
    return EventDataset.from_mapping({"schema":"sociolab.events.v1","dataset_id":dataset_id,
        "origin":"synthetic","source_revision":"1","clock":{"kind":"ticks","run_id":"control-study"},
        "records":[]})


def initial_feature_journal():
    batch = [raw("person-"+a,"entity.observed",{"entity_id":a,"entity_type":"person"},0)
        for a in ACTORS]
    batch += [interval(raw("member-"+a,"membership.observed",
        {"actor":a,"population":"control-team","status":"present"},0),0,28) for a in ACTORS]
    batch.append(interval(raw("coverage","coverage.observed",
        {"population":"control-team","layer":"participation","actors":list(ACTORS),"status":"complete"},0),0,28))
    return ingest_records(empty("control-features"),batch,received_at=utc(0))


def feature_wave(dataset, store, plan, panel, i):
    slot = SCHEDULE[i]
    at, received = slot["start"]+1, slot["as_of"]
    batch, messages = [], []
    if ATTEND[i]:
        aid = f"meeting-{i}"
        batch += [raw("entity-"+aid,"entity.observed",{"entity_id":aid,"entity_type":"activity"},at),
            interval(raw("desc-"+aid,"activity.observed",
                {"activity":aid,"activity_type":"meeting","status":"held"},at),slot["start"],slot["end"])]
        batch += [raw("attend-"+aid+"-"+a,"participation.observed",
            {"actor":a,"activity":aid,"role":"participant","status":"attended"},at) for a in ATTEND[i]]
    for a in SUPPORT[i]:
        iid, cid = f"i-{i}-{a}", f"c-{i}-{a}"
        addressee = ACTORS[(ACTORS.index(a)+1)%len(ACTORS)]
        batch += [raw(iid,"interaction.observed",
            {"actor":a,"target":addressee,"action":"utterance","topic":"alpha"},at),
            raw(cid,"content.observed",content_payload(iid,TEXT),at)]
        messages.append((a,iid,cid))
    dataset = ingest_records(dataset,batch,received_at=received)
    for a,iid,cid in messages:
        args = bind_args(dataset,{cid:TEXT},PEOPLE,TOPICS,cid,[],[iid],iid)
        candidate = action(actor=f"A{ACTORS.index(a)+1}")
        candidate["evidence"] = [{"message":"M1","quote":"我支持甲方案"}]
        d = decision([candidate])
        store = snapshot(store,args,create_model(args,d),d,revision_id=iid,received_at=received)
    panel = append_semantic_wave(dataset,store,plan,panel,wave_id=slot["wave_id"],activity_links=None)
    return dataset,store,panel


def expected_features(i,a):
    return int(a in SUPPORT[i]), len(ATTEND[i])-1 if a in ATTEND[i] else 0


def outcome_batch(i,values):
    batch = []
    for a,value in zip(ACTORS,values):
        r = raw(f"out-{i}-{a}","actor.attribute.observed",
            {"actor":a,"name":SOURCE["attribute"],"value":value},SCHEDULE[i]["end"])
        r["source"]["system"] = SOURCE["system"]
        batch.append(r)
    return batch


def expected_next(values,i,language,network):
    return [v+1+language*expected_features(i,a)[0]+network*expected_features(i,a)[1]
        for a,v in zip(ACTORS,values)]


class ForecastControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial_dataset = initial_feature_journal()
        cls.initial_store = SemanticObservationStore.empty(cls.initial_dataset)
        cls.panel_plan = freeze_semantic_panel(cls.initial_dataset,cls.initial_store,
            registered_at=utc(0),schedule=SCHEDULE,settings=SETTINGS)
        dataset,store = cls.initial_dataset,cls.initial_store
        panel = start_semantic_panel(dataset,store,cls.panel_plan)
        cls.history = []
        for i in range(6):
            dataset,store,panel = feature_wave(dataset,store,cls.panel_plan,panel,i)
            cls.history.append((dataset,store,panel))

    def test_feature_reconstruction_matches_predeclared_support_and_attendance(self):
        for i,(_,_,panel) in enumerate(self.history):
            wave = panel["waves"][-1]
            self.assertEqual(wave["wave_id"],SCHEDULE[i]["wave_id"])
            for row in wave["features"]["rows"]:
                l,n = expected_features(i,row["actor_id"])
                self.assertEqual(row["expression_actions"]["support"]["person_topic"]["selected_expression_count"],l)
                self.assertEqual(row["attendance"]["coattendance_neighbors"],n)
                self.assertEqual(row["attendance"]["scope"],"COMPLETE_DECLARED_VIEW")
        self.assertEqual(self.history[-1][2]["waves"][:5],self.history[-2][2]["waves"])

    def run_control(self,name):
        language,network = COEFFICIENTS[name]
        outcomes = ingest_records(empty("control-outcomes-"+name),
            [raw("outcome-person-"+a,"entity.observed",{"entity_id":a,"entity_type":"person"},0)
             for a in ACTORS],received_at=utc(0))
        plan = freeze_semantic_forecast_plan(self.initial_dataset,self.initial_store,
            self.panel_plan,outcomes,outcome_source=SOURCE,action="support",initial_history_waves=4)
        values,manifest,forecasts = [1,2,4,5],[],[]
        for i in range(7):
            if i:
                values = expected_next(values,i-1,language,network)
            self.assertTrue(all(SOURCE["minimum"]<=v<=SOURCE["maximum"] for v in values))
            outcomes = ingest_records(outcomes,outcome_batch(i,values),received_at=SCHEDULE[i]["as_of"])
            if manifest and manifest[-1]["target_cutoff"] is None:
                manifest[-1]["target_cutoff"] = len(outcomes.records)
            if 3<=i<6:
                dataset,store,panel = self.history[i]
                forecast = issue_semantic_forecast(dataset,store,self.panel_plan,panel,outcomes,
                    plan,fold_id=SCHEDULE[i+1]["wave_id"])
                self.assertTrue(all(m["status"]=="OK" for m in forecast["models"].values()))
                self.assertEqual(forecast["models"]["language_network_ols"]["rank"],4)
                # Compare against the known generating law, not a second
                # fitted implementation of OLS or a post-selected threshold.
                for got,want in zip(forecast["models"]["language_network_ols"]["coefficients"],
                                    (1,1,language,network)):
                    self.assertAlmostEqual(got,want,places=9)
                manifest.append({"panel":panel,"forecast":forecast,"target_cutoff":None})
                forecasts.append(forecast)
        dataset,store,_ = self.history[-1]
        result = evaluate_semantic_forecasts(dataset,store,self.panel_plan,outcomes,plan,manifest)
        self.assertEqual(result["fold_count"],3)
        self.assertEqual(result["actor_forecast_count"],12)
        for m in result["models"].values():
            self.assertEqual(m["n_evaluated"],12)
        self.assertAlmostEqual(result["models"]["language_network_ols"]["metrics"]["raw"]["mae"],0,places=9)
        self.assertFalse(result["empirical_accuracy_established"])
        summary = {"schema":"sociolab.semantic-forecast-known-law-control.v1",
            "scenario":name,"known_coefficients":[1,1,language,network],
            "measurement_status":"SYNTHETIC_KNOWN_LAW_NOT_INDEPENDENT_EMPIRICAL_EVIDENCE",
            "forecast_hashes":[f["forecast_hash"] for f in forecasts],
            "coefficients":[{m:r["coefficients"] for m,r in f["models"].items()} for f in forecasts],
            "evaluation":result}
        summary["report_hash"] = _digest(summary)
        print("SEMANTIC_FORECAST_CONTROL_JSON="+json.dumps(summary,sort_keys=True),flush=True)
        return result["models"]

    def test_negative_control_own_history_alone(self):
        m = self.run_control("own_only")
        for name in ("own_lag_ols","language_ols","language_network_ols"):
            self.assertAlmostEqual(m[name]["metrics"]["raw"]["mae"],0,places=9)

    def test_positive_control_language_signal(self):
        m = self.run_control("language_only")
        self.assertGreater(m["own_lag_ols"]["metrics"]["raw"]["mae"],0.1)
        self.assertAlmostEqual(m["language_ols"]["metrics"]["raw"]["mae"],0,places=9)

    def test_positive_control_network_signal(self):
        m = self.run_control("network_only")
        self.assertGreater(m["language_ols"]["metrics"]["raw"]["mae"],0.1)

    def test_positive_control_joint_signal(self):
        m = self.run_control("joint")
        self.assertGreater(m["language_ols"]["metrics"]["raw"]["mae"],0.1)
