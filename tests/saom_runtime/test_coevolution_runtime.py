"""Opt-in joint CPU integration against the genuine pinned cusna estimator.

The invented behavior values exercise the adapter, not an empirical model.
No upstream result is replaced or fabricated. Run with the optional [saom]
dependencies: python -m unittest discover -s tests/saom_runtime -v
"""

from contextlib import redirect_stdout
from importlib.metadata import version
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from cusna.saom.data import SaomData, synthetic_panel
from cusna.saom.cpu import MAX_STEPS
from cusna.saom.mom import MomEstimator
from cusna.saom.stats import BehEffectSpec, EffectSpec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sociolab.cli import main
from sociolab.coevolution import coevolution_model_report, fit_coevolution_saom
from sociolab.coevolution_input import CoevolutionSpec
from sociolab.panels import LongitudinalPanel


_SETTINGS = {
    "seed": 1234, "n1": 64, "nD": 64, "n3": 128,
    "batch2": 16, "n2": (2, 2, 2, 2),
}
_NETWORK_EFFECTS = ("density", "recip", "transTrip", "altX", "egoX", "simX")
_BEHAVIOR_EFFECTS = ("linear", "quad", "avSim")


def _panel(waves, behavior, dataset_id):
    actors = [f"actor-{i:03d}" for i in range(waves[0].shape[0])]
    return LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1",
        "dataset_id": dataset_id, "origin": "synthetic", "source_reference": None,
        "actors": actors, "relation": "directed_observed_social_tie",
        "behavior_variable": "invented_ordinal_measurement",
        "waves": [
            {
                "time_index": t, "source_revision": f"wave-{t}",
                "network_complete": True,
                "edges": [[actors[i], actors[j]]
                          for i in range(len(actors))
                          for j in range(len(actors)) if wave[i, j]],
                "behavior": {actor: int(behavior[i, t]) for i, actor in enumerate(actors)},
            }
            for t, wave in enumerate(waves)
        ],
    })


def _spec():
    return CoevolutionSpec(
        behavior_variable="invented_ordinal_measurement", minimum=1, maximum=5,
        measurement_reference="synthetic:unit-test/ordinal-1-5",
        research_question="Does the adapter preserve the actual upstream joint CPU result?",
    )


def _fixture():
    network = synthetic_panel(20, mean_degree=4, change_frac=0.25, seed=17)
    indices = np.arange(20)
    initial = 1 + indices % 5
    behavior = np.column_stack((initial, np.clip(initial + indices % 3 - 1, 1, 5)))
    panel = _panel(network.waves, behavior, "upstream-synthetic-joint-20")
    return panel, _spec(), SaomData(network.waves, behavior=behavior)


