"""Evidence-preserving temporal views; aggregation, not a network algorithm."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import networkx as nx

from ._json import unique_object
from .dataset import ORIGINS
from .events import EventDataset, parse_time


SCHEMA = "sociolab.snapshot.v1"
VIEW_SCHEMA = "sociolab.view.v1"
_EVENT_LAYERS = {
    "communication": {"utterance", "reply"},
    "delivery": {"delivery"},
    "cooperation_actions": {"cooperation"},
    "conflict": {"conflict"},
}


def content_hash(value: Any) -> str:
    """Hash strict, canonical JSON, never implementation-dependent repr()."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("snapshot data must contain finite UTF-8 JSON values") from error
    return "sha256:" + sha256(encoded).hexdigest()


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonempty trimmed text")
    return value


def _ids(value: Any, name: str) -> list[str]:
    if type(value) is not list:
        raise ValueError(f"{name} must be a JSON array")
    for item in value:
        _text(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicates")
    return sorted(value)


def _fields(value: Any, expected: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} requires precisely {sorted(expected)}")


def _number(value: Any, name: str, *, positive: bool = False) -> None:
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")


def validate_view_spec(value: Mapping[str, Any], clock: dict) -> dict:
    """Normalize a strict source-clock view. Empty filters mean no filter."""
    if type(value) is not dict:
        raise ValueError("view must be an object")
    view = deepcopy(value)
    for key in ("actions", "roles", "topics"):
        view.setdefault(key, [])
    mode = view.get("mode")
    if type(mode) is not str:
        raise ValueError("view mode must be text")
    temporal = {"at"} if mode == "state" else {"start", "end"}
    _fields(view, {"schema", "population", "layer", "mode", "directed",
                   "actions", "roles", "topics"} | temporal, "view")
    if view["schema"] != VIEW_SCHEMA or mode not in {"state", "events", "participation"}:
        raise ValueError("unsupported view schema or mode")
    _text(view["population"], "population")
    _text(view["layer"], "layer")
    if type(view["directed"]) is not bool:
        raise ValueError("view direction must be boolean")
    for key in ("actions", "roles", "topics"):
        view[key] = _ids(view[key], key)
    if mode == "state":
        parse_time(view["at"], clock)
        if any(view[key] for key in ("actions", "roles", "topics")):
            raise ValueError("state views do not have action/role/topic filters")
    else:
        if parse_time(view["start"], clock) >= parse_time(view["end"], clock):
            raise ValueError("window must have start < end")
    if mode == "events":
        admitted = _EVENT_LAYERS.get(view["layer"], set())
        if not view["directed"] or not view["actions"] or not set(view["actions"]) <= admitted:
            raise ValueError("event view needs directed, explicitly selected actions in its typed layer")
        if view["roles"]:
            raise ValueError("event views do not have participation role filters")
    if mode == "participation":
        if view["directed"] or view["layer"] != "participation" or view["actions"] or view["topics"]:
            raise ValueError("participation is undirected with role filters only")
    return view


def view_policy_hash(view: dict, clock: dict) -> str:
    policy = {k: v for k, v in view.items() if k not in {"at", "start", "end"}}
    return content_hash({"view": policy, "clock": clock})


class NetworkSnapshot:
    """A defensive JSON value with explicit coverage and reproducibility hashes.

    create() is for validated internal data/fixtures. from_mapping() additionally
    requires and checks serialized hashes; neither authenticates a source claim.
    """

    def __init__(self, data: dict) -> None:
        raise TypeError("use NetworkSnapshot.create() or from_mapping() for validated construction")

    @classmethod
    def create(cls, value: Mapping[str, Any]) -> NetworkSnapshot:
        if type(value) is not dict:
            raise ValueError("snapshot must be an object")
        data = deepcopy(value)
        provided_hash = data.pop("content_hash", None)
        provided_policy = data.pop("policy_hash", None)
        mode = data.get("view", {}).get("mode") if type(data.get("view")) is dict else None
        if type(mode) is not str:
            raise ValueError("snapshot needs a typed view")
        data.setdefault("weight_semantics", {"state": "observed_strength", "events": "event_count",
                                            "participation": "binary_participation"}.get(mode))
        _fields(data, {"schema", "dataset", "view", "knowledge_cutoff", "directed", "bipartite",
                       "persons", "activities", "edges", "coverage", "population", "provenance",
                       "weight_semantics"}, "snapshot")
        if data["schema"] != SCHEMA:
            raise ValueError("unsupported snapshot schema")
        ds = data["dataset"]
        _fields(ds, {"dataset_id", "origin", "source_revision", "clock", "content_hash",
                     "known_records_hash"}, "snapshot dataset")
        for key in ("dataset_id", "source_revision"):
            _text(ds[key], key)
        if type(ds["origin"]) is not str or ds["origin"] not in ORIGINS:
            raise ValueError("unknown snapshot origin")
        for key in ("content_hash", "known_records_hash"):
            if type(ds[key]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", ds[key]):
                raise ValueError("invalid dataset hash")
        data["view"] = validate_view_spec(data["view"], ds["clock"])
        view = data["view"]
        if type(data["knowledge_cutoff"]) is not int or data["knowledge_cutoff"] < 0:
            raise ValueError("knowledge cutoff must be a nonnegative integer")
        if type(data["directed"]) is not bool or data["directed"] != view["directed"]:
            raise ValueError("snapshot direction disagrees with its view")
        if type(data["bipartite"]) is not bool or data["bipartite"] != (mode == "participation"):
            raise ValueError("snapshot mode and bipartite flag disagree")
        semantics = {"state": "observed_strength", "events": "event_count", "participation": "binary_participation"}
        if data["weight_semantics"] != semantics[mode]:
            raise ValueError("snapshot weight meaning disagrees with its view")
        for key in ("persons", "activities"):
            data[key] = _ids(data[key], key)
        persons, activities = set(data["persons"]), set(data["activities"])
        if persons & activities or (not data["bipartite"] and activities):
            raise ValueError("person and activity namespaces must be disjoint")
        pop = data["population"]
        if type(pop) is not dict:
            raise ValueError("population must be an object")
        pop.setdefault("unknown_intervals", {})
        pop.setdefault("exposure_unit", "point" if mode == "state" else
                       "tick" if ds["clock"]["kind"] == "ticks" else "microsecond")
        _fields(pop, {"policy", "eligible", "absent", "unknown", "exposure", "exposure_unit",
                      "unknown_intervals"}, "population")
        expected_policy = "eligible_at" if mode == "state" else "eligible_any_overlap"
        if pop["policy"] != expected_policy:
            raise ValueError("incorrect eligible population policy")
        for key in ("eligible", "absent", "unknown"):
            pop[key] = _ids(pop[key], key)
        if set(pop["eligible"]) != persons or persons & set(pop["absent"]) or persons & set(pop["unknown"]) or set(pop["absent"]) & set(pop["unknown"]):
            raise ValueError("population categories must be disjoint and eligible must match persons")
        if type(pop["exposure"]) is not dict or set(pop["exposure"]) != persons:
            raise ValueError("exposure must describe every eligible person")
        for duration in pop["exposure"].values():
            _number(duration, "exposure", positive=True)
        unit = "point" if mode == "state" else "tick" if ds["clock"]["kind"] == "ticks" else "microsecond"
        if pop["exposure_unit"] != unit or type(pop["unknown_intervals"]) is not dict:
            raise ValueError("invalid exposure unit or unknown intervals")
        for actor, intervals in pop["unknown_intervals"].items():
            if actor not in persons | set(pop["unknown"]) or type(intervals) is not list:
                raise ValueError("unknown membership intervals reference an invalid actor")
            for interval in intervals:
                if type(interval) is not list or len(interval) != 2:
                    raise ValueError("unknown intervals must be numeric pairs")
                for boundary in interval:
                    if type(boundary) is not int or (ds["clock"]["kind"] == "ticks" and boundary < 0):
                        raise ValueError("unknown interval boundaries must use exact numeric clock units")
                if interval[0] >= interval[1]:
                    raise ValueError("unknown intervals must have positive duration")
        coverage = data["coverage"]
        _fields(coverage, {"complete", "actors", "evidence"}, "coverage")
        if type(coverage["complete"]) is not bool or type(coverage["actors"]) is not dict or set(coverage["actors"]) != persons:
            raise ValueError("coverage must describe exactly the eligible people")
        if any(type(x) is not str or x not in {"complete", "partial", "unobserved"} for x in coverage["actors"].values()):
            raise ValueError("invalid coverage status")
        if coverage["complete"] and (pop["unknown"] or any(pop["unknown_intervals"].values()) or any(x != "complete" for x in coverage["actors"].values())):
            raise ValueError("complete coverage cannot contain unknown membership or incomplete actors")
        coverage["evidence"] = _ids(coverage["evidence"], "coverage evidence")
        if coverage["complete"] and not coverage["evidence"]:
            raise ValueError("complete coverage requires explicit coverage evidence")
        prov = data["provenance"]
        _fields(prov, {"selected_records", "record_history"}, "provenance")
        prov["selected_records"] = _ids(prov["selected_records"], "selected records")
        if type(prov["record_history"]) is not list:
            raise ValueError("record history must be an array")
        history_ids, active, facts = set(), set(), {}
        for seq, record in enumerate(prov["record_history"], 1):
            _fields(record, {"record_id", "fact_id", "source_system", "operation", "supersedes", "kind", "ingest_seq"}, "history record")
            for key in ("record_id", "fact_id", "source_system", "kind"):
                _text(record[key], key)
            if record["record_id"] in history_ids or type(record["ingest_seq"]) is not int or record["ingest_seq"] != seq:
                raise ValueError("record history must be a unique contiguous receipt prefix")
            fact = (record["source_system"], record["fact_id"])
            predecessor = facts.get(fact)
            if record["supersedes"] != predecessor or type(record["operation"]) is not str or record["operation"] not in {"assert", "retract"}:
                raise ValueError("invalid revision history")
            if record["operation"] == "retract" and predecessor is None:
                raise ValueError("retraction needs a predecessor")
            history_ids.add(record["record_id"])
            active.discard(predecessor)
            if record["operation"] == "assert":
                active.add(record["record_id"])
            facts[fact] = record["record_id"]
        if len(prov["record_history"]) != data["knowledge_cutoff"]:
            raise ValueError("history must end exactly at knowledge cutoff")
        if not set(prov["selected_records"]) <= active or not set(coverage["evidence"]) <= active:
            raise ValueError("snapshot evidence must reference effective assertions")
        coverage_ids = {r["record_id"] for r in prov["record_history"] if r["kind"] == "coverage.observed"}
        if not set(coverage["evidence"]) <= coverage_ids.intersection(prov["selected_records"]):
            raise ValueError("coverage evidence must reference selected coverage.observed assertions")
        if type(data["edges"]) is not list:
            raise ValueError("edges must be an array")
        seen = set()
        for edge in data["edges"]:
            _fields(edge, {"source", "target", "strength", "evidence"}, "edge")
            a, b = edge["source"], edge["target"]
            _text(a, "edge source"); _text(b, "edge target")
            if a not in persons or b not in (activities if data["bipartite"] else persons) or a == b:
                raise ValueError("edge endpoints are outside their declared partitions")
            if not data["directed"] and not data["bipartite"] and b < a:
                a, b = b, a
                edge["source"], edge["target"] = a, b
            if (a, b) in seen:
                raise ValueError("duplicate snapshot edge")
            seen.add((a, b))
            _number(edge["strength"], "strength", positive=True)
            if mode == "participation" and edge["strength"] != 1:
                raise ValueError("participation edges are binary")
            if mode == "events" and type(edge["strength"]) is not int:
                raise ValueError("event counts must be integers")
            edge["evidence"] = _ids(edge["evidence"], "edge evidence")
            if not edge["evidence"] or not set(edge["evidence"]) <= set(prov["selected_records"]):
                raise ValueError("edge evidence must be selected effective assertions")
        data["edges"].sort(key=lambda e: (e["source"], e["target"]))
        data["policy_hash"] = view_policy_hash(view, ds["clock"])
        if provided_policy is not None and provided_policy != data["policy_hash"]:
            raise ValueError("view policy hash does not match snapshot")
        data["content_hash"] = content_hash(data)
        if provided_hash is not None and provided_hash != data["content_hash"]:
            raise ValueError("snapshot content hash does not match its contents")
        result = object.__new__(cls)
        result._json = json.dumps(data, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False)
        return result

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NetworkSnapshot:
        if type(data) is not dict or "content_hash" not in data or "policy_hash" not in data:
            raise ValueError("serialized snapshots require content and policy hashes")
        if any(type(data[key]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", data[key])
               for key in ("content_hash", "policy_hash")):
            raise ValueError("serialized snapshots require non-null SHA-256 hashes")
        return cls.create(data)

    def to_dict(self) -> dict:
        return json.loads(self._json)

    @property
    def content_hash(self) -> str: return self.to_dict()["content_hash"]
    @property
    def policy_hash(self) -> str: return self.to_dict()["policy_hash"]
    @property
    def persons(self) -> tuple[str, ...]: return tuple(self.to_dict()["persons"])
    @property
    def activities(self) -> tuple[str, ...]: return tuple(self.to_dict()["activities"])
    @property
    def directed(self) -> bool: return self.to_dict()["directed"]
    @property
    def bipartite(self) -> bool: return self.to_dict()["bipartite"]
    @property
    def coverage_complete(self) -> bool: return self.to_dict()["coverage"]["complete"]
    @property
    def view(self) -> dict: return self.to_dict()["view"]
    @property
    def layer(self) -> str: return self.view["layer"]

    def require_complete(self) -> None:
        if not self.coverage_complete:
            raise ValueError("analysis requires complete declared coverage and membership; inspect the snapshot's unknowns")

    def to_graph(self) -> nx.Graph:
        data = self.to_dict()
        graph = nx.DiGraph() if data["directed"] else nx.Graph()
        graph.add_nodes_from((n, {"kind": "person", "bipartite": 0}) for n in data["persons"])
        graph.add_nodes_from((n, {"kind": "activity", "bipartite": 1}) for n in data["activities"])
        graph.add_edges_from((e["source"], e["target"], {"strength": e["strength"], "evidence": list(e["evidence"])}) for e in data["edges"])
        graph.graph.update(snapshot_hash=data["content_hash"], layer=data["view"]["layer"],
                           weight_semantics=data["weight_semantics"])
        return graph


def load_snapshot(path: str | Path) -> NetworkSnapshot:
    with Path(path).open(encoding="utf-8") as stream:
        return NetworkSnapshot.from_mapping(json.load(stream, object_pairs_hook=unique_object))


def load_view(path: str | Path, clock: dict) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        return validate_view_spec(json.load(stream, object_pairs_hook=unique_object), clock)


class _TemporalView:
    """Source-state replay and interval selection in the declared clock."""

    def __init__(self, dataset: EventDataset, view: dict, cutoff: int | None):
        self.dataset, self.view, self.clock = dataset, view, dataset.clock
        self.records = dataset.as_known(cutoff)
        self.identities = dataset.identity_map_at(cutoff)
        self.entities = dataset.entities_at(cutoff)
        self.people = sorted({self.identity(n) for n, kind in self.entities.items() if kind == "person"})
        self.membership = {actor: [] for actor in self.people}
        for record in self.records:
            if record["kind"] in {"membership.observed", "membership.changed"} and record["payload"]["population"] == view["population"]:
                self.membership[self.identity(record["payload"]["actor"])].append(record)
        self.coverage = [r for r in self.records if r["kind"] == "coverage.observed"
                         and r["payload"]["population"] == view["population"]
                         and r["payload"]["layer"] == view["layer"]]

    def identity(self, actor: str) -> str:
        return self.identities.get(actor, actor)

    def time(self, value: Any) -> int:
        return parse_time(value, self.clock)

    def interval(self, record: dict) -> tuple[int, int | None] | None:
        interval = record["valid_interval"]
        if interval is None:
            return None
        return self.time(interval[0]), None if interval[1] is None else self.time(interval[1])

    def contains(self, record: dict, at: int) -> bool:
        interval = self.interval(record)
        if interval is None:
            return self.time(record["occurred_at"]) == at
        start, end = interval
        return start <= at and (end is None or at < end)

    def state_candidates(self, records: list[dict], at: int) -> list[dict]:
        changes = [r for r in records if r["kind"].endswith(".changed") and self.time(r["occurred_at"]) <= at]
        latest = max((self.time(r["occurred_at"]) for r in changes), default=None)
        return ([r for r in changes if self.time(r["occurred_at"]) == latest] +
                [r for r in records if not r["kind"].endswith(".changed") and self.contains(r, at)])

    def membership_at(self, actor: str, at: int) -> tuple[str, list[str]]:
        records = self.state_candidates(self.membership[actor], at)
        states = {r["payload"]["status"] for r in records}
        if len(states) > 1:
            raise ValueError(f"conflicting membership evidence for {actor}; receipt order is not state precedence")
        return next(iter(states), "unknown"), [r["record_id"] for r in records]

    def boundaries(self, records: list[dict], start: int, end: int) -> list[int]:
        values = {start, end}
        for record in records:
            interval = self.interval(record)
            times = interval if interval is not None else (self.time(record["occurred_at"]),)
            values.update(t for t in times if t is not None and start < t < end)
        return sorted(values)

    def membership_segments(self, actor: str, start: int, end: int) -> list[tuple[int, int, str, list[str]]]:
        points = self.boundaries(self.membership[actor], start, end)
        return [(a, b, *self.membership_at(actor, a)) for a, b in zip(points, points[1:])]

    def coverage_at(self, actor: str, at: int) -> tuple[str, list[str]]:
        records = [r for r in self.coverage if self.contains(r, at) and
                   actor in {self.identity(x) for x in r["payload"]["actors"]}]
        states = {r["payload"]["status"] for r in records}
        if len(states) > 1:
            raise ValueError(f"conflicting coverage evidence for {actor}")
        return next(iter(states), "unobserved"), [r["record_id"] for r in records]

    def coverage_over(self, actor: str, intervals: list[tuple[int, int]]) -> tuple[str, list[str]]:
        states, evidence = [], set()
        for start, end in intervals:
            points = self.boundaries(self.coverage, start, end)
            for a in points[:-1]:
                state, refs = self.coverage_at(actor, a)
                states.append(state)
                evidence.update(refs)
        if states and all(s == "complete" for s in states):
            status = "complete"
        elif not states or all(s == "unobserved" for s in states):
            status = "unobserved"
        else:
            status = "partial"
        return status, sorted(evidence)

    def ensure_observed(self, actors: tuple[str, ...], *, at: int | None = None,
                        intervals: list[tuple[int, int]] = ()) -> None:
        """An explicit no-observation declaration cannot hide known evidence."""
        for record in self.coverage:
            if record["payload"]["status"] != "unobserved":
                continue
            covered = {self.identity(a) for a in record["payload"]["actors"]}
            if not covered.intersection(actors):
                continue
            lo, hi = self.interval(record)
            intersects = self.contains(record, at) if at is not None else any(
                max(a, lo) < min(b, hi if hi is not None else b) for a, b in intervals)
            if intersects:
                raise ValueError("explicit unobserved coverage contradicts an effective observation in that view")


def materialize_snapshot(dataset: EventDataset, view_spec: Mapping[str, Any],
                         knowledge_cutoff: int | None = None) -> NetworkSnapshot:
    """Build a state, directed action-count, or person–activity temporal view.

    Unknown observations remain explicit. Analytical entry points require
    complete coverage; users can still inspect incomplete snapshots.
    """
    view = validate_view_spec(view_spec, dataset.clock)
    records = dataset.records
    cutoff = len(records) if knowledge_cutoff is None else knowledge_cutoff
    temporal = _TemporalView(dataset, view, cutoff)
    mode = view["mode"]
    at = temporal.time(view["at"]) if mode == "state" else None
    start = temporal.time(view["start"]) if mode != "state" else None
    end = temporal.time(view["end"]) if mode != "state" else None
    selected, coverage_evidence = set(), set()
    eligible, absent, unknown = [], [], []
    exposure, unknown_intervals, spans, coverage_actors = {}, {}, {}, {}
    for actor in temporal.people:
        if mode == "state":
            state, evidence = temporal.membership_at(actor, at)
            selected.update(evidence)
            if state == "present":
                eligible.append(actor)
                exposure[actor] = 1
                coverage_actors[actor], refs = temporal.coverage_at(actor, at)
                coverage_evidence.update(refs)
            elif state == "absent":
                absent.append(actor)
            else:
                unknown.append(actor)
        else:
            segments = temporal.membership_segments(actor, start, end)
            for _, _, _, evidence in segments:
                selected.update(evidence)
            present = [(a, b) for a, b, state, _ in segments if state == "present"]
            missing = [[a, b] for a, b, state, _ in segments if state == "unknown"]
            if present:
                eligible.append(actor)
                spans[actor] = present
                exposure[actor] = sum(b - a for a, b in present)
                coverage_actors[actor], refs = temporal.coverage_over(actor, present)
                coverage_evidence.update(refs)
            elif missing:
                unknown.append(actor)
            else:
                absent.append(actor)
            if missing:
                unknown_intervals[actor] = missing
    selected.update(coverage_evidence)
    people = set(eligible)
    edge_map: dict[tuple[str, str], dict] = {}

    def add_edge(a: str, b: str, strength: int | float, evidence: list[str], *, count: bool = False) -> None:
        if a == b:
            raise ValueError("identity mapping creates a self-relation")
        if mode != "participation" and not view["directed"] and b < a:
            a, b = b, a
        key = (a, b)
        if key not in edge_map:
            edge_map[key] = {"source": a, "target": b, "strength": strength, "evidence": set(evidence)}
        else:
            if count:
                edge_map[key]["strength"] += strength
            elif edge_map[key]["strength"] != strength:
                raise ValueError("conflicting strengths for the same observed relation")
            edge_map[key]["evidence"].update(evidence)
        selected.update(evidence)

    activities: set[str] = set()
    if mode == "state":
        by_relation: dict[tuple[str, str], list[dict]] = {}
        for record in temporal.records:
            if record["kind"] not in {"relation.observed", "relation.changed"}:
                continue
            payload = record["payload"]
            if payload["layer"] != view["layer"]:
                continue
            if payload["directed"] != view["directed"]:
                raise ValueError("a relation layer cannot silently change direction")
            a, b = temporal.identity(payload["source"]), temporal.identity(payload["target"])
            if not view["directed"] and b < a:
                a, b = b, a
            by_relation.setdefault((a, b), []).append(record)
        for (a, b), relation_records in by_relation.items():
            effective = temporal.state_candidates(relation_records, at)
            if a not in people or b not in people or not effective:
                continue
            strengths = {r["payload"]["strength"] for r in effective}
            if len(strengths) != 1:
                raise ValueError("conflicting simultaneous or overlapping relation assertions")
            evidence = [r["record_id"] for r in effective]
            temporal.ensure_observed((a, b), at=at)
            selected.update(evidence)  # explicit zero state is evidence, not an edge
            strength = next(iter(strengths))
            if strength > 0:
                add_edge(a, b, strength, evidence)
    elif mode == "events":
        for record in temporal.records:
            if record["kind"] != "interaction.observed":
                continue
            payload, when = record["payload"], temporal.time(record["occurred_at"])
            if not start <= when < end or payload["action"] not in view["actions"]:
                continue
            if view["topics"] and payload["topic"] not in view["topics"]:
                continue
            a, b = temporal.identity(payload["actor"]), temporal.identity(payload["target"])
            if a in people and b in people and all(temporal.membership_at(n, when)[0] == "present" for n in (a, b)):
                temporal.ensure_observed((a, b), at=when)
                add_edge(a, b, 1, [record["record_id"]], count=True)
    else:
        descriptions = {}
        for record in temporal.records:
            if record["kind"] != "activity.observed":
                continue
            activity = temporal.identity(record["payload"]["activity"])
            if activity in descriptions:
                raise ValueError("an activity occurrence needs one effective description; revise its fact explicitly")
            descriptions[activity] = record
            interval = temporal.interval(record)
            overlaps = (interval[0] < end and (interval[1] is None or interval[1] > start)) if interval else start <= temporal.time(record["occurred_at"]) < end
            if overlaps and record["payload"]["status"] == "held":
                activities.add(activity)
                selected.add(record["record_id"])
        participation = [r for r in temporal.records if r["kind"] == "participation.observed"
                         and temporal.identity(r["payload"]["actor"]) in people
                         and (not view["roles"] or r["payload"]["role"] in view["roles"])]

        def attendance_overlaps(first: dict, second: dict, actor: str) -> bool:
            first_interval, second_interval = temporal.interval(first), temporal.interval(second)
            if first_interval is None or second_interval is None:
                point = first if first_interval is None else second
                other = second if first_interval is None else first
                when = temporal.time(point["occurred_at"])
                return start <= when < end and temporal.contains(other, when) and temporal.membership_at(actor, when)[0] == "present"
            lo = max(start, first_interval[0], second_interval[0])
            hi = min(end, first_interval[1] if first_interval[1] is not None else end,
                     second_interval[1] if second_interval[1] is not None else end)
            return any(max(lo, a) < min(hi, b) for a, b in spans[actor])

        by_attendance = {}
        for record in participation:
            payload = record["payload"]
            actor = temporal.identity(payload["actor"])
            key = (actor, temporal.identity(payload["activity"]), payload["role"])
            for previous in by_attendance.get(key, []):
                if previous["payload"]["status"] != payload["status"] and attendance_overlaps(record, previous, actor):
                    raise ValueError("conflicting attended/absent evidence; correct or retract the source assertion")
            by_attendance.setdefault(key, []).append(record)
        for record in participation:
            payload = record["payload"]
            actor, activity = temporal.identity(payload["actor"]), temporal.identity(payload["activity"])
            interval = temporal.interval(record)
            if interval:
                a, b = max(start, interval[0]), min(end, interval[1] if interval[1] is not None else end)
                admitted = a < b and any(max(a, x) < min(b, y) for x, y in spans[actor])
            else:
                when = temporal.time(record["occurred_at"])
                admitted = start <= when < end and temporal.membership_at(actor, when)[0] == "present"
            if not admitted:
                continue
            if interval:
                observed_spans = [(max(a, x), min(b, y)) for x, y in spans[actor] if max(a, x) < min(b, y)]
                temporal.ensure_observed((actor,), intervals=observed_spans)
            else:
                temporal.ensure_observed((actor,), at=when)
            if activity not in descriptions:
                raise ValueError("participation needs an explicit activity occurrence description")
            description = descriptions[activity]
            if payload["status"] == "absent":
                selected.add(record["record_id"])
                continue
            if description["payload"]["status"] == "cancelled":
                raise ValueError("attended participation conflicts with a cancelled activity; correct or retract attendance")
            if description["payload"]["status"] != "held":
                raise ValueError("attended participation conflicts with a scheduled activity")
            activity_interval = temporal.interval(description)
            if activity_interval:
                lo, hi = activity_interval
                if interval:
                    a, b = max(a, lo), min(b, hi if hi is not None else b)
                    admitted = a < b and any(max(a, x) < min(b, y) for x, y in spans[actor])
                else:
                    admitted = lo <= when and (hi is None or when < hi)
            else:
                if interval or temporal.time(description["occurred_at"]) != when:
                    raise ValueError("point-only activity observations admit participation at that exact instant; supply an explicit activity interval")
            if admitted:
                activities.add(activity)
                add_edge(actor, activity, 1, [record["record_id"], description["record_id"]])

    # A known-empty population still needs an applicable observation declaration.
    if not eligible:
        for record in temporal.coverage:
            if mode == "state":
                applies = temporal.contains(record, at)
            else:
                interval = temporal.interval(record)
                applies = interval[0] <= start and (interval[1] is None or interval[1] >= end)
            if applies and record["payload"]["status"] == "complete":
                coverage_evidence.add(record["record_id"])
                selected.add(record["record_id"])
    complete = (bool(coverage_evidence) and not unknown and not unknown_intervals
                and all(state == "complete" for state in coverage_actors.values()))
    prefix = [r for r in records if r["ingest_seq"] <= cutoff]
    prefix_dataset = dataset.to_dict()
    prefix_dataset["records"] = prefix
    history = [{"record_id": r["record_id"], "fact_id": r["fact_id"],
                "source_system": r["source"]["system"], "operation": r["operation"],
                "supersedes": r["supersedes"], "kind": r["kind"], "ingest_seq": r["ingest_seq"]} for r in prefix]
    edges = [{**e, "evidence": sorted(e["evidence"])} for e in edge_map.values()]
    return NetworkSnapshot.create({
        "schema": SCHEMA,
        "dataset": {"dataset_id": dataset.dataset_id, "origin": dataset.origin,
                    "source_revision": dataset.source_revision, "clock": dataset.clock,
                    "content_hash": content_hash(prefix_dataset), "known_records_hash": content_hash(prefix)},
        "view": view, "knowledge_cutoff": cutoff, "directed": view["directed"],
        "bipartite": mode == "participation", "persons": eligible,
        "activities": sorted(activities), "edges": edges,
        "coverage": {"complete": complete, "actors": coverage_actors, "evidence": sorted(coverage_evidence)},
        "population": {"policy": "eligible_at" if mode == "state" else "eligible_any_overlap",
                       "eligible": eligible, "absent": absent, "unknown": unknown,
                       "exposure": exposure, "unknown_intervals": unknown_intervals},
        "provenance": {"selected_records": sorted(selected), "record_history": history},
    })
