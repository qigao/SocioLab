"""Real ZIP/CSV boundary tests with explicitly synthetic, anonymous inputs."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import csv
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_BZIP2, ZIP_DEFLATED

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab import mauldin
from sociolab.cli import main


ACTORS = tuple(str(1000 + index) for index in range(145))
NETWORK_FILES = ("w1_KnowofEdgelist.csv",) + tuple(
    f"w{wave}_{relation}Edgelist.csv"
    for wave in (2, 3, 4) for relation in ("Academic", "Friendship", "Professional")
)
SYNTHETIC_DOCUMENTS = {
    "README.txt": b"Synthetic source-format fixture. This is not the official dataset or documentation.",
    "Data Dictionary.pdf": b"Synthetic dictionary fingerprint fixture; not a document reviewed for research.",
}


def csv_bytes(header, rows):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def source_members():
    """Small-format fixture retaining all 145 artificial roster identities."""
    members = {**SYNTHETIC_DOCUMENTS, "MANIFEST.TXT": b"Synthetic test archive\n"}
    members["ParticipationAcrossWaves.csv"] = csv_bytes(
        ["PARTID", "Cohort", "w1_status", "w2_status", "w3_status", "w4_status"],
        [[actor, "1", "1", "1", "1", "10" if actor == ACTORS[3] else "1"] for actor in ACTORS],
    )
    for name in NETWORK_FILES:
        members[name] = csv_bytes(["PARTID", "Alter"], [[actor, "NA"] for actor in ACTORS])
    for wave in (1, 3, 4):
        members[f"w{wave}_Characteristics.csv"] = csv_bytes(
            ["PARTID", "PRIVATE_MEASUREMENT"], [[actor, "DO_NOT_DISCLOSE_ATTRIBUTE"] for actor in ACTORS])
    members["SharedCourseAffiliationMatrix.csv"] = csv_bytes(
        ["", ACTORS[0], ACTORS[1]], [[ACTORS[0], 0, 1], [ACTORS[1], 1, 0]])
    members["SharedCourseValuedEdgelist.csv"] = csv_bytes(
        ["PARTID", "Alter", "Degree"], [[ACTORS[0], ACTORS[1], 1]])
    return members


def set_network(members, name, overrides, extra=()):
    rows = [[ego, alter] for ego in ACTORS for alter in overrides.get(ego, ["NA"])]
    members[name] = csv_bytes(["PARTID", "Alter"], [*rows, *extra])


def write_source(path, members=None, *, compression=ZIP_DEFLATED):
    with ZipFile(path, "w", compression=compression) as archive:
        for name, raw in (source_members() if members is None else members).items():
            archive.writestr(name, raw)
    return Path(path)


@contextmanager
def reviewed_synthetic_documents():
    """Only exercises the reviewed-profile branch; does not certify a fixture."""
    hashes = {name: sha256(raw).hexdigest() for name, raw in SYNTHETIC_DOCUMENTS.items()}
    with patch.object(mauldin, "_REVIEWED_DOCUMENT_SHA256", hashes):
        yield


class MauldinSourceTests(unittest.TestCase):
    def report(self, members=None, *, reviewed=True):
        with tempfile.TemporaryDirectory() as folder:
            path = write_source(Path(folder) / "source.zip", members)
            if reviewed:
                with reviewed_synthetic_documents():
                    return mauldin.mauldin_source_report(path)
            return mauldin.mauldin_source_report(path)

    def network(self, report, wave, relation="friendship"):
        return next(row for row in report["networks"] if row["wave"] == wave and row["relation"] == relation)

    def test_cli_completed_audit_returns_json_without_claiming_model_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_source(Path(folder) / "source.zip")
            output = StringIO()
            with reviewed_synthetic_documents(), redirect_stdout(output):
                code = main(["source", "mauldin", "inspect", str(path)])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["kind"], "MAULDIN_SOURCE_AUDIT")
        self.assertEqual(report["status"], "NOT_ESTIMABLE")
        self.assertFalse(report["empirical_admitted"])
        self.assertFalse(report["source"]["matches_official_reference"])
        self.assertEqual(len(report["networks"]), 10)

    def test_cli_malformed_archive_exits_two_with_no_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.zip"
            path.write_bytes(b"not the Mauldin archive")
            output, errors = StringIO(), StringIO()
            with redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                main(["source", "mauldin", "inspect", str(path)])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("readable supported ZIP", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_roster_status_and_item_nonresponse_are_distinct_without_disclosure(self):
        members = source_members()
        set_network(members, "w4_FriendshipEdgelist.csv", {ACTORS[0]: [ACTORS[3]]})
        report = self.report(members)
        self.assertEqual(report["roster"]["raw_records"], 145)
        self.assertEqual(report["roster"]["unique_actors"], 145)
        self.assertFalse(report["roster"]["roster_filter_applied"])
        self.assertEqual(report["roster"]["per_wave_status_counts"]["4"], {"1": 144, "10": 1})
        network = self.network(report, 4)
        self.assertEqual(network["incoming_positive_nominations_by_alter_status"], {"10": 1})
        self.assertEqual(network["item_coverage"]["unknown_na"], 144)
        self.assertIn({"status_code": "1", "item_coverage": "unknown_na", "ego_count": 143},
                      network["status_by_item_coverage"])
        self.assertEqual(len(report["source"]["members"]), 19)
        text = json.dumps(report, allow_nan=False)
        self.assertNotIn("DO_NOT_DISCLOSE_ATTRIBUTE", text)
        self.assertNotIn("PRIVATE_MEASUREMENT", text)
        for actor in ACTORS:
            self.assertNotIn('"' + actor + '"', text)
        self.assertFalse(report["characteristic_values_used"])
        self.assertFalse(report["panel_created"])
        self.assertFalse(report["model_fitted"])

    def test_recorded_nomination_turnover_partitions_do_not_create_absent_dyads(self):
        a, b, c = ACTORS[:3]
        members = source_members()
        set_network(members, "w2_FriendshipEdgelist.csv", {a: [b], b: [""]})
        set_network(members, "w3_FriendshipEdgelist.csv", {b: [c], c: [a]})
        set_network(members, "w4_FriendshipEdgelist.csv", {a: [b], b: [c], c: [""]})
        report = self.report(members)
        transitions = [row for row in report["longitudinal_nominations"] if row["relation"] == "friendship"]
        self.assertEqual(len(report["longitudinal_nominations"]), 6)
        self.assertEqual([(row["before_wave"], row["after_wave"]) for row in transitions], [(2, 3), (3, 4)])
        first = transitions[0]
        self.assertEqual([first[name]["count"] for name in ("persistent", "first_recorded", "no_longer_recorded")], [0, 2, 1])
        self.assertIn({"before": "reported_no_alters", "after": "recorded_nominations", "count": 1},
                      first["first_recorded"]["ego_item_coverage"])
        self.assertIn({"before": "unknown_na", "after": "recorded_nominations", "count": 1},
                      first["first_recorded"]["ego_item_coverage"])
        self.assertEqual(first["no_longer_recorded"]["ego_item_coverage"],
                         [{"before": "recorded_nominations", "after": "unknown_na", "count": 1}])
        self.assertEqual([transitions[1][name]["count"] for name in ("persistent", "first_recorded", "no_longer_recorded")], [1, 1, 1])
        for transition in report["longitudinal_nominations"]:
            self.assertFalse(transition["tie_creation_or_dissolution_inferred"])
            self.assertEqual(sum(row["ego_count"] for row in transition["ego_item_coverage_transitions"]), 145)
            self.assertEqual(sum(transition[key]["count"] for key in ("persistent", "first_recorded", "no_longer_recorded")),
                             transition["positive_nomination_union_count"])
            for key in ("persistent", "first_recorded", "no_longer_recorded"):
                self.assertEqual(sum(row["count"] for row in transition[key]["ego_item_coverage"]), transition[key]["count"])
        self.assertTrue(all(row["confirmed_absent_dyads"] == 0 for row in report["networks"]))
        self.assertFalse(any(row["unlisted_dyads_expanded_to_zero"] for row in report["networks"]))

    def test_direction_is_preserved(self):
        a, b = ACTORS[:2]
        members = source_members()
        set_network(members, "w2_FriendshipEdgelist.csv", {a: [b]})
        set_network(members, "w3_FriendshipEdgelist.csv", {b: [a]})
        report = self.report(members)
        transition = next(row for row in report["longitudinal_nominations"] if row["relation"] == "friendship" and row["before_wave"] == 2)
        self.assertEqual([transition[name]["count"] for name in ("persistent", "first_recorded", "no_longer_recorded")], [0, 1, 1])

    def test_anomalies_do_not_erase_other_positive_records_or_repair_missing_egos(self):
        a, b, c, d, e = ACTORS[:5]
        members = source_members()
        set_network(members, "w2_FriendshipEdgelist.csv", {
            a: [a, b, b, "9999"], b: [], c: ["", "NA", a], d: ["", ""], e: ["unsupported"],
        }, extra=(("9998", a),))
        network = self.network(self.report(members), 2)
        self.assertEqual(network["unique_recorded_positive_nominations"], 2)
        expected = {"self_nomination_records": 1, "out_of_roster_alter_records": 1,
                    "out_of_roster_ego_records": 1, "duplicate_positive_records": 1,
                    "missing_ego_record_egos": 1, "ambiguous_item_encoding_egos": 3,
                    "duplicate_placeholder_records": 1, "unsupported_alter_records": 1}
        self.assertEqual(network["anomalies"], expected)
        self.assertEqual(network["item_coverage"]["missing_ego_record"], 1)
        self.assertEqual(network["confirmed_absent_dyads"], 0)

    def test_unreviewed_documents_do_not_gain_interpretation_or_license_verification(self):
        members = source_members()
        set_network(members, "w4_FriendshipEdgelist.csv", {ACTORS[3]: [ACTORS[0]]})
        members["README.txt"] += b" altered"
        report = self.report(members)
        self.assertFalse(report["documentation_profile"]["reviewed_documents_match"])
        self.assertFalse(report["documentation_profile"]["interpretation_applied"])
        self.assertFalse(report["documentation_profile"]["license_consistency_resolved"])
        self.assertNotIn("license_declarations", report["documentation_profile"])
        self.assertEqual(report["longitudinal_nominations"], [])
        network = self.network(report, 4)
        self.assertIsNone(network["unique_recorded_positive_nominations"])
        self.assertIsNone(network["item_coverage"])
        self.assertEqual(network["unique_in_roster_offdiagonal_id_pairs"], 1)
        self.assertNotIn("answered_item_with_nonparticipant_or_ambiguous_status_egos", network["anomalies"])
        self.assertIn("UNREVIEWED_SOURCE_DOCUMENTATION", {row["code"] for row in report["blockers"]})

    def test_even_matching_source_fingerprints_do_not_admit_empirical_model(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_source(Path(folder) / "source.zip")
            digest = sha256(path.read_bytes()).hexdigest()
            with reviewed_synthetic_documents(), patch.object(mauldin, "REFERENCE_ARCHIVE_SHA256", digest):
                report = mauldin.mauldin_source_report(path)
        self.assertTrue(report["source"]["matches_official_reference"])
        self.assertTrue(report["documentation_profile"]["reviewed_documents_match"])
        self.assertFalse(report["source"]["reference_match_is_model_qualification"])
        self.assertEqual(report["status"], "NOT_ESTIMABLE")
        self.assertFalse(report["empirical_admitted"])
        self.assertFalse(report["documentation_profile"]["license_consistency_resolved"])
        self.assertFalse(report["documentation_profile"]["external_metadata_retrieved_during_audit"])
        self.assertEqual({row["statement"] for row in report["documentation_profile"]["license_declarations"]},
                         {"CC BY 4.0", "CC BY-NC-ND 4.0"})
        self.assertIn("ELIGIBLE_ALTER_ROSTER_UNRESOLVED", {row["code"] for row in report["blockers"]})

    def test_missing_or_duplicate_roster_records_are_reported_without_truncating(self):
        members = source_members()
        table = list(csv.reader(StringIO(members["ParticipationAcrossWaves.csv"].decode())))
        table.append(table[1])
        members["ParticipationAcrossWaves.csv"] = csv_bytes(table[0], table[1:])
        report = self.report(members)
        self.assertEqual(report["roster"]["raw_records"], 146)
        self.assertEqual(report["roster"]["unique_actors"], 145)
        self.assertEqual(report["roster"]["anomalies"]["duplicate_identity_records"], 1)
        self.assertIn("ROSTER_SIZE_DIFFERS_FROM_REVIEWED_SOURCE", {row["code"] for row in report["blockers"]})

    def test_unsafe_duplicate_and_missing_members_are_rejected(self):
        for unsafe in ("../README.txt", "/README.txt", "folder\\README.txt"):
            with self.subTest(path=unsafe):
                members = source_members()
                members[unsafe] = members.pop("README.txt")
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    self.report(members)
        members = source_members()
        members["nested/README.txt"] = members["README.txt"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.report(members)
        members = source_members()
        del members["w2_FriendshipEdgelist.csv"]
        with self.assertRaisesRegex(ValueError, "lacks required"):
            self.report(members)

    def test_archive_member_total_and_member_count_limits_use_real_bounded_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_source(Path(folder) / "source.zip")
            cases = (("_MAX_ARCHIVE_BYTES", path.stat().st_size - 1),
                     ("_MAX_MEMBER_BYTES", 1), ("_MAX_TOTAL_BYTES", 1), ("_MAX_MEMBERS", 18))
            for field, limit in cases:
                with self.subTest(field=field), patch.object(mauldin, field, limit):
                    with self.assertRaisesRegex(ValueError, "limit"):
                        mauldin.mauldin_source_report(path)

    def test_malformed_csv_zip_and_unsupported_compression_fail_as_value_errors(self):
        for raw in (b"PARTID,Alter\n1000,1001,extra\n", b"PARTID,Alter\n1000,\xff\n",
                    b"PARTID,Alter\n\"unterminated", b"wrong,header\n1000,1001\n"):
            with self.subTest(raw=raw):
                members = source_members()
                members["w2_FriendshipEdgelist.csv"] = raw
                with self.assertRaises(ValueError):
                    self.report(members)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.zip"
            path.write_bytes(b"not a ZIP")
            with self.assertRaises(ValueError):
                mauldin.mauldin_source_report(path)
            write_source(path, compression=ZIP_BZIP2)
            with self.assertRaisesRegex(ValueError, "unsupported compression"):
                mauldin.mauldin_source_report(path)


if __name__ == "__main__":
    unittest.main()
