#!/usr/bin/env python3
"""Check the fixed synthetic journal case independently, without fitting.

Only the standard library is used. Source batches, receipt prefixes, fact heads,
identity resolution, point measurements and the fixture's simple network states
are reconstructed independently. Saved predictions supply the error arithmetic;
no coefficient, graph algorithm or forecasting model is estimated here.
The checker is deliberately limited to this invented ticks-clock fixture.
It emits aggregates and hashes only and refuses to overwrite existing output.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import sys


REPOSITORY = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
EXAMPLES = REPOSITORY / "examples/journal-forecast"
PROTOCOL_SHA256 = "b05f754cded7fd2f848125c6f5fee298843b0bc6377e67bd76858bbe7f317350"
STAGES = ("initial", "late_history", "target", "revised_target")
MODELS = ("persistence", "own_lag_ols", "network_lag_ols")
PROFILE = "journal-receipt-prefix-point-behavior-v1"
FORECAST_PROFILE = "own-lag-outgoing-gap-ols-v1"
ATOL = RTOL = 1e-12
BRIDGE_SCOPE = {
    "receipt_prefix_enforced": True, "historical_as_of_availability_verified": False,
    "receipt_timestamps_externally_authenticated": False,
    "forecast_issued_before_target_observation_verified": False, "live_subscription": False,
    "models_fitted_by_bridge": False,
    "behavior_selection": "one_active_point_measurement_per_actor_at_exact_source_time",
    "behavior_forward_filled": False, "behavior_imputed": False, "actor_dropping": False,
    "network_selection": "complete_directed_binary_state_at_each_declared_history_time",
    "network_source_system_filter": None, "population_boundary_qualified": False,
    "single_origin_as_known_profile": True, "cross_cutoff_immutable_prefix_compatibility_established": False,
    "content_hash_authenticates_author": False, "content_hash_proves_prospective_timestamp": False,
    "contains_private_actor_records": True, "causal_effect_identified": False,
    "empirical_forecast_validated": False,
}
FORECAST_SCOPE = {
    "analysis": "retrospective_temporal_holdout", "forecast_uses_history_prefix_only": True,
    "target_observations_consumed_at_creation": False, "target_network_consumed": False,
    "neighbor_direction": "outgoing_successors_in_each_known_wave", "no_outgoing_neighbor_gap": 0.0,
    "no_outgoing_neighbor_convention": "structural_zero_gap_not_missing_value_imputation",
    "actor_dropping": False, "behavior_imputation": False, "preprocessing_fitted": False,
    "historical_receipt_availability": "unknown", "historical_as_of_availability_verified": False,
    "population_boundary_qualified": False,
    "fixed_roster_contract": "same_supplied_actors_in_every_history_wave_and_target",
    "wave_time_unit": "wave_index_not_calendar_duration", "ordinal_values_treated_as_numeric": True,
    "scale_endpoints_required_in_history": False, "condition_number_threshold": None,
    "null_condition_number": "zero_smallest_singular_value_or_nonfinite_ratio",
    "coefficient_inference": False, "probabilistic_forecast": False, "calibration_status": "NOT_ESTIMATED",
    "prediction_intervals": None, "causal_effect_identified": False, "empirical_forecast_validated": False,
    "content_hash_authenticates_author": False, "content_hash_proves_prospective_timestamp": False,
    "prediction_artifact_contains_private_actor_records": True,
}


class CheckError(ValueError):
    """Fixed error codes only: never include private input values."""


def require(condition, code):
    if not condition:
        raise CheckError(code)


def digest(raw):
    return sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value):
    return "sha256:" + digest(canonical(value))


def hashed(value, field="content_hash"):
    return {**value, field: content_hash(value)}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def invalid_constant(_value):
    raise CheckError("NONFINITE_JSON_VALUE")


def load(path):
    raw = path.read_bytes()
    require(0 < len(raw) < 10_000_000, "INPUT_SIZE")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    canonical(value)
    return value, raw


class Audit:
    def __init__(self):
        self.count = 0
        self.numeric_count = 0
        self.max_absolute_error = 0.0

    def exact(self, actual, expected, label):
        self.count += 1
        require(canonical(actual) == canonical(expected), label)

    def condition(self, valid, label):
        self.count += 1
        require(valid, label)

    def compare(self, actual, expected, label):
        # Only public score structures reach this recursive comparison. Private
        # evidence is checked atomically, so actor keys cannot enter error codes.
        if type(expected) is dict:
            self.condition(type(actual) is dict and set(actual) == set(expected), label + ".FIELDS")
            for key in sorted(expected):
                self.compare(actual[key], expected[key], label + "." + key)
        elif type(expected) is float:
            self.condition(type(actual) in (int, float) and math.isfinite(actual), label + ".FINITE")
            error = abs(actual - expected)
            self.numeric_count += 1
            self.max_absolute_error = max(self.max_absolute_error, error)
            self.condition(math.isclose(actual, expected, abs_tol=ATOL, rel_tol=RTOL), label + ".VALUE")
        else:
            self.exact(actual, expected, label)


def prefix(journal, cutoff):
    """Independently replay source-scoped linear fact histories and identities."""
    require(type(cutoff) is int and 0 < cutoff <= len(journal["records"]), "PREFIX_CUTOFF")
    records = journal["records"][:cutoff]
    heads, seen, previous_time = {}, set(), None
    for seq, record in enumerate(records, 1):
        require(record["ingest_seq"] == seq and record["record_id"] not in seen, "RECEIPT_SEQUENCE")
        received = datetime.fromisoformat(record["recorded_at"].replace("Z", "+00:00"))
        require(previous_time is None or previous_time <= received, "RECEIPT_TIME_ORDER")
        previous_time = received
        fact = (record["source"]["system"], record["fact_id"])
        predecessor = heads.get(fact)
        require(record["supersedes"] == (None if predecessor is None else predecessor["record_id"]), "FACT_CHAIN")
        require(record["operation"] in ("assert", "retract"), "FACT_OPERATION")
        require(predecessor is None or predecessor["kind"] == record["kind"], "FACT_KIND")
        require(record["operation"] != "retract" or (predecessor is not None and record["payload"] is None), "RETRACTION")
        heads[fact] = record
        seen.add(record["record_id"])
    active = sorted((record for record in heads.values() if record["operation"] == "assert"),
                    key=lambda record: record["ingest_seq"])
    entities, direct = {}, {}
    identity_evidence = []
    for record in active:
        payload = record["payload"]
        if record["kind"] == "entity.observed":
            require(payload["entity_id"] not in entities, "ENTITY_UNIQUENESS")
            entities[payload["entity_id"]] = payload["entity_type"]
            identity_evidence.append(record)
        elif record["kind"] == "identity.mapped":
            require(payload["alias"] not in direct, "IDENTITY_UNIQUENESS")
            direct[payload["alias"]] = payload["canonical"]
            identity_evidence.append(record)
    identities = {}
    for alias in direct:
        current, visited = alias, set()
        while current in direct:
            require(current not in visited, "IDENTITY_CYCLE")
            visited.add(current)
            following = direct[current]
            require(current in entities and following in entities
                    and entities[current] == entities[following], "IDENTITY_ENTITY_TYPE")
            current = following
        identities[alias] = current
    identity_state = {"entities": entities, "identity_map": identities, "entity_identity_evidence": identity_evidence}
    envelope = {key: value for key, value in journal.items() if key != "records"}
    proof = {
        "knowledge_cutoff": cutoff, "prefix_envelope": envelope,
        "prefix_content_hash": content_hash({**envelope, "records": records}),
        "prefix_records_hash": content_hash(records), "receipt_records": records,
        "active_record_ids": [record["record_id"] for record in active],
        **identity_state, "identity_state_hash": content_hash(identity_state),
    }
    return proof, active


def point_behavior(proof, active, spec, when, issuance=None):
    selected = {actor: [] for actor in spec["actors"]}
    for record in active:
        if record["kind"] != "actor.attribute.observed":
            continue
        payload = record["payload"]
        if (record["source"]["system"] != spec["behavior_source"]["system"]
                or payload["name"] != spec["behavior_source"]["attribute"] or record["occurred_at"] != when):
            continue
        require(record["valid_interval"] is None, "FIXTURE_BEHAVIOR_POINT")
        raw = payload["actor"]
        actor = proof["identity_map"].get(raw, raw)
        require(actor in selected and proof["entities"].get(raw) == "person", "FIXTURE_BEHAVIOR_ROSTER")
        if issuance is not None:
            require(issuance["entities"].get(raw) == "person"
                    and issuance["identity_map"].get(raw, raw) == actor, "TARGET_IDENTITY_CHANGED")
        value = payload["value"]
        require(type(value) is int and 0 <= value <= 5, "FIXTURE_BEHAVIOR_SCALE")
        selected[actor].append({"record": record, "resolved_actor": actor})
    require(all(len(rows) == 1 for rows in selected.values()), "POINT_BEHAVIOR_UNIQUENESS")
    evidence = [selected[actor][0] for actor in spec["actors"]]
    return {item["resolved_actor"]: item["record"]["payload"]["value"] for item in evidence}, evidence


def snapshot_reference(proof, active, spec, at):
    """Reference only this fixture: persistent membership, point binary relations.

    This is not a replacement snapshot implementation or a graph algorithm.
    Other relation/membership kinds, populations and clocks are unsupported here.
    """
    identities = proof["identity_map"]
    resolve = lambda actor: identities.get(actor, actor)
    people = sorted({resolve(actor) for actor, kind in proof["entities"].items() if kind == "person"})
    require(people == spec["actors"], "FIXTURE_SNAPSHOT_ROSTER")
    selected, coverage = set(), []
    for actor in people:
        memberships = [record for record in active if record["kind"] == "membership.changed"
                       and record["payload"]["population"] == spec["population"]
                       and resolve(record["payload"]["actor"]) == actor and record["occurred_at"] <= at]
        require(len(memberships) == 1 and memberships[0]["payload"]["status"] == "present", "FIXTURE_MEMBERSHIP")
        selected.add(memberships[0]["record_id"])
    for record in active:
        if record["kind"] != "coverage.observed":
            continue
        payload, interval = record["payload"], record["valid_interval"]
        if payload["population"] == spec["population"] and payload["layer"] == spec["layer"] and interval[0] <= at < interval[1]:
            require(payload["status"] == "complete" and sorted(resolve(actor) for actor in payload["actors"]) == people,
                    "FIXTURE_COVERAGE")
            coverage.append(record["record_id"])
    require(len(coverage) == 1, "FIXTURE_COVERAGE_UNIQUENESS")
    selected.update(coverage)
    edges, pairs = [], set()
    for record in active:
        if record["kind"] not in ("relation.observed", "relation.changed"):
            continue
        require(record["kind"] == "relation.observed" and record["valid_interval"] is None, "FIXTURE_RELATION_KIND")
        payload = record["payload"]
        if payload["layer"] != spec["layer"] or record["occurred_at"] != at:
            continue
        source, target = resolve(payload["source"]), resolve(payload["target"])
        require(payload["directed"] is True and source in people and target in people
                and source != target and payload["strength"] in (0, 1), "FIXTURE_RELATION_DOMAIN")
        require((source, target) not in pairs, "FIXTURE_RELATION_UNIQUENESS")
        pairs.add((source, target))
        selected.add(record["record_id"])
        if payload["strength"] == 1:
            edges.append({"source": source, "target": target, "strength": 1, "evidence": [record["record_id"]]})
    edges.sort(key=lambda edge: (edge["source"], edge["target"]))
    envelope = proof["prefix_envelope"]
    view = {"schema": "sociolab.view.v1", "population": spec["population"], "layer": spec["layer"],
            "mode": "state", "directed": True, "at": at, "actions": [], "roles": [], "topics": []}
    history = [{"record_id": record["record_id"], "fact_id": record["fact_id"],
                "source_system": record["source"]["system"], "operation": record["operation"],
                "supersedes": record["supersedes"], "kind": record["kind"], "ingest_seq": record["ingest_seq"]}
               for record in proof["receipt_records"]]
    return hashed({
        "schema": "sociolab.snapshot.v1",
        "dataset": {key: envelope[key] for key in ("dataset_id", "origin", "source_revision", "clock")} | {
            "content_hash": proof["prefix_content_hash"], "known_records_hash": proof["prefix_records_hash"]},
        "view": view, "knowledge_cutoff": proof["knowledge_cutoff"], "directed": True, "bipartite": False,
        "persons": people, "activities": [], "edges": edges,
        "coverage": {"complete": True, "actors": {actor: "complete" for actor in people}, "evidence": sorted(coverage)},
        "population": {"policy": "eligible_at", "eligible": people, "absent": [], "unknown": [],
                       "exposure": {actor: 1 for actor in people}, "exposure_unit": "point", "unknown_intervals": {}},
        "provenance": {"selected_records": sorted(selected), "record_history": history},
        "weight_semantics": "observed_strength",
        "policy_hash": content_hash({"view": {key: value for key, value in view.items() if key != "at"},
                                     "clock": envelope["clock"]}),
    })


def history_reference(journal, spec):
    proof, active = prefix(journal, spec["knowledge_cutoff"])
    manifests, waves = [], []
    for wave in spec["waves"]:
        snapshot = snapshot_reference(proof, active, spec, wave["at"])
        behavior, evidence = point_behavior(proof, active, spec, wave["at"])
        manifest = hashed({
            "time_index": wave["time_index"], "at": wave["at"], "parsed_at": wave["at"], "source_time_unit": "tick",
            "knowledge_cutoff": spec["knowledge_cutoff"], "prefix_content_hash": proof["prefix_content_hash"],
            "identity_state_hash": proof["identity_state_hash"], "snapshot": snapshot, "behavior_evidence": evidence,
        }, "manifest_hash")
        manifests.append(manifest)
        waves.append({"time_index": wave["time_index"], "source_revision": manifest["manifest_hash"],
                      "network_complete": True, "edges": [[edge["source"], edge["target"]] for edge in snapshot["edges"]],
                      "behavior": behavior})
    panel = {"schema": "sociolab.longitudinal.v1", "dataset_id": journal["dataset_id"], "origin": journal["origin"],
             "source_reference": spec["source_reference"], "actors": spec["actors"],
             "relation": "directed_observed_social_tie", "behavior_variable": spec["forecast_specification"]["behavior"]["variable"],
             "waves": waves}
    return hashed({
        "schema": "sociolab.journal-forecast-history-bundle.v1", "kind": "JOURNAL_FORECAST_HISTORY", "profile": PROFILE,
        "history": panel, "specification": spec, "provenance": {**proof, "waves": manifests},
        "scope": {**BRIDGE_SCOPE, "target_behavior_selected": False, "target_network_materialized": False},
    })


def check_forecast(forecast, bundle, audit, label):
    audit.exact(forecast["content_hash"], content_hash({key: value for key, value in forecast.items() if key != "content_hash"}),
                label + ".HASH")
    audit.exact(forecast["schema"], "sociolab.behavior-forecast-artifact.v1", label + ".SCHEMA")
    audit.exact(forecast["kind"], "BEHAVIOR_FORECAST", label + ".KIND")
    audit.exact(forecast["profile"], FORECAST_PROFILE, label + ".PROFILE")
    history, spec = bundle["history"], bundle["specification"]["forecast_specification"]
    audit.exact(forecast["actors"], history["actors"], label + ".ROSTER")
    audit.exact(forecast["dataset"], {key: history[key] for key in
                ("dataset_id", "origin", "source_reference", "relation", "behavior_variable")}, label + ".DATASET")
    audit.exact(forecast["specification"], spec, label + ".SPECIFICATION")
    audit.exact(forecast["specification_hash"], content_hash(spec), label + ".SPECIFICATION_HASH")
    audit.exact(forecast["history"], {
        "content_hash": content_hash(history), "wave_time_indices": [wave["time_index"] for wave in history["waves"]],
        "wave_source_revisions": [wave["source_revision"] for wave in history["waves"]],
        "origin_time_index": 1, "wave_gap": 1, "transition_count": 1,
    }, label + ".HISTORY_BINDING")
    audit.exact(forecast["scope"], FORECAST_SCOPE, label + ".SCOPE")
    features = []
    for wave in history["waves"]:
        outgoing = {actor: [] for actor in history["actors"]}
        for source, target in wave["edges"]:
            outgoing[source].append(target)
        own, network = [], []
        for actor in history["actors"]:
            value = float(wave["behavior"][actor])
            others = outgoing[actor]
            gap = math.fsum(float(wave["behavior"][other]) for other in others) / len(others) - value if others else 0.0
            own.append([1.0, value])
            network.append([1.0, value, gap])
        features.append({"own_lag_ols": own, "network_lag_ols": network})
    audit.exact(forecast["training"], {
        "row_count": 4, "feature_hashes": {name: content_hash(rows) for name, rows in features[0].items()},
        "label_hash": content_hash([float(history["waves"][1]["behavior"][actor]) for actor in history["actors"]]),
    }, label + ".TRAINING_INPUTS")
    audit.exact(forecast["forecast_input_hashes"], {name: content_hash(rows) for name, rows in features[1].items()},
                label + ".FORECAST_INPUTS")
    audit.exact(forecast["models"]["persistence"]["raw_predictions"],
                [float(history["waves"][1]["behavior"][actor]) for actor in history["actors"]], label + ".PERSISTENCE_BINDING")


def target_reference(journal, spec, forecast, history_bundle, cutoff):
    proof, active = prefix(journal, cutoff)
    issuance = history_bundle["provenance"]
    require(cutoff >= spec["knowledge_cutoff"], "TARGET_CUTOFF_ORDER")
    require(all(proof["entities"].get(actor) == "person" and proof["identity_map"].get(actor, actor) == actor
                for actor in spec["actors"]), "TARGET_ROSTER_IDENTITY")
    behavior, evidence = point_behavior(proof, active, spec, spec["target_at"], issuance)
    provenance = {key: proof[key] for key in (
        "knowledge_cutoff", "prefix_envelope", "prefix_content_hash", "prefix_records_hash",
        "entities", "identity_map", "entity_identity_evidence", "identity_state_hash")}
    provenance.update({"history_knowledge_cutoff": spec["knowledge_cutoff"],
                       "issuance_identity_state_hash": issuance["identity_state_hash"],
                       "target_time_index": 2, "target_at": 20, "parsed_at": 20, "source_time_unit": "tick",
                       "behavior_source": spec["behavior_source"], "behavior_evidence": evidence})
    provenance = hashed(provenance, "manifest_hash")
    target = {"schema": "sociolab.behavior-target.v1", "dataset_id": journal["dataset_id"], "origin": journal["origin"],
              "source_reference": spec["source_reference"], "behavior_variable": forecast["dataset"]["behavior_variable"],
              "time_index": 2, "source_revision": provenance["manifest_hash"], "behavior": behavior}
    return hashed({
        "schema": "sociolab.journal-forecast-target-bundle.v1", "kind": "JOURNAL_FORECAST_TARGET", "profile": PROFILE,
        "target": target, "provenance": provenance, "forecast_hash": forecast["content_hash"],
        "history_bundle_hash": history_bundle["content_hash"],
        "scope": {**BRIDGE_SCOPE, "target_behavior_selected": True, "target_network_materialized": False,
                  "historical_network_replayed": True, "selected_target_identity_frozen_at_history_cutoff": True},
    })


def score_reference(forecast, target, retained, audit, label):
    models = {}
    actors = forecast["actors"]
    require(set(forecast["models"]) == set(MODELS) and len(actors) == 4 and set(target["behavior"]) == set(actors),
            "SCORE_FIXED_POPULATION")
    for name in MODELS:
        model = forecast["models"][name]
        require(model["status"] in ("OK", "NOT_ESTIMABLE"), "SCORE_MODEL_STATUS")
        available = model["status"] == "OK"
        losses = {variant: None for variant in ("raw", "clipped")}
        if available:
            require(model["reason"] is None, "SCORE_AVAILABLE_REASON")
            raw, clipped = model["raw_predictions"], model["clipped_predictions"]
            require(all(type(values) is list and len(values) == 4 and
                        all(type(value) in (int, float) and math.isfinite(value) for value in values)
                        for values in (raw, clipped)), "SCORE_PREDICTION_ARRAY")
            audit.exact([float(value) for value in clipped], [min(max(float(value), 0.0), 5.0) for value in raw],
                        label + "." + name + ".CLIPPING")
            count = sum(left != right for left, right in zip(raw, clipped))
            audit.exact(model["clipping_count"], count, label + "." + name + ".CLIPPING_COUNT")
            for variant, values in (("raw", raw), ("clipped", clipped)):
                errors = [float(prediction) - target["behavior"][actor] for actor, prediction in zip(actors, values)]
                losses[variant] = {"mae": math.fsum(abs(error) for error in errors) / 4,
                                   "rmse": math.sqrt(math.fsum(error * error for error in errors) / 4)}
        else:
            require(all(model[key] is None for key in ("raw_predictions", "clipped_predictions", "clipping_count")),
                    "UNAVAILABLE_PREDICTIONS")
            count = None
        models[name] = {"status": model["status"], "reason": model["reason"], "n_evaluated": 4 if available else 0,
                        "clipping_count": count, **losses}
    comparisons = {}
    for name, baseline in (("network_vs_own", "own_lag_ols"), ("network_vs_persistence", "persistence")):
        available = models["network_lag_ols"]["status"] == models[baseline]["status"] == "OK"
        comparisons[name] = {
            "status": "OK" if available else "NOT_ESTIMABLE", "reason": None if available else "required_forecast_not_estimable",
            "n_evaluated": 4 if available else 0, "direction": "network_minus_baseline_negative_favors_network",
            **{variant: {metric + "_difference": models["network_lag_ols"][variant][metric] - models[baseline][variant][metric]
                         for metric in ("mae", "rmse")} if available else None for variant in ("raw", "clipped")},
        }
    expected = {
        "schema": "sociolab.behavior-forecast-score.v1", "kind": "BEHAVIOR_FORECAST_SCORE", "profile": FORECAST_PROFILE,
        "dataset_id": target["dataset_id"], "behavior_variable": target["behavior_variable"],
        "forecast_hash": forecast["content_hash"], "history_prefix_hash": forecast["history"]["content_hash"],
        "specification_hash": forecast["specification_hash"], "target_behavior_hash": content_hash(target),
        "target_source_revision": target["source_revision"], "target_time_index": 2, "actor_count": 4,
        "models": models, "comparisons": comparisons,
        "metrics": {"primary": "mae", "secondary": "rmse", "primary_prediction": "clipped", "raw_metrics_reported": True,
                    "rounding": "none", "same_actor_comparison": True, "unit": "declared_behavior_level", "uncertainty_intervals": False},
        "scope": {**FORECAST_SCOPE, "score_output": "aggregate_only", "target_used_only_for_scoring": True},
        "runtime": retained["runtime"],
    }
    audit.compare(retained, expected, label)
    return {"models": models, "comparisons": comparisons}


def check(private, public):
    audit = Audit()
    protocol, protocol_raw = load(EXPERIMENT / "protocol.json")
    audit.exact(digest(protocol_raw), PROTOCOL_SHA256, "FROZEN_PROTOCOL_HASH")
    audit.exact(protocol["stage_order"], list(STAGES), "STAGE_ORDER")
    execution, execution_raw = load(public / "execution.json")
    report, report_raw = load(public / "report.json")
    audit.exact(execution["protocol_sha256"], PROTOCOL_SHA256, "EXECUTION_PROTOCOL_HASH")
    audit.exact(execution["report_file_sha256"], digest(report_raw), "EXECUTION_REPORT_HASH")
    audit.exact(execution["source_hashes_at_start"], execution["source_hashes_at_finish"], "UNCHANGED_SOURCE_MAPS")
    for relative, expected in execution["source_hashes_at_start"].items():
        path = (REPOSITORY / relative).resolve()
        require(path.is_relative_to(REPOSITORY), "SOURCE_PATH_OUTSIDE_REPOSITORY")
        audit.exact(digest(path.read_bytes()), expected, "CURRENT_SOURCE_FILE_HASH")
    for relative, expected in protocol["input_file_sha256"].items():
        audit.exact(digest((REPOSITORY / relative).read_bytes()), expected, "PROTOCOL_INPUT_FILE_HASH")
    private_paths = {path.name: path for path in private.glob("*.json")}
    private_hashes = {name: digest(path.read_bytes()) for name, path in private_paths.items()}
    audit.exact(private_hashes, execution["private_input_file_sha256"], "PRIVATE_FILE_INVENTORY_HASHES")
    audit.exact(private_hashes, execution["frozen_artifact_file_sha256"], "ALL_PRIVATE_FILES_FROZEN_AT_CREATION")
    for name, expected in execution["frozen_artifact_file_sha256"].items():
        audit.exact(private_hashes[name], expected, "FROZEN_ARTIFACT_FILE_HASH")
    retained = {name: load(path)[0] for name, path in private_paths.items()}
    empty, _ = load(EXAMPLES / "empty.events.json")
    spec, _ = load(EXAMPLES / "history.spec.json")
    audit.exact(empty["origin"], "synthetic", "SYNTHETIC_ORIGIN")
    audit.exact(empty["clock"], {"kind": "ticks", "run_id": "journal-forecast-example"}, "FIXTURE_CLOCK")
    audit.exact(empty["records"], [], "EMPTY_BASE_JOURNAL")
    audit.exact(spec["waves"], [{"time_index": 0, "at": 0}, {"time_index": 1, "at": 10}], "FIXTURE_WAVES")
    audit.exact(spec["target_at"], 20, "FIXTURE_TARGET_TIME")
    audit.exact(spec["forecast_specification"]["target_time_index"], 2, "FIXTURE_TARGET_INDEX")
    audit.condition(len(spec["actors"]) == 4 and spec["actors"] == sorted(set(spec["actors"])), "FIXTURE_ROSTER")
    audit.exact(spec["forecast_specification"]["behavior"]["minimum"], 0, "FIXTURE_SCALE_MINIMUM")
    audit.exact(spec["forecast_specification"]["behavior"]["maximum"], 5, "FIXTURE_SCALE_MAXIMUM")
    audit.exact(spec["source_reference"], None, "SYNTHETIC_SOURCE_REFERENCE")
    records, journals, counts = [], {}, {}
    for stage, expected_cutoff in zip(STAGES, (24, 29, 33, 34)):
        settings = protocol["stages"][stage]
        batch, _ = load(EXAMPLES / settings["batch"])
        audit.exact(len(batch), settings["record_count"], "BATCH_RECORD_COUNT")
        for raw in batch:
            require("ingest_seq" not in raw and "recorded_at" not in raw, "RAW_RECEIPT_INJECTION")
            records.append({**raw, "ingest_seq": len(records) + 1, "recorded_at": settings["received_at"]})
        expected = {**empty, "records": list(records)}
        journal = retained[f"journal-{stage}.json"]
        audit.exact(journal, expected, "IMPORTED_STAGE_CONTENT")
        audit.exact(len(records), expected_cutoff, "FIXTURE_STAGE_CUTOFF")
        audit.exact(settings["knowledge_cutoff"], expected_cutoff, "PROTOCOL_STAGE_CUTOFF")
        prefix(journal, expected_cutoff)
        journals[stage], counts[stage] = journal, expected_cutoff
    revised_spec = {**spec, "knowledge_cutoff": 29}
    audit.exact(retained["history-original.spec.json"], spec, "SAVED_ORIGINAL_SPEC")
    audit.exact(retained["history-revised.spec.json"], revised_spec, "SAVED_REVISED_SPEC")
    audit.exact(retained["forecast.spec.json"], spec["forecast_specification"], "SAVED_FORECAST_SPEC")
    histories = {}
    for label, stage, settings in (
        ("original", "initial", spec), ("old-cutoff-replay", "late_history", spec),
        ("revised", "late_history", revised_spec), ("old-cutoff-after-target", "target", spec),
        ("old-cutoff-after-correction", "revised_target", spec),
    ):
        expected = history_reference(journals[stage], settings)
        audit.exact(retained[f"history-{label}.bundle.json"], expected, "HISTORY_BUNDLE_REFERENCE")
        audit.exact(retained[f"history-{label}.json"], expected["history"], "EXPORTED_HISTORY_REFERENCE")
        histories[label] = expected
    for label in ("old-cutoff-replay", "old-cutoff-after-target", "old-cutoff-after-correction"):
        audit.exact(private_hashes[f"history-{label}.bundle.json"], private_hashes["history-original.bundle.json"],
                    "OLD_CUTOFF_HISTORY_BYTES")
        audit.exact(private_hashes[f"history-{label}.json"], private_hashes["history-original.json"], "OLD_CUTOFF_PANEL_BYTES")
    predictions = {label: retained[f"forecast-{label}.json"] for label in ("original", "old-cutoff-replay", "revised-history")}
    for label, history_label in (("original", "original"), ("old-cutoff-replay", "original"), ("revised-history", "revised")):
        check_forecast(predictions[label], histories[history_label], audit, "FORECAST." + label)
    audit.exact(private_hashes["forecast-original.json"], private_hashes["forecast-old-cutoff-replay.json"], "REPLAY_FORECAST_BYTES")
    original, revised = histories["original"], histories["revised"]
    old_waves, new_waves = original["history"]["waves"], revised["history"]["waves"]
    history_changes = {
        "behavior_values_changed": any(a["behavior"] != b["behavior"] for a, b in zip(old_waves, new_waves)),
        "network_edges_changed": any(a["edges"] != b["edges"] for a, b in zip(old_waves, new_waves)),
        "history_bundle_changed": original["content_hash"] != revised["content_hash"],
        "forecast_changed": predictions["original"]["content_hash"] != predictions["revised-history"]["content_hash"],
        "training_label_hash_changed": predictions["original"]["training"]["label_hash"] != predictions["revised-history"]["training"]["label_hash"],
    }
    audit.condition(all(history_changes.values()), "NEW_CUTOFF_CHANGES")
    targets = {}
    for label, stage, settings, forecast_label, history_label, cutoff in (
        ("original", "target", spec, "original", "original", 33),
        ("revised-history", "target", revised_spec, "revised-history", "revised", 33),
        ("old-cutoff-replay", "revised_target", spec, "original", "original", 33),
        ("corrected", "revised_target", spec, "original", "original", 34),
    ):
        expected = target_reference(journals[stage], settings, predictions[forecast_label], histories[history_label], cutoff)
        audit.exact(retained[f"target-{label}.bundle.json"], expected, "TARGET_BUNDLE_REFERENCE")
        audit.exact(retained[f"target-{label}.json"], expected["target"], "EXPORTED_TARGET_REFERENCE")
        targets[label] = expected
    audit.exact(private_hashes["target-original.bundle.json"], private_hashes["target-old-cutoff-replay.bundle.json"], "OLD_TARGET_BUNDLE_BYTES")
    audit.exact(private_hashes["target-original.json"], private_hashes["target-old-cutoff-replay.json"], "OLD_TARGET_BYTES")
    changed_target_count = sum(targets["original"]["target"]["behavior"][actor] != targets["corrected"]["target"]["behavior"][actor]
                               for actor in spec["actors"])
    audit.exact(changed_target_count, 1, "TARGET_CORRECTION_COUNT")
    audit.condition(not any(record["kind"] in ("relation.observed", "relation.changed") and record["occurred_at"] >= 20
                            for record in records), "NO_TARGET_NETWORK_OBSERVATIONS")
    audit.condition(not any(record["kind"] == "coverage.observed" and record["valid_interval"][0] <= 20 < record["valid_interval"][1]
                            for record in records), "NO_TARGET_NETWORK_COVERAGE")
    scores, score_hashes = {}, {}
    for label, forecast_label, target_label in (
        ("original", "original", "original"), ("revised-history", "revised-history", "revised-history"),
        ("corrected-target", "original", "corrected"),
    ):
        score, raw = load(public / f"score-{label}.json")
        audit.exact(digest(raw), private_hashes[f"score-{label}.json"], "PRIVATE_PUBLIC_SCORE_BYTES")
        scores[label] = score_reference(predictions[forecast_label], targets[target_label]["target"], score, audit, "SCORE." + label)
        score_hashes[f"score-{label}.json"] = digest(raw)
    audit.condition(scores["original"]["models"] != scores["corrected-target"]["models"], "CORRECTION_CHANGES_SCORES")
    expected_report = {
        "schema": "sociolab.journal-forecast-example-report.v1", "kind": "SYNTHETIC_JOURNAL_FORECAST_EXECUTION",
        "actor_count": 4, "history_wave_count": 2, "target_time_index": 2, "receipt_cutoffs": counts,
        "history_changes_at_new_cutoff": history_changes, "old_history_replays_byte_identically": True,
        "old_prediction_replay_byte_identical": True, "old_target_replay_byte_identical": True,
        "all_saved_predictions_unchanged": True, "target_correction_rescores_same_forecast": True,
        "original_history_bundle_hash": original["content_hash"], "revised_history_bundle_hash": revised["content_hash"],
        "original_forecast_hash": predictions["original"]["content_hash"],
        "revised_history_forecast_hash": predictions["revised-history"]["content_hash"],
        "original_target_source_revision": targets["original"]["target"]["source_revision"],
        "corrected_target_source_revision": targets["corrected"]["target"]["source_revision"],
        "score_file_sha256": score_hashes, "target_network_observations_supplied": False,
        "future_network_used_in_target_selection": False, "single_origin_analysis_versions": 2,
        "independent_real_forecast_origins": 0, "historical_as_of_availability_verified": False,
        "empirical_prediction_validated": False, "prospective_validation": False, "causal_effect_identified": False,
        "realtime_subscription_implemented": False, "engineering_example_only": True,
    }
    audit.exact(report, expected_report, "PUBLIC_REPORT_REFERENCE")
    destinations = [
        (private, "journal-initial.json"), (private, "history-original.bundle.json"), (private, "forecast-original.json"),
        (private, "journal-late_history.json"), (private, "history-old-cutoff-replay.bundle.json"), (private, "forecast-old-cutoff-replay.json"),
        (private, "history-revised.bundle.json"), (private, "forecast-revised-history.json"), (private, "journal-target.json"),
        (private, "history-old-cutoff-after-target.bundle.json"), (private, "target-original.bundle.json"), (public, "score-original.json"),
        (private, "target-revised-history.bundle.json"), (public, "score-revised-history.json"), (private, "journal-revised_target.json"),
        (private, "history-old-cutoff-after-correction.bundle.json"), (private, "target-old-cutoff-replay.bundle.json"),
        (private, "target-corrected.bundle.json"), (public, "score-corrected-target.json"),
    ]
    audit.exact(len(execution["steps"]), len(destinations), "CLI_STEP_COUNT")
    for order, (step, (directory, name)) in enumerate(zip(execution["steps"], destinations), 1):
        audit.exact(step["order"], order, "CLI_STEP_ORDER")
        audit.exact(step["exit_code"], 0, "CLI_STEP_EXIT")
        audit.exact(step["stderr_empty"], True, "CLI_STDERR_EMPTY")
        audit.exact(step["stderr_sha256"], digest(b""), "CLI_STDERR_HASH")
        audit.exact((private / f"step-{order:02d}.stderr.log").read_bytes().hex(), "", "RETAINED_STDERR_EMPTY")
        audit.exact(step["stdout_sha256"], digest((directory / name).read_bytes()), "CLI_STDOUT_HASH")
    audit.exact(len(execution["prediction_records"]), 3, "PREDICTION_RECORD_COUNT")
    for record, label in zip(execution["prediction_records"], ("original", "old-cutoff-replay", "revised-history")):
        audit.exact(record["label"], label, "PREDICTION_RECORD_LABEL")
        audit.exact(record["file_sha256"], private_hashes[f"forecast-{label}.json"], "PREDICTION_RECORD_FILE_HASH")
        audit.exact(record["forecast_hash"], predictions[label]["content_hash"], "PREDICTION_RECORD_CONTENT_HASH")
        audit.exact(record["target_batch_not_yet_ingested"], True, "PREDICTION_RECORD_PRETARGET_FLAG")
    for key, expected in (
        ("implementation_and_inputs_unchanged", True), ("frozen_artifacts_unchanged", True),
        ("automatic_retry", False), ("tuning_after_scores", False), ("real_data_used", False),
        ("execution_order_authenticates_historical_availability", False),
        ("all_fixture_batches_known_before_execution", True), ("engineering_example_only", True),
    ):
        audit.exact(execution[key], expected, "EXECUTION_SCOPE." + key)
    return hashed({
        "schema": "sociolab.independent-journal-forecast-check.v1", "kind": "INDEPENDENT_SYNTHETIC_JOURNAL_FORECAST_CHECK",
        "status": "PASS", "method": "stdlib_receipt_replay_and_saved_prediction_error_arithmetic",
        "protocol_sha256": PROTOCOL_SHA256, "execution_file_sha256": digest(execution_raw), "report_file_sha256": digest(report_raw),
        "checker_sha256": digest(Path(__file__).read_bytes()), "private_file_sha256": private_hashes,
        "score_file_sha256": score_hashes, "source_file_sha256": execution["source_hashes_at_start"],
        "counts": {"checks": audit.count, "numeric_comparisons": audit.numeric_count, "actor_count": 4,
                   "history_waves": 2, "history_bundles_checked": len(histories), "target_bundles_checked": len(targets),
                   "saved_forecasts_checked": len(predictions), "scores_checked": len(scores), "cli_steps_checked": len(destinations),
                   "target_values_corrected": changed_target_count, "receipt_cutoffs": counts},
        "numeric_comparison": {"max_absolute_error": audit.max_absolute_error, "absolute_tolerance": ATOL, "relative_tolerance": RTOL},
        "scope": {"sociolab_imported": False, "numpy_imported": False, "networkx_imported": False,
                  "model_fitted_or_refitted": False, "coefficients_independently_validated": False,
                  "fixture_only_snapshot_reference": True, "all_fixture_batches_known_before_execution": True,
                  "receipt_timestamps_invented": True, "target_network_materialized": False,
                  "historical_as_of_availability_verified": False, "prospective_validation": False,
                  "empirical_forecast_validated": False, "causal_effect_identified": False,
                  "content_hashes_authenticate_sources_or_times": False, "output": "aggregate_only"},
        "runtime": {"python": platform.python_version(), "third_party_dependencies": []},
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-directory", type=Path, required=True)
    parser.add_argument("--public-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        require(not arguments.output.exists(), "OUTPUT_ALREADY_EXISTS")
        result = check(arguments.private_directory.resolve(), arguments.public_directory.resolve())
        with arguments.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"status": "PASS", "checks": result["counts"]["checks"],
                          "max_absolute_error": result["numeric_comparison"]["max_absolute_error"]}, sort_keys=True))
        return 0
    except CheckError as error:
        print("independent check rejected: " + str(error), file=sys.stderr)
    except OSError:
        print("independent check rejected: FILE_ACCESS_ERROR", file=sys.stderr)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        print("independent check rejected: INVALID_INPUT_STRUCTURE_OR_ARITHMETIC", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
