"""Historical archive covariates using the existing NetworkX graph provider.

These are features of released records, not measured membership, relationship
states, or complete communication. No target labels or fitted parameters enter
this module. Replay reconstructs source-time history; it is not a live receipt
stream and does not invent an ordering among equal-time events.
"""

from __future__ import annotations

from math import log1p

import networkx as nx

from .archive_recurrence import _MAX_NODES, _MAX_PAIRS, _MAX_ROWS, _archive_prediction
from .snapshots import content_hash


DYADIC_FEATURE_NAMES = (
    "log1p_history_expected_count",
    "log1p_recent_expected_count",
    "log1p_last_record_age_horizons",
)
NETWORK_FEATURE_NAMES = DYADIC_FEATURE_NAMES + (
    "log1p_reverse_history_expected_count",
    "log1p_reverse_recent_expected_count",
    "log1p_source_out_degree",
    "log1p_target_in_degree",
    "log1p_directed_two_step_paths",
)
_MAX_SECOND = 2**63 - 1


def _duration(value: int, name: str) -> None:
    if type(value) is not int or not 0 < value <= _MAX_SECOND:
        raise ValueError(f"{name} must be positive integer source seconds within the archive range")


def _canonical_rows(rows: tuple) -> tuple:
    """Validate a bounded row collection and restore original physical order."""
    if type(rows) not in (tuple, list) or len(rows) > _MAX_ROWS:
        raise ValueError("archive feature history must be a bounded tuple or list of rows")
    normalized, line_ids, actors, pairs = [], set(), set(), set()
    for row in rows:
        if type(row) not in (tuple, list) or len(row) != 4 or any(type(value) is not int for value in row):
            raise ValueError("archive feature rows require four integers: line, source, target, time")
        line, source, target, when = row
        if not 1 <= line <= _MAX_ROWS or line in line_ids:
            raise ValueError("archive feature physical line IDs must be unique and within the row budget")
        if not 0 <= source <= 2**31 - 1 or not 0 <= target <= 2**31 - 1 or not 0 <= when <= _MAX_SECOND:
            raise ValueError("archive feature actor ID or source time is outside the archive range")
        line_ids.add(line)
        actors.update((source, target))
        if source != target:
            pairs.add((source, target))
        if len(actors) > _MAX_NODES or len(pairs) > _MAX_PAIRS:
            raise ValueError("archive feature history exceeds the actor/pair budget")
        normalized.append(tuple(row))
    return tuple(sorted(normalized))


def make_archive_features(history_rows: tuple, *, origin: int, horizon: int, recent_width: int) -> dict:
    """Build fixed dyadic and network features from rows strictly before origin.

    Duplicate published triples count as distinct records. The NetworkX graph
    is binary and excludes self-pairs; its degrees and directed two-step counts
    therefore do not multiply duplicate edges. Physical row IDs determine only
    a stable evidence representation, never event ordering.
    """
    for value, name in ((origin, "origin"), (horizon, "horizon"), (recent_width, "recent_width")):
        _duration(value, name)
    if origin + horizon > _MAX_SECOND:
        raise ValueError("archive feature target end exceeds the source-second range")
    history = _canonical_rows(history_rows)
    baseline = _archive_prediction(history, origin=origin, horizon=horizon, recent_width=recent_width)
    counts = {(row["source"], row["target"]): row for row in baseline["predictions"]}
    graph = nx.DiGraph()
    graph.add_edges_from(counts)
    last = {}
    for _, source, target, when in history:
        if source != target:
            last[source, target] = max(when, last.get((source, target), when))
    rows = []
    for pair, count in sorted(counts.items()):
        source, target = pair
        reverse = counts.get((target, source), {})
        dyadic = [
            log1p(count["history_count"] * horizon / origin),
            log1p(count["recent_count"] * horizon / recent_width),
            log1p((origin - last[pair]) / horizon),
        ]
        intermediaries = (set(graph.successors(source)) & set(graph.predecessors(target))) - {source, target}
        network = dyadic + [
            log1p(reverse.get("history_count", 0) * horizon / origin),
            log1p(reverse.get("recent_count", 0) * horizon / recent_width),
            log1p(graph.out_degree(source)),
            log1p(graph.in_degree(target)),
            log1p(len(intermediaries)),
        ]
        rows.append({"source": source, "target": target,
                     "dyadic_features": dyadic, "network_features": network})
    result = {
        "schema": "sociolab.archive-network-features.v1",
        "baseline_forecast_hash": baseline["content_hash"],
        "history_rows_hash": baseline["history_rows_hash"],
        "history_row_count": len(history),
        "origin_at_seconds": origin, "horizon_seconds": horizon, "recent_width_seconds": recent_width,
        "feature_names": {"dyadic": list(DYADIC_FEATURE_NAMES), "network": list(NETWORK_FEATURE_NAMES)},
        "rows": rows,
        "scope": {
            "contains_private_actor_records": True,
            "target": "matching_released_archive_row", "source_time_history_only": True,
            "source_time_unit": "relative_seconds", "historical_receipt_availability_verified": False,
            "source_membership_or_coverage_assertions_created": False,
            "graph_provider": "networkx.DiGraph", "graph_edges": "binary_nonself_history_pairs",
            "target_information_consumed": False,
        },
    }
    result["content_hash"] = content_hash(result)
    return result


class ArchiveFeatureReplay:
    """Append-only source-time replay with atomic history/clock updates.

    Each call supplies every newly available line in [previous_origin, origin).
    Rows can arrive in any order within that interval, including equal-time
    groups. A missing line cannot be detected from this archive API; late lines
    and corrections are rejected, not silently backdated into issued features.
    Empty intervals still advance the clock and expire the recent window.
    """

    def __init__(self, *, horizon: int, recent_width: int):
        _duration(horizon, "horizon")
        _duration(recent_width, "recent_width")
        self._horizon = horizon
        self._recent_width = recent_width
        self._origin = 0
        self._history = ()

    @property
    def origin(self) -> int:
        return self._origin

    @property
    def history_rows(self) -> tuple:
        return self._history

    def advance(self, origin: int, new_rows: tuple) -> dict:
        _duration(origin, "origin")
        if origin <= self._origin:
            raise ValueError("archive replay origins must strictly increase")
        added = _canonical_rows(new_rows)
        if any(not self._origin <= row[3] < origin for row in added):
            raise ValueError("archive replay accepts only rows in [previous_origin, origin)")
        combined = _canonical_rows(self._history + added)
        result = make_archive_features(combined, origin=origin, horizon=self._horizon,
                                       recent_width=self._recent_width)
        self._history = combined
        self._origin = origin
        return result
