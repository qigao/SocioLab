"""Upstream NetworkX group-betweenness study on one published social graph.

This is NOT Borgatti's entire KPP-Pos/KPP-Neg family and does not estimate
causal influence.  NetworkX 3.6.1 has a known group-centrality defect on
non-strongly-connected directed graphs, so we do not expose a generic
DiGraph adapter here.  See networkx/networkx#8559.
"""

from __future__ import annotations

from importlib.metadata import version

import networkx as nx

from .references import karate_club_report


def karate_keyplayers_report(group_size: int = 2) -> dict[str, object]:
    """Use NetworkX's greedy prominent-group algorithm on Karate Club.

    The upstream search returns a rounded objective.  Recompute the chosen
    group's centrality with the upstream exact group-betweenness API, without
    independently implementing a network algorithm.
    """
    if type(group_size) is not int or not 1 <= group_size <= 4:
        raise ValueError("group_size must be an integer in [1, 4]")

    source = karate_club_report()
    graph = nx.karate_club_graph()
    if graph.is_directed() or not nx.is_connected(graph):
        raise ValueError("the qualified key-player reference must be connected and undirected")

    upstream_score, members = nx.prominent_group(
        graph, group_size, greedy=True, normalized=True, weight=None,
    )
    if (
        len(members) != group_size
        or len(set(members)) != group_size
        or any(actor not in graph for actor in members)
    ):
        raise RuntimeError("upstream prominent_group returned invalid members")

    measured = nx.group_betweenness_centrality(
        graph, members, normalized=True, weight=None,
    )
    # NetworkX 3.6 rounds the selection score to two decimal places; do not
    # mistake that coarse value for the unrounded group-centrality measure.
    if abs(float(upstream_score) - float(measured)) > 0.011:
        raise RuntimeError("upstream search and group-centrality disagreement")

    return {
        "kind": "REFERENCE_MODEL_RESULT",
        "engine": "networkx",
        "engine_version": version("networkx"),
        "dataset_id": source["dataset_id"],
        "source_record_hash": source["source_record_hash"],
        "origin": source["origin"],
        "relation": source["relation"],
        "directed": False,
        "objective": "normalized_unweighted_group_betweenness",
        "algorithm": "networkx.prominent_group",
        "selection": "greedy_heuristic",
        "global_optimum_claim": False,
        "group_size": group_size,
        "selected_actor_ids": [str(actor) for actor in sorted(members)],
        "upstream_selection_score": float(upstream_score),
        "upstream_group_betweenness": float(measured),
        "meaning": (
            "task-specific group betweenness on observed undirected ties; "
            "not full Borgatti KPP, not social power or causal influence"
        ),
    }
