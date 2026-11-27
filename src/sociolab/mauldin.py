"""Aggregate audit of the supplied Mauldin MSW archive; no panel or estimator.

Unlisted nominations are never expanded into absent dyads. The reviewed
documents leave the eligible alter roster unresolved, so this reader cannot
admit an empirical model even when every source byte matches the reference.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
import re
import stat
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED
import zlib


SOURCE_URL = "https://mavmatrix.uta.edu/socialnetworksforsocialgood_datasets/2/"
REFERENCE_ARCHIVE_SHA256 = "d64a69e38401f2d1b81ae00f57dca670352a443c3a6332ddab4d01ff341d1c01"
_REVIEWED_DOCUMENT_SHA256 = {
    "README.txt": "692c2ba8a7d90375bcc2dd236e069b85191a13ae8c3ff84aa1b9c77a9095b6d7",
    "Data Dictionary.pdf": "0e80647d08871b9bcfff0fb342d6da528c77625f1e9bdac3ef1b21b9ec1ae36e",
}
_RELATIONS = (("Academic", "academic_discussion"), ("Friendship", "friendship"),
              ("Professional", "professional_influence"))
_NETWORKS = (("w1_KnowofEdgelist.csv", 1, "knows_of"),) + tuple(
    (f"w{wave}_{file_label}Edgelist.csv", wave, relation)
    for wave in (2, 3, 4) for file_label, relation in _RELATIONS
)
_CHARACTERISTICS = tuple(f"w{wave}_Characteristics.csv" for wave in (1, 3, 4))
_REQUIRED_FILES = frozenset({
    "README.txt", "Data Dictionary.pdf", "MANIFEST.TXT", "ParticipationAcrossWaves.csv",
    "SharedCourseAffiliationMatrix.csv", "SharedCourseValuedEdgelist.csv",
    *_CHARACTERISTICS, *(name for name, _, _ in _NETWORKS),
})
_MAX_ARCHIVE_BYTES = 8_000_000
_MAX_MEMBER_BYTES = 4_000_000
_MAX_TOTAL_BYTES = 16_000_000
_MAX_MEMBERS = 40
_MAX_CSV_ROWS = 100_000
_MAX_CSV_COLUMNS = 200
_ID = re.compile(r"[0-9]{4}\Z")
_COVERAGE = ("recorded_nominations", "reported_no_alters", "unknown_na",
             "missing_ego_record", "ambiguous_item_encoding")


def _hash(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _source_members(path: str | Path) -> tuple[bytes, dict[str, bytes]]:
    with Path(path).open("rb") as stream:
        raw = stream.read(_MAX_ARCHIVE_BYTES + 1)
    if not raw or len(raw) > _MAX_ARCHIVE_BYTES:
        raise ValueError("Mauldin ZIP must be nonempty and within the archive byte limit")
    members: dict[str, bytes] = {}
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_MEMBERS:
                raise ValueError("Mauldin ZIP exceeds the member count limit")
            total = 0
            for entry in entries:
                name = entry.orig_filename
                parts = PurePosixPath(name)
                if (not name or "\x00" in name or "\\" in name or ":" in name
                        or parts.is_absolute() or ".." in parts.parts
                        or parts.as_posix() != name.rstrip("/")):
                    raise ValueError("Mauldin ZIP contains an unsafe member path")
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError("Mauldin ZIP contains a nonregular member")
                if entry.flag_bits & 1 or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise ValueError("Mauldin ZIP uses encryption or unsupported compression")
                if entry.is_dir():
                    if entry.file_size:
                        raise ValueError("Mauldin ZIP directory contains unexpected data")
                    continue
                basename = parts.name
                if basename in members:
                    raise ValueError("Mauldin ZIP contains duplicate required basenames")
                if basename not in _REQUIRED_FILES:
                    raise ValueError("Mauldin ZIP contains an unsupported source member")
                total += entry.file_size
                if entry.file_size > _MAX_MEMBER_BYTES or total > _MAX_TOTAL_BYTES:
                    raise ValueError("Mauldin ZIP exceeds the uncompressed byte limits")
                with archive.open(entry) as stream:
                    payload = stream.read(_MAX_MEMBER_BYTES + 1)
                if len(payload) != entry.file_size or len(payload) > _MAX_MEMBER_BYTES:
                    raise ValueError("Mauldin ZIP member size does not match its bounded payload")
                members[basename] = payload
    except (BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as error:
        raise ValueError("Mauldin source is not a readable supported ZIP archive") from error
    if set(members) != _REQUIRED_FILES:
        raise ValueError("Mauldin ZIP lacks required source files")
    return raw, members


def _csv_table(raw: bytes, name: str, *, retain: bool) -> tuple[list[str], list[list[str]], dict]:
    rows = []
    try:
        reader = csv.reader(StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader)
        if not header or len(header) > _MAX_CSV_COLUMNS:
            raise ValueError("Mauldin CSV has an invalid column count: " + name)
        count = 0
        for row in reader:
            count += 1
            if len(row) != len(header) or count > _MAX_CSV_ROWS:
                raise ValueError("Mauldin CSV has a malformed or oversized table: " + name)
            if retain:
                rows.append(row)
    except (UnicodeError, csv.Error, StopIteration) as error:
        raise ValueError("Mauldin CSV cannot be decoded or parsed: " + name) from error
    return header, rows, {"data_records": count, "columns": len(header),
                          "blank_header_columns": header.count("")}


def _roster(rows: list[list[str]]) -> tuple[dict, dict[str, list[list[str]]]]:
    if not rows:
        raise ValueError("Mauldin participation roster is empty")
    by_id = defaultdict(list)
    issues = Counter()
    statuses = {wave: Counter() for wave in (1, 2, 3, 4)}
    for row in rows:
        if _ID.fullmatch(row[0]):
            by_id[row[0]].append(row)
        else:
            issues["invalid_identity_records"] += 1
        if row[1] not in {"1", "2", "3", "4", "5", "6"}:
            issues["unsupported_cohort_code_records"] += 1
        for wave in (1, 2, 3, 4):
            allowed = {"-99", "0", "1"} | ({"10"} if wave == 4 else set())
            code = row[wave + 1] if row[wave + 1] in allowed else "UNSUPPORTED"
            statuses[wave][code] += 1
            if code == "UNSUPPORTED":
                issues["unsupported_status_records"] += 1
    issues["duplicate_identity_records"] = sum(len(records) - 1 for records in by_id.values())
    report = {"raw_records": len(rows), "unique_actors": len(by_id),
              "reference_roster_size": 145, "roster_filter_applied": False,
              "per_wave_status_counts": {str(w): dict(sorted(c.items())) for w, c in statuses.items()},
              "anomalies": {key: value for key, value in sorted(issues.items()) if value}}
    return report, dict(by_id)


def _status(roster: dict, actor: str, wave: int) -> str:
    records = roster.get(actor, [])
    if len(records) != 1:
        return "AMBIGUOUS_ROSTER"
    code = records[0][wave + 1]
    return code if code in {"-99", "0", "1"} | ({"10"} if wave == 4 else set()) else "UNSUPPORTED"


def _network(rows: list[list[str]], name: str, wave: int, relation: str,
             roster: dict, *, reviewed: bool) -> tuple[dict, set, dict]:
    encodings = defaultdict(Counter)
    row_counts = Counter({key: 0 for key in ("target_id_records", "blank_alter_records", "na_alter_records",
                                            "unsupported_alter_records")})
    anomalies = Counter()
    positive_records = Counter()
    for ego, alter in rows:
        encoding = "blank" if alter == "" else "na" if alter == "NA" else "positive" if _ID.fullmatch(alter) else "invalid"
        row_counts[{"blank": "blank_alter_records", "na": "na_alter_records",
                    "positive": "target_id_records", "invalid": "unsupported_alter_records"}[encoding]] += 1
        if not _ID.fullmatch(ego):
            anomalies["invalid_ego_id_records"] += 1
            continue
        if ego not in roster:
            anomalies["out_of_roster_ego_records"] += 1
            continue
        encodings[ego][encoding] += 1
        if encoding == "invalid":
            anomalies["unsupported_alter_records"] += 1
        elif encoding == "positive":
            if alter not in roster:
                anomalies["out_of_roster_alter_records"] += 1
            elif ego == alter:
                anomalies["self_nomination_records"] += 1
            else:
                positive_records[(ego, alter)] += 1
    coverage = {}
    for ego in roster:
        counts = encodings[ego]
        if not counts:
            state = "missing_ego_record"
        elif set(counts) == {"positive"}:
            state = "recorded_nominations"
        elif counts == {"blank": 1}:
            state = "reported_no_alters"
        elif set(counts) == {"na"}:
            state = "unknown_na"
        else:
            state = "ambiguous_item_encoding"
        coverage[ego] = state
        if state in {"missing_ego_record", "ambiguous_item_encoding"}:
            anomalies[state + "_egos"] += 1
        anomalies["duplicate_placeholder_records"] += max(0, counts["blank"] - 1) + max(0, counts["na"] - 1)
        if reviewed and state in {"recorded_nominations", "reported_no_alters"} and _status(roster, ego, wave) != "1":
            anomalies["answered_item_with_nonparticipant_or_ambiguous_status_egos"] += 1
    anomalies["duplicate_positive_records"] = sum(count - 1 for count in positive_records.values())
    positives = set(positive_records)
    counts = Counter(coverage.values())
    status_coverage = Counter((_status(roster, actor, wave), state) for actor, state in coverage.items())
    report = {
        "file": name, "wave": wave, "relation": relation,
        "raw_records": len(rows), "row_counts": dict(row_counts),
        "unique_in_roster_offdiagonal_id_pairs": len(positives),
        "unique_recorded_positive_nominations": len(positives) if reviewed else None,
        "anomalies": {key: value for key, value in sorted(anomalies.items()) if value},
        "item_coverage": {key: counts[key] for key in _COVERAGE} if reviewed else None,
        "status_by_item_coverage": [
            {"status_code": code, "item_coverage": state, "ego_count": count}
            for (code, state), count in sorted(status_coverage.items())
        ] if reviewed else None,
        "incoming_positive_nominations_by_alter_status": dict(sorted(Counter(
            _status(roster, alter, wave) for _, alter in positives).items())) if reviewed else None,
        "unlisted_dyads_expanded_to_zero": False,
        "confirmed_absent_dyads": 0,
        "item_interpretation_applied": reviewed,
    }
    return report, positives, coverage


def _transition(before: tuple, after: tuple) -> dict:
    first, old, old_coverage = before
    second, new, new_coverage = after
    categories = {"persistent": old & new, "first_recorded": new - old,
                  "no_longer_recorded": old - new}
    report = {"relation": first["relation"], "before_wave": first["wave"], "after_wave": second["wave"],
              "positive_nomination_union_count": len(old | new), "tie_creation_or_dissolution_inferred": False}
    for name, pairs in categories.items():
        coverage = Counter((old_coverage[ego], new_coverage[ego]) for ego, _ in pairs)
        report[name] = {"count": len(pairs), "ego_item_coverage": [
            {"before": old_state, "after": new_state, "count": count}
            for (old_state, new_state), count in sorted(coverage.items())]}
    coverage = Counter((old_coverage[ego], new_coverage[ego]) for ego in old_coverage)
    report["ego_item_coverage_transitions"] = [
        {"before": old_state, "after": new_state, "ego_count": count}
        for (old_state, new_state), count in sorted(coverage.items())]
    return report


def mauldin_source_report(path: str | Path) -> dict[str, object]:
    """Audit a bounded caller-supplied ZIP and disclose only aggregate evidence.

    Malformed source structure raises ValueError. A completed audit always
    remains NOT_ESTIMABLE: nomination eligibility, observation/composition
    policy and empirical model qualification are unresolved. Positive records
    survive other anomalies of the same ego; none are silently repaired into a
    usable network. Literal blank and NA item records are kept distinct.
    """
    raw, members = _source_members(path)
    reviewed = all(_hash(members[name]) == digest for name, digest in _REVIEWED_DOCUMENT_SHA256.items())
    tables = {}
    inventory = []
    for name, payload in sorted(members.items()):
        record = {"name": name, "bytes": len(payload), "sha256": _hash(payload)}
        if name.endswith(".csv"):
            retain = name == "ParticipationAcrossWaves.csv" or name in {item[0] for item in _NETWORKS}
            header, rows, table = _csv_table(payload, name, retain=retain)
            record["table"] = table
            if retain:
                tables[name] = (header, rows)
        inventory.append(record)
    header, rows = tables["ParticipationAcrossWaves.csv"]
    if header != ["PARTID", "Cohort", "w1_status", "w2_status", "w3_status", "w4_status"]:
        raise ValueError("Mauldin participation CSV has an unsupported header")
    roster_report, roster = _roster(rows)
    networks = {}
    for name, wave, relation in _NETWORKS:
        header, rows = tables[name]
        if header != ["PARTID", "Alter"]:
            raise ValueError("Mauldin network CSV has an unsupported header: " + name)
        networks[(relation, wave)] = _network(rows, name, wave, relation, roster, reviewed=reviewed)
    blockers = [{"code": "ELIGIBLE_ALTER_ROSTER_UNRESOLVED", "scope": "empirical_model",
                 "reason": "No verified per-ego eligible alter set; unlisted dyads remain unknown."},
                {"code": "OBSERVATION_AND_COMPOSITION_POLICY_UNQUALIFIED", "scope": "empirical_model",
                 "reason": "Survey nonresponse, item nonresponse, study consent and program enrollment are distinct."},
                {"code": "NO_QUALIFIED_LONGITUDINAL_BEHAVIOR", "scope": "coevolution_model",
                 "reason": "No behavior values are imported, completed, recoded or fitted."}]
    if not reviewed:
        blockers.append({"code": "UNREVIEWED_SOURCE_DOCUMENTATION", "scope": "source_interpretation"})
    if _hash(raw) != REFERENCE_ARCHIVE_SHA256:
        blockers.append({"code": "ARCHIVE_DIFFERS_FROM_OFFICIAL_REFERENCE", "scope": "source_identity"})
    if roster_report["raw_records"] != 145 or roster_report["unique_actors"] != 145:
        blockers.append({"code": "ROSTER_SIZE_DIFFERS_FROM_REVIEWED_SOURCE", "scope": "source_identity"})
    if roster_report["anomalies"]:
        blockers.append({"code": "ROSTER_ANOMALIES", "scope": "source_interpretation",
                         "counts": roster_report["anomalies"]})
    for report, _, _ in networks.values():
        if report["anomalies"]:
            blockers.append({"code": "NETWORK_SOURCE_ANOMALIES", "scope": "source_interpretation",
                             "file": report["file"], "counts": report["anomalies"]})
    profile = {
        "reviewed_documents_match": reviewed,
        "reference_review_date": "2026-11-27",
        "reviewed_document_sha256": dict(_REVIEWED_DOCUMENT_SHA256),
        "interpretation_applied": reviewed,
        "eligible_alter_roster_verified": False,
        "license_consistency_resolved": False,
        "external_metadata_retrieved_during_audit": False,
        "license_scope": "source reuse/redistribution provenance; not an estimator diagnostic or a legal determination",
    }
    if reviewed:
        profile.update({
            "blank_alter_meaning": "reported no alters for that item; no expansion into roster-wide absent dyads",
            "NA_alter_meaning": "survey or item nonresponse; not an absent tie",
            "status_meanings": {"-99": "not enrolled in study", "0": "did not participate in survey",
                                "1": "participated in survey; does not establish item response",
                                "10": "wave 4 only: not enrolled in MSW program; incoming nominations retained"},
            "scope_evidence": [
                {"source": "README.txt", "meaning": "W2-W4 roster described as all program students, including non-study students."},
                {"source": "Data Dictionary.pdf pages 22-23", "meaning": "Question wording refers to classmates in your cohort."},
                {"source": "https://doi.org/10.3390/educsci12030205", "meaning": "Published 2022 analysis of 70 full-time students does not define the 145-record archive boundary."},
            ],
            "license_declarations": [
                {"source": SOURCE_URL, "statement": "CC BY 4.0", "reviewed_at": "2026-11-27",
                 "basis": "recorded landing-page declaration, not a live check by this offline audit"},
                {"source": "README.txt", "statement": "CC BY-NC-ND 4.0"},
            ],
            "wave1_separate_relation": True,
            "wave2_behavior_not_collected": True,
            "wave4_separate_consent": True,
        })
    return {
        "kind": "MAULDIN_SOURCE_AUDIT", "status": "NOT_ESTIMABLE", "empirical_admitted": False,
        "source": {"landing_url": SOURCE_URL, "archive_bytes": len(raw), "archive_sha256": _hash(raw),
                   "official_reference_archive_sha256": REFERENCE_ARCHIVE_SHA256,
                   "matches_official_reference": _hash(raw) == REFERENCE_ARCHIVE_SHA256,
                   "reference_match_is_model_qualification": False, "members": inventory},
        "documentation_profile": profile, "roster": roster_report,
        "networks": [value[0] for value in networks.values()],
        "longitudinal_nominations": [
            _transition(networks[(relation, wave)], networks[(relation, wave + 1)])
            for _, relation in _RELATIONS for wave in (2, 3)
        ] if reviewed else [],
        "blockers": blockers, "person_records_disclosed": False,
        "characteristic_values_used": False, "raw_source_redistributed": False,
        "source_files_modified": False, "panel_created": False, "model_fitted": False,
        "causal_effect_identified": False,
        "meaning": "aggregate source audit and recorded nomination comparison; not complete networks, network change estimates or empirical admission",
    }
