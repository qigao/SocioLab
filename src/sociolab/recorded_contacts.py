"""Reviewed Hypertext 2009 archive: recorded badge proximity, not complete ties.

The published file is the object of this descriptive case. Parsing every row
does not establish device uptime, conference attendance, or all real contacts.
No input is relabeled as a complete social-network snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import zlib


SOURCE_URL = "https://sociopatterns.org/datasets/hypertext-2009-dynamic-contact-network/"
DOWNLOAD_URL = "https://sociopatterns.org/assets/data/ht2009_contact_list.dat.gz"
PAPER_DOI = "https://doi.org/10.1016/j.jtbi.2010.11.033"
REFERENCE_GZIP_SHA256 = "43014e65bb8f6aa7d75d36a8ab61279b617bee88197e04a330c4386305ae1738"
REFERENCE_PAYLOAD_SHA256 = "ed7fcc05f614cd47ffa230183ce2375af140fd13ca98a253d236f9ba043f695e"
TIME_ORIGIN_UNIX = 1246255200
_MAX_COMPRESSED_BYTES = 8_000_000
_MAX_DECOMPRESSED_BYTES = 32_000_000
_MAX_RECORDS = 500_000
_MAX_ACTORS = 200
_MAX_TIME_SECONDS = 7 * 86400
_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,9})\Z")


@dataclass(frozen=True, slots=True)
class RecordedContactArchive:
    """Validated immutable rows; actor IDs are an artifact-derived node set."""

    actors: tuple[int, ...]
    records: tuple[tuple[int, int, int], ...]
    compressed_sha256: str
    payload_sha256: str
    compressed_bytes: int
    payload_bytes: int
    reversed_order_rows: int


def load_recorded_contact_archive(path: str | Path) -> RecordedContactArchive:
    """Read bounded ASCII gzip TSV of (20-second bin endpoint, ID, ID).

    Reverse ordering of an undirected pair is canonicalized. A repeated
    (time, unordered pair), self-pair, malformed row, or off-grid time fails;
    none is silently dropped. Format validity alone is not source admission.
    """
    with Path(path).open("rb") as stream:
        raw = stream.read(_MAX_COMPRESSED_BYTES + 1)
    if not raw or len(raw) > _MAX_COMPRESSED_BYTES:
        raise ValueError("contact gzip must be nonempty and within the compressed byte limit")
    try:
        with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
            payload = stream.read(_MAX_DECOMPRESSED_BYTES + 1)
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as error:
        raise ValueError("invalid contact gzip stream") from error
    if not payload or len(payload) > _MAX_DECOMPRESSED_BYTES:
        raise ValueError("contact payload must be nonempty and within the decompressed byte limit")
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("contact TSV requires ASCII integer fields") from error
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines or len(lines) > _MAX_RECORDS:
        raise ValueError("contact TSV exceeds the row limit or contains no records")
    actors, seen, records = set(), set(), []
    previous_time = 0
    reversed_rows = 0
    for number, line in enumerate(lines, 1):
        fields = line.removesuffix("\r").split("\t")
        if len(fields) != 3 or any(_INTEGER.fullmatch(value) is None for value in fields):
            raise ValueError(f"contact row {number} requires exactly three canonical integer TSV fields")
        time_end, source, target = map(int, fields)
        if (not 0 < time_end <= _MAX_TIME_SECONDS or time_end % 20
                or time_end < previous_time):
            raise ValueError(f"contact row {number} has an unordered or unsupported 20-second endpoint")
        if max(source, target) > 2**31 - 1 or source == target:
            raise ValueError(f"contact row {number} contains an invalid ID or self-pair")
        previous_time = time_end
        actors.update((source, target))
        if len(actors) > _MAX_ACTORS:
            raise ValueError("contact archive exceeds the fixed case node budget")
        reversed_rows += int(source > target)
        record = (time_end, min(source, target), max(source, target))
        if record in seen:
            raise ValueError(f"contact row {number} duplicates an undirected pair-bin")
        seen.add(record)
        records.append(record)
    return RecordedContactArchive(
        tuple(sorted(actors)), tuple(sorted(records)), sha256(raw).hexdigest(),
        sha256(payload).hexdigest(), len(raw), len(payload), reversed_rows,
    )


def hypertext2009_case_report(path: str | Path) -> dict[str, object]:
    """Run the predeclared recorded-contact case on the reviewed TSV payload.

    Exact decompressed bytes are required to apply this source's clock and
    study scope. Recompressed equivalent bytes are allowed and separately
    fingerprinted. No original IDs, pair lists, or memberships are exported.
    """
    archive = load_recorded_contact_archive(path)
    if archive.payload_sha256 != REFERENCE_PAYLOAD_SHA256:
        raise ValueError("this case requires the reviewed Hypertext 2009 TSV payload fingerprint")
    from .contact_analysis import recorded_contact_analysis

    analysis = recorded_contact_analysis(archive.actors, archive.records)
    return {
        "kind": "RECORDED_CONTACT_CASE_STUDY",
        "profile": "hypertext2009-recorded-proximity-v1",
        "research_question": "How do recorded cross-community contacts, static reachability and the same retrospective reference group differ between two equal observation windows?",
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
            "first_bin_endpoint_seconds": archive.records[0][0],
            "last_bin_endpoint_seconds": archive.records[-1][0],
        },
        "measurement": {
            "basis": "published_log_recorded_badge_proximity",
            "directed": False, "source_bin_seconds": 20,
            "source_interval_definition": "the source documents each endpoint t as the contact bin [t-20,t]",
            "window_rule": "for aligned half-open [start,end) bin-start windows, include records with start < t <= end",
            "time_origin_unix": TIME_ORIGIN_UNIX,
            "time_origin_utc": datetime.fromtimestamp(TIME_ORIGIN_UNIX, timezone.utc).isoformat(),
            "documented_local_origin": "2009-06-29 08:00, as paired with the source UNIX origin",
            "duration_unit": "recorded pair-bin seconds = 20 * retained pair-bin count; not independently measured continuous contact time",
            "edge_absence_meaning": "no pair satisfying the scenario's window and bin-count rule in the supplied artifact; not confirmed physical noncontact",
            "node_universe": "all identifiers appearing anywhere in the reviewed archive, retained in every graph, including zero-record nodes",
            "node_universe_uses_later_records": True,
            "conference_roster_or_attendance_inferred": False,
            "zero_degree_meaning": "zero qualifying records in this graph, not established social isolation or absence",
            "binary_topology": "one undirected unit edge per pair meeting the declared bin threshold; bin totals are separate summaries",
        },
        "qualification": {
            "scope": "retrospective descriptive comparison of the reviewed published-record graphs",
            "physical_contact_observation_complete": None,
            "device_uptime_available": False, "source_log_completeness_established": False,
            "all_conference_participants_covered": False,
            "population_boundary_qualified": False,
            "social_tie_absences_inferred": False,
            "time_respecting_transmission_validated": False,
            "causal_effect_identified": False, "forecast_validated": False,
            "saom_model_fitted": False, "raw_source_data_exported": False,
        },
        "analysis": analysis,
        "limits": [
            "The paper reports voluntary badge participation of about 75%; volunteer selection and missing contacts remain possible.",
            "An identifier's zero records in a window do not establish attendance, eligibility, device uptime or lack of real contact.",
            "Communities and group betweenness describe static aggregated recorded topology, not observed alliances, influence or temporal spreading paths.",
            "The fixed baseline partition was optimized on the first window; later cross-partition differences are relative to that fitted partition, not a test of social integration.",
            "A fixed Louvain seed ensures this execution is reproducible; community-solution uniqueness and robustness across algorithms or seeds are not established.",
            "The reference group and node universe use the whole archive, including later records; this is not a past-only forecast or intervention evaluation.",
            "Window and bin-threshold comparisons are descriptive sensitivity checks, not confidence intervals or an uncertainty model for missing sensors.",
        ],
    }
