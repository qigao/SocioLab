"""Reviewed-source temporal paths under explicit recorded-bin conventions.

This source-specific profile retains the archive and window definitions of the
static case. It makes no claim of observed message delivery or full coverage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from .contact_analysis import _SCENARIOS
from .recorded_contacts import (
    DOWNLOAD_URL, PAPER_DOI, REFERENCE_GZIP_SHA256, REFERENCE_PAYLOAD_SHA256,
    SOURCE_URL, TIME_ORIGIN_UNIX, load_recorded_contact_archive,
)


def hypertext2009_temporal_case_report(path: str | Path) -> dict:
    """Analyze only the exact reviewed payload; export aggregates and hashes.

    Neither community discovery nor reference-group selection runs here.
    Per-source hypothetical availability begins at each window's start. Both
    temporal variants allow waiting across unobserved intervals; that is a
    modeling convention, not an observation of attendance or signal retention.
    """
    archive = load_recorded_contact_archive(path)
    if archive.payload_sha256 != REFERENCE_PAYLOAD_SHA256:
        raise ValueError("this temporal case requires the reviewed Hypertext 2009 TSV payload fingerprint")
    from .temporal_contacts import temporal_contact_report

    scenarios = []
    for name, intervals, minimum_bins in _SCENARIOS:
        duration = intervals[0][1] - intervals[0][0]
        deadlines = tuple(value for value in (3600, 7200, 14400, 21600, 28800, 36000, 43200)
                          if value <= duration)
        windows = []
        for index, (start, end) in enumerate(intervals):
            analysis = temporal_contact_report(
                archive.actors, archive.records, start=start, end=end,
                minimum_bins=minimum_bins, deadlines_seconds=deadlines,
            )
            windows.append({"window_index": index, **analysis})
        scenarios.append({
            "scenario": name, "minimum_bins_per_pair": minimum_bins,
            "arrival_deadlines_seconds": list(deadlines), "windows": windows,
        })
    return {
        "kind": "RECORDED_CONTACT_TEMPORAL_STUDY",
        "profile": "hypertext2009-recorded-bin-reachability-v1",
        "research_question": "How much static ordered-pair reachability remains when contact-bin order is respected, under strict and same-bin relay conventions?",
        "engine": "networkx", "engine_version": version("networkx"),
        "source": {
            "dataset": "SocioPatterns Hypertext 2009 contact list",
            "source_url": SOURCE_URL, "download_url": DOWNLOAD_URL,
            "paper_doi": PAPER_DOI,
            "attribution": "SocioPatterns collaboration; Isella et al., What's in a crowd? Analysis of face-to-face behavioral networks, Journal of Theoretical Biology 271 (2011), 166-180.",
            "published_license_statement": "Creative Commons Attribution-NonCommercial-ShareAlike; see official dataset terms",
            "license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
            "compressed_sha256": archive.compressed_sha256,
            "payload_sha256": archive.payload_sha256,
            "compressed_bytes": archive.compressed_bytes, "payload_bytes": archive.payload_bytes,
            "reviewed_payload_matches": True,
            "reviewed_compressed_bytes_match": archive.compressed_sha256 == REFERENCE_GZIP_SHA256,
            "supplied_artifact_fully_parsed": True,
            "row_count": len(archive.records), "node_count": len(archive.actors),
            "distinct_recorded_pairs": len({row[1:] for row in archive.records}),
            "reversed_pair_order_rows_canonicalized": archive.reversed_order_rows,
            "duplicate_rows_dropped": 0, "self_pairs_dropped": 0,
        },
        "measurement": {
            "basis": "published_log_recorded_badge_proximity",
            "source_bin_seconds": 20, "source_contact_direction": "undirected",
            "temporal_reachability_direction": "ordered source-target pairs; generally asymmetric",
            "time_origin_unix": TIME_ORIGIN_UNIX,
            "time_origin_utc": datetime.fromtimestamp(TIME_ORIGIN_UNIX, timezone.utc).isoformat(),
            "source_interval_definition": "each endpoint t labels the recorded bin [t-20,t]",
            "window_rule": "start < recorded_bin_endpoint <= end",
            "node_universe": "all endpoint IDs anywhere in the reviewed archive, retained in every window",
            "node_universe_uses_later_records": True,
            "static_comparator": "same-window same-threshold recorded-pair graph; unordered reachable counts are doubled for ordered-pair comparison",
            "arrival_unit": "earliest reachable bin endpoint minus window start, including initial waiting; not a measured continuous transfer latency",
            "conditional_arrival_statistics": "summaries use reachable nonself ordered pairs; reachable pair sets can differ across windows and conventions",
        },
        "assumptions": {
            "source_initialization": "each source analyzed separately with a hypothetical signal available at window start",
            "waiting": "unlimited lossless waiting within the window, including periods without records",
            "contact_use": "every qualifying recorded pair-bin permits a hypothetical transfer in either direction under the selected bin rule",
            "strict": "at most one contact hop per bin; successive contact-bin endpoints strictly increase",
            "nonstrict": "multiple contact hops may occur in one bin; contact-bin endpoints are nondecreasing",
            "pair_filter": "a pair qualifies using its total bin count over the whole window; retain all its in-window records, including earlier bins",
            "threshold_sensitivity_uses_later_window_records": True,
            "actual_signal_retention_observed": False,
            "actual_transmission_probability_specified": False,
        },
        "scenarios": scenarios,
        "qualification": {
            "scope": "retrospective paths on the reviewed recorded-bin graphs under declared conventions",
            "recorded_bin_order_paths_computed": True,
            "physical_contact_observation_complete": None,
            "source_log_completeness_established": False,
            "device_uptime_available": False, "population_boundary_qualified": False,
            "actual_transmission_observed": False,
            "time_respecting_transmission_validated": False,
            "real_world_transmission_bounds_established": False,
            "forecast_validated": False, "causal_effect_identified": False,
            "temporal_community_inferred": False, "temporal_group_centrality_computed": False,
            "saom_model_fitted": False, "raw_source_data_exported": False,
        },
        "limits": [
            "The strict/nonstrict/static inclusion compares models on the selected records; it is not a statistical or physical bound on real transmission.",
            "Equal calendar windows and waiting edges do not establish equal attendance, device exposure, presence or retention of information.",
            "Missing recorded contacts are not confirmed noncontacts; omitted real contacts and unknown transfer delays lie outside these models.",
            "The archive actor universe and whole-window multi-bin filter use later records; this is not a past-only forecast or online decision rule.",
            "Bin-endpoint arrival labels do not identify exact within-bin ordering or continuous transfer latency; BFS edge counts are not elapsed seconds.",
            "Arrival summary comparisons condition on each graph's reachable ordered pairs, which need not be the same pairs across windows.",
            "Actor-level temporal reachability is generally asymmetric and nontransitive; no static SCC, community or key-group metric is reinterpreted as temporal here.",
            "This source contains no observed message deliveries, language labels, conflict measurements or activity attendance incidences.",
        ],
    }
