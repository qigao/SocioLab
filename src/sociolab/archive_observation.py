"""Descriptive record presence in a fixed released archive.

Rows and their absence describe the supplied file. Neither establishes real
communication coverage, membership, recording outages or relationship states.
This audit uses the full released time stream, including later records around
an empty interval; it is not a past-only forecast or a source of coverage events.
"""

from __future__ import annotations

from bisect import bisect_left

from .archive_features import _canonical_rows
from .snapshots import content_hash


_MAX_SECOND = 2**63 - 1
_MAX_WINDOWS = 100
_MAX_REPORTED_GAPS = 20


def _windows(value: list[dict]) -> list[dict]:
    if type(value) is not list or not 1 <= len(value) <= _MAX_WINDOWS:
        raise ValueError("archive audit requires 1 to 100 ordered windows")
    normalized, identifiers, previous_end = [], set(), None
    for item in value:
        if type(item) is not dict or set(item) != {"id", "start", "end"}:
            raise ValueError("archive audit windows require exactly id, start and end")
        identifier, start, end = item["id"], item["start"], item["end"]
        if type(identifier) is not str or not identifier.strip() or len(identifier) > 100:
            raise ValueError("archive audit window id must be a nonempty string of at most 100 characters")
        if identifier in identifiers:
            raise ValueError("archive audit window ids must be unique")
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= _MAX_SECOND):
            raise ValueError("archive audit windows require 0 <= start < end within integer source seconds")
        if previous_end is not None and start < previous_end:
            raise ValueError("archive audit windows must be ordered and nonoverlapping")
        normalized.append({"id": identifier, "start": start, "end": end})
        identifiers.add(identifier)
        previous_end = end
    return normalized


def _longest_gap(times: list[int]) -> dict:
    result = {
        "status": "NOT_AVAILABLE", "maximum_elapsed_seconds": None,
        "tied_maximum_count": 0, "first_20_intervals": [], "intervals_truncated": False,
        "interval_boundary": "open_both_record_endpoints_excluded",
        "meaning": "between_record_elapsed_time_not_verified_unobserved_duration",
    }
    if len(times) < 2:
        return result
    maximum = max(right - left for left, right in zip(times, times[1:]))
    count, intervals = 0, []
    for left, right in zip(times, times[1:]):
        if right - left != maximum:
            continue
        count += 1
        if len(intervals) < _MAX_REPORTED_GAPS:
            intervals.append({"left_record_seconds": left, "right_record_seconds": right,
                              "elapsed_seconds": maximum,
                              "interior_integer_seconds": max(maximum - 1, 0)})
    result.update(status="AVAILABLE", maximum_elapsed_seconds=maximum,
                  tied_maximum_count=count, first_20_intervals=intervals,
                  intervals_truncated=count > len(intervals))
    return result


def audit_archive_windows(rows: tuple, windows: list[dict]) -> dict:
    """Report fixed half-open windows and open between-record gaps.

    Every source row, including self records and duplicate triples, contributes
    to archive presence. Original physical IDs supply stable evidence identities;
    source time supplies window membership. A future tail can change this complete
    archive audit, unlike an already issued historical forecast. No input is mutated.
    """
    source = _canonical_rows(rows)
    declared = _windows(windows)
    times = sorted({row[3] for row in source})
    reports = []
    for window in declared:
        start, end = window["start"], window["end"]
        lower, upper = bisect_left(times, start), bisect_left(times, end)
        selected = tuple(row for row in source if start <= row[3] < end)
        previous = times[lower - 1] if lower else None
        following = times[upper] if upper < len(times) else None
        nonself = [row for row in selected if row[1] != row[2]]
        reports.append({
            "id": window["id"], "start_seconds": start, "end_seconds": end,
            "row_count": len(selected), "nonself_row_count": len(nonself),
            "distinct_actor_count": len({actor for row in selected for actor in row[1:3]}),
            "distinct_nonself_pair_count": len({row[1:3] for row in nonself}),
            "target_rows_hash": content_hash(selected),
            "archive_row_status": "ARCHIVE_ROWS_PRESENT" if selected else "NO_ARCHIVE_ROWS",
            "real_coverage_status": "UNKNOWN", "real_coverage_evidence": [],
            "membership_eligibility_verified": False,
            "strict_complete_observation_r1_status": "NOT_ADMITTED",
            "previous_record_at_seconds": previous, "next_record_at_seconds": following,
            "empty_window_internally_bounded": not selected and previous is not None and following is not None,
            "first_record_in_window_seconds": times[lower] if lower < upper else None,
            "last_record_in_window_seconds": times[upper - 1] if lower < upper else None,
        })
    result = {
        "schema": "sociolab.archive-observation-audit.v1",
        "source_rows_hash": content_hash(source), "source_row_count": len(source),
        "distinct_record_time_count": len(times),
        "first_record_seconds": times[0] if times else None,
        "last_record_seconds": times[-1] if times else None,
        "windows": reports, "longest_between_record_gap": _longest_gap(times),
        "scope": {
            "analysis": "retrospective_full_released_archive_record_presence",
            "source_time_unit": "relative_seconds", "window_boundary": "left_closed_right_open",
            "contains_private_actor_records": False, "past_only_forecast": False,
            "later_archive_records_used_for_gap_boundaries": True,
            "calendar_mapping_verified": False, "recording_start_or_end_inferred": False,
            "real_observation_coverage_inferred": False, "coverage_events_created": False,
            "archive_gap_cause": "UNKNOWN", "recording_outage_inferred": False,
            "real_communication_absence_inferred": False, "relationship_termination_inferred": False,
        },
    }
    result["content_hash"] = content_hash(result)
    return result
