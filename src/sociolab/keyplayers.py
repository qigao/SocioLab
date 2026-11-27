"""Thin unweighted group-betweenness adapters, with explicit selection scope.

Selection is a greedy structural heuristic, not causal influence or the full
Borgatti KPP family. Directed/disconnected candidate scoring is separate from
selection: pinned NetworkX prominent_group fails on some directed graphs.
"""

from __future__ import annotations

from importlib.metadata import version
from math import isfinite

import networkx as nx

from ._graphs import canonical_graph, integer_limit, node_ids, require_unit_edges
from .references import karate_club_report


def score_key_group(graph: nx.Graph, members) -> dict[str, object]:
    """Score the specified group with upstream unweighted group betweenness.

    Directed and disconnected simple graphs are allowed. At least two nodes
    must remain outside the group for the declared normalization. An absent
    member is an error: never silently score only the surviving subgroup.
    """
    work = canonical_graph(graph)
    require_unit_edges(work)
    members = sorted(node_ids(members, name="group members"))
    if not members or len(members) > len(work) - 2:
        raise ValueError("group must be nonempty and leave at least two outside nodes")
    if not set(members) <= set(work):
        raise ValueError("every group member must be present in the graph")
    measured = float(nx.group_betweenness_centrality(
        work, members, normalized=True, weight=None, endpoints=False,
    ))
    if not isfinite(measured) or measured < -1e-12 or measured > 1 + 1e-12:
        raise RuntimeError("NetworkX returned invalid normalized group betweenness")
    return {
        "kind": "GROUP_SCORE", "status": "OK", "engine": "networkx",
        "engine_version": version("networkx"),
        "algorithm": "networkx.group_betweenness_centrality",
        "objective": "normalized_unweighted_group_betweenness",
        "members": members, "score": measured, "group_size": len(members),
        "node_count": len(work), "edge_count": work.number_of_edges(),
        "outside_node_count": len(work) - len(members), "directed": work.is_directed(),
        "settings": {"weight": None, "normalized": True, "endpoints": False},
    }


def select_key_group(
    graph: nx.Graph, group_size: int = 2, *, excluded=(),
    max_nodes: int = 200, max_edges: int = 2000,
) -> dict[str, object]:
    """Select a small group via the real upstream greedy prominent_group search.

    Admission is connected, simple, undirected and unweighted. Explicit nonunit
    strength/weight/distance attributes are rejected, never silently discarded.
    The requested resource limits are recorded and checked before optimization.
    Nonempty exclusions are outside this first scope: NetworkX 3.7's search
    returned inconsistent scores on a connected six-node string-ID graph with
    an excluded candidate. No relabeling or replacement optimizer hides that bug.
    """
    integer_limit(max_nodes, name="max_nodes")
    integer_limit(max_edges, name="max_edges", minimum=0)
    integer_limit(group_size, name="group_size")
    work = canonical_graph(graph, undirected=True)
    require_unit_edges(work)
    if len(work) > max_nodes or work.number_of_edges() > max_edges:
        raise ValueError("graph exceeds the declared group-selection computation budget")
    if group_size > min(4, len(work) - 2):
        raise ValueError("group_size must be <= min(4, number of nodes - 2)")
    if not nx.is_connected(work):
        raise ValueError("group selection requires a connected graph")
    excluded = sorted(node_ids(excluded, name="excluded nodes"))
    if not set(excluded) <= set(work):
        raise ValueError("excluded nodes must be present in the graph")
    if len(work) - len(excluded) < group_size:
        raise ValueError("not enough eligible candidates for the requested group_size")
    if excluded:
        raise ValueError(
            "nonempty excluded is unsupported: pinned NetworkX 3.7 prominent_group "
            "has a reproduced exclusion-related selection-score inconsistency"
        )
    upstream_score, members = nx.prominent_group(
        work, group_size, C=excluded or None, greedy=True,
        normalized=True, weight=None, endpoints=False,
    )
    if (len(members) != group_size or len(set(members)) != group_size
            or not set(members) <= set(work) - set(excluded)):
        raise RuntimeError("NetworkX prominent_group returned invalid members")
    result = score_key_group(work, members)
    upstream_score = float(upstream_score)
    if not isfinite(upstream_score) or abs(upstream_score - result["score"]) > 0.011:
        raise RuntimeError("upstream search and group-centrality disagreement")
    result.update({
        "kind": "GROUP_SELECTION", "algorithm": "networkx.prominent_group",
        "selection": "greedy_heuristic", "global_optimum_claim": False,
        "selection_score_rounded": upstream_score,
        "settings": {
            **result["settings"], "greedy": True, "excluded": excluded,
            "max_nodes": max_nodes, "max_edges": max_edges,
        },
    })
    return result


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

    # This reference explicitly studies unweighted topology, even though the
    # published dataset also contains interaction-context counts. Make that
    # transformation here rather than weakening generic weighted-input checks.
    topology = nx.Graph()
    topology.add_nodes_from(graph)
    topology.add_edges_from(graph.edges())
    generic = select_key_group(topology, group_size)
    members = generic["members"]
    upstream_score = generic["selection_score_rounded"]
    measured = generic["score"]

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
