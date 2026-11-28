"""Receipt-bound repeat-interaction baselines and coverage-aware future scoring.

The fixed risk set contains previously observed ordered pairs, not inferred
relationships. All event counts and observation intervals use the original
snapshot materializer. This module neither fits a latent relationship model nor
changes a source-declared relationship when an event window expires.
"""

from __future__ import annotations

from copy import deepcopy
import math

from .behavior_forecast import _fields, _integer, _origin, _text
from .events import EventDataset, parse_time
from .journal_forecast import _prefix
from .snapshots import _TemporalView, content_hash, materialize_snapshot, validate_view_spec


_PROFILE = "complete-history-directed-repeat-pairs-v1"
_MODELS = ("historical_poisson", "recent_poisson", "recent_occurrence")
_SPEC_FIELDS = {
    "schema", "knowledge_cutoff", "source_reference", "observation_reference",
    "actors", "population", "layer", "actions", "topics", "history_start",
    "recent_start", "origin_at", "target_end", "risk_set",
}
_FORECAST_FIELDS = {
    "schema", "kind", "profile", "specification", "journal", "windows",
    "provenance", "predictions", "scope", "content_hash",
}
_SCOPE = {
    "risk_set": "history_positive_ordered_pairs",
    "receipt_prefix_enforced": True,
    "history_raw_future_assertions_rejected": True,
    "history_event_counts_use_source_time": True,
    "source_system_filter": None,
    "timestamps_ordered_within_ties": False,
    "relationship_state_inferred": False,
    "window_expiry_is_relationship_termination": False,
    "probability_calibration_validated": False,
    "empirical_forecast_validated": False,
    "population_boundary_qualified": False,
    "causal_effect_identified": False,
    "receipt_timestamps_authenticated": False,
    "prospective_issuance_verified": False,
    "observation_declarations_authenticated": False,
    "uncertainty_intervals": False,
}


def _view(spec: dict, start: object, end: object) -> dict:
    return {
        "schema": "sociolab.view.v1", "population": spec["population"],
        "layer": spec["layer"], "mode": "events", "directed": True,
        "actions": spec["actions"], "topics": spec["topics"], "roles": [],
        "start": start, "end": end,
    }


def _specification(dataset: EventDataset, value: dict) -> dict:
    _fields(value, _SPEC_FIELDS, "repeat-interaction specification")
    if value["schema"] != "sociolab.repeat-interaction-spec.v1":
        raise ValueError("unsupported repeat-interaction specification schema")
    if value["risk_set"] != "history_positive_ordered_pairs":
        raise ValueError("repeat-interaction risk set must be history_positive_ordered_pairs")
    _origin(dataset.origin, value["source_reference"])
    _text(value["observation_reference"], "observation_reference")
    cutoff = _integer(value["knowledge_cutoff"], "knowledge_cutoff")
    dataset.as_known(cutoff)
    actors = value["actors"]
    if type(actors) is not list or not 2 <= len(actors) <= 200:
        raise ValueError("repeat-interaction requires 2 to 200 fixed actors")
    for actor in actors:
        _text(actor, "actor")
    if actors != sorted(set(actors)):
        raise ValueError("actors must be unique, sorted canonical identities")
    entities, identities = dataset.entities_at(cutoff), dataset.identity_map_at(cutoff)
    if any(entities.get(a) != "person" or identities.get(a, a) != a for a in actors):
        raise ValueError("fixed actors must be canonical people known at the history cutoff")
    view = validate_view_spec(_view(value, value["history_start"], value["origin_at"]), dataset.clock)
    if len(view["actions"]) != 1:
        raise ValueError("the initial repeat-interaction profile requires one declared action")
    start, recent, origin, end = (parse_time(value[key], dataset.clock) for key in (
        "history_start", "recent_start", "origin_at", "target_end"))
    if not start <= recent < origin < end:
        raise ValueError("require history_start <= recent_start < origin_at < target_end")
    for width in (origin - start, origin - recent, end - origin):
        try:
            finite = math.isfinite(width)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("window durations must have finite numerical representations")
    spec = deepcopy(value)
    spec["actions"], spec["topics"] = view["actions"], view["topics"]
    return spec


def _matching_assertion(record: dict, spec: dict) -> bool:
    return (record["operation"] == "assert" and record["kind"] == "interaction.observed"
            and record["payload"]["action"] in spec["actions"]
            and (not spec["topics"] or record["payload"]["topic"] in spec["topics"]))


def _future_stream_gate(dataset: EventDataset, spec: dict) -> None:
    # Raw assertions remain known even after a correction or retraction. Check
    # the declared action/topic stream across actors, as in journal evaluation.
    origin = parse_time(spec["origin_at"], dataset.clock)
    for record in dataset.records[:spec["knowledge_cutoff"]]:
        if _matching_assertion(record, spec) and parse_time(record["occurred_at"], dataset.clock) >= origin:
            raise ValueError("history receipt prefix already contains a target-or-later interaction assertion")


