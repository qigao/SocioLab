"""Explicit CPU integration tests for the optional [saom] dependency.

Run with: python -m unittest discover -s tests/saom_runtime -v
This directory is intentionally not a package in the base test discovery.
Missing cusna is an error in this opt-in suite; no estimator is substituted.
"""

from importlib.metadata import version
from pathlib import Path
import sys
import unittest

import numpy as np
from cusna.saom.data import SaomData, synthetic_panel
from cusna.saom.mom import MomEstimator
from cusna.saom.stats import EffectSpec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sociolab.panels import LongitudinalPanel
from sociolab.saom import fit_network_saom, saom_wave_matrices


def _panel(waves, dataset_id):
    actors = [f"actor-{i:03d}" for i in range(waves[0].shape[0])]
    return LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1",
        "dataset_id": dataset_id,
        "origin": "synthetic",
        "source_reference": None,
        "actors": actors,
        "relation": "directed_observed_social_tie",
        "behavior_variable": "unused",
        "waves": [
            {
                "time_index": t,
                "source_revision": f"wave-{t}",
                "network_complete": True,
                "edges": [[actors[i], actors[j]]
                          for i in range(len(actors))
                          for j in range(len(actors)) if wave[i, j]],
                "behavior": {actor: None for actor in actors},
            }
            for t, wave in enumerate(waves)
        ],
    })


class SAOMRuntimeTests(unittest.TestCase):
    def test_reciprocal_directed_panel_is_rejected_before_estimation(self):
        panel = _panel([
            np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]], dtype=np.uint8),
            np.array([[0, 1, 1], [1, 0, 0], [1, 0, 0]], dtype=np.uint8),
        ], "reciprocal-directed-observations")
        upstream_data = SaomData(saom_wave_matrices(panel))
        self.assertTrue(upstream_data.symmetric)
        with self.assertRaisesRegex(
            ValueError,
            "directed SAOM is unsupported.*cusna infers an undirected model",
        ):
            fit_network_saom(panel)

    def test_cpu_fit_matches_actual_upstream_result(self):
        upstream_data = synthetic_panel(
            20, mean_degree=4, change_frac=0.25, seed=17,
        )
        self.assertFalse(upstream_data.symmetric)
        panel = _panel(upstream_data.waves, "upstream-synthetic-20")
        settings = {
            "seed": 1234,
            "n1": 64,
            "nD": 64,
            "n3": 128,
            "batch2": 16,
            "n2": (2, 2, 2, 2),
        }
        upstream_estimator = MomEstimator(
            upstream_data,
            effects=[EffectSpec(name) for name in ("density", "recip", "transTrip")],
            backend="cpu", conditional=True, **settings,
        )
        upstream = upstream_estimator.estimate(verbose=False)
        report = fit_network_saom(panel, **settings)

        self.assertEqual(report["engine_version"], version("cusna"))
        self.assertEqual(report["backend"], upstream.backend)
        self.assertEqual(report["conditional"], upstream.conditional)
        self.assertEqual(report["effect_names"], upstream.param_names)
        for key, values in (("estimates", upstream.theta),
                            ("standard_errors", upstream.se),
                            ("tconv", upstream.tconv)):
            np.testing.assert_allclose(report[key], values, rtol=1e-9, atol=1e-9)
            self.assertTrue(np.isfinite(report[key]).all())
        self.assertAlmostEqual(report["tconv_max"], upstream.tconv_max, places=9)
        for field in ("targets", "sim_means", "D", "msf"):
            np.testing.assert_allclose(report["diagnostics"][field],
                                       getattr(upstream, field), rtol=1e-9, atol=1e-9)
        for field in ("rate_est", "rate_sd", "theta_trace"):
            np.testing.assert_allclose(report[field], getattr(upstream, field),
                                       rtol=1e-9, atol=1e-9)
        self.assertEqual(report["diagnostics"]["derivative_rank"], np.linalg.matrix_rank(upstream.D))
        self.assertEqual(report["diagnostics"]["statistic_covariance_rank"],
                         np.linalg.matrix_rank(upstream.msf))
        self.assertAlmostEqual(report["diagnostics"]["derivative_condition_number"],
                               np.linalg.cond(upstream.D), places=9)
        self.assertAlmostEqual(report["diagnostics"]["statistic_covariance_condition_number"],
                               np.linalg.cond(upstream.msf), places=9)
        self.assertEqual(report["max_abs_tconv"], float(np.max(np.abs(upstream.tconv))))
        expected_convergence = (np.max(np.abs(upstream.tconv)) < 0.1
                                and 0 <= upstream.tconv_max < 0.25)
        self.assertEqual(report["convergence_is_validated"], bool(expected_convergence))
        self.assertEqual(report["convergence_status"],
                         "CONVERGED" if expected_convergence else "NOT_CONVERGED")
        self.assertEqual(report["convergence_scope"], "numerical moment matching only")
        self.assertEqual(report["n_simulations"], upstream.n_sims)
        self.assertEqual(report["n_simulations_unit"], "full-panel replicates")
        self.assertGreater(report["n_simulations"], 0)
        self.assertEqual(report["dataset_hash"], panel.content_hash)
        self.assertEqual(report["seed"], settings["seed"])
        self.assertEqual(report["n2"], list(settings["n2"]))
        for field in ("firstg", "nsub", "diagonalize", "maxdegree"):
            self.assertEqual(report["algorithm_settings"][field], getattr(upstream_estimator, field))
        np.testing.assert_allclose(report["algorithm_settings"]["initial_theta"],
                                   upstream.theta_trace[0])
        self.assertEqual(report["runtime_versions"]["numpy"], version("numpy"))
        self.assertEqual(report["runtime_versions"]["numba"], version("numba"))
        self.assertIn("not standard error", report["rate_sd_meaning"])
        self.assertFalse(report["independent_reference_validated"])
        self.assertFalse(report["behavior_coevolution_fitted"])
        self.assertFalse(report["population_boundary_qualified"])
        self.assertFalse(report["causal_effect_identified"])


if __name__ == "__main__":
    unittest.main()
