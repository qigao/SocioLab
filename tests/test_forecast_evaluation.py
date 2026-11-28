"""Synthetic contracts for saved, immutable-prefix forecast evaluation."""

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

from sociolab.behavior_forecast import make_behavior_forecast, score_behavior_forecast
from sociolab.forecast_evaluation import (
    evaluate_behavior_forecasts,
    load_behavior_forecast_plan,
    make_behavior_forecast_plan,
)
from sociolab.panels import LongitudinalPanel


ACTORS = tuple(f"retained_private_actor_{letter}" for letter in "abcd")


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + sha256(raw.encode("utf-8")).hexdigest()


def rehash(value):
    value["content_hash"] = canonical_hash({key: item for key, item in value.items() if key != "content_hash"})
    return value


def spec(target_time=2):
    return {
        "schema": "sociolab.behavior-forecast.v1", "profile": "own-lag-outgoing-gap-ols-v1",
        "behavior": {"variable": "invented_level", "minimum": 0, "maximum": 10,
                     "measurement_reference": "Synthetic declared integer scale 0 through 10."},
        "target_time_index": target_time,
        "research_question": "Does the fixed outgoing gap improve held-out next-wave prediction?",
    }


def history(wave_count=2, *, values=None, edges=None, times=None, actors=ACTORS):
    if values is None:
        values = ((1, 2, 3, 4), (3, 2, 5, 5), (3, 2, 5, 5), (5, 4, 7, 7))
    if edges is None:
        edges = (
            ((actors[0], actors[1]), (actors[1], actors[0]), (actors[2], actors[3])),
            ((actors[0], actors[2]), (actors[1], actors[0]), (actors[3], actors[1])),
            ((actors[0], actors[3]), (actors[2], actors[1]), (actors[3], actors[0])),
            (),
        )
    if times is None:
        times = list(range(wave_count))
    return LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1", "dataset_id": "invented-rolling-fixture",
        "origin": "synthetic", "source_reference": None, "actors": list(actors),
        "relation": "directed_observed_social_tie", "behavior_variable": "invented_level",
        "waves": [{"time_index": times[index], "source_revision": f"network-and-behavior-{times[index]}",
                   "network_complete": True, "edges": [list(edge) for edge in sorted(edges[index])],
                   "behavior": dict(zip(actors, values[index]))} for index in range(wave_count)],
    })


def target(time, values, actors=ACTORS):
    return {
        "schema": "sociolab.behavior-target.v1", "dataset_id": "invented-rolling-fixture",
        "origin": "synthetic", "source_reference": None, "behavior_variable": "invented_level",
        "time_index": time, "source_revision": f"behavior-only-{time}", "behavior": dict(zip(actors, values)),
    }


def fixture(*, values=None, edges=None):
    if values is None:
        values = ((1, 2, 3, 4), (3, 2, 5, 5), (3, 2, 5, 5), (5, 4, 7, 7))
    first = history(2, values=values, edges=edges)
    plan = make_behavior_forecast_plan(first, spec(), [2, 3])
    folds = []
    for count in (2, 3):
        prefix = history(count, values=values, edges=edges)
        folds.append({"history": prefix, "forecast": make_behavior_forecast(prefix, spec(count)),
                      "target": target(count, values[count])})
    return plan, folds


def replace_history(fold, raw_history):
    fold["history"] = LongitudinalPanel.from_mapping(raw_history)
    fold["forecast"] = make_behavior_forecast(fold["history"], spec(fold["target"]["time_index"]))


