"""Small synthetic checks of the strict temporal forecast/scoring boundary."""

from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import networkx as nx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.behavior_forecast import (
    load_behavior_forecast,
    load_behavior_forecast_spec,
    load_behavior_target,
    make_behavior_forecast,
    score_behavior_forecast,
)
from sociolab.panels import LongitudinalPanel


ACTORS = tuple(f"private_actor_{letter}" for letter in "abcd")


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + sha256(raw.encode("utf-8")).hexdigest()


def rehash(artifact):
    artifact["content_hash"] = canonical_hash({key: value for key, value in artifact.items() if key != "content_hash"})
    return artifact


def panel(values=((1, 2, 3, 4), (3, 2, 5, 5)), edges=None, times=None, actors=ACTORS, complete=True):
    if edges is None:
        edges = (((actors[0], actors[1]), (actors[1], actors[0]), (actors[2], actors[3])),
                 ((actors[0], actors[2]), (actors[1], actors[0]), (actors[3], actors[1])))
    if times is None:
        times = tuple(range(len(values)))
    return LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1", "dataset_id": "synthetic-prefix-fixture",
        "origin": "synthetic", "source_reference": None, "actors": list(actors),
        "relation": "directed_observed_social_tie", "behavior_variable": "synthetic_level",
        "waves": [{"time_index": time, "source_revision": f"wave-{time}", "network_complete": complete,
                   "edges": [list(edge) for edge in sorted(wave_edges)], "behavior": dict(zip(actors, wave_values))}
                  for time, wave_values, wave_edges in zip(times, values, edges)],
    })


def specification():
    return {
        "schema": "sociolab.behavior-forecast.v1", "profile": "own-lag-outgoing-gap-ols-v1",
        "behavior": {"variable": "synthetic_level", "minimum": 0, "maximum": 5,
                     "measurement_reference": "Six synthetic integer levels; endpoints need not appear in history."},
        "target_time_index": 2, "research_question": "Does the outgoing-neighbor gap add held-out predictive information?",
    }


def target(values=(4, 3, 5, 2)):
    return {
        "schema": "sociolab.behavior-target.v1", "dataset_id": "synthetic-prefix-fixture",
        "origin": "synthetic", "source_reference": None, "behavior_variable": "synthetic_level",
        "time_index": 2, "source_revision": "target-observation-v1", "behavior": dict(zip(ACTORS, values)),
    }