def _poisson_probability(count: int, horizon: int, exposure: int) -> float:
    try:
        intensity = count * (horizon / exposure)
    except OverflowError as error:
        raise ValueError("forecast intensity is outside the finite numerical profile") from error
    if not math.isfinite(intensity):
        raise ValueError("forecast intensity must be finite")
    return -math.expm1(-intensity)


def make_repeat_interaction_forecast(dataset: EventDataset, spec: dict) -> dict:
    """Freeze private probabilities using only complete history at explicit K.

    Any supplied journal tail after K is ignored. The source-time origin starts
    the half-open target window. Source coverage and membership are declarations,
    not authenticated completeness or scientifically qualified population data.
    """
    spec = _specification(dataset, spec)
    _future_stream_gate(dataset, spec)
    cutoff = spec["knowledge_cutoff"]
    history_view = _view(spec, spec["history_start"], spec["origin_at"])
    history = materialize_snapshot(dataset, history_view, knowledge_cutoff=cutoff)
    history.require_complete()
    data = history.to_dict()
    origin = parse_time(spec["origin_at"], dataset.clock)
    width = origin - parse_time(spec["history_start"], dataset.clock)
    recent_width = origin - parse_time(spec["recent_start"], dataset.clock)
    horizon = parse_time(spec["target_end"], dataset.clock) - origin
    if data["persons"] != spec["actors"]:
        raise ValueError("history population must exactly match the frozen actor roster")
    temporal = _TemporalView(dataset, history_view, cutoff)
    if any(data["population"]["exposure"][a] != width or temporal.membership_at(a, origin)[0] != "present"
           for a in spec["actors"]):
        raise ValueError("all frozen actors need full history exposure and presence at the origin")
    if len(data["edges"]) > 2000:
        raise ValueError("repeat-interaction budget is at most 2000 historical risk pairs")
    recent = materialize_snapshot(dataset, _view(spec, spec["recent_start"], spec["origin_at"]),
                                  knowledge_cutoff=cutoff)
    recent.require_complete()
    recent_counts = {(e["source"], e["target"]): e["strength"] for e in recent.to_dict()["edges"]}
    records = {r["record_id"]: r for r in dataset.as_known(cutoff)}
    predictions = []
    for edge in data["edges"]:
        count = edge["strength"]
        recent_count = recent_counts.get((edge["source"], edge["target"]), 0)
        last = max(parse_time(records[r]["occurred_at"], dataset.clock) for r in edge["evidence"])
        predictions.append({
            "source": edge["source"], "target": edge["target"],
            "history_count": count, "recent_count": recent_count,
            "last_event_age": origin - last,
            "probabilities": {
                "historical_poisson": _poisson_probability(count, horizon, width),
                "recent_poisson": _poisson_probability(recent_count, horizon, recent_width),
                "recent_occurrence": 1.0 if recent_count else 0.0,
            },
        })
    prefix = _prefix(dataset, cutoff)
    artifact = {
        "schema": "sociolab.repeat-interaction-forecast.v1", "kind": "REPEAT_INTERACTION_FORECAST",
        "profile": _PROFILE, "specification": spec, "journal": prefix["prefix_envelope"],
        "windows": {"history_width": width, "recent_width": recent_width, "horizon": horizon,
                    "source_time_unit": "tick" if dataset.clock["kind"] == "ticks" else "microsecond"},
        "provenance": {key: prefix[key] for key in (
            "knowledge_cutoff", "prefix_content_hash", "prefix_records_hash", "identity_state_hash")},
        "predictions": predictions,
        "scope": {**_SCOPE, "contains_private_actor_records": True},
    }
    artifact["provenance"].update(history_snapshot_hash=history.content_hash, recent_snapshot_hash=recent.content_hash)
    artifact["content_hash"] = content_hash(artifact)
    return artifact


def _target_reason(snapshot: dict, actors: tuple[str, str], horizon: int) -> str | None:
    population = snapshot["population"]
    if any(a in population["unknown"] or population["unknown_intervals"].get(a) for a in actors):
        return "membership_unknown"
    if any(population["exposure"].get(a, 0) != horizon for a in actors):
        return "membership_not_full_horizon"
    if any(snapshot["coverage"]["actors"].get(a) != "complete" for a in actors):
        return "coverage_incomplete"
    return None


