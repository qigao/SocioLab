"""Only upstream NetworkX calculations; no custom centrality implementation."""

from __future__ import annotations

from importlib.metadata import version

import networkx as nx

from .dataset import NetworkDataset


def structural_report(dataset: NetworkDataset) -> dict[str, object]:
    if not isinstance(dataset, NetworkDataset):
        raise TypeError("structure analysis requires NetworkDataset")
    graph = dataset.to_graph()
    return {
        "kind": "REFERENCE_MODEL_RESULT",
        "engine": "networkx",
        "engine_version": version("networkx"),
        "dataset_id": dataset.dataset_id,
        "dataset_hash": dataset.content_hash,
        "source_origin": dataset.origin,
        "relation": dataset.relation,
        "directed": True,
        "actors": list(dataset.actors),
        "edge_count": graph.number_of_edges(),
        "weak_components": sorted(
            (sorted(group) for group in nx.weakly_connected_components(graph)),
            key=lambda item: item[0],
        ),
        "out_reachable_count": {
            actor: len(nx.descendants(graph, actor)) for actor in dataset.actors
        },
        "betweenness_centrality": {
            actor: float(value)
            for actor, value in sorted(nx.betweenness_centrality(graph).items())
        },
    }
