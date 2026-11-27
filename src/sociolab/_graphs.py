"""Validation and canonical copies for the thin NetworkX adapters."""

from __future__ import annotations

from math import isfinite
from numbers import Real

import networkx as nx


def node_ids(values, *, name: str = "nodes") -> list[str | int]:
    """Require distinct JSON scalar IDs of one type; never stringify collisions."""
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a collection of node IDs")
    try:
        result = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a collection of node IDs") from exc
    if any(type(v) not in (str, int) or (isinstance(v, str) and not v.strip())
           for v in result):
        raise ValueError(f"{name} must contain nonempty strings or plain integers")
    if len({type(v) for v in result}) > 1:
        raise ValueError(f"{name} must use one ID type, without mixing strings and integers")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicate IDs")
    return result


def canonical_graph(graph: nx.Graph, *, undirected: bool = False) -> nx.Graph:
    """Copy a simple graph in canonical order without changing the caller."""
    if not isinstance(graph, nx.Graph) or graph.is_multigraph():
        raise ValueError("analysis requires a simple NetworkX Graph or DiGraph")
    if undirected and graph.is_directed():
        raise ValueError("this analysis requires an undirected graph")
    if nx.number_of_selfloops(graph):
        raise ValueError("self-loops are outside the supported graph scope")
    nodes = sorted(node_ids(graph))
    result = nx.DiGraph() if graph.is_directed() else nx.Graph()
    result.graph.update(graph.graph)
    result.add_nodes_from((n, dict(graph.nodes[n])) for n in nodes)
    edges = []
    for a, b, data in graph.edges(data=True):
        if not graph.is_directed() and b < a:
            a, b = b, a
        edges.append((a, b, dict(data)))
    result.add_edges_from(sorted(edges, key=lambda e: (e[0], e[1])))
    return result


def positive_number(value, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        numeric = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return numeric


def require_unit_edges(graph: nx.Graph) -> None:
    """Do not silently discard explicitly weighted strength/distance data."""
    for _, _, data in graph.edges(data=True):
        for key in ("strength", "weight", "distance"):
            if key in data and positive_number(data[key], name=key) != 1:
                raise ValueError(
                    f"unweighted analysis requires unit {key}; weighted edges are unsupported"
                )


def integer_limit(value, *, name: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def evidence_ids(value, *, name: str = "evidence") -> list[str]:
    """Evidence references are IDs, never arbitrary serialized source objects."""
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{name} must be a list of nonempty evidence IDs")
    return sorted(set(value))
