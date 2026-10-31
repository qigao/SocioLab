"""Published social-network references using the original upstream datasets.

No data files are copied or inferred: NetworkX supplies Zachary's observed
karate-club graph, edge weights, and post-fission group labels.
"""

from __future__ import annotations

from hashlib import sha256
from importlib.metadata import version
import json

import networkx as nx


_KARATE_CITATION = (
    "Zachary, W. W. (1977). An Information Flow Model for Conflict and "
    "Fission in Small Groups. Journal of Anthropological Research 33, 452-473."
)
_KARATE_REFERENCE = (
    "https://networkx.org/documentation/stable/reference/generated/"
    "networkx.generators.social.karate_club_graph.html"
)


def karate_club_report() -> dict[str, object]:
    """Analyze published observations in *upstream* NetworkX, not a clone.

    The original graph is undirected. The club label is post-fission outcome,
    not a baseline Agent attribute. Neither friendships nor post-fission
    labels identify experimental transmission, private trust or causality.
    """
    graph = nx.karate_club_graph()
    if graph.is_directed() or graph.is_multigraph():
        raise ValueError("Zachary source is an undirected simple graph")
    if graph.number_of_nodes() != 34 or graph.number_of_edges() != 78:
        raise ValueError("unexpected published Zachary reference structure")

    actors = sorted(graph.nodes())
    clubs: dict[str, str] = {}
    for actor in actors:
        club = graph.nodes[actor].get("club")
        if club not in {"Officer", "Mr. Hi"}:
            raise ValueError("missing/invalid post-fission club outcome")
        clubs[str(actor)] = club

    edges: list[list[int]] = []
    for left, right, data in graph.edges(data=True):
        weight = data.get("weight")
        if type(weight) is not int or weight <= 0:
            raise ValueError("published interaction-context weight must be positive integer")
        edges.append([min(left, right), max(left, right), weight])
    edges.sort()

    source_record = {
        "actors": actors,
        "post_fission_club": clubs,
        "undirected_interaction_context_edges": edges,
    }
    canonical = json.dumps(
        source_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    centrality = nx.betweenness_centrality(graph, normalized=True, weight=None)
    top_betweenness = sorted(centrality, key=lambda n: (-centrality[n], n))[:5]

    return {
        "kind": "REFERENCE_DATASET_RESULT",
        "engine": "networkx",
        "engine_version": version("networkx"),
        "dataset_id": "zachary-karate-club-1977",
        "source_citation": _KARATE_CITATION,
        "source_url": _KARATE_REFERENCE,
        "source_record_hash": "sha256:" + sha256(canonical.encode("utf-8")).hexdigest(),
        "origin": "published_observation_embedded_in_networkx",
        "relation": "undirected_observed_social_interaction",
        "directed": False,
        "weighted_edge_semantics": "number_of_interaction_contexts",
        "population_size": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "connected_component_count": nx.number_connected_components(graph),
        "post_fission_club_counts": {
            club: sum(c == club for c in clubs.values())
            for club in ("Mr. Hi", "Officer")
        },
        "top_unweighted_betweenness": [
            {"actor": str(actor), "score": centrality[actor]}
            for actor in top_betweenness
        ],
        "has_longitudinal_waves": False,
        "post_fission_club_is_baseline_covariate": False,
        "meaning": (
            "observational reference; undirected contacts are neither directed "
            "trust nor actual V19 message deliveries; no causal effect identified"
        ),
    }
