"""Recurrence of rows in a fixed released email archive.

This source-specific retrospective study does not create EventDataset member or
coverage assertions. A zero label means no matching row in the supplied release,
not verified absence of real communication. Only baseline arithmetic is shared
with the complete-observation repeat-interaction profile.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import gzip
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import zlib

from .repeat_evaluation import _model_summary, _risk_change
from .repeat_interaction import (
    _MODELS, _probability_bin_models, _probability_bins, _probability_scores,
    _repeat_probabilities,
)
from .snapshots import content_hash


REFERENCE_GZIP_SHA256 = "b1f92288e855044bbc74bacac39d42b12e59ec2a0130ad8df419786eb46a7bff"
REFERENCE_PAYLOAD_SHA256 = "87f766b9e9547cb315c2fc1e49ed6eff2c60c121579b22d095079a401bbb3eb9"
REFERENCE_PROTOCOL_HASH = "sha256:d3f841be83127fdcaa4c6ca26129d845ac276c32e6e527b0324aa90c1e8da7e0"
PROTOCOL_FREEZE_COMMIT = "4c93277b7098d2e98e6a4d22874c8e0b9f976d5b"
_MAX_COMPRESSED_BYTES = 2_000_000
_MAX_DECOMPRESSED_BYTES = 8_000_000
_MAX_ROWS = 100_000
_MAX_NODES = 200
_MAX_PAIRS = 2000
_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,18})\Z")


@dataclass(frozen=True, slots=True)
class ReleasedEmailArchive:
    """Validated physical lines (line number, sender, recipient, relative second)."""

    rows: tuple[tuple[int, int, int, int], ...]
    compressed_sha256: str
    payload_sha256: str
    compressed_bytes: int
    payload_bytes: int


def load_email_eu_dept3_archive(path: str | Path) -> ReleasedEmailArchive:
    """Parse every ASCII three-integer line, preserving direction and repeats.

    File order need not follow source time and is never used as receipt order.
    Self-pairs remain in the parsed source and are excluded only by the declared
    prediction rule. Invalid or oversized input fails the whole read.
    """
    with Path(path).open("rb") as stream:
        raw = stream.read(_MAX_COMPRESSED_BYTES + 1)
    if not raw or len(raw) > _MAX_COMPRESSED_BYTES:
        raise ValueError("email gzip must be nonempty and within the compressed byte limit")
    try:
        with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
            payload = stream.read(_MAX_DECOMPRESSED_BYTES + 1)
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as error:
        raise ValueError("invalid email gzip stream") from error
    if not payload or len(payload) > _MAX_DECOMPRESSED_BYTES:
        raise ValueError("email payload must be nonempty and within the decompressed byte limit")
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("email archive requires ASCII integer fields") from error
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines or len(lines) > _MAX_ROWS:
        raise ValueError("email archive exceeds the row limit or contains no records")
    rows, actors, pairs = [], set(), set()
    for number, line in enumerate(lines, 1):
        fields = line.split()
        if len(fields) != 3 or any(_INTEGER.fullmatch(value) is None for value in fields):
            raise ValueError(f"email row {number} requires exactly three canonical nonnegative integers")
        source, target, when = map(int, fields)
        if max(source, target) > 2**31 - 1 or when > 2**63 - 1:
            raise ValueError(f"email row {number} is outside the ID or timestamp range")
        rows.append((number, source, target, when))
        actors.update((source, target))
        if source != target:
            pairs.add((source, target))
        if len(actors) > _MAX_NODES or len(pairs) > _MAX_PAIRS:
            raise ValueError("email archive exceeds the declared actor/pair budget")
    return ReleasedEmailArchive(tuple(rows), sha256(raw).hexdigest(), sha256(payload).hexdigest(),
                                len(raw), len(payload))


def _source_audit(archive: ReleasedEmailArchive) -> dict:
    rows = archive.rows
    triples = Counter(row[1:] for row in rows)
    times = Counter(row[3] for row in rows)
    return {
        "compressed_sha256": archive.compressed_sha256, "payload_sha256": archive.payload_sha256,
        "compressed_bytes": archive.compressed_bytes, "payload_bytes": archive.payload_bytes,
        "row_count": len(rows), "node_count": len({actor for row in rows for actor in row[1:3]}),
        "distinct_directed_pairs": len({row[1:3] for row in rows}),
        "distinct_nonself_pairs": len({row[1:3] for row in rows if row[1] != row[2]}),
        "self_pair_rows": sum(row[1] == row[2] for row in rows),
        "duplicate_triple_groups": sum(count > 1 for count in triples.values()),
        "duplicate_triple_additional_rows": sum(count - 1 for count in triples.values()),
        "timestamp_tie_groups": sum(count > 1 for count in times.values()),
        "timestamp_tie_additional_rows": sum(count - 1 for count in times.values()),
        "time_decreases_in_file_order": sum(a[3] > b[3] for a, b in zip(rows, rows[1:])),
        "minimum_relative_second": min(times), "maximum_relative_second": max(times),
        "all_rows_parsed": True, "duplicate_rows_dropped": 0,
        "original_line_numbers_retained": True, "file_order_used_as_receipt_order": False,
    }


def _archive_prediction(history_rows: tuple, *, origin: int, horizon: int, recent_width: int) -> dict:
    """Accept historical lines only; no full-archive hash or target enters here."""
    if any(type(value) is not int or value <= 0 for value in (origin, horizon, recent_width)):
        raise ValueError("archive window durations and origin must be positive integer seconds")
    if recent_width > origin:
        raise ValueError("recent window cannot start before the archive's fixed zero")
    if any(not 0 <= row[3] < origin for row in history_rows):
        raise ValueError("archive prediction accepts only rows strictly before its origin")
    nonself = [row for row in history_rows if row[1] != row[2]]
    counts = Counter(row[1:3] for row in nonself)
    recent = Counter(row[1:3] for row in nonself if row[3] >= origin - recent_width)
    if len(counts) > _MAX_PAIRS:
        raise ValueError("archive forecast exceeds the historical pair budget")
    predictions = [{
        "source": pair[0], "target": pair[1],
        "history_count": count, "recent_count": recent[pair],
        "probabilities": _repeat_probabilities(count, recent[pair], horizon, origin, recent_width),
    } for pair, count in sorted(counts.items())]
    result = {
        "schema": "sociolab.released-archive-prediction.v1",
        "origin_at_seconds": origin, "history_start_seconds": 0,
        "recent_start_seconds": origin - recent_width, "target_end_seconds": origin + horizon,
        "history_rows_hash": content_hash(history_rows),
        "history_row_count": len(history_rows), "history_nonself_row_count": len(nonself),
        "recent_nonself_row_count": sum(recent.values()),
        "history_actor_count": len({actor for row in nonself for actor in row[1:3]}),
        "predictions": predictions,
        "scope": {"contains_private_actor_records": True,
                  "target": "matching_released_archive_row", "source_time_history_only": True,
                  "real_receipt_history_reconstructed": False, "prospective_issuance_verified": False},
    }
    result["content_hash"] = content_hash(result)
    return result


def _archive_fold(prediction: dict, target_rows: tuple, edges: list[float]) -> tuple[dict, dict, set]:
    """Label a frozen historical risk set with rows from its exact target window."""
    origin, end = prediction["origin_at_seconds"], prediction["target_end_seconds"]
    if any(not origin <= row[3] < end for row in target_rows):
        raise ValueError("archive target rows must lie inside the exact half-open target window")
    target_pairs = {row[1:3] for row in target_rows if row[1] != row[2]}
    risk = {(row["source"], row["target"]) for row in prediction["predictions"]}
    scored = [(row, int((row["source"], row["target"]) in target_pairs)) for row in prediction["predictions"]]
    models = _probability_scores(scored)
    diagnostics = _probability_bin_models(scored, edges)
    positives = len(risk & target_pairs)
    report = {key: deepcopy(prediction[key]) for key in (
        "origin_at_seconds", "recent_start_seconds", "target_end_seconds", "history_rows_hash",
        "history_row_count", "history_nonself_row_count", "recent_nonself_row_count", "history_actor_count")}
    report.update({
        "status": "ARCHIVE_LABELS_SCORED" if risk else "EMPTY_RISK_SET",
        "forecast_hash": prediction["content_hash"], "target_rows_hash": content_hash(target_rows),
        "target_row_count": len(target_rows),
        "target_nonself_row_count": sum(row[1] != row[2] for row in target_rows),
        "risk_pairs": len(risk), "archive_positive_pairs": positives,
        "archive_negative_pairs": len(risk) - positives,
        "target_positive_pairs_outside_risk": len(target_pairs - risk),
        "models": models, "probability_diagnostics": diagnostics,
        "always_zero_brier": positives / len(risk) if risk else None,
    })
    # Neutral internal arithmetic structure, deliberately not a strict R1 score.
    return report, {"score": {"models": models}, "models": diagnostics}, risk


def email_eu_dept3_case_report(path: str | Path, protocol: dict) -> dict:
    """Run only the reviewed source and pre-acquisition frozen study protocol.

    Recompression is allowed if the decompressed payload is identical; both
    identities are reported. Different data or a changed analysis plan require
    a separately reviewed study rather than automatic retuning of this case.
    """
    if content_hash(protocol) != REFERENCE_PROTOCOL_HASH:
        raise ValueError("Dept3 study requires the frozen pre-acquisition protocol")
    archive = load_email_eu_dept3_archive(path)
    if archive.payload_sha256 != REFERENCE_PAYLOAD_SHA256:
        raise ValueError("Dept3 study requires the reviewed released payload fingerprint")
    audit = _source_audit(archive)
    admission = protocol["admission"]
    if audit["row_count"] != admission["required_rows"] or audit["node_count"] != admission["required_nodes"]:
        raise ValueError("Dept3 archive does not match the predeclared row/node counts")
    if audit["maximum_relative_second"] < admission["minimum_archive_max_time"]:
        raise ValueError("Dept3 archive does not reach the predeclared artifact extent")
    measurement = protocol["measurement"]
    edges = _probability_bins(protocol["analysis"]["probability_bins"])
    reports, diagnostics, previous_risk = [], [], None
    for index, origin in enumerate(measurement["origins"]):
        history_rows = tuple(row for row in archive.rows if row[3] < origin)
        prediction = _archive_prediction(history_rows, origin=origin, horizon=measurement["horizon"],
                                         recent_width=measurement["recent_width"])
        # Construct targets only after historical probabilities have been frozen.
        target_rows = tuple(row for row in archive.rows if origin <= row[3] < origin + measurement["horizon"])
        report, diagnostic, risk = _archive_fold(prediction, target_rows, edges)
        report.update(index=index, risk_change=_risk_change(risk, previous_risk))
        reports.append(report)
        diagnostics.append(diagnostic)
        previous_risk = risk
    n = sum(report["risk_pairs"] for report in reports)
    positives = sum(report["archive_positive_pairs"] for report in reports)
    models = {model: _model_summary(diagnostics, model, len(reports), edges) for model in _MODELS}
    reference = positives / n if n else None
    result = {
        "schema": "sociolab.released-archive-recurrence-study.v1",
        "kind": "RELEASED_ARCHIVE_RECURRENCE_STUDY",
        "profile": "email-eu-dept3-released-record-recurrence-v1", "study_id": protocol["study_id"],
        "protocol_hash": content_hash(protocol), "protocol_freeze_commit": PROTOCOL_FREEZE_COMMIT,
        "source": {**deepcopy(protocol["source"]), **audit,
                   "reviewed_payload_matches": True,
                   "reviewed_compressed_bytes_match": archive.compressed_sha256 == REFERENCE_GZIP_SHA256,
                   "attribution": "Ashwin Paranjape, Austin R. Benson and Jure Leskovec, Motifs in Temporal Networks, WSDM 2017, 601-610."},
        "measurement": deepcopy(measurement),
        "admission": {"status": "ADMITTED_FOR_RELEASED_ARCHIVE_RECURRENCE",
                      "strict_complete_observation_r1_status": "NOT_ADMITTED",
                      "artifact_extent_check_is_real_followup_closure": False},
        "counts": {"planned_origins": len(reports),
                   "scored_origins": sum(report["risk_pairs"] > 0 for report in reports),
                   "risk_pair_origin_count": n, "scored_pair_origin_count": n,
                   "archive_positive_pair_origin_count": positives,
                   "archive_negative_pair_origin_count": n - positives},
        "folds": reports, "probability_bins": edges, "models": models,
        "reference": {"always_zero_brier": reference,
                      "model_brier_minus_always_zero": {
                          model: models[model]["pooled_brier"] - reference if n else None for model in _MODELS}},
        "scope": {**deepcopy(protocol["scope"]),
                  "released_record_temporal_holdout_executed": True,
                  "real_communication_forecast_validated": False,
                  "source_membership_or_coverage_assertions_created": False,
                  "all_models_use_same_archive_labels": True,
                  "contains_private_actor_records": False,
                  "sample_unit": "ordered_pair_origin_not_independent_relationship",
                  "target_information_used_to_refit": False,
                  "confidence_intervals": False, "dependent_pairs_treated_as_iid": False},
    }
    result["content_hash"] = content_hash(result)
    return result
