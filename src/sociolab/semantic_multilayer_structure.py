"""Layer-specific descriptive structure of selected synthetic expression views.

No completeness, causal influence, observed tie or diffusion claim is made
for the language-derived graphs.
"""
from math import isfinite

import networkx as nx

from .changes import compare_snapshots, _structure, _groups
from .communities import community_report, compare_communities
from .semantic_actions import ACTIONS
from .semantic_llm import _digest
from .semantic_multilayer import build_multilayer_frame, _compare_frames
from .snapshots import NetworkSnapshot


def _ids(values, label, *, nonempty=True):
    if (type(values) is not list or (nonempty and not values) or
            any(type(v) is not str or not v.strip() or v.strip() != v for v in values) or
            len(set(values)) != len(values)):
        raise ValueError("explicit distinct " + label + " required")
    return sorted(values)


def _cohort(dataset, cutoff, actors):
    entities, identities = dataset.entities_at(cutoff), dataset.identity_map_at(cutoff)
    if any(entities.get(a) != "person" or identities.get(a, a) != a for a in actors):
        raise ValueError("expression cohort must contain known canonical persons at both prefixes")


def _not_run(reason):
    return {"status": "NOT_RUN", "reason": reason}


def _expression_graph(frame, actors, action):
    """The explicit cohort is a fixed analysis denominator, not a roster claim."""
    graph = nx.DiGraph()
    graph.add_nodes_from(actors)
    selected, excluded = [], []
    for e in frame["expression"]["edges"]:
        if e["layer"] != "PERSON_PERSON" or e["action"] != action:
            continue
        a, b = e["source"]["id"], e["target"]["id"]
        if a not in graph or b not in graph:
            excluded.extend(e["event_ids"])
            continue
        selected.extend(e["event_ids"])
        graph.add_edge(a, b, strength=e["event_count"], evidence=tuple(e["event_ids"]))
    return graph, sorted(selected), sorted(excluded)


def _topic_profile(frame, actors, action):
    """Bipartite counts only; do not project shared topics into person ties."""
    graph = nx.DiGraph()
    graph.add_nodes_from(("person", a) for a in actors)
    selected, excluded = [], []
    for e in frame["expression"]["edges"]:
        if e["layer"] != "PERSON_TOPIC" or e["action"] != action:
            continue
        actor, topic = e["source"]["id"], e["target"]["id"]
        if actor not in actors:
            excluded.extend(e["event_ids"])
            continue
        graph.add_edge(("person", actor), ("topic", topic), strength=e["event_count"])
        selected.extend(e["event_ids"])
    return {"person_counts": {a: {"distinct_selected_topics": graph.out_degree(("person", a)),
        "selected_expression_count": graph.out_degree(("person", a), weight="strength")} for a in actors},
        "topics": [{"topic_id": t, "distinct_selected_actors": graph.in_degree(("topic", t)),
            "selected_expression_count": graph.in_degree(("topic", t), weight="strength")}
            for t in sorted(n[1] for n in graph if n[0] == "topic")],
        "selected_event_ids": sorted(selected), "outside_cohort_event_ids": sorted(excluded),
        "person_projection": "NOT_REQUESTED_SHARED_TOPIC_IS_NOT_A_TIE"}


def _centrality(graph):
    # Counts are never used as distances. Explicitly describe unweighted
    # structural paths in this selected view, not communication transmission.
    return {a: {"in_neighbors": graph.in_degree(a), "out_neighbors": graph.out_degree(a),
        "in_expression_count": graph.in_degree(a, weight="strength"),
        "out_expression_count": graph.out_degree(a, weight="strength"),
        "unweighted_betweenness": value}
        for a, value in sorted(nx.betweenness_centrality(graph, normalized=True, weight=None).items())}


def _topology(graph):
    copy = nx.DiGraph()
    copy.add_nodes_from(graph)
    copy.add_edges_from(graph.edges())
    return copy


