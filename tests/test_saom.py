"""Input invariants; optional upstream execution is in tests/saom_runtime."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.panels import LongitudinalPanel, load_panel
from sociolab.saom import _assess_mom_diagnostics, saom_wave_matrices, fit_network_saom

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/synthetic_longitudinal.json"


class SAOMInputTests(unittest.TestCase):
    def test_directed_source_identity_and_order(self):
        panel = load_panel(EXAMPLE)
        matrices = saom_wave_matrices(panel)
        self.assertEqual(len(matrices), 3)
        self.assertEqual([m.shape for m in matrices], [(3, 3)] * 3)
        self.assertTrue(all(m.dtype == np.uint8 for m in matrices))
        self.assertEqual([int(m.sum()) for m in matrices], [1, 2, 1])
        self.assertEqual([int(m[0, 1]) for m in matrices], [1, 1, 0])
        self.assertEqual([int(m[1, 0]) for m in matrices], [0, 0, 0])
        self.assertEqual([int(m[1, 2]) for m in matrices], [0, 1, 1])

    def test_cannot_count_unobserved_ties_as_zero(self):
        panel = load_panel(EXAMPLE)
        data = panel.to_dict()
        data["waves"][1]["network_complete"] = False
        with self.assertRaisesRegex(ValueError, "incomplete network"):
            saom_wave_matrices(LongitudinalPanel.from_mapping(data))

    def test_no_fake_saom_or_invalid_budget(self):
        panel = load_panel(EXAMPLE)
        for kwargs in ({"seed": True}, {"n1": 0}, {"nD": -1},
                       {"n2": (1, 1)}, {"n2": (1, 1, 1, True)},
                       {"batch2": 0}, {"n3": 1}, {"n3": 3}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    fit_network_saom(panel, **kwargs)

    def test_reject_wrong_type(self):
        with self.assertRaises(TypeError):
            saom_wave_matrices({"actors": ["alice"]})


class SAOMDiagnosticTests(unittest.TestCase):
    """Synthetic diagnostic arrays exercise the gate, never an estimator."""

    def diagnostics(self):
        return {
            "theta": np.array([-2.0, 1.0, 0.5]),
            "se": np.ones(3),
            "tconv": np.array([0.02, 0.03, 0.04]),
            "tconv_max": np.linalg.norm([0.02, 0.03, 0.04]),
            "targets": np.array([1.0, 2.0, 3.0]),
            "sim_means": np.array([1.02, 2.03, 3.04]),
            "D": np.eye(3),
            "msf": np.eye(3),
        }

    def test_individual_convergence_threshold_is_strict_and_absolute(self):
        for ratio, expected in ((np.nextafter(0.1, 0.0), True),
                                (0.1, False), (-0.1, False)):
            with self.subTest(ratio=ratio):
                values = self.diagnostics()
                values["tconv"] = np.array([ratio, 0.0, 0.0])
                values["tconv_max"] = abs(ratio)
                values["sim_means"] = values["targets"] + values["tconv"]
                report = _assess_mom_diagnostics(**values)
                self.assertEqual(report["convergence_is_validated"], expected)
                self.assertEqual(report["convergence_status"],
                                 "CONVERGED" if expected else "NOT_CONVERGED")
                self.assertEqual(report["max_abs_tconv"], abs(ratio))
                self.assertEqual(report["convergence_scope"], "numerical moment matching only")

    def test_overall_convergence_threshold_is_independent_and_strict(self):
        values = self.diagnostics()
        values["tconv"] = np.array([0.05, -0.05, 0.0])
        values["sim_means"] = values["targets"] + values["tconv"]
        values["msf"] = np.array([[1.0, 0.92, 0.0], [0.92, 1.0, 0.0], [0.0, 0.0, 1.0]])
        for overall, expected in ((np.nextafter(0.25, 0.0), True), (0.25, False)):
            with self.subTest(overall=overall):
                values["tconv_max"] = overall
                report = _assess_mom_diagnostics(**values)
                self.assertEqual(report["convergence_is_validated"], expected)

    def test_singular_and_invalid_covariance_diagnostics_fail(self):
        cases = (
            ("D", np.diag([1.0, 1.0, 0.0]), "rank-deficient"),
            ("msf", np.diag([1.0, 1.0, 0.0]), "rank-deficient"),
            ("msf", np.diag([1.0, 1.0, -1.0]), "positive definite"),
            ("msf", np.array([[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
             "not symmetric"),
        )
        for field, array, message in cases:
            with self.subTest(field=field, message=message):
                values = self.diagnostics()
                values[field] = array
                with self.assertRaisesRegex(ValueError, message):
                    _assess_mom_diagnostics(**values)

    def test_derivative_need_not_be_symmetric_or_positive_definite(self):
        values = self.diagnostics()
        values["D"] = np.array([[1.0, 0.5, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]])
        values["se"] = np.sqrt([1.25, 1.0, 1.0])
        report = _assess_mom_diagnostics(**values)
        self.assertEqual(report["diagnostics"]["derivative_rank"], 3)
        self.assertTrue(report["convergence_is_validated"])

    def test_condition_numbers_are_reported_without_an_arbitrary_cutoff(self):
        values = self.diagnostics()
        values["D"] = np.diag([1.0, 1.0, 1e-10])
        values["se"] = np.array([1.0, 1.0, 1e10])
        report = _assess_mom_diagnostics(**values)
        self.assertEqual(report["diagnostics"]["derivative_condition_number"], 1e10)
        self.assertEqual(report["diagnostics"]["statistic_covariance_condition_number"], 1.0)

    def test_invalid_shapes_nonfinite_values_and_errors_fail(self):
        cases = (
            ("theta", np.zeros((3, 1))),
            ("theta", np.array([True, False, True])),
            ("se", np.array(["1", "1", "1"])),
            ("D", np.full((3, 3), np.nan)),
            ("sim_means", np.array([1.0, 2.0, np.inf])),
            ("tconv_max", np.nan),
            ("tconv_max", -0.1),
            ("se", np.array([1.0, 0.0, 1.0])),
            ("se", np.array([1.0, -1.0, 1.0])),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                values = self.diagnostics()
                values[field] = value
                with self.assertRaises(ValueError):
                    _assess_mom_diagnostics(**values)


if __name__ == "__main__":
    unittest.main()
