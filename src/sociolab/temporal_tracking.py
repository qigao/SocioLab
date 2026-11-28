"""Immutable tracking with an explicitly advanced source-time cursor.

Receipt batches and source-time advances are separate operations. Every view
uses the original materializer and analysis engine; this module only resolves
fixed templates at the cursor and records which operation caused a version.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from .events import EventDataset, ingest_records, parse_time
from .network_tracking import (
    _SCOPE as _FIXED_SCOPE,
    _analysis, _fields, _fingerprints, _hash_field, _integer, _text,
    _transition as _fixed_transition,
    _views as _fixed_views,
)
from .snapshots import NetworkSnapshot, content_hash, materialize_snapshot, validate_view_spec

_PROFILE = "receipt-source-time-tracking-v1"
_STATE_FIELDS = {
    "schema", "kind", "profile", "sequence", "previous_state_hash", "registration", "registration_hash",
    "dataset", "knowledge_cutoff", "cursor", "cursor_value", "views", "scope", "content_hash",
}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SCOPE = {
    **_FIXED_SCOPE,
    "registered_view_times_fixed": False,
    "registered_view_templates_fixed": True,
    "explicit_source_time_advance": True,
    "receipt_batches_advance_source_time": False,
    "source_time_advances_append_receipts": False,
    "source_time_cursor_is_receipt_time": False,
    "source_time_advance_proves_new_source_fact": False,
    "all_registered_views_rematerialized_after_time_advance": True,
    "window_boundaries": "start_inclusive_end_exclusive",
    "window_expiry_proves_real_relation_ended": False,
}
_TRANSITION_SCOPE = {
    **_SCOPE,
    "change_meaning": "descriptive_change_under_fixed_view_templates_and_explicit_source_time_cursor",
}


def _format_time(value: int, clock: dict) -> int | str:
    if clock["kind"] == "ticks":
        if value < 0:
            raise ValueError("trailing window starts before source tick zero")
        return value
    try:
        instant = _EPOCH + timedelta(microseconds=value)
    except OverflowError as error:
        raise ValueError("source-time window exceeds the supported UTC calendar") from error
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _cursor(value: object, clock: dict) -> tuple[int | str, int]:
    parsed = parse_time(value, clock)
    return _format_time(parsed, clock), parsed


def _resolve_view(template: object, width: object, cursor: int | str, clock: dict) -> dict:
    if type(template) is not dict or {"at", "start", "end"} & set(template):
        raise ValueError("view template must be an object without at/start/end")
    view = deepcopy(template)
    if view.get("mode") == "state":
        if width is not None:
            raise ValueError("state templates require a null window_width")
        view["at"] = cursor
    else:
        _integer(width, "window_width", 1)
        view["start"] = _format_time(parse_time(cursor, clock) - width, clock)
        view["end"] = cursor
    return validate_view_spec(view, clock)


def _registration(registration: object, clock: dict) -> dict:
    _fields(registration, {"schema", "initial_cursor", "source_time_unit", "views"}, "temporal tracking registration")
    if registration["schema"] != "sociolab.temporal-tracking-spec.v1":
        raise ValueError("unsupported temporal tracking registration schema")
    unit = "tick" if clock["kind"] == "ticks" else "microsecond"
    if registration["source_time_unit"] != unit:
        raise ValueError("source_time_unit must match the declared source clock")
    cursor, _ = _cursor(registration["initial_cursor"], clock)
    if type(registration["views"]) is not list or not 1 <= len(registration["views"]) <= 16:
        raise ValueError("tracking requires between 1 and 16 registered views")
    views, seen = [], set()
    for item in registration["views"]:
        _fields(item, {"view_id", "view", "window_width", "analysis"}, "registered temporal view")
        view_id = _text(item["view_id"], "view_id")
        if view_id in seen:
            raise ValueError("registered view IDs must be unique")
        seen.add(view_id)
        view = _resolve_view(item["view"], item["window_width"], cursor, clock)
        analysis = _analysis(item["analysis"], view)
        template = {key: value for key, value in view.items() if key not in {"at", "start", "end"}}
        views.append({"view_id": view_id, "view": template, "window_width": item["window_width"], "analysis": analysis})
    normalized = {"schema": registration["schema"], "initial_cursor": cursor, "source_time_unit": unit, "views": views}
    content_hash(normalized)
    return normalized


def _resolved_registration(registration: dict, cursor: int | str, clock: dict) -> dict:
    return {"views": [
        {"view_id": item["view_id"], "view": _resolve_view(item["view"], item["window_width"], cursor, clock),
         "analysis": item["analysis"]}
        for item in registration["views"]
    ]}


def _state(dataset: EventDataset, registration: dict, cursor: int | str,
           sequence: int, previous: str | None) -> dict:
    normalized_cursor, value = _cursor(cursor, dataset.clock)
    resolved = _resolved_registration(registration, normalized_cursor, dataset.clock)
    state = {
        "schema": "sociolab.temporal-tracking-state.v1", "kind": "TEMPORAL_TRACKING_STATE", "profile": _PROFILE,
        "sequence": sequence, "previous_state_hash": previous,
        "registration": registration, "registration_hash": content_hash(registration),
        "dataset": dataset.to_dict(), "knowledge_cutoff": len(dataset.records),
        "cursor": normalized_cursor, "cursor_value": value,
        "views": _fixed_views(dataset, resolved), "scope": deepcopy(_SCOPE),
    }
    state["content_hash"] = content_hash(state)
    return state


def initialize_temporal_tracking(dataset: EventDataset, registration: dict) -> dict:
    """Resolve the fixed templates at their initial source-time cursor."""
    if not isinstance(dataset, EventDataset):
        raise TypeError("temporal tracking requires an EventDataset")
    registered = _registration(registration, dataset.clock)
    return _state(dataset, registered, registered["initial_cursor"], 0, None)


def validate_temporal_tracking_state(state: dict) -> dict:
    """Validate exact state fields and replay all snapshots at the saved cursor.

    This checks the current retained journal and views. The persistence layer
    separately replays receipt and time operations to verify chain ancestry.
    """
    _fields(state, _STATE_FIELDS, "temporal tracking state")
    if (state["schema"] != "sociolab.temporal-tracking-state.v1" or
            state["kind"] != "TEMPORAL_TRACKING_STATE" or state["profile"] != _PROFILE):
        raise ValueError("unsupported temporal tracking state schema, kind or profile")
    _hash_field(state["content_hash"], "state content_hash")
    if state["content_hash"] != content_hash({key: value for key, value in state.items() if key != "content_hash"}):
        raise ValueError("tracking state content hash does not match its contents")
    sequence = _integer(state["sequence"], "sequence")
    if sequence == 0:
        if state["previous_state_hash"] is not None:
            raise ValueError("initial tracking state must not have a predecessor")
    else:
        _hash_field(state["previous_state_hash"], "previous_state_hash")
    dataset = EventDataset.from_mapping(state["dataset"])
    if _integer(state["knowledge_cutoff"], "knowledge_cutoff") != len(dataset.records):
        raise ValueError("tracking cutoff must equal the complete retained journal head")
    registered = _registration(state["registration"], dataset.clock)
    if content_hash(registered) != content_hash(state["registration"]):
        raise ValueError("stored temporal registration must be normalized")
    if state["registration_hash"] != content_hash(registered):
        raise ValueError("registration hash does not match the fixed view templates")
    cursor, value = _cursor(state["cursor"], dataset.clock)
    if cursor != state["cursor"] or type(state["cursor_value"]) is not int or state["cursor_value"] != value:
        raise ValueError("saved cursor and cursor_value must match the normalized source time")
    initial_value = parse_time(registered["initial_cursor"], dataset.clock)
    if value < initial_value or (sequence == 0 and value != initial_value):
        raise ValueError("saved cursor is inconsistent with the initial registration and sequence")
    if state["scope"] != _SCOPE or content_hash(state["scope"]) != content_hash(_SCOPE):
        raise ValueError("tracking scope does not match the fixed temporal profile")
    resolved = _resolved_registration(registered, cursor, dataset.clock)
    views = state["views"]
    if type(views) is not list or len(views) != len(resolved["views"]):
        raise ValueError("tracking state must contain every registered view in order")
    for item, declared in zip(views, resolved["views"]):
        _fields(item, {"view_id", "snapshot", "fingerprints"}, "retained temporal view")
        if item["view_id"] != declared["view_id"]:
            raise ValueError("retained view IDs must match registration order")
        snapshot = NetworkSnapshot.from_mapping(item["snapshot"])
        expected = materialize_snapshot(dataset, declared["view"], knowledge_cutoff=state["knowledge_cutoff"])
        if snapshot.content_hash != expected.content_hash:
            raise ValueError("retained snapshot does not match replay of its template, cursor and journal")
        _fields(item["fingerprints"], {"graph", "population", "coverage", "evidence"}, "semantic fingerprints")
        if item["fingerprints"] != _fingerprints(expected):
            raise ValueError("snapshot semantic fingerprints do not match source replay")
    return deepcopy(state)


def _transition(before: dict, after: dict, cause: str) -> dict:
    # The fixed tracker owns source-tail accounting, semantic fingerprints,
    # completeness guards, projection budgets and the upstream comparison.
    transition = _fixed_transition(before, after)
    transition.pop("content_hash")
    transition.update({
        "schema": "sociolab.temporal-tracking-transition.v1", "kind": "TEMPORAL_TRACKING_TRANSITION",
        "profile": _PROFILE, "cause": cause,
        "before_cursor": before["cursor"], "after_cursor": after["cursor"],
        "before_cursor_value": before["cursor_value"], "after_cursor_value": after["cursor_value"],
        "scope": deepcopy(_TRANSITION_SCOPE),
    })
    if cause == "source_time_advance":
        transition["status"] = "APPLIED" if before["cursor_value"] != after["cursor_value"] else "NO_TIME_ADVANCE"
    transition["content_hash"] = content_hash(transition)
    return transition


def apply_temporal_tracking_batch(state: dict, batch: list[dict], received_at: str | None = None) -> dict:
    """Accept a receipt batch while preserving the explicit source-time cursor.

    Empty and duplicate-only batches preserve the state exactly. A late source
    correction reconstructs the current views without rewriting old versions.
    """
    before = validate_temporal_tracking_state(state)
    dataset = EventDataset.from_mapping(before["dataset"])
    updated = ingest_records(dataset, batch, received_at=received_at)
    if updated.content_hash == dataset.content_hash:
        return {"state": before, "transition": _transition(before, before, "receipt_batch")}
    after = _state(updated, deepcopy(before["registration"]), before["cursor"],
                   before["sequence"] + 1, before["content_hash"])
    return {"state": after, "transition": _transition(before, after, "receipt_batch")}


def advance_temporal_tracking(state: dict, cursor: int | str) -> dict:
    """Advance source time explicitly without accepting any source receipts.

    Equal instants are idempotent, including equivalent UTC spellings. A later
    cursor creates a version even when no observable view component changes.
    Time reversal is rejected rather than replacing any saved reconstruction.
    """
    before = validate_temporal_tracking_state(state)
    dataset = EventDataset.from_mapping(before["dataset"])
    normalized_cursor, value = _cursor(cursor, dataset.clock)
    if value < before["cursor_value"]:
        raise ValueError("source-time cursor cannot move backwards")
    if value == before["cursor_value"]:
        return {"state": before, "transition": _transition(before, before, "source_time_advance")}
    after = _state(dataset, deepcopy(before["registration"]), normalized_cursor,
                   before["sequence"] + 1, before["content_hash"])
    return {"state": after, "transition": _transition(before, after, "source_time_advance")}
