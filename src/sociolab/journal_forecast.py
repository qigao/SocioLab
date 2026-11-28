"""Receipt-prefix inputs for one saved behavioral forecast, without fitting.

The bridge preserves the source journal's evidence and selects complete binary
network states plus exact point measurements. It does not authenticate receipt
timestamps, subscribe to a live source, or relax the immutable-prefix evaluator's
revision policy across different knowledge cutoffs.
"""

from __future__ import annotations

from copy import deepcopy

from .behavior_forecast import (
    _fields, _hash, _integer, _origin, _text, _validate_forecast, _validate_spec,
)
from .events import EventDataset, parse_time
from .panels import LongitudinalPanel
from .snapshots import materialize_snapshot

_PROFILE = "journal-receipt-prefix-point-behavior-v1"
_SPEC_FIELDS = {
    "schema", "knowledge_cutoff", "source_reference", "actors", "population", "layer",
    "behavior_source", "waves", "target_at", "forecast_specification",
}
_SCOPE = {
    "receipt_prefix_enforced": True,
    "historical_as_of_availability_verified": False,
    "receipt_timestamps_externally_authenticated": False,
    "forecast_issued_before_target_observation_verified": False,
    "live_subscription": False,
    "models_fitted_by_bridge": False,
    "behavior_selection": "one_active_point_measurement_per_actor_at_exact_source_time",
    "behavior_forward_filled": False,
    "behavior_imputed": False,
    "actor_dropping": False,
    "network_selection": "complete_directed_binary_state_at_each_declared_history_time",
    "network_source_system_filter": None,
    "population_boundary_qualified": False,
    "single_origin_as_known_profile": True,
    "cross_cutoff_immutable_prefix_compatibility_established": False,
    "content_hash_authenticates_author": False,
    "content_hash_proves_prospective_timestamp": False,
    "contains_private_actor_records": True,
    "causal_effect_identified": False,
    "empirical_forecast_validated": False,
}


def _validated_spec(dataset: EventDataset, spec: dict) -> dict:
    if not isinstance(dataset, EventDataset):
        raise TypeError("journal forecast inputs require an EventDataset")
    _fields(spec, _SPEC_FIELDS, "journal forecast history specification")
    if spec["schema"] != "sociolab.journal-forecast-history.v1":
        raise ValueError("unsupported journal forecast history schema")
    _origin(dataset.origin, spec["source_reference"])
    cutoff = _integer(spec["knowledge_cutoff"], "knowledge_cutoff")
    dataset.as_known(cutoff)
    _text(spec["population"], "population")
    _text(spec["layer"], "layer")
    _fields(spec["behavior_source"], {"system", "attribute"}, "behavior_source")
    for field in ("system", "attribute"):
        _text(spec["behavior_source"][field], f"behavior_source {field}")
    actors = spec["actors"]
    if type(actors) is not list or not 2 <= len(actors) <= 200:
        raise ValueError("journal forecast requires between 2 and 200 fixed actors")
    for actor in actors:
        _text(actor, "actor")
    if actors != sorted(set(actors)):
        raise ValueError("actors must be unique, sorted canonical identities")
    entities, identities = dataset.entities_at(cutoff), dataset.identity_map_at(cutoff)
    if any(entities.get(actor) != "person" or identities.get(actor, actor) != actor for actor in actors):
        raise ValueError("every fixed actor must be a known canonical person at the history cutoff")
    waves = spec["waves"]
    if type(waves) is not list or not 2 <= len(waves) <= 32:
        raise ValueError("journal forecast requires between 2 and 32 history waves")
    indices, source_times = [], []
    for wave in waves:
        _fields(wave, {"time_index", "at"}, "history wave")
        indices.append(_integer(wave["time_index"], "wave time_index"))
        source_times.append(parse_time(wave["at"], dataset.clock))
    index_gap, source_gap = indices[1] - indices[0], source_times[1] - source_times[0]
    if index_gap <= 0 or any(right - left != index_gap for left, right in zip(indices, indices[1:])):
        raise ValueError("wave indices must strictly increase at one constant gap")
    if source_gap <= 0 or any(right - left != source_gap for left, right in zip(source_times, source_times[1:])):
        raise ValueError("source wave times must strictly increase at one exact constant gap")
    forecast_spec = _validate_spec(spec["forecast_specification"])
    if forecast_spec["target_time_index"] != indices[-1] + index_gap:
        raise ValueError("forecast target index must be the next index at the same wave gap")
    if parse_time(spec["target_at"], dataset.clock) != source_times[-1] + source_gap:
        raise ValueError("target_at must be the next source time at the same exact gap")
    normalized = deepcopy(spec)
    normalized["forecast_specification"] = forecast_spec
    _hash(normalized)
    return normalized