def _expression_analysis(left, right, actors, action, *, seed, resolution, group_members,
        max_nodes, max_edges):
    old, old_ids, old_excluded = _expression_graph(left, actors, action)
    new, new_ids, new_excluded = _expression_graph(right, actors, action)
    topic = {"before": _topic_profile(left, actors, action),
             "after": _topic_profile(right, actors, action)}
    result = {"action": action, "fixed_cohort": actors,
        "coverage": "SELECTED_CANDIDATES_NOT_POPULATION_COMPLETE",
        "selected_event_ids": {"before": old_ids, "after": new_ids},
        "outside_cohort_event_ids": {"before": old_excluded, "after": new_excluded},
        "person_topic": topic}
    if any(g.number_of_nodes() > max_nodes or g.number_of_edges() > max_edges for g in (old, new)):
        result["person_person"] = _not_run("expression_structure_budget_exceeded")
        return result
    before = community_report(old, algorithm="louvain", seed=seed, resolution=resolution, weight="strength")
    after = community_report(new, algorithm="louvain", seed=seed, resolution=resolution, weight="strength")
    # The fixed selected cohort supplies a common analysis denominator.
    # This does not establish real-world common observation coverage.
    lineage = compare_communities(before["communities"], after["communities"], observable=actors)
    first, second = _centrality(old), _centrality(new)
    if group_members is None:
        groups = _not_run("explicit_group_not_requested")
    else:
        groups = _groups(_topology(old), _topology(new), size=len(group_members),
            members=group_members, max_nodes=max_nodes, max_edges=max_edges)
    result["person_person"] = {"status": "OK", "structure": {"before": _structure(old), "after": _structure(new)},
        "communities": {"before": before, "after": after, "lineage": lineage,
            "meaning": "partition of selected action-count topology only"},
        "centrality": {"before": first, "after": second,
            "delta": {a: {k: second[a][k] - first[a][k] for k in first[a]} for a in actors},
            "distance": "UNWEIGHTED"},
        "key_groups": groups, "group_graph": "EXPLICIT_UNWEIGHTED_EXPRESSION_TOPOLOGY",
        "isolate_meaning": "no selected in-cohort edge, not observed social isolation"}
    return result


def compare_multilayer_structure(dataset, store, *, before, after, actors, actions,
        seed, resolution, max_nodes, max_edges, expression_group_members=None,
        attendance_group_size=None):
    """Analyze each requested layer independently; do not combine scores."""
    actors = _ids(actors, "expression cohort")
    actions = _ids(actions, "expression actions")
    if not set(actions) <= set(ACTIONS):
        raise ValueError("unknown expression action")
    if type(seed) is not int or seed < 0:
        raise ValueError("explicit nonnegative community seed required")
    if type(resolution) not in (int, float) or not isfinite(resolution) or resolution <= 0:
        raise ValueError("positive finite community resolution required")
    if type(max_nodes) is not int or max_nodes < 1 or type(max_edges) is not int or max_edges < 0:
        raise ValueError("explicit structure budgets required")
    if expression_group_members is not None:
        expression_group_members = _ids(expression_group_members, "expression group members")
        if not set(expression_group_members) <= set(actors) or len(expression_group_members) > len(actors)-2:
            raise ValueError("expression group must be within cohort and leave two outside nodes")
    if attendance_group_size is not None and (type(attendance_group_size) is not int or attendance_group_size < 1):
        raise ValueError("positive attendance group size required")
    left, right = (build_multilayer_frame(dataset, store, **spec) for spec in (before, after))
    change = _compare_frames(dataset, left, right)
    for frame in (left, right):
        _cohort(dataset, frame["journal_cutoff"], actors)
    expression = [_expression_analysis(left, right, actors, action, seed=seed,
        resolution=resolution, group_members=expression_group_members,
        max_nodes=max_nodes, max_edges=max_edges) for action in actions]

    # The attendance analysis uses the native complete-coverage population,
    # not the selected expression cohort. Never compare their scores as if
    # the denominators or edge measurements were interchangeable.
    old = NetworkSnapshot.from_mapping(left["participation"])
    new = NetworkSnapshot.from_mapping(right["participation"])
    projection = left["settings"]["affiliation_projection"]
    if not (old.coverage_complete and new.coverage_complete):
        attendance = _not_run("incomplete_declared_participation_coverage")
    elif projection != "none" and any(
            len(f["affiliation"]["persons"]) > max_nodes or f["affiliation"]["projected_edge_count"] > max_edges
            for f in (left, right)):
        attendance = _not_run("attendance_structure_budget_exceeded")
    else:
        attendance = compare_snapshots(old, new, algorithm="louvain", seed=seed,
            resolution=resolution, projection=projection, group_size=attendance_group_size,
            max_nodes=max_nodes, max_edges=max_edges, max_pairs=left["settings"]["max_pairs"])

    result = {"schema": "sociolab.multilayer-structure-change.v1",
        "profile": "SYNTHETIC_RESEARCH_ONLY",
        "change": change, "expression_analysis": expression,
        "attendance_analysis": attendance,
        "settings": {"actors": actors, "actions": actions, "seed": seed, "resolution": resolution,
            "max_nodes": max_nodes, "max_edges": max_edges, "expression_group_members": expression_group_members,
            "attendance_group_size": attendance_group_size},
        "attendance_scope": "NATIVE_DECLARED_PARTICIPATION_POPULATION_NOT_EXPRESSION_COHORT",
        "interpretation": "LAYER_SPECIFIC_SELECTED_STRUCTURE_NOT_LATENT_RELATIONSHIPS",
        "combined_score": None, "qualification_status": "NOT_ESTABLISHED",
        "causal_effect_identified": False, "future_prediction": False,
        "time_respecting_transmission_validated": False}
    result["result_hash"] = _digest(result)
    return result
