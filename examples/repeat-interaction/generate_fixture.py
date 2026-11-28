"""Write a fresh, wholly invented repeat-interaction example directory."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sociolab.events import EventDataset, ingest_records

ACTORS = ["A", "B", "C", "D"]
SYSTEM = "invented-repeat-interaction"


def record(identifier, kind, payload, at=0, interval=None, *, fact=None, supersedes=None, retract=False):
    return {"record_id": identifier, "fact_id": fact or identifier,
            "operation": "retract" if retract else "assert", "supersedes": supersedes,
            "kind": kind, "occurred_at": at, "valid_interval": interval,
            "source": {"system": SYSTEM, "record_id": identifier, "revision": identifier,
                       "evidence_ref": "synthetic:" + identifier}, "payload": payload}


def coverage(identifier, actors, interval, layer="communication"):
    return record(identifier, "coverage.observed", {
        "population": "team", "layer": layer, "actors": actors, "status": "complete",
    }, at=interval[0], interval=interval)


def reply(identifier, source, target, at):
    return record(identifier, "interaction.observed", {
        "actor": source, "target": target, "action": "reply", "topic": "task",
    }, at=at)


def ingest(dataset, rows, minute):
    return ingest_records(dataset, rows, received_at=f"2026-11-28T00:{minute:02d}:00Z")


def target(dataset, observed_through=30):
    return {"schema": "sociolab.repeat-interaction-target.v1",
            "knowledge_cutoff": len(dataset.records), "observed_through": observed_through,
            "observation_reference": "Invented follow-up declarations; not authenticated coverage."}


def build_fixture():
    empty = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "invented-repeat-interaction-example",
        "origin": "synthetic", "source_revision": "invented-repeat-source-v1",
        "clock": {"kind": "ticks", "run_id": "repeat-interaction-example"}, "records": [],
    })
    rows = [record("person-" + a, "entity.observed", {"entity_id": a, "entity_type": "person"}) for a in ACTORS]
    rows += [record("member-" + a, "membership.changed", {"actor": a, "population": "team", "status": "present"}) for a in ACTORS]
    rows += [coverage("history-coverage", ACTORS, [0, 20]),
             coverage("cooperation-coverage", ACTORS, [0, None], "cooperation"),
             record("cooperation-active", "relation.changed", {"layer": "cooperation", "source": "A", "target": "B", "directed": False, "strength": 1}),
             reply("history-AB-0", "A", "B", 0), reply("history-AB-12", "A", "B", 12),
             reply("history-AB-19", "A", "B", 19), reply("history-AC-5", "A", "C", 5),
             reply("history-BD-10", "B", "D", 10), reply("history-BD-15", "B", "D", 15)]
    history = ingest(empty, rows, 1)
    specification = {
        "schema": "sociolab.repeat-interaction-spec.v1", "knowledge_cutoff": len(history.records),
        "source_reference": None, "observation_reference": "Invented complete communication history for an engineering case.",
        "actors": ACTORS, "population": "team", "layer": "communication", "actions": ["reply"], "topics": [],
        "history_start": 0, "recent_start": 15, "origin_at": 20, "target_end": 30,
        "risk_set": "history_positive_ordered_pairs",
    }
    complete = ingest(history, [coverage("complete-future-coverage", ACTORS, [20, 40]),
        reply("complete-AB-20", "A", "B", 20), reply("complete-BD-29", "B", "D", 29),
        reply("complete-AB-30", "A", "B", 30)], 2)
    partial = ingest(history, [coverage("partial-AB-coverage", ["A", "B"], [20, 30]),
        coverage("partial-CD-coverage", ["C", "D"], [20, 25]),
        record("D-left", "membership.changed", {"actor": "D", "population": "team", "status": "absent"}, at=25),
        reply("partial-AB-20", "A", "B", 20), reply("partial-AC-24", "A", "C", 24),
        reply("partial-BD-22", "B", "D", 22)], 2)
    restored = ingest(partial, [coverage("restored-C-coverage", ["C"], [25, 30])], 3)
    retracted = ingest(restored, [record("retracted-AC-24", "interaction.observed", None, at=24,
        fact="partial-AC-24", supersedes="partial-AC-24", retract=True)], 4)
    terminated = ingest(complete, [record("cooperation-ended", "relation.changed", {
        "layer": "cooperation", "source": "A", "target": "B", "directed": False, "strength": 0,
    }, at=35)], 3)
    common = {"schema": "sociolab.view.v1", "population": "team", "layer": "communication",
              "mode": "events", "directed": True, "actions": ["reply"], "roles": [], "topics": []}
    files = {"history.events.json": history.to_dict(), "specification.json": specification,
             "incomplete.target.json": target(partial, 23),
             "target-window.view.json": {**common, "start": 20, "end": 30},
             "empty-window.view.json": {**common, "start": 31, "end": 40},
             "cooperation-state.view.json": {**common, "layer": "cooperation", "mode": "state", "directed": False, "actions": [], "at": 40},
             "terminated.events.json": terminated.to_dict()}
    for name, dataset in (("complete", complete), ("partial", partial), ("restored", restored), ("retracted", retracted)):
        files[name + ".events.json"] = dataset.to_dict()
        files[name + ".target.json"] = target(dataset)
    assert [len(x.records) for x in (history, complete, partial, restored, retracted, terminated)] == [17, 21, 23, 24, 25, 22]
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="fresh output directory; no existing artifacts are overwritten")
    args = parser.parse_args()
    files = build_fixture()
    args.output.mkdir(mode=0o700)
    hashes = {}
    for name, value in files.items():
        raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        with (args.output / name).open("xb") as stream:
            stream.write(raw)
        hashes[name] = sha256(raw).hexdigest()
    metadata = {"schema": "sociolab.repeat-interaction-fixture.v1", "origin": "synthetic",
                "history_knowledge_cutoff": 17, "complete_knowledge_cutoff": 21,
                "partial_knowledge_cutoff": 23, "restored_knowledge_cutoff": 24,
                "retracted_knowledge_cutoff": 25, "terminated_knowledge_cutoff": 22,
                "history_width": 20, "recent_width": 5, "horizon": 10,
                "risk_pair_count": 3, "input_file_sha256": hashes,
                "all_source_values_invented": True, "all_targets_authored_before_execution": True,
                "real_source_qualified": False, "predictive_effectiveness_validated": False}
    with (args.output / "metadata.json").open("x") as stream:
        json.dump(metadata, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "generated_file_count": len(files) + 1, "history_knowledge_cutoff": 17, "origin": "synthetic"}, sort_keys=True))


if __name__ == "__main__":
    main()
