"""Opt-in missing-dyad integration against the genuine pinned CPU estimator.

Run with the optional [saom] dependencies:
python -m unittest discover -s tests/saom_runtime -p test_partial_saom_runtime.py -v
The fixture is invented, its masks are fixed before fitting, and no solver is
mocked or replaced. Low simulation counts test software, not empirical fit.
"""

from importlib.metadata import version
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from cusna.saom.cpu import MAX_STEPS
from cusna.saom.data import SaomData, synthetic_panel
from cusna.saom.mom import MomEstimator
from cusna.saom.stats import EffectSpec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sociolab.partial_panels import PartialNetworkPanel
from sociolab.partial_saom import (
    fit_partial_network_saom,
    partial_network_model_report,
    partial_saom_wave_matrices,
)


_EFFECTS = ("density", "recip", "transTrip")
_SETTINGS = {
    "seed": 1234, "n1": 64, "nD": 64, "n3": 128,
    "batch2": 16, "n2": (2, 2, 2, 2),
}


def _panel(waves, dataset_id):
    actors = [f"actor-{i:03d}" for i in range(waves[0].shape[0])]
    return PartialNetworkPanel.from_mapping({
        "schema": "sociolab.partial-network.v1",
        "dataset_id": dataset_id, "origin": "synthetic", "source_reference": None,
        "actors": actors, "relation": "directed_observed_social_tie",
        "population_definition": "Fixed invented roster present at all waves.",
        "observation_definition": "Explicit binary observations; unlisted dyads are unknown.",
        "waves": [
            {
                "time_index": t, "source_revision": f"wave-{t}",
                "observed_present": [[actors[i], actors[j]]
                                     for i in range(len(actors))
                                     for j in range(len(actors))
                                     if i != j and wave[i, j] == 1],
                "observed_absent": [[actors[i], actors[j]]
                                    for i in range(len(actors))
                                    for j in range(len(actors))
                                    if i != j and wave[i, j] == 0],
            }
            for t, wave in enumerate(waves)
        ],
    })


def _fixed_mask_fixture():
    original = synthetic_panel(20, mean_degree=4, change_frac=0.25, seed=17)
    waves = [wave.astype(np.float64) for wave in original.waves]
    # Fixed actor rows, chosen before any fit: outgoing nonresponse does not
    # delete either actor or their separately observed incoming nominations.
    waves[0][0, 1:] = np.nan
    waves[1][2, np.arange(20) != 2] = np.nan
    return _panel(waves, "upstream-synthetic-partial-20"), waves


