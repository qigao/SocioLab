"""Small, read-only, versioned input contract; no network algorithm lives here."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json

import networkx as nx

SCHEMA = "sociolab.network.v1"
ORIGINS = frozenset({"synthetic", "external_observation", "simulation_export"})
RELATIONS = frozenset({"contact_opportunity", "trust", "realized_transmission"})
_FIELDS = frozenset({
    "schema", "dataset_id", "origin", "source_revision", "time_index",
    "relation", "actors", "edges",
})


def _nonempty(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonempty, whitespace-trimmed text")
    return value


@dataclass(frozen=True)
class NetworkDataset:
    dataset_id: str
    origin: str
    source_revision: str
    time_index: int
    relation: str
    actors: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _nonempty(self.dataset_id, "dataset_id")
        _nonempty(self.source_revision, "source_revision")
        if self.origin not in ORIGINS:
            raise ValueError("unknown source origin")
        if self.relation not in RELATIONS:
            raise ValueError("unknown directed relation")
        if type(self.time_index) is not int or self.time_index < 0:
            raise ValueError("time_index must be a nonnegative integer")
        if type(self.actors) is not tuple or not self.actors:
            raise ValueError("actors must be a nonempty tuple")
        for actor in self.actors:
            _nonempty(actor, "actor")
        if self.actors != tuple(sorted(set(self.actors))):
            raise ValueError("actors must be unique and canonically ordered")
        if type(self.edges) is not tuple:
            raise ValueError("edges must be a tuple")
        for edge in self.edges:
            if type(edge) is not tuple or len(edge) != 2:
                raise ValueError("each directed edge must be a (source, target) tuple")
            if edge[0] not in self.actors or edge[1] not in self.actors:
                raise ValueError("edge references an unknown actor")
            if edge[0] == edge[1]:
                raise ValueError("self-loop edges are not admitted by this input contract")
        if self.edges != tuple(sorted(set(self.edges))):
            raise ValueError("directed edges must be unique and canonically ordered")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NetworkDataset:
        if type(data) is not dict or set(data) != _FIELDS:
            raise ValueError("network dataset requires precisely the v1 schema fields")
        if data["schema"] != SCHEMA:
            raise ValueError("unsupported network dataset schema")
        if type(data["actors"]) is not list or type(data["edges"]) is not list:
            raise ValueError("actors and edges must be JSON arrays")
        if any(type(item) is not list or len(item) != 2 for item in data["edges"]):
            raise ValueError("each edge must be a JSON pair")
        return cls(
            data["dataset_id"], data["origin"], data["source_revision"],
            data["time_index"], data["relation"], tuple(data["actors"]),
            tuple(tuple(item) for item in data["edges"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "dataset_id": self.dataset_id,
            "origin": self.origin,
            "source_revision": self.source_revision,
            "time_index": self.time_index,
            "relation": self.relation,
            "actors": list(self.actors),
            "edges": [list(item) for item in self.edges],
        }

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()

    def to_graph(self) -> nx.DiGraph:
        """Hand the exact graph to NetworkX or another upstream library."""
        graph = nx.DiGraph()
        graph.add_nodes_from(self.actors)
        graph.add_edges_from(self.edges)
        return graph


def load_network(path: str | Path) -> NetworkDataset:
    with Path(path).open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    return NetworkDataset.from_mapping(data)
