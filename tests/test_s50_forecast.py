"""Synthetic ZIPs verify temporal input separation, never real target values."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from sociolab import s50_forecast
from sociolab.s50 import S50_SOURCE
from sociolab.s50_forecast import load_s50_forecast_history, load_s50_forecast_target


def synthetic_members() -> dict[str, bytes]:
    """Generate a teaching-format fixture, not a copy of the source dataset."""
    files = {}
    for wave, count in enumerate((113, 116), start=1):
        matrix = [[0] * 50 for _ in range(50)]
        links = [(actor, (actor + distance) % 50)
                 for distance in range(1, 4) for actor in range(50)]
        for actor, alter in links[:count]:
            matrix[actor][alter] = 1
        files[f"s50-network{wave}.dat"] = matrix_bytes(matrix)
    files["s50-network3.dat"] = b"intentionally not a valid network\n"
    files["s50-alcohol.dat"] = b"".join(
        f"{1 + actor % 5} {1 + (actor + 1) % 5} {1 + (actor + 2) % 5}\n".encode()
        for actor in range(50)
    )
    return files


def matrix_bytes(matrix: list[list[int]]) -> bytes:
    return ("\n".join(" ".join(map(str, row)) for row in matrix) + "\n").encode()


def archive_bytes(files: dict[str, bytes]) -> bytes:
    result = BytesIO()
    with ZipFile(result, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return result.getvalue()


class S50ForecastSourceTest(unittest.TestCase):
    def read(self, files: dict[str, bytes] | bytes, reader=load_s50_forecast_history):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-s50.zip"
            path.write_bytes(files if isinstance(files, bytes) else archive_bytes(files))
            return reader(path)

    def test_history_retains_fixed_early_roster_and_teaching_scope(self):
        panel, provenance = self.read(synthetic_members())
        self.assertEqual(panel.actors, tuple(f"p{i:03d}" for i in range(1, 51)))
        self.assertEqual([wave.time_index for wave in panel.waves], [0, 1])
        self.assertEqual([len(wave.edges) for wave in panel.waves], [113, 116])
        self.assertEqual([dict(wave.behavior)["p001"] for wave in panel.waves], [1, 2])
        self.assertEqual(panel.dataset_id, "teenage-friends-s50-numerical-example")
        self.assertEqual(panel.origin, "external_observation")
        self.assertEqual(panel.source_reference, S50_SOURCE)
        self.assertEqual(panel.behavior_variable, "alcohol_consumption_ordinal_1_to_5")
        self.assertEqual(provenance["consumed_behavior_columns_1based"], [1, 2])
        self.assertRegex(provenance["source_prefix_sha256"], r"^sha256:[a-f0-9]{64}$")
        self.assertNotIn("source_archive_sha256", provenance)
        self.assertNotIn("p001", json.dumps(provenance))
        for field in ("source_claim_verified", "sample_has_valid_population_boundary",
                      "suitable_for_empirical_influence_estimation", "causal_effect_identified",
                      "forecast_accuracy_established", "future_network_members_read",
                      "future_behavior_columns_parsed"):
            self.assertFalse(provenance[field])

    def test_future_replacements_and_missing_future_cannot_change_history(self):
        original = synthetic_members()
        expected = self.read(original)
        prefix = [b" ".join(row.split()[:2]) for row in original["s50-alcohol.dat"].splitlines()]
        for future in (b"5", b"0", b"NA", b"\xff", b"several opaque future tokens", b""):
            with self.subTest(future=future):
                changed = dict(original)
                del changed["s50-network3.dat"]
                changed["s50-alcohol.dat"] = b"\n".join(row + b" " + future for row in prefix) + b"\n"
                self.assertEqual(self.read(changed), expected)
        changed = dict(original)
        changed["s50-network3.dat"] = b"\xff" * 170_000  # Unconsumed member size is irrelevant.
        self.assertEqual(self.read(changed), expected)

    def test_history_never_opens_future_network_member(self):
        original_open = ZipFile.open
        opened = []

        def record_open(archive, member, *args, **kwargs):
            opened.append(member.filename if hasattr(member, "filename") else member)
            return original_open(archive, member, *args, **kwargs)

        raw = archive_bytes(synthetic_members())
        with patch.object(ZipFile, "open", record_open):
            self.read(raw)
        self.assertCountEqual(opened, ["s50-network1.dat", "s50-network2.dat", "s50-alcohol.dat"])

    def test_consumed_behavior_changes_only_its_wave_revision_and_prefix_hash(self):
        files = synthetic_members()
        baseline, baseline_provenance = self.read(files)
        for column in (0, 1):
            with self.subTest(column=column):
                changed = dict(files)
                rows = [row.split() for row in files["s50-alcohol.dat"].splitlines()]
                rows[0][column] = b"5"
                changed["s50-alcohol.dat"] = b"\n".join(b" ".join(row) for row in rows) + b"\n"
                panel, provenance = self.read(changed)
                self.assertNotEqual(panel.waves[column].source_revision, baseline.waves[column].source_revision)
                self.assertEqual(panel.waves[1 - column], baseline.waves[1 - column])
                self.assertNotEqual(provenance["source_prefix_sha256"], baseline_provenance["source_prefix_sha256"])

    def test_consumed_network_change_changes_revision_without_future_dependence(self):
        files = synthetic_members()
        baseline, baseline_provenance = self.read(files)
        matrix = [list(map(int, row.split())) for row in files["s50-network1.dat"].splitlines()]
        matrix[0][1], matrix[0][49] = 0, 1
        files["s50-network1.dat"] = matrix_bytes(matrix)
        panel, provenance = self.read(files)
        self.assertNotEqual(panel.waves[0].source_revision, baseline.waves[0].source_revision)
        self.assertEqual(panel.waves[1], baseline.waves[1])
        self.assertNotEqual(provenance["source_prefix_sha256"], baseline_provenance["source_prefix_sha256"])

    def test_target_has_exact_schema_and_needs_no_network_or_valid_history_values(self):
        files = synthetic_members()
        expected = self.read(files, load_s50_forecast_target)
        self.assertEqual(set(expected), {"schema", "dataset_id", "origin", "source_reference",
                                        "behavior_variable", "time_index", "source_revision", "behavior"})
        self.assertEqual(expected["schema"], "sociolab.behavior-target.v1")
        self.assertEqual(expected["time_index"], 2)
        self.assertEqual(expected["behavior"]["p001"], 3)
        self.assertEqual(list(expected["behavior"]), [f"p{i:03d}" for i in range(1, 51)])
        target_only = {"s50-alcohol.dat": b"".join(
            b"\xff invalid " + row.split()[2] + b"\n"
            for row in files["s50-alcohol.dat"].splitlines()
        )}
        self.assertEqual(self.read(target_only, load_s50_forecast_target), expected)
        rows = target_only["s50-alcohol.dat"].splitlines()
        rows[0] = b"\xff invalid 4"
        target_only["s50-alcohol.dat"] = b"\n".join(rows) + b"\n"
        changed = self.read(target_only, load_s50_forecast_target)
        self.assertNotEqual(changed["source_revision"], expected["source_revision"])
        self.assertEqual(changed["behavior"]["p001"], 4)

    def test_target_rejects_missing_or_invalid_consumed_target(self):
        for row in (b"1 2", b"1 2 NA", b"1 2 -999", b"1 2 0", b"1 2 6",
                    b"1 2 \xff", b"1 2 3 extra"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.read({"s50-alcohol.dat": (row + b"\n") * 50}, load_s50_forecast_target)
        with self.assertRaisesRegex(ValueError, "50 rows"):
            self.read({"s50-alcohol.dat": b"1 2 3\n" * 49}, load_s50_forecast_target)

    def test_history_rejects_bad_consumed_behavior_and_missing_rows(self):
        for row in (b"1", b"NA 2 hidden", b"1 0 hidden", b"6 2 hidden", b"\xff 2 hidden"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                files = synthetic_members()
                files["s50-alcohol.dat"] = (row + b"\n") * 50
                self.read(files)
        files = synthetic_members()
        files["s50-alcohol.dat"] = b"1 2 hidden\n" * 49
        with self.assertRaisesRegex(ValueError, "50 rows"):
            self.read(files)

    def test_history_rejects_bad_consumed_network_without_filling_missing_ties(self):
        base = synthetic_members()
        original = [list(map(int, row.split())) for row in base["s50-network1.dat"].splitlines()]
        cases = []
        for row, column, value in ((0, 1, 9), (0, 0, 1), (0, 1, 0)):
            matrix = [line[:] for line in original]
            matrix[row][column] = value
            cases.append(matrix_bytes(matrix))
        matrix = [line[:] for line in original]
        matrix[0] = [0] + [1] * 13 + [0] * 36
        cases.extend((matrix_bytes(matrix), matrix_bytes(original[:49]),
                      matrix_bytes([line[:49] for line in original])))
        for invalid in cases:
            with self.subTest(invalid=invalid[:60]), self.assertRaises(ValueError):
                files = dict(base)
                files["s50-network1.dat"] = invalid
                self.read(files)

    def test_required_members_and_safe_zip_limits_are_enforced(self):
        base = synthetic_members()
        for name in ("s50-network1.dat", "s50-network2.dat", "s50-alcohol.dat"):
            with self.subTest(missing=name), self.assertRaisesRegex(ValueError, "lacks required"):
                self.read({key: value for key, value in base.items() if key != name})
        for unsafe in ("../extra.dat", "/extra.dat", "folder\\extra.dat"):
            with self.subTest(path=unsafe), self.assertRaisesRegex(ValueError, "unsafe member path"):
                self.read({**base, unsafe: b"unused"})
        with self.assertRaisesRegex(ValueError, "duplicate required"):
            self.read({**base, "extra/s50-network1.dat": base["s50-network1.dat"]})
        with self.assertRaisesRegex(ValueError, "valid ZIP"):
            self.read(b"not a ZIP")
        raw = archive_bytes(base)
        with patch.object(s50_forecast, "_ARCHIVE_MAX_BYTES", len(raw) - 1):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                self.read(raw)
        with patch.object(s50_forecast, "_MEMBER_MAX_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "bounded input size"):
                self.read(raw)


if __name__ == "__main__":
    unittest.main()
