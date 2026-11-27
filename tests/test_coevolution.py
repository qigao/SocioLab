"""Boundary checks for audited original CPU paths and joint fit budgets."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.coevolution import _record_cpu_batch, fit_coevolution_saom
from sociolab.coevolution_input import load_coevolution_spec
from sociolab.panels import load_panel


class CoevolutionBoundaryTest(unittest.TestCase):
    def audit(self):
        return {"batch_calls": 0, "period_paths_checked": 0,
                "max_steps_per_path": 0, "max_steps_by_period": [0, 0]}

    def check(self, result, audit=None, period=0):
        _record_cpu_batch(result, n_sims=2, period=period, step_limit=4_000_000,
                          audit=self.audit() if audit is None else audit)

    def test_cpu_audit_retains_original_result_and_counts_every_path(self):
        audit = self.audit()
        result = {"steps": np.array([3, 8]), "ntim": np.array([1.01, 1.2])}
        original = deepcopy(result)
        self.check(result, audit, period=1)
        self.check({"steps": np.array([5, 2]), "ntim": np.array([1.3, 1.1])}, audit)
        self.assertEqual(audit, {"batch_calls": 2, "period_paths_checked": 4,
                                "max_steps_per_path": 8, "max_steps_by_period": [5, 8]})
        for key in result:
            np.testing.assert_array_equal(result[key], original[key])

    def test_reaching_kernel_limit_is_rejected_without_counting_batch(self):
        audit = self.audit()
        with self.assertRaisesRegex(ValueError, "step limit"):
            self.check({"steps": np.array([8, 4_000_000]), "ntim": np.array([1.1, 0.4])}, audit)
        self.assertEqual(audit, self.audit())

    def test_malformed_or_incomplete_cpu_paths_fail(self):
        for steps in (np.array([True, False]), np.array([1., 2.]), np.array([-1, 2]),
                      np.array([[1, 2]]), np.array([1])):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                self.check({"steps": steps, "ntim": np.array([1.1, 1.2])})
        for elapsed in (np.array([1.0, 1.1]), np.array([0.5, 1.1]), np.array([np.nan, 1.1]),
                        np.array([np.inf, 1.1]), np.array([1.1])):
            with self.subTest(elapsed=elapsed), self.assertRaises(ValueError):
                self.check({"steps": np.array([1, 2]), "ntim": elapsed})

    def test_joint_budget_counts_rates_and_rejects_invalid_settings_before_fitting(self):
        folder = Path(__file__).resolve().parents[1] / "examples/coevolution"
        panel = load_panel(folder / "synthetic.panel.json")
        spec = load_coevolution_spec(folder / "synthetic.model.json")
        # Two waves require two rates plus nine evaluation effects, not nine.
        for budget in (9, 10, 11):
            with self.subTest(n3=budget), self.assertRaisesRegex(ValueError, "including both rates"):
                fit_coevolution_saom(panel, spec, n3=budget)
        for settings in ({"seed": True}, {"seed": -1}, {"n1": 0}, {"nD": 2.5},
                         {"n3": False}, {"batch2": 0}, {"n2": (1, 2, 3)},
                         {"n2": [1, 2, 3, 4]}, {"n2": (1, 2, 3, False)}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                fit_coevolution_saom(panel, spec, **settings)

    def test_fit_requires_typed_panel_and_specification(self):
        with self.assertRaises(TypeError):
            fit_coevolution_saom({}, {})


if __name__ == "__main__":
    unittest.main()
