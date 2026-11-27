"""Aggregate audit of the exact downloaded Mauldin archive; emit no actor IDs.

Run: python independent_audit.py /path/to/source.zip > independent_audit.json
This is an audit convention over the published roster, not an admitted model
or a corrected/released version of the source data. Raw source is unchanged.
"""

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
from zipfile import ZipFile


SOURCE_SHA256 = "d64a69e38401f2d1b81ae00f57dca670352a443c3a6332ddab4d01ff341d1c01"


def records(archive, name, header):
    reader = csv.DictReader(StringIO(archive.read(name).decode("utf-8-sig")))
    if reader.fieldnames != header:
        raise ValueError("unexpected source header in " + name)
    return list(reader)


def audit_archive(raw: bytes) -> dict:
    """Audit one verified byte buffer, without exposing any individual records."""
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("archive differs from the verified source; audit is version-specific")
    with ZipFile(BytesIO(raw)) as archive:
        people = records(archive, "ParticipationAcrossWaves.csv",
                         ["PARTID", "Cohort", "w1_status", "w2_status", "w3_status", "w4_status"])
        roster = {row["PARTID"] for row in people}
        if len(roster) != len(people) or len(roster) != 145:
            raise ValueError("unexpected published roster")
        status = {w: {row["PARTID"]: row[f"w{w}_status"] for row in people} for w in range(1, 5)}
        cohort = {row["PARTID"]: row["Cohort"] for row in people}
        file_audit = []
        states = {}
        for name in sorted(archive.namelist()):
            if re.fullmatch(r"w[1-4]_.+Edgelist\.csv", name) is None:
                continue
            wave = int(name[1])
            rows = records(archive, name, ["PARTID", "Alter"])
            by_ego = defaultdict(list)
            for row in rows:
                if row["PARTID"] not in roster:
                    raise ValueError("unrecognized ego in " + name)
                by_ego[row["PARTID"]].append(row["Alter"])

            def category(value):
                if value == "":
                    return "empty"
                if value == "NA":
                    return "NA"
                if re.fullmatch(r"\d{4}", value):
                    return "ID"
                raise ValueError("unsupported Alter encoding in " + name)

            kinds = {ego: Counter(category(value) for value in alters)
                     for ego, alters in by_ego.items()}
            mixed = [ego for ego, classes in kinds.items() if len(classes) != 1]
            na_egos = {ego for ego, classes in kinds.items() if "NA" in classes}
            omitted = roster - set(by_ego)
            nomination_rows = [(row["PARTID"], row["Alter"])
                               for row in rows if category(row["Alter"]) == "ID"]
            self_rows = [(ego, alter) for ego, alter in nomination_rows if ego == alter]
            outside_rows = [(ego, alter) for ego, alter in nomination_rows if alter not in roster]
            legal_ties = {(ego, alter) for ego, alter in nomination_rows if ego != alter and alter in roster}
            incoming = Counter(alter for _, alter in legal_ties)

            def incoming_summary(actors):
                return {
                    "ego_count": len(actors),
                    "egos_with_known_incoming": sum(actor in incoming for actor in actors),
                    "known_incoming_ties": sum(incoming[actor] for actor in actors),
                    "outgoing_record_shapes": dict(sorted(Counter(
                        "+".join(sorted(kinds[actor])) if actor in kinds else "omitted"
                        for actor in actors
                    ).items())),
                }

            source_status = {
                code: incoming_summary({actor for actor, value in status[wave].items() if value == code})
                for code in ("0", "-99", "10") if code in status[wave].values()
            }
            file_audit.append({
                "file": name,
                "source_member_sha256": sha256(archive.read(name)).hexdigest(),
                "raw_data_rows": len(rows),
                "raw_nomination_rows": len(nomination_rows),
                "NA_rows": sum(classes["NA"] for classes in kinds.values()),
                "empty_rows": sum(classes["empty"] for classes in kinds.values()),
                "ego_record_shapes": dict(sorted(Counter("+".join(sorted(classes)) for classes in kinds.values()).items())),
                "mixed_record_egos": len(mixed),
                "repeated_NA_placeholder_egos": sum(classes["NA"] > 1 for classes in kinds.values()),
                "repeated_empty_placeholder_egos": sum(classes["empty"] > 1 for classes in kinds.values()),
                "duplicate_nomination_rows": len(nomination_rows) - len(set(nomination_rows)),
                "self_nomination_rows": len(self_rows),
                "out_of_roster_alter_rows": len(outside_rows),
                "out_of_roster_alter_count": len({alter for _, alter in outside_rows}),
                "legal_known_ties_within_published_roster": len(legal_ties),
                "cross_cohort_legal_ties": sum(cohort[ego] != cohort[alter] for ego, alter in legal_ties),
                "NA_egos_by_participation_status": dict(sorted(Counter(status[wave][ego] for ego in na_egos).items())),
                "omitted_egos_by_participation_status": dict(sorted(Counter(status[wave][ego] for ego in omitted).items())),
                "relation_NA_egos": incoming_summary(na_egos),
                "relation_omitted_egos": incoming_summary(omitted),
                "survey_or_enrollment_status": source_status,
            })
            if "_Friendship" in name:
                if mixed or outside_rows or any(classes["NA"] > 1 or classes["empty"] > 1 for classes in kinds.values()):
                    raise ValueError("ambiguous source prevents friendship reference counts")
                # U = relation response unknown; P = recorded positive nomination;
                # N = unlisted in a supplied ID-only or explicit-empty ego record.
                # N does NOT establish dyadic absence without eligible-alter scope.
                # Self-nominations are counted above, excluded from legal dyads.
                unknown_egos = na_egos | omitted
                states[wave] = {
                    (ego, alter): "U" if ego in unknown_egos else "P" if (ego, alter) in legal_ties else "N"
                    for ego in roster for alter in roster if ego != alter
                }

    friendship_waves = []
    for wave in (2, 3, 4):
        counts = Counter(states[wave].values())
        friendship_waves.append({
            "wave": wave, "recorded_nomination": counts["P"], "unlisted_in_supplied_ego_record": counts["N"],
            "relation_response_unknown": counts["U"], "total_legal_directed_dyads": sum(counts.values()),
        })

    friendship_transitions = []
    for before, after in ((2, 3), (3, 4)):
        counts = Counter(states[before][dyad] + "->" + states[after][dyad] for dyad in states[before])
        labels = {"N": "unlisted", "P": "recorded", "U": "unknown"}
        table = {f"{labels[left]}->{labels[right]}": counts[f"{left}->{right}"]
                 for left in ("N", "P", "U") for right in ("N", "P", "U")}
        friendship_transitions.append({
            "before_wave": before, "after_wave": after,
            "counts": table,
            "retained_recorded_nominations": counts["P->P"],
            "newly_recorded_nominations": counts["N->P"] + counts["U->P"],
            "no_longer_recorded_nominations": counts["P->N"] + counts["P->U"],
            "unknown_to_supplied_ego_record": counts["U->N"] + counts["U->P"],
            "supplied_ego_record_to_unknown": counts["N->U"] + counts["P->U"],
            "both_waves_have_supplied_ego_records": sum(counts[f"{left}->{right}"] for left in ("N", "P") for right in ("N", "P")),
            "total_legal_directed_dyads": sum(counts.values()),
        })

    return {
        "source_archive_sha256": SOURCE_SHA256,
        "actor_count": len(roster), "legal_directed_dyad_count": len(roster) * (len(roster) - 1),
        "conventions": {
            "direction": "PARTID nominator to Alter nominee",
            "roster": "all 145 IDs in ParticipationAcrossWaves.csv, unchanged between waves",
            "diagonal": "excluded from legal directed dyads; raw self-nominations separately counted",
            "NA": "unknown outgoing row for this relation, even when overall survey status is 1",
            "empty_Alter": "explicitly reported no alters for this relation",
            "omitted_ego": "unknown outgoing row, never an observed zero",
            "positive_rows": "named alters are recorded nominations; unlisted alters are not confirmed absent without eligible-alter scope",
            "incoming": "retained independently of the target actor's response/enrollment status",
            "membership": "no actor dropped based on survey or program-enrollment status",
            "coverage_caveat": "README's full-program roster wording differs from dictionary's in-your-cohort wording and related paper's full-time subset; do not infer confirmed additions/removals",
            "qualification": "aggregate source audit only, not model admission or a corrected dataset",
        },
        "files": file_audit,
        "friendship_waves": friendship_waves,
        "recorded_nomination_turnover": friendship_transitions,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="original Mauldin ZIP with the verified source SHA256")
    args = parser.parse_args(argv)
    try:
        result = audit_archive(args.archive.read_bytes())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
