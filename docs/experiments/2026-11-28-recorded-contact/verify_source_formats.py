"""Independently audit the two official Hypertext 2009 source encodings.

Standard library only; no SocioLab import, graph algorithm, source correction,
or row-level output. Supply the original official gzip files locally. The
JSON comparison is a format diagnostic, not a second observation system.
"""

import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path


SOURCE_PAGE = "https://sociopatterns.org/datasets/hypertext-2009-dynamic-contact-network/"
DATA_ROOT = "https://sociopatterns.org/assets/data/"
PAPER = "https://doi.org/10.1016/j.jtbi.2010.11.033"
MANUSCRIPT = "https://iris.unito.it/bitstream/2318/1731001/2/1006.1260.pdf"
EXPECTED = {
    "ht2009_contact_list.dat.gz": "43014e65bb8f6aa7d75d36a8ab61279b617bee88197e04a330c4386305ae1738",
    "ht2009_contact_intervals.json.gz": "1c9bdc1315708a296fcd1f407fa84c5cd3103f0e0b4b3b645c8c7676f3b93bde",
}
ORIGIN = 1246255200
WINDOWS = ((0, 36000), (86400, 122400))


def fingerprint_and_read(path, source_name):
    raw = path.read_bytes()
    if len(raw) > 1_000_000 or sha256(raw).hexdigest() != EXPECTED[source_name]:
        raise ValueError("input differs from the inspected official source: " + source_name)
    with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
        unpacked = stream.read(2_000_001)
    if len(unpacked) > 2_000_000:
        raise ValueError("source exceeds the decompression budget")
    return unpacked.decode("utf-8"), {
        "source_name": source_name, "source_url": DATA_ROOT + source_name,
        "compressed_bytes": len(raw), "compressed_sha256": sha256(raw).hexdigest(),
        "decompressed_bytes": len(unpacked), "decompressed_sha256": sha256(unpacked).hexdigest(),
        "matches_inspected_source": True,
    }


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def audit(contact_list, contact_intervals):
    text, tsv_source = fingerprint_and_read(contact_list, "ht2009_contact_list.dat.gz")
    rows = []
    reversed_order = 0
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 3 or any(not item.isascii() or not item.isdecimal() for item in fields):
            raise ValueError("TSV must contain three nonnegative integer fields per line")
        tick, left, right = map(int, fields)
        if tick <= 0 or tick % 20 or left == right:
            raise ValueError("unexpected TSV tick or self-contact")
        reversed_order += left > right
        rows.append((tick, min(left, right), max(left, right)))
    if not rows or any(a[0] > b[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("TSV ticks must be nondecreasing")
    observed = set(rows)
    if len(observed) != len(rows):
        raise ValueError("TSV repeats an unordered pair in a time bin")
    actors = {actor for _, left, right in rows for actor in (left, right)}
    pairs = {(left, right) for _, left, right in rows}

    text, json_source = fingerprint_and_read(contact_intervals, "ht2009_contact_intervals.json.gz")
    source = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if type(source) is not dict:
        raise ValueError("interval encoding must be an object")
    intervals = []
    pair_entries = []
    for left, neighbors in source.items():
        if not left.isascii() or not left.isdecimal() or type(neighbors) is not dict:
            raise ValueError("invalid interval node or neighbor object")
        for right, spans in neighbors.items():
            if not right.isascii() or not right.isdecimal() or type(spans) is not list:
                raise ValueError("invalid interval neighbor or interval list")
            a, b = sorted((int(left), int(right)))
            if a == b:
                raise ValueError("self-contact in interval encoding")
            pair_entries.append((a, b))
            previous_end = None
            for span in spans:
                if (type(span) is not list or len(span) != 2
                        or any(type(t) is not int for t in span)
                        or not 0 <= span[0] < span[1]
                        or (previous_end is not None and span[0] < previous_end)):
                    raise ValueError("invalid or overlapping interval")
                intervals.append((a, b, span[0], span[1]))
                previous_end = span[1]
    if len(pair_entries) != len(set(pair_entries)):
        raise ValueError("same unordered pair appears twice as a JSON neighbor entry")

    # Treat JSON start,start+20,...<end as candidate TSV endpoint labels only
    # for a source-format diagnostic. This is not a physical-time conversion.
    expanded = {(tick, a, b) for a, b, start, end in intervals
                for tick in range(start, end, 20)}
    off_grid = [(start, end) for _, _, start, end in intervals if start % 20 or end % 20]
    aligned = {(tick, a, b) for a, b, start, end in intervals
               for tick in range(start - start % 20, end, 20)}

    windows = []
    for start, end in WINDOWS:
        selected = [(t, a, b) for t, a, b in rows if start < t <= end]
        ids = {actor for _, a, b in selected for actor in (a, b)}
        windows.append({
            "source_bin_start_window": [start, end], "duration_seconds": end - start,
            "tsv_endpoint_selection": "window_start < t <= window_end",
            "utc_start": datetime.fromtimestamp(ORIGIN + start, timezone.utc).isoformat(),
            "utc_end": datetime.fromtimestamp(ORIGIN + end, timezone.utc).isoformat(),
            "recorded_pair_bins": len(selected), "recorded_pair_bin_seconds": len(selected) * 20,
            "recorded_unordered_pairs": len({(a, b) for _, a, b in selected}),
            "ids_with_recorded_contacts": len(ids),
            "archive_ids_without_recorded_contacts": len(actors - ids),
            "first_recorded_endpoint": min(t for t, _, _ in selected),
            "last_recorded_endpoint": max(t for t, _, _ in selected),
            "recording_completeness_inferred_from_time_span": False,
        })

    return {
        "kind": "HYPERTEXT_RECORDED_CONTACT_SOURCE_REVIEW",
        "status": "INSPECTED_FOR_PUBLISHED_RECORDS_DESCRIPTION",
        "inspected_utc": datetime.now(timezone.utc).isoformat(),
        "auditor": {"dependency_scope": "Python standard library; no SocioLab imports",
                    "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest()},
        "sources": [tsv_source, json_source],
        "primary_references": {
            "dataset_page": SOURCE_PAGE,
            "published_paper": PAPER,
            "author_manuscript": MANUSCRIPT,
            "license_link_from_dataset_page": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
            "dataset_citation": "Isella et al. (2011), What's in a crowd? Analysis of face-to-face behavioral networks, Journal of Theoretical Biology 271, 166-180.",
            "acknowledgement": "SocioPatterns collaboration, https://sociopatterns.org/",
        },
        "documented_measurement": {
            "dataset_page_scope": "Voluntary conference badge wearers, about 110 attendees over about 2.5 days; no personal data or Live Social Semantics metadata are published here.",
            "tsv_semantics": "t i j records an undirected proximity observation in the source-described interval [t-20,t]; timestamps are seconds relative to Unix origin 1246255200.",
            "origin_utc": "2009-06-29T06:00:00+00:00",
            "origin_local_description": "Official page says 08:00 on 29 June 2009; this matches Europe/Rome summer time, not 08:00 UTC.",
            "paper_section_II_pdf_page_3": "Badges exchange short-range radio packets; a contact is maintained by packet exchange within successive 20-second bins. About 75% of HT09 participants volunteered; the authors explicitly discuss possible volunteer-selection bias and incomplete sampling.",
            "paper_section_III_pdf_pages_3_to_4": "Daily static graphs link two tags when at least one contact is detected; weights aggregate contact duration.",
            "paper_abstract_pdf_page_2": "The authors report that static aggregated networks can yield erroneous transmission-path conclusions compared with time-resolved data.",
            "license_statement": "The official dataset page links Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported and requests the paper citation and SocioPatterns acknowledgement.",
        },
        "tsv_audit": {
            "rows": len(rows), "unique_pair_bins": len(observed), "endpoint_ids": len(actors),
            "unique_unordered_pairs": len(pairs), "distinct_endpoint_ticks": len({t for t, _, _ in rows}),
            "first_endpoint_tick": rows[0][0], "last_endpoint_tick": rows[-1][0],
            "endpoint_grid_seconds": 20, "all_ticks_on_grid": True,
            "duplicate_unordered_pair_bins": 0, "self_contacts": 0,
            "rows_with_descending_source_id_order": reversed_order,
            "times_nondecreasing": True,
        },
        "json_format_diagnostic": {
            "outer_keys": len(source), "endpoint_ids_including_neighbor_keys": len({x for a, b, _, _ in intervals for x in (a, b)}),
            "unordered_pair_entries": len(pair_entries), "interval_records": len(intervals),
            "candidate_expansion": "range(start,end,20) interpreted as candidate TSV endpoint labels, solely to compare source encodings",
            "expanded_unique_pair_bins": len(expanded),
            "extra_compared_with_tsv": len(expanded - observed),
            "missing_compared_with_tsv": len(observed - expanded),
            "exact_source_encoding_match": expanded == observed,
            "off_grid_interval_count": len(off_grid),
            "off_grid_time_ranges_without_actor_ids": [list(span) for span in off_grid],
            "hypothetical_floor_start_to_grid_matches_tsv": aligned == observed,
            "hypothetical_alignment_applied_to_sources": False,
            "decision": "Use the unchanged official TSV and its explicit interval definition for analysis. Preserve the JSON discrepancy; do not silently correct it or claim exact agreement of the raw encodings.",
            "independent_sensor_validation": False,
        },
        "specified_equal_windows": windows,
        "scope_and_qualification": {
            "measurement_basis": "published_file_recorded_badge_proximity",
            "actor_universe_basis": "Retrospective union of all anonymous endpoint IDs in the TSV archive; not an independently verified conference roster.",
            "zero_edge_meaning": "No qualifying record in the selected published-file window, not confirmed absence of physical proximity or a social relationship.",
            "all_published_input_rows_parsed": True,
            "source_log_complete": False, "known_device_uptime": False,
            "source_log_completeness_qualification": "Not independently established by the published files; parsing every supplied row is a separate check.",
            "complete_physical_observations": False, "all_attendee_coverage": False,
            "participant_presence_or_eligibility_inferred": False,
            "physical_contact_duration_measured_continuously": False,
            "source_event_count_means_social_encounter_count": False,
            "social_ties_or_friendship_measured": False,
            "causal_effect_identified": False, "temporal_transmission_paths_identified": False,
            "source_rows_or_actor_ids_exported": False,
            "limits": [
                "No independent badge uptime, attendance, or exposure ledger is supplied by these two published files.",
                "A time window inside the first/last recorded ticks does not establish continuous observation coverage.",
                "A node with no record in a window remains in the fixed archive universe as zero recorded degree, with physical state unknown.",
                "Twenty times the pair-bin count is recorded pair-bin seconds, not an exact measurement of continuous interaction seconds or distinct encounters.",
                "Static connected paths do not establish time-respecting or realized information/disease transmission.",
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contact_list", type=Path)
    parser.add_argument("contact_intervals", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.contact_list, args.contact_intervals), indent=2,
                     sort_keys=True, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
