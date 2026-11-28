"""Aligned synthetic expression, attendance and declared activity-context views.

Reuse the existing journal snapshot and affiliation engines. Never infer
attendance, social ties, causal effects or semantic facts from an expression.
"""
from collections import defaultdict
from .semantic_observations import SemanticObservationStore, project_reviewed_expressions, _dataset_binding
from .semantic_llm import _digest
from .events import parse_time
from .snapshots import materialize_snapshot
from .affiliations import affiliation_report

UTC = {"kind": "utc"}
LINK_SCHEMA = "sociolab.expression-activity-links.v1"
FRAME_SCHEMA = "sociolab.multilayer-expression-frame.v1"
CHANGE_SCHEMA = "sociolab.multilayer-expression-change.v1"


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError("unexpected multilayer fields")


def _text(value):
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("nonblank declared identifier or evidence reference required")
    value.encode("utf-8", errors="strict")


def _check_hash(value, field):
    if type(value) is not dict or value.get(field) != _digest({k: v for k, v in value.items() if k != field}):
        raise ValueError("multilayer digest mismatch: " + field)


def _check_availability(dataset, store, journal_cutoff, observation_cutoff, as_of):
    if not isinstance(store, SemanticObservationStore):
        raise ValueError("explicit expression store required")
    instant = parse_time(as_of, UTC)
    dataset.as_known(journal_cutoff)
    if type(observation_cutoff) is not int or not 0 <= observation_cutoff <= len(store.records):
        raise ValueError("invalid observation cutoff")
    if journal_cutoff and parse_time(dataset.records[journal_cutoff-1]["recorded_at"], UTC) > instant:
        raise ValueError("journal prefix is unavailable at as_of")
    if observation_cutoff and parse_time(store.records[observation_cutoff-1]["received_at"], UTC) > instant:
        raise ValueError("expression prefix is unavailable at as_of")


def _activity_records(dataset, cutoff):
    active = dataset.as_known(cutoff)
    entities = dataset.entities_at(cutoff)
    identities = dataset.identity_map_at(cutoff)
    descriptions = defaultdict(list)
    for record in active:
        if record["kind"] == "activity.observed":
            raw = record["payload"]["activity"]
            activity = identities.get(raw, raw)
            descriptions[activity].append(record)
    return entities, identities, descriptions


def _contains(record, when, clock):
    at = parse_time(when, clock)
    interval = record["valid_interval"]
    if interval is None:
        return at == parse_time(record["occurred_at"], clock)
    return parse_time(interval[0], clock) <= at and (
        interval[1] is None or at < parse_time(interval[1], clock))


def _activity_link(dataset, event, activity_record_id, state):
    entities, identities, descriptions = state
    matches = [(activity, record) for activity, records in descriptions.items()
        for record in records if record["record_id"] == activity_record_id]
    if len(matches) != 1:
        return None, "ACTIVITY_DESCRIPTION_NOT_CURRENT"
    activity, record = matches[0]
    if (entities.get(activity) != "activity" or record["payload"]["activity"] != activity or
            identities.get(activity, activity) != activity):
        return None, "ACTIVITY_IDENTITY_NOT_CANONICAL"
    if len(descriptions[activity]) != 1:
        return None, "AMBIGUOUS_ACTIVITY_DESCRIPTION"
    if record["payload"]["status"] != "held":
        return None, "ACTIVITY_NOT_HELD"
    if not _contains(record, event["occurred_at"], dataset.clock):
        return None, "ACTIVITY_OUTSIDE_EXPRESSION_TIME"
    return activity, None


