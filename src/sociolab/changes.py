"""Descriptive changes between qualified snapshots, using upstream analyses.

Record availability, measured relations, and derived graph structure remain
separate. A change in a graph is not an identified effect of a social action.
"""

from __future__ import annotations

from importlib.metadata import version
from math import isfinite
from typing import Any

import networkx as nx

from .affiliations import affiliation_report
from .communities import community_report, compare_communities
from .keyplayers import score_key_group, select_key_group
from .snapshots import NetworkSnapshot


def _not_run(reason: str) -> dict[str, object]:
    return {"status": "NOT_RUN", "reason": reason}


def _edge_changes(
    before: list[dict[str, Any]], after: list[dict[str, Any]], *, directed: bool,
) -> dict[str, object]:
    def index(edges: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        result = {}
        for edge in edges:
            a, b = edge["source"], edge["target"]
            key = (a, b) if directed else tuple(sorted((a, b)))
            result[key] = edge
        return result

    old, new = index(before), index(after)
    shared = old.keys() & new.keys()
    reweighted, evidence_changed = [], []
    for key in sorted(shared):
        entry = {"source": key[0], "target": key[1], "before": old[key], "after": new[key]}
        if old[key]["strength"] != new[key]["strength"]:
            reweighted.append(entry)
        elif old[key].get("evidence", []) != new[key].get("evidence", []) or (
            old[key].get("activities", []) != new[key].get("activities", [])
        ):
            evidence_changed.append(entry)
    return {
        "before_edge_count": len(old),
        "after_edge_count": len(new),
        "added": [new[key] for key in sorted(new.keys() - old.keys())],
        "removed": [old[key] for key in sorted(old.keys() - new.keys())],
        "reweighted": reweighted,
        "evidence_changed": evidence_changed,
        "unchanged_edge_count": len(shared) - len(reweighted) - len(evidence_changed),
    }


def _source_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, object]:
    old = {row["record_id"]: row for row in before["provenance"]["record_history"]}
    new = {row["record_id"]: row for row in after["provenance"]["record_history"]}
    for record_id in old.keys() & new.keys():
        if old[record_id] != new[record_id]:
            raise ValueError("snapshots disagree on immutable record-history metadata")
    added = sorted(
        (new[record_id] for record_id in new.keys() - old.keys()),
        key=lambda row: (row["ingest_seq"], row["record_id"]),
    )
    selected_before = set(before["provenance"]["selected_records"])
    selected_after = set(after["provenance"]["selected_records"])
    return {
        "before_source_revision": before["dataset"]["source_revision"],
        "after_source_revision": after["dataset"]["source_revision"],
        "new_records": [r for r in added if r["operation"] == "assert" and r["supersedes"] is None],
        "corrected_records": [r for r in added if r["operation"] == "assert" and r["supersedes"] is not None],
        "retracted_records": [r for r in added if r["operation"] == "retract"],
        "records_only_before": sorted(old.keys() - new.keys()),
        "records_only_before_meaning": "receipt-prefix availability difference, not a retraction",
        "selected_evidence_added": sorted(selected_after - selected_before),
        "selected_evidence_removed": sorted(selected_before - selected_after),
        "selection_change_meaning": "may reflect window, eligibility, correction, or retraction",
    }


def _population_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, object]:
    old, new = set(before["persons"]), set(after["persons"])
    added, removed = new - old, old - new
    old_pop, new_pop = before["population"], after["population"]
    joined = added & set(old_pop["absent"])
    left = removed & set(new_pop["absent"])
    return {
        "before_person_count": len(old),
        "after_person_count": len(new),
        "common_observable": sorted(old & new),
        "eligible_added": sorted(added),
        "eligible_removed": sorted(removed),
        "joined": sorted(joined),
        "left": sorted(left),
        "newly_observed_eligible": sorted(added - joined),
        "no_longer_observed_eligible": sorted(removed - left),
        "unknown_before": old_pop["unknown"],
        "unknown_after": new_pop["unknown"],
        "before": old_pop,
        "after": new_pop,
        "meaning": "eligibility changes between views; no exact join or leave event time inferred",
    }


def _structure(graph: nx.Graph) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "OK",
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "directed": graph.is_directed(),
        "isolates": sorted(nx.isolates(graph)),
        "reachability_meaning": "structural potential, not observed or time-respecting transmission",
    }
    if graph.is_directed():
        weak = sorted(sorted(c) for c in nx.weakly_connected_components(graph))
        strong = sorted(sorted(c) for c in nx.strongly_connected_components(graph))
        result.update({
            "weak_components": weak,
            "weak_component_count": len(weak),
            "strong_components": strong,
            "strong_component_count": len(strong),
            "out_reachable_count": {actor: len(nx.descendants(graph, actor)) for actor in sorted(graph)},
            "bridges": None,
            "bridge_status": "NOT_APPLICABLE_DIRECTED",
        })
    else:
        components = sorted(sorted(c) for c in nx.connected_components(graph))
        reachable = {actor: len(c) - 1 for c in components for actor in c}
        result.update({
            "components": components,
            "component_count": len(components),
            "reachable_count": {actor: reachable[actor] for actor in sorted(reachable)},
            "bridges": sorted(sorted(edge) for edge in nx.bridges(graph)),
            "bridge_status": "OK",
        })
    return result