def _prefix(dataset: EventDataset, cutoff: int) -> dict:
    """Bind the exact receipt prefix, preserving the unchanged journal envelope."""
    active = dataset.as_known(cutoff)
    source = dataset.to_dict()
    records = source.pop("records")[:cutoff]
    entities = dataset.entities_at(cutoff)
    identities = dataset.identity_map_at(cutoff)
    identity_evidence = [record for record in active if record["kind"] in {"entity.observed", "identity.mapped"}]
    identity_state = {"entities": entities, "identity_map": identities, "entity_identity_evidence": identity_evidence}
    return {
        "knowledge_cutoff": cutoff,
        "prefix_envelope": source,
        "prefix_content_hash": _hash({**source, "records": records}),
        "prefix_records_hash": _hash(records),
        "receipt_records": records,
        "active_record_ids": [record["record_id"] for record in active],
        **identity_state,
        "identity_state_hash": _hash(identity_state),
    }


def _behavior_at(
    dataset: EventDataset,
    spec: dict,
    at: object,
    context: dict,
    *,
    issuance: dict | None = None,
) -> tuple[dict[str, int], list[dict]]:
    """Select before validating values; invalid and duplicate evidence cannot hide."""
    actors = set(spec["actors"])
    clock = dataset.clock
    when = parse_time(at, clock)
    entities, identities = context["entities"], context["identity_map"]
    selected = {actor: [] for actor in spec["actors"]}
    scale = spec["forecast_specification"]["behavior"]
    for record in dataset.as_known(context["knowledge_cutoff"]):
        if record["kind"] != "actor.attribute.observed":
            continue
        payload = record["payload"]
        if record["source"]["system"] != spec["behavior_source"]["system"] or payload["name"] != spec["behavior_source"]["attribute"]:
            continue
        interval = record["valid_interval"]
        relevant_time = parse_time(record["occurred_at"], clock) == when
        if interval is not None:
            relevant_time |= (parse_time(interval[0], clock) <= when and
                              (interval[1] is None or when < parse_time(interval[1], clock)))
        if not relevant_time:
            continue
        raw_actor = payload["actor"]
        resolved = identities.get(raw_actor, raw_actor)
        issued_actor = (issuance["identity_map"].get(raw_actor, raw_actor)
                        if issuance is not None and raw_actor in issuance["entities"] else None)
        if resolved not in actors and issued_actor not in actors:
            continue
        if issuance is not None and (issuance["entities"].get(raw_actor) != "person" or issued_actor != resolved):
            raise ValueError("selected target measurement requires a history-known actor with unchanged identity resolution")
        if entities.get(raw_actor) != "person" or resolved not in actors:
            raise ValueError("selected behavior must resolve to a fixed canonical person")
        if interval is not None:
            raise ValueError("behavior requires point measurements; intervals touching a selected wave are unsupported")
        value = payload["value"]
        if type(value) is not int or not scale["minimum"] <= value <= scale["maximum"]:
            raise ValueError("selected behavior must be a known integer level within the declared scale")
        if clock["kind"] == "utc" and parse_time(record["recorded_at"], {"kind": "utc"}) < when:
            raise ValueError("selected UTC observed behavior cannot have a receipt earlier than its occurrence")
        selected[resolved].append({"record": record, "resolved_actor": resolved})
    if any(len(records) != 1 for records in selected.values()):
        raise ValueError("each fixed actor needs exactly one active point behavior record at every selected time")
    evidence = [selected[actor][0] for actor in spec["actors"]]
    return {item["resolved_actor"]: item["record"]["payload"]["value"] for item in evidence}, evidence


def make_journal_forecast_history(dataset: EventDataset, spec: dict) -> dict:
    """Materialize one private historical panel at one explicit receipt cutoff.

    The complete receipt prefix and raw selected evidence are retained. Model
    creation remains the separate existing ``forecast create`` operation.
    """
    specification = _validated_spec(dataset, spec)
    cutoff = specification["knowledge_cutoff"]
    provenance = _prefix(dataset, cutoff)
    waves, manifests = [], []
    for wave in specification["waves"]:
        snapshot = materialize_snapshot(dataset, {
            "schema": "sociolab.view.v1", "population": specification["population"],
            "layer": specification["layer"], "mode": "state", "directed": True, "at": wave["at"],
        }, knowledge_cutoff=cutoff)
        snapshot.require_complete()
        if list(snapshot.persons) != specification["actors"] or snapshot.bipartite or not snapshot.directed:
            raise ValueError("each complete directed nonbipartite snapshot must equal the fixed actor roster")
        snapshot_data = snapshot.to_dict()
        if any(edge["strength"] != 1 for edge in snapshot_data["edges"]):
            raise ValueError("positive network state strength must be exactly one; weighted ties are unsupported")
        behavior, evidence = _behavior_at(dataset, specification, wave["at"], provenance)
        manifest = {
            "time_index": wave["time_index"], "at": wave["at"], "knowledge_cutoff": cutoff,
            "parsed_at": parse_time(wave["at"], dataset.clock),
            "source_time_unit": "tick" if dataset.clock["kind"] == "ticks" else "microsecond",
            "prefix_content_hash": provenance["prefix_content_hash"],
            "identity_state_hash": provenance["identity_state_hash"],
            "snapshot": snapshot_data, "behavior_evidence": evidence,
        }
        manifest["manifest_hash"] = _hash(manifest)
        manifests.append(manifest)
        waves.append({
            "time_index": wave["time_index"], "source_revision": manifest["manifest_hash"],
            "network_complete": True,
            "edges": [[edge["source"], edge["target"]] for edge in snapshot_data["edges"]],
            "behavior": behavior,
        })
    panel = LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1", "dataset_id": dataset.dataset_id,
        "origin": dataset.origin, "source_reference": specification["source_reference"],
        "actors": specification["actors"], "relation": "directed_observed_social_tie",
        "behavior_variable": specification["forecast_specification"]["behavior"]["variable"], "waves": waves,
    })
    provenance["waves"] = manifests
    bundle = {
        "schema": "sociolab.journal-forecast-history-bundle.v1", "kind": "JOURNAL_FORECAST_HISTORY",
        "profile": _PROFILE, "history": panel.to_dict(), "specification": specification,
        "provenance": provenance, "scope": {**_SCOPE, "target_behavior_selected": False,
                                            "target_network_materialized": False},
    }
    bundle["content_hash"] = _hash(bundle)
    return bundle