def freeze_activity_links(dataset, store, *, journal_cutoff, observation_cutoff, as_of,
        start, end, authority, links):
    """Freeze an explicit full link set, not an inferred or authenticated association.

    Each expression can have one declared activity context in this profile.
    The linked activity must be a current held occurrence at the event time.
    as_of is the declared availability of the link set, not source time.
    """
    _dataset_binding(dataset)
    _check_availability(dataset, store, journal_cutoff, observation_cutoff, as_of)
    _fields(authority, "id source_ref")
    for value in authority.values():
        _text(value)
    projection = project_reviewed_expressions(dataset, store, journal_cutoff=journal_cutoff,
        observation_cutoff=observation_cutoff, start=start, end=end)
    events = {e["event_id"]: e for e in projection["events"]}
    state = _activity_records(dataset, journal_cutoff)
    if type(links) is not list:
        raise ValueError("explicit activity link list required")
    seen, normalized = set(), []
    for link in links:
        _fields(link, "event_id activity_record_id evidence_ref")
        for value in link.values():
            _text(value)
        if link["event_id"] in seen:
            raise ValueError("one explicit activity link per expression event")
        seen.add(link["event_id"])
        if link["event_id"] not in events:
            raise ValueError("link requires a selected expression at its original prefix")
        event = events[link["event_id"]]
        activity, reason = _activity_link(dataset, event, link["activity_record_id"], state)
        if reason:
            raise ValueError(reason)
        normalized.append({**link, "activity_id": activity,
            "expression_occurred_at": event["occurred_at"], "topic_id": event["topic_id"]})
    result = {"schema": LINK_SCHEMA, "dataset": _dataset_binding(dataset),
        "journal_cutoff": journal_cutoff, "observation_cutoff": observation_cutoff, "as_of": as_of,
        "window": {"start": start, "end": end},
        "expression_projection_hash": projection["result_hash"],
        "authority": authority, "links": sorted(normalized, key=lambda r: r["event_id"]),
        "link_status": "CALLER_DECLARED_NOT_AUTHENTICATED"}
    result["link_hash"] = _digest(result)
    return result


def _replay_links(dataset, store, plan, journal_cutoff, observation_cutoff, as_of):
    _check_hash(plan, "link_hash")
    if plan.get("schema") != LINK_SCHEMA:
        raise ValueError("unsupported activity link plan")
    if (plan["journal_cutoff"] > journal_cutoff or plan["observation_cutoff"] > observation_cutoff or
            parse_time(plan["as_of"], UTC) > parse_time(as_of, UTC)):
        raise ValueError("activity link plan is unavailable at requested prefix/as_of")
    rebuilt = freeze_activity_links(dataset, store, journal_cutoff=plan["journal_cutoff"],
        observation_cutoff=plan["observation_cutoff"], as_of=plan["as_of"],
        start=plan["window"]["start"], end=plan["window"]["end"], authority=plan["authority"],
        links=[{k: row[k] for k in ("event_id", "activity_record_id", "evidence_ref")} for row in plan["links"]])
    if rebuilt != plan:
        raise ValueError("activity links do not replay at their declared prefix")
    return rebuilt


def _context_edges(links):
    grouped = defaultdict(list)
    for row in links:
        grouped[("PERSON_ACTIVITY_EXPRESSION_CONTEXT", row["actor_id"],
            row["activity_id"], row["action"])].append((row["event_id"], row["binding_hash"]))
        if row["topic_id"] is not None:
            grouped[("TOPIC_ACTIVITY_EXPRESSION_CONTEXT", row["topic_id"],
                row["activity_id"], row["action"])].append((row["event_id"], row["binding_hash"]))
    return [{"layer": layer, "source": {"kind": "person" if layer.startswith("PERSON") else "topic", "id": source},
        "target": {"kind": "activity", "id": target}, "action": action,
        "event_count": len(ids), "event_ids": sorted(e for e, _ in ids),
        "binding_hashes": sorted(h for _, h in ids)}
        for (layer, source, target, action), ids in sorted(grouped.items())]