class ForecastEvaluationTests(unittest.TestCase):
    def test_plan_is_past_only_and_never_fits_or_builds_graphs(self):
        initial, specification, targets = history(), spec(), [2, 3]
        with patch.object(np.linalg, "lstsq", side_effect=AssertionError("plan must not fit")) as solver, \
                patch.object(nx, "DiGraph", side_effect=AssertionError("plan must not build graph")) as graph, \
                patch("sociolab.behavior_forecast.make_behavior_forecast", side_effect=AssertionError("no forecast issuance")):
            plan = make_behavior_forecast_plan(initial, specification, targets)
        solver.assert_not_called()
        graph.assert_not_called()
        self.assertEqual(plan["initial_history"]["content_hash"], initial.content_hash)
        self.assertEqual(plan["initial_history"]["actor_roster_hash"], canonical_hash(list(ACTORS)))
        self.assertEqual(plan["initial_history"]["actor_count"], 4)
        self.assertEqual(plan["target_time_indices"], [2, 3])
        self.assertEqual(plan["wave_gap"], 1)
        self.assertEqual(plan["content_hash"], canonical_hash({key: value for key, value in plan.items() if key != "content_hash"}))
        self.assertNotIn("target_behavior_hash", plan)
        with self.assertRaises(TypeError):
            make_behavior_forecast_plan(initial, specification, targets, target={})

    def test_hand_calculated_pooled_and_macro_losses_and_exact_denominators(self):
        plan, folds = fixture()
        report = evaluate_behavior_forecasts(plan, folds)
        self.assertEqual(report["actor_count"], 4)
        self.assertEqual(report["fold_count"], 2)
        self.assertEqual(report["actor_forecast_count"], 8)
        persistence = report["models"]["persistence"]
        for variant in ("raw", "clipped"):
            self.assertAlmostEqual(persistence[variant]["pooled"]["mae"], 1.0)
            self.assertAlmostEqual(persistence[variant]["macro"]["mae"], 1.0)
            self.assertAlmostEqual(persistence[variant]["pooled"]["rmse"], math.sqrt(2.0))
            self.assertAlmostEqual(persistence[variant]["macro"]["rmse"], 1.0)
        self.assertEqual(report["folds"][0]["score"]["models"]["persistence"]["clipped"]["rmse"], 0.0)
        self.assertEqual(report["folds"][1]["score"]["models"]["persistence"]["clipped"]["rmse"], 2.0)
        for name, model in report["models"].items():
            self.assertEqual(model["status"], "OK")
            self.assertEqual(model["expected_fold_count"], 2)
            self.assertEqual(model["available_fold_count"], 2)
            self.assertEqual(model["expected_actor_forecast_count"], 8)
            self.assertEqual(model["available_actor_forecast_count"], 8)
            self.assertEqual(model["failed_target_time_indices"], [])
            # Independently pool the retained private prediction errors, rather
            # than reusing the evaluator's fold-level loss aggregation.
            for variant in ("raw", "clipped"):
                errors = [prediction - fold["target"]["behavior"][actor]
                          for fold in folds for actor, prediction in
                          zip(fold["forecast"]["actors"], fold["forecast"]["models"][name][f"{variant}_predictions"])]
                self.assertAlmostEqual(model[variant]["pooled"]["mae"], sum(abs(error) for error in errors) / 8)
                self.assertAlmostEqual(model[variant]["pooled"]["rmse"], math.sqrt(sum(error ** 2 for error in errors) / 8))
                self.assertAlmostEqual(model[variant]["pooled"]["mae"], model[variant]["macro"]["mae"])
        for comparison, baseline in (("network_vs_own", "own_lag_ols"), ("network_vs_persistence", "persistence")):
            values = report["comparisons"][comparison]
            self.assertEqual(values["available_actor_forecast_count"], 8)
            for variant in ("raw", "clipped"):
                for aggregation in ("pooled", "macro"):
                    for metric in ("mae", "rmse"):
                        expected = (report["models"]["network_lag_ols"][variant][aggregation][metric]
                                    - report["models"][baseline][variant][aggregation][metric])
                        self.assertAlmostEqual(values[variant][aggregation][f"{metric}_difference"], expected)
        comparison = report["comparisons"]["network_vs_persistence"]["raw"]
        self.assertNotAlmostEqual(comparison["pooled"]["rmse_difference"], comparison["macro"]["rmse_difference"])

    def test_evaluation_calls_real_existing_scorer_without_refitting(self):
        plan, folds = fixture()
        with patch.object(np.linalg, "lstsq", side_effect=AssertionError("evaluation must not fit")) as solver, \
                patch.object(nx, "DiGraph", side_effect=AssertionError("evaluation must not build features")) as graph, \
                patch("sociolab.behavior_forecast.make_behavior_forecast", side_effect=AssertionError("no reissuance")), \
                patch("sociolab.forecast_evaluation.score_behavior_forecast", wraps=score_behavior_forecast) as scorer:
            report = evaluate_behavior_forecasts(plan, folds)
        solver.assert_not_called()
        graph.assert_not_called()
        self.assertEqual(scorer.call_count, 2)
        for index, audit in enumerate(report["folds"]):
            fold = folds[index]
            self.assertEqual(audit["fold_index"], index + 1)
            self.assertEqual(audit["history_prefix_hash"], fold["history"].content_hash)
            self.assertEqual(audit["forecast_hash"], fold["forecast"]["content_hash"])
            self.assertEqual(audit["score"], score_behavior_forecast(fold["forecast"], fold["target"]))
            self.assertEqual(audit["score_hash"], canonical_hash(audit["score"]))
        self.assertEqual(report["content_hash"], canonical_hash({key: value for key, value in report.items() if key != "content_hash"}))

    def test_future_changes_cannot_change_the_initial_plan_or_earlier_forecast(self):
        plan, folds = fixture()
        changed_values = ((1, 2, 3, 4), (3, 2, 5, 5), (4, 3, 6, 6), (6, 5, 8, 8))
        changed_plan, changed_folds = fixture(values=changed_values)
        self.assertEqual(plan, changed_plan)
        self.assertEqual(folds[0]["forecast"], changed_folds[0]["forecast"])
        self.assertNotEqual(folds[1]["forecast"]["content_hash"], changed_folds[1]["forecast"]["content_hash"])
        initial_hash = folds[0]["forecast"]["content_hash"]
        first = evaluate_behavior_forecasts(plan, folds)
        second = evaluate_behavior_forecasts(changed_plan, changed_folds)
        self.assertEqual(first["folds"][0]["forecast_hash"], second["folds"][0]["forecast_hash"])
        self.assertNotEqual(first["folds"][0]["score_hash"], second["folds"][0]["score_hash"])
        self.assertEqual(folds[0]["forecast"]["content_hash"], initial_hash)
        with self.assertRaisesRegex(ValueError, "immediately follow"):
            make_behavior_forecast_plan(history(3), spec(), [2, 3])

    def test_rank_failure_in_one_fold_is_retained_and_never_silently_dropped(self):
        edges = ((), ((ACTORS[0], ACTORS[2]), (ACTORS[1], ACTORS[0]), (ACTORS[3], ACTORS[1])), (), ())
        plan, folds = fixture(edges=edges)
        self.assertEqual(folds[0]["forecast"]["models"]["network_lag_ols"]["status"], "NOT_ESTIMABLE")
        self.assertEqual(folds[1]["forecast"]["models"]["network_lag_ols"]["status"], "OK")
        report = evaluate_behavior_forecasts(plan, folds)
        self.assertEqual(len(report["folds"]), 2)
        self.assertEqual(report["actor_forecast_count"], 8)
        network = report["models"]["network_lag_ols"]
        self.assertEqual(network["status"], "NOT_ESTIMABLE")
        self.assertEqual(network["available_fold_count"], 1)
        self.assertEqual(network["expected_fold_count"], 2)
        self.assertEqual(network["available_actor_forecast_count"], 4)
        self.assertEqual(network["expected_actor_forecast_count"], 8)
        self.assertEqual(network["failed_target_time_indices"], [2])
        self.assertIsNone(network["raw"])
        self.assertIsNone(network["clipped"])
        self.assertIsNone(network["clipping_count"])
        for baseline in ("persistence", "own_lag_ols"):
            self.assertEqual(report["models"][baseline]["status"], "OK")
            self.assertEqual(report["models"][baseline]["available_actor_forecast_count"], 8)
        for comparison in report["comparisons"].values():
            self.assertEqual(comparison["status"], "NOT_ESTIMABLE")
            self.assertEqual(comparison["available_actor_forecast_count"], 4)
            self.assertEqual(comparison["failed_target_time_indices"], [2])
            self.assertIsNone(comparison["raw"])
            self.assertIsNone(comparison["clipped"])

    def test_exact_fold_coverage_and_order_are_required(self):
        plan, folds = fixture()
        invalid_lists = [[], folds[:1], folds + [folds[1]], list(reversed(folds)), [folds[0], folds[0]], tuple(folds)]
        for index, invalid in enumerate(invalid_lists):
            with self.subTest(case=index), self.assertRaises(ValueError):
                evaluate_behavior_forecasts(plan, invalid)
        for mutation in (lambda fold: fold.update(score={}), lambda fold: fold.pop("target")):
            changed = deepcopy(folds)
            mutation(changed[0])
            with self.assertRaisesRegex(ValueError, "exact fields"):
                evaluate_behavior_forecasts(plan, changed)

    def test_full_prefix_comparison_rejects_old_values_edges_and_revision_changes(self):
        plan, folds = fixture()
        changes = [
            lambda raw: raw["waves"][0]["behavior"].update({ACTORS[0]: 2}),
            lambda raw: raw["waves"][0].update(edges=[]),
            lambda raw: raw["waves"][0].update(source_revision="late-corrected-revision"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                altered = deepcopy(folds)
                raw = altered[1]["history"].to_dict()
                change(raw)
                # Reissue a structurally valid artifact for the changed history:
                # the evaluator must still reject the immutable-prefix breach.
                replace_history(altered[1], raw)
                with self.assertRaisesRegex(ValueError, "without changing"):
                    evaluate_behavior_forecasts(plan, altered)
        altered = deepcopy(folds)
        shifted = history(2, times=[1, 2])
        altered[1]["history"] = shifted
        altered[1]["forecast"] = make_behavior_forecast(shifted, spec(3))
        with self.assertRaisesRegex(ValueError, "append exactly one"):
            evaluate_behavior_forecasts(plan, altered)

    def test_appended_behavior_equals_previous_target_but_revision_names_need_not(self):
        plan, folds = fixture()
        self.assertNotEqual(folds[0]["target"]["source_revision"], folds[1]["history"].waves[-1].source_revision)
        report = evaluate_behavior_forecasts(plan, folds)
        self.assertTrue(report["scope"]["full_prefix_extension_verified"])
        self.assertTrue(report["scope"]["previous_target_matches_next_history"])
        changed = deepcopy(folds)
        raw = changed[1]["history"].to_dict()
        raw["waves"][-1]["behavior"][ACTORS[0]] = 4
        replace_history(changed[1], raw)
        with self.assertRaisesRegex(ValueError, "preceding independently scored target"):
            evaluate_behavior_forecasts(plan, changed)

    def test_first_history_and_each_forecast_must_bind_the_retained_prefix(self):
        plan, folds = fixture()
        changed = deepcopy(folds)
        raw = changed[0]["history"].to_dict()
        raw["waves"][0]["behavior"][ACTORS[0]] = 2
        replace_history(changed[0], raw)
        with self.assertRaisesRegex(ValueError, "initial history"):
            evaluate_behavior_forecasts(plan, changed)
        for mutation in (
            lambda value: value["history"].update(content_hash="sha256:" + "a" * 64),
            lambda value: value["history"]["wave_source_revisions"].__setitem__(0, "different-retained-revision"),
        ):
            changed = deepcopy(folds)
            mutation(changed[1]["forecast"])
            rehash(changed[1]["forecast"])
            with self.assertRaisesRegex(ValueError, "retained prefix"):
                evaluate_behavior_forecasts(plan, changed)
        changed = deepcopy(folds)
        changed[0]["forecast"]["models"]["persistence"]["raw_predictions"][0] = 4.0
        with self.assertRaisesRegex(ValueError, "content hash"):
            evaluate_behavior_forecasts(plan, changed)

    def test_roster_dataset_and_specification_cannot_change_between_folds(self):
        plan, folds = fixture()
        changed = deepcopy(folds)
        raw = changed[1]["history"].to_dict()
        old, new = ACTORS[0], "another_private_actor"
        raw["actors"] = sorted(new if actor == old else actor for actor in raw["actors"])
        for wave in raw["waves"]:
            wave["behavior"] = {new if actor == old else actor: value for actor, value in wave["behavior"].items()}
            wave["edges"] = sorted([[new if actor == old else actor for actor in edge] for edge in wave["edges"]])
        replace_history(changed[1], raw)
        with self.assertRaisesRegex(ValueError, "roster"):
            evaluate_behavior_forecasts(plan, changed)
        changed = deepcopy(folds)
        raw = changed[1]["history"].to_dict()
        raw["dataset_id"] = "changed-dataset"
        replace_history(changed[1], raw)
        with self.assertRaisesRegex(ValueError, "dataset and source"):
            evaluate_behavior_forecasts(plan, changed)
        for mutate in (
            lambda value: value["behavior"].update(maximum=9),
            lambda value: value["behavior"].update(measurement_reference="changed scale definition"),
            lambda value: value.update(research_question="changed after seeing the first outcome"),
        ):
            changed = deepcopy(folds)
            new_spec = spec(3)
            mutate(new_spec)
            changed[1]["forecast"] = make_behavior_forecast(changed[1]["history"], new_spec)
            with self.assertRaisesRegex(ValueError, "fixed plan specification"):
                evaluate_behavior_forecasts(plan, changed)

    def test_targets_are_revalidated_and_saved_score_input_is_not_accepted(self):
        plan, folds = fixture()
        mutations = [
            lambda value: value.update(time_index=4),
            lambda value: value.update(edges=[]),
            lambda value: value["behavior"].pop(ACTORS[0]),
            lambda value: value["behavior"].update({ACTORS[0]: None}),
            lambda value: value["behavior"].update({ACTORS[0]: 11}),
            lambda value: value.update(dataset_id="other-source"),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                changed = deepcopy(folds)
                mutation(changed[-1]["target"])
                with self.assertRaises(ValueError):
                    evaluate_behavior_forecasts(plan, changed)
        changed = deepcopy(folds)
        changed[-1]["target"] = score_behavior_forecast(changed[-1]["forecast"], changed[-1]["target"])
        with self.assertRaisesRegex(ValueError, "exact fields"):
            evaluate_behavior_forecasts(plan, changed)

    def test_plan_limits_complete_scale_and_equal_gaps_are_checked_without_fit(self):
        initial = history()
        invalid_targets = [[], [2], [2, 2], [2, 4], [3, 2], [True, 2], (2, 3), list(range(2, 34))]
        with patch.object(np.linalg, "lstsq", side_effect=AssertionError("no fit")):
            for targets in invalid_targets:
                with self.assertRaises(ValueError):
                    make_behavior_forecast_plan(initial, spec(), targets)
            largest = make_behavior_forecast_plan(initial, spec(), list(range(2, 33)))
            self.assertEqual(len(largest["target_time_indices"]), 31)
            shifted = history(2, times=[2, 4])
            shifted_plan = make_behavior_forecast_plan(shifted, spec(6), [6, 8])
            self.assertEqual(shifted_plan["wave_gap"], 2)
            invalid_histories = []
            for field, value in (("network_complete", False),):
                raw = initial.to_dict()
                raw["waves"][0][field] = value
                invalid_histories.append(LongitudinalPanel.from_mapping(raw))
            for value in (None, 11):
                raw = initial.to_dict()
                raw["waves"][0]["behavior"][ACTORS[0]] = value
                invalid_histories.append(LongitudinalPanel.from_mapping(raw))
            invalid_histories.append(history(3, times=[0, 1, 3]))
            many_actors = tuple(f"actor-{index:03}" for index in range(201))
            invalid_histories.append(history(2, values=((1,) * 201,) * 2, edges=((), ()), actors=many_actors))
            for prefix in invalid_histories:
                with self.assertRaises(ValueError):
                    make_behavior_forecast_plan(prefix, spec(), [2, 3])
        with self.assertRaises(TypeError):
            make_behavior_forecast_plan(initial.to_dict(), spec(), [2, 3])

    def test_plan_tampering_and_rehashed_invalid_contracts_are_rejected(self):
        plan, folds = fixture()
        changed = deepcopy(plan)
        changed["target_time_indices"][1] = 4
        with self.assertRaisesRegex(ValueError, "content hash"):
            evaluate_behavior_forecasts(changed, folds)
        changes = [
            lambda value: value.update(extra="unrecognized"),
            lambda value: value.update(schema="wrong"),
            lambda value: value.update(profile="adaptive-profile"),
            lambda value: value.update(wave_gap=True),
            lambda value: value.update(training_policy="allow_late_corrections"),
            lambda value: value.update(evaluation_policy="drop_failed_folds"),
            lambda value: value.update(target_time_indices=[2, 4]),
            lambda value: value["initial_history"].update(actor_count=True),
            lambda value: value["initial_history"].update(actor_count=201),
            lambda value: value["initial_history"].update(actor_roster_hash="invalid"),
            lambda value: value["initial_history"].update(wave_time_indices=[0, 0]),
            lambda value: value["initial_history"].update(wave_source_revisions=["same", "same"]),
            lambda value: value["metrics"].update(primary="rmse"),
            lambda value: value["scope"].update(forecast_issuance_before_target_observation_verified=True),
            lambda value: value["scope"].update(actor_forecast_rows_independent=0),
        ]
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                changed = deepcopy(plan)
                change(changed)
                rehash(changed)
                with self.assertRaises(ValueError):
                    evaluate_behavior_forecasts(changed, folds)

    def test_inputs_remain_unchanged_and_outputs_do_not_alias_plan_inputs(self):
        initial, specification, targets = history(), spec(), [2, 3]
        original = (initial.to_dict(), deepcopy(specification), list(targets))
        plan = make_behavior_forecast_plan(initial, specification, targets)
        self.assertEqual((initial.to_dict(), specification, targets), original)
        plan["specification"]["research_question"] = "mutated returned object"
        self.assertEqual(specification, original[1])
        plan, folds = fixture()
        before_plan, before_folds = deepcopy(plan), deepcopy(folds)
        report = evaluate_behavior_forecasts(plan, folds)
        self.assertEqual(plan, before_plan)
        self.assertEqual(folds, before_folds)
        report["dataset"]["dataset_id"] = "mutated report"
        report["target_time_indices"].append(4)
        self.assertEqual(plan, before_plan)

    def test_aggregate_privacy_and_limits_are_explicit(self):
        plan, folds = fixture()
        report = evaluate_behavior_forecasts(plan, folds)
        for value in (plan, report):
            serialized = json.dumps(value)
            for actor in ACTORS:
                self.assertNotIn(actor, serialized)
            for forbidden in ('"actors"', '"raw_predictions"', '"clipped_predictions"', '"row_errors"', '"path"'):
                self.assertNotIn(forbidden, serialized)
        scope = report["scope"]
        for flag in ("actor_forecast_rows_independent", "uncertainty_intervals", "p_values", "stability_established",
                     "causal_effect_identified", "empirical_forecast_validated", "late_revisions_in_same_plan_allowed",
                     "forecast_issuance_before_target_observation_verified", "content_hash_proves_prospective_timestamp",
                     "refitting_performed_by_evaluation", "fold_dropping", "actor_dropping"):
            self.assertFalse(scope[flag])
        self.assertEqual(scope["historical_receipt_availability"], "unknown")
        self.assertTrue(scope["full_prefix_extension_verified"])

    def test_strict_plan_loader_round_trip_duplicate_keys_and_nonfinite_content(self):
        plan = make_behavior_forecast_plan(history(), spec(), [2, 3])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            self.assertEqual(load_behavior_forecast_plan(path), plan)
            path.write_text('{"schema":"first","schema":"duplicate"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                load_behavior_forecast_plan(path)
            changed = deepcopy(plan)
            changed["wave_gap"] = float("nan")
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite"):
                load_behavior_forecast_plan(path)


if __name__ == "__main__":
    unittest.main()