class PartialSAOMRuntimeTests(unittest.TestCase):
    def test_three_wave_masks_initialization_and_known_incoming(self):
        waves = [
            np.array([[0, np.nan, 1, 0], [1, 0, 0, 0],
                      [0, 1, 0, 0], [0, 0, 0, 0]], dtype=float),
            np.array([[0, np.nan, np.nan, np.nan], [1, 0, 1, 0],
                      [0, 1, 0, 0], [0, 0, 0, 0]], dtype=float),
            np.array([[0, 1, np.nan, 0], [1, 0, 1, 0],
                      [0, 0, 0, 0], [0, 0, 0, 0]], dtype=float),
        ]
        panel = _panel(waves, "three-wave-partial-observations")
        matrices = partial_saom_wave_matrices(panel)
        for actual, expected in zip(matrices, waves):
            self.assertEqual(actual.dtype, np.dtype(np.float64))
            np.testing.assert_array_equal(actual, expected)
            np.testing.assert_array_equal(np.diag(actual), np.zeros(4))
        data = SaomData(matrices)
        for actual, expected in zip(data.miss, waves):
            np.testing.assert_array_equal(actual, np.isnan(expected))
        self.assertFalse(data.symmetric)
        self.assertEqual([data.imputed[t][0, 1] for t in range(3)], [0, 0, 1])
        self.assertEqual([data.imputed[t][0, 2] for t in range(3)], [1, 1, 1])
        self.assertTrue(np.isnan(matrices[1][0, 1:]).all())
        self.assertEqual(matrices[1][1, 0], 1)
        self.assertEqual(data.imputed[1][1, 0], 1)
        self.assertTrue(data.permitted(0)[0, 1])
        self.assertTrue(data.permitted(1)[0, 2])
        # Previously unknown A->B becoming observed does not add a change
        # to the known-overlap stopping target or a period moment target.
        self.assertEqual([data.observed_distance(t) for t in range(2)], [1, 1])
        self.assertEqual([int(data.kmask_dist(t).sum()) for t in range(2)], [9, 9])
        self.assertFalse(data.kmask_dist(1)[0, 1])
        self.assertEqual(data.target_network(1)[0, 1], 0)
        self.assertEqual(data.target_network(1)[1, 0], 1)

        model = partial_network_model_report(panel)
        self.assertFalse(model["model_fitted"])
        self.assertEqual(model["effect_names"], list(_EFFECTS))
        self.assertEqual(model["targets"], [5, 2, 0])
        self.assertEqual([p["moment_targets"] for p in model["periods"]],
                         [[3, 2, 0], [2, 0, 0]])
        self.assertEqual([p["conditional_target_distance"] for p in model["periods"]], [1, 1])
        self.assertEqual([p["known_overlap"] for p in model["periods"]], [9, 9])
        self.assertEqual([p["unknown_dyads_permitted_to_toggle"] for p in model["periods"]], [3, 3])
        self.assertEqual([x["unknown_dyads"] for x in model["initialization"]], [1, 3, 1])
        self.assertEqual([x["unknown_initialized_to_one"] for x in model["initialization"]], [0, 1, 1])
        self.assertFalse(model["missingness_policy"]["source_observations_reclassified"])
        self.assertFalse(model["missingness_policy"]["missingness_mechanism_modeled"])
        self.assertTrue(model["missingness_policy"]["known_incoming_preserved"])
        # Upstream initialization does not turn the stored unknowns into
        # observations, and callers receive a fresh matrix on every request.
        matrices[1][0, 2] = 0
        self.assertTrue(np.isnan(partial_saom_wave_matrices(panel)[1][0, 2]))
        json.dumps(model, allow_nan=False)

    def test_unsupported_periods_and_symmetric_mode_reject_before_fit(self):
        complete = np.array([[0, 1, 0], [0, 0, 1], [0, 0, 0]], dtype=float)
        unknown = np.full((3, 3), np.nan)
        np.fill_diagonal(unknown, 0)
        no_overlap_start = unknown.copy()
        no_overlap_end = unknown.copy()
        no_overlap_start[0, 1] = 1
        no_overlap_end[1, 2] = 1
        symmetric_start = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]], dtype=float)
        symmetric_end = np.array([[0, 1, 1], [1, 0, 0], [1, 0, 0]], dtype=float)
        cases = [
            ("all-unknown-wave", [complete, unknown], "known-overlap"),
            ("no-common-known-dyad", [no_overlap_start, no_overlap_end], "known-overlap"),
            ("zero-observed-distance", [complete, complete.copy()], "positive observed distance"),
            ("symmetric-directed-observations", [symmetric_start, symmetric_end], "undirected model"),
        ]
        for name, waves, message in cases:
            panel = _panel(waves, name)
            for operation in (partial_network_model_report, fit_partial_network_saom):
                with self.subTest(case=name, operation=operation.__name__):
                    with self.assertRaisesRegex(ValueError, message):
                        operation(panel)

    def test_cpu_fit_matches_actual_upstream_with_fixed_missing_rows(self):
        panel, waves = _fixed_mask_fixture()
        for actual, expected in zip(partial_saom_wave_matrices(panel), waves):
            np.testing.assert_array_equal(actual, expected)
        data = SaomData(waves)
        self.assertFalse(data.symmetric)
        self.assertEqual([int(mask.sum()) for mask in data.miss], [19, 19])
        self.assertGreater(data.observed_distance(0), 0)
        self.assertTrue((waves[0][1:, 0] == 1).any())
        self.assertTrue((waves[1][:, 2] == 1).any())
        estimator = MomEstimator(
            data, effects=[EffectSpec(name) for name in _EFFECTS],
            backend="cpu", conditional=True, **_SETTINGS,
        )
        model = partial_network_model_report(panel)
        np.testing.assert_array_equal(model["targets"], estimator.targets)
        self.assertEqual(model["periods"][0]["known_overlap"], int(data.kmask_dist(0).sum()))
        self.assertEqual(model["periods"][0]["conditional_target_distance"], data.observed_distance(0))

        # Keeping final networks changes only returned diagnostics. Each fit
        # starts with its own fresh seed; neither is fed precomputed results.
        upstream = estimator.estimate(verbose=False, return_deps=True)
        report = fit_partial_network_saom(panel, **_SETTINGS)
        self.assertEqual(report["kind"], "PARTIAL_NETWORK_SAOM_FIT")
        self.assertTrue(report["model_fitted"])
        self.assertEqual(report["engine_version"], version("cusna"))
        self.assertEqual(report["backend"], upstream.backend)
        self.assertTrue(report["conditional"])
        self.assertTrue(upstream.conditional)
        self.assertEqual(report["effect_names"], upstream.param_names)
        for key, values in (("estimates", upstream.theta), ("standard_errors", upstream.se),
                            ("tconv", upstream.tconv), ("rate_est", upstream.rate_est),
                            ("rate_sd", upstream.rate_sd), ("theta_trace", upstream.theta_trace)):
            np.testing.assert_allclose(report[key], values, rtol=1e-9, atol=1e-9)
            self.assertTrue(np.isfinite(report[key]).all())
        self.assertAlmostEqual(report["tconv_max"], upstream.tconv_max, places=9)
        for field in ("targets", "sim_means", "D", "msf"):
            np.testing.assert_allclose(report["diagnostics"][field], getattr(upstream, field),
                                       rtol=1e-9, atol=1e-9)
        for name, matrix in (("derivative", upstream.D), ("statistic_covariance", upstream.msf)):
            self.assertEqual(report["diagnostics"][name + "_rank"], np.linalg.matrix_rank(matrix))
            self.assertEqual(report["diagnostics"][name + "_rank"], 3)
            self.assertAlmostEqual(report["diagnostics"][name + "_condition_number"],
                                   np.linalg.cond(matrix), places=9)
        self.assertEqual(report["max_abs_tconv"], float(np.max(np.abs(upstream.tconv))))
        converged = bool(np.max(np.abs(upstream.tconv)) < 0.1 and 0 <= upstream.tconv_max < 0.25)
        self.assertEqual(report["convergence_is_validated"], converged)
        self.assertEqual(report["convergence_status"], "CONVERGED" if converged else "NOT_CONVERGED")
        self.assertEqual(report["convergence_scope"], "numerical moment matching only")
        self.assertEqual(report["n_simulations"], upstream.n_sims)
        self.assertEqual(report["n_simulations"], 576)
        self.assertEqual(report["n_simulations_unit"], "full-panel replicates")
        for index, final_networks in enumerate(estimator.last_deps):
            reached = ((final_networks != data.imputed[index]) & data.kmask_dist(index)).sum(axis=(1, 2))
            np.testing.assert_array_equal(reached, np.full(_SETTINGS["n3"], data.observed_distance(index)))
        audit = report["cpu_path_audit"]
        self.assertTrue(audit["all_paths_reached_target"])
        self.assertEqual(audit["step_cap"], MAX_STEPS)
        self.assertEqual(audit["total_period_paths"], upstream.n_sims * data.n_periods)
        self.assertEqual(len(audit["periods"]), data.n_periods)
        for index, period in enumerate(audit["periods"]):
            self.assertEqual(period["period_index"], index)
            self.assertEqual(period["target_distance"], data.observed_distance(index))
            self.assertEqual(period["path_count"], upstream.n_sims)
            self.assertEqual(period["batch_calls"], 2 + estimator.nsub + sum(estimator.n2))
            self.assertGreaterEqual(period["max_steps"], period["target_distance"])
            self.assertLess(period["max_steps"], MAX_STEPS)
            self.assertGreater(period["min_duration"], 0)
            self.assertGreaterEqual(period["max_duration"], period["min_duration"])
        for key, value in _SETTINGS.items():
            self.assertEqual(report[key], list(value) if key == "n2" else value)
        for key in ("firstg", "nsub", "diagonalize", "maxdegree"):
            self.assertEqual(report["algorithm_settings"][key], getattr(estimator, key))
        np.testing.assert_array_equal(report["algorithm_settings"]["initial_theta"], upstream.theta_trace[0])
        self.assertEqual(report["dataset_hash"], panel.content_hash)
        self.assertEqual(report["runtime_versions"]["numpy"], version("numpy"))
        self.assertEqual(report["runtime_versions"]["numba"], version("numba"))
        self.assertIn("not standard error", report["rate_sd_meaning"])
        for key in ("source_claim_verified", "population_boundary_qualified", "empirical_admitted",
                    "independent_reference_validated", "causal_effect_identified", "behavior_coevolution_fitted"):
            self.assertFalse(report[key])
        self.assertFalse(report["missingness_policy"]["missingness_mechanism_modeled"])
        self.assertFalse(report["missingness_policy"]["source_observations_reclassified"])
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
