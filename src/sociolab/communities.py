"""Published karate-club graph: upstream community detection vs observed factions.

The discovered partition uses ONLY the graph topology, not the post-fission
club attribute. The labels are consulted afterward for description, not to
train the partition or claim a causal explanation of the historical split.
"""

from __future__ import annotations

from importlib.metadata import version

import networkx as nx

from .references import karate_club_report


def karate_community_report() -> dict[str, object]:
    """Run NetworkX's greedy modularity on the unweighted Karate graph."""
    source = karate_club_report()
    graph = nx.karate_club_graph()
    if graph.is_directed() or not nx.is_connected(graph):
        raise ValueError("karate community reference requires connected undirected graph")
    if graph.number_of_nodes() != source["population_size"] or graph.number_of_edges() != source["edge_count"]:
        raise ValueError("karate source changed during community analysis")

    # This call is the complete *upstream* optimization. No local partition
    # search, bespoke propagation/graph engine, or hand-coded centrality.
    detected = list(nx.community.greedy_modularity_communities(graph, weight=None))
    partition = sorted((tuple(sorted(c)) for c in detected), key=lambda c: c[0])
    if not partition or set().union(*(set(c) for c in partition)) != set(graph.nodes):
        raise RuntimeError("NetworkX returned an incomplete community partition")
    if sum(len(c) for c in partition) != graph.number_of_nodes():
        raise RuntimeError("NetworkX communities overlap in the returned partition")

    detected_score = float(nx.community.modularity(graph, partition, weight=None))
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
