"""Compare the CLI report with the independent exact-source audit aggregates.

Run: python verify_audit.py source-audit.json independent-audit.json
The independent script reads the original archive; this comparison imports no
SocioLab implementation and does not turn record counts into model admission.
"""

import argparse
import json
from pathlib import Path


def verify(report: dict, reference: dict) -> dict:
    checks = 0

    def same(actual, expected, label):
        nonlocal checks
        if actual != expected:
            raise ValueError("audit disagreement: " + label)
        checks += 1

    same(report["kind"], "MAULDIN_SOURCE_AUDIT", "result kind")
    same(report["status"], "NOT_ESTIMABLE", "admission status")
    same(report["empirical_admitted"], False, "empirical admission")
    same(report["panel_created"], False, "panel creation")
    same(report["model_fitted"], False, "model fitting")
    same(report["source"]["archive_sha256"], reference["source_archive_sha256"], "source bytes")
    same(report["source"]["matches_official_reference"], True, "reference fingerprint")
    same(report["documentation_profile"]["reviewed_documents_match"], True, "reviewed documentation")
    same(report["roster"]["unique_actors"], reference["actor_count"], "roster count")
    supplied = {item["file"]: item for item in report["networks"]}
    original = {item["file"]: item for item in reference["files"]}
    same(set(supplied), set(original), "all ten source relationship files")
    for name, actual in supplied.items():
        expected = original[name]
        same(actual["raw_records"], expected["raw_data_rows"], name + " row count")
        for actual_key, expected_key in (
            ("target_id_records", "raw_nomination_rows"),
            ("na_alter_records", "NA_rows"),
            ("blank_alter_records", "empty_rows"),
        ):
            same(actual["row_counts"][actual_key], expected[expected_key], name + " " + actual_key)
        same(actual["unique_recorded_positive_nominations"],
             expected["legal_known_ties_within_published_roster"], name + " recorded nominations")
        for actual_key, expected_key in (
            ("self_nomination_records", "self_nomination_rows"),
            ("out_of_roster_alter_records", "out_of_roster_alter_rows"),
            ("duplicate_positive_records", "duplicate_nomination_rows"),
        ):
            same(actual["anomalies"].get(actual_key, 0), expected[expected_key], name + " " + actual_key)
        same(actual["item_coverage"]["unknown_na"], expected["relation_NA_egos"]["ego_count"], name + " NA coverage")
        same(actual["item_coverage"]["missing_ego_record"], expected["relation_omitted_egos"]["ego_count"], name + " omitted coverage")
        for code, summary in expected["survey_or_enrollment_status"].items():
            same(actual["incoming_positive_nominations_by_alter_status"].get(code, 0),
                 summary["known_incoming_ties"], name + " incoming by status " + code)
        same(actual["confirmed_absent_dyads"], 0, name + " inferred absence")
        same(actual["unlisted_dyads_expanded_to_zero"], False, name + " zero expansion")
    transitions = {(item["before_wave"], item["after_wave"]): item
                   for item in report["longitudinal_nominations"] if item["relation"] == "friendship"}
    same(set(transitions), {(2, 3), (3, 4)}, "friendship wave pairs")
    unknown = {"unknown_na", "missing_ego_record"}
    for expected in reference["recorded_nomination_turnover"]:
        pair = (expected["before_wave"], expected["after_wave"])
        actual = transitions[pair]
        for key, expected_key in (("persistent", "retained_recorded_nominations"),
                                  ("first_recorded", "newly_recorded_nominations"),
                                  ("no_longer_recorded", "no_longer_recorded_nominations")):
            same(actual[key]["count"], expected[expected_key], str(pair) + " " + key)
            same(sum(row["count"] for row in actual[key]["ego_item_coverage"]),
                 actual[key]["count"], str(pair) + " disjoint nomination strata")
        for key, side, oracle_key in (("first_recorded", "before", "unknown->recorded"),
                                      ("no_longer_recorded", "after", "recorded->unknown")):
            same(sum(row["count"] for row in actual[key]["ego_item_coverage"] if row[side] in unknown),
                 expected["counts"][oracle_key], str(pair) + " " + oracle_key)
        same(sum(row["ego_count"] for row in actual["ego_item_coverage_transitions"]),
             reference["actor_count"], str(pair) + " roster preserved")
        same(actual["tie_creation_or_dissolution_inferred"], False, str(pair) + " inferred change")
    return {"verified": True, "comparison_checks": checks,
            "source_archive_sha256": reference["source_archive_sha256"],
            "network_files_compared": len(supplied), "friendship_transitions_compared": len(transitions),
            "empirical_model_qualified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(json.loads(args.report.read_text()), json.loads(args.reference.read_text()))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