class BehaviorForecastTests(unittest.TestCase):
    def assertNumbersAlmostEqual(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for left, right in zip(actual, expected):
            self.assertAlmostEqual(left, right, places=11)

    def test_exact_synthetic_golden_forecasts_and_aggregate_scores(self):
        artifact = make_behavior_forecast(panel(), specification())
        self.assertEqual(artifact["history"]["content_hash"], panel().content_hash)
        self.assertEqual(artifact["history"]["wave_time_indices"], [0, 1])
        self.assertEqual(artifact["training"]["row_count"], 4)
        models = artifact["models"]
        self.assertEqual(models["persistence"]["raw_predictions"], [3.0, 2.0, 5.0, 5.0])
        self.assertNumbersAlmostEqual(models["own_lag_ols"]["coefficients"], [1.5, 0.9])
        self.assertNumbersAlmostEqual(models["network_lag_ols"]["coefficients"], [1.0, 1.0, 1.0])
        self.assertNumbersAlmostEqual(models["own_lag_ols"]["raw_predictions"], [4.2, 3.3, 6.0, 6.0])
        self.assertNumbersAlmostEqual(models["network_lag_ols"]["raw_predictions"], [6.0, 4.0, 6.0, 3.0])
        self.assertNumbersAlmostEqual(models["own_lag_ols"]["clipped_predictions"], [4.2, 3.3, 5.0, 5.0])
        self.assertNumbersAlmostEqual(models["network_lag_ols"]["clipped_predictions"], [5.0, 4.0, 5.0, 3.0])
        self.assertEqual(models["own_lag_ols"]["clipping_count"], 2)
        self.assertEqual(models["network_lag_ols"]["clipping_count"], 2)
        score = score_behavior_forecast(artifact, target())
        expected = {
            "persistence": ((1.25, math.sqrt(2.75)), (1.25, math.sqrt(2.75))),
            "own_lag_ols": ((1.375, math.sqrt(4.2825)), (0.875, math.sqrt(2.2825))),
            "network_lag_ols": ((1.25, math.sqrt(1.75)), (0.75, math.sqrt(0.75))),
        }
        for name, variants in expected.items():
            self.assertEqual(score["models"][name]["n_evaluated"], 4)
            for variant, (mae, rmse) in zip(("raw", "clipped"), variants):
                self.assertAlmostEqual(score["models"][name][variant]["mae"], mae)
                self.assertAlmostEqual(score["models"][name][variant]["rmse"], rmse)
        self.assertAlmostEqual(score["comparisons"]["network_vs_own"]["clipped"]["mae_difference"], -0.125)
        self.assertAlmostEqual(score["comparisons"]["network_vs_persistence"]["clipped"]["mae_difference"], -0.5)
        self.assertEqual(score["target_behavior_hash"], canonical_hash(target()))

    def test_actual_numpy_and_networkx_calls_direction_and_isolate_convention(self):
        real_lstsq, real_successors = np.linalg.lstsq, nx.DiGraph.successors
        with patch.object(np.linalg, "lstsq", wraps=real_lstsq) as solver, \
                patch.object(nx.DiGraph, "successors", autospec=True, side_effect=real_successors) as successors:
            artifact = make_behavior_forecast(panel(), specification())
        self.assertEqual(solver.call_count, 2)
        self.assertEqual(successors.call_count, 8)
        for call in solver.call_args_list:
            self.assertEqual(call.kwargs, {"rcond": None})
        own = [[1.0, 1.0], [1.0, 2.0], [1.0, 3.0], [1.0, 4.0]]
        network = [[1.0, 1.0, 1.0], [1.0, 2.0, -1.0], [1.0, 3.0, 1.0], [1.0, 4.0, 0.0]]
        last_network = [[1.0, 3.0, 2.0], [1.0, 2.0, 1.0], [1.0, 5.0, 0.0], [1.0, 5.0, -3.0]]
        self.assertEqual(artifact["training"]["feature_hashes"]["own_lag_ols"], canonical_hash(own))
        self.assertEqual(artifact["training"]["feature_hashes"]["network_lag_ols"], canonical_hash(network))
        self.assertEqual(artifact["forecast_input_hashes"]["network_lag_ols"], canonical_hash(last_network))
        self.assertEqual(artifact["training"]["label_hash"], canonical_hash([3.0, 2.0, 5.0, 5.0]))
        self.assertEqual(solver.call_args_list[1].args[0].tolist(), network)
        self.assertEqual(artifact["scope"]["no_outgoing_neighbor_gap"], 0.0)
        self.assertFalse(artifact["scope"]["behavior_imputation"])

    def test_multiple_transitions_are_pooled_transition_then_actor_order(self):
        values = ((1, 2, 3, 4), (3, 2, 5, 5), (4, 3, 5, 2))
        history = panel(values=values, edges=((), (), ()), times=(2, 4, 6))
        spec = specification()
        spec["target_time_index"] = 8
        artifact = make_behavior_forecast(history, spec)
        self.assertEqual(artifact["training"]["row_count"], 8)
        self.assertEqual(artifact["history"]["wave_gap"], 2)
        own = [[1.0, float(value)] for row in values[:-1] for value in row]
        labels = [float(value) for row in values[1:] for value in row]
        self.assertEqual(artifact["training"]["feature_hashes"]["own_lag_ols"], canonical_hash(own))
        self.assertEqual(artifact["training"]["label_hash"], canonical_hash(labels))
        self.assertEqual(artifact["models"]["persistence"]["raw_predictions"], list(values[-1]))

    def test_issuer_rejects_future_wave_or_wrong_gap_before_graph_or_solver(self):
        future_panel = panel(values=((1, 2, 3, 4), (3, 2, 5, 5), (4, 3, 5, 2)), edges=((), (), ()))
        uneven = panel(values=((1, 2, 3, 4), (3, 2, 5, 5), (4, 3, 5, 2)), edges=((), (), ()), times=(0, 2, 5))
        for history, forecast_spec in ((future_panel, specification()), (uneven, specification())):
            with self.subTest(times=[wave.time_index for wave in history.waves]), \
                    patch.object(nx, "DiGraph") as graph, patch.object(np.linalg, "lstsq") as solver:
                with self.assertRaises(ValueError):
                    make_behavior_forecast(history, forecast_spec)
                graph.assert_not_called()
                solver.assert_not_called()
        for time in (0, 1, 3):
            spec = specification()
            spec["target_time_index"] = time
            with self.assertRaisesRegex(ValueError, "next wave"):
                make_behavior_forecast(panel(), spec)

    def test_hidden_target_changes_cannot_change_an_issued_forecast(self):
        history, spec = panel(), specification()
        first = make_behavior_forecast(history, spec)
        changed_target = target((0, 0, 0, 0))
        changed_target["source_revision"] = "separate-future-observation"
        before = deepcopy(first)
        initial_score = score_behavior_forecast(first, target())
        changed_score = score_behavior_forecast(first, changed_target)
        self.assertEqual(first, before)
        self.assertEqual(first, make_behavior_forecast(history, spec))
        self.assertEqual(initial_score["forecast_hash"], changed_score["forecast_hash"])
        self.assertNotEqual(initial_score["target_behavior_hash"], changed_score["target_behavior_hash"])
        self.assertNotEqual(initial_score["models"], changed_score["models"])
        with self.assertRaises(TypeError):
            make_behavior_forecast(history, spec, target=changed_target)

    def test_inputs_are_not_mutated_and_returned_spec_does_not_alias_input(self):
        history, spec, observed = panel(), specification(), target()
        before_history, before_spec, before_target = history.to_dict(), deepcopy(spec), deepcopy(observed)
        artifact = make_behavior_forecast(history, spec)
        before_artifact = deepcopy(artifact)
        score_behavior_forecast(artifact, observed)
        self.assertEqual(history.to_dict(), before_history)
        self.assertEqual(spec, before_spec)
        self.assertEqual(observed, before_target)
        self.assertEqual(artifact, before_artifact)
        artifact["specification"]["behavior"]["maximum"] = 7
        self.assertEqual(spec, before_spec)

    def test_rank_deficiency_retains_persistence_and_diagnostics_without_predictions(self):
        history = panel(edges=((), ()))
        artifact = make_behavior_forecast(history, specification())
        self.assertEqual(artifact["models"]["own_lag_ols"]["status"], "OK")
        network = artifact["models"]["network_lag_ols"]
        self.assertEqual(network["status"], "NOT_ESTIMABLE")
        self.assertEqual(network["reason"], "rank_deficient_training_design")
        self.assertEqual(network["rank"], 2)
        self.assertEqual(len(network["coefficients"]), 3)
        self.assertIsNone(network["raw_predictions"])
        self.assertIsNone(network["clipped_predictions"])
        self.assertIsNone(network["clipping_count"])
        self.assertIsNone(network["condition_number"])
        score = score_behavior_forecast(artifact, target())
        self.assertEqual(score["models"]["persistence"]["n_evaluated"], 4)
        self.assertEqual(score["models"]["network_lag_ols"]["n_evaluated"], 0)
        for comparison in score["comparisons"].values():
            self.assertEqual(comparison["status"], "NOT_ESTIMABLE")
            self.assertEqual(comparison["n_evaluated"], 0)
            self.assertIsNone(comparison["clipped"])
        constant = make_behavior_forecast(panel(values=((2, 2, 2, 2), (2, 2, 2, 2)), edges=((), ())), specification())
        self.assertEqual(constant["models"]["persistence"]["status"], "OK")
        self.assertEqual(constant["models"]["own_lag_ols"]["reason"], "rank_deficient_training_design")
        self.assertEqual(constant["models"]["network_lag_ols"]["reason"], "rank_deficient_training_design")

    def test_training_rows_must_exceed_column_count(self):
        for n in (2, 3):
            actors = ACTORS[:n]
            history = panel(values=(tuple(range(1, n + 1)), tuple(range(2, n + 2))),
                            actors=actors, edges=(((actors[0], actors[1]),), ()))
            artifact = make_behavior_forecast(history, specification())
            network = artifact["models"]["network_lag_ols"]
            self.assertEqual(network["status"], "NOT_ESTIMABLE")
            self.assertEqual(network["reason"], "insufficient_training_rows")
            self.assertIsNone(network["raw_predictions"])
            own = artifact["models"]["own_lag_ols"]
            self.assertEqual(own["status"], "NOT_ESTIMABLE" if n == 2 else "OK")
            if n == 2:
                self.assertEqual(own["reason"], "insufficient_training_rows")

    def test_declared_scale_does_not_require_observed_endpoints(self):
        spec = specification()
        spec["behavior"]["maximum"] = 10
        artifact = make_behavior_forecast(panel(), spec)
        self.assertEqual(artifact["models"]["network_lag_ols"]["status"], "OK")
        self.assertFalse(artifact["scope"]["scale_endpoints_required_in_history"])
        self.assertIsNone(artifact["scope"]["condition_number_threshold"])

    def test_incomplete_null_out_of_scale_and_wrong_variable_are_rejected(self):
        invalid = [panel(complete=False), panel(values=((1, None, 3, 4), (3, 2, 5, 5))),
                   panel(values=((1, 2, 3, 6), (3, 2, 5, 5)))]
        for history in invalid:
            with self.assertRaises(ValueError):
                make_behavior_forecast(history, specification())
        spec = specification()
        spec["behavior"]["variable"] = "different_variable"
        with self.assertRaises(ValueError):
            make_behavior_forecast(panel(), spec)
        with self.assertRaises(TypeError):
            make_behavior_forecast(panel().to_dict(), specification())

    def test_budgets_and_exact_spec_fields_are_checked_before_upstream_calls(self):
        many_actors = tuple(f"actor-{i:03}" for i in range(201))
        too_many_actors = panel(values=((1,) * 201, (2,) * 201), edges=((), ()), actors=many_actors)
        too_many_waves = panel(values=((1, 2, 3, 4),) * 33, edges=((),) * 33)
        for history in (too_many_actors, too_many_waves):
            with patch.object(nx, "DiGraph") as graph, patch.object(np.linalg, "lstsq") as solver:
                with self.assertRaisesRegex(ValueError, "budget"):
                    make_behavior_forecast(history, specification())
                graph.assert_not_called()
                solver.assert_not_called()
        mutations = [
            lambda value: value.update(extra="unrecognized"),
            lambda value: value.update(schema="wrong"),
            lambda value: value.update(profile="wrong"),
            lambda value: value.update(target_time_index=True),
            lambda value: value.update(research_question=" "),
            lambda value: value["behavior"].update(minimum=-1),
            lambda value: value["behavior"].update(minimum=True),
            lambda value: value["behavior"].update(maximum=0),
            lambda value: value["behavior"].update(maximum=100),
            lambda value: value["behavior"].update(maximum=5.0),
            lambda value: value["behavior"].update(minimum=2 ** 53, maximum=2 ** 53 + 2),
            lambda value: value["behavior"].update(measurement_reference=""),
        ]
        for mutate in mutations:
            spec = specification()
            mutate(spec)
            with self.assertRaises(ValueError):
                make_behavior_forecast(panel(), spec)

    def test_artifact_hash_detects_tampering_and_all_nested_contracts_are_validated(self):
        artifact = make_behavior_forecast(panel(), specification())
        tampered = deepcopy(artifact)
        tampered["models"]["network_lag_ols"]["raw_predictions"][0] += 1
        with self.assertRaisesRegex(ValueError, "content hash"):
            score_behavior_forecast(tampered, target())
        mutations = [
            lambda value: value.update(extra="unrecognized"),
            lambda value: value["actors"].reverse(),
            lambda value: value["actors"].append(value["actors"][0]),
            lambda value: value["history"].update(origin_time_index=0),
            lambda value: value["history"].update(wave_gap=0),
            lambda value: value["history"].update(wave_source_revisions=["same", "same"]),
            lambda value: value["training"].update(row_count=3),
            lambda value: value["training"]["feature_hashes"].update(network_lag_ols="not-a-hash"),
            lambda value: value["models"]["network_lag_ols"].update(status="NOT_ESTIMABLE"),
            lambda value: value["models"]["network_lag_ols"].update(rank=1),
            lambda value: value["models"]["network_lag_ols"].update(rank=True),
            lambda value: value["models"]["network_lag_ols"].update(feature_names=["intercept", "own_lag", "incoming"]),
            lambda value: value["models"]["network_lag_ols"].update(condition_number=1.0),
            lambda value: value["models"]["network_lag_ols"].update(clipping_count=0),
            lambda value: value["models"]["network_lag_ols"]["clipped_predictions"].__setitem__(0, 3.0),
            lambda value: value["models"]["network_lag_ols"]["raw_predictions"].pop(),
            lambda value: value["models"]["persistence"].update(coefficients=[1.0]),
            lambda value: value["runtime"].update(numpy=""),
            lambda value: value["scope"].update(causal_effect_identified=True),
            lambda value: value["scope"].update(historical_as_of_availability_verified=0),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                invalid = deepcopy(artifact)
                mutate(invalid)
                rehash(invalid)
                with self.assertRaises(ValueError):
                    score_behavior_forecast(invalid, target())

    def test_nonestimable_artifact_cannot_reintroduce_predictions(self):
        artifact = make_behavior_forecast(panel(edges=((), ())), specification())
        artifact["models"]["network_lag_ols"]["raw_predictions"] = [1.0] * 4
        rehash(artifact)
        with self.assertRaisesRegex(ValueError, "not estimable"):
            score_behavior_forecast(artifact, target())

    def test_target_must_match_every_contract_field_and_the_full_roster(self):
        artifact = make_behavior_forecast(panel(), specification())
        mutations = [
            lambda value: value.update(schema="wrong"),
            lambda value: value.update(dataset_id="another-dataset"),
            lambda value: value.update(behavior_variable="another-variable"),
            lambda value: value.update(time_index=1),
            lambda value: value.update(time_index=True),
            lambda value: value.update(source_revision=" "),
            lambda value: value.update(origin="external_observation", source_reference="https://example.invalid/source"),
            lambda value: value.update(source_reference="https://example.invalid/source"),
            lambda value: value.update(edges=[]),
            lambda value: value["behavior"].pop(ACTORS[0]),
            lambda value: value["behavior"].update(unknown_actor=2),
            lambda value: value["behavior"].update({ACTORS[0]: None}),
            lambda value: value["behavior"].update({ACTORS[0]: True}),
            lambda value: value["behavior"].update({ACTORS[0]: 2.0}),
            lambda value: value["behavior"].update({ACTORS[0]: 6}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                observed = target()
                mutate(observed)
                with self.assertRaises(ValueError):
                    score_behavior_forecast(artifact, observed)

    def test_external_source_reference_must_match_without_relaxing_receipt_claims(self):
        raw_history = panel().to_dict()
        raw_history.update(origin="external_observation", source_reference="https://example.invalid/study")
        artifact = make_behavior_forecast(LongitudinalPanel.from_mapping(raw_history), specification())
        observed = target()
        observed.update(origin="external_observation", source_reference="https://example.invalid/study")
        score = score_behavior_forecast(artifact, observed)
        self.assertEqual(score["scope"]["historical_receipt_availability"], "unknown")
        self.assertFalse(score["scope"]["historical_as_of_availability_verified"])
        self.assertFalse(score["scope"]["population_boundary_qualified"])
        observed["source_reference"] = "https://example.invalid/another-study"
        with self.assertRaisesRegex(ValueError, "source_reference"):
            score_behavior_forecast(artifact, observed)

    def test_aggregate_output_contains_no_actor_records_or_target_values(self):
        artifact = make_behavior_forecast(panel(), specification())
        score = score_behavior_forecast(artifact, target())
        serialized = json.dumps(score)
        for actor in ACTORS:
            self.assertNotIn(actor, serialized)
        forbidden = {"actors", "behavior", "raw_predictions", "clipped_predictions", "row_errors", "coefficients"}

        def check_keys(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value))
                for nested in value.values():
                    check_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    check_keys(nested)

        check_keys(score)
        for flag in ("causal_effect_identified", "empirical_forecast_validated", "probabilistic_forecast",
                     "content_hash_authenticates_author", "content_hash_proves_prospective_timestamp"):
            self.assertFalse(score["scope"][flag])
        self.assertEqual(score["metrics"]["rounding"], "none")
        self.assertNotIn("target_behavior_hash", artifact)
        self.assertNotIn("timestamp", artifact)
        self.assertNotIn("archive_hash", artifact)

    def test_loaders_round_trip_and_reject_duplicate_keys_and_nonfinite_artifacts(self):
        artifact, spec, observed = make_behavior_forecast(panel(), specification()), specification(), target()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for name, value, loader in (("artifact", artifact, load_behavior_forecast),
                                        ("spec", spec, load_behavior_forecast_spec),
                                        ("target", observed, load_behavior_target)):
                path = base / f"{name}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                self.assertEqual(loader(path), value)
                path.write_text('{"schema":"first","schema":"second"}', encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                    loader(path)
            invalid = deepcopy(artifact)
            invalid["models"]["network_lag_ols"]["raw_predictions"][0] = float("nan")
            path = base / "nonfinite.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite"):
                load_behavior_forecast(path)


if __name__ == "__main__":
    unittest.main()
