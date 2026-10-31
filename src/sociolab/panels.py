"""Strict, descriptive multi-wave network inputs for upstream Python research.

This module contains no SAOM, causal, diffusion or social influence estimator.
Absent ties are meaningful only when network_complete is explicitly true.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import json
import re

import networkx as nx

_SCHEMA = "sociolab.longitudinal.v1"
_FIELDS = frozenset({
    "schema", "dataset_id", "origin", "source_reference", "actors",
    "relation", "behavior_variable", "waves",
})
_WAVE_FIELDS = frozenset({
    "time_index", "source_revision", "network_complete", "edges", "behavior",
})
_ORIGINS = frozenset({"synthetic", "external_observation"})
_RELATION = "directed_observed_social_tie"


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be nonempty, trimmed text")
    return value


def _canonical_hash(value: dict[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NetworkWave:
    time_index: int
    source_revision: str
    network_complete: bool
    edges: tuple[tuple[str, str], ...]
    behavior: tuple[tuple[str, int | None], ...]

    def __post_init__(self) -> None:
        if type(self.time_index) is not int or self.time_index < 0:
            raise ValueError("wave time must be nonnegative integer")
        _name(self.source_revision, "source_revision")
        if type(self.network_complete) is not bool:
            raise ValueError("network completeness must be boolean")
        if type(self.edges) is not tuple or self.edges != tuple(sorted(set(self.edges))):
            raise ValueError("edges must be a unique sorted tuple")
        for edge in self.edges:
            if type(edge) is not tuple or len(edge) != 2:
                raise ValueError("edge must be a directed pair")
            _name(edge[0], "edge source")
            _name(edge[1], "edge target")
            if edge[0] == edge[1]:
                raise ValueError("self edges are not admitted")
        if type(self.behavior) is not tuple:
            raise ValueError("behaviors must be a tuple")
        if self.behavior != tuple(sorted(self.behavior)):
            raise ValueError("behaviors must be ordered by actor")
        for item in self.behavior:
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("behavior must be an actor/value pair")
            _name(item[0], "behavior actor")
            if item[1] is not None and (type(item[1]) is not int or item[1] < 0):
                raise ValueError("behavior must be nonnegative integer or null")

    def to_dict(self) -> dict[str, object]:
        return {
            "time_index": self.time_index,
            "source_revision": self.source_revision,
            "network_complete": self.network_complete,
            "edges": [list(edge) for edge in self.edges],
            "behavior": dict(self.behavior),
        }


@dataclass(frozen=True)
class LongitudinalPanel:
    dataset_id: str
    origin: str
    source_reference: str | None
    actors: tuple[str, ...]
    relation: str
    behavior_variable: str
    waves: tuple[NetworkWave, ...]

    def __post_init__(self) -> None:
        _name(self.dataset_id, "dataset_id")
        _name(self.behavior_variable, "behavior_variable")
        if type(self.origin) is not str or self.origin not in _ORIGINS:
            raise ValueError("unsupported panel origin")
        if self.origin == "synthetic":
            if self.source_reference is not None:
                raise ValueError("synthetic panel cannot claim external source")
        elif not (type(self.source_reference) is str and re.fullmatch(r"https://[^\s]+", self.source_reference)):
            raise ValueError("observed panel requires an HTTPS source")
        if self.relation != _RELATION:
            raise ValueError("unsupported relation")
        if type(self.actors) is not tuple or len(self.actors) < 2:
            raise ValueError("panel requires at least two actors")
        for actor in self.actors:
            _name(actor, "actor")
        if self.actors != tuple(sorted(set(self.actors))):
            raise ValueError("actors must be unique and sorted")
        if type(self.waves) is not tuple or len(self.waves) < 2:
            raise ValueError("panel requires at least two waves")
        actor_set = set(self.actors)
        previous_time: int | None = None
        seen_revision: set[str] = set()
        for wave in self.waves:
            if not isinstance(wave, NetworkWave):
                raise TypeError("invalid wave object")
            if previous_time is not None and wave.time_index <= previous_time:
                raise ValueError("wave time indices must strictly increase")
            previous_time = wave.time_index
            if wave.source_revision in seen_revision:
                raise ValueError("wave source revisions must be unique")
            seen_revision.add(wave.source_revision)
            if any(u not in actor_set or v not in actor_set for u, v in wave.edges):
                raise ValueError("unknown actor in wave edges")
            if tuple(actor for actor, _ in wave.behavior) != self.actors:
                raise ValueError("all actors must be explicitly recorded")

    @classmethod
    def from_mapping(cls, value: object) -> LongitudinalPanel:
        if type(value) is not dict or set(value) != _FIELDS:
            raise ValueError("longitudinal panel must use exact v1 fields")
        if value["schema"] != _SCHEMA:
            raise ValueError("unsupported longitudinal panel schema")
        dataset_id = _name(value["dataset_id"], "dataset_id")
        origin = value["origin"]
        if type(origin) is not str or origin not in _ORIGINS:
            raise ValueError("unsupported longitudinal panel origin")
        reference = value["source_reference"]
        if origin == "synthetic":
            if reference is not None:
                raise ValueError("synthetic panel cannot claim external source")
        elif not (type(reference) is str and re.fullmatch(r"https://[^\s]+", reference)):
            raise ValueError("external observation requires an HTTPS source citation")
        actors_raw = value["actors"]
        if type(actors_raw) is not list or len(actors_raw) < 2:
            raise ValueError("panel requires at least two ordered actors")
        actors = tuple(_name(actor, "actor") for actor in actors_raw)
        if actors != tuple(sorted(set(actors))):
            raise ValueError("actor identities must be unique and sorted")
        relation = value["relation"]
        if relation != _RELATION:
            raise ValueError("panel only admits directed, observed social ties")
        behavior_variable = _name(value["behavior_variable"], "behavior_variable")
        waves_raw = value["waves"]
        if type(waves_raw) is not list or len(waves_raw) < 2:
            raise ValueError("panel needs at least two observed waves")
        seen_revisions: set[str] = set()
        waves: list[NetworkWave] = []
        actor_set = set(actors)
        for raw in waves_raw:
            if type(raw) is not dict or set(raw) != _WAVE_FIELDS:
                raise ValueError("wave requires exact fields")
            index = raw["time_index"]
            if type(index) is not int or index < 0 or (waves and index <= waves[-1].time_index):
                raise ValueError("waves must have increasing nonnegative time indices")
            revision = _name(raw["source_revision"], "source_revision")
            if revision in seen_revisions:
                raise ValueError("each source wave needs a distinct revision")
            seen_revisions.add(revision)
            if type(raw["network_complete"]) is not bool:
                raise ValueError("network completeness must be explicit boolean")
            raw_edges = raw["edges"]
            if type(raw_edges) is not list:
                raise ValueError("wave edges must be a list")
            edges: list[tuple[str, str]] = []
            for raw_edge in raw_edges:
                if type(raw_edge) is not list or len(raw_edge) != 2:
                    raise ValueError("edges must be directed pairs")
                u, v = (_name(a, "edge endpoint") for a in raw_edge)
                if u not in actor_set or v not in actor_set or u == v:
                    raise ValueError("edge must connect two distinct known actors")
                edges.append((u, v))
            if tuple(edges) != tuple(sorted(set(edges))):
                raise ValueError("ties must be unique and canonical")
            behavior = raw["behavior"]
            if type(behavior) is not dict or set(behavior) != actor_set:
                raise ValueError("all actors must have explicit behavior or null")
            values = []
            for actor in actors:
                measurement = behavior[actor]
                if measurement is not None and (type(measurement) is not int or measurement < 0):
                    raise ValueError("observed behavior must be nonnegative integer or null")
                values.append((actor, measurement))
            waves.append(NetworkWave(index, revision, raw["network_complete"], tuple(edges), tuple(values)))
        return cls(dataset_id, origin, reference, actors, relation, behavior_variable, tuple(waves))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "dataset_id": self.dataset_id,
            "origin": self.origin,
            "source_reference": self.source_reference,
            "actors": list(self.actors),
            "relation": self.relation,
            "behavior_variable": self.behavior_variable,
            "waves": [wave.to_dict() for wave in self.waves],
        }

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self.to_dict())


def load_panel(path: str | Path) -> LongitudinalPanel:
    with Path(path).open("r", encoding="utf-8") as handle:
        return LongitudinalPanel.from_mapping(json.load(handle))


def longitudinal_structure_report(panel: LongitudinalPanel) -> dict[str, object]:
    """Use real NetworkX structural metrics; DO NOT infer causal influence."""
    if not isinstance(panel, LongitudinalPanel):
        raise TypeError("expected a LongitudinalPanel")
    if any(not wave.network_complete for wave in panel.waves):
        raise ValueError("unobserved ties cannot be treated as absent ties")
    records: list[dict[str, object]] = []
    prior_edges: set[tuple[str, str]] | None = None
    for wave in panel.waves:
        graph = nx.DiGraph()
        graph.add_nodes_from(panel.actors)
        graph.add_edges_from(wave.edges)
        current_edges = set(graph.edges())
        records.append({
            "time_index": wave.time_index,
            "source_revision": wave.source_revision,
            "directed_edge_count": graph.number_of_edges(),
            "directed_density": nx.density(graph),
            "weak_components": nx.number_weakly_connected_components(graph),
            "added_tie_count": None if prior_edges is None else len(current_edges - prior_edges),
            "removed_tie_count": None if prior_edges is None else len(prior_edges - current_edges),
            "missing_behavior_count": sum(v is None for _, v in wave.behavior),
        })
        prior_edges = current_edges
    return {
        "kind": "REFERENCE_MODEL_RESULT",
        "engine": "networkx",
        "engine_version": version("networkx"),
        "dataset_id": panel.dataset_id,
        "dataset_hash": panel.content_hash,
        "origin": panel.origin,
        "source_reference": panel.source_reference,
        "source_claim_verified": False,
        "relation": panel.relation,
        "behavior_variable": panel.behavior_variable,
        "actor_count": len(panel.actors),
        "wave_count": len(panel.waves),
        "waves": records,
        "causal_effect_identified": False,
        "saom_model_fitted": False,
        "meaning": "descriptive longitudinal graph metrics; no social influence or causality estimated",
    }
