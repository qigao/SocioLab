"""Aggregate probability diagnostics on actual receipt-bound scoring rows."""

from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.events import ingest_records
from sociolab.repeat_interaction import (
    _probability_bins,
    diagnose_repeat_interaction_forecast,
    make_repeat_interaction_forecast,
    score_repeat_interaction_forecast,
)
from test_repeat_interaction import (
    A, B, C, D, ACTORS, ALIAS, LATER, MODELS, canonical_hash, coverage,
    fixture, interaction, revise, target_spec, with_target,
)


def partial_target(dataset):
    return ingest_records(dataset, [
        coverage("diagnostic-target-AB", [A, B], 10),
        coverage("diagnostic-target-CD-first", [C, D], 10, 11),
        coverage("diagnostic-target-CD-last", [C, D], 12),
        interaction("diagnostic-target-AB-positive", A, B, 10),
        interaction("diagnostic-target-CD-positive", C, D, 13),
    ], received_at=LATER)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class RepeatInteractionDiagnosticTests(unittest.TestCase):
    def assert_bin(self, row, count, predicted_sum, positive_count, squared_error_sum):
        self.assertEqual(row["count"], count)
        self.assertAlmostEqual(row["sum_predicted_probability"], predicted_sum, places=14)
        self.assertEqual(row["positive_count"], positive_count)
        self.assertAlmostEqual(row["sum_squared_error"], squared_error_sum, places=14)
        if count:
            self.assertAlmostEqual(row["mean_predicted_probability"], predicted_sum / count, places=14)
            self.assertEqual(row["observed_fraction"], positive_count / count)
            self.assertAlmostEqual(row["brier"], squared_error_sum / count, places=14)
        else:
            for key in ("mean_predicted_probability", "observed_fraction", "brier"):
                self.assertIsNone(row[key])

    def test_boundaries_zero_one_and_exact_interior_preserve_analytic_statistics(self):
        dataset, specification = fixture()
        forecast = make_repeat_interaction_forecast(dataset, specification)
        later = with_target(dataset)
        target = target_spec(later)
        # Put a boundary exactly on the saved B->A/C->D historical probability.
        # The expected counts, outcomes and probabilities below are independently
        # derived from the five fixture events and four-tick target window.
        interior = next(p for p in forecast["predictions"] if p["source"] == B)["probabilities"]["historical_poisson"]
        edges = [0, 0.2, interior, 0.5, 0.9, 1]
        before = deepcopy((forecast, target, edges, later.to_dict()))
        diagnostic = diagnose_repeat_interaction_forecast(later, forecast, target, edges)
        self.assertEqual(before, (forecast, target, edges, later.to_dict()))
        self.assertEqual(diagnostic["probability_bins"], [float(x) for x in edges])
        self.assertEqual(diagnostic["schema"], "sociolab.repeat-interaction-diagnostics.v1")
        self.assertEqual(diagnostic["kind"], "REPEAT_INTERACTION_DIAGNOSTICS")

        low = 1 - math.exp(-0.4)
        high = 1 - math.exp(-1.2)
        recent_high = 1 - math.exp(-1.6)
        recent_middle = 1 - math.exp(-0.8)
        self.assertAlmostEqual(interior, low, places=14)
        expected = {
            "historical_poisson": {
                2: (2, 2 * low, 1, (1 - low) ** 2 + low ** 2),
                3: (1, high, 1, (1 - high) ** 2),
            },
            "recent_poisson": {
                0: (1, 0, 1, 1),
                3: (2, recent_high + recent_middle, 1, (1 - recent_high) ** 2 + recent_middle ** 2),
            },
            "recent_occurrence": {0: (1, 0, 1, 1), 4: (2, 2, 1, 1)},
        }
        for model, populated in expected.items():
            rows = diagnostic["models"][model]["bins"]
            self.assertEqual(len(rows), 5)
            for index, row in enumerate(rows):
                self.assertEqual((row["lower"], row["upper"], row["upper_inclusive"]),
                                 (float(edges[index]), float(edges[index + 1]), index == 4))
                self.assert_bin(row, *populated.get(index, (0, 0, 0, 0)))
            self.assertEqual(sum(row["count"] for row in rows), 3)
            self.assertEqual(sum(row["positive_count"] for row in rows), 2)
            self.assertAlmostEqual(math.fsum(row["sum_squared_error"] for row in rows) / 3,
                                   diagnostic["score"]["models"][model]["brier"], places=14)

        self.assertEqual(diagnostic["content_hash"], canonical_hash({
            key: value for key, value in diagnostic.items() if key != "content_hash"
        }))
        text = encoded(diagnostic)
        self.assertTrue(all(actor not in text for actor in ACTORS + [ALIAS]))
        self.assertTrue(diagnostic["scope"]["descriptive_only"])
        for flag in ("calibration_fitted", "calibration_validated", "probability_calibration_validated",
                     "dependent_pairs_treated_as_iid", "contains_private_actor_records"):
            self.assertFalse(diagnostic["scope"][flag])

    def test_partial_coverage_positive_is_evidence_but_never_a_calibration_row(self):
        dataset, specification = fixture(coverage_end=10)
        forecast = make_repeat_interaction_forecast(dataset, specification)
        later = partial_target(dataset)
        diagnostic = diagnose_repeat_interaction_forecast(later, forecast, target_spec(later), [0, 0.5, 1])
        counts = diagnostic["score"]["counts"]
        self.assertEqual((counts["risk_pairs"], counts["scorable_pairs"], counts["known_positive_pairs"],
                          counts["known_positive_unscored_pairs"]), (3, 2, 2, 1))
        for model in MODELS:
            bins = diagnostic["models"][model]["bins"]
            self.assertEqual(sum(row["count"] for row in bins), 2)
            self.assertEqual(sum(row["positive_count"] for row in bins), 1)
        occurrence = diagnostic["models"]["recent_occurrence"]["bins"]
        self.assert_bin(occurrence[0], 1, 0, 0, 0)
        self.assert_bin(occurrence[1], 1, 1, 1, 0)
        historical = diagnostic["models"]["historical_poisson"]["bins"]
        low, high = 1 - math.exp(-0.4), 1 - math.exp(-1.2)
        self.assert_bin(historical[0], 1, low, 0, low ** 2)
        self.assert_bin(historical[1], 1, high, 1, (1 - high) ** 2)

    def test_immature_and_empty_risk_results_retain_all_empty_bins(self):
        for has_history_events in (True, False):
            with self.subTest(has_history_events=has_history_events):
                dataset, specification = fixture(events=has_history_events)
                forecast = make_repeat_interaction_forecast(dataset, specification)
                later = with_target(dataset)
                target = target_spec(later, through=12 if has_history_events else 14)
                diagnostic = diagnose_repeat_interaction_forecast(later, forecast, target, [0, 0.25, 0.5, 1])
                self.assertEqual(diagnostic["score"]["status"], "UNSCORED")
                self.assertEqual(diagnostic["score"]["counts"]["known_positive_pairs"], int(has_history_events))
                for model in MODELS:
                    bins = diagnostic["models"][model]["bins"]
                    self.assertEqual(len(bins), 3)
                    for row in bins:
                        self.assert_bin(row, 0, 0, 0, 0)

    def test_normalization_and_invalid_probability_boundaries(self):
        self.assertEqual(_probability_bins([0, 1]), [0.0, 1.0])
        self.assertEqual(_probability_bins([i / 20 for i in range(21)]), [i / 20 for i in range(21)])
        normalized = _probability_bins([-0.0, 0.5, 1])
        self.assertTrue(all(type(edge) is float for edge in normalized))
        self.assertEqual(math.copysign(1, normalized[0]), 1)
        invalid = [None, {}, (0, 1), [], [0], [i / 21 for i in range(22)],
                   [0, True, 1], [False, 1], [0, "0.5", 1], [0, None, 1],
                   [0, math.nan, 1], [0, math.inf, 1], [0, -math.inf, 1], [0, 10 ** 400, 1],
                   [-0.1, 1], [0.1, 1], [0, 0.9], [0, 1.1], [0, 0, 1],
                   [0, 0.7, 0.4, 1], [0, 1, 1]]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                _probability_bins(value)
        dataset, specification = fixture()
        forecast = make_repeat_interaction_forecast(dataset, specification)
        with self.assertRaisesRegex(ValueError, "booleans"):
            diagnose_repeat_interaction_forecast(dataset, forecast, target_spec(dataset), [0, True, 1])

    def test_later_target_revision_changes_diagnostics_without_rewriting_old_versions(self):
        dataset, specification = fixture()
        forecast = make_repeat_interaction_forecast(dataset, specification)
        later = with_target(dataset)
        original_target = target_spec(later)
        original = diagnose_repeat_interaction_forecast(later, forecast, original_target, [0, 0.5, 1])
        revised = revise(later, "future-BA", "corrected-future-BA", when=15)
        current = diagnose_repeat_interaction_forecast(revised, forecast, target_spec(revised), [0, 0.5, 1])
        self.assertEqual(original["score"]["counts"]["scorable_positive_pairs"], 2)
        self.assertEqual(current["score"]["counts"]["scorable_positive_pairs"], 1)
        self.assertNotEqual(original["content_hash"], current["content_hash"])
        self.assertEqual(encoded(original), encoded(diagnose_repeat_interaction_forecast(
            revised, forecast, original_target, [0, 0.5, 1]
        )))
        self.assertEqual(encoded(forecast), encoded(make_repeat_interaction_forecast(revised, specification)))
        occurrence = current["models"]["recent_occurrence"]["bins"]
        self.assert_bin(occurrence[0], 1, 0, 0, 0)
        self.assert_bin(occurrence[1], 2, 2, 1, 1)

    def test_diagnostic_entry_point_rejects_rehashed_prediction_tampering(self):
        dataset, specification = fixture()
        forecast = make_repeat_interaction_forecast(dataset, specification)
        later = with_target(dataset)
        forecast["predictions"][0]["probabilities"]["historical_poisson"] = 0.123
        forecast["content_hash"] = canonical_hash({key: value for key, value in forecast.items() if key != "content_hash"})
        with self.assertRaisesRegex(ValueError, "does not match its original"):
            diagnose_repeat_interaction_forecast(later, forecast, target_spec(later), [0, 1])

    def test_existing_v1_scores_keep_their_pre_refactor_identity(self):
        dataset, specification = fixture()
        forecast = make_repeat_interaction_forecast(dataset, specification)
        later = with_target(dataset)
        cases = [
            (later, forecast, target_spec(later), "sha256:8d501a4c6ff850603a6d058556020ddac95587e4049ff1cd1af44c32627a3919"),
            (later, forecast, target_spec(later, through=12), "sha256:d11954c829edb58d257f0340f7852a03cde0bba723c4d83508eb733e85395f60"),
        ]
        dataset, specification = fixture(coverage_end=10)
        forecast = make_repeat_interaction_forecast(dataset, specification)
        later = partial_target(dataset)
        cases.append((later, forecast, target_spec(later), "sha256:8562e704e6fb412524001d09b61a6dd75f74fa4149134012f24daa4a7d1833da"))
        dataset, specification = fixture(events=False)
        forecast = make_repeat_interaction_forecast(dataset, specification)
        cases.append((dataset, forecast, target_spec(dataset), "sha256:3ad28a53fa11547fc353939f62a12397620d465aedbd63adac87d512ec0a44ba"))
        for dataset, forecast, target, expected_hash in cases:
            with self.subTest(expected_hash=expected_hash):
                score = score_repeat_interaction_forecast(dataset, forecast, target)
                self.assertEqual(score["content_hash"], expected_hash)
                diagnostic = diagnose_repeat_interaction_forecast(dataset, forecast, target, [0, 0.5, 1])
                self.assertEqual(encoded(score), encoded(diagnostic["score"]))


if __name__ == "__main__":
    unittest.main()
