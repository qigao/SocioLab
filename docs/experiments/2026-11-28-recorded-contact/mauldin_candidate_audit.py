"""Audit a retrospective 70-person Mauldin candidate without creating a panel.

The caller supplies the previously fingerprinted official ZIP. Only aggregate
counts, source hashes and explicit qualification limits are emitted. Participant
IDs, row-level observations, individual attributes and model inputs are not
exported. No source anomaly or paper/archive discrepancy is repaired.
"""

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile


ARCHIVE_BYTES = 853589
ARCHIVE_SHA256 = "d64a69e38401f2d1b81ae00f57dca670352a443c3a6332ddab4d01ff341d1c01"
SOURCE_URL = "https://mavmatrix.uta.edu/context/socialnetworksforsocialgood_datasets/article/1000/type/native/viewcontent"
PAPER_URL = "https://www.mdpi.com/2227-7102/12/3/205"


def audit(path):
    if path.stat().st_size != ARCHIVE_BYTES:
        raise ValueError("requires the previously reviewed official archive byte count")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("requires the previously reviewed official archive SHA-256")
    member_fingerprints = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        def member(name):
            matches = [info for info in archive.infolist()
                       if Path(info.filename).name == name and not info.is_dir()]
            if len(matches) != 1:
                raise ValueError("missing or ambiguous source member: " + name)
            data = archive.read(matches[0])
            member_fingerprints[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
            return data

        def table(name, fields):
            reader = csv.DictReader(io.StringIO(member(name).decode("utf-8-sig")))
            if reader.fieldnames != fields:
                raise ValueError("unexpected source columns: " + name)
            result = list(reader)
            if any(set(row) != set(fields) or any(value is None for value in row.values()) for row in result):
                raise ValueError("malformed source row: " + name)
            return result

        # These documentation bytes accompany the measurement interpretation;
        # their hashes do not independently resolve its eligibility questions.
        member("README.txt")
        member("Data Dictionary.pdf")
        people = table("ParticipationAcrossWaves.csv",
                       ["PARTID", "Cohort", "w1_status", "w2_status", "w3_status", "w4_status"])
        roster = {row["PARTID"]: row for row in people}
        if len(roster) != len(people) or len(roster) != 145:
            raise ValueError("unexpected source roster")
        fulltime = {actor for actor, row in roster.items() if row["Cohort"] in {"1", "2", "3"}}
        for actor in fulltime:
            enrolled_at_waves = [roster[actor][f"w{wave}_status"] != "-99" for wave in (1, 2, 3)]
            if len(set(enrolled_at_waves)) != 1:
                raise ValueError("initial study-enrollment indicators disagree")
        enrolled = {actor for actor in fulltime if roster[actor]["w1_status"] != "-99"}
        candidate = {actor for actor in enrolled if roster[actor]["w4_status"] != "10"}
        if [len(fulltime), len(enrolled), len(candidate)] != [74, 72, 70]:
            raise ValueError("candidate counts differ from this fingerprinted-source review")

        def relationship(wave, name):
            rows = table(f"w{wave}_{name}Edgelist.csv", ["PARTID", "Alter"])
            by_ego = defaultdict(list)
            for row in rows:
                if row["PARTID"] not in roster or not (row["Alter"].isdigit() or row["Alter"] in {"", "NA"}):
                    raise ValueError("unexpected nomination encoding")
                by_ego[row["PARTID"]].append(row["Alter"])
            categories = Counter()
            unknown, known = set(), set()
            for actor in candidate:
                values = by_ego[actor]
                if not values:
                    categories["omitted_ego"] += 1
                    unknown.add(actor)
                elif all(value == "NA" for value in values):
                    categories["unknown_na"] += 1
                    unknown.add(actor)
                elif all(value == "" for value in values):
                    categories["explicit_blank"] += 1
                    known.add(actor)
                elif all(value.isdigit() for value in values):
                    categories["recorded_nominations"] += 1
                    known.add(actor)
                else:
                    raise ValueError("mixed positive/blank/NA records for one ego")
            positive_rows = [(row["PARTID"], row["Alter"]) for row in rows
                             if row["PARTID"] in candidate and row["Alter"].isdigit()]
            internal_rows = [(ego, alter) for ego, alter in positive_rows
                             if ego != alter and alter in candidate]
            internal = set(internal_rows)
            same_cohort = sum(roster[ego]["Cohort"] == roster[alter]["Cohort"] for ego, alter in internal)
            self_egos = {ego for ego, alter in positive_rows if ego == alter}
            outside = [(ego, alter) for ego, alter in positive_rows if ego != alter and alter not in candidate]
            internal_egos = {ego for ego, _ in internal}
            return {
                "wave": wave, "relation": name.lower(),
                "survey_status_counts": dict(sorted(Counter(roster[a][f"w{wave}_status"] for a in candidate).items())),
                "item_coverage_counts": {key: categories[key] for key in
                                         ("recorded_nominations", "explicit_blank", "unknown_na", "omitted_ego")},
                "known_item_egos": len(known), "unknown_item_egos": len(unknown),
                "unknown_item_ego_survey_status_counts": dict(sorted(Counter(roster[a][f"w{wave}_status"] for a in unknown).items())),
                "within_candidate_nonself_recorded_nominations": len(internal),
                "duplicate_internal_positive_records": len(internal_rows) - len(internal),
                "same_cohort_recorded_nominations": same_cohort,
                "cross_cohort_recorded_nominations": len(internal) - same_cohort,
                "same_cohort_share_of_recorded_nominations": same_cohort / len(internal),
                "self_nomination_records": sum(ego == alter for ego, alter in positive_rows),
                "self_nomination_egos": len(self_egos),
                "self_nomination_egos_also_reporting_other_candidate_alters": len(self_egos & internal_egos),
                "outside_candidate_nonself_nomination_records": len(outside),
                "outside_candidate_but_fulltime_nomination_records": sum(alter in fulltime for _, alter in outside),
                "to_non_fulltime_roster_nomination_records": sum(alter in roster and alter not in fulltime for _, alter in outside),
                "outside_entire_roster_nomination_records": sum(alter not in roster for _, alter in outside),
                "known_item_egos_without_recorded_candidate_alter": len(known - internal_egos),
                "recorded_candidate_nominations_per_known_item_ego": len(internal) / len(known),
                "known_candidate_incoming_nominations_to_unknown_egos": sum(alter in unknown for _, alter in internal),
                "unknown_egos_with_known_candidate_incoming": len({alter for _, alter in internal if alter in unknown}),
                "count_scope": "recorded nonself nominations and source item coverage; no unlisted pair is asserted absent",
            }

        relationships = [relationship(wave, name) for wave in (2, 3, 4)
                         for name in ("Friendship", "Academic")]

    index = {(item["wave"], item["relation"]): item for item in relationships}
    friendship4 = index[(4, "friendship")]
    return {
        "kind": "MAULDIN_RETROSPECTIVE_CANDIDATE_AUDIT",
        "status": "NOT_ESTIMABLE",
        "archive": {"source_url": SOURCE_URL, "bytes": len(raw), "sha256": ARCHIVE_SHA256},
        "source_members": member_fingerprints,
        "audit_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "selection": {
            "source_roster_count": len(roster),
            "fulltime_cohorts": [1, 2, 3],
            "fulltime_count": len(fulltime),
            "fulltime_source_cohort_sizes": dict(sorted(Counter(roster[a]["Cohort"] for a in fulltime).items())),
            "initial_study_enrollment_rule": "w1_status != -99; agreement of enrollment indicators across waves 1, 2 and 3 is checked",
            "initial_study_enrolled_count": len(enrolled),
            "originally_not_enrolled_count": len(fulltime - enrolled),
            "retention_rule": "keep initially enrolled fulltime people with w4_status != 10; retain later status -99 (not enrolled in the study) without reclassification",
            "known_program_leavers_excluded_count": len(enrolled - candidate),
            "candidate_count": len(candidate),
            "candidate_source_cohort_sizes": dict(sorted(Counter(roster[a]["Cohort"] for a in candidate).items())),
            "wave4_survey_participants": sum(roster[a]["w4_status"] == "1" for a in candidate),
            "wave4_status_minus99_retained": sum(roster[a]["w4_status"] == "-99" for a in candidate),
            "retrospective_selection": True,
            "uses_wave4_membership_when_selecting_earlier_wave_population": True,
            "paper_analytic_roster_identity_verified": False,
            "forecast_baseline_population": False,
        },
        "relationships": relationships,
        "paper_comparison": {
            "url": PAPER_URL,
            "doi": "10.3390/educsci12030205",
            "sections": {
                "2.2": "Fulltime recruitment 74, enrolled 72, retained study sample 70; initial cohort sizes described as 24-26.",
                "2.5": "The selected 70 completed first-year surveys; 63 completed second-year surveys.",
                "2.6": "The reported friendship/academic roster comprises 2014-2016 fulltime students; separate no-tie and nonresponse choices; binary directed ties.",
                "2.7": "Nine of the 70 students did not report second-year friendship ties.",
                "3.2": "Five reported no friends; second-year mean 8.9 among reporters; same-cohort friendship share 78.3%; first-year friendship/academic shares 99.5%/99.2%.",
            },
            "candidate_population_counts_match_74_72_70": True,
            "candidate_wave4_survey_response_count_matches_63": True,
            "friendship_wave4_unknown_item_count": {"paper": 9, "archive_candidate": friendship4["unknown_item_egos"], "matches": friendship4["unknown_item_egos"] == 9},
            "friendship_wave4_no_friends_or_no_candidate_nominations": {
                "paper_reported_no_friends": 5,
                "archive_candidate_explicit_blank": friendship4["item_coverage_counts"]["explicit_blank"],
                "archive_candidate_known_item_without_candidate_alter": friendship4["known_item_egos_without_recorded_candidate_alter"],
                "matches": friendship4["item_coverage_counts"]["explicit_blank"] == 5
                and friendship4["known_item_egos_without_recorded_candidate_alter"] == 5,
            },
            "friendship_wave4_reporter_mean": {
                "paper": 8.9,
                "archive_candidate_recorded_nominations_per_known_item_ego": friendship4["recorded_candidate_nominations_per_known_item_ego"],
                "paper_inferred_known_item_ego_count_from_70_minus_9": 61,
                "archive_candidate_known_item_ego_count": friendship4["known_item_egos"],
                "not_a_replication": True,
            },
            "cohort_nomination_percentages": [
                {"wave": wave, "relation": relation, "paper_percent": expected,
                 "archive_candidate_percent": 100 * index[(wave, relation)]["same_cohort_share_of_recorded_nominations"],
                 "matches_after_one_decimal_rounding": round(100 * index[(wave, relation)]["same_cohort_share_of_recorded_nominations"], 1) == expected}
                for wave, relation, expected in ((3, "friendship", 99.5), (3, "academic", 99.2), (4, "friendship", 78.3))
            ],
            "paper_initial_cohort_size_range": [24, 26],
            "all_archive_fulltime_cohort_sizes_in_paper_range": all(24 <= count <= 26 for count in Counter(roster[a]["Cohort"] for a in fulltime).values()),
            "discrepancy_cause_established": False,
            "na_reclassified_to_match_paper": False,
        },
        "eligibility_evidence": {
            "official_catalogue": "https://mavmatrix.uta.edu/socialnetworksforsocialgood_datasets/2/",
            "readme_locations": ["METHODS: Sample", "METHODS: Description of methods used for collection/generation of data"],
            "dictionary_pages": [2, 22, 23],
            "readme_scope": "program-wide roster at waves 2-4, including non-study students",
            "dictionary_scope": "question wording refers to classmates in the respondent's cohort",
            "paper_scope": "2014-2016 fulltime students in the wave3/wave4 analysis",
            "cross_cohort_nominations_are_recorded": True,
            "non_fulltime_alters_are_recorded_from_candidate_egos": True,
            "source_eligibility_fully_established": False,
            "negative_observation_rule": "Unlisted dyads are not asserted absent in this audit. Such a mapping requires a declared eligible-alter domain and a justified complete item-response rule; NA/omitted ego rows remain unknown and retain incoming observations.",
        },
        "qualification": {
            "complete_graph_metrics_computed": False,
            "panel_created": False,
            "model_fitted": False,
            "source_eligibility_fully_established": False,
            "empirical_model_admitted": False,
            "causal_effect_identified": False,
            "row_level_data_exported": False,
            "individual_attributes_exported": False,
        },
        "interpretation": [
            "This explicitly selected retained-study candidate is not the original 145-person population and not an independently verified reproduction of the paper's analytic roster.",
            "Selecting wave1-3 observations using later wave4 departure information is retrospective; this population cannot be treated as known at a forecasting baseline.",
            "Wave4 friendship has ten source-NA egos, including three survey respondents, and four explicit blanks; the paper reports nine missing and five no-friend respondents. No source row is recoded to force agreement.",
            "Self-nominations are reported separately and excluded only from the explicitly nonself positive-record count. They are not silently corrected in the source or used to establish complete negative observations.",
            "Known incoming nominations to unknown outgoing egos remain counted. Record turnover, positive counts and coverage do not establish complete-network structure, relationship creation/dissolution or causal effects.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="local original UTA_Social_Networks_Social_Good.zip")
    args = parser.parse_args()
    try:
        result = audit(args.archive)
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
