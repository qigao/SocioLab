#!/usr/bin/env python3
"""Independently check the fixed invented tracking case using only the stdlib.

This is a fixture-specific source-state and storage checker, not a general
snapshot implementation. It does not import SocioLab or graph libraries, run
the tracker, fit models, or independently validate community algorithms.
Individual records and reconstructed edges stay in memory; output is aggregate.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import platform


REPOSITORY = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
FIXTURE = REPOSITORY / "examples" / "network-tracking"
VIEW_IDS = ("cooperation_5", "cooperation_15", "communication")
FLAGS = ("observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed")
ANALYSIS = {
    "algorithm": "greedy", "seed": 0, "resolution": 1.0,
    "group_size": None, "group_members": None, "projection": "none",
    "max_nodes": 200, "max_edges": 2000, "max_pairs": 100000,
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return "sha256:" + sha256(canonical(value)).hexdigest()


def file_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


class Audit:
    def __init__(self, private):
        self.private = private
        self.checks = 0
        self.numeric_checks = 0
        self.max_error = 0.0
        self.inputs = {}

    def check(self, condition, label):
        self.checks += 1
        if not condition:
            raise ValueError("independent tracking check failed: " + label)

    def equal(self, actual, expected, label):
        self.check(canonical(actual) == canonical(expected), label)

    def number(self, actual, expected, label):
        self.check(type(actual) in (int, float) and math.isfinite(actual), label + " type")
        self.numeric_checks += 1
        self.max_error = max(self.max_error, abs(actual - expected))
        self.check(actual == expected, label)

    def label(self, path):
        path = path.resolve()
        if path.is_relative_to(self.private):
            return "private/" + path.relative_to(self.private).as_posix()
        self.check(path.is_relative_to(REPOSITORY), "input path stays within declared roots")
        return "repository/" + path.relative_to(REPOSITORY).as_posix()

    def read(self, path, *, lines=False):
        data = path.read_bytes()
        self.inputs[self.label(path)] = sha256(data).hexdigest()
        text = data.decode("utf-8")
        if lines:
            return [json.loads(line, object_pairs_hook=unique) for line in text.splitlines()]
        return json.loads(text, object_pairs_hook=unique)

    def hashed(self, value, label):
        self.check(type(value) is dict and "content_hash" in value, label + " shape")
        self.equal(value["content_hash"], digest({k: v for k, v in value.items() if k != "content_hash"}),
                   label + " canonical hash")


def effective_records(audit, records):
    """Resolve raw fact chains, including a retraction that removes its head."""
    heads, ids = {}, set()
    previous_receipt = None
    for sequence, record in enumerate(records, 1):
        audit.number(record["ingest_seq"], sequence, "contiguous receipt")
        audit.check(record["record_id"] not in ids, "unique accepted record")
        receipt = datetime.fromisoformat(record["recorded_at"].replace("Z", "+00:00"))
        audit.check(receipt.utcoffset() is not None, "receipt timezone")
        audit.check(previous_receipt is None or receipt >= previous_receipt, "receipt ordering")
        previous_receipt = receipt
        key = (record["source"]["system"], record["fact_id"])
        predecessor = heads.get(key)
        audit.equal(record["supersedes"], None if predecessor is None else predecessor["record_id"],
                    "fact revision follows exact current head")
        if predecessor is not None:
            audit.equal(record["kind"], predecessor["kind"], "fact revision preserves kind")
        audit.check(record["operation"] in ("assert", "retract"), "known source operation")
        if record["operation"] == "retract":
            audit.check(predecessor is not None and record["payload"] is None, "retraction shape")
        ids.add(record["record_id"])
        heads[key] = record
    return [record for record in heads.values() if record["operation"] == "assert"]


def reconstruct(audit, journal, view):
    """Replay only this fixture's memberships, interval coverage and two views.

    The fixture has no alias, activity, annotation, absent-member or interval
    relation records. Reject expansion into those cases rather than pretending
    this small checker implements the general production materializer.
    """
    records = journal["records"]
    active = effective_records(audit, records)
    kinds = {"entity.observed", "membership.changed", "coverage.observed",
             "relation.changed", "interaction.observed", "actor.attribute.observed"}
    audit.check(all(record["kind"] in kinds for record in active), "fixed fixture kinds")
    persons = sorted(record["payload"]["entity_id"] for record in active if record["kind"] == "entity.observed")
    audit.check(not persons or persons == ["A", "B", "C", "D"], "fixed invented roster")
    for record in active:
        if record["kind"] == "entity.observed":
            audit.equal(record["payload"]["entity_type"], "person", "fixture entity type")
    membership = [record for record in active if record["kind"] == "membership.changed"]
    audit.equal(sorted(record["payload"]["actor"] for record in membership), persons,
                "one source membership per fixture person")
    for record in membership:
        audit.equal(record["payload"]["population"], view["population"], "membership population")
        audit.equal(record["payload"]["status"], "present", "fixture membership status")
        audit.number(record["occurred_at"], 0, "fixture membership origin")
    selected = {record["record_id"] for record in membership}
    coverage_records = [record for record in active if record["kind"] == "coverage.observed"
                        and record["payload"]["population"] == view["population"]
                        and record["payload"]["layer"] == view["layer"]]
    audit.check(len(coverage_records) == (1 if persons else 0), "unique effective layer coverage")
    coverage_ids, actor_coverage = [], {}
    for record in coverage_records:
        audit.equal(record["valid_interval"], [0, 20], "fixture coverage interval")
        audit.equal(sorted(record["payload"]["actors"]), persons, "coverage roster")
        audit.check(record["payload"]["status"] in ("complete", "partial"), "fixture coverage status")
        coverage_ids.append(record["record_id"])
        actor_coverage = {person: record["payload"]["status"] for person in persons}
    selected.update(coverage_ids)
    edge_records = {}
    if view["mode"] == "state":
        audit.check(view["at"] in (5, 15) and not view["directed"], "fixed state query")
        for record in active:
            if record["kind"] != "relation.changed" or record["payload"]["layer"] != view["layer"]:
                continue
            audit.check(not record["payload"]["directed"] and record["valid_interval"] is None,
                        "fixture relation form")
            if record["occurred_at"] <= view["at"]:
                pair = tuple(sorted((record["payload"]["source"], record["payload"]["target"])))
                edge_records.setdefault(pair, []).append(record)
        edges = []
        for pair, candidates in sorted(edge_records.items()):
            latest = max(record["occurred_at"] for record in candidates)
            effective = [record for record in candidates if record["occurred_at"] == latest]
            strength = effective[0]["payload"]["strength"]
            audit.check(all(record["payload"]["strength"] == strength for record in effective),
                        "unique source relation value")
            evidence = sorted(record["record_id"] for record in effective)
            selected.update(evidence)
            if strength > 0:
                edges.append({"source": pair[0], "target": pair[1], "strength": strength, "evidence": evidence})
    else:
        audit.equal({key: view[key] for key in ("mode", "directed", "start", "end", "actions", "topics")},
                    {"mode": "events", "directed": True, "start": 0, "end": 20,
                     "actions": ["reply", "utterance"], "topics": []}, "fixed communication query")
        for record in active:
            if (record["kind"] == "interaction.observed" and 0 <= record["occurred_at"] < 20
                    and record["payload"]["action"] in view["actions"]):
                pair = (record["payload"]["actor"], record["payload"]["target"])
                edge_records.setdefault(pair, []).append(record)
                selected.add(record["record_id"])
        edges = [{"source": pair[0], "target": pair[1], "strength": len(items),
                  "evidence": sorted(record["record_id"] for record in items)}
                 for pair, items in sorted(edge_records.items())]
    audit.check(all(edge["source"] in persons and edge["target"] in persons
                    and edge["source"] != edge["target"] for edge in edges), "fixture endpoint eligibility")
    state_mode = view["mode"] == "state"
    return {
        "directed": view["directed"], "bipartite": False, "persons": persons, "activities": [], "edges": edges,
        "weight_semantics": "observed_strength" if state_mode else "event_count",
        "population": {"policy": "eligible_at" if state_mode else "eligible_any_overlap", "eligible": persons,
                       "absent": [], "unknown": [], "unknown_intervals": {},
                       "exposure": {person: 1 if state_mode else 20 for person in persons},
                       "exposure_unit": "point" if state_mode else "tick"},
        "coverage": {"complete": bool(coverage_ids) and all(x == "complete" for x in actor_coverage.values()),
                     "actors": actor_coverage, "evidence": sorted(coverage_ids)},
        "provenance": {"selected_records": sorted(selected), "record_history": [
            {"record_id": record["record_id"], "fact_id": record["fact_id"],
             "source_system": record["source"]["system"], "operation": record["operation"],
             "supersedes": record["supersedes"], "kind": record["kind"], "ingest_seq": record["ingest_seq"]}
            for record in records]},
    }


def fingerprints(expected):
    graph = {key: expected[key] for key in ("directed", "bipartite", "persons", "activities", "weight_semantics")}
    graph["edges"] = [{"source": edge["source"], "target": edge["target"],
                       "strength": int(edge["strength"]) if float(edge["strength"]).is_integer() else edge["strength"]}
                      for edge in expected["edges"]]
    evidence = {"selected_records": expected["provenance"]["selected_records"],
                "coverage_evidence": expected["coverage"]["evidence"],
                "edge_evidence": [{key: edge[key] for key in ("source", "target", "evidence")}
                                  for edge in expected["edges"]], "annotation_summary": None}
    return {"graph": digest(graph), "population": digest(expected["population"]),
            "coverage": digest({key: expected["coverage"][key] for key in ("complete", "actors")}),
            "evidence": digest(evidence)}


def expected_comparison(before, after, flags):
    if not any(flags[key] for key in FLAGS[:3]):
        return "NOT_RUN", "no_observable_change"
    if not before["coverage"]["complete"] or not after["coverage"]["complete"]:
        return "NOT_RUN", "incomplete_before_or_after_coverage"
    return "OK", None


def relation_counts(before, after):
    old = {(edge["source"], edge["target"]): edge for edge in before["edges"]}
    new = {(edge["source"], edge["target"]): edge for edge in after["edges"]}
    shared = old.keys() & new.keys()
    reweighted = sum(old[key]["strength"] != new[key]["strength"] for key in shared)
    evidence = sum(old[key]["strength"] == new[key]["strength"] and old[key]["evidence"] != new[key]["evidence"]
                   for key in shared)
    return {"added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
            "reweighted": reweighted, "evidence_changed": evidence,
            "unchanged_edge_count": len(shared) - reweighted - evidence}


def check_transition(audit, checkpoint, previous, expected, prior_expected):
    transition, state, before = checkpoint["transition"], checkpoint["state"], previous["state"]
    audit.hashed(transition, "transition")
    audit.equal(transition["schema"], "sociolab.network-tracking-transition.v1", "transition schema")
    audit.equal(transition["kind"], "NETWORK_TRACKING_TRANSITION", "transition kind")
    audit.equal(transition["profile"], "receipt-fixed-view-tracking-v1", "transition profile")
    audit.equal(transition["status"], "APPLIED", "committed transition status")
    for key, wanted in (("before_state_hash", before["content_hash"]), ("after_state_hash", state["content_hash"]),
                        ("before_sequence", before["sequence"]), ("after_sequence", state["sequence"]),
                        ("before_knowledge_cutoff", before["knowledge_cutoff"]),
                        ("after_knowledge_cutoff", state["knowledge_cutoff"]),
                        ("registration_hash", state["registration_hash"])):
        audit.equal(transition[key], wanted, "transition state binding " + key)
    tail = state["dataset"]["records"][before["knowledge_cutoff"]:]
    audit.check(bool(tail), "committed batch contains new receipts")
    audit.check(all(record["recorded_at"] == tail[0]["recorded_at"] for record in tail), "single batch receipt instant")
    source = {"appended_record_count": len(tail),
              "new_assertion_count": sum(r["operation"] == "assert" and r["supersedes"] is None for r in tail),
              "revised_assertion_count": sum(r["operation"] == "assert" and r["supersedes"] is not None for r in tail),
              "retraction_count": sum(r["operation"] == "retract" for r in tail),
              "first_ingest_seq": tail[0]["ingest_seq"], "last_ingest_seq": tail[-1]["ingest_seq"],
              "recorded_at": tail[0]["recorded_at"], "appended_records_hash": digest(tail),
              "record_ids": [r["record_id"] for r in tail]}
    audit.equal(transition["source"], source, "transition source counters and receipt hash")
    summaries = []
    audit.equal([row["view_id"] for row in transition["views"]], list(VIEW_IDS), "transition view order")
    for index, row in enumerate(transition["views"]):
        old, new = prior_expected[index], expected[index]
        old_fingerprints, new_fingerprints = fingerprints(old), fingerprints(new)
        flags = dict(zip(FLAGS, [old_fingerprints[k] != new_fingerprints[k] for k in ("graph", "population", "coverage", "evidence")]))
        audit.equal({key: row[key] for key in FLAGS}, flags, "independent semantic change flags")
        audit.equal(row["before_fingerprints"], old_fingerprints, "old semantic fingerprints")
        audit.equal(row["after_fingerprints"], new_fingerprints, "new semantic fingerprints")
        for label, container in (("before", before), ("after", state)):
            snapshot = container["views"][index]["snapshot"]
            audit.equal(row[label + "_snapshot_hash"], snapshot["content_hash"], "transition snapshot binding")
            audit.equal(row[label + "_complete"], snapshot["coverage"]["complete"], "transition coverage binding")
        status, reason = expected_comparison(old, new, flags)
        audit.equal(row["comparison"]["status"], status, "comparison eligibility")
        if status == "NOT_RUN":
            audit.equal(row["comparison"], {"status": status, "reason": reason}, "explicit comparison skip")
        else:
            report = row["comparison"]["report"]
            audit.equal(report["kind"], "DESCRIPTIVE_NETWORK_CHANGE", "comparison report kind")
            for label, container in (("before", before), ("after", state)):
                snapshot = container["views"][index]["snapshot"]
                audit.equal(report["inputs"][label]["snapshot_hash"], snapshot["content_hash"], "upstream report input binding")
            for key, count in relation_counts(old, new).items():
                measured = report["relations"][key]
                audit.number(measured if key == "unchanged_edge_count" else len(measured), count, "relation difference count")
            audit.number(report["relations"]["before_edge_count"], len(old["edges"]), "comparison before edge count")
            audit.number(report["relations"]["after_edge_count"], len(new["edges"]), "comparison after edge count")
            audit.equal(report["causal_effect_identified"], False, "comparison causal scope")
            audit.equal(report["future_prediction"], False, "comparison predictive scope")
        summaries.append({"view_id": row["view_id"], **flags, "comparison_status": status,
                          "comparison_reason": reason, "complete": new["coverage"]["complete"],
                          "person_count": len(new["persons"]), "edge_count": len(new["edges"])})
    audit.equal(transition["scope"]["causal_effect_identified"], False, "transition causal scope")
    return summaries


def check_receipt(audit, receipt, checkpoint, status):
    state, transition = checkpoint["state"], checkpoint["transition"]
    updates = {} if status != "APPLIED" else {row["view_id"]: row for row in transition["views"]}
    views = []
    for row in state["views"]:
        snap, update = row["snapshot"], updates.get(row["view_id"])
        comparison = None if update is None else update["comparison"]
        views.append({"view_id": row["view_id"], "snapshot_hash": snap["content_hash"],
                      "person_count": len(snap["persons"]), "activity_count": len(snap["activities"]),
                      "edge_count": len(snap["edges"]), "complete": snap["coverage"]["complete"],
                      "changes": None if update is None else {key: update[key] for key in FLAGS},
                      "comparison_status": None if comparison is None else comparison["status"],
                      "comparison_reason": None if comparison is None else comparison.get("reason")})
    wanted = {"kind": "NETWORK_TRACKING_RECEIPT", "status": status, "sequence": state["sequence"],
              "knowledge_cutoff": state["knowledge_cutoff"], "state_hash": state["content_hash"],
              "checkpoint_hash": checkpoint["content_hash"], "registration_hash": state["registration_hash"],
              "views": views, "fixed_source_views": True, "source_authenticity_verified": False,
              "causal_effect_identified": False}
    audit.equal(receipt, wanted, "saved receipt equals its exact retained checkpoint")


def check_case(private):
    audit = Audit(private)
    protocol = audit.read(CASE / "protocol.json")
    metadata = audit.read(FIXTURE / "metadata.json")
    audit.equal(protocol["schema"], "sociolab.network-tracking-case-protocol.v1", "frozen case protocol schema")
    audit.equal(protocol["fixture_metadata_file_sha256"], file_digest(FIXTURE / "metadata.json"), "protocol binds fixture metadata")
    for key, wanted in (("planned_delivery_count", 11), ("planned_applied_count", 9), ("planned_idempotent_count", 2),
                        ("planned_checkpoint_count_including_initial", 10), ("planned_final_knowledge_cutoff", 22),
                        ("planned_final_sequence", 9), ("registered_view_count", 3)):
        audit.number(protocol[key], wanted, "protocol planned count " + key)
    audit.equal(metadata["schema"], "sociolab.network-tracking-fixture.v1", "fixture schema")
    for name, expected_hash in metadata["input_file_sha256"].items():
        audit.equal(file_digest(FIXTURE / name), expected_hash, "frozen fixture file hash")
    audit.equal(file_digest(FIXTURE / "generate_fixture.py"), metadata["generator_file_sha256"], "fixture generator hash")
    empty = audit.read(FIXTURE / metadata["initial_dataset"])
    registration = audit.read(FIXTURE / metadata["registration"])
    batches = audit.read(FIXTURE / metadata["streams"]["all"], lines=True)
    first = audit.read(FIXTURE / metadata["streams"]["before_restart"], lines=True)
    second = audit.read(FIXTURE / metadata["streams"]["after_restart"], lines=True)
    audit.equal(first + second, batches, "stream split retains exact batch order")
    audit.number(len(first), 8, "restart split")
    audit.number(len(batches), 11, "delivery count")
    audit.equal(empty["records"], [], "initial journal is empty")
    audit.equal(empty["clock"], {"kind": "ticks", "run_id": "network-tracking-example"}, "fixed source clock")
    audit.equal([row["view_id"] for row in registration["views"]], list(VIEW_IDS), "registered fixture views")
    normalized = deepcopy(registration)
    for row in normalized["views"]:
        audit.equal(row["analysis"], {}, "fixture uses fixed default analyses")
        row["analysis"] = deepcopy(ANALYSIS)
    files = sorted((private / "store").glob("[0-9]*.json"))
    audit.equal([path.name for path in files], [f"{index:08d}.json" for index in range(10)], "contiguous retained checkpoints")
    checkpoints = [audit.read(path) for path in files]
    checkpoint_hashes = {path.name: file_digest(path) for path in files}
    reconstructed, summaries = [], []
    for sequence, checkpoint in enumerate(checkpoints):
        audit.hashed(checkpoint, "checkpoint")
        audit.equal(checkpoint["schema"], "sociolab.network-tracking-checkpoint.v1", "checkpoint schema")
        audit.number(checkpoint["sequence"], sequence, "checkpoint sequence")
        audit.equal(checkpoint["previous_checkpoint_hash"], None if sequence == 0 else checkpoints[sequence - 1]["content_hash"],
                    "checkpoint predecessor hash")
        state = checkpoint["state"]
        audit.hashed(state, "state")
        audit.equal(state["schema"], "sociolab.network-tracking-state.v1", "state schema")
        audit.equal(state["kind"], "NETWORK_TRACKING_STATE", "state kind")
        audit.equal(state["profile"], "receipt-fixed-view-tracking-v1", "state profile")
        audit.number(state["sequence"], sequence, "state sequence")
        audit.equal(state["registration"], normalized, "immutable full view and analysis registration")
        audit.equal(state["registration_hash"], digest(normalized), "registration hash")
        journal = state["dataset"]
        audit.equal({key: value for key, value in journal.items() if key != "records"},
                    {key: value for key, value in empty.items() if key != "records"}, "immutable source envelope")
        audit.number(state["knowledge_cutoff"], len(journal["records"]), "state exact receipt cutoff")
        audit.equal(state["previous_state_hash"], None if sequence == 0 else checkpoints[sequence - 1]["state"]["content_hash"],
                    "state predecessor hash")
        if sequence:
            old = checkpoints[sequence - 1]["state"]["dataset"]["records"]
            audit.equal(journal["records"][:len(old)], old, "immutable complete raw receipt prefix")
            audit.check(len(journal["records"]) > len(old), "nonduplicate committed batch")
        audit.equal([row["view_id"] for row in state["views"]], list(VIEW_IDS), "retained view order")
        expected_views = []
        for row, declared in zip(state["views"], normalized["views"]):
            snapshot = row["snapshot"]
            audit.hashed(snapshot, "snapshot")
            audit.equal(snapshot["schema"], "sociolab.snapshot.v1", "snapshot schema")
            expected = reconstruct(audit, journal, declared["view"])
            expected_views.append(expected)
            for key, wanted in expected.items():
                audit.equal(snapshot[key], wanted, "independent source replay " + key)
            audit.equal(snapshot["view"], declared["view"], "fixed snapshot source query")
            audit.number(snapshot["knowledge_cutoff"], len(journal["records"]), "snapshot cutoff")
            wanted_dataset = {key: journal[key] for key in ("dataset_id", "origin", "source_revision", "clock")}
            wanted_dataset.update(content_hash=digest(journal), known_records_hash=digest(journal["records"]))
            audit.equal(snapshot["dataset"], wanted_dataset, "snapshot complete prefix hashes")
            policy = {key: value for key, value in declared["view"].items() if key not in ("at", "start", "end")}
            audit.equal(snapshot["policy_hash"], digest({"view": policy, "clock": journal["clock"]}), "view policy hash")
            audit.equal(row["fingerprints"], fingerprints(expected), "independent semantic fingerprints")
        reconstructed.append(expected_views)
        for key in ("historical_as_of_availability_verified", "content_hash_authenticates_author",
                    "content_hash_proves_external_timestamp", "causal_effect_identified", "live_subscription"):
            audit.equal(state["scope"][key], False, "retained scope " + key)
        if sequence:
            summaries.append({"sequence": sequence, "knowledge_cutoff": state["knowledge_cutoff"],
                              "views": check_transition(audit, checkpoint, checkpoints[sequence - 1], expected_views, reconstructed[-2])})
        else:
            audit.equal(checkpoint["transition"], None, "initial checkpoint has no transition")
            audit.equal(journal, empty, "initial checkpoint source binding")
    receipts = audit.read(private / "receipts.json")
    audit.number(len(receipts), len(batches), "one recorded acknowledgment per delivery")
    expected_journal, known, sequence = deepcopy(empty), {}, 0
    for index, (batch, stage_name, receipt) in enumerate(zip(batches, metadata["stage_order"], receipts), 1):
        audit.equal(sorted(batch), ["received_at", "records", "schema"], "strict fixture batch keys")
        audit.equal(batch["schema"], "sociolab.network-tracking-batch.v1", "batch schema")
        before_count = len(expected_journal["records"])
        for raw in batch["records"]:
            audit.check("ingest_seq" not in raw and "recorded_at" not in raw, "importer owns receipts")
            if raw["record_id"] in known:
                audit.equal(raw, known[raw["record_id"]], "duplicate old revision retains exact source content")
                continue
            known[raw["record_id"]] = deepcopy(raw)
            expected_journal["records"].append({**deepcopy(raw), "ingest_seq": len(expected_journal["records"]) + 1,
                                                "recorded_at": batch["received_at"]})
        added = len(expected_journal["records"]) - before_count
        sequence += bool(added)
        checkpoint = checkpoints[sequence]
        audit.equal(checkpoint["state"]["dataset"], expected_journal, "independent ordered import and record deduplication")
        status = "APPLIED" if added else "NO_NEW_RECORDS"
        check_receipt(audit, receipt, checkpoint, status)
        stage = metadata["stages"][stage_name]
        for key, wanted in (("delivery_index", index), ("records_added", added), ("knowledge_cutoff_before", before_count),
                            ("knowledge_cutoff", len(expected_journal["records"])), ("accepted_batch_sequence", sequence)):
            audit.number(stage[key], wanted, "declared fixture delivery " + key)
        audit.equal(stage["expected_receipt_status"], status, "declared idempotent receipt status")
        old_sequence = sequence - 1 if added else sequence
        for view_index, view_id in enumerate(VIEW_IDS):
            old, new = reconstructed[old_sequence][view_index], reconstructed[sequence][view_index]
            entry = stage["views"][view_id]
            flags = dict(zip(FLAGS, [fingerprints(old)[k] != fingerprints(new)[k] for k in ("graph", "population", "coverage", "evidence")]))
            audit.equal(entry["observed_graph_changed"], flags["observed_graph_changed"], "fixture observed graph flag")
            audit.equal(entry["population_changed"], flags["population_changed"], "fixture population flag")
            audit.equal(entry["coverage_changed"], flags["coverage_changed"], "fixture coverage flag")
            audit.equal(entry["selected_evidence_changed"], flags["evidence_changed"], "fixture selected evidence flag")
            audit.equal(entry["receipt_prefix_evidence_changed"], bool(added), "fixture receipt-only distinction")
            audit.equal(entry["snapshot_hash_changed"], bool(added), "fixture full snapshot hash change")
            audit.equal(entry["complete"], new["coverage"]["complete"], "fixture completeness")
            audit.number(entry["edge_count"], len(new["edges"]), "fixture edge count")
            wanted_status, wanted_reason = expected_comparison(old, new, flags) if added else (None, None)
            audit.equal(entry["tracking_comparison_status"], wanted_status, "fixture tracking comparison status")
            audit.equal(entry["tracking_comparison_reason"], wanted_reason, "fixture tracking comparison reason")
            eligible = bool(added and old["coverage"]["complete"] and new["coverage"]["complete"])
            audit.equal(entry["comparison_eligible"], eligible, "fixture qualified comparison scope")
            if eligible:
                audit.equal(entry["qualified_relation_change_counts"],
                            {key: count for key, count in relation_counts(old, new).items() if key != "unchanged_edge_count"},
                            "independent source relation counts against fixture oracle")
    audit.number(sequence, 9, "nine nonduplicate deliveries")
    audit.number(len(expected_journal["records"]), 22, "final receipt count")
    comparison_count = sum(row["comparison_status"] == "OK" for s in summaries for row in s["views"])
    audit.number(comparison_count, 6, "six eligible observable view changes")
    rejected = audit.read(FIXTURE / metadata["negative_case"]["file"], lines=True)
    audit.number(len(rejected), 1, "one rejected delivery fixture")
    audit.number(len(rejected[0]["records"]), 1, "one conflicting retry record")
    conflicting = rejected[0]["records"][0]
    audit.check(conflicting["record_id"] in known and canonical(conflicting) != canonical(known[conflicting["record_id"]]),
                "rejected fixture reuses an accepted ID with changed source content")
    check_receipt(audit, audit.read(private / "initial-receipt.json"), checkpoints[0], "INITIALIZED")
    check_receipt(audit, audit.read(private / "restart-inspect.json"), checkpoints[7], "INSPECTED")
    check_receipt(audit, audit.read(private / "final-inspect.json"), checkpoints[9], "INSPECTED")
    execution = audit.read(private / "execution-private.json")
    audit.equal(execution["status"], "PASS", "recorded case execution status")
    audit.equal(execution["protocol_file_sha256"], file_digest(CASE / "protocol.json"), "execution binds fixed protocol")
    audit.equal(execution["checkpoint_creation_hashes"], checkpoint_hashes, "checkpoint creation seals")
    audit.equal(execution["checkpoints_final_hashes"], checkpoint_hashes, "old checkpoint files preserved after restart")
    audit.equal(execution["source_hashes_before"], execution["source_hashes_after"], "execution implementation stayed fixed")
    for name, wanted in execution["source_hashes_before"].items():
        path = (REPOSITORY / name).resolve()
        audit.check(path.is_relative_to(REPOSITORY), "source hash path scope")
        audit.equal(file_digest(path), wanted, "current implementation matches recorded execution")
    sessions = execution["sessions"]
    audit.number(len(sessions), 2, "two actual streaming sessions")
    for session, index, start, end, termination, exit_code in (
            (sessions[0], 1, 1, 8, "SIGKILL", -9), (sessions[1], 2, 9, 11, "EOF", 0)):
        for key, wanted in (("index", index), ("delivery_start_1based", start), ("delivery_end_1based", end),
                            ("acknowledged_before_eof_count", end - start + 1), ("exit_code", exit_code)):
            audit.number(session[key], wanted, "recorded streaming session " + key)
        audit.equal(session["termination"], termination, "recorded session termination")
    audit.equal(execution["competing_writer_rejected"], True, "actual competing writer rejected")
    audit.number(execution["rejected_batch_exit_code"], 2, "conflicting retry exit code")
    audit.equal(execution["rejected_batch_preserved_checkpoints"], True, "conflicting retry preserves commits")
    public_execution = audit.read(CASE / "execution.json")
    audit.equal(public_execution, execution, "public execution matches retained private execution record")
    public_report = audit.read(CASE / "report.json")
    audit.equal(public_report["status"], "PASS", "public report execution status")
    for key, wanted in (("delivery_count", 11), ("applied_count", 9), ("no_new_records_count", 2),
                        ("checkpoint_count", 10), ("registered_view_count", 3),
                        ("final_knowledge_cutoff", 22), ("final_sequence", 9), ("acknowledgments_observed_before_eof", 11)):
        audit.number(public_report[key], wanted, "public report count " + key)
    audit.equal(public_report["receipts"], [{"stage": stage, **receipt} for stage, receipt in zip(metadata["stage_order"], receipts)],
                "public receipt summaries bind all private acknowledgments")
    audit.equal(public_report["scope"], metadata["scope"], "public report retains fixture-only scope")
    audit.equal(public_report["final_checkpoint_hash"], checkpoints[-1]["content_hash"], "public report final checkpoint")
    for key in ("forced_process_exit_recovered", "all_retained_checkpoint_bytes_unchanged",
                "competing_writer_rejected", "conflicting_record_retry_rejected"):
        audit.equal(public_report[key], True, "public report execution claim " + key)
    for label, expected_hash in audit.inputs.items():
        path = private / label.removeprefix("private/") if label.startswith("private/") else REPOSITORY / label.removeprefix("repository/")
        audit.equal(file_digest(path), expected_hash, "checker leaves every input unchanged")
    report = {
        "schema": "sociolab.independent-network-tracking-check.v1", "kind": "INDEPENDENT_NETWORK_TRACKING_CHECK",
        "status": "PASS", "method": "stdlib_fixed_fixture_source_replay_prefix_binding_and_receipt_checks",
        "counts": {"checks": audit.checks, "numeric_comparisons": audit.numeric_checks, "checkpoints": 10,
                   "deliveries": 11, "applied_batches": 9, "idempotent_deliveries": 2, "accepted_source_records": 22,
                   "registered_views": 3, "independently_reconstructed_snapshots": 30,
                   "qualified_comparison_reports": comparison_count},
        "numeric_comparison": {"max_absolute_error": audit.max_error, "comparison": "exact counts and declared values"},
        "checkpoint_file_sha256": checkpoint_hashes, "input_file_sha256": audit.inputs,
        "protocol_file_sha256": file_digest(CASE / "protocol.json"),
        "checker_sha256": file_digest(Path(__file__)), "transition_summaries": summaries,
        "scope": {"fixture_specific_source_replay": True, "standard_library_only": True,
                  "sociolab_imported": False, "graph_library_imported": False, "tracker_executed_by_checker": False,
                  "community_algorithms_independently_validated": False, "model_fitted_or_refitted": False,
                  "observed_process_claims_bound_to_retained_execution_record": True,
                  "all_source_values_known_before_execution": True, "output": "aggregate_only",
                  "source_authenticity_verified": False, "historical_as_of_availability_verified": False,
                  "external_source_subscription": False, "empirical_forecast_validated": False,
                  "causal_effect_identified": False, "hashes_authenticate_sources_or_times": False},
        "runtime": {"python": platform.python_version(), "dependency": "Python standard library"},
    }
    return {**report, "content_hash": digest(report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("output already exists; independent reports are not overwritten")
    report = check_case(args.private_root.resolve())
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "counts": report["counts"],
                      "numeric_comparison": report["numeric_comparison"],
                      "content_hash": report["content_hash"]}, sort_keys=True))


if __name__ == "__main__":
    main()