def score_repeat_interaction_forecast(dataset: EventDataset, forecast: dict, target_spec: dict) -> dict:
    """Replay the frozen history, then score one explicitly declared target K.

    All models use the same complete-follow-up pairs. Known positives under
    partial follow-up remain in aggregate evidence counts, but are not pooled
    with fully observed negatives. No eligible rows means null metrics, not zero.
    """
    _fields(forecast, _FORECAST_FIELDS, "repeat-interaction forecast")
    if forecast["content_hash"] != content_hash({k: v for k, v in forecast.items() if k != "content_hash"}):
        raise ValueError("repeat-interaction forecast hash does not match its contents")
    expected = make_repeat_interaction_forecast(dataset, forecast["specification"])
    if content_hash(forecast) != content_hash(expected):
        raise ValueError("saved forecast does not match its original journal history and specification")
    _fields(target_spec, {"schema", "knowledge_cutoff", "observed_through", "observation_reference"},
            "repeat-interaction target")
    if target_spec["schema"] != "sociolab.repeat-interaction-target.v1":
        raise ValueError("unsupported repeat-interaction target schema")
    _text(target_spec["observation_reference"], "target observation_reference")
    cutoff = _integer(target_spec["knowledge_cutoff"], "target knowledge_cutoff")
    spec = forecast["specification"]
    if cutoff < spec["knowledge_cutoff"]:
        raise ValueError("target receipt cutoff cannot precede the history cutoff")
    prefix = _prefix(dataset, cutoff)
    issuance = _prefix(dataset, spec["knowledge_cutoff"])
    if prefix["identity_map"] != issuance["identity_map"] or any(
            prefix["entities"].get(a) != "person" for a in spec["actors"]):
        raise ValueError("target receipt cutoff must preserve the frozen actor identities and alias map")
    observed_through = parse_time(target_spec["observed_through"], dataset.clock)
    origin = parse_time(spec["origin_at"], dataset.clock)
    target_end = parse_time(spec["target_end"], dataset.clock)
    if observed_through < origin:
        raise ValueError("observed_through cannot precede the forecast origin")
    mature = observed_through >= target_end
    # Partial follow-up can retain already observed positives. Never select
    # events after the declared observed-through boundary merely because a
    # later source-time assertion happens to be present at this receipt cutoff.
    end = spec["target_end"] if mature else target_spec["observed_through"]
    snapshot = None
    edges = {}
    if observed_through > origin:
        snapshot = materialize_snapshot(dataset, _view(spec, spec["origin_at"], end),
                                        knowledge_cutoff=cutoff).to_dict()
        edges = {(e["source"], e["target"]): e for e in snapshot["edges"]}
    risk = {(p["source"], p["target"]) for p in forecast["predictions"]}
    earliest = {}
    records = {r["record_id"]: r for r in dataset.records[:cutoff]}
    for record in records.values():
        earliest.setdefault((record["source"]["system"], record["fact_id"]), record["ingest_seq"])
    for pair in risk & edges.keys():
        for record_id in edges[pair]["evidence"]:
            record = records[record_id]
            if earliest[(record["source"]["system"], record["fact_id"])] <= spec["knowledge_cutoff"]:
                raise ValueError("selected target interaction fact was first received at or before the history cutoff")
    counts = {
        "risk_pairs": len(risk), "scorable_pairs": 0, "unscored_pairs": 0,
        "known_positive_pairs": 0, "scorable_positive_pairs": 0,
        "scorable_negative_pairs": 0, "known_positive_unscored_pairs": 0,
    }
    reasons = {name: 0 for name in (
        "followup_not_closed", "membership_unknown", "membership_not_full_horizon", "coverage_incomplete")}
    scored = []
    for prediction in forecast["predictions"]:
        pair = prediction["source"], prediction["target"]
        positive = int(pair in edges)
        counts["known_positive_pairs"] += positive
        reason = "followup_not_closed" if not mature else _target_reason(snapshot, pair, target_end - origin)
        if reason is not None:
            counts["unscored_pairs"] += 1
            counts["known_positive_unscored_pairs"] += positive
            reasons[reason] += 1
        else:
            counts["scorable_pairs"] += 1
            counts["scorable_positive_pairs"] += positive
            counts["scorable_negative_pairs"] += 1 - positive
            scored.append((prediction, positive))
    n = len(scored)
    models = {}
    for model in _MODELS:
        models[model] = {
            "status": "SCORED" if n else "UNSCORED", "n": n,
            "brier": math.fsum((p["probabilities"][model] - y) ** 2 for p, y in scored) / n if n else None,
            "mean_predicted_probability": math.fsum(p["probabilities"][model] for p, _ in scored) / n if n else None,
            "observed_fraction": counts["scorable_positive_pairs"] / n if n else None,
        }
    result = {
        "schema": "sociolab.repeat-interaction-score.v1", "kind": "REPEAT_INTERACTION_SCORE",
        "profile": _PROFILE, "forecast_hash": forecast["content_hash"],
        "history_prefix_hash": issuance["prefix_content_hash"],
        "target": {"specification": deepcopy(target_spec), "prefix_hash": prefix["prefix_content_hash"],
                   "snapshot_hash": None if snapshot is None else snapshot["content_hash"],
                   "followup_closed": mature},
        "status": "UNSCORED" if not n else ("SCORED" if n == len(risk) else "PARTIALLY_SCORED"),
        "counts": counts, "unscored_reasons": reasons, "models": models,
        "scope": {**_SCOPE, "contains_private_actor_records": False, "output": "aggregate_only",
                  "all_models_use_same_scoring_pairs": True, "target_fact_ancestry_gate_enforced": True,
                  "known_positive_partial_followup_scored": False, "target_population_expands_risk_set": False,
                  "dependent_pairs_treated_as_iid": False, "target_information_used_to_refit": False},
    }
    result["content_hash"] = content_hash(result)
    return result
