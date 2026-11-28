#!/usr/bin/env python3
"""Check the retained invented UTC live-tracking case using only the stdlib.

This checker independently reconstructs this fixture's two source views and
checks immutable receipts, query cursors, hashes and restart bindings. It does
not run a tracker, sample a clock, fit a model or validate graph algorithms.
Process observations are bound to retained execution records, not reobserved.
Only aggregate counts and hashes are written; actor records stay in memory.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import re


REPOSITORY = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
VIEW_IDS = ("cooperation", "communication")
FLAGS = ("observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed")
ANALYSIS = {
    "algorithm": "greedy", "seed": 0, "resolution": 1.0,
    "group_size": None, "group_members": None, "projection": "none",
    "max_nodes": 200, "max_edges": 2000, "max_pairs": 100000,
}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
WINDOW = 3_000_000
DAY = 86_400_000_000


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


def utc_value(value):
    if type(value) is not str or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        raise ValueError("fixture UTC values must have explicit UTC and at most six fractional digits")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    delta = instant - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def utc_text(value):
    return (EPOCH + timedelta(microseconds=value)).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
            raise ValueError("independent live tracking check failed: " + label)

    def equal(self, actual, expected, label):
        if isinstance(actual, (bytes, set)) or isinstance(expected, (bytes, set)):
            self.check(type(actual) is type(expected) and actual == expected, label)
        else:
            self.check(canonical(actual) == canonical(expected), label)

    def number(self, actual, expected, label):
        self.check(type(actual) in (int, float) and math.isfinite(actual), label + " type")
        self.numeric_checks += 1
        self.max_error = max(self.max_error, abs(actual - expected))
        self.check(actual == expected, label)

    def read(self, path):
        path = path.resolve()
        if path.is_relative_to(self.private):
            label = "private/" + path.relative_to(self.private).as_posix()
        else:
            self.check(path.is_relative_to(REPOSITORY), "input path is in a declared root")
            label = "repository/" + path.relative_to(REPOSITORY).as_posix()
        data = path.read_bytes()
        self.inputs[label] = sha256(data).hexdigest()
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique)

    def hashed(self, value, label):
        self.check(type(value) is dict and "content_hash" in value, label + " shape")
        self.equal(value["content_hash"], digest({k: v for k, v in value.items() if k != "content_hash"}),
                   label + " canonical hash")


def effective_records(audit, records):
    heads, ids, previous_receipt = {}, set(), None
    for sequence, record in enumerate(records, 1):
        audit.number(record["ingest_seq"], sequence, "contiguous receipt sequence")
        audit.check(record["record_id"] not in ids, "unique retained record ID")
        receipt = utc_value(record["recorded_at"])
        audit.check(previous_receipt is None or receipt >= previous_receipt, "nondecreasing recorded receipt time")
        previous_receipt = receipt
        key = (record["source"]["system"], record["fact_id"])
        predecessor = heads.get(key)
        audit.equal(record["supersedes"], None if predecessor is None else predecessor["record_id"],
                    "revision binds the exact prior fact head")
        if predecessor is not None:
            audit.equal(record["kind"], predecessor["kind"], "revision preserves source kind")
        audit.equal(record["operation"], "assert", "this fixture contains assertion revisions only")
        ids.add(record["record_id"])
        heads[key] = record
    return list(heads.values())


def reconstruct(audit, journal, view, anchor):
    """Reconstruct this fixed fixture, not a general materializer.

    Four people are present from anchor minus one day; two explicit complete
    coverage declarations are open-ended. Cooperation states persist. The
    single communication event is selected only in [cursor-3 seconds,cursor).
    There are no aliases, annotations, activities or population changes.
    """
    records = journal["records"]
    active = effective_records(audit, records)
    audit.check(len(records) in (13, 14), "fixture receipt cutoff")
    audit.equal({r["kind"] for r in active},
                {"entity.observed", "membership.changed", "coverage.observed", "relation.changed", "interaction.observed"},
                "fixture kinds")
    persons = sorted(r["payload"]["entity_id"] for r in active if r["kind"] == "entity.observed")
    audit.equal(persons, ["A", "B", "C", "D"], "invented fixed roster")
    memberships = [r for r in active if r["kind"] == "membership.changed"]
    audit.equal(sorted(r["payload"]["actor"] for r in memberships), persons, "one membership per person")
    for record in active:
        audit.equal(record["source"]["system"], "invented-live-tracking", "fixture source system")
        if record["kind"] == "entity.observed":
            audit.equal(record["payload"]["entity_type"], "person", "fixture entity type")
        if record["kind"] in ("entity.observed", "membership.changed", "relation.changed", "coverage.observed"):
            audit.number(utc_value(record["occurred_at"]), anchor - DAY, "source assertion time")
    for record in memberships:
        audit.equal(record["payload"]["population"], view["population"], "membership population")
        audit.equal(record["payload"]["status"], "present", "persistent fixture membership")
        audit.equal(record["valid_interval"], None, "fixture membership uses changed state")
    coverage = [r for r in active if r["kind"] == "coverage.observed" and r["payload"]["layer"] == view["layer"]]
    audit.number(len(coverage), 1, "one coverage declaration per layer")
    for record in coverage:
        audit.equal(record["payload"]["population"], view["population"], "coverage population")
        audit.equal(record["payload"]["actors"], persons, "coverage roster")
        audit.equal(record["payload"]["status"], "complete", "declared complete source coverage")
        audit.equal(record["valid_interval"], [utc_text(anchor - DAY), None], "open-ended fixture coverage")
    selected = {r["record_id"] for r in memberships + coverage}
    state_mode = view["mode"] == "state"
    if state_mode:
        cursor = utc_value(view["at"])
        audit.equal((view["layer"], view["directed"]), ("cooperation", False), "state layer and direction")
        candidates = {}
        for record in active:
            if record["kind"] == "relation.changed" and record["payload"]["layer"] == view["layer"]:
                audit.equal(record["valid_interval"], None, "state source interval")
                audit.equal(record["payload"]["directed"], False, "state source direction")
                if utc_value(record["occurred_at"]) <= cursor:
                    pair = tuple(sorted((record["payload"]["source"], record["payload"]["target"])))
                    candidates.setdefault(pair, []).append(record)
        edges = []
        for pair, values in sorted(candidates.items()):
            latest = max(utc_value(r["occurred_at"]) for r in values)
            chosen = [r for r in values if utc_value(r["occurred_at"]) == latest]
            strengths = {r["payload"]["strength"] for r in chosen}
            audit.number(len(strengths), 1, "unambiguous state strength")
            strength = next(iter(strengths))
            evidence = sorted(r["record_id"] for r in chosen)
            selected.update(evidence)
            if strength > 0:
                edges.append({"source": pair[0], "target": pair[1], "strength": strength, "evidence": evidence})
        exposure = 1
    else:
        start, cursor = utc_value(view["start"]), utc_value(view["end"])
        audit.number(cursor - start, WINDOW, "exact trailing microsecond width")
        audit.equal((view["mode"], view["layer"], view["directed"], view["actions"]),
                    ("events", "communication", True, ["reply", "utterance"]), "communication query")
        audit.check(start >= anchor - DAY, "whole event window has declared membership and coverage")
        grouped = {}
        interactions = [r for r in active if r["kind"] == "interaction.observed"]
        audit.number(len(interactions), 1, "one fixture event")
        for record in interactions:
            when = utc_value(record["occurred_at"])
            audit.number(when, anchor - 1_000_000, "event source time")
            if start <= when < cursor and record["payload"]["action"] in view["actions"]:
                pair = (record["payload"]["actor"], record["payload"]["target"])
                grouped.setdefault(pair, []).append(record)
                selected.add(record["record_id"])
        edges = [{"source": p[0], "target": p[1], "strength": len(values),
                  "evidence": sorted(r["record_id"] for r in values)} for p, values in sorted(grouped.items())]
        exposure = WINDOW
    audit.check(cursor >= anchor, "no query reversal before initial cursor")
    audit.check(all(e["source"] in persons and e["target"] in persons and e["source"] != e["target"] for e in edges),
                "selected endpoints are distinct eligible people")
    return {
        "directed": view["directed"], "bipartite": False, "persons": persons, "activities": [], "edges": edges,
        "weight_semantics": "observed_strength" if state_mode else "event_count",
        "population": {"policy": "eligible_at" if state_mode else "eligible_any_overlap", "eligible": persons,
                       "absent": [], "unknown": [], "unknown_intervals": {},
                       "exposure": {p: exposure for p in persons},
                       "exposure_unit": "point" if state_mode else "microsecond"},
        "coverage": {"complete": True, "actors": {p: "complete" for p in persons},
                     "evidence": sorted(r["record_id"] for r in coverage)},
        "provenance": {"selected_records": sorted(selected), "record_history": [
            {"record_id": r["record_id"], "fact_id": r["fact_id"], "source_system": r["source"]["system"],
             "operation": r["operation"], "supersedes": r["supersedes"], "kind": r["kind"], "ingest_seq": r["ingest_seq"]}
            for r in records]},
    }


def fingerprints(expected):
    graph = {k: expected[k] for k in ("directed", "bipartite", "persons", "activities", "weight_semantics")}
    graph["edges"] = [{"source": e["source"], "target": e["target"],
                       "strength": int(e["strength"]) if float(e["strength"]).is_integer() else e["strength"]}
                      for e in expected["edges"]]
    evidence = {"selected_records": expected["provenance"]["selected_records"],
                "coverage_evidence": expected["coverage"]["evidence"],
                "edge_evidence": [{k: e[k] for k in ("source", "target", "evidence")} for e in expected["edges"]],
                "annotation_summary": None}
    return {"graph": digest(graph), "population": digest(expected["population"]),
            "coverage": digest({k: expected["coverage"][k] for k in ("complete", "actors")}), "evidence": digest(evidence)}


def check_transition(audit, checkpoint, previous, expected, prior):
    transition, state, before = checkpoint["transition"], checkpoint["state"], previous["state"]
    audit.hashed(transition, "transition")
    for key, wanted in (("schema", "sociolab.temporal-tracking-transition.v1"), ("kind", "TEMPORAL_TRACKING_TRANSITION"),
                        ("profile", "receipt-source-time-tracking-v1"), ("status", "APPLIED"),
                        ("before_state_hash", before["content_hash"]), ("after_state_hash", state["content_hash"]),
                        ("before_sequence", before["sequence"]), ("after_sequence", state["sequence"]),
                        ("before_knowledge_cutoff", before["knowledge_cutoff"]), ("after_knowledge_cutoff", state["knowledge_cutoff"]),
                        ("before_cursor", before["cursor"]), ("after_cursor", state["cursor"]),
                        ("before_cursor_value", before["cursor_value"]), ("after_cursor_value", state["cursor_value"]),
                        ("registration_hash", state["registration_hash"])):
        audit.equal(transition[key], wanted, "transition binding " + key)
    tail = state["dataset"]["records"][before["knowledge_cutoff"]:]
    if tail:
        audit.equal(transition["cause"], "receipt_batch", "receipt cause")
        audit.equal((state["cursor"], state["cursor_value"]), (before["cursor"], before["cursor_value"]), "receipt holds cursor")
        audit.number(len(tail), 1, "fixture correction is one record")
    else:
        audit.equal(transition["cause"], "source_time_advance", "time cause")
        audit.equal(state["dataset"], before["dataset"], "time-only commit retains entire source journal")
        audit.equal(state["knowledge_cutoff"], before["knowledge_cutoff"], "time-only commit retains K")
        audit.check(state["cursor_value"] > before["cursor_value"], "time commit strictly advances")
    source = {"appended_record_count": len(tail),
              "new_assertion_count": sum(r["operation"] == "assert" and r["supersedes"] is None for r in tail),
              "revised_assertion_count": sum(r["operation"] == "assert" and r["supersedes"] is not None for r in tail),
              "retraction_count": sum(r["operation"] == "retract" for r in tail),
              "first_ingest_seq": tail[0]["ingest_seq"] if tail else None,
              "last_ingest_seq": tail[-1]["ingest_seq"] if tail else None,
              "recorded_at": tail[0]["recorded_at"] if tail else None,
              "appended_records_hash": digest(tail), "record_ids": [r["record_id"] for r in tail]}
    audit.equal(transition["source"], source, "source counters and zero-receipt time advance")
    audit.equal([r["view_id"] for r in transition["views"]], list(VIEW_IDS), "transition view order")
    summaries = []
    for index, row in enumerate(transition["views"]):
        old, new = prior[index], expected[index]
        old_fp, new_fp = fingerprints(old), fingerprints(new)
        flags = dict(zip(FLAGS, [old_fp[k] != new_fp[k] for k in ("graph", "population", "coverage", "evidence")]))
        audit.equal({k: row[k] for k in FLAGS}, flags, "independent semantic flags")
        audit.equal(row["before_fingerprints"], old_fp, "before fingerprints")
        audit.equal(row["after_fingerprints"], new_fp, "after fingerprints")
        for label, container in (("before", before), ("after", state)):
            snapshot = container["views"][index]["snapshot"]
            audit.equal(row[label + "_snapshot_hash"], snapshot["content_hash"], "transition snapshot hash")
            audit.equal(row[label + "_complete"], True, "fixture declared coverage remains complete")
        status = "OK" if any(flags[k] for k in FLAGS[:3]) else "NOT_RUN"
        audit.equal(row["comparison"]["status"], status, "comparison eligibility")
        if status == "NOT_RUN":
            audit.equal(row["comparison"], {"status": "NOT_RUN", "reason": "no_observable_change"}, "explicit comparison skip")
        else:
            report = row["comparison"]["report"]
            audit.equal(report["kind"], "DESCRIPTIVE_NETWORK_CHANGE", "comparison type")
            for label, container in (("before", before), ("after", state)):
                audit.equal(report["inputs"][label]["snapshot_hash"], container["views"][index]["snapshot"]["content_hash"],
                            "comparison input binding")
            old_edges = {(e["source"], e["target"]): e for e in old["edges"]}
            new_edges = {(e["source"], e["target"]): e for e in new["edges"]}
            shared = old_edges.keys() & new_edges.keys()
            counts = {"added": len(new_edges.keys() - old_edges.keys()), "removed": len(old_edges.keys() - new_edges.keys()),
                      "reweighted": sum(old_edges[p]["strength"] != new_edges[p]["strength"] for p in shared),
                      "evidence_changed": sum(old_edges[p]["strength"] == new_edges[p]["strength"] and
                                              old_edges[p]["evidence"] != new_edges[p]["evidence"] for p in shared)}
            for key, count in counts.items():
                audit.number(len(report["relations"][key]), count, "independent relation difference count")
            audit.number(report["relations"]["unchanged_edge_count"], len(shared) - counts["reweighted"] - counts["evidence_changed"],
                         "unchanged relation count")
            audit.number(report["relations"]["before_edge_count"], len(old_edges), "before edge count")
            audit.number(report["relations"]["after_edge_count"], len(new_edges), "after edge count")
            audit.equal(report["causal_effect_identified"], False, "comparison causal scope")
            audit.equal(report["future_prediction"], False, "comparison predictive scope")
        summaries.append({"view_id": row["view_id"], **flags, "comparison_status": status,
                          "person_count": len(new["persons"]), "edge_count": len(new["edges"])})
    audit.equal(transition["scope"]["causal_effect_identified"], False, "transition causal scope")
    return summaries


def check_receipt(audit, receipt, checkpoint, status, cause=None):
    state, transition = checkpoint["state"], checkpoint["transition"]
    updates = {} if status != "APPLIED" else {r["view_id"]: r for r in transition["views"]}
    views = []
    for row in state["views"]:
        snap, update = row["snapshot"], updates.get(row["view_id"])
        comparison = None if update is None else update["comparison"]
        views.append({"view_id": row["view_id"], "snapshot_hash": snap["content_hash"],
                      "person_count": len(snap["persons"]), "activity_count": len(snap["activities"]),
                      "edge_count": len(snap["edges"]), "complete": snap["coverage"]["complete"],
                      "changes": None if update is None else {k: update[k] for k in FLAGS},
                      "comparison_status": None if comparison is None else comparison["status"],
                      "comparison_reason": None if comparison is None else comparison.get("reason"),
                      "source_time": {k: snap["view"][k] for k in ("at", "start", "end") if k in snap["view"]}})
    wanted = {"kind": "NETWORK_TRACKING_RECEIPT", "status": status, "sequence": state["sequence"],
              "knowledge_cutoff": state["knowledge_cutoff"], "state_hash": state["content_hash"],
              "checkpoint_hash": checkpoint["content_hash"], "registration_hash": state["registration_hash"],
              "views": views, "fixed_source_views": False, "source_authenticity_verified": False,
              "causal_effect_identified": False, "cursor": state["cursor"], "cursor_value": state["cursor_value"],
              "source_time_unit": "microsecond", "view_templates_fixed": True, "transition_cause": cause}
    audit.equal(receipt, wanted, "receipt binds exact retained checkpoint and requested cause")


def authored_inputs(anchor):
    """Literal fixture expectations, independent of the production builder."""
    start, now = utc_text(anchor - DAY), utc_text(anchor)

    def record(identifier, kind, payload, *, at=start, interval=None, fact=None, supersedes=None, revision="initial"):
        return {"record_id": identifier, "fact_id": identifier if fact is None else fact,
                "operation": "assert", "supersedes": supersedes, "kind": kind,
                "occurred_at": at, "valid_interval": interval,
                "source": {"system": "invented-live-tracking", "record_id": identifier,
                           "revision": revision, "evidence_ref": "synthetic:" + identifier}, "payload": payload}

    persons = ["A", "B", "C", "D"]
    records = [record("declare-" + p, "entity.observed", {"entity_id": p, "entity_type": "person"}) for p in persons]
    records += [record("membership-" + p, "membership.changed",
                       {"actor": p, "population": "invented-team", "status": "present"}) for p in persons]
    records += [record("coverage-" + layer, "coverage.observed",
                       {"population": "invented-team", "layer": layer, "actors": persons, "status": "complete"},
                       interval=[start, None]) for layer in VIEW_IDS]
    for a, b in (("A", "B"), ("C", "D")):
        records.append(record("cooperation-" + a + "-" + b, "relation.changed",
                              {"layer": "cooperation", "source": a, "target": b, "directed": False, "strength": 1}))
    records.append(record("reply-A-C", "interaction.observed",
                          {"actor": "A", "target": "C", "action": "reply", "topic": "task"},
                          at=utc_text(anchor - 1_000_000)))
    dataset = {"schema": "sociolab.events.v1", "dataset_id": "synthetic-live-tracking-example", "origin": "synthetic",
               "source_revision": "invented-live-tracking-source-v1", "clock": {"kind": "utc"},
               "records": [{**r, "ingest_seq": i, "recorded_at": now} for i, r in enumerate(records, 1)]}
    state_view = {"schema": "sociolab.view.v1", "population": "invented-team", "layer": "cooperation",
                  "mode": "state", "directed": False, "actions": [], "roles": [], "topics": []}
    registration = {"schema": "sociolab.temporal-tracking-spec.v1", "initial_cursor": now,
                    "source_time_unit": "microsecond", "views": [
                        {"view_id": "cooperation", "view": state_view, "window_width": None, "analysis": {}},
                        {"view_id": "communication", "view": {**state_view, "layer": "communication", "mode": "events",
                                                               "directed": True, "actions": ["reply", "utterance"]},
                         "window_width": WINDOW, "analysis": {}}]}
    late = {"schema": "sociolab.network-tracking-batch.v1", "received_at": utc_text(anchor + 1_000_000), "records": [
        record("cooperation-A-D-correction", "relation.changed",
               {"layer": "cooperation", "source": "A", "target": "D", "directed": False, "strength": 1},
               fact="cooperation-A-B", supersedes="cooperation-A-B", revision="late-correction")]}
    return dataset, registration, late


def private_files(private):
    result = {}
    for path in sorted(private.rglob("*")):
        if path.is_symlink():
            raise ValueError("private case inputs must not contain symbolic links")
        if path.is_file():
            result[path.relative_to(private).as_posix()] = file_digest(path)
        elif not path.is_dir():
            raise ValueError("private case inputs must be regular files or directories")
    return result


def check_fixture(audit, initial, registration, late, metadata):
    audit.equal(metadata["schema"], "sociolab.live-tracking-fixture.v1", "fixture schema")
    audit.equal(metadata["origin"], "synthetic", "invented fixture origin")
    anchor = utc_value(metadata["anchor_utc"])
    audit.equal(metadata["anchor_utc"], utc_text(anchor), "canonical anchor UTC")
    for key, wanted in (("anchor_value", anchor), ("source_start_value", anchor - DAY),
                        ("event_value", anchor - 1_000_000), ("expiry_boundary_value", anchor + 2_000_000),
                        ("window_width_microseconds", WINDOW), ("invented_person_count", 4),
                        ("registered_view_count", 2), ("initial_knowledge_cutoff", 13),
                        ("after_late_knowledge_cutoff", 14), ("late_batch_record_count", 1)):
        audit.number(metadata[key], wanted, "fixture declared " + key)
    for key, wanted in (("source_start_utc", anchor - DAY), ("event_time", anchor - 1_000_000),
                        ("expiry_boundary_utc", anchor + 2_000_000), ("initial_cursor", anchor),
                        ("initial_received_at", anchor), ("late_received_at", anchor + 1_000_000)):
        audit.equal(metadata[key], utc_text(wanted), "fixture UTC binding " + key)
    audit.equal(metadata["source_time_unit"], "microsecond", "fixture UTC unit")
    audit.equal(metadata["expiry_condition"], "cursor_value > expiry_boundary_value", "inclusive lower window boundary")
    audit.equal(metadata["window_boundary"], "start_inclusive_end_exclusive", "window interpretation")
    expected = authored_inputs(anchor)
    for name, value, wanted in zip(("dataset", "registration", "late_batch"), (initial, registration, late), expected):
        audit.equal(value, wanted, "independent authored fixture " + name)
        audit.equal(metadata["input_content_hashes"][name], digest(value), "fixture canonical input hash")
    for key in ("real_data_used", "automatic_tick_count_predeclared", "live_checkpoint_count_predeclared",
                "source_authenticity_verified", "real_time_latency_guarantee", "causal_effect_identified",
                "empirical_prediction_validated"):
        audit.equal(metadata["scope"][key], False, "fixture qualification " + key)
    for key in ("engineering_fixture_only", "all_source_values_authored", "source_receipt_times_authored",
                "anchor_is_only_varying_input", "actual_timer_samples_and_process_evidence_retained_separately"):
        audit.equal(metadata["scope"][key], True, "fixture scope " + key)
    return anchor


def check_checkpoints(audit, initial, registration, late, metadata, anchor):
    normalized = deepcopy(registration)
    for row in normalized["views"]:
        row["analysis"] = deepcopy(ANALYSIS)
    store = audit.private / "store"
    for path in store.iterdir():
        audit.check(path.is_file() and not path.is_symlink(), "store entries are nonsymlink regular files")
        audit.check(path.name == ".writer.lock" or re.fullmatch(r"\d{8}\.json|\.pending-[0-9a-f]{32}\.json", path.name),
                    "only final checkpoint, recognized pending and lock files")
    files = sorted(path for path in store.iterdir() if re.fullmatch(r"\d{8}\.json", path.name))
    audit.check(len(files) >= 5, "case retains initial, correction and multiple time versions")
    audit.equal([p.name for p in files], [f"{i:08d}.json" for i in range(len(files))], "contiguous final checkpoint names")
    checkpoints = [audit.read(path) for path in files]
    corrected = deepcopy(initial)
    corrected["records"].append({**deepcopy(late["records"][0]), "ingest_seq": 14, "recorded_at": late["received_at"]})
    reconstructed, summaries = [], []
    for sequence, checkpoint in enumerate(checkpoints):
        audit.hashed(checkpoint, "checkpoint")
        audit.equal(checkpoint["schema"], "sociolab.network-tracking-checkpoint.v1", "checkpoint schema")
        audit.number(checkpoint["sequence"], sequence, "checkpoint sequence")
        audit.equal(checkpoint["previous_checkpoint_hash"], None if sequence == 0 else checkpoints[sequence - 1]["content_hash"],
                    "checkpoint predecessor hash")
        state = checkpoint["state"]
        audit.hashed(state, "state")
        audit.equal(state["schema"], "sociolab.temporal-tracking-state.v1", "unchanged temporal state schema")
        audit.equal(state["kind"], "TEMPORAL_TRACKING_STATE", "state kind")
        audit.equal(state["profile"], "receipt-source-time-tracking-v1", "existing temporal core profile")
        audit.number(state["sequence"], sequence, "state sequence")
        audit.equal(state["registration"], normalized, "immutable registration")
        audit.equal(state["registration_hash"], digest(normalized), "registration hash")
        cursor = utc_value(state["cursor"])
        audit.equal(state["cursor"], utc_text(cursor), "canonical exact UTC cursor")
        audit.number(state["cursor_value"], cursor, "UTC integer cursor binding")
        journal = state["dataset"]
        audit.check(len(journal["records"]) in (13, 14), "only initial or corrected receipt prefix")
        audit.equal(journal, initial if len(journal["records"]) == 13 else corrected, "full authored journal and receipt fields")
        audit.number(state["knowledge_cutoff"], len(journal["records"]), "exact state K")
        audit.equal(state["previous_state_hash"], None if sequence == 0 else checkpoints[sequence - 1]["state"]["content_hash"],
                    "state predecessor binding")
        if sequence:
            old = checkpoints[sequence - 1]["state"]["dataset"]["records"]
            audit.check(len(journal["records"]) >= len(old), "receipt prefix never shrinks")
            audit.equal(journal["records"][:len(old)], old, "complete receipt prefix byte-content preserved")
        audit.equal([r["view_id"] for r in state["views"]], list(VIEW_IDS), "retained view order")
        expected_views = []
        for row, declared in zip(state["views"], normalized["views"]):
            view = deepcopy(declared["view"])
            if view["mode"] == "state":
                view["at"] = state["cursor"]
            else:
                view.update(start=utc_text(cursor - declared["window_width"]), end=state["cursor"])
            snapshot = row["snapshot"]
            audit.hashed(snapshot, "snapshot")
            audit.equal(snapshot["schema"], "sociolab.snapshot.v1", "snapshot schema")
            expected = reconstruct(audit, journal, view, anchor)
            expected_views.append(expected)
            for key, wanted in expected.items():
                audit.equal(snapshot[key], wanted, "independent source replay " + key)
            audit.equal(snapshot["view"], view, "exact resolved source query")
            audit.number(snapshot["knowledge_cutoff"], len(journal["records"]), "snapshot K")
            wanted_dataset = {k: journal[k] for k in ("dataset_id", "origin", "source_revision", "clock")}
            wanted_dataset.update(content_hash=digest(journal), known_records_hash=digest(journal["records"]))
            audit.equal(snapshot["dataset"], wanted_dataset, "snapshot receipt-prefix hashes")
            audit.equal(snapshot["policy_hash"], digest({"view": declared["view"], "clock": journal["clock"]}), "view policy hash")
            audit.equal(row["fingerprints"], fingerprints(expected), "independent semantic fingerprints")
            if sequence == 0:
                audit.equal(snapshot["content_hash"], metadata["initial_snapshot_hashes"][row["view_id"]], "builder initial snapshot binding")
        reconstructed.append(expected_views)
        for key in ("historical_as_of_availability_verified", "content_hash_authenticates_author",
                    "content_hash_proves_external_timestamp", "causal_effect_identified", "live_subscription",
                    "automatic_event_time_advance", "receipt_batches_advance_source_time", "source_time_advances_append_receipts",
                    "source_time_cursor_is_receipt_time", "source_time_advance_proves_new_source_fact", "window_expiry_proves_real_relation_ended"):
            audit.equal(state["scope"][key], False, "unchanged temporal core scope " + key)
        if sequence:
            summaries.append({"sequence": sequence, "knowledge_cutoff": state["knowledge_cutoff"],
                              "cause": checkpoint["transition"]["cause"],
                              "views": check_transition(audit, checkpoint, checkpoints[sequence - 1], expected_views, reconstructed[-2])})
        else:
            audit.equal(checkpoint["transition"], None, "initial transition absent")
            audit.equal(journal, initial, "initial journal binding")
            audit.number(cursor, anchor, "initial cursor equals anchor")
    audit.equal(checkpoints[-1]["state"]["dataset"], corrected, "final corrected journal")
    audit.number(sum(s["cause"] == "receipt_batch" for s in summaries), 1, "only one accepted receipt batch")
    audit.number(sum(v["comparison_status"] == "OK" for s in summaries for v in s["views"]), 2,
                 "exactly event expiry and late state correction require comparisons")
    for index, key in ((0, "initial_view_expectations"), (-1, "after_expiry_and_late_view_expectations")):
        expected_counts = {view_id: {"person_count": len(v["persons"]), "edge_count": len(v["edges"]),
                                    "complete": v["coverage"]["complete"]}
                           for view_id, v in zip(VIEW_IDS, reconstructed[index])}
        audit.equal(metadata[key], expected_counts, "fixture aggregate source expectation")
    return checkpoints, summaries, {p.name: file_digest(p) for p in files}


def check_execution(audit, execution, protocol, checkpoints, receipts, late, metadata, hashes):
    audit.equal(execution["kind"], "LIVE_NETWORK_TRACKING_EXECUTION", "execution type")
    audit.equal(execution["status"], "PASS", "execution status")
    audit.equal(execution["anchor_utc"], metadata["anchor_utc"], "runtime anchor bound to fixture")
    audit.equal(execution["protocol_file_sha256"], file_digest(CASE / "protocol.json"), "execution frozen protocol binding")
    audit.equal(execution["source_hashes_before"], execution["source_hashes_after"], "executed sources unchanged")
    required_sources = {
        "src/sociolab/live_tracking.py", "src/sociolab/tracking_store.py", "src/sociolab/temporal_tracking.py",
        "src/sociolab/network_tracking.py", "src/sociolab/events.py", "src/sociolab/snapshots.py", "src/sociolab/cli.py",
        "examples/live-tracking/generate_fixture.py", str(Path(__file__).resolve().relative_to(REPOSITORY)),
        str((CASE / "protocol.json").relative_to(REPOSITORY)),
        str((CASE / "run_live_tracking_case.py").relative_to(REPOSITORY)),
    }
    audit.check(required_sources <= execution["source_hashes_before"].keys(), "execution seals all essential sources")
    for name, wanted in execution["source_hashes_before"].items():
        path = REPOSITORY / name
        audit.check(not Path(name).is_absolute() and path.resolve().is_relative_to(REPOSITORY), "source hash path stays in repository")
        audit.equal(file_digest(path), wanted, "current file equals frozen executed source")
    input_names = {"initial.events.json", "registration.json", "late.batch.json", "fixture-metadata.json"}
    audit.equal(set(execution["input_file_sha256"]), input_names, "exact runtime input inventory")
    for name, wanted in execution["input_file_sha256"].items():
        audit.equal(file_digest(audit.private / name), wanted, "private authored input unchanged")
    audit.equal(execution["input_file_sha256_after"], execution["input_file_sha256"], "runtime inputs retain their creation hashes")
    audit.equal(execution["private_artifact_hash_exclusions"], ["execution-private.json"], "only self-referential execution manifest excluded")
    artifacts = {p.name: file_digest(p) for p in audit.private.iterdir() if p.is_file() and p.name != "execution-private.json"}
    audit.equal(execution["private_artifact_creation_hashes"], artifacts, "all private nonstore artifacts retain creation bytes")
    audit.equal(execution["private_artifact_final_hashes"], artifacts, "complete final private nonstore inventory")
    audit.equal(execution["private_artifacts_unchanged"], True, "recorded private artifact invariance")
    encoded = (json.dumps(late, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    audit.equal((audit.private / "late-input.jsonl").read_bytes(), encoded, "retained exact input line serialization")
    audit.equal(execution["checkpoint_creation_hashes"], hashes, "all first-observed checkpoint bytes retained")
    audit.equal(execution["checkpoints_final_hashes"], hashes, "final checkpoint byte inventory")
    audit.equal(execution["competing_writer_rejected"], True, "retained competing-writer observation")
    audit.check(utc_value(execution["started_at"]) <= utc_value(execution["anchor_utc"]) < utc_value(execution["finished_at"]),
                "execution time bounds include runtime anchor")
    audit.check(type(execution["elapsed_seconds"]) in (int, float) and
                math.isfinite(execution["elapsed_seconds"]) and execution["elapsed_seconds"] > 0, "positive retained elapsed time")
    phases = execution["phases"]
    audit.equal(set(phases), {"idle_expiry", "partial_line", "correction", "sigkill", "restart", "duplicate", "eof"},
                "complete retained execution phase inventory")
    sessions = execution["sessions"]
    audit.number(len(sessions), 2, "one killed session and one EOF session")
    recovered_sequence = phases["sigkill"]["recovered_sequence"]
    audit.check(type(recovered_sequence) is int and 0 < recovered_sequence < len(checkpoints) - 1, "recovered head precedes restarted progress")
    next_index = 0
    for number, session in enumerate(sessions, 1):
        audit.number(session["index"], number, "session order")
        audit.number(session["receipt_start_index"], next_index, "contiguous session acknowledgment slices")
        end = session["receipt_end_index_exclusive"]
        audit.check(type(end) is int and next_index < end <= len(receipts), "nonempty valid session acknowledgment slice")
        audit.number(session["exit_code"], -9 if number == 1 else 0, "retained session exit code")
        audit.equal(session["termination"], "SIGKILL" if number == 1 else "EOF", "retained session termination")
        for stream, extension in (("stdout", "bin"), ("stderr", "txt"), ("stdin", "bin")):
            name = f"{stream}-session{number}.{extension}"
            audit.equal(session[stream + "_file"], name, "retained stream filename")
            audit.equal(session[stream + "_sha256"], file_digest(audit.private / name), "raw process stream binding")
        input_bytes = (audit.private / session["stdin_file"]).read_bytes()
        audit.equal(input_bytes, encoded, "each session received exactly the authored correction line")
        writes_name = f"stdin-session{number}-writes.json"
        audit.equal(session["stdin_writes_file"], writes_name, "input-write evidence filename")
        audit.equal(session["stdin_writes_sha256"], file_digest(audit.private / writes_name), "input-write evidence byte hash")
        writes = audit.read(audit.private / writes_name)
        audit.equal(writes, session["input_writes"], "public write ordering binds private evidence")
        lengths = [len(encoded) // 2, len(encoded) - len(encoded) // 2] if number == 1 else [len(encoded)]
        audit.number(len(writes), len(lengths), "exact split/retry write count")
        offset, last_finish = 0, utc_value(session["started_at"])
        for write_index, (write, length) in enumerate(zip(writes, lengths), 1):
            audit.number(write["index"], write_index, "ordered input writes")
            audit.number(write["offset"], offset, "contiguous input byte offsets")
            audit.number(write["byte_count"], length, "actual input chunk byte count")
            audit.number(write["requested_byte_count"], length, "requested chunk equals bytes delivered")
            audit.equal(write["write_succeeded"], True, "recorded successful input write")
            started, finished = utc_value(write["started_at"]), utc_value(write["finished_at"])
            audit.check(last_finish <= started <= finished <= utc_value(session["finished_at"]), "ordered retained input-write times")
            last_finish, offset = finished, offset + length
        audit.number(offset, len(input_bytes), "write log covers all retained stdin bytes")
        stdout = (audit.private / session["stdout_file"]).read_bytes()
        stderr = (audit.private / session["stderr_file"]).read_bytes()
        lines = stdout.split(b"\n")
        parsed = [json.loads(line.decode("utf-8"), object_pairs_hook=unique) for line in lines[:-1]]
        audit.equal(parsed, receipts[next_index:end], "complete raw stdout lines equal saved acknowledgments")
        audit.number(session["unterminated_stdout_bytes"], len(lines[-1]), "partial output bytes are not acknowledgments")
        audit.equal(stderr, b"", "successful case sessions have no stderr")
        if number == 2:
            audit.equal(lines[-1], b"", "normal EOF leaves no incomplete output")
        begun, finished = utc_value(session["started_at"]), utc_value(session["finished_at"])
        audit.check(utc_value(execution["started_at"]) <= begun < finished <= utc_value(execution["finished_at"]),
                    "session time range belongs to execution")
        current_sequence = 0 if number == 1 else recovered_sequence
        for receipt in parsed:
            status, cause, sequence = receipt["status"], receipt["transition_cause"], receipt["sequence"]
            audit.check(type(sequence) is int and 0 <= sequence < len(checkpoints), "acknowledged final checkpoint exists")
            if status == "APPLIED":
                audit.number(sequence, current_sequence + 1, "every acknowledged commit follows the session head")
                current_sequence = sequence
                audit.equal(checkpoints[sequence]["transition"]["cause"], cause, "acknowledged operation cause")
            elif status == "NO_NEW_RECORDS":
                audit.equal(cause, "receipt_batch", "duplicate acknowledgment cause")
                audit.number(sequence, current_sequence, "duplicate retains current head")
            else:
                audit.equal((status, cause), ("NO_TIME_ADVANCE", "source_time_advance"), "only supported time noop")
                audit.number(sequence, current_sequence, "equal-time acknowledgment retains current head")
            check_receipt(audit, receipt, checkpoints[sequence], status, cause)
            if cause == "source_time_advance":
                audit.check(begun <= receipt["cursor_value"] <= finished, "sampled cursor within retained process time range")
        before_close = session["observed_before_stdin_close_count"]
        audit.check(type(before_close) is int and 0 < before_close <= end - next_index, "acknowledgments observed while stdin open")
        next_index = end
    audit.number(next_index, len(receipts), "sessions cover all acknowledgments")

    def at(index):
        audit.check(type(index) is int and 0 <= index < len(receipts), "phase acknowledgment index")
        return receipts[index]

    idle = phases["idle_expiry"]
    expired = at(idle["receipt_index"])
    audit.equal(idle["expiry_boundary_utc"], metadata["expiry_boundary_utc"], "idle expiry boundary")
    audit.equal((expired["status"], expired["transition_cause"], expired["knowledge_cutoff"]),
                ("APPLIED", "source_time_advance", 13), "idle expiry with unchanged receipt cutoff")
    audit.check(expired["cursor_value"] > metadata["expiry_boundary_value"], "event is strictly past inclusive lower boundary")
    audit.number(expired["views"][1]["edge_count"], 0, "idle event expired")
    partial = phases["partial_line"]
    audit.number(partial["total_line_bytes"], len(encoded), "actual late batch serialized line length")
    audit.number(partial["first_chunk_bytes"], len(encoded) // 2, "predeclared partial input split")
    audit.check(0 < partial["first_chunk_bytes"] < len(encoded) - 1 and b"\n" not in encoded[:partial["first_chunk_bytes"]],
                "first chunk contains no complete JSONL request")
    partial_start, partial_finish = utc_value(partial["started_at"]), utc_value(partial["finished_at"])
    first_writes = sessions[0]["input_writes"]
    audit.check(expired["cursor_value"] <= utc_value(first_writes[0]["started_at"]), "idle timer observation precedes any stdin bytes")
    audit.check(utc_value(first_writes[0]["finished_at"]) <= partial_start <= partial_finish <= utc_value(first_writes[1]["started_at"]),
                "partial-line observations lie strictly between the two input writes")
    progressed = partial["observed_receipt_indices"]
    audit.number(len(progressed), 2, "two timer observations while the line is incomplete")
    audit.check(idle["receipt_index"] < partial["sent_after_receipt_count"] <= progressed[0] < progressed[1],
                "partial input observations follow idle phase")
    for index in progressed:
        receipt = at(index)
        audit.equal((receipt["status"], receipt["transition_cause"], receipt["knowledge_cutoff"]),
                    ("APPLIED", "source_time_advance", 13), "partial input permits pure time progress")
        audit.check(partial_start <= receipt["cursor_value"] <= partial_finish, "observed sample belongs to partial-line period")
    correction_index = phases["correction"]["receipt_index"]
    correction = at(correction_index)
    audit.check(progressed[1] < correction_index < sessions[0]["receipt_end_index_exclusive"], "completed batch follows partial period")
    audit.equal((correction["status"], correction["transition_cause"], correction["knowledge_cutoff"]),
                ("APPLIED", "receipt_batch", 14), "one late correction was accepted")
    audit.equal(correction["views"][0]["changes"]["observed_graph_changed"], True, "correction changes cooperation graph")
    for receipt in receipts[:correction_index]:
        audit.number(receipt["knowledge_cutoff"], 13, "no partial request appended a record")
    for receipt in receipts[correction_index:]:
        audit.number(receipt["knowledge_cutoff"], 14, "accepted correction is never undone or duplicated")
    killed = phases["sigkill"]
    observed_index = killed["last_observed_receipt_index"]
    observed = at(observed_index)
    audit.check(correction_index < observed_index < sessions[0]["receipt_end_index_exclusive"], "post-correction automatic advance precedes kill")
    audit.equal((observed["status"], observed["transition_cause"]), ("APPLIED", "source_time_advance"), "last prekill observation is automatic progress")
    audit.number(sessions[0]["observed_before_stdin_close_count"], observed_index + 1, "prekill observation count")
    audit.check(observed["cursor_value"] <= utc_value(killed["killed_at"]) <= utc_value(sessions[0]["finished_at"]), "retained kill time bounds")
    recovered = checkpoints[recovered_sequence]
    audit.number(killed["recovered_knowledge_cutoff"], 14, "recovered K")
    audit.equal(killed["recovered_cursor"], recovered["state"]["cursor"], "recovered cursor binding")
    audit.equal(killed["recovered_checkpoint_hash"], recovered["content_hash"], "recovered checkpoint binding")
    first_acks = {r["sequence"] for r in receipts[:sessions[0]["receipt_end_index_exclusive"]] if r["status"] == "APPLIED"}
    audit.check(first_acks and max(first_acks) <= recovered_sequence, "all acknowledged commits survive restart")
    unacknowledged = set(range(1, recovered_sequence + 1)) - first_acks
    audit.equal(unacknowledged, set(range(max(first_acks) + 1, recovered_sequence + 1)), "unacknowledged published versions form a time-only tail")
    audit.number(killed["unacknowledged_published_count"], len(unacknowledged), "published time tail count")
    for sequence in unacknowledged:
        audit.equal(checkpoints[sequence]["transition"]["cause"], "source_time_advance", "unacknowledged published tail is time-only")
    restarted_index = phases["restart"]["first_auto_receipt_index"]
    restarted = at(restarted_index)
    audit.check(sessions[1]["receipt_start_index"] <= restarted_index, "restart observation belongs to second session")
    audit.equal((restarted["status"], restarted["transition_cause"]), ("APPLIED", "source_time_advance"), "restart automatic advance")
    audit.check(restarted["cursor_value"] > recovered["state"]["cursor_value"], "restart advances beyond saved cursor")
    audit.check(restarted["cursor_value"] <= utc_value(sessions[1]["input_writes"][0]["started_at"]), "restart progresses before duplicate delivery")
    duplicate_index = phases["duplicate"]["receipt_index"]
    duplicate = at(duplicate_index)
    audit.check(restarted_index < duplicate_index < phases["eof"]["sent_after_receipt_count"] <= len(receipts), "retry and EOF phase order")
    audit.equal((duplicate["status"], duplicate["transition_cause"], duplicate["knowledge_cutoff"]),
                ("NO_NEW_RECORDS", "receipt_batch", 14), "exact correction retry stays idempotent")
    audit.number(sessions[1]["observed_before_stdin_close_count"], phases["eof"]["sent_after_receipt_count"] - sessions[1]["receipt_start_index"],
                 "normal EOF pre-close acknowledgment count")
    audit.equal(receipts[-1]["checkpoint_hash"], checkpoints[-1]["content_hash"], "normal EOF acknowledged final committed version")
    check_receipt(audit, audit.read(audit.private / "initial-receipt.json"), checkpoints[0], "INITIALIZED")
    check_receipt(audit, audit.read(audit.private / "restart-inspect.json"), recovered, "INSPECTED")
    check_receipt(audit, audit.read(audit.private / "final-inspect.json"), checkpoints[-1], "INSPECTED")
    return len(unacknowledged)


def check_protocol(audit, protocol):
    audit.equal(protocol["schema"], "sociolab.live-tracking-case-protocol.v1", "protocol schema")
    audit.equal(protocol["kind"], "FROZEN_SYNTHETIC_LIVE_TRACKING_PROTOCOL", "protocol kind")
    audit.equal(protocol["origin"], "synthetic", "protocol origin")
    audit.equal(protocol["fixture_generator_sha256"], file_digest(REPOSITORY / "examples/live-tracking/generate_fixture.py"),
                "protocol binds exact fixture builder")
    audit.equal(protocol["independent_checker_sha256"], file_digest(Path(__file__)), "checker frozen before case")
    audit.number(protocol["interval_ms"], 1000, "predeclared live interval")
    audit.equal(protocol["source_time_unit"], "microsecond", "protocol UTC microseconds")
    audit.equal(protocol["clock_policy"], {
        "wall_clock_sample": "time.time_ns() // 1000", "scheduling_clock": "time.monotonic_ns()",
        "schedule": "completion_plus_interval", "first_tick": "one_interval_after_startup_replay_and_validation",
        "startup_validation_advances_cursor": False, "backward_clock": "reject_without_commit",
        "equal_clock": "NO_TIME_ADVANCE", "missed_intervals": "coalesce_to_one_actual_sample",
        "stdin_manual_advances_allowed": False, "observed_eof_stops_timers": True,
    }, "frozen clock policy")
    fixture = protocol["fixture"]
    for key, expected in (("source_start_offset_microseconds", -DAY), ("event_offset_microseconds", -1_000_000),
                          ("window_width_microseconds", WINDOW), ("initial_received_at_offset_microseconds", 0),
                          ("late_received_at_offset_microseconds", 1_000_000), ("invented_person_count", 4),
                          ("registered_view_count", 2), ("initial_knowledge_cutoff", 13), ("final_knowledge_cutoff", 14),
                          ("receipt_appends_after_initialization", 1), ("duplicate_receipt_requests", 1)):
        audit.number(fixture[key], expected, "predeclared fixture " + key)
    audit.equal(fixture["expiry_condition"], "cursor > anchor + 2000000_microseconds", "predeclared exact expiry")
    audit.equal(fixture["automatic_tick_count_predeclared"], False, "actual tick count is measured")
    audit.equal(fixture["checkpoint_count_predeclared"], False, "actual checkpoint count is measured")
    execution = protocol["execution"]
    audit.equal(execution["stage_order"], ["idle_expiry", "partial_line", "correction", "sigkill", "restart", "duplicate", "eof"],
                "predeclared execution order")
    for key, expected in (("actual_cli_subprocesses_required", 2), ("partial_input_new_time_commits_required", 2),
                          ("first_exit_code", -9), ("second_exit_code", 0)):
        audit.number(execution[key], expected, "predeclared execution " + key)
    for key in ("idle_phase_has_no_stdin_bytes", "partial_phase_selected_cursors_at_or_after_send_completion",
                "timeouts_are_test_guards_not_latency_guarantees", "allow_unacknowledged_published_time_tail_after_sigkill",
                "restart_must_retain_all_acknowledged_versions", "second_writer_must_be_rejected",
                "all_observed_checkpoint_file_hashes_must_remain_unchanged", "raw_stdout_and_stderr_retained_privately",
                "private_store_outside_repository", "existing_outputs_never_overwritten"):
        audit.equal(execution[key], True, "predeclared evidence requirement " + key)
    audit.equal(execution["automatic_retry_or_fixture_tuning"], False, "no adaptive case tuning")
    for key in ("checkpoint_alone_authenticates_driver_origin", "exact_actual_timer_samples_known_before_execution",
                "source_cursor_is_completeness_watermark", "external_source_subscription", "automatic_forecast_trigger",
                "latency_sla_validated", "exactly_once_output_delivery_claimed", "physical_power_loss_experiment",
                "source_authenticity_verified", "empirical_prediction_validated", "causal_effect_identified"):
        audit.equal(protocol["scope"][key], False, "protocol scope " + key)
    for key in ("all_social_values_invented", "source_and_receipt_times_authored_relative_to_anchor",
                "actual_local_UTC_driver", "core_receives_explicit_advance_commands"):
        audit.equal(protocol["scope"][key], True, "protocol positive scope " + key)


def aggregate_only(value):
    forbidden = {"actors", "persons", "edges", "records", "record_ids", "payload", "predictions", "behavior",
                 "targets", "selected_records", "record_history"}
    if type(value) is dict:
        if forbidden.intersection(value):
            raise ValueError("public evidence contains individual source fields")
        for item in value.values():
            aggregate_only(item)
    elif type(value) is list:
        for item in value:
            aggregate_only(item)


def check_case(private):
    audit = Audit(private)
    originals = private_files(private)
    protocol = audit.read(CASE / "protocol.json")
    check_protocol(audit, protocol)
    initial = audit.read(private / "initial.events.json")
    registration = audit.read(private / "registration.json")
    late = audit.read(private / "late.batch.json")
    metadata = audit.read(private / "fixture-metadata.json")
    anchor = check_fixture(audit, initial, registration, late, metadata)
    checkpoints, summaries, checkpoint_hashes = check_checkpoints(audit, initial, registration, late, metadata, anchor)
    receipts = audit.read(private / "receipts.json")
    audit.check(type(receipts) is list and bool(receipts), "saved ordinary acknowledgment list")
    execution = audit.read(private / "execution-private.json")
    unacknowledged = check_execution(audit, execution, protocol, checkpoints, receipts, late, metadata, checkpoint_hashes)
    public_execution = audit.read(CASE / "execution.json")
    audit.equal(public_execution, execution, "public/private execution equality")
    audit.equal(file_digest(CASE / "execution.json"), file_digest(private / "execution-private.json"), "public/private execution byte equality")
    public = audit.read(CASE / "report.json")
    final = checkpoints[-1]["state"]
    counts = {
        "checkpoint_count": len(checkpoints), "observed_receipt_count": len(receipts),
        "applied_time_ack_count": sum(r["status"] == "APPLIED" and r["transition_cause"] == "source_time_advance" for r in receipts),
        "applied_receipt_ack_count": sum(r["status"] == "APPLIED" and r["transition_cause"] == "receipt_batch" for r in receipts),
        "no_new_records_count": sum(r["status"] == "NO_NEW_RECORDS" for r in receipts),
        "no_time_advance_count": sum(r["status"] == "NO_TIME_ADVANCE" for r in receipts),
        "initial_knowledge_cutoff": 13, "final_knowledge_cutoff": 14, "final_sequence": len(checkpoints) - 1,
        "interval_ms": 1000, "window_width_microseconds": WINDOW, "registered_view_count": 2,
        "unacknowledged_published_count": unacknowledged, "partial_input_timer_progress_count": 2,
    }
    for key, expected in counts.items():
        audit.number(public[key], expected, "public aggregate " + key)
    audit.number(counts["applied_receipt_ack_count"], 1, "exactly one late correction acknowledgment")
    audit.number(counts["no_new_records_count"], 1, "exactly one duplicate acknowledgment")
    audit.number(counts["applied_time_ack_count"] + counts["applied_receipt_ack_count"] + unacknowledged,
                 len(checkpoints) - 1, "every committed version has an ACK or declared killed time tail")
    audit.equal(public["kind"], "SYNTHETIC_LIVE_NETWORK_TRACKING_CASE", "public case kind")
    audit.equal(public["status"], "PASS", "public case status")
    audit.equal(public["origin"], "synthetic", "public invented source scope")
    audit.equal(public["source_time_unit"], "microsecond", "public UTC unit")
    audit.equal(public["final_cursor"], final["cursor"], "public final cursor")
    audit.equal(public["final_checkpoint_hash"], checkpoints[-1]["content_hash"], "public final checkpoint")
    audit.equal(public["protocol_file_sha256"], file_digest(CASE / "protocol.json"), "public protocol binding")
    audit.equal(public["receipts"], receipts, "public ordinary summaries equal complete private ACKs")
    for key, index in (("initial_view_edge_counts", 0), ("final_view_edge_counts", -1)):
        wanted = {v["view_id"]: len(v["snapshot"]["edges"]) for v in checkpoints[index]["state"]["views"]}
        audit.equal(public[key], wanted, "public source-reconstructed edge counts")
    for key in ("recovery_after_sigkill", "competing_writer_rejected", "all_retained_checkpoint_bytes_unchanged"):
        audit.equal(public[key], True, "public recorded execution claim " + key)
    audit.equal(public["scope"], {
        "engineering_fixture_only": True, "real_social_observations_used": False,
        "actual_local_wall_clock_driver": True, "source_timestamps_invented_relative_to_anchor": True,
        "receipt_timestamps_invented": True, "source_authenticity_verified": False,
        "source_cursor_is_completeness_watermark": False, "external_source_subscription": False,
        "physical_power_loss_experiment": False, "latency_sla_validated": False,
        "exactly_once_output_delivery_claimed": False, "empirical_prediction_validated": False,
        "causal_effect_identified": False,
    }, "public scope does not promote engineering evidence into research validation")
    for item in (public, public_execution):
        aggregate_only(item)
    audit.equal(private_files(private), originals, "checker leaves every private file unchanged, including pending files")
    for label, wanted in audit.inputs.items():
        path = private / label.removeprefix("private/") if label.startswith("private/") else REPOSITORY / label.removeprefix("repository/")
        audit.equal(file_digest(path), wanted, "checker leaves all parsed public/private input bytes unchanged")
    time_count = sum(row["cause"] == "source_time_advance" for row in summaries)
    qualified = sum(v["comparison_status"] == "OK" for row in summaries for v in row["views"])
    pending_count = sum(bool(re.fullmatch(r"store/\.pending-[0-9a-f]{32}\.json", name)) for name in originals)
    report = {
        "schema": "sociolab.independent-live-tracking-check.v1", "kind": "INDEPENDENT_LIVE_TRACKING_CHECK", "status": "PASS",
        "method": "stdlib_fixture_UTC_source_reconstruction_checkpoint_axes_and_retained_process_bindings",
        "counts": {"checks": audit.checks, "numeric_comparisons": audit.numeric_checks,
                   "checkpoints": len(checkpoints), "acknowledgments": len(receipts),
                   "applied_receipt_batches": 1, "applied_time_advances": time_count,
                   "no_new_records": counts["no_new_records_count"], "no_time_advance": counts["no_time_advance_count"],
                   "unacknowledged_published_time_versions": unacknowledged, "retained_pending_files": pending_count,
                   "final_knowledge_cutoff": 14, "registered_views": 2, "independently_reconstructed_snapshots": 2 * len(checkpoints),
                   "qualified_comparison_reports": qualified, "partial_input_timer_observations": 2,
                   "private_files_unchanged": len(originals)},
        "numeric_comparison": {"max_absolute_error": audit.max_error, "comparison": "exact integer microseconds, counts and source values"},
        "checkpoint_file_sha256": checkpoint_hashes, "private_file_sha256": originals, "parsed_input_file_sha256": audit.inputs,
        "protocol_file_sha256": file_digest(CASE / "protocol.json"), "checker_sha256": file_digest(Path(__file__)),
        "scope": {"fixture_specific_UTC_source_reconstruction": True, "standard_library_only": True,
                  "sociolab_imported": False, "graph_library_imported": False, "tracker_executed_by_checker": False,
                  "community_algorithms_independently_validated": False, "model_fitted_or_refitted": False,
                  "process_claims_bound_to_retained_execution_records": True, "process_independently_reobserved": False,
                  "actual_timer_count_predeclared": False, "unacknowledged_published_time_tail_allowed": True,
                  "pending_files_preserved_not_promoted": True, "output": "aggregate_only",
                  "all_social_values_authored": True, "source_receipt_times_authored": True,
                  "wall_clock_origin_authenticated": False, "core_scope_retained_unchanged": True,
                  "window_expiry_proves_real_relation_ended": False, "source_cursor_is_completeness_watermark": False,
                  "real_time_latency_validated": False, "source_authenticity_verified": False,
                  "historical_as_of_availability_verified": False, "external_source_subscription": False,
                  "empirical_forecast_validated": False, "causal_effect_identified": False,
                  "hashes_authenticate_sources_or_times": False},
        "runtime": {"python": platform.python_version(), "dependency": "Python standard library"},
    }
    aggregate_only(report)
    return {**report, "content_hash": digest(report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    private, output = args.private_root.resolve(), args.report.resolve()
    if not private.is_dir() or private == REPOSITORY or private.is_relative_to(REPOSITORY) or REPOSITORY.is_relative_to(private):
        parser.error("private root must be an existing directory outside and not containing the repository")
    if args.report.exists() or args.report.is_symlink() or output.is_relative_to(private):
        parser.error("output must be new and outside the protected private case")
    report = check_case(private)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "counts": report["counts"],
                      "numeric_comparison": report["numeric_comparison"], "content_hash": report["content_hash"]}, sort_keys=True))


if __name__ == "__main__":
    main()