def build_multilayer_frame(dataset, store, *, journal_cutoff, observation_cutoff, as_of,
        start, end, population, roles, activity_links, affiliation_projection, max_pairs):
    """Align separate measurements at explicit knowledge prefixes and source window."""
    _dataset_binding(dataset)
    _check_availability(dataset, store, journal_cutoff, observation_cutoff, as_of)
    if affiliation_projection not in ("none", "count", "newman"):
        raise ValueError("unsupported affiliation projection")
    if type(max_pairs) is not int or max_pairs < 0:
        raise ValueError("explicit nonnegative affiliation pair budget required")
    expression = project_reviewed_expressions(dataset, store, journal_cutoff=journal_cutoff,
        observation_cutoff=observation_cutoff, start=start, end=end)
    view = {"schema": "sociolab.view.v1", "population": population, "mode": "participation",
        "layer": "participation", "directed": False, "start": start, "end": end, "roles": roles}
    participation = materialize_snapshot(dataset, view, journal_cutoff)
    incidence = participation.to_dict()
    if incidence["dataset"]["content_hash"] != expression["journal_prefix_hash"]:
        raise ValueError("expression and participation source prefixes differ")
    affiliation = None
    if participation.coverage_complete:
        affiliation = affiliation_report(participation.to_graph(), participation.persons,
            projection=affiliation_projection, max_pairs=max_pairs)
        affiliation_status = "COMPLETE_DECLARED_COVERAGE"
    else:
        affiliation_status = "NOT_RUN_INCOMPLETE_PARTICIPATION_COVERAGE"
    events = {e["event_id"]: e for e in expression["events"]}
    active_links, withheld_links = [], []
    attendance = {(e["source"], e["target"]): e["evidence"] for e in incidence["edges"]}
    state = _activity_records(dataset, journal_cutoff)
    first, last = parse_time(start, dataset.clock), parse_time(end, dataset.clock)
    if activity_links is not None:
        plan = _replay_links(dataset, store, activity_links, journal_cutoff, observation_cutoff, as_of)
        for link in plan["links"]:
            eid = link["event_id"]
            if not first <= parse_time(link["expression_occurred_at"], dataset.clock) < last:
                continue
            if eid not in events:
                withheld_links.append({"event_id": eid, "reason": "EXPRESSION_NOT_CURRENT"})
                continue
            event = events[eid]
            activity, reason = _activity_link(dataset, event, link["activity_record_id"], state)
            if reason or activity != link["activity_id"]:
                withheld_links.append({"event_id": eid, "reason": reason or "ACTIVITY_IDENTITY_CHANGED"})
                continue
            evidence = attendance.get((event["actor_id"], activity))
            binding = {"link": link, "authority": plan["authority"], "available_at": plan["as_of"],
                "journal_cutoff": plan["journal_cutoff"], "observation_cutoff": plan["observation_cutoff"]}
            active_links.append({**link, "actor_id": event["actor_id"], "action": event["action"],
                "binding_hash": _digest(binding), "association_available_at": plan["as_of"],
                "attendance_in_window": "SELECTED_INCIDENCE" if evidence is not None else
                    "NO_SELECTED_INCIDENCE" if event["actor_id"] in participation.persons and participation.coverage_complete
                    else "UNKNOWN_OR_OUTSIDE_PARTICIPATION_SCOPE",
                "attendance_evidence": [] if evidence is None else evidence})
    result = {"schema": FRAME_SCHEMA, "profile": "SYNTHETIC_RESEARCH_ONLY",
        "dataset": _dataset_binding(dataset), "as_of": as_of, "journal_cutoff": journal_cutoff,
        "observation_cutoff": observation_cutoff, "window": {"start": start, "end": end},
        "settings": {"population": population, "roles": participation.view["roles"],
            "affiliation_projection": affiliation_projection, "max_pairs": max_pairs},
        "expression": expression, "participation": incidence, "affiliation_status": affiliation_status,
        "affiliation": affiliation, "activity_link_plan_hash": None if activity_links is None else activity_links["link_hash"],
        "activity_context_links": active_links, "withheld_activity_links": withheld_links,
        "activity_context_edges": _context_edges(active_links),
        "expression_scope": "EXPLICIT_SELECTED_CANDIDATES_NOT_POPULATION_COMPLETE",
        "activity_context_scope": "DECLARED_ASSOCIATION_NOT_ATTENDANCE",
        "qualification_status": "NOT_ESTABLISHED", "causal_effect_identified": False}
    result["frame_hash"] = _digest(result)
    return result