class CoevolutionRuntimeTests(unittest.TestCase):
    def test_reciprocal_directed_panel_is_rejected_before_estimation(self):
        waves = [
            np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]], dtype=np.uint8),
            np.array([[0, 1, 1], [1, 0, 0], [1, 0, 0]], dtype=np.uint8),
        ]
        behavior = np.array([[1, 2], [3, 4], [5, 5]])
        self.assertTrue(SaomData(waves, behavior=behavior).symmetric)
        panel = _panel(waves, behavior, "reciprocal-directed-joint-observations")
        for operation in (coevolution_model_report, fit_coevolution_saom):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(
                    ValueError, "directed coevolution is unsupported.*cusna infers an undirected model",
                ):
                    operation(panel, _spec())

    def test_cpu_fit_and_model_layout_match_actual_upstream(self):
        panel, spec, data = _fixture()
        self.assertFalse(data.symmetric)
        estimator = MomEstimator(
            data, effects=[EffectSpec(name, dyn=name in ("altX", "egoX", "simX"))
                           for name in _NETWORK_EFFECTS],
            beh_effects=[BehEffectSpec(name) for name in _BEHAVIOR_EFFECTS],
            backend="cpu", conditional=False, **_SETTINGS,
        )
        model = coevolution_model_report(panel, spec)
        self.assertFalse(model["behavior_coevolution_fitted"])
        self.assertEqual(model["parameter_names"], estimator.param_names)
        self.assertEqual(model["model_descriptor"]["parameter_count"], estimator.p)
        self.assertEqual(estimator.p, 11)
        layout = model["model_descriptor"]["parameter_layout"]
        self.assertEqual([item["index"] for item in layout], list(range(estimator.p)))
        self.assertEqual([item["name"] for item in layout], estimator.param_names)
        self.assertEqual([item["block"] for item in layout],
                         ["network_rate", "behavior_rate"]
                         + ["network_evaluation"] * 6 + ["behavior_evaluation"] * 3)
        np.testing.assert_allclose(model["targets"], estimator.targets, rtol=0, atol=0)
        np.testing.assert_allclose(model["initial_theta"], estimator.default_theta0(), rtol=0, atol=0)
        preprocessing = model["behavior_preprocessing"]
        for key, attribute in (("minimum", "zmin"), ("maximum", "zmax"),
                               ("range", "range"), ("overall_mean", "overall_mean"),
                               ("similarity_mean", "sim_mean")):
            self.assertEqual(preprocessing[key], getattr(data.beh, attribute))

        # The direct and adapted fits each start with a fresh seed. Inspecting
        # the separate model above consumes no RNG draws in either fit.
        upstream = estimator.estimate(verbose=False)
        report = fit_coevolution_saom(panel, spec, **_SETTINGS)
        self.assertEqual(report["kind"], "COEVOLUTION_MODEL_RESULT")
        self.assertEqual(report["engine_version"], version("cusna"))
        self.assertEqual(report["backend"], upstream.backend)
        self.assertFalse(report["conditional"])
        self.assertFalse(upstream.conditional)
        self.assertIsNone(upstream.rate_est)
        self.assertIsNone(upstream.rate_sd)
        self.assertEqual(report["parameter_names"], upstream.param_names)
        self.assertEqual(report["model_descriptor"], model["model_descriptor"])
        for key, values in (("estimates", upstream.theta),
                            ("standard_errors", upstream.se), ("tconv", upstream.tconv),
                            ("theta_trace", upstream.theta_trace)):
            np.testing.assert_allclose(report[key], values, rtol=1e-9, atol=1e-9)
        self.assertAlmostEqual(report["tconv_max"], upstream.tconv_max, places=9)
        for key in ("targets", "sim_means", "D", "msf"):
            np.testing.assert_allclose(report["diagnostics"][key], getattr(upstream, key),
                                       rtol=1e-9, atol=1e-9)
        for name, matrix in (("derivative", upstream.D), ("statistic_covariance", upstream.msf)):
            self.assertEqual(report["diagnostics"][name + "_rank"], np.linalg.matrix_rank(matrix))
            self.assertEqual(report["diagnostics"][name + "_rank"], estimator.p)
            self.assertAlmostEqual(report["diagnostics"][name + "_condition_number"],
                                   np.linalg.cond(matrix), places=9)
        self.assertEqual(report["max_abs_tconv"], float(np.max(np.abs(upstream.tconv))))
        converged = bool(np.max(np.abs(upstream.tconv)) < 0.1 and 0 <= upstream.tconv_max < 0.25)
        self.assertEqual(report["convergence_is_validated"], converged)
        self.assertEqual(report["convergence_status"], "CONVERGED" if converged else "NOT_CONVERGED")
        self.assertEqual(report["convergence_scope"], "numerical moment matching only")
        self.assertEqual(report["period_rates"], [{
            "period": 1, "from_time_index": 0, "to_time_index": 1,
            "network": {"parameter_index": 0, "estimate": float(upstream.theta[0]),
                        "standard_error": float(upstream.se[0])},
            "behavior": {"parameter_index": 1, "estimate": float(upstream.theta[1]),
                         "standard_error": float(upstream.se[1])},
        }])
        self.assertTrue(np.all(np.asarray(report["theta_trace"])[:, :2] > 0))
        self.assertEqual(report["n_simulations"], upstream.n_sims)
        self.assertEqual(report["n_simulations"], 576)
        self.assertEqual(report["n_simulations_unit"], "full-panel replicates")
        audit = report["simulation_diagnostics"]
        self.assertEqual(audit["period_paths_checked"], upstream.n_sims * estimator.P)
        self.assertEqual(audit["batch_calls"], (2 + estimator.nsub + sum(estimator.n2)) * estimator.P)
        self.assertEqual(audit["kernel_step_limit"], MAX_STEPS)
        self.assertFalse(audit["truncated_paths_detected"])
        self.assertEqual(len(audit["max_steps_by_period"]), estimator.P)
        self.assertEqual(audit["max_steps_per_path"], max(audit["max_steps_by_period"]))
        self.assertGreater(audit["max_steps_per_path"], 0)
        self.assertLess(audit["max_steps_per_path"], MAX_STEPS)
        for key, value in _SETTINGS.items():
            self.assertEqual(report[key], list(value) if key == "n2" else value)
        for key in ("firstg", "nsub", "diagonalize", "maxdegree"):
            self.assertEqual(report["algorithm_settings"][key], getattr(estimator, key))
        self.assertEqual(report["dataset_hash"], panel.content_hash)
        self.assertEqual(report["specification_hash"], spec.content_hash)
        self.assertEqual(report["runtime_versions"]["numpy"], version("numpy"))
        self.assertEqual(report["runtime_versions"]["numba"], version("numba"))
        self.assertTrue(report["behavior_coevolution_fitted"])
        for key in ("source_claim_verified", "independent_reference_validated",
                    "population_boundary_qualified", "empirical_model_qualified",
                    "forecast_validated", "causal_effect_identified"):
            self.assertFalse(report[key])
        json.dumps(report, allow_nan=False)

    def test_actual_cli_fit_emits_json_with_numerical_exit_status(self):
        panel, spec, _ = _fixture()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            panel_path = Path(directory) / "panel.json"
            spec_path = Path(directory) / "specification.json"
            panel_path.write_text(json.dumps(panel.to_dict()), encoding="utf-8")
            spec_path.write_text(json.dumps(spec.to_dict()), encoding="utf-8")
            with redirect_stdout(output):
                status = main([
                    "coevolution", "fit", str(panel_path), str(spec_path),
                    "--seed", "1234", "--n1", "64", "--nd", "64", "--n3", "128",
                    "--batch2", "16", "--n2", "2", "2", "2", "2",
                ])
        report = json.loads(output.getvalue())
        self.assertEqual(status, 0 if report["convergence_is_validated"] else 2)
        self.assertEqual(report["kind"], "COEVOLUTION_MODEL_RESULT")
        self.assertFalse(report["conditional"])
        self.assertTrue(report["behavior_coevolution_fitted"])
        self.assertFalse(report["independent_reference_validated"])
        self.assertFalse(report["forecast_validated"])
        self.assertFalse(report["causal_effect_identified"])
        self.assertEqual(report["dataset_hash"], panel.content_hash)
        self.assertEqual(report["specification_hash"], spec.content_hash)
        self.assertEqual(report["model_descriptor"]["parameter_count"], 11)
        self.assertEqual(report["n_simulations"], 576)
        self.assertEqual(report["simulation_diagnostics"]["period_paths_checked"], 576)
        self.assertEqual(np.asarray(report["diagnostics"]["D"]).shape, (11, 11))
        self.assertEqual(np.asarray(report["diagnostics"]["msf"]).shape, (11, 11))


if __name__ == "__main__":
    unittest.main()
