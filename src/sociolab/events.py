"""Versioned external observations and their as-known revision history.

This module validates and selects analytical inputs. It does not own a
social world, infer relationships, or order simultaneous actions causally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import math
import re

from ._json import unique_object
from .annotation_schema import (
    ANNOTATION_FIELDS, CONTENT_FIELDS,
    validate_annotation_payload, validate_content_payload,
)

_SCHEMA = "sociolab.events.v1"
_FIELDS = frozenset({
    "schema", "dataset_id", "origin", "source_revision", "clock", "records",
})
_RECEIPT_FIELDS = frozenset({"ingest_seq", "recorded_at"})
_RECORD_FIELDS = frozenset({
    "record_id", "fact_id", "operation", "supersedes", "kind", "occurred_at",
    "valid_interval", "source", "payload", "ingest_seq", "recorded_at",
})
_SOURCE_FIELDS = frozenset({"system", "record_id", "revision", "evidence_ref"})
_ORIGINS = frozenset({"synthetic", "external_observation", "simulation_export"})
_PAYLOAD_FIELDS = {
    "entity.observed": {"entity_id", "entity_type"},
    "identity.mapped": {"alias", "canonical"},
    "membership.observed": {"actor", "population", "status"},
    "membership.changed": {"actor", "population", "status"},
    "actor.attribute.observed": {"actor", "name", "value"},
    "activity.observed": {"activity", "status", "activity_type"},
    "participation.observed": {"actor", "activity", "role", "status"},
    "interaction.observed": {"actor", "target", "action", "topic"},
    "relation.observed": {"layer", "source", "target", "directed", "strength"},
    "relation.changed": {"layer", "source", "target", "directed", "strength"},
    "coverage.observed": {"population", "layer", "actors", "status"},
    "content.observed": CONTENT_FIELDS,
    "annotation.recorded": ANNOTATION_FIELDS,
}
_UTC_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _fields(value: object, expected: set[str] | frozenset[str], label: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{label} requires exactly its declared fields")


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{label} must be nonempty, trimmed text")
    return value


def _choice(value: object, choices: set[str] | frozenset[str], label: str) -> None:
    if type(value) is not str or value not in choices:
        raise ValueError(f"unsupported {label}")


def _canonical_json(value: object) -> str:
    try:
        result = json.dumps(value, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False)
        result.encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise ValueError("event data must contain finite UTF-8 JSON values") from error
    return result


def _utc_time(value: object) -> int:
    if type(value) is not str or _UTC_PATTERN.fullmatch(value) is None:
        raise ValueError("UTC time requires an explicit Z/+00:00 timestamp with microsecond precision or less")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid UTC timestamp") from error
    delta = instant - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _validate_clock(clock: object) -> None:
    if type(clock) is not dict:
        raise ValueError("clock must be a declared UTC or ticks object")
    kind = clock.get("kind")
    if kind == "ticks":
        _fields(clock, {"kind", "run_id"}, "ticks clock")
        _text(clock["run_id"], "clock run_id")
    elif kind == "utc":
        _fields(clock, {"kind"}, "UTC clock")
    else:
        raise ValueError("unsupported event clock")


def parse_time(value: object, clock: dict[str, object]) -> int:
    """Return exact ticks or UTC microseconds; never round a source timestamp."""
    _validate_clock(clock)
    if clock["kind"] == "utc":
        return _utc_time(value)
    if type(value) is not int or value < 0:
        raise ValueError("tick time must be a nonnegative integer")
    return value


def _nonnegative_number(value: object, label: str) -> None:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")


def _validate_payload(kind: str, payload: object) -> None:
    _fields(payload, _PAYLOAD_FIELDS[kind], f"{kind} payload")
    match kind:
        case "entity.observed":
            _text(payload["entity_id"], "entity ID")
            _choice(payload["entity_type"], {"person", "activity"}, "entity type")
        case "identity.mapped":
            _text(payload["alias"], "alias ID")
            _text(payload["canonical"], "canonical ID")
        case "membership.observed" | "membership.changed":
            _text(payload["actor"], "membership actor")
            _text(payload["population"], "population")
            _choice(payload["status"], {"present", "absent"}, "membership status")
        case "actor.attribute.observed":
            _text(payload["actor"], "attribute actor")
            _text(payload["name"], "attribute name")
            value = payload["value"]
            if value is not None and type(value) not in (str, int, float, bool):
                raise ValueError("attribute value must be a primitive JSON value")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("attribute value must be finite")
        case "activity.observed":
            _text(payload["activity"], "activity ID")
            _text(payload["activity_type"], "activity type")
            _choice(payload["status"], {"scheduled", "held", "cancelled"}, "activity status")
        case "participation.observed":
            _text(payload["actor"], "participation actor")
            _text(payload["activity"], "participation activity")
            _text(payload["role"], "participation role")
            _choice(payload["status"], {"attended", "absent"}, "attendance status")
        case "interaction.observed":
            _text(payload["actor"], "interaction actor")
            _text(payload["target"], "interaction target")
            _choice(payload["action"], {"utterance", "reply", "delivery", "cooperation", "conflict"}, "interaction action")
            if payload["topic"] is not None:
                _text(payload["topic"], "interaction topic")
        case "relation.observed" | "relation.changed":
            for field in ("layer", "source", "target"):
                _text(payload[field], f"relation {field}")
            if type(payload["directed"]) is not bool:
                raise ValueError("relation directed must be boolean")
            _nonnegative_number(payload["strength"], "relation strength")
        case "coverage.observed":
            _text(payload["population"], "coverage population")
            _text(payload["layer"], "coverage layer")
            _choice(payload["status"], {"complete", "partial", "unobserved"}, "coverage status")
            if type(payload["actors"]) is not list:
                raise ValueError("coverage actors must be a JSON array")
            for actor in payload["actors"]:
                _text(actor, "coverage actor")
            if len(set(payload["actors"])) != len(payload["actors"]):
                raise ValueError("coverage actor IDs must be unique")
        case "content.observed":
            validate_content_payload(payload)
        case "annotation.recorded":
            validate_annotation_payload(payload)


def _validate_record(record: object, clock: dict[str, object], *, raw: bool = False) -> None:
    expected = _RECORD_FIELDS - _RECEIPT_FIELDS if raw else _RECORD_FIELDS
    _fields(record, expected, "event record")
    for field in ("record_id", "fact_id"):
        _text(record[field], field)
    _choice(record["operation"], {"assert", "retract"}, "record operation")
    _choice(record["kind"], set(_PAYLOAD_FIELDS), "record kind")
    if record["supersedes"] is not None:
        _text(record["supersedes"], "supersedes")
    parse_time(record["occurred_at"], clock)
    interval = record["valid_interval"]
    if interval is not None:
        if type(interval) is not list or len(interval) != 2:
            raise ValueError("valid_interval must be null or [start,end]")
        start = parse_time(interval[0], clock)
        if interval[1] is not None and parse_time(interval[1], clock) <= start:
            raise ValueError("valid_interval end must be strictly after its start")
        if record["kind"] in {"content.observed", "annotation.recorded"}:
            raise ValueError(f"{record['kind']} requires an instantaneous record")
    _fields(record["source"], _SOURCE_FIELDS, "record source")
    for field in _SOURCE_FIELDS:
        _text(record["source"][field], f"source {field}")
    if not raw:
        if type(record["ingest_seq"]) is not int or record["ingest_seq"] < 1:
            raise ValueError("ingest_seq must be a positive integer")
        _utc_time(record["recorded_at"])
    if record["operation"] == "retract":
        if record["payload"] is not None or record["supersedes"] is None:
            raise ValueError("retraction requires a predecessor and null payload")
    else:
        _validate_payload(record["kind"], record["payload"])
        if record["kind"] in {"membership.observed", "coverage.observed"} and interval is None:
            raise ValueError(f"{record['kind']} requires a valid interval")
        if record["kind"] in {
            "entity.observed", "identity.mapped", "membership.changed",
            "relation.changed", "interaction.observed",
        } and interval is not None:
            raise ValueError(f"{record['kind']} requires an instantaneous record")
    _canonical_json(record)


def _fact_key(record: dict[str, object]) -> tuple[str, str]:
    return record["source"]["system"], record["fact_id"]


def _entity_state(active: tuple[dict[str, object], ...]) -> tuple[dict[str, str], dict[str, str]]:
    entities: dict[str, str] = {}
    direct: dict[str, str] = {}
    for record in active:
        payload = record["payload"]
        if record["kind"] == "entity.observed":
            entity_id = payload["entity_id"]
            if entity_id in entities:
                raise ValueError("an entity ID requires one active declaration")
            entities[entity_id] = payload["entity_type"]
        elif record["kind"] == "identity.mapped":
            alias = payload["alias"]
            if alias in direct:
                raise ValueError("an alias requires one active identity mapping")
            direct[alias] = payload["canonical"]
    for alias, canonical in direct.items():
        if alias not in entities or canonical not in entities:
            raise ValueError("identity mappings must reference known entities")
        if entities[alias] != entities[canonical]:
            raise ValueError("identity mappings must preserve entity type")
    resolved: dict[str, str] = {}
    for alias in direct:
        current = alias
        seen: set[str] = set()
        while current in direct:
            if current in seen:
                raise ValueError("identity mapping cycle")
            seen.add(current)
            current = direct[current]
        resolved[alias] = current
    return dict(sorted(entities.items())), dict(sorted(resolved.items()))


def _validate_historical_links(record: dict[str, object], records_by_id: dict[str, dict[str, object]]) -> None:
    """Bind to exact earlier assertions, including now-stale historical parents."""
    def target(record_id: str, kind: str) -> dict[str, object]:
        if record_id not in records_by_id:
            raise ValueError("annotation/content target must exist at an earlier receipt")
        parent = records_by_id[record_id]
        if parent["kind"] != kind or parent["operation"] != "assert":
            raise ValueError(f"annotation/content target must be an asserted {kind} record")
        return parent["payload"]

    payload = record["payload"]
    if record["kind"] == "content.observed":
        interaction = target(payload["interaction_record_id"], "interaction.observed")
        if interaction["action"] not in {"utterance", "reply"}:
            raise ValueError("content must target an utterance or reply interaction")
    elif record["kind"] == "annotation.recorded":
        content = target(payload["target_record_id"], "content.observed")
        if (payload["target_content_revision"] != content["content_revision"]
                or payload["target_content_hash"] != content["content_hash"]):
            raise ValueError("annotation must match the exact target content revision and hash")
        for span in payload["evidence"]:
            if span["end"] > content["length"][span["unit"]]:
                raise ValueError("evidence span exceeds the declared target content length")


def _validate_references(record: dict[str, object], entities: dict[str, str], identities: dict[str, str],
                         records_by_id: dict[str, dict[str, object]]) -> None:
    def entity(value: str, required: str) -> str:
        if value not in entities or entities[value] != required:
            raise ValueError(f"{record['kind']} requires a known {required}: {value}")
        return identities.get(value, value)

    kind, payload = record["kind"], record["payload"]
    if kind in {"membership.observed", "membership.changed", "actor.attribute.observed"}:
        entity(payload["actor"], "person")
    elif kind == "activity.observed":
        entity(payload["activity"], "activity")
    elif kind == "participation.observed":
        entity(payload["actor"], "person")
        entity(payload["activity"], "activity")
    elif kind == "interaction.observed":
        if entity(payload["actor"], "person") == entity(payload["target"], "person"):
            raise ValueError("interaction becomes a self-tie after identity resolution")
    elif kind in {"relation.observed", "relation.changed"}:
        if entity(payload["source"], "person") == entity(payload["target"], "person"):
            raise ValueError("relation becomes a self-tie after identity resolution")
    elif kind == "coverage.observed":
        actors = [entity(actor, "person") for actor in payload["actors"]]
        if len(set(actors)) != len(actors):
            raise ValueError("coverage actors duplicate an identity after resolution")
    elif kind == "annotation.recorded" and payload["subject"]["kind"] == "person":
        subject = entity(payload["subject"]["id"], "person")
        content = records_by_id[payload["target_record_id"]]["payload"]
        interaction = records_by_id[content["interaction_record_id"]]["payload"]
        # The historical speaker need not remain an active entity after their
        # interaction was withdrawn. Only the annotation's person subject is
        # an active entity reference; historical parent records are immutable.
        speaker = identities.get(interaction["actor"], interaction["actor"])
        if subject == speaker:
            raise ValueError("annotation person subject becomes a self-target after identity resolution")


def _validate_dataset(value: object) -> None:
    _fields(value, _FIELDS, "event dataset")
    if value["schema"] != _SCHEMA:
        raise ValueError("unsupported event dataset schema")
    _text(value["dataset_id"], "dataset_id")
    _text(value["source_revision"], "source_revision")
    _choice(value["origin"], _ORIGINS, "source origin")
    _validate_clock(value["clock"])
    if type(value["records"]) is not list:
        raise ValueError("records must be a JSON array")
    records_by_id: dict[str, dict[str, object]] = {}
    latest: dict[tuple[str, str], dict[str, object]] = {}
    entities: dict[str, str] = {}
    identities: dict[str, str] = {}
    previous_receipt: int | None = None
    for expected_seq, record in enumerate(value["records"], 1):
        _validate_record(record, value["clock"])
        if record["ingest_seq"] != expected_seq:
            raise ValueError("receipt sequences must be contiguous and ordered from 1")
        receipt = _utc_time(record["recorded_at"])
        if previous_receipt is not None and receipt < previous_receipt:
            raise ValueError("receipt timestamps must be nondecreasing")
        previous_receipt = receipt
        record_id = record["record_id"]
        if record_id in records_by_id:
            raise ValueError("record IDs must be unique in the accepted journal")
        key = _fact_key(record)
        predecessor_id = record["supersedes"]
        if predecessor_id is None:
            if key in latest:
                raise ValueError("each source fact must have one revision root")
        else:
            if predecessor_id not in records_by_id:
                raise ValueError("revision predecessor must exist at an earlier receipt")
            predecessor = records_by_id[predecessor_id]
            if _fact_key(predecessor) != key or predecessor["kind"] != record["kind"]:
                raise ValueError("revision must preserve source system, fact and kind")
            if latest[key]["record_id"] != predecessor_id:
                raise ValueError("revision branch: supersedes must reference the current head")
        if record["operation"] == "assert":
            _validate_historical_links(record, records_by_id)
        records_by_id[record_id] = record
        latest[key] = record
        if record["kind"] in {"entity.observed", "identity.mapped"}:
            active = tuple(item for item in latest.values() if item["operation"] == "assert")
            entities, identities = _entity_state(active)
            for item in active:
                _validate_references(item, entities, identities, records_by_id)
        elif record["operation"] == "assert":
            _validate_references(record, entities, identities, records_by_id)


@dataclass(frozen=True, init=False)
class EventDataset:
    """Immutable journal with fresh public dictionaries on every read."""

    _canonical: str
    _dataset_id: str
    _origin: str
    _source_revision: str
    _clock_json: str

    def __init__(self, value: dict[str, object]):
        _validate_dataset(value)
        object.__setattr__(self, "_canonical", _canonical_json(value))
        object.__setattr__(self, "_dataset_id", value["dataset_id"])
        object.__setattr__(self, "_origin", value["origin"])
        object.__setattr__(self, "_source_revision", value["source_revision"])
        object.__setattr__(self, "_clock_json", _canonical_json(value["clock"]))

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> EventDataset:
        return cls(value)

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    @property
    def origin(self) -> str:
        return self._origin

    @property
    def source_revision(self) -> str:
        return self._source_revision

    @property
    def clock(self) -> dict[str, object]:
        return json.loads(self._clock_json)

    @property
    def records(self) -> tuple[dict[str, object], ...]:
        return tuple(self.to_dict()["records"])

    def to_dict(self) -> dict[str, object]:
        return json.loads(self._canonical)

    @property
    def content_hash(self) -> str:
        return "sha256:" + sha256(self._canonical.encode("utf-8")).hexdigest()

    def as_known(self, knowledge_cutoff: int | None = None) -> tuple[dict[str, object], ...]:
        """Select effective assertions in an exact receipt prefix, not event time."""
        records = self.records
        cutoff = len(records) if knowledge_cutoff is None else knowledge_cutoff
        if type(cutoff) is not int or not 0 <= cutoff <= len(records):
            raise ValueError("knowledge cutoff must identify an existing receipt prefix")
        latest: dict[tuple[str, str], dict[str, object]] = {}
        for record in records[:cutoff]:
            latest[_fact_key(record)] = record
        return tuple(sorted(
            (record for record in latest.values() if record["operation"] == "assert"),
            key=lambda record: record["ingest_seq"],
        ))

    def entities_at(self, knowledge_cutoff: int | None = None) -> dict[str, str]:
        return _entity_state(self.as_known(knowledge_cutoff))[0]

    def identity_map_at(self, knowledge_cutoff: int | None = None) -> dict[str, str]:
        return _entity_state(self.as_known(knowledge_cutoff))[1]


def load_event_dataset(path: str | Path) -> EventDataset:
    with Path(path).open("r", encoding="utf-8") as handle:
        return EventDataset.from_mapping(json.load(handle, object_pairs_hook=unique_object))


def _source_content(record: dict[str, object]) -> str:
    return _canonical_json({key: value for key, value in record.items() if key not in _RECEIPT_FIELDS})


def ingest_records(dataset: EventDataset, raw_records: list[dict[str, object]], *,
                   received_at: str | None = None) -> EventDataset:
    """Append valid observations with importer receipts; identical IDs are idempotent."""
    if not isinstance(dataset, EventDataset):
        raise ValueError("ingestion requires an EventDataset")
    if type(raw_records) is not list:
        raise ValueError("raw records must be a JSON array")
    if received_at is None:
        received_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    _utc_time(received_at)
    value = dataset.to_dict()
    records = value["records"]
    known = {record["record_id"]: _source_content(record) for record in records}
    added = False
    for raw in raw_records:
        _validate_record(raw, value["clock"], raw=True)
        content = _source_content(raw)
        record_id = raw["record_id"]
        if record_id in known:
            if known[record_id] != content:
                raise ValueError("record ID reused with different source content")
            continue
        record = json.loads(content)
        record["ingest_seq"] = len(records) + 1
        record["recorded_at"] = received_at
        records.append(record)
        known[record_id] = content
        added = True
    return EventDataset.from_mapping(value) if added else dataset