def _weight_scope(graph: nx.Graph) -> bool:
    return all(
        value == 1
        for _, _, attributes in graph.edges(data=True)
        for name, value in attributes.items()
        if name in {"strength", "weight", "distance"}
    )


def _score(graph: nx.Graph, members: list[str]) -> dict[str, object]:
    missing = sorted(set(members) - set(graph))
    if missing:
        return {"status": "UNAVAILABLE", "reason": "members_absent", "missing_members": missing}
    if len(members) > graph.number_of_nodes() - 2:
        return _not_run("group_size_leaves_fewer_than_two_outside_nodes")
    if not _weight_scope(graph):
        return _not_run("weighted_group_scoring_not_qualified")
    return score_key_group(graph, members)


def _select(graph: nx.Graph, size: int, *, max_nodes: int, max_edges: int) -> dict[str, object]:
    if graph.is_directed():
        return _not_run("directed_group_selection_not_qualified")
    if size > 4 or size > graph.number_of_nodes() - 2:
        return _not_run("group_size_outside_selection_scope")
    if graph.number_of_nodes() > max_nodes or graph.number_of_edges() > max_edges:
        return _not_run("group_selection_budget_exceeded")
    if not _weight_scope(graph):
        return _not_run("weighted_group_selection_not_qualified")
    if not nx.is_connected(graph):
        return _not_run("disconnected_group_selection_not_qualified")
    return select_key_group(graph, size, max_nodes=max_nodes, max_edges=max_edges)


def _groups(
    before: nx.Graph, after: nx.Graph, *, size: int | None,
    members: list[str] | None, max_nodes: int, max_edges: int,
) -> dict[str, object]:
    if size is None:
        return _not_run("group_analysis_not_requested")
    if members is None:
        original_before = _select(before, size, max_nodes=max_nodes, max_edges=max_edges)
        members = original_before.get("members")
        origin = "upstream_selected" if members is not None else "unavailable"
    else:
        original_before = _score(before, members)
        origin = "supplied"
    return {
        "requested_group_size": size,
        "objective": "normalized_unweighted_group_betweenness",
        "original": {
            "origin": origin,
            "members": members,
            "before": original_before,
            "after": _score(after, members) if members is not None else _not_run("original_group_unavailable"),
        },
        "new_selection": _select(after, size, max_nodes=max_nodes, max_edges=max_edges),
        "meaning": "structural position, not social influence or an intervention effect",
    }


def _project_graph(report: dict[str, Any]) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(report["persons"])
    for edge in report["projected_edges"]:
        graph.add_edge(
            edge["source"], edge["target"], strength=edge["strength"],
            evidence=edge["evidence"], activities=edge["activities"],
        )
    return graph


