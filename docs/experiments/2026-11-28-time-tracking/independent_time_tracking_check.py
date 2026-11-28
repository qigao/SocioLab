#!/usr/bin/env python3
"""Independently check the invented source-time tracking case using only the stdlib.

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
FIXTURE = REPOSITORY / "examples" / "time-tracking"
VIEW_IDS = ("cooperation", "communication", "trust")
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
    """Replay this ticks fixture, without implementing general snapshot semantics.

    Membership is present from zero. Coverage consists of explicit finite
    complete intervals; gaps remain unobserved/partial. State facts persist
    from their source time; interactions enter [start,end) exactly. There are
    no aliases, activities, annotations or membership exits in this fixture.
    """
    records = journal["records"]
    active = effective_records(audit, records)
    kinds = {"entity.observed", "membership.changed", "coverage.observed",
             "relation.changed", "interaction.observed"}
    audit.check(all(record["kind"] in kinds for record in active), "fixed fixture record kinds")
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
        audit.equal(record["payload"]["status"], "present", "fixture membership state")
        audit.number(record["occurred_at"], 0, "fixture membership origin")
    selected = {record["record_id"] for record in membership}
    coverage = [record for record in active if record["kind"] == "coverage.observed"
                and record["payload"]["population"] == view["population"]
                and record["payload"]["layer"] == view["layer"]]
    for record in coverage:
        audit.equal(sorted(record["payload"]["actors"]), persons, "coverage roster")
        audit.equal(record["payload"]["status"], "complete", "fixture declared coverage status")
        interval = record["valid_interval"]
        audit.check(type(interval) is list and len(interval) == 2 and
                    all(type(value) is int for value in interval) and interval[0] < interval[1],
                    "fixture finite coverage interval")
    state_mode = view["mode"] == "state"
    if state_mode:
        points = [view["at"]]
    else:
        audit.equal({key: view[key] for key in ("mode", "directed", "actions", "topics")},
                    {"mode": "events", "directed": True, "actions": ["reply", "utterance"], "topics": []},
                    "fixed communication query semantics")
        audit.number(view["end"] - view["start"], 10, "fixed trailing width")
        cuts = {view["start"], view["end"]}
        for record in coverage:
            cuts.update(value for value in record["valid_interval"] if view["start"] < value < view["end"])
        points = sorted(cuts)[:-1]
    coverage_ids, statuses = set(), []
    for point in points:
        matching = [record for record in coverage if record["valid_interval"][0] <= point < record["valid_interval"][1]]
        coverage_ids.update(record["record_id"] for record in matching)
        statuses.append("complete" if matching else "unobserved")
    coverage_status = ("complete" if all(value == "complete" for value in statuses) else
                       "unobserved" if all(value == "unobserved" for value in statuses) else "partial")
    selected.update(coverage_ids)
    edge_records = {}
    if state_mode:
        audit.check(not view["directed"] and view["layer"] in ("cooperation", "trust"), "fixture state graph type")
        for record in active:
            if record["kind"] != "relation.changed" or record["payload"]["layer"] != view["layer"]:
                continue
            audit.check(not record["payload"]["directed"] and record["valid_interval"] is None,
                        "fixture state record form")
            if record["occurred_at"] <= view["at"]:
                pair = tuple(sorted((record["payload"]["source"], record["payload"]["target"])))
                edge_records.setdefault(pair, []).append(record)
        edges = []
        for pair, candidates in sorted(edge_records.items()):
            latest = max(record["occurred_at"] for record in candidates)
            effective = [record for record in candidates if record["occurred_at"] == latest]
            strength = effective[0]["payload"]["strength"]
            audit.check(all(record["payload"]["strength"] == strength for record in effective),
                        "unique selected source relation value")
            evidence = sorted(record["record_id"] for record in effective)
            selected.update(evidence)
            if strength > 0:
                edges.append({"source": pair[0], "target": pair[1], "strength": strength, "evidence": evidence})
    else:
        for record in active:
            if (record["kind"] == "interaction.observed" and view["start"] <= record["occurred_at"] < view["end"]
                    and record["payload"]["action"] in view["actions"]):
                pair = (record["payload"]["actor"], record["payload"]["target"])
                edge_records.setdefault(pair, []).append(record)
                selected.add(record["record_id"])
        edges = [{"source": pair[0], "target": pair[1], "strength": len(items),
                  "evidence": sorted(record["record_id"] for record in items)}
                 for pair, items in sorted(edge_records.items())]
    audit.check(all(edge["source"] in persons and edge["target"] in persons
                    and edge["source"] != edge["target"] for edge in edges), "fixture endpoint eligibility")
    return {
        "directed": view["directed"], "bipartite": False, "persons": persons, "activities": [], "edges": edges,
        "weight_semantics": "observed_strength" if state_mode else "event_count",
        "population": {"policy": "eligible_at" if state_mode else "eligible_any_overlap", "eligible": persons,
                       "absent": [], "unknown": [], "unknown_intervals": {},
                       "exposure": {person: 1 if state_mode else 10 for person in persons},
                       "exposure_unit": "point" if state_mode else "tick"},
        "coverage": {"complete": bool(coverage_ids) and coverage_status == "complete",
                     "actors": {person: coverage_status for person in persons}, "evidence": sorted(coverage_ids)},
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
    audit.equal(transition["schema"], "sociolab.temporal-tracking-transition.v1", "transition schema")
    audit.equal(transition["kind"], "TEMPORAL_TRACKING_TRANSITION", "transition kind")
    audit.equal(transition["profile"], "receipt-source-time-tracking-v1", "transition profile")
    audit.equal(transition["status"], "APPLIED", "committed transition status")
    for key, wanted in (("before_state_hash", before["content_hash"]), ("after_state_hash", state["content_hash"]),
                        ("before_sequence", before["sequence"]), ("after_sequence", state["sequence"]),
                        ("before_knowledge_cutoff", before["knowledge_cutoff"]),
                        ("after_knowledge_cutoff", state["knowledge_cutoff"]),
                        ("before_cursor", before["cursor"]), ("after_cursor", state["cursor"]),
                        ("before_cursor_value", before["cursor_value"]), ("after_cursor_value", state["cursor_value"]),
                        ("registration_hash", state["registration_hash"])):
        audit.equal(transition[key], wanted, "transition state binding " + key)
    tail = state["dataset"]["records"][before["knowledge_cutoff"]:]
    if tail:
        audit.equal(transition["cause"], "receipt_batch", "receipt commit cause")
        audit.equal(state["cursor"], before["cursor"], "receipt commit holds source cursor")
        audit.check(all(record["recorded_at"] == tail[0]["recorded_at"] for record in tail), "one batch receipt instant")
    else:
        audit.equal(transition["cause"], "source_time_advance", "time commit cause")
        audit.equal(state["dataset"], before["dataset"], "time commit retains entire journal")
        audit.check(state["cursor_value"] > before["cursor_value"], "time-only commit strictly advances")
    source = {"appended_record_count": len(tail),
              "new_assertion_count": sum(r["operation"] == "assert" and r["supersedes"] is None for r in tail),
              "revised_assertion_count": sum(r["operation"] == "assert" and r["supersedes"] is not None for r in tail),
              "retraction_count": sum(r["operation"] == "retract" for r in tail),
              "first_ingest_seq": tail[0]["ingest_seq"] if tail else None,
              "last_ingest_seq": tail[-1]["ingest_seq"] if tail else None,
              "recorded_at": tail[0]["recorded_at"] if tail else None,
              "appended_records_hash": digest(tail), "record_ids": [r["record_id"] for r in tail]}
    audit.equal(transition["source"], source, "transition source counters and empty-tail semantics")
    summaries = []
    audit.equal([row["view_id"] for row in transition["views"]], list(VIEW_IDS), "transition view order")
    for index, row in enumerate(transition["views"]):
        old, new = prior_expected[index], expected[index]
        old_fp, new_fp = fingerprints(old), fingerprints(new)
        flags = dict(zip(FLAGS, [old_fp[k] != new_fp[k] for k in ("graph", "population", "coverage", "evidence")]))
        audit.equal({key: row[key] for key in FLAGS}, flags, "independent semantic change flags")
        audit.equal(row["before_fingerprints"], old_fp, "old semantic fingerprints")
        audit.equal(row["after_fingerprints"], new_fp, "new semantic fingerprints")
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
    audit.equal(transition["scope"]["window_expiry_proves_real_relation_ended"], False, "window expiry scope")
    return summaries


def check_receipt(audit, receipt, checkpoint, status, cause=None):
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
                      "comparison_reason": None if comparison is None else comparison.get("reason"),
                      "source_time": {key: snap["view"][key] for key in ("at", "start", "end") if key in snap["view"]}})
    wanted = {"kind": "NETWORK_TRACKING_RECEIPT", "status": status, "sequence": state["sequence"],
              "knowledge_cutoff": state["knowledge_cutoff"], "state_hash": state["content_hash"],
              "checkpoint_hash": checkpoint["content_hash"], "registration_hash": state["registration_hash"],
              "views": views, "fixed_source_views": False, "source_authenticity_verified": False,
              "causal_effect_identified": False, "cursor": state["cursor"], "cursor_value": state["cursor_value"],
              "source_time_unit": "tick", "view_templates_fixed": True, "transition_cause": cause}
    audit.equal(receipt, wanted, "saved receipt equals its exact retained checkpoint and requested cause")


def check_case(private):
    audit = Audit(private)
    protocol = audit.read(CASE / "protocol.json")
    metadata = audit.read(FIXTURE / "metadata.json")
    audit.equal(protocol["schema"], "sociolab.temporal-tracking-case-protocol.v1", "frozen protocol schema")
    audit.equal(protocol["fixture_metadata_file_sha256"], file_digest(FIXTURE / "metadata.json"), "protocol binds frozen metadata")
    for key, wanted in (("planned_delivery_count", 11), ("planned_applied_count", 8),
                        ("planned_receipt_append_count", 3), ("planned_source_time_advance_count", 5),
                        ("planned_no_new_records_count", 1), ("planned_no_time_advance_count", 2),
                        ("planned_checkpoint_count_including_initial", 9), ("planned_final_knowledge_cutoff", 22),
                        ("planned_final_sequence", 8), ("planned_initial_cursor", 10), ("planned_final_cursor", 26),
                        ("registered_view_count", 3)):
        audit.number(protocol[key], wanted, "protocol planned count " + key)
    audit.equal(protocol["source_time_unit"], "tick", "protocol source unit")
    audit.equal(protocol["execution"]["required_restart_position"],
                {"sequence": 4, "knowledge_cutoff": 20, "cursor": 20}, "protocol exact restart position")
    audit.equal(protocol["scope"]["cursor_is_not_a_feed_completeness_watermark"], True, "protocol watermark scope")
    for key in ("intermediate_instants_between_advances_exhaustively_checked", "automatic_wall_clock_scheduler",
                "external_source_subscription", "automatic_forecast_trigger", "source_authenticity_verified",
                "empirical_prediction_validated", "causal_effect_identified"):
        audit.equal(protocol["scope"][key], False, "protocol scope " + key)
    audit.equal(metadata["schema"], "sociolab.temporal-tracking-fixture.v1", "fixture schema")
    for name, wanted in metadata["input_file_sha256"].items():
        audit.equal(file_digest(FIXTURE / name), wanted, "frozen fixture input hash")
    audit.equal(file_digest(FIXTURE / "generate_fixture.py"), metadata["generator_file_sha256"], "fixture generator hash")
    empty = audit.read(FIXTURE / metadata["initial_dataset"])
    registration = audit.read(FIXTURE / metadata["registration"])
    requests = audit.read(FIXTURE / metadata["streams"]["all"], lines=True)
    first = audit.read(FIXTURE / metadata["streams"]["before_restart"], lines=True)
    second = audit.read(FIXTURE / metadata["streams"]["after_restart"], lines=True)
    audit.equal(first + second, requests, "stream split preserves exact request order")
    audit.number(len(first), 5, "restart split")
    audit.number(len(requests), 11, "request count")
    audit.equal(empty["records"], [], "initial journal is empty")
    audit.equal(empty["clock"], {"kind": "ticks", "run_id": "time-tracking-example"}, "fixed source clock")
    audit.equal(registration["schema"], "sociolab.temporal-tracking-spec.v1", "temporal registration schema")
    audit.equal(registration["source_time_unit"], "tick", "source time unit")
    audit.number(registration["initial_cursor"], 10, "initial source cursor")
    audit.equal([row["view_id"] for row in registration["views"]], list(VIEW_IDS), "registered fixture views")
    normalized = deepcopy(registration)
    for row in normalized["views"]:
        audit.equal(row["analysis"], {}, "fixture uses fixed default analyses")
        audit.equal(row["window_width"], 10 if row["view_id"] == "communication" else None, "fixed template width")
        audit.check(not {"at", "start", "end"}.intersection(row["view"]), "templates omit resolved source bounds")
        row["analysis"] = deepcopy(ANALYSIS)
    files = sorted((private / "store").glob("[0-9]*.json"))
    audit.equal([path.name for path in files], [f"{index:08d}.json" for index in range(9)], "contiguous retained checkpoints")
    checkpoints = [audit.read(path) for path in files]
    checkpoint_hashes = {path.name: file_digest(path) for path in files}
    audit.equal(metadata["checkpoints"], [{"sequence": entry["state"]["sequence"],
                                         "knowledge_cutoff": entry["state"]["knowledge_cutoff"],
                                         "source_cursor": entry["state"]["cursor"]} for entry in checkpoints],
                "predeclared two-axis checkpoint schedule")
    reconstructed, summaries = [], []
    for sequence, checkpoint in enumerate(checkpoints):
        audit.hashed(checkpoint, "checkpoint")
        audit.equal(checkpoint["schema"], "sociolab.network-tracking-checkpoint.v1", "shared checkpoint schema")
        audit.number(checkpoint["sequence"], sequence, "checkpoint sequence")
        audit.equal(checkpoint["previous_checkpoint_hash"], None if sequence == 0 else checkpoints[sequence - 1]["content_hash"],
                    "checkpoint predecessor hash")
        state = checkpoint["state"]
        audit.hashed(state, "state")
        audit.equal(state["schema"], "sociolab.temporal-tracking-state.v1", "state schema")
        audit.equal(state["kind"], "TEMPORAL_TRACKING_STATE", "state kind")
        audit.equal(state["profile"], "receipt-source-time-tracking-v1", "state profile")
        audit.number(state["sequence"], sequence, "state sequence")
        audit.equal(state["registration"], normalized, "immutable full templates and analysis registration")
        audit.equal(state["registration_hash"], digest(normalized), "registration hash")
        audit.check(type(state["cursor"]) is int and state["cursor"] >= 10, "fixture exact tick cursor")
        audit.number(state["cursor_value"], state["cursor"], "numeric cursor binding")
        journal = state["dataset"]
        audit.equal({key: value for key, value in journal.items() if key != "records"},
                    {key: value for key, value in empty.items() if key != "records"}, "immutable source envelope")
        audit.number(state["knowledge_cutoff"], len(journal["records"]), "state exact receipt cutoff")
        audit.equal(state["previous_state_hash"], None if sequence == 0 else checkpoints[sequence - 1]["state"]["content_hash"],
                    "state predecessor hash")
        if sequence:
            old = checkpoints[sequence - 1]["state"]["dataset"]["records"]
            audit.equal(journal["records"][:len(old)], old, "immutable complete raw receipt prefix")
            audit.check(len(journal["records"]) >= len(old), "receipt count cannot decrease")
        audit.equal([row["view_id"] for row in state["views"]], list(VIEW_IDS), "retained view order")
        expected_views = []
        for row, declared in zip(state["views"], normalized["views"]):
            view = deepcopy(declared["view"])
            if view["mode"] == "state":
                view["at"] = state["cursor"]
            else:
                view.update(start=state["cursor"] - declared["window_width"], end=state["cursor"])
            snapshot = row["snapshot"]
            audit.hashed(snapshot, "snapshot")
            audit.equal(snapshot["schema"], "sociolab.snapshot.v1", "snapshot schema")
            expected = reconstruct(audit, journal, view)
            expected_views.append(expected)
            for key, wanted in expected.items():
                audit.equal(snapshot[key], wanted, "independent source replay " + key)
            audit.equal(snapshot["view"], view, "exact cursor-resolved source query")
            audit.number(snapshot["knowledge_cutoff"], len(journal["records"]), "snapshot receipt cutoff")
            wanted_dataset = {key: journal[key] for key in ("dataset_id", "origin", "source_revision", "clock")}
            wanted_dataset.update(content_hash=digest(journal), known_records_hash=digest(journal["records"]))
            audit.equal(snapshot["dataset"], wanted_dataset, "snapshot full journal prefix hashes")
            audit.equal(snapshot["policy_hash"], digest({"view": declared["view"], "clock": journal["clock"]}), "unchanged temporal view policy hash")
            audit.equal(row["fingerprints"], fingerprints(expected), "independent semantic fingerprints")
        reconstructed.append(expected_views)
        for key in ("historical_as_of_availability_verified", "content_hash_authenticates_author",
                    "content_hash_proves_external_timestamp", "causal_effect_identified", "live_subscription",
                    "automatic_event_time_advance", "receipt_batches_advance_source_time", "source_time_advances_append_receipts",
                    "source_time_cursor_is_receipt_time", "source_time_advance_proves_new_source_fact", "window_expiry_proves_real_relation_ended"):
            audit.equal(state["scope"][key], False, "retained scope " + key)
        if sequence:
            summaries.append({"sequence": sequence, "knowledge_cutoff": state["knowledge_cutoff"],
                              "source_cursor": state["cursor"], "cause": checkpoint["transition"]["cause"],
                              "views": check_transition(audit, checkpoint, checkpoints[sequence - 1], expected_views, reconstructed[-2])})
        else:
            audit.equal(checkpoint["transition"], None, "initial checkpoint has no transition")
            audit.equal(journal, empty, "initial checkpoint source binding")
            audit.number(state["cursor"], 10, "initial checkpoint cursor")
    receipts = audit.read(private / "receipts.json")
    audit.number(len(receipts), len(requests), "one saved acknowledgment per request")
    expected_journal, known, sequence, cursor = deepcopy(empty), {}, 0, 10
    request_counts = {"APPLIED": 0, "NO_NEW_RECORDS": 0, "NO_TIME_ADVANCE": 0}
    for index, (request, stage_name, receipt) in enumerate(zip(requests, metadata["stage_order"], receipts), 1):
        before_count, before_cursor, before_sequence = len(expected_journal["records"]), cursor, sequence
        is_receipt = request["schema"] == "sociolab.network-tracking-batch.v1"
        if is_receipt:
            audit.equal(sorted(request), ["received_at", "records", "schema"], "strict receipt envelope")
            for raw in request["records"]:
                audit.check("ingest_seq" not in raw and "recorded_at" not in raw, "importer owns receipt fields")
                if raw["record_id"] in known:
                    audit.equal(raw, known[raw["record_id"]], "record-level retry is exact")
                    continue
                known[raw["record_id"]] = deepcopy(raw)
                expected_journal["records"].append({**deepcopy(raw), "ingest_seq": len(expected_journal["records"]) + 1,
                                                    "recorded_at": request["received_at"]})
        else:
            audit.equal(request["schema"], "sociolab.network-tracking-advance.v1", "advance envelope schema")
            audit.equal(sorted(request), ["cursor", "schema"], "strict time-only control")
            audit.check(type(request["cursor"]) is int and request["cursor"] >= cursor, "forward or equal fixture control")
            cursor = request["cursor"]
        added = len(expected_journal["records"]) - before_count
        advanced = cursor != before_cursor
        committed = bool(added or advanced)
        sequence += committed
        checkpoint = checkpoints[sequence]
        audit.equal(checkpoint["state"]["dataset"], expected_journal, "independent import/control journal binding")
        audit.number(checkpoint["state"]["cursor"], cursor, "independent control cursor binding")
        status = "APPLIED" if committed else "NO_NEW_RECORDS" if is_receipt else "NO_TIME_ADVANCE"
        cause = "receipt_batch" if is_receipt else "source_time_advance"
        request_counts[status] += 1
        check_receipt(audit, receipt, checkpoint, status, cause)
        stage = metadata["stages"][stage_name]
        for key, wanted in (("delivery_index", index), ("records_added", added), ("knowledge_cutoff_before", before_count),
                            ("knowledge_cutoff", len(expected_journal["records"])), ("source_cursor_before", before_cursor),
                            ("source_cursor", cursor), ("sequence_before", before_sequence), ("sequence", sequence)):
            audit.number(stage[key], wanted, "declared fixture stage " + key)
        audit.equal(stage["expected_receipt_status"], status, "declared no-op status")
        audit.equal(stage["expected_transition_cause"], cause, "declared request cause")
        audit.equal(stage["checkpoint_created"], committed, "declared checkpoint creation")
        audit.equal(stage["source_time_advanced"], advanced, "declared cursor movement")
        for view_index, view_id in enumerate(VIEW_IDS):
            old, new = reconstructed[before_sequence][view_index], reconstructed[sequence][view_index]
            entry = stage["views"][view_id]
            flags = dict(zip(FLAGS, [fingerprints(old)[key] != fingerprints(new)[key] for key in ("graph", "population", "coverage", "evidence")]))
            audit.equal({key: entry[key] for key in FLAGS}, flags, "declared independent semantic flags")
            audit.equal(entry["selected_evidence_changed"], old["provenance"]["selected_records"] != new["provenance"]["selected_records"],
                        "declared selected evidence independent of whole prefix")
            audit.equal(entry["complete"], new["coverage"]["complete"], "declared coverage completeness")
            counts = {value: list(new["coverage"]["actors"].values()).count(value) for value in set(new["coverage"]["actors"].values())}
            audit.equal(entry["coverage_status_counts"], counts, "declared coverage status counts")
            audit.number(entry["edge_count"], len(new["edges"]), "declared edge count")
            snap = checkpoint["state"]["views"][view_index]["snapshot"]
            audit.equal(entry["snapshot_hash"], snap["content_hash"], "fixture oracle snapshot hash")
            audit.equal(entry["source_time"], {key: snap["view"][key] for key in ("at", "start", "end") if key in snap["view"]},
                        "declared resolved source bounds")
            audit.equal(entry["receipt_prefix_changed"], bool(added), "receipt change distinct from time movement")
            audit.equal(entry["resolved_view_changed"], advanced, "source query change distinct from receipts")
            audit.equal(entry["snapshot_hash_changed"], committed, "snapshot hash change includes time-only versions")
            wanted_status, wanted_reason = expected_comparison(old, new, flags) if committed else (None, None)
            audit.equal(entry["tracking_comparison_status"], wanted_status, "declared comparison status")
            audit.equal(entry["tracking_comparison_reason"], wanted_reason, "declared comparison reason")
            eligible = bool(committed and old["coverage"]["complete"] and new["coverage"]["complete"])
            audit.equal(entry["comparison_eligible"], eligible, "qualified comparison source scope")
            if eligible:
                audit.equal(entry["qualified_relation_change_counts"],
                            {key: value for key, value in relation_counts(old, new).items() if key != "unchanged_edge_count"},
                            "independent relation counts against source oracle")
    audit.equal(request_counts, {"APPLIED": 8, "NO_NEW_RECORDS": 1, "NO_TIME_ADVANCE": 2}, "request status totals")
    audit.number(sequence, 8, "committed version count")
    audit.number(cursor, 26, "final source cursor")
    audit.number(len(expected_journal["records"]), 22, "final receipt count")
    comparison_count = sum(row["comparison_status"] == "OK" for summary in summaries for row in summary["views"])
    audit.number(comparison_count, 5, "qualified observable comparisons")
    audit.number(sum(summary["cause"] == "source_time_advance" for summary in summaries), 5, "time-only commit count")
    audit.number(sum(summary["cause"] == "receipt_batch" for summary in summaries), 3, "receipt commit count")
    invisible = [s for s in summaries if not any(row[key] for row in s["views"] for key in FLAGS)]
    audit.equal([(s["sequence"], s["knowledge_cutoff"], s["source_cursor"], s["cause"]) for s in invisible],
                [(7, 22, 25, "source_time_advance")], "time-only commit survives unchanged semantic flags")
    check_receipt(audit, audit.read(private / "initial-receipt.json"), checkpoints[0], "INITIALIZED")
    check_receipt(audit, audit.read(private / "restart-inspect.json"), checkpoints[4], "INSPECTED")
    check_receipt(audit, audit.read(private / "final-inspect.json"), checkpoints[8], "INSPECTED")
    execution = audit.read(private / "execution-private.json")
    audit.equal(execution["status"], "PASS", "recorded execution status")
    audit.equal(execution["protocol_file_sha256"], file_digest(CASE / "protocol.json"), "execution binds frozen protocol")
    audit.equal(execution["checkpoint_creation_hashes"], checkpoint_hashes, "creation seals for all retained checkpoints")
    audit.equal(execution["checkpoints_final_hashes"], checkpoint_hashes, "retained checkpoint bytes unchanged")
    audit.equal(execution["source_hashes_before"], execution["source_hashes_after"], "execution source and fixture hashes stable")
    for name, wanted in execution["source_hashes_before"].items():
        path = (REPOSITORY / name).resolve()
        audit.check(path.is_relative_to(REPOSITORY), "source hash path scope")
        audit.equal(file_digest(path), wanted, "current source matches recorded execution")
    sessions = execution["sessions"]
    audit.number(len(sessions), 2, "actual streaming session count")
    for session, index, first_request, last_request, termination, exit_code in (
            (sessions[0], 1, 1, 5, "SIGKILL", -9), (sessions[1], 2, 6, 11, "EOF", 0)):
        for key, wanted in (("index", index), ("delivery_start_1based", first_request), ("delivery_end_1based", last_request),
                            ("acknowledged_before_eof_count", last_request - first_request + 1), ("exit_code", exit_code)):
            audit.number(session[key], wanted, "recorded session " + key)
        audit.equal(session["termination"], termination, "recorded process termination")
    audit.equal(execution["competing_writer_rejected"], True, "competing writer rejected")
    audit.number(len(execution["rejected_controls"]), 3, "negative control count")
    for declared, observed in zip(metadata["negative_cases"], execution["rejected_controls"]):
        negative = audit.read(FIXTURE / declared["file"], lines=True)
        audit.number(len(negative), 1, "single negative request")
        request = negative[0]
        reason = declared["expected"]
        if reason == "reject_backwards_source_time":
            audit.check(type(request["cursor"]) is int and request["cursor"] < cursor, "negative backward cursor")
        elif reason == "reject_noninteger_tick_cursor":
            audit.check(type(request["cursor"]) is not int, "negative tick type")
        else:
            audit.equal(reason, "reject_mixed_advance_and_receipt_fields", "known negative control reason")
            audit.check("records" in request and request["schema"] == "sociolab.network-tracking-advance.v1", "negative mixed command")
        audit.equal(observed, {"file": declared["file"], "expected": reason, "exit_code": 2,
                               "checkpoint_hash_preserved": True, "checkpoint_files_preserved": True},
                    "negative command retained execution evidence")
    audit.equal(audit.read(CASE / "execution.json"), execution, "public/private execution record equality")
    public = audit.read(CASE / "report.json")
    audit.equal(public["status"], "PASS", "public case status")
    for key, wanted in (("delivery_count", 11), ("applied_count", 8), ("no_new_records_count", 1),
                        ("no_time_advance_count", 2), ("applied_receipt_batch_count", 3),
                        ("applied_source_time_advance_count", 5), ("checkpoint_count", 9),
                        ("registered_view_count", 3), ("final_knowledge_cutoff", 22),
                        ("final_sequence", 8), ("final_cursor", 26), ("acknowledgments_observed_before_eof", 11)):
        audit.number(public[key], wanted, "public aggregate count " + key)
    audit.equal(public["source_time_unit"], "tick", "public source time unit")
    audit.equal(public["rejected_controls"], execution["rejected_controls"], "public negative-control evidence")
    audit.equal(public["protocol_file_sha256"], file_digest(CASE / "protocol.json"), "public protocol binding")
    for key in ("forced_process_exit_recovered", "all_retained_checkpoint_bytes_unchanged", "competing_writer_rejected"):
        audit.equal(public[key], True, "public observed execution claim " + key)
    audit.equal(public["receipts"], [{"stage": stage, **receipt} for stage, receipt in zip(metadata["stage_order"], receipts)],
                "public receipt summaries bind all private acknowledgments")
    audit.equal(public["scope"], metadata["scope"], "public scope remains fixture-specific")
    audit.equal(public["final_checkpoint_hash"], checkpoints[-1]["content_hash"], "public final checkpoint binding")
    for label, wanted in audit.inputs.items():
        path = private / label.removeprefix("private/") if label.startswith("private/") else REPOSITORY / label.removeprefix("repository/")
        audit.equal(file_digest(path), wanted, "checker leaves all input files unchanged")
    report = {
        "schema": "sociolab.independent-time-tracking-check.v1", "kind": "INDEPENDENT_TIME_TRACKING_CHECK", "status": "PASS",
        "method": "stdlib_fixture_source_time_receipt_replay_and_checkpoint_binding",
        "counts": {"checks": audit.checks, "numeric_comparisons": audit.numeric_checks, "checkpoints": 9,
                   "requests": 11, "applied_receipt_batches": 3, "applied_time_advances": 5,
                   "no_new_records": 1, "no_time_advance": 2, "final_knowledge_cutoff": 22, "final_cursor": 26,
                   "registered_views": 3, "independently_reconstructed_snapshots": 27,
                   "qualified_comparison_reports": comparison_count},
        "numeric_comparison": {"max_absolute_error": audit.max_error, "comparison": "exact counts and declared source values"},
        "checkpoint_file_sha256": checkpoint_hashes, "input_file_sha256": audit.inputs,
        "protocol_file_sha256": file_digest(CASE / "protocol.json"), "checker_sha256": file_digest(Path(__file__)),
        "transition_summaries": summaries,
        "scope": {"fixture_specific_ticks_source_replay": True, "standard_library_only": True,
                  "sociolab_imported": False, "graph_library_imported": False, "tracker_executed_by_checker": False,
                  "community_algorithms_independently_validated": False, "model_fitted_or_refitted": False,
                  "process_claims_bound_to_retained_execution_records": True, "output": "aggregate_only",
                  "all_source_values_known_before_execution": True, "source_cursor_explicit_not_wall_clock": True,
                  "window_expiry_proves_real_relation_ended": False, "source_authenticity_verified": False,
                  "historical_as_of_availability_verified": False, "external_source_subscription": False,
                  "empirical_forecast_validated": False, "causal_effect_identified": False,
                  "hashes_authenticate_sources_or_times": False},
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
