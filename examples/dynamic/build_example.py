"""Build invented observations demonstrating the event → snapshot pipeline.

Run from the repository with PYTHONPATH=src python examples/dynamic/build_example.py.
No empirical data or generated dialogue is used.
"""

import json
from pathlib import Path

from sociolab.events import EventDataset, ingest_records


def record(record_id, kind, payload, *, at=0, interval=None):
    return {"record_id": record_id, "fact_id": record_id, "operation": "assert",
            "supersedes": None, "kind": kind, "occurred_at": at,
            "valid_interval": interval, "source": {"system": "invented-example",
            "record_id": record_id, "revision": "example-1", "evidence_ref": "synthetic:" + record_id},
            "payload": payload}


def build():
    people = list("ABCDEF")
    records = [record("person-" + p, "entity.observed", {"entity_id": p, "entity_type": "person"}) for p in people]
    records.append(record("activity-workshop", "entity.observed", {"entity_id": "workshop", "entity_type": "activity"}))
    records += [record("join-" + p, "membership.changed", {"actor": p, "population": "team", "status": "present"}) for p in people]
    records += [record("coverage-" + layer, "coverage.observed", {
        "population": "team", "layer": layer, "actors": people, "status": "complete"}, interval=[0, 100])
        for layer in ("cooperation", "communication", "participation", "conflict")]
    for a, b in ("AB", "AC", "BC", "DE", "DF", "EF", "CD"):
        records.append(record("cooperate-" + a + b, "relation.changed", {
            "layer": "cooperation", "source": a, "target": b, "directed": False, "strength": 1}))
    records.append(record("workshop-description", "activity.observed", {
        "activity": "workshop", "status": "held", "activity_type": "workshop"}, at=4, interval=[4, 6]))
    records += [record("attendance-" + p, "participation.observed", {
        "actor": p, "activity": "workshop", "role": "participant", "status": "attended"}, at=4, interval=[4, 6]) for p in people]
    records.append(record("conflict-CD", "interaction.observed", {
        "actor": "C", "target": "D", "action": "conflict", "topic": "proposal"}, at=8))
    records.append(record("attribute-C", "actor.attribute.observed", {"actor": "C", "name": "declared_position", "value": "opposes_proposal"}, at=9))
    records.append(record("end-cooperation-CD", "relation.changed", {
        "layer": "cooperation", "source": "C", "target": "D", "directed": False, "strength": 0}, at=10))
    records.append(record("reply-FA", "interaction.observed", {
        "actor": "F", "target": "A", "action": "reply", "topic": "task"}, at=22))
    records.append(record("leave-F", "membership.changed", {"actor": "F", "population": "team", "status": "absent"}, at=25))
    records.append(record("later-message-AF", "interaction.observed", {
        "actor": "A", "target": "F", "action": "utterance", "topic": "task"}, at=26))
    empty = EventDataset.from_mapping({"schema": "sociolab.events.v1", "dataset_id": "invented-team",
        "origin": "synthetic", "source_revision": "example-1", "clock": {"kind": "ticks", "run_id": "example-run"}, "records": []})
    return ingest_records(empty, records, received_at="2026-11-27T12:00:00Z")


def main():
    target = Path(__file__).parent
    base = {"schema": "sociolab.view.v1", "population": "team", "layer": "cooperation",
            "mode": "state", "directed": False, "actions": [], "roles": [], "topics": []}
    documents = {"events.json": build().to_dict(),
        "cooperation-before.view.json": {**base, "at": 5},
        "cooperation-after.view.json": {**base, "at": 15},
        "communication.view.json": {**base, "layer": "communication", "mode": "events", "directed": True,
                                    "start": 20, "end": 30, "actions": ["reply", "utterance"]},
        "participation.view.json": {**base, "layer": "participation", "mode": "participation", "start": 4, "end": 6},
        "conflict.view.json": {**base, "layer": "conflict", "mode": "events", "directed": True,
                               "start": 0, "end": 10, "actions": ["conflict"]}}
    for name, value in documents.items():
        (target / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