def _measurements(frame):
    values = {}
    for edge in frame["expression"]["edges"]:
        key = (edge["layer"], edge["source"]["kind"], edge["source"]["id"],
            edge["target"]["kind"], edge["target"]["id"], edge["action"])
        values[key] = (edge["event_count"], tuple(edge["event_ids"]))
    for edge in frame["activity_context_edges"]:
        key = (edge["layer"], edge["source"]["kind"], edge["source"]["id"],
            edge["target"]["kind"], edge["target"]["id"], edge["action"])
        values[key] = (edge["event_count"], tuple(sorted(edge["event_ids"] + edge["binding_hashes"])))
    for edge in frame["participation"]["edges"]:
        key = ("PERSON_ACTIVITY_ATTENDANCE", "person", edge["source"], "activity", edge["target"], "attended")
        values[key] = (edge["strength"], tuple(sorted(edge["evidence"])))
    return values


def compare_multilayer_frames(dataset, store, *, before, after):
    """Recompute both frames on one journal/store lineage, then compare like units."""
    left, right = (build_multilayer_frame(dataset, store, **spec) for spec in (before, after))
    if left["settings"] != right["settings"]:
        raise ValueError("multilayer comparison requires identical participation settings")
    if (left["journal_cutoff"] > right["journal_cutoff"] or left["observation_cutoff"] > right["observation_cutoff"] or
            parse_time(left["as_of"], UTC) > parse_time(right["as_of"], UTC)):
        raise ValueError("comparison knowledge prefixes must be nondecreasing")
    equal_window = left["window"] == right["window"]
    if not equal_window and parse_time(left["window"]["end"], dataset.clock) > parse_time(right["window"]["start"], dataset.clock):
        raise ValueError("use an identical window or ordered nonoverlapping source windows")
    a, b = _measurements(left), _measurements(right)
    changes = []
    for key in sorted(set(a) | set(b)):
        old, new = a.get(key, (0, ())), b.get(key, (0, ()))
        if old == new:
            continue
        layer, sk, source, tk, target, action = key
        changes.append({"layer": layer, "source": {"kind": sk, "id": source},
            "target": {"kind": tk, "id": target}, "action": action,
            "before_count": old[0], "after_count": new[0], "count_delta": new[0]-old[0],
            "before_evidence_ids": list(old[1]), "after_evidence_ids": list(new[1]),
            "change": "ADDED_TO_VIEW" if key not in a else "REMOVED_FROM_VIEW" if key not in b else
                "COUNT_CHANGED" if old[0] != new[0] else "EVIDENCE_CHANGED"})
    result = {"schema": CHANGE_SCHEMA, "profile": "SYNTHETIC_RESEARCH_ONLY",
        "comparison": "FIXED_WINDOW_RECEIPT_OR_SELECTION_CHANGE" if equal_window else "ORDERED_WINDOW_DESCRIPTIVE_CHANGE",
        "before_frame_hash": left["frame_hash"], "after_frame_hash": right["frame_hash"],
        "before_window": left["window"], "after_window": right["window"],
        "changes": changes,
        "participation_coverage_complete": {"before": left["participation"]["coverage"]["complete"],
            "after": right["participation"]["coverage"]["complete"]},
        "affiliation": {"before": left["affiliation"], "after": right["affiliation"]},
        "interpretation": "COUNTS_IN_SELECTED_VIEWS_NOT_RELATIONSHIP_FORMATION_OR_DISSOLUTION",
        "qualification_status": "NOT_ESTABLISHED", "causal_effect_identified": False}
    result["result_hash"] = _digest(result)
    return result
