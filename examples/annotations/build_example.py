"""Invented labels exercising annotation contracts; no classifier is executed.

The example source strings below are synthetic. Journals contain only metadata,
hashes, lengths and spans, never copies of private source content.
Run: PYTHONPATH=src python examples/annotations/build_example.py
"""

from hashlib import sha256
import json
from pathlib import Path

from sociolab.annotation_schema import TAXONOMY
from sociolab.events import EventDataset, ingest_records


HUMAN = {"kind": "human", "id": "example-reviewer", "version": "1"}
MODEL = {"kind": "model", "id": "provided-demo-labels", "version": "1"}


def record(record_id, kind, payload, *, at=0, interval=None):
    return {"record_id": record_id, "fact_id": record_id, "operation": "assert", "supersedes": None,
            "kind": kind, "occurred_at": at, "valid_interval": interval,
            "source": {"system": "invented-annotation-example", "record_id": record_id,
                       "revision": "example-1", "evidence_ref": "synthetic:" + record_id}, "payload": payload}


def build():
    people = list("ABCD")
    records = [record("person-" + p, "entity.observed", {"entity_id": p, "entity_type": "person"}) for p in people]
    records += [record("join-" + p, "membership.changed", {"actor": p, "population": "team", "status": "present"}) for p in people]
    records += [record("coverage-" + layer, "coverage.observed", {
        "population": "team", "layer": layer, "actors": people, "status": "complete"}, interval=[0, 100])
        for layer in ("communication", "cooperation")]
    for a, b in ("AB", "BC", "CD"):
        records.append(record("cooperate-" + a + b, "relation.changed", {
            "layer": "cooperation", "source": a, "target": b, "directed": False, "strength": 1}))
    statements = [
        ("m1", "A", "B", 5, "proposal-P", "我反对方案 P。", "disagreement", "topic", "proposal-P"),
        ("m2", "B", "A", 6, "proposal-P", "You are an idiot.", "insult", "person", "A"),
        ("m3", "C", "B", 7, "work", "I will help you finish the task.", "cooperation_commitment", "person", "B"),
        ("m4", "D", "A", 8, "task", "The meeting starts at noon.", "neutral", "none", None),
        ("m5", "A", "D", 15, "proposal-P", "I can help mediate your disagreement.", "mediation", "person", "D"),
        ("m6", "B", "C", 16, "work", "I support your suggestion.", "support", "person", "C"),
    ]
    for message, actor, addressee, at, topic, _, _, _, _ in statements:
        records.append(record(message, "interaction.observed", {
            "actor": actor, "target": addressee, "action": "utterance", "topic": topic}, at=at))
    contents = {}
    for message, _, _, at, _, text, _, _, _ in statements:
        encoded = text.encode("utf-8")
        content = {"interaction_record_id": message, "content_ref": "synthetic-content:" + message,
                   "content_revision": "1", "content_hash": "sha256:" + sha256(encoded).hexdigest(),
                   "language": "zh" if message == "m1" else "en",
                   "length": {"unicode_codepoint": len(text), "utf8_byte": len(encoded)}}
        contents[message] = content
        records.append(record("content-" + message, "content.observed", content, at=at))

    def annotation(message, method, label, subject_kind, subject_id, topic):
        content = contents[message]
        return {"target_record_id": "content-" + message,
                "target_content_revision": content["content_revision"], "target_content_hash": content["content_hash"],
                "method": method, "taxonomy": TAXONOMY, "label": label,
                "subject": {"kind": subject_kind, "id": subject_id}, "topic": topic,
                "evidence": [] if label in {"neutral", "uncertain"} else [
                    {"unit": "unicode_codepoint", "start": 0, "end": content["length"]["unicode_codepoint"]}],
                "score": None if method["kind"] == "human" else {"kind": "uncalibrated", "value": 0.8}}

    for message, _, _, _, topic, _, label, subject_kind, subject_id in statements:
        records.append(record("human-" + message, "annotation.recorded",
                              annotation(message, HUMAN, label, subject_kind, subject_id, topic), at=50))
    # Model-format decisions are deliberately supplied fixtures, not model output.
    # m1 gets the label right but mistakes a topic for a person; m3 misses a
    # commitment; m4 abstains; m6 has no candidate label.
    candidates = [("m1", "disagreement", "person", "B", "proposal-P"),
                  ("m2", "insult", "person", "A", "proposal-P"),
                  ("m3", "neutral", "none", None, "work"),
                  ("m4", "uncertain", "none", None, "task"),
                  ("m5", "mediation", "person", "D", "proposal-P")]
    for message, label, subject_kind, subject_id, topic in candidates:
        records.append(record("model-" + message, "annotation.recorded",
                              annotation(message, MODEL, label, subject_kind, subject_id, topic), at=51))
    empty = EventDataset.from_mapping({"schema": "sociolab.events.v1", "dataset_id": "invented-annotations",
        "origin": "synthetic", "source_revision": "example-1", "clock": {"kind": "ticks", "run_id": "annotation-example"}, "records": []})
    return ingest_records(empty, records, received_at="2026-11-27T14:00:00Z")


def main():
    target = Path(__file__).parent
    base = {"schema": "sociolab.view.v1", "population": "team", "layer": "annotated_conflict", "mode": "annotations",
            "directed": True, "start": 0, "end": 10, "actions": ["reply", "utterance"], "roles": [], "topics": [],
            "source_layer": "communication", "method": HUMAN, "taxonomy": TAXONOMY, "labels": ["insult", "threat"]}
    documents = {"events.json": build().to_dict(), "human.method.json": HUMAN, "model.method.json": MODEL,
        "conflict-before.view.json": base,
        "conflict-after.view.json": {**base, "start": 10, "end": 20},
        "disagreement.view.json": {**base, "layer": "annotated_disagreement", "labels": ["disagreement"]},
        "model-disagreement.view.json": {**base, "layer": "annotated_disagreement", "labels": ["disagreement"], "method": MODEL}}
    for name, value in documents.items():
        (target / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
