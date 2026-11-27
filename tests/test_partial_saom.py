"""Observation conversion, admission and path-audit boundaries; no fake fit."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.cli import main
from sociolab.partial_panels import PartialNetworkPanel, load_partial_panel
from sociolab.partial_saom import (
    partial_saom_wave_matrices, partial_network_model_report,
    fit_partial_network_saom, _record_conditional_batch,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/partial/coverage.panel.json"


def unknown_panel():
    value = load_partial_panel(EXAMPLE).to_dict()
    for wave in value["waves"]:
        wave["observed_present"] = []
        wave["observed_absent"] = []
    return PartialNetworkPanel.from_mapping(value)


class PartialSAOMBoundaryTests(unittest.TestCase):
    def test_matrices_keep_explicit_negatives_and_directional_unknowns(self):
        panel = load_partial_panel(EXAMPLE)
        matrices = partial_saom_wave_matrices(panel)
        for wave, matrix in zip(panel.waves, matrices):
            self.assertEqual(matrix.dtype, np.float64)
            for row, actor in enumerate(panel.actors):
                for column, alter in enumerate(panel.actors):
                    pair = (actor, alter)
                    if row == column or pair in wave.observed_absent:
                        self.assertEqual(matrix[row, column], 0)
                    elif pair in wave.observed_present:
                        self.assertEqual(matrix[row, column], 1)
                    else:
                        self.assertTrue(np.isnan(matrix[row, column]))
        self.assertFalse(np.array_equal(matrices[0], matrices[0].T, equal_nan=True))
        old_hash = panel.content_hash
        matrices[0][:] = 99
        fresh = partial_saom_wave_matrices(panel)
        self.assertFalse(np.any(fresh[0] == 99))
        self.assertEqual(panel.content_hash, old_hash)

    def test_all_unknown_wave_keeps_every_offdiagonal_nan(self):
        for matrix in partial_saom_wave_matrices(unknown_panel()):
            self.assertEqual(int(np.isnan(matrix).sum()), 12)
            np.testing.assert_array_equal(np.diag(matrix), np.zeros(4))

    def test_readiness_rejects_no_shared_observations_or_no_observed_changes(self):
        for function in (partial_network_model_report, fit_partial_network_saom):
            with self.subTest(function=function.__name__):
                with self.assertRaisesRegex(ValueError, "known-overlap"):
                    function(unknown_panel())
                value = load_partial_panel(EXAMPLE).to_dict()
                value["waves"][1]["observed_present"] = value["waves"][0]["observed_present"]
                value["waves"][1]["observed_absent"] = value["waves"][0]["observed_absent"]
                with self.assertRaisesRegex(ValueError, "positive observed distance"):
                    function(PartialNetworkPanel.from_mapping(value))

    def test_budget_types_are_rejected_before_a_solver_is_loaded(self):
        panel = unknown_panel()
        for values in ({"seed": True}, {"seed": -1}, {"n1": 0}, {"nD": 1.5},
                       {"n3": 3}, {"batch2": False}, {"n2": [2, 2, 2, 2]},
                       {"n2": (2, 2, 0, 2)}):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "seed/budgets|n2|n3"):
                fit_partial_network_saom(panel, **values)

    def test_cli_native_inspection_preserves_coverage_instead_of_fitting(self):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["partial", "inspect", str(EXAMPLE)])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["kind"], "PARTIAL_NETWORK_OBSERVATION_REPORT")
        self.assertEqual(report["periods"][0]["known_overlap"], 4)
        self.assertEqual(report["periods"][0]["coverage_lost"], 2)
        self.assertFalse(report["model_fitted"])

    def test_cli_reports_not_ready_as_an_error_without_fake_fit_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unknown.json"
            path.write_text(json.dumps(unknown_panel().to_dict()))
            for action in ("model", "fit"):
                output, errors = StringIO(), StringIO()
                with redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                    main(["partial", action, str(path)])
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("known-overlap", errors.getvalue())


class ConditionalPathAuditTests(unittest.TestCase):
    def record(self, result):
        audit = [{"path_count": 0, "batch_calls": 0, "max_steps": 0,
                  "min_duration": float("inf"), "max_duration": 0.0}]
        _record_conditional_batch(audit, result, n_sims=2, period=0, target=2, max_steps=100)
        return audit[0]

    def valid(self):
        return {"steps": np.array([3, 7], dtype=np.int64),
                "dist": np.array([2, 2]), "dist_stat": np.array([2, 2]), "ntim": np.array([0.2, 1.5])}

    def test_completed_conditional_paths_can_have_durations_below_one(self):
        result = self.valid()
        original = {key: value.copy() for key, value in result.items()}
        audit = self.record(result)
        self.assertEqual(audit, {"path_count": 2, "batch_calls": 1, "max_steps": 7,
                                 "min_duration": 0.2, "max_duration": 1.5})
        for key in original:
            np.testing.assert_array_equal(result[key], original[key])

    def test_incomplete_capped_or_invalid_paths_are_rejected(self):
        for key, value in (("dist", [2, 1]), ("dist", [2, float("nan")]), ("dist_stat", [2, 1]),
                           ("steps", [3, 100]), ("steps", [0, 7]),
                           ("steps", [3.0, 7.0]), ("steps", [True, True]),
                           ("steps", [3]), ("ntim", [0.2, 0]),
                           ("ntim", [0.2, float("inf")])):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                result = self.valid()
                result[key] = np.asarray(value)
                self.record(result)


if __name__ == "__main__":
    unittest.main()
