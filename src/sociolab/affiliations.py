"""Observed two-mode affiliation data, analyzed with upstream NetworkX.

The Davis Southern Women reference records women attending events. A projection
represents *inferred co-attendance*, never separately observed person-person
friendship, directed trust, message delivery or a causal effect.
"""

from __future__ import annotations

from hashlib import sha256
from importlib.metadata import version
import json

import networkx as nx
from networkx.algorithms import bipartite

from ._graphs import (
    canonical_graph, evidence_ids, integer_limit, node_ids, positive_number,
    require_unit_edges,
)


_DAVIS_REFERENCE = (
    "https://networkx.org/documentation/stable/reference/generated/"
    "networkx.generators.social.davis_southern_women_graph.html"
)
_DAVIS_CITATION = (
    "Davis, A., Gardner, B. B. & Gardner, M. R. (1941). "
    "Deep South. University of Chicago Press."
)


def affiliation_report(
    graph: nx.Graph, persons, *, projection: str = "none", max_pairs: int = 100000,
) -> dict[str, object]:
    """Preserve an observed affiliation graph and optionally project co-attendance.

    Incidences are binary. Nonunit strength/weight/distance data are rejected;
    upstream count/Newman projection does not consume incidence intensities.
    Evidence is a list of source record IDs on each edge (and optionally on
    activity nodes). Projected evidence links both incidences and their activity.
    The pair budget uses a conservative upper bound before dense allocation.
    """
    if projection not in ("none", "count", "newman"):
        raise ValueError("projection must be 'none', 'count', or 'newman'")
    integer_limit(max_pairs, name="max_pairs", minimum=0)
    work = canonical_graph(graph, undirected=True)
    require_unit_edges(work)
    people = sorted(node_ids(persons, name="persons"))
    person_set = set(people)
    if not person_set <= set(work):
        raise ValueError("all persons must be present in the bipartite graph")
    activities = sorted(set(work) - person_set)
    activity_set = set(activities)
    for actor, data in work.nodes(data=True):
        expected = 0 if actor in person_set else 1
        if "bipartite" in data and (type(data["bipartite"]) is not int or data["bipartite"] != expected):
            raise ValueError("bipartite node attributes disagree with the explicit person partition")
    incidence = []
    edge_evidence = {}
    for a, b, data in work.edges(data=True):
        if a in activity_set and b in person_set:
            a, b = b, a
        if a not in person_set or b not in activity_set:
            raise ValueError("every incidence must connect a person and an activity")
        evidence = evidence_ids(data.get("evidence", []))
        edge_evidence[(a, b)] = evidence
        incidence.append({"source": a, "target": b, "evidence": evidence})
    incidence.sort(key=lambda edge: (edge["source"], edge["target"]))
    if not bipartite.is_bipartite(work):
        raise ValueError("affiliation graph must be bipartite")
    activity_evidence = {
        activity: evidence_ids(work.nodes[activity].get("evidence", []), name="activity evidence")
        for activity in activities
    }
    pair_bound = min(
        len(people) * (len(people) - 1) // 2,
        sum(work.degree[a] * (work.degree[a] - 1) // 2 for a in activities),
    )
    projected_edges = []
    projected_isolates = None
    algorithm = None
    if projection != "none":
        if pair_bound > max_pairs:
            raise ValueError(
                f"projection pair upper bound {pair_bound} exceeds max_pairs={max_pairs}; "
                "request the original bipartite report or increase the explicit budget"
            )
        if projection == "count":
            projected = bipartite.weighted_projected_graph(work, people)
            algorithm = "networkx.algorithms.bipartite.weighted_projected_graph"
        else:
            projected = bipartite.collaboration_weighted_projected_graph(work, people)
            algorithm = "networkx.algorithms.bipartite.collaboration_weighted_projected_graph"
        if projected.is_directed() or set(projected) != person_set or nx.number_of_selfloops(projected):
            raise RuntimeError("NetworkX returned an invalid affiliation projection")
        if projected.number_of_edges() > max_pairs:
            raise RuntimeError("NetworkX projection exceeded the declared pair bound")
        for a, b, data in projected.edges(data=True):
            if b < a:
                a, b = b, a
            strength = data["weight"]
            positive_number(strength, name="projected strength")
            if projection == "count" and type(strength) is not int:
                raise RuntimeError("NetworkX co-attendance count must be an integer")
            shared = sorted(set(work[a]) & set(work[b]))
            evidence = set()
            for activity in shared:
                evidence.update(edge_evidence[(a, activity)])
                evidence.update(edge_evidence[(b, activity)])
                evidence.update(activity_evidence[activity])
            projected_edges.append({
                "source": a, "target": b, "strength": strength,
                "activities": shared, "evidence": sorted(evidence),
            })
        projected_edges.sort(key=lambda edge: (edge["source"], edge["target"]))
        projected_isolates = sorted(nx.isolates(projected))
    return {
        "kind": "AFFILIATION_RESULT", "status": "OK", "engine": "networkx",
        "engine_version": version("networkx"), "directed": False, "bipartite": True,
        "persons": people, "activities": activities,
        "person_count": len(people), "activity_count": len(activities),
        "incidence_count": len(incidence), "incidence_edges": incidence,
        "person_isolates": sorted(n for n in people if work.degree[n] == 0),
        "activity_details": [
            {"activity": a, "participant_count": work.degree[a], "evidence": activity_evidence[a]}
            for a in activities
        ],
        "projection": projection, "algorithm": algorithm,
        "projection_status": "NOT_REQUESTED" if projection == "none" else "OK",
        "projected_edges": projected_edges,
        "projected_edge_count": len(projected_edges) if projection != "none" else None,
        "projected_isolates": projected_isolates,
        "settings": {
            "max_pairs": max_pairs, "pair_upper_bound": pair_bound,
            "budget_method": "min(all_person_pairs, sum(activity_pairs))",
            "incidence_weight": "binary", "projection_is_observed_relation": False,
        },
        "meaning": "Derived co-attendance only; no direct interpersonal relationship is inferred",
    }


def davis_affiliation_report() -> dict[str, object]:
    """Read the *official* NetworkX Davis data and its weighted projection."""
    graph = nx.davis_southern_women_graph()
    if graph.is_directed() or graph.is_multigraph() or not bipartite.is_bipartite(graph):
        raise ValueError("Davis source must be an undirected simple bipartite graph")

    women = sorted(n for n, d in graph.nodes(data=True) if d.get("bipartite") == 0)
    events = sorted(n for n, d in graph.nodes(data=True) if d.get("bipartite") == 1)
    if (
        len(women) != 18 or len(events) != 14
        or graph.number_of_nodes() != len(women) + len(events)
        or graph.number_of_edges() != 89
    ):
        raise ValueError("unexpected published Davis actor/event counts")
    woman_ids, event_ids = set(women), set(events)
    attendance: list[list[str]] = []
    for a, b in graph.edges():
        if a in woman_ids and b in event_ids:
            attendance.append([a, b])
        elif b in woman_ids and a in event_ids:
            attendance.append([b, a])
        else:
            raise ValueError("Davis affiliation must connect a woman to an event")
    attendance.sort()

    generic = affiliation_report(graph, women, projection="count")
    if generic["projected_edge_count"] != 139:
        raise ValueError("unexpected published co-attendance projection")

    original = {"women": women, "events": events, "attendance": attendance}
    raw = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    top_attendance = sorted(women, key=lambda actor: (-graph.degree[actor], actor))[:5]
    return {
        "kind": "REFERENCE_DATASET_RESULT",
        "engine": "networkx",
        "engine_version": version("networkx"),
        "dataset_id": "davis-southern-women-1941",
        "source_record_hash": "sha256:" + sha256(raw.encode("utf-8")).hexdigest(),
        "source_citation": _DAVIS_CITATION,
        "source_url": _DAVIS_REFERENCE,
        "origin": "published_observation_embedded_in_networkx",
        "relation": "undirected_observed_person_event_attendance",
        "directed": False,
        "bipartite": True,
        "person_count": len(women),
        "event_count": len(events),
        "observed_attendance_count": len(attendance),
        "women_projected_coattendance_edge_count": generic["projected_edge_count"],
        "projection_kind": "inferred_shared_event_count_not_observed_person_tie",
        "top_women_by_events_attended": [
            {"woman": name, "event_count": graph.degree[name]}
            for name in top_attendance
        ],
        "has_longitudinal_network_waves": False,
        "causal_effect_identified": False,
        "meaning": (
            "observed people-to-events affiliations and derived co-attendance; "
            "neither person-to-person trust nor observed transmission nor causation"
        ),
    }
