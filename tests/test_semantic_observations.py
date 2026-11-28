"""Synthetic expression sidecar: exact review replay and temporal graph semantics."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sociolab.events import EventDataset, ingest_records
from sociolab.language_context import bind_language_context
from sociolab import semantic_observations as so
from sociolab import semantic_admission as ad
from sociolab import semantic_actions as sa
from sociolab.semantic_llm import _digest
from test_semantic_actions import action, raw
from test_semantic_admission import audit_args, report, reviews, decision, ARCHIVE


AUTHORITY = {"id": "fixture-review-operator", "source_ref": "fictional:research-only"}
T1 = "2026-11-28T08:10:00Z"
T2 = "2026-11-28T08:20:00Z"
T3 = "2026-11-28T08:30:00Z"


def bind_args(dataset, data, people, topics, target_id, preceding_ids, member_ids, case_id):
    context = bind_language_context(dataset, knowledge_cutoff=len(dataset.records),
        target_record_id=target_id, preceding_record_ids=preceding_ids, original_bytes=data,
        conversation={"id": case_id, "revision": "1", "source_ref": "fictional",
            "interaction_record_ids": member_ids})
    frozen = sa.freeze_actions_input(context, people, topics)
    request, *binding = sa._request(context, data, people, topics,
        model_key="qwen3-8b", reasoning_mode="off")
    return dataset, context, frozen, data, people, topics, request, binding, ad.freeze_review_input(context, people, topics)


def create_model(args, candidate):
    _, context, frozen, _, _, _, request, binding, _ = args
    return report(context, frozen, request, binding, candidate)


def snapshot(store, args, model, reference, *, revision_id, supersedes=None, received_at=T1, selected=None):
    dataset, context, frozen, data, people, topics, _, _, ri = args
    cutoff = context["knowledge_cutoff"]
    refs = reviews(ri, cutoff, reference)
    audit = ad.assess_semantic_admission(dataset, context, frozen, model,
        original_bytes=data, people=people, topics=topics, model_key="qwen3-8b",
        reasoning_mode="off", admission_cutoff=cutoff, reviews=refs)
    # The test explicitly selects the reviewed hashes; the store has no default admission.
    selection = audit["reviewed_direct_expression_candidate_hashes"] if selected is None else selected
    return so.append_reviewed_snapshot(store, dataset, context, frozen, model,
        original_bytes=data, people=people, topics=topics, model_key="qwen3-8b",
        reasoning_mode="off", admission_cutoff=cutoff, reviews=refs,
        selected_action_hashes=selection, revision_id=revision_id, supersedes=supersedes,
        received_at=received_at, authority=AUTHORITY)


def project(dataset, store, *, journal_cutoff=None, observation_cutoff=None, start=0, end=10):
    return so.project_reviewed_expressions(dataset, store,
        journal_cutoff=len(dataset.records) if journal_cutoff is None else journal_cutoff,
        observation_cutoff=len(store.records) if observation_cutoff is None else observation_cutoff,
        start=start, end=end)


def content_payload(iid, data, revision="1"):
    return {"interaction_record_id": iid, "content_ref": "private:"+iid,
        "content_revision": revision, "content_hash": "sha256:"+sha256(data).hexdigest(),
        "language": "zh", "length": {"unicode_codepoint": len(data.decode()), "utf8_byte": len(data)}}


class ExpressionStoreTests(unittest.TestCase):
    def setUp(self):
        self.args = audit_args()
        self.dataset = self.args[0]
        self.empty = so.SemanticObservationStore.empty(self.dataset)
        self.own = action()
        self.other = action("A3", "disagreement", "T2", "T2", "REPORTED", "小陈反对乙方案")
        self.candidate = decision([self.own, self.other])
        self.model = create_model(self.args, self.candidate)
        self.store = snapshot(self.empty, self.args, self.model, self.candidate, revision_id="r1")

    def test_immutable_roundtrip_and_explicit_selection(self):
        self.assertEqual(len(self.empty.records), 0)
        self.assertEqual(len(self.store.records), 1)
        self.assertEqual(len(self.store.records[0]["payload"]["selected_action_hashes"]), 1)
        self.assertEqual(self.store.records[0]["previous_hash"], None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "expressions.json"
            path.write_text(json.dumps(self.store.to_dict(), ensure_ascii=False), encoding="utf-8")
            restored = so.load_semantic_observations(path)
            self.assertEqual(restored.content_hash, self.store.content_hash)
            self.assertEqual(project(self.dataset, restored), project(self.dataset, self.store))
        copy = self.store.to_dict()
        copy["records"].clear()
        self.assertEqual(len(self.store.records), 1)
        self.assertNotIn("我支持", str(self.store.to_dict()))

    def test_actual_networkx_person_topic_and_no_reported_edge(self):
        result = project(self.dataset, self.store)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["actor_id"], "B")
        self.assertEqual(result["events"][0]["occurred_at"], 2)
        self.assertEqual(result["events"][0]["available_at"], T1)
        self.assertEqual(result["edges"][0]["layer"], "PERSON_TOPIC")
        self.assertEqual(result["edges"][0]["target"], {"kind": "topic", "id": "alpha"})
        g = so.expression_graph(result, layer="PERSON_TOPIC", action="support")
        self.assertEqual(list(g.edges()), [(("person", "B"), ("topic", "alpha"))])
        self.assertEqual(g[("person","B")][("topic","alpha")]["weight"], 1)
        self.assertEqual(so.expression_graph(result, layer="PERSON_TOPIC", action="disagreement").number_of_edges(), 0)
        self.assertFalse(result["network_mutated"])

    def test_two_knowledge_prefixes_and_half_open_source_window(self):
        self.assertEqual(project(self.dataset, self.store, observation_cutoff=0)["events"], [])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            project(self.dataset, self.store, journal_cutoff=6)
        self.assertEqual(project(self.dataset, self.store, start=0, end=2)["events"], [])
        self.assertEqual(len(project(self.dataset, self.store, start=2, end=3)["events"]), 1)
        with self.assertRaises(ValueError):
            project(self.dataset, self.store, start=2, end=2)

    def test_only_selected_reviewed_direct_candidates_can_be_stored(self):
        for selection in ([], ["unknown"], [_digest(self.model["candidate"]["actions"][1])],
                self.store.records[0]["payload"]["selected_action_hashes"]*2):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                snapshot(self.empty, self.args, self.model, self.candidate,
                    revision_id="bad", selected=selection)

    def test_reference_disagreement_prevents_snapshot(self):
        with self.assertRaises(ValueError):
            snapshot(self.empty, self.args, self.model, decision([self.other]),
                revision_id="bad")

    def test_explicit_withdrawal_and_revision_chain(self):
        key = self.store.records[0]["key"]
        withdrawn = so.withdraw_reviewed_snapshot(self.store, self.dataset,
            key=key, revision_id="r2", supersedes="r1", journal_cutoff=7,
            received_at=T2, authority=AUTHORITY)
        self.assertEqual(project(self.dataset, withdrawn)["events"], [])
        self.assertEqual(project(self.dataset, withdrawn)["withdrawn_revisions"], ["r2"])
        self.assertEqual(project(self.dataset, withdrawn, observation_cutoff=1),
                         project(self.dataset, self.store))
        with self.assertRaisesRegex(ValueError, "supersede current head"):
            snapshot(withdrawn, self.args, self.model, self.candidate,
                revision_id="branch", supersedes="r1", received_at=T3)
        reasserted = snapshot(withdrawn, self.args, self.model, self.candidate,
            revision_id="r3", supersedes="r2", received_at=T3)
        self.assertEqual(len(project(self.dataset, reasserted)["events"]), 1)

    def test_source_revision_withholds_stale_until_new_review(self):
        text = "我反对甲方案。".encode()
        replacement = raw("c2-new", "content.observed", content_payload("i2", text, "2"), 2)
        replacement.update(fact_id="c2", supersedes="c2")
        updated = ingest_records(self.dataset, [replacement], received_at="2026-11-28T08:15:00Z")
        previous = project(updated, self.store, journal_cutoff=7)
        self.assertEqual(previous, project(self.dataset, self.store))
        withheld = project(updated, self.store)
        self.assertEqual(withheld["events"], [])
        self.assertEqual(withheld["withheld_revisions"][0]["revision_id"], "r1")
        args = bind_args(updated, {"c1": self.args[3]["c1"], "c2-new": text},
            self.args[4], self.args[5], "c2-new", ["c1"], ["i1","i2"], "corrected")
        candidate = decision([action(label="disagreement", quote="我反对甲方案")])
        revised = snapshot(self.store, args, create_model(args, candidate), candidate,
            revision_id="r2", supersedes="r1", received_at=T2)
        result = project(updated, revised)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["target_content_record_id"], "c2-new")
        self.assertEqual(result["events"][0]["action"], "disagreement")
        self.assertEqual(result["events"][0]["revision_id"], "r2")
        self.assertEqual(project(updated, revised, journal_cutoff=7, observation_cutoff=1), previous)

    def test_new_interaction_evolves_both_network_layers(self):
        text = "我支持甲方案，你真是个废物。".encode()
        added = [raw("i3", "interaction.observed", {"actor":"B","target":"A",
            "action":"utterance","topic":"meeting"}, 3),
            raw("c3", "content.observed", content_payload("i3", text), 3)]
        updated = ingest_records(self.dataset, added, received_at="2026-11-28T08:15:00Z")
        args = bind_args(updated, {"c2": self.args[3]["c2"], "c3": text},
            self.args[4], self.args[5], "c3", ["c2"], ["i2","i3"], "second")
        candidate = decision([action(), action(label="insult", subject="A1", topic="NONE", quote="你真是个废物")])
        evolved = snapshot(self.store, args, create_model(args, candidate), candidate,
            revision_id="r2", received_at=T2)
        result = project(updated, evolved)
        self.assertEqual(len(result["events"]), 3)
        self.assertEqual([e["occurred_at"] for e in result["events"]], [2,3,3])
        topic = so.expression_graph(result, layer="PERSON_TOPIC", action="support")
        person = so.expression_graph(result, layer="PERSON_PERSON", action="insult")
        self.assertEqual(topic[("person","B")][("topic","alpha")]["weight"], 2)
        self.assertEqual(person[("person","B")][("person","A")]["weight"], 1)
        self.assertEqual(len(project(updated, evolved, start=3, end=4)["events"]), 2)
        self.assertEqual(project(updated, evolved, journal_cutoff=7, observation_cutoff=1),
                         project(self.dataset, self.store))

    def test_receipt_times_and_forked_prefix_fail(self):
        with self.assertRaisesRegex(ValueError, "predates"):
            snapshot(self.empty, self.args, self.model, self.candidate,
                revision_id="early", received_at="2026-11-28T07:59:00Z")
        changed = self.dataset.to_dict()
        changed["records"][0]["source"]["revision"] = "different"
        fork = EventDataset.from_mapping(changed)
        with self.assertRaisesRegex(ValueError, "another journal"):
            project(fork, self.store)

    def test_tampered_store_and_external_origin_rejected(self):
        changed = self.store.to_dict()
        changed["records"][0]["revision_id"] = "changed"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            so.SemanticObservationStore.from_mapping(changed)
        changed = self.dataset.to_dict()
        changed["origin"] = "external_observation"
        with self.assertRaisesRegex(ValueError, "synthetic"):
            so.SemanticObservationStore.empty(EventDataset.from_mapping(changed))

    def test_rehashed_wrong_interaction_key_is_rejected(self):
        value = self.store.to_dict()
        rec = value["records"][0]
        rec["key"]["interaction_fact_id"] = "unrelated"
        rec["record_hash"] = _digest({k:v for k,v in rec.items() if k!="record_hash"})
        value["store_hash"] = _digest({k:v for k,v in value.items() if k!="store_hash"})
        loaded = so.SemanticObservationStore.from_mapping(value)
        with self.assertRaisesRegex(ValueError, "fact key"):
            project(self.dataset, loaded)


class ActualModelSidecarReplayTests(unittest.TestCase):
    def test_real_reported_and_own_review_projects_only_own_expression(self):
        archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))
        model = next(r["result"] for r in archive["rows"] if r["case_id"] == "reported-and-own")
        args = audit_args(target="小陈反对乙方案，我支持甲方案。", case_id="reported-and-own")
        reference = decision([action(), action("A3","disagreement","T2","T2","REPORTED","小陈反对乙方案")])
        store = snapshot(so.SemanticObservationStore.empty(args[0]), args, model, reference,
            revision_id="real-model-replay")
        result = project(args[0], store)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["actor_id"], "B")
        self.assertEqual(result["events"][0]["action"], "support")
        self.assertEqual(result["qualification_status"], "NOT_ESTABLISHED")
