"""Published karate-club graph: upstream community detection vs observed factions.

The discovered partition uses ONLY the graph topology, not the post-fission
club attribute. The labels are consulted afterward for description, not to
train the partition or claim a causal explanation of the historical split.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import version
from math import fsum, isfinite

import networkx as nx

from ._graphs import canonical_graph, node_ids, positive_number
from .references import karate_club_report


def _partition(groups) -> list[list[str | int]]:
    """Canonical membership sets, independent of user-supplied display labels."""
    if isinstance(groups, Mapping):
        groups = groups.values()
    if isinstance(groups, (str, bytes)):
        raise ValueError("partition must be a collection of communities")
    try:
        groups = list(groups)
    except TypeError as exc:
        raise ValueError("partition must be a collection of communities") from exc
    result = [sorted(node_ids(group, name="community members")) for group in groups]
    if any(not group for group in result):
        raise ValueError("a community must not be empty")
    node_ids([node for group in result for node in group], name="partition members")
    return sorted(result, key=tuple)


def community_report(
    graph: nx.Graph, *, algorithm: str = "louvain", seed: int = 0,
    resolution: float = 1.0, weight: str | None = "strength",
) -> dict[str, object]:
    """Run the original positive-weight community algorithm on a canonical copy.

    A missing selected weight has NetworkX's unit-weight meaning. ``weight=None``
    explicitly requests topology-only analysis. Known strength/weight attributes
    must still be positive: this is not a signed-community model. IDs retain their
    JSON scalar type; strings and integers must never be mixed within one graph.
    """
    if algorithm not in ("louvain", "greedy"):
        raise ValueError("algorithm must be 'louvain' or 'greedy'")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    resolution = positive_number(resolution, name="resolution")
    if weight is not None and (not isinstance(weight, str) or not weight.strip()):
        raise ValueError("weight must be a nonempty attribute name or None")
    work = canonical_graph(graph)
    selected_weights = []
    for _, _, data in work.edges(data=True):
        for key in {"strength", "weight", weight} - {None}:
            if key in data:
                positive_number(data[key], name=key)
        selected_weights.append(
            positive_number(data.get(weight, 1), name="selected edge weight")
            if weight is not None else 1.0
        )
    try:
        total_weight = fsum(selected_weights)
    except OverflowError as exc:
        raise ValueError("total edge weight must be finite") from exc
    if not isfinite(total_weight):
        raise ValueError("total edge weight must be finite")

    upstream_name = (
        "networkx.community.louvain_communities" if algorithm == "louvain"
        else "networkx.community.greedy_modularity_communities"
    )
    if not work:
        status, groups, modularity = "EMPTY_GRAPH", [], None
    elif not work.number_of_edges():
        status, groups, modularity = "NO_EDGES", [[n] for n in work], None
    else:
        if algorithm == "louvain":
            detected = nx.community.louvain_communities(
                work, weight=weight, resolution=resolution, seed=seed,
            )
        else:
            detected = nx.community.greedy_modularity_communities(
                work, weight=weight, resolution=resolution,
            )
        groups = _partition(detected)
        if not nx.community.is_partition(work, groups):
            raise RuntimeError("NetworkX returned an invalid community partition")
        modularity = float(nx.community.modularity(
            work, groups, weight=weight, resolution=resolution,
        ))
        if not isfinite(modularity):
            raise RuntimeError("NetworkX returned nonfinite modularity")
        status = "OK"
    return {
        "kind": "COMMUNITY_RESULT", "status": status,
        "engine": "networkx", "engine_version": version("networkx"),
        "algorithm": upstream_name, "directed": work.is_directed(),
        "node_count": len(work), "edge_count": work.number_of_edges(),
        "communities": groups, "community_count": len(groups),
        "modularity": modularity, "isolates": sorted(nx.isolates(work)),
        "settings": {
            "algorithm": algorithm, "seed": seed, "resolution": resolution,
            "weight": weight, "missing_weight": "unit",
            "node_order": list(work), "edge_order": [list(e) for e in work.edges()],
        },
    }


def compare_communities(before_partition, after_partition, *, observable=None) -> dict[str, object]:
    """Describe membership lineage; matching only determines display-ID continuity.

    Partitions are sequences of communities or mappings whose labels are ignored.
    ``observable`` is an explicit subset of common nodes, never an inferred roster.
    Every positive overlap is retained; no minimum-overlap threshold is hidden.
    Display IDs are local to this comparison, not global identities across runs.
    """
    before, after = _partition(before_partition), _partition(after_partition)
    old_nodes = {node for group in before for node in group}
    new_nodes = {node for group in after for node in group}
    node_ids(old_nodes | new_nodes, name="compared node IDs")
    common = old_nodes & new_nodes
    observed = common if observable is None else set(node_ids(observable, name="observable"))
    if not observed <= common:
        raise ValueError("observable must be a subset of nodes in both partitions")
    old_sets = [set(group) & observed for group in before]
    new_sets = [set(group) & observed for group in after]

    overlap_graph = nx.Graph()
    overlap_graph.add_nodes_from(("before", i) for i in range(len(before)))
    overlap_graph.add_nodes_from(("after", j) for j in range(len(after)))
    overlaps = []
    for i, old in enumerate(old_sets):
        for j, new in enumerate(new_sets):
            shared = old & new
            if shared:
                overlap_graph.add_edge(("before", i), ("after", j), weight=len(shared))
                overlaps.append((i, j, shared))
    matching = nx.max_weight_matching(overlap_graph, weight="weight", maxcardinality=False)
    pairs = []
    for a, b in matching:
        if a[0] == "after":
            a, b = b, a
        pairs.append((a[1], b[1]))
    pairs.sort()
    old_labels = [f"c{i}" for i in range(len(before))]
    inherited = {j: old_labels[i] for i, j in pairs}
    new_labels = []
    next_label = len(before)
    for j in range(len(after)):
        if j in inherited:
            new_labels.append(inherited[j])
        else:
            new_labels.append(f"c{next_label}")
            next_label += 1

    lineage = []
    for i, j, shared in overlaps:
        events = []
        if overlap_graph.degree[("before", i)] > 1:
            events.append("split")
        if overlap_graph.degree[("after", j)] > 1:
            events.append("merge")
        lineage.append({
            "before_id": old_labels[i], "after_id": new_labels[j],
            "before_index": i, "after_index": j, "members": sorted(shared),
            "overlap_count": len(shared),
            "jaccard": len(shared) / len(old_sets[i] | new_sets[j]),
            "retention": len(shared) / len(old_sets[i]),
            "contribution": len(shared) / len(new_sets[j]),
            "events": events or ["continuation"],
        })
    matches = [{
        "before_id": old_labels[i], "after_id": new_labels[j],
        "before_index": i, "after_index": j,
        "overlap_count": overlap_graph[("before", i)][("after", j)]["weight"],
    } for i, j in pairs]

    # These are observed equal-weight candidate choices, not a uniqueness proof
    # for the global matching. Do not claim unique identities in an ambiguous case.
    equal_candidates = []
    for node in overlap_graph:
        by_weight = {}
        for other, data in overlap_graph[node].items():
            by_weight.setdefault(data["weight"], []).append(other[1])
        for count, candidates in sorted(by_weight.items()):
            if len(candidates) > 1:
                equal_candidates.append({
                    "side": node[0], "index": node[1], "overlap_count": count,
                    "candidate_indices": sorted(candidates),
                })
    return {
        "kind": "COMMUNITY_COMPARISON",
        "status": "COMPARABLE" if observed else "NO_COMMON_OBSERVABLE",
        "engine": "networkx", "engine_version": version("networkx"),
        "before_communities": [
            {"id": old_labels[i], "members": group, "observable_members": sorted(old_sets[i])}
            for i, group in enumerate(before)
        ],
        "after_communities": [
            {"id": new_labels[j], "members": group, "observable_members": sorted(new_sets[j])}
            for j, group in enumerate(after)
        ],
        "common_observable": sorted(observed), "entered": sorted(new_nodes - old_nodes),
        "left": sorted(old_nodes - new_nodes), "unobserved_common": sorted(common - observed),
        "lineage": lineage, "matches": matches,
        "unmatched_before_ids": [old_labels[i] for i in range(len(before)) if i not in {p[0] for p in pairs}],
        "unmatched_after_ids": [new_labels[j] for j in range(len(after)) if j not in inherited],
        "membership_stability": {
            "same_partition": (
                {frozenset(group) for group in old_sets if group}
                == {frozenset(group) for group in new_sets if group}
            ) if observed else None,
            "matched_member_fraction": sum(m["overlap_count"] for m in matches) / len(observed)
            if observed else None,
        },
        "settings": {
            "matching": "networkx.max_weight_matching", "maxcardinality": False,
            "matching_weight": "integer_common_member_count", "minimum_overlap": 1,
            "fraction_population": "common_observable", "display_ids_scope": "comparison",
        },
        "matching_ambiguity": {
            "equal_weight_candidates": equal_candidates, "unique_optimum_assessed": False,
            "tie_policy": "NetworkX matching on canonical input; display names have no substantive meaning",
        },
    }


def karate_community_report() -> dict[str, object]:
    """Run NetworkX's greedy modularity on the unweighted Karate graph."""
    source = karate_club_report()
    graph = nx.karate_club_graph()
    if graph.is_directed() or not nx.is_connected(graph):
        raise ValueError("karate community reference requires connected undirected graph")
    if graph.number_of_nodes() != source["population_size"] or graph.number_of_edges() != source["edge_count"]:
        raise ValueError("karate source changed during community analysis")

    generic = community_report(graph, algorithm="greedy", weight=None)
    partition = generic["communities"]
    detected_score = generic["modularity"]
    observed = [
        {actor for actor, attr in graph.nodes(data=True) if attr.get("club") == group}
        for group in ("Mr. Hi", "Officer")
    ]
    if any(not group for group in observed) or len(set().union(*observed)) != graph.number_of_nodes():
        raise ValueError("unexpected published post-fission actor groups")
    observed_score = float(nx.community.modularity(graph, observed, weight=None))
    results = []
    for community in partition:
        members = set(community)
        results.append({
            "actors": [str(n) for n in community],
            "size": len(community),
            "post_fission_group_counts": {
                "Mr. Hi": len(members & observed[0]),
                "Officer": len(members & observed[1]),
            },
        })

    return {
        "kind": "REFERENCE_MODEL_RESULT",
        "dataset_id": source["dataset_id"],
        "source_record_hash": source["source_record_hash"],
        "source_origin": source["origin"],
        "engine": "networkx",
        "engine_version": version("networkx"),
        "algorithm": "networkx.community.greedy_modularity_communities",
        "graph_relation": "undirected_observed_social_interaction",
        "graph_weight_mode": "unweighted",
        "community_count": len(partition),
        "detected_communities": results,
        "detected_modularity": detected_score,
        "post_fission_observed_group_modularity": observed_score,
        "labels_used_for_detection": False,
        "historical_faction_labels_are_post_fission": True,
        "causal_effect_identified": False,
        "meaning": (
            "Topology-only community partition compared descriptively against "
            "post-fission groups; this does not demonstrate prediction or causation"
        ),
    }
