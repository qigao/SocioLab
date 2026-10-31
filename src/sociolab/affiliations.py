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


_DAVIS_REFERENCE = (
    "https://networkx.org/documentation/stable/reference/generated/"
    "networkx.generators.social.davis_southern_women_graph.html"
)
_DAVIS_CITATION = (
    "Davis, A., Gardner, B. B. & Gardner, M. R. (1941). "
    "Deep South. University of Chicago Press."
)


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

    projection = bipartite.weighted_projected_graph(graph, women)
    if projection.is_directed() or set(projection.nodes) != woman_ids:
        raise ValueError("upstream women projection has invalid actor roster")
    if projection.number_of_edges() != 139:
        raise ValueError("unexpected published co-attendance projection")
    if any(
        type(data.get("weight")) is not int or data["weight"] <= 0
        for _, _, data in projection.edges(data=True)
    ):
        raise ValueError("co-attendance counts must be positive integers")

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
        "women_projected_coattendance_edge_count": projection.number_of_edges(),
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
