"""Reproduce two synthetic design examples with the original NetworkX 3.7.

This is an experiment, not a new SocioLab event importer or network engine.
Run from the repository root and redirect stdout to a report if desired.
"""

from importlib.metadata import version
import json
from platform import python_version

import networkx as nx
from networkx.algorithms import bipartite


def describe(graph):
    groups = sorted(
        (sorted(c) for c in nx.community.greedy_modularity_communities(
            graph, weight=None, resolution=1.0,
        )), key=lambda c: c[0],
    )
    return {
        "nodes": sorted(graph),
        "edges": sorted([list(sorted(edge)) for edge in graph.edges]),
        "edge_count": graph.number_of_edges(),
        "components": sorted((sorted(c) for c in nx.connected_components(graph)),
                             key=lambda c: c[0]),
        "community_partition": groups,
        "modularity": nx.community.modularity(graph, groups, weight=None, resolution=1.0),
        "betweenness": nx.betweenness_centrality(graph, weight=None),
        "reachable_other_nodes": {
            actor: len(nx.node_connected_component(graph, actor)) - 1
            for actor in sorted(graph)
        },
    }


def main():
    if version("networkx") != "3.7":
        raise RuntimeError("This recorded experiment requires NetworkX 3.7")
    graph = nx.Graph()
    graph.add_nodes_from("ABCDEF")
    graph.add_edges_from([
        ("A", "B"), ("A", "C"), ("B", "C"),
        ("D", "E"), ("D", "F"), ("E", "F"), ("C", "D"),
    ])
    before = describe(graph)
    _, chosen = nx.prominent_group(graph, 2, weight=None, greedy=True)
    before["selected_group"] = sorted(chosen)
    before["group_betweenness"] = nx.group_betweenness_centrality(
        graph, chosen, weight=None,
    )
    after_graph = graph.copy()
    after_graph.remove_edge("C", "D")
    after = describe(after_graph)
    after["previous_group"] = sorted(chosen)
    after["previous_group_betweenness"] = nx.group_betweenness_centrality(
        after_graph, chosen, weight=None,
    )
    after["group_selection_status"] = "NOT_RUN"
    after["group_selection_reason"] = (
        "Disconnected graphs are outside the proposed initial selection scope; "
        "this is not a claim that upstream forbids every disconnected graph."
    )

    people = list("ABCDEF")
    attendance = nx.Graph()
    attendance.add_nodes_from(people, bipartite=0)
    attendance.add_node("activity:all-hands", bipartite=1)
    attendance.add_edges_from((p, "activity:all-hands") for p in people)
    projection = bipartite.weighted_projected_graph(attendance, people)
    newman = bipartite.collaboration_weighted_projected_graph(attendance, people)
    report = {
        "kind": "SYNTHETIC_DESIGN_EXPERIMENT",
        "engine": "networkx", "engine_version": version("networkx"),
        "python_version": python_version(), "empirical_claim": False,
        "scenario": "Explicit removal of the only supplied collaboration bridge",
        "community_algorithm": "networkx.community.greedy_modularity_communities",
        "community_weight": None, "community_resolution": 1.0,
        "group_selection": "networkx.prominent_group(greedy=True)",
        "before": before, "after": after,
        "large_activity_projection": {
            "people": 6, "activity_count": 1,
            "observed_attendances": attendance.number_of_edges(),
            "derived_person_pairs": projection.number_of_edges(),
            "count_weight_per_pair": projection["A"]["B"]["weight"],
            "newman_weight_per_pair": newman["A"]["B"]["weight"],
            "newman_pair_count": newman.number_of_edges(),
            "meaning": "Derived co-attendance only; no direct interpersonal tie is observed",
        },
        "interpretation": (
            "One supplied bridge removal disconnects the graph without changing this "
            "community partition. Co-attendance projection creates 15 pairs from six "
            "incidences. No language classifier or conflict-to-trust rule was applied."
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
