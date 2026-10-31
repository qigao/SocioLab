"""Synthetic ZIP fixtures test the official file reader, not the real dataset."""

from io import BytesIO, StringIO
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.s50 import load_s50_archive, s50_reference_report
from sociolab.cli import main

COUNTS = (113, 116, 122)


def example_zip(*, missing: str | None = None, invalid: tuple[str, str] | None = None) -> bytes:
    """Make generated, s50-shaped test data; NEVER claim these are original s50."""
    files = {}
    for i, count in enumerate(COUNTS):
        matrix = [[0] * 50 for _ in range(50)]
        links = [(actor, (actor + distance) % 50)
                 for distance in range(1, 4) for actor in range(50)]
        for actor, target in links[:count]:
            matrix[actor][target] = 1
        files[f"s50-network{i + 1}.dat"] = "\n".join(
            " ".join(map(str, row)) for row in matrix
        ) + "\n"
    files["s50-alcohol.dat"] = "\n".join(
        " ".join(str(1 + (actor + wave) % 5) for wave in range(3))
        for actor in range(50)
    ) + "\n"
    if missing:
        del files[missing]
    if invalid:
        files[invalid[0]] = invalid[1]
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class S50PublishedFormatTest(unittest.TestCase):
    def run_file(self, raw: bytes, func=load_s50_archive):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s50.zip"
            path.write_bytes(raw)
            return func(path)

    def test_synthetic_source_shape_validates_via_real_networkx(self):
        panel, provenance = self.run_file(example_zip())
        self.assertEqual(len(panel.actors), 50)
        self.assertEqual([len(w.edges) for w in panel.waves], list(COUNTS))
        self.assertEqual([w.time_index for w in panel.waves], [0, 1, 2])
        self.assertEqual([w.behavior[0] for w in panel.waves], [("p001", 1), ("p001", 2), ("p001", 3)])
        self.assertRegex(provenance["source_archive_sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(len(provenance["source_member_sha256"]), 4)
        report = self.run_file(example_zip(), s50_reference_report)
        self.assertEqual(report["kind"], "REFERENCE_MODEL_RESULT")
        self.assertEqual([w["directed_edge_count"] for w in report["waves"]], list(COUNTS))
        self.assertFalse(report["source_claim_verified"])
        self.assertFalse(report["sample_has_valid_population_boundary"])
        self.assertFalse(report["suitable_for_empirical_influence_estimation"])
        self.assertFalse(report["saom_model_fitted"])
        self.assertFalse(report["causal_effect_identified"])

    def test_cli_reports_source_scope_without_fabricating_empirical_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.zip"
            path.write_bytes(example_zip())
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["s50", str(path)]), 0)
            result = json.loads(output.getvalue())
        self.assertEqual(result["published_illustrative_tie_counts"], [113, 116, 122])
        self.assertFalse(result["source_claim_verified"])
        self.assertFalse(result["suitable_for_empirical_influence_estimation"])

    def test_requires_four_source_files(self):
        with self.assertRaisesRegex(ValueError, "lacks required"):
            self.run_file(example_zip(missing="s50-network2.dat"))

    def test_rejects_truncated_network_matrix(self):
        with self.assertRaisesRegex(ValueError, "50 rows"):
            self.run_file(example_zip(invalid=("s50-network1.dat", "0 1\n")))

    def test_rejects_missing_tie_instead_of_treating_it_as_absent(self):
        text = " ".join(["9"] + ["0"] * 49) + "\n"
        bad = text * 50
        with self.assertRaisesRegex(ValueError, "missing or unsupported"):
            self.run_file(example_zip(invalid=("s50-network1.dat", bad)))

    def test_rejects_wrong_behavior_domain(self):
        with self.assertRaisesRegex(ValueError, "missing or unsupported"):
            self.run_file(example_zip(invalid=("s50-alcohol.dat", "9 9 9\n" * 50)))

    def test_rejects_invalid_archive_and_missing_members(self):
        with self.assertRaisesRegex(ValueError, "valid ZIP"):
            self.run_file(b"not a zip archive")

    def test_rejects_duplicate_required_basename(self):
        buffer = BytesIO(example_zip())
        with ZipFile(buffer, "a", ZIP_DEFLATED) as archive:
            archive.writestr("alternate/s50-network1.dat", "0 0\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_file(buffer.getvalue())

    def test_rejects_path_traversal(self):
        buffer = BytesIO(example_zip())
        with ZipFile(buffer, "a", ZIP_DEFLATED) as archive:
            archive.writestr("../bad.txt", "bad")
        with self.assertRaisesRegex(ValueError, "unsafe member path"):
            self.run_file(buffer.getvalue())

    def test_rejects_wrong_published_wave_counts(self):
        with self.assertRaisesRegex(ValueError, "friendship ties differ"):
            self.run_file(example_zip(invalid=("s50-network1.dat", "0 " * 49 + "0\n" + ("0 " * 49 + "0\n") * 49)))


if __name__ == "__main__":
    unittest.main()
