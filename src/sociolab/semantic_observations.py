"""Synthetic-only versioned reviewed-expression sidecar and temporal projection.

Not an observation admission authority. Never mutate the source EventDataset.
"""
from dataclasses import dataclass
from pathlib import Path
import json
from collections import defaultdict

from ._json import unique_object
from .events import EventDataset, parse_time
from .annotations import annotation_report
from .semantic_llm import _digest, _json
from .semantic_admission import assess_semantic_admission

SCHEMA = "sociolab.reviewed-expression-store.v1"
PROFILE = "SYNTHETIC_RESEARCH_ONLY"
UTC = {"kind": "utc"}
LAYERS = ("PERSON_PERSON", "PERSON_TOPIC")


def _fields(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError("unexpected expression store fields")


def _text(value):
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("nonblank trimmed expression identifier required")
    value.encode("utf-8", errors="strict")


def _check_hash(value, key):
    if value.get(key) != _digest({k: v for k, v in value.items() if k != key}):
        raise ValueError("expression digest mismatch: " + key)


def _authority(value):
    _fields(value, "id source_ref")
    _text(value["id"])
    _text(value["source_ref"])


def _key(value):
    _fields(value, "source_system interaction_fact_id")
    for v in value.values():
        _text(v)
    return value["source_system"], value["interaction_fact_id"]


def _prefix(dataset, cutoff):
    dataset.as_known(cutoff)  # enforce exact existing prefix
    data = dataset.to_dict()
    data["records"] = data["records"][:cutoff]
    return _digest(data)


def _dataset_binding(dataset):
    if not isinstance(dataset, EventDataset) or dataset.origin != "synthetic":
        raise ValueError("reviewed-expression research store requires a synthetic EventDataset")
    return {"dataset_id": dataset.dataset_id, "source_revision": dataset.source_revision,
        "origin": dataset.origin, "clock": dataset.clock}


def _payload_actions(payload):
    _fields(payload, "context audit selected_action_hashes people_ids")
    context, audit = payload["context"], payload["audit"]
    _check_hash(context, "context_hash")
    _check_hash(audit, "result_hash")
    if (context["schema"] != "sociolab.language-context.v1" or
            audit["schema"] != "sociolab.semantic-action-admission-audit.v1" or
            audit["context_hash"] != context["context_hash"] or
            audit["reference_status"] != "EXACT_DECLARED_REFERENCE_AGREEMENT" or
            audit["observation_status"] != "NOT_ADMITTED" or audit["network_mutated"] is not False):
        raise ValueError("reviewed-expression snapshot requires exact reference audit")
    target = context["entries"][-1]
    if (audit["target_content_record_id"] != target["content_record_id"] or
            audit["interaction_record_id"] != target["interaction_record_id"] or
            audit["source_speaker_id"] != target["actor"] or audit["occurred_at"] != target["occurred_at"]):
        raise ValueError("audit target binding mismatch")
    selected = payload["selected_action_hashes"]
    people = payload["people_ids"]
    if (type(selected) is not list or not selected or
            any(type(h) is not str for h in selected) or selected != sorted(set(selected)) or
            type(people) is not list or any(type(p) is not str for p in people) or people != sorted(set(people))):
        raise ValueError("explicit unique selected hashes and canonical person IDs required")
    eligible = audit["reviewed_direct_expression_candidate_hashes"]
    rows = {r["action_hash"]: r for r in audit["rows"]}
    actions = []
    for h in selected:
        if h not in eligible or h not in rows:
            raise ValueError("selection is not a reviewed direct expression candidate")
        row = rows[h]
        action = row["action"]
        if (h != _digest(action) or row["disposition"] != "REVIEWED_DIRECT_EXPRESSION_CANDIDATE"
                or action["actor_id"] != target["actor"] or action["actor_id"] not in people
                or action["attribution"] != "DIRECT" or action["polarity"] != "AFFIRMED"
                or action["modality"] != "ASSERTED" or action["assertion_status"] != "NOT_ESTABLISHED"
                or action["subject"]["kind"] not in ("person", "topic") or action["topic_status"] == "unresolved"
                or (action["subject"]["kind"] == "person" and
                    (action["subject"]["id"] not in people or action["subject"]["id"] == action["actor_id"]))):
            raise ValueError("inconsistent selected expression")
        actions.append((h, action))
    return actions


def _validate(value):
    _fields(value, "schema profile dataset records store_hash")
    if value["schema"] != SCHEMA or value["profile"] != PROFILE:
        raise ValueError("unsupported expression store")
    _fields(value["dataset"], "dataset_id source_revision origin clock")
    if value["dataset"]["origin"] != "synthetic":
        raise ValueError("only synthetic research stores are supported")
    _check_hash(value, "store_hash")
    if type(value["records"]) is not list:
        raise ValueError("expression records must be an array")
    heads, seen = {}, set()
    last_hash, last_cutoff, last_time = None, 0, None
    for i, record in enumerate(value["records"], 1):
        _fields(record, "seq revision_id key supersedes operation received_at journal_cutoff journal_prefix_hash authority payload previous_hash record_hash")
        _check_hash(record, "record_hash")
        _text(record["revision_id"])
        _text(record["journal_prefix_hash"])
        _authority(record["authority"])
        key = _key(record["key"])
        cutoff = record["journal_cutoff"]
        instant = parse_time(record["received_at"], UTC)
        if (type(record["seq"]) is not int or record["seq"] != i or
                record["revision_id"] in seen or record["previous_hash"] != last_hash or
                type(cutoff) is not int or cutoff < last_cutoff or
                (last_time is not None and instant < last_time)):
            raise ValueError("expression receipt order or chain mismatch")
        if record["supersedes"] != heads.get(key):
            raise ValueError("expression revision must supersede current head")
        if record["operation"] == "snapshot":
            _payload_actions(record["payload"])
            if record["payload"]["audit"]["admission_cutoff"] != cutoff:
                raise ValueError("snapshot audit cutoff mismatch")
        elif record["operation"] == "withdraw":
            if record["payload"] is not None or key not in heads:
                raise ValueError("withdrawal requires predecessor and null payload")
        else:
            raise ValueError("unknown expression operation")
        heads[key] = record["revision_id"]
        seen.add(record["revision_id"])
        last_hash, last_cutoff, last_time = record["record_hash"], cutoff, instant


@dataclass(frozen=True, init=False)
class SemanticObservationStore:
    """Immutable JSON sidecar. Hashes are consistency checks, not signatures."""
    _canonical: str

    def __init__(self, value):
        _validate(value)
        object.__setattr__(self, "_canonical", _json(value))

    @classmethod
    def empty(cls, dataset):
        value = {"schema": SCHEMA, "profile": PROFILE,
            "dataset": _dataset_binding(dataset), "records": []}
        value["store_hash"] = _digest(value)
        return cls(value)

    @classmethod
    def from_mapping(cls, value):
        return cls(value)

    def to_dict(self):
        return json.loads(self._canonical)

    @property
    def records(self):
        return tuple(self.to_dict()["records"])

    @property
    def content_hash(self):
        return self.to_dict()["store_hash"]


def load_semantic_observations(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return SemanticObservationStore.from_mapping(json.load(handle, object_pairs_hook=unique_object))


def _check_prefixes(dataset, store, journal_cutoff, observation_cutoff):
    if not isinstance(store, SemanticObservationStore):
        raise ValueError("explicit expression store required")
    if store.to_dict()["dataset"] != _dataset_binding(dataset):
        raise ValueError("expression store dataset mismatch")
    prefix_hash = _prefix(dataset, journal_cutoff)
    records = store.records
    if type(observation_cutoff) is not int or not 0 <= observation_cutoff <= len(records):
        raise ValueError("observation cutoff must identify an existing receipt prefix")
    for record in records[:observation_cutoff]:
        cutoff = record["journal_cutoff"]
        if cutoff > journal_cutoff or _prefix(dataset, cutoff) != record["journal_prefix_hash"]:
            raise ValueError("expression receipt is unavailable at journal cutoff or belongs to another journal")
        if cutoff and parse_time(record["received_at"], UTC) < parse_time(dataset.records[cutoff-1]["recorded_at"], UTC):
            raise ValueError("expression receipt predates its required journal prefix")
        if record["operation"] == "snapshot":
            target_id = record["payload"]["context"]["entries"][-1]["interaction_record_id"]
            interaction = next((r for r in dataset.records[:cutoff] if r["record_id"] == target_id), None)
            if interaction is None or interaction["kind"] != "interaction.observed" or record["key"] != _interaction_key(interaction):
                raise ValueError("expression fact key does not bind its source interaction")
    return records[:observation_cutoff], prefix_hash


def _interaction_key(record):
    return {"source_system": record["source"]["system"], "interaction_fact_id": record["fact_id"]}


def _append(store, dataset, *, revision_id, supersedes, key, operation, cutoff, received_at, authority, payload):
    previous, prefix_hash = _check_prefixes(dataset, store, cutoff, len(store.records))
    instant = parse_time(received_at, UTC)
    if cutoff and instant < parse_time(dataset.records[cutoff-1]["recorded_at"], UTC):
        raise ValueError("expression receipt predates its required journal prefix")
    record = {"seq": len(previous)+1, "revision_id": revision_id, "key": key,
        "supersedes": supersedes, "operation": operation, "received_at": received_at,
        "journal_cutoff": cutoff, "journal_prefix_hash": prefix_hash,
        "authority": authority, "payload": payload,
        "previous_hash": previous[-1]["record_hash"] if previous else None}
    record["record_hash"] = _digest(record)
    value = store.to_dict()
    value["records"].append(record)
    value["store_hash"] = _digest({k: v for k, v in value.items() if k != "store_hash"})
    return SemanticObservationStore(value)


def append_reviewed_snapshot(store, dataset, context, frozen, model_report, *, original_bytes,
        people, topics, model_key, reasoning_mode, admission_cutoff, reviews,
        selected_action_hashes, revision_id, supersedes, received_at, authority):
    """Recompute review audit and explicitly select a nonempty research snapshot."""
    _dataset_binding(dataset)
    audit = assess_semantic_admission(dataset, context, frozen, model_report, original_bytes=original_bytes,
        people=people, topics=topics, model_key=model_key, reasoning_mode=reasoning_mode,
        admission_cutoff=admission_cutoff, reviews=reviews)
    if type(selected_action_hashes) is not list or any(type(h) is not str for h in selected_action_hashes):
        raise ValueError("explicit action hash selection required")
    if len(selected_action_hashes) != len(set(selected_action_hashes)):
        raise ValueError("duplicate selected action hash")
    payload = {"context": context, "audit": audit, "selected_action_hashes": sorted(selected_action_hashes),
        "people_ids": sorted(people)}
    _payload_actions(payload)
    interaction = next(r for r in dataset.records[:admission_cutoff]
        if r["record_id"] == audit["interaction_record_id"])
    return _append(store, dataset, revision_id=revision_id, supersedes=supersedes,
        key=_interaction_key(interaction), operation="snapshot", cutoff=admission_cutoff,
        received_at=received_at, authority=authority, payload=payload)


def withdraw_reviewed_snapshot(store, dataset, *, key, revision_id, supersedes,
        journal_cutoff, received_at, authority):
    """Explicit retraction of the current sidecar revision; no claim of no behavior."""
    return _append(store, dataset, revision_id=revision_id, supersedes=supersedes,
        key=key, operation="withdraw", cutoff=journal_cutoff, received_at=received_at,
        authority=authority, payload=None)


def _context_current(context, current):
    for entry in context["entries"]:
        row = current.get(entry["content_record_id"])
        if row is None or any(entry[field] != row[field] for field in (
                "interaction_record_id", "content_revision", "content_hash", "language", "length",
                "occurred_at", "actor", "addressee", "interaction_topic", "interaction_action")):
            return False
    return True


def project_reviewed_expressions(dataset, store, *, journal_cutoff, observation_cutoff, start, end):
    """Separate source-time half-open window and two explicit knowledge prefixes."""
    records, prefix_hash = _check_prefixes(dataset, store, journal_cutoff, observation_cutoff)
    first, last = parse_time(start, dataset.clock), parse_time(end, dataset.clock)
    if first >= last:
        raise ValueError("source-time window must be increasing")
    heads = {}
    for record in records:
        heads[_key(record["key"])] = record
    current = {r["record_id"]: r for r in annotation_report(dataset, knowledge_cutoff=journal_cutoff)["current_contents"]}
    entities, identities = dataset.entities_at(journal_cutoff), dataset.identity_map_at(journal_cutoff)
    events, withheld, withdrawn, grouped = [], [], [], defaultdict(list)
    for key in sorted(heads):
        record = heads[key]
        if record["operation"] == "withdraw":
            withdrawn.append(record["revision_id"])
            continue
        payload = record["payload"]
        context = payload["context"]
        target = context["entries"][-1]
        if not _context_current(context, current) or any(
                entities.get(p) != "person" or identities.get(p, p) != p for p in payload["people_ids"]):
            withheld.append({"revision_id": record["revision_id"], "reason": "STALE_OR_AMBIGUOUS_CONTEXT_OR_IDENTITY"})
            continue
        if not first <= parse_time(target["occurred_at"], dataset.clock) < last:
            continue
        for action_hash, action in _payload_actions(payload):
            subject = action["subject"]
            layer = "PERSON_PERSON" if subject["kind"] == "person" else "PERSON_TOPIC"
            event_id = _digest([record["record_hash"], action_hash])
            event = {"event_id": event_id, "revision_id": record["revision_id"], "action_hash": action_hash,
                "source_speaker_id": target["actor"], "occurred_at": target["occurred_at"],
                "available_at": record["received_at"], "target_content_record_id": target["content_record_id"],
                "interaction_record_id": target["interaction_record_id"], "audit_hash": payload["audit"]["result_hash"],
                "layer": layer, "actor_id": action["actor_id"], "action": action["action"],
                "subject": subject, "topic_id": action["topic_id"], "evidence": action["evidence"]}
            events.append(event)
            grouped[(layer, event["actor_id"], subject["id"], event["action"])].append(event_id)
    edges = [{"layer": layer, "source": {"kind": "person", "id": actor},
        "target": {"kind": "person" if layer == "PERSON_PERSON" else "topic", "id": target},
        "action": action, "event_count": len(ids), "event_ids": sorted(ids)}
        for (layer, actor, target, action), ids in sorted(grouped.items())]
    prefix = store.to_dict()
    prefix["records"] = list(records)
    prefix.pop("store_hash")
    result = {"schema": "sociolab.reviewed-expression-projection.v1", "profile": PROFILE,
        "journal_cutoff": journal_cutoff, "journal_prefix_hash": prefix_hash,
        "observation_cutoff": observation_cutoff, "observation_prefix_hash": _digest(prefix),
        "window": {"start": start, "end": end}, "events": events, "edges": edges,
        "withheld_revisions": withheld, "withdrawn_revisions": withdrawn,
        "counting_unit": "selected reviewed expression candidates, not relationships or realized behavior",
        "qualification_status": "NOT_ESTABLISHED", "network_mutated": False}
    result["result_hash"] = _digest(result)
    return result


def expression_graph(projection, *, layer, action):
    """A separate directed NetworkX expression-frequency graph for one action."""
    from .semantic_actions import ACTIONS
    import networkx as nx
    _check_hash(projection, "result_hash")
    if (projection.get("schema") != "sociolab.reviewed-expression-projection.v1" or
            projection.get("profile") != PROFILE or layer not in LAYERS or action not in ACTIONS):
        raise ValueError("unsupported reviewed-expression graph selection")
    graph = nx.DiGraph(profile=PROFILE, layer=layer, action=action,
        projection_hash=projection["result_hash"], counting_unit=projection["counting_unit"])
    for edge in projection["edges"]:
        if edge["layer"] == layer and edge["action"] == action:
            source, target = edge["source"], edge["target"]
            graph.add_edge((source["kind"], source["id"]), (target["kind"], target["id"]),
                weight=edge["event_count"], event_ids=tuple(edge["event_ids"]))
    return graph