def compare_snapshots(
    before: NetworkSnapshot,
    after: NetworkSnapshot,
    *,
    algorithm: str = "louvain",
    seed: int = 0,
    resolution: float = 1.0,
    group_size: int | None = None,
    group_members: list[str] | tuple[str, ...] | None = None,
    projection: str = "none",
    max_nodes: int = 200,
    max_edges: int = 2000,
    max_pairs: int = 100000,
) -> dict[str, object]:
    """Compare the same typed view under two windows or knowledge cutoffs.

    Both snapshots must have complete coverage. Group-selection budgets do
    not change the population analyzed by the structural/community reports.
    Bipartite inputs require an explicit projection for person-only analyses.
    """
    if not isinstance(before, NetworkSnapshot) or not isinstance(after, NetworkSnapshot):
        raise TypeError("change analysis requires NetworkSnapshot inputs")
    if type(algorithm) is not str or algorithm not in {"louvain", "greedy"}:
        raise ValueError("unsupported community algorithm")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if type(resolution) not in {int, float} or not isfinite(resolution) or resolution <= 0:
        raise ValueError("resolution must be finite and positive")
    if type(projection) is not str or projection not in {"none", "count", "newman"}:
        raise ValueError("unsupported affiliation projection")
    if type(max_nodes) is not int or max_nodes < 1 or any(
        type(value) is not int or value < 0 for value in (max_edges, max_pairs)
    ):
        raise ValueError("node budget must be positive; edge and pair budgets must be nonnegative integers")
    if group_size is not None and (type(group_size) is not int or group_size < 1):
        raise ValueError("group_size must be a positive integer")
    members = None
    if group_members is not None:
        if type(group_members) not in {list, tuple} or not group_members:
            raise ValueError("group_members must be a nonempty list or tuple")
        if any(type(actor) is not str or not actor or actor.strip() != actor for actor in group_members):
            raise ValueError("group members must be nonempty actor IDs")
        if len(set(group_members)) != len(group_members):
            raise ValueError("group members must be distinct")
        members = sorted(group_members)
        if group_size is not None and group_size != len(members):
            raise ValueError("group_size disagrees with group_members")
        group_size = len(members)

    old, new = before.to_dict(), after.to_dict()
    if any(old["dataset"][key] != new["dataset"][key] for key in ("dataset_id", "origin", "clock")):
        raise ValueError("snapshots must share dataset identity, origin, and clock")
    if before.policy_hash != after.policy_hash:
        raise ValueError("snapshots must share the same view policy")
    if before.directed != after.directed or before.bipartite != after.bipartite:
        raise ValueError("snapshot graph types must agree")
    if not before.bipartite and projection != "none":
        raise ValueError("affiliation projection requires bipartite snapshots")
    before.require_complete()
    after.require_complete()

    population = _population_changes(old, new)
    result: dict[str, Any] = {
        "kind": "DESCRIPTIVE_NETWORK_CHANGE",
        "engine": "networkx",
        "engine_version": version("networkx"),
        "inputs": {
            label: {
                "snapshot_hash": data["content_hash"],
                "policy_hash": data["policy_hash"],
                "dataset": data["dataset"],
                "view": data["view"],
                "knowledge_cutoff": data["knowledge_cutoff"],
                "coverage": data["coverage"],
                "weight_semantics": data["weight_semantics"],
            }
            for label, data in (("before", old), ("after", new))
        },
        "settings": {
            "algorithm": algorithm, "seed": seed, "resolution": resolution,
            "community_weight": "strength", "group_size": group_size,
            "group_members": members, "projection": projection,
            "group_selection_max_nodes": max_nodes,
            "group_selection_max_edges": max_edges, "max_projection_pairs": max_pairs,
        },
        "source_changes": _source_changes(old, new),
        "population": population,
        # Bipartite records retain person/activity endpoint roles even though
        # their incidence graph is undirected.
        "relations": _edge_changes(
            old["edges"], new["edges"], directed=before.directed or before.bipartite,
        ),
        "analysis_relation": old["view"]["layer"],
        "derived_projection": False,
        "causal_effect_identified": False,
        "future_prediction": False,
        "time_respecting_transmission_validated": False,
        "meaning": "descriptive changes under a fixed view policy; no causal attribution",
    }
    old_graph, new_graph = before.to_graph(), after.to_graph()
    if before.bipartite:
        old_aff = affiliation_report(old_graph, before.persons, projection=projection, max_pairs=max_pairs)
        new_aff = affiliation_report(new_graph, after.persons, projection=projection, max_pairs=max_pairs)
        result["activities"] = {
            "projection": projection, "before": old_aff, "after": new_aff,
            "before_incidence_count": len(old_aff["incidence_edges"]),
            "after_incidence_count": len(new_aff["incidence_edges"]),
            "added_activity_ids": sorted(set(after.activities) - set(before.activities)),
            "removed_activity_ids": sorted(set(before.activities) - set(after.activities)),
        }
        if projection == "none":
            reason = "person_graph_projection_not_requested"
            result["structure"] = {"before": _not_run(reason), "after": _not_run(reason)}
            result["communities"] = {
                "before": _not_run(reason), "after": _not_run(reason), "lineage": _not_run(reason),
            }
            result["key_groups"] = _not_run(reason)
            return result
        result["activities"]["projected_relation_changes"] = _edge_changes(
            old_aff["projected_edges"], new_aff["projected_edges"], directed=False,
        )
        old_graph, new_graph = _project_graph(old_aff), _project_graph(new_aff)
        result["derived_projection"] = True
        result["analysis_relation"] = "derived_co_participation"
    else:
        result["activities"] = _not_run("not_an_affiliation_view")

    result["structure"] = {"before": _structure(old_graph), "after": _structure(new_graph)}
    old_communities = community_report(old_graph, algorithm=algorithm, seed=seed, resolution=resolution, weight="strength")
    new_communities = community_report(new_graph, algorithm=algorithm, seed=seed, resolution=resolution, weight="strength")
    result["communities"] = {
        "before": old_communities,
        "after": new_communities,
        "lineage": compare_communities(
            old_communities["communities"], new_communities["communities"],
            observable=population["common_observable"],
        ),
    }
    result["key_groups"] = _groups(
        old_graph, new_graph, size=group_size, members=members,
        max_nodes=max_nodes, max_edges=max_edges,
    )
    return result
