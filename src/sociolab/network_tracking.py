"""Immutable receipt-driven checkpoints for fixed registered network views.

The pure core ingests an explicit batch, reconstructs each fixed view, and keeps
observed graph, population, coverage and selected evidence changes distinct.
Persistence, locking, checkpoint retention and delivery belong to the caller.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite

from .affiliations import affiliation_report
from .changes import compare_snapshots
from .events import EventDataset, ingest_records
from .snapshots import NetworkSnapshot, content_hash, materialize_snapshot, validate_view_spec

_PROFILE = "receipt-fixed-view-tracking-v1"
_STATE_FIELDS = {
    "schema", "kind", "profile", "sequence", "previous_state_hash", "registration", "registration_hash",
    "dataset", "knowledge_cutoff", "views", "scope", "content_hash",
}
_ANALYSIS_DEFAULTS = {
    "algorithm": "greedy", "seed": 0, "resolution": 1.0,
    "group_size": None, "group_members": None, "projection": "none",
    "max_nodes": 200, "max_edges": 2000, "max_pairs": 100000,
}
_SCOPE = {
    "receipt_driven": True,
    "registered_view_times_fixed": True,
    "automatic_event_time_advance": False,
    "live_subscription": False,
    "all_registered_views_rematerialized_after_append": True,
    "qualified_comparison_requires_both_snapshots_complete": True,
    "whole_analysis_node_budget": 200,
    "whole_analysis_edge_budget": 2000,
    "group_selection_budgets_are_separate": True,
    "unknown_observations_treated_as_absent": False,
    "snapshot_hash_change_means_network_change": False,
    "historical_as_of_availability_verified": False,
    "content_hash_authenticates_author": False,
    "content_hash_proves_external_timestamp": False,
    "contains_private_actor_records": True,
    "automatic_annotation_qualified": False,
    "causal_effect_identified": False,
}
_TRANSITION_SCOPE = {**_SCOPE, "change_meaning": "descriptive_change_under_fixed_registered_views"}


def _fields(value: object, expected: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} must use exact fields")


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonempty trimmed text")
    return value


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _hash_field(value: object, name: str) -> None:
    if (type(value) is not str or len(value) != 71 or not value.startswith("sha256:") or
            any(character not in "0123456789abcdef" for character in value[7:])):
        raise ValueError(f"{name} must be a canonical SHA-256 hash")


def _analysis(value: object, view: dict) -> dict:
    if type(value) is not dict or not set(value) <= set(_ANALYSIS_DEFAULTS):
        raise ValueError("analysis contains unsupported settings")
    analysis = deepcopy(_ANALYSIS_DEFAULTS)
    analysis.update(deepcopy(value))
    if type(analysis["algorithm"]) is not str or analysis["algorithm"] not in {"greedy", "louvain"}:
        raise ValueError("unsupported tracking community algorithm")
    _integer(analysis["seed"], "analysis seed")
    resolution = analysis["resolution"]
    try:
        finite = type(resolution) in (int, float) and isfinite(resolution)
    except OverflowError:
        finite = False
    if not finite or resolution <= 0:
        raise ValueError("analysis resolution must be finite and positive")
    analysis["resolution"] = float(resolution)
    if type(analysis["projection"]) is not str or analysis["projection"] not in {"none", "count", "newman"}:
        raise ValueError("unsupported tracking affiliation projection")
    if view["mode"] != "participation" and analysis["projection"] != "none":
        raise ValueError("projection requires a participation view")
    for key in ("max_nodes", "max_edges", "max_pairs"):
        _integer(analysis[key], key, 1 if key == "max_nodes" else 0)
    if analysis["group_size"] is not None:
        _integer(analysis["group_size"], "group_size", 1)
    members = analysis["group_members"]
    if members is not None:
        if type(members) is not list or not members:
            raise ValueError("group_members must be a nonempty JSON array or null")
        for member in members:
            _text(member, "group member")
        if len(set(members)) != len(members):
            raise ValueError("group members must be unique")
        if analysis["group_size"] is not None and analysis["group_size"] != len(members):
            raise ValueError("group_size must match group_members")
        analysis["group_members"] = sorted(members)
        analysis["group_size"] = len(members)
    return analysis


def _registration(registration: object, clock: dict) -> dict:
    _fields(registration, {"schema", "views"}, "network tracking registration")
    if registration["schema"] != "sociolab.network-tracking-spec.v1":
        raise ValueError("unsupported network tracking registration schema")
    if type(registration["views"]) is not list or not 1 <= len(registration["views"]) <= 16:
        raise ValueError("tracking requires between 1 and 16 registered views")
    views, seen = [], set()
    for item in registration["views"]:
        _fields(item, {"view_id", "view", "analysis"}, "registered view")
        view_id = _text(item["view_id"], "view_id")
        if view_id in seen:
            raise ValueError("registered view IDs must be unique")
        seen.add(view_id)
        view = validate_view_spec(item["view"], clock)
        views.append({"view_id": view_id, "view": view, "analysis": _analysis(item["analysis"], view)})
    normalized = {"schema": registration["schema"], "views": views}
    content_hash(normalized)
    return normalized


def _semantic_weight(value: int | float) -> int | float:
    # Preserve exact integers, including ones too large for lossless float
    # conversion, while making the equal numeric strengths 1 and 1.0 identical.
    return int(value) if type(value) is float and value.is_integer() else value


def _fingerprints(snapshot: NetworkSnapshot) -> dict:
    value = snapshot.to_dict()
    graph = {key: value[key] for key in ("directed", "bipartite", "persons", "activities", "weight_semantics")}
    graph["edges"] = [{"source": edge["source"], "target": edge["target"], "strength": _semantic_weight(edge["strength"])}
                      for edge in value["edges"]]
    evidence = {
        "selected_records": value["provenance"]["selected_records"],
        "coverage_evidence": value["coverage"]["evidence"],
        "edge_evidence": [{key: edge[key] for key in ("source", "target", "evidence")} for edge in value["edges"]],
        "annotation_summary": value.get("annotation_summary"),
    }
    return {
        "graph": content_hash(graph), "population": content_hash(value["population"]),
        "coverage": content_hash({key: value["coverage"][key] for key in ("complete", "actors")}),
        "evidence": content_hash(evidence),
    }


def _views(dataset: EventDataset, registration: dict) -> list[dict]:
    cutoff = len(dataset.records)
    result = []
    for item in registration["views"]:
        snapshot = materialize_snapshot(dataset, item["view"], knowledge_cutoff=cutoff)
        result.append({"view_id": item["view_id"], "snapshot": snapshot.to_dict(), "fingerprints": _fingerprints(snapshot)})
    return result


def _state(dataset: EventDataset, registration: dict, views: list[dict], sequence: int, previous: str | None) -> dict:
    state = {
        "schema": "sociolab.network-tracking-state.v1", "kind": "NETWORK_TRACKING_STATE", "profile": _PROFILE,
        "sequence": sequence, "previous_state_hash": previous, "registration": registration,
        "registration_hash": content_hash(registration), "dataset": dataset.to_dict(),
        "knowledge_cutoff": len(dataset.records), "views": views, "scope": deepcopy(_SCOPE),
    }
    state["content_hash"] = content_hash(state)
    return state


def initialize_network_tracking(dataset: EventDataset, registration: dict) -> dict:
    """Create an initial immutable checkpoint, including incomplete snapshots."""
    if not isinstance(dataset, EventDataset):
        raise TypeError("network tracking requires an EventDataset")
    registered = _registration(registration, dataset.clock)
    return _state(dataset, registered, _views(dataset, registered), 0, None)


def validate_network_tracking_state(state: dict) -> dict:
    """Validate a checkpoint and replay every snapshot from its complete journal.

    Returns a fresh value. An otherwise hash-consistent edited derived snapshot
    cannot bypass source replay; retained chain ancestry is checked by the store.
    """
    _fields(state, _STATE_FIELDS, "network tracking state")
    if (state["schema"] != "sociolab.network-tracking-state.v1" or
            state["kind"] != "NETWORK_TRACKING_STATE" or state["profile"] != _PROFILE):
        raise ValueError("unsupported network tracking state schema, kind or profile")
    _hash_field(state["content_hash"], "state content_hash")
    if state["content_hash"] != content_hash({key: value for key, value in state.items() if key != "content_hash"}):
        raise ValueError("tracking state content hash does not match its contents")
    sequence = _integer(state["sequence"], "sequence")
    if sequence == 0:
        if state["previous_state_hash"] is not None:
            raise ValueError("initial tracking state must not have a predecessor")
    else:
        _hash_field(state["previous_state_hash"], "previous_state_hash")
    dataset = EventDataset.from_mapping(state["dataset"])
    if _integer(state["knowledge_cutoff"], "knowledge_cutoff") != len(dataset.records):
        raise ValueError("tracking cutoff must equal the complete retained journal head")
    normalized = _registration(state["registration"], dataset.clock)
    if content_hash(normalized) != content_hash(state["registration"]):
        raise ValueError("stored registration must be normalized")
    if state["registration_hash"] != content_hash(normalized):
        raise ValueError("registration hash does not match the fixed registered views")
    if state["scope"] != _SCOPE or content_hash(state["scope"]) != content_hash(_SCOPE):
        raise ValueError("tracking scope does not match the fixed profile")
    views = state["views"]
    if type(views) is not list or len(views) != len(normalized["views"]):
        raise ValueError("tracking state must contain every registered view in order")
    for item, declared in zip(views, normalized["views"]):
        _fields(item, {"view_id", "snapshot", "fingerprints"}, "retained view")
        if item["view_id"] != declared["view_id"]:
            raise ValueError("retained view IDs must match registration order")
        snapshot = NetworkSnapshot.from_mapping(item["snapshot"])
        expected = materialize_snapshot(dataset, declared["view"], knowledge_cutoff=state["knowledge_cutoff"])
        if snapshot.content_hash != expected.content_hash:
            raise ValueError("retained snapshot does not match replay of its registered view and journal")
        _fields(item["fingerprints"], {"graph", "population", "coverage", "evidence"}, "semantic fingerprints")
        if item["fingerprints"] != _fingerprints(expected):
            raise ValueError("snapshot semantic fingerprints do not match source replay")
    return deepcopy(state)


def _analysis_budget_exceeded(before: NetworkSnapshot, after: NetworkSnapshot, analysis: dict) -> bool:
    for snapshot in (before, after):
        data = snapshot.to_dict()
        if len(data["persons"]) + len(data["activities"]) > 200 or len(data["edges"]) > 2000:
            return True
    if before.bipartite and analysis["projection"] != "none":
        # An incidence graph under the cap can project to a dense person graph.
        # Reuse the original bounded projection instead of counting pairs with
        # a second implementation or running unbounded structural analyses.
        for snapshot in (before, after):
            projected = affiliation_report(snapshot.to_graph(), snapshot.persons,
                                           projection=analysis["projection"], max_pairs=analysis["max_pairs"])
            if len(projected["projected_edges"]) > 2000:
                return True
    return False


def _view_transition(old: dict, new: dict, analysis: dict) -> dict:
    before = NetworkSnapshot.from_mapping(old["snapshot"])
    after = NetworkSnapshot.from_mapping(new["snapshot"])
    flags = {name: old["fingerprints"][component] != new["fingerprints"][component] for name, component in (
        ("observed_graph_changed", "graph"), ("population_changed", "population"),
        ("coverage_changed", "coverage"), ("evidence_changed", "evidence"),
    )}
    observable_change = any(flags[name] for name in ("observed_graph_changed", "population_changed", "coverage_changed"))
    if not observable_change:
        comparison = {"status": "NOT_RUN", "reason": "no_observable_change"}
    elif not before.coverage_complete or not after.coverage_complete:
        comparison = {"status": "NOT_RUN", "reason": "incomplete_before_or_after_coverage"}
    elif _analysis_budget_exceeded(before, after, analysis):
        comparison = {"status": "NOT_RUN", "reason": "analysis_budget_exceeded"}
    else:
        comparison = {"status": "OK", "report": compare_snapshots(before, after, **analysis)}
    return {
        "view_id": old["view_id"], "before_snapshot_hash": before.content_hash, "after_snapshot_hash": after.content_hash,
        "before_fingerprints": deepcopy(old["fingerprints"]), "after_fingerprints": deepcopy(new["fingerprints"]),
        **flags, "before_complete": before.coverage_complete, "after_complete": after.coverage_complete,
        "comparison": comparison,
    }


def _transition(before: dict, after: dict) -> dict:
    records = after["dataset"]["records"][before["knowledge_cutoff"]:]
    source = {
        "appended_record_count": len(records),
        "new_assertion_count": sum(record["operation"] == "assert" and record["supersedes"] is None for record in records),
        "revised_assertion_count": sum(record["operation"] == "assert" and record["supersedes"] is not None for record in records),
        "retraction_count": sum(record["operation"] == "retract" for record in records),
        "first_ingest_seq": records[0]["ingest_seq"] if records else None,
        "last_ingest_seq": records[-1]["ingest_seq"] if records else None,
        "recorded_at": records[0]["recorded_at"] if records else None,
        "appended_records_hash": content_hash(records), "record_ids": [record["record_id"] for record in records],
    }
    transition = {
        "schema": "sociolab.network-tracking-transition.v1", "kind": "NETWORK_TRACKING_TRANSITION", "profile": _PROFILE,
        "status": "APPLIED" if records else "NO_NEW_RECORDS", "before_state_hash": before["content_hash"],
        "after_state_hash": after["content_hash"], "before_sequence": before["sequence"], "after_sequence": after["sequence"],
        "before_knowledge_cutoff": before["knowledge_cutoff"], "after_knowledge_cutoff": after["knowledge_cutoff"],
        "registration_hash": before["registration_hash"], "source": source,
        "views": [_view_transition(old, new, registered["analysis"]) for old, new, registered in
                  zip(before["views"], after["views"], before["registration"]["views"])],
        "scope": deepcopy(_TRANSITION_SCOPE),
    }
    transition["content_hash"] = content_hash(transition)
    return transition


def apply_network_tracking_batch(state: dict, batch: list[dict], received_at: str | None = None) -> dict:
    """Return a new checkpoint and transition; mutate nothing and persist nothing.

    An empty or fully duplicate batch preserves the state exactly. All transition
    receipt counts and hashes concern newly appended records only, so persistence
    can replay mixed duplicate/new requests from the accepted tail alone.
    """
    before = validate_network_tracking_state(state)
    dataset = EventDataset.from_mapping(before["dataset"])
    updated = ingest_records(dataset, batch, received_at=received_at)
    if updated.content_hash == dataset.content_hash:
        return {"state": before, "transition": _transition(before, before)}
    registered = deepcopy(before["registration"])
    after = _state(updated, registered, _views(updated, registered), before["sequence"] + 1, before["content_hash"])
    return {"state": after, "transition": _transition(before, after)}