def _match_forecast(bundle: dict, forecast: dict) -> dict:
    artifact = _validate_forecast(forecast)
    panel = LongitudinalPanel.from_mapping(bundle["history"])
    expected_history = {
        "content_hash": panel.content_hash,
        "wave_time_indices": [wave.time_index for wave in panel.waves],
        "wave_source_revisions": [wave.source_revision for wave in panel.waves],
        "origin_time_index": panel.waves[-1].time_index,
        "wave_gap": panel.waves[1].time_index - panel.waves[0].time_index,
        "transition_count": len(panel.waves) - 1,
    }
    dataset = {key: bundle["history"][key] for key in
               ("dataset_id", "origin", "source_reference", "relation", "behavior_variable")}
    if (artifact["history"] != expected_history or artifact["actors"] != list(panel.actors) or
            artifact["dataset"] != dataset or
            artifact["specification"] != bundle["specification"]["forecast_specification"]):
        raise ValueError("saved forecast must match the replayed history, fixed roster, source, scale and specification")
    return artifact


def make_journal_forecast_target(
    dataset: EventDataset, spec: dict, forecast: dict, knowledge_cutoff: int,
) -> dict:
    """Extract separate target behavior after verifying the saved history binding.

    Only the old historical network states are replayed. The later receipt prefix
    is hashed for identity/provenance and queried for behavior; no target network
    is materialized. New aliases cannot supply the target's measurement identity.
    """
    history_bundle = make_journal_forecast_history(dataset, spec)
    specification = history_bundle["specification"]
    artifact = _match_forecast(history_bundle, forecast)
    cutoff = _integer(knowledge_cutoff, "target knowledge_cutoff")
    if cutoff < specification["knowledge_cutoff"]:
        raise ValueError("target knowledge cutoff cannot precede the history cutoff")
    current = _prefix(dataset, cutoff)
    issuance = history_bundle["provenance"]
    if any(current["entities"].get(actor) != "person" or current["identity_map"].get(actor, actor) != actor
           for actor in specification["actors"]):
        raise ValueError("target cutoff cannot change any frozen roster actor's identity")
    behavior, evidence = _behavior_at(dataset, specification, specification["target_at"], current, issuance=issuance)
    # The full journal prefix is hashed, but future network records are not
    # interpreted or copied into the target measurement manifest.
    provenance = {key: current[key] for key in (
        "knowledge_cutoff", "prefix_envelope", "prefix_content_hash", "prefix_records_hash",
        "entities", "identity_map", "entity_identity_evidence", "identity_state_hash",
    )}
    provenance.update({
        "history_knowledge_cutoff": specification["knowledge_cutoff"],
        "issuance_identity_state_hash": issuance["identity_state_hash"],
        "target_time_index": artifact["specification"]["target_time_index"],
        "target_at": specification["target_at"],
        "parsed_at": parse_time(specification["target_at"], dataset.clock),
        "source_time_unit": "tick" if dataset.clock["kind"] == "ticks" else "microsecond",
        "behavior_source": deepcopy(specification["behavior_source"]),
        "behavior_evidence": evidence,
    })
    provenance["manifest_hash"] = _hash(provenance)
    target = {
        "schema": "sociolab.behavior-target.v1", "dataset_id": dataset.dataset_id,
        "origin": dataset.origin, "source_reference": specification["source_reference"],
        "behavior_variable": artifact["dataset"]["behavior_variable"],
        "time_index": artifact["specification"]["target_time_index"],
        "source_revision": provenance["manifest_hash"], "behavior": behavior,
    }
    bundle = {
        "schema": "sociolab.journal-forecast-target-bundle.v1", "kind": "JOURNAL_FORECAST_TARGET",
        "profile": _PROFILE, "target": target, "provenance": provenance,
        "forecast_hash": artifact["content_hash"], "history_bundle_hash": history_bundle["content_hash"],
        "scope": {**_SCOPE, "target_behavior_selected": True, "target_network_materialized": False,
                  "historical_network_replayed": True, "selected_target_identity_frozen_at_history_cutoff": True},
    }
    bundle["content_hash"] = _hash(bundle)
    return bundle
