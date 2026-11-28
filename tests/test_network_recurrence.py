"""Temporal adapter checks and upstream fits using authored fictional rows only."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import gzip
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.archive_features import make_archive_features
from sociolab.cli import main
import sociolab.network_recurrence as module
from sociolab.network_recurrence import (
    MODEL_NAMES, _comparison_report, _fit_one, _forecast, _predict_one,
    _prepare_training, _score_fold, email_eu_dept2_network_report,
)
from sociolab.snapshots import content_hash


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/experiments/2026-11-28-dept2-network/protocol.json"
A, B, C, D = 100000011, 100000012, 100000013, 100000014
# These small integer records are authored examples, not real archive records.
ROWS = (
    (1, A, B, 1), (2, B, A, 2), (3, A, C, 3), (4, C, A, 4),
    (5, B, C, 7), (6, A, B, 8), (7, A, B, 10), (8, C, A, 12),
    (9, D, A, 11), (10, B, A, 15), (11, B, C, 17), (12, A, D, 18),
    (13, D, A, 19), (14, A, B, 20), (15, D, B, 22), (16, A, D, 24),
    (17, A, B, 25), (18, B, D, 27), (19, C, A, 29), (20, D, B, 30),
    (21, A, C, 34), (22, C, D, 35),
)


def protocol():
    result = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    result["study_id"] = "fictional-network-recurrence-contract"
    result["source"] = {"dataset": "authored integer example", "source_url": "https://example.invalid/fictional"}
    result["measurement"].update(training_origins=[10, 15], fit_cutoff=20,
                                 validation_origins=[20], test_origins=[25, 30],
                                 horizon=5, recent_width=4)
    result["admission"].update(required_rows=len(ROWS), required_nodes=4, minimum_archive_max_time=35)
    return result


def training(rows=ROWS, plan=None):
    plan = protocol() if plan is None else plan
    return _prepare_training(tuple(row for row in rows if row[3] < plan["measurement"]["fit_cutoff"]),
                             plan["measurement"])


def features(rows=ROWS, origin=20):
    return make_archive_features(tuple(row for row in rows if row[3] < origin),
                                 origin=origin, horizon=5, recent_width=4)


def payload(rows=ROWS):
    return "".join(f"{source} {target} {when}\n" for _, source, target, when in rows).encode("ascii")


try:
    HAS_PROVIDER = version("scikit-learn") == "1.9.1"
except PackageNotFoundError:
    HAS_PROVIDER = False


class NetworkRecurrenceContractTests(unittest.TestCase):
    """These checks run even when the optional fitted-model package is absent."""

    def test_training_risk_labels_and_exact_window_boundaries(self):
        examples, summary = training()
        self.assertEqual((summary["pair_origin_count"], summary["positive_count"], summary["negative_count"]),
                         (11, 5, 6))
        self.assertEqual([fold["risk_pairs"] for fold in summary["folds"]], [5, 6])
        self.assertEqual([fold["archive_positive_pairs"] for fold in summary["folds"]], [2, 3])
        self.assertEqual([fold["target_positive_pairs_outside_risk"] for fold in summary["folds"]], [1, 1])
        at10 = {(row["source"], row["target"]): row["label"] for row in examples if row["origin_at_seconds"] == 10}
        at15 = {(row["source"], row["target"]): row["label"] for row in examples if row["origin_at_seconds"] == 15}
        self.assertEqual(at10[A, B], 1)  # The record exactly at origin is a target.
        self.assertEqual(at10[B, A], 0)  # Time 15 belongs to the next target.
        self.assertEqual(at15[B, A], 1)
        self.assertEqual(at15[A, B], 0)  # Time 20 is beyond the training label window.
        self.assertNotIn((D, A), at10)
        self.assertNotIn((A, D), at15)
        self.assertFalse(summary["validation_or_test_labels_used"])

    def test_training_refuses_future_rows_unclosed_targets_and_overlaps(self):
        plan = protocol()
        with self.assertRaisesRegex(ValueError, "strictly before the fit cutoff"):
            _prepare_training(tuple(row for row in ROWS if row[3] <= 20), plan["measurement"])
        for origins in ([10, 16], [10, 14], [15, 10]):
            changed = deepcopy(plan["measurement"])
            changed["training_origins"] = origins
            with self.subTest(origins=origins), self.assertRaisesRegex(ValueError, "must not overlap"):
                _prepare_training(tuple(row for row in ROWS if row[3] < 20), changed)

    def test_empty_and_single_class_fits_are_explicit_without_provider_or_fallback(self):
        plan = protocol()
        for rows, expected in (((), "empty_training_risk_set"),
                               (((1, A, B, 1),), "training_requires_both_binary_classes")):
            examples, summary = training(rows, plan)
            with patch.object(module, "_provider", side_effect=AssertionError("no upstream fit is admissible")):
                fitted = _fit_one(examples, summary, plan, "dyadic_logistic")
            self.assertEqual(fitted.report["status"], "NOT_ESTIMABLE")
            self.assertEqual(fitted.report["reason"], expected)
            self.assertIsNone(fitted.scaler)
            self.assertIsNone(fitted.estimator)
            self.assertIsNone(_predict_one(fitted, features(rows)))

    def test_failed_model_cannot_enable_a_forecast_before_training_cutoff(self):
        plan = protocol()
        rows = ((1, A, B, 1),)
        examples, summary = training(rows, plan)
        fitted = {name: _fit_one(examples, summary, plan, name)
                  for name in ("dyadic_logistic", "network_logistic")}
        before_cutoff = features(rows, origin=15)
        with self.assertRaisesRegex(ValueError, "cutoff"):
            _predict_one(fitted["dyadic_logistic"], before_cutoff)
        with self.assertRaisesRegex(ValueError, "cutoff"):
            _forecast(rows, before_cutoff, fitted, summary, plan)

    def test_single_class_models_keep_all_planned_slots_with_null_metrics(self):
        rows = ((1, A, B, 1), (2, A, B, 20), (3, B, A, 25))
        with patch.object(module, "_provider", side_effect=AssertionError("single-class fitting must not run")):
            report = _comparison_report(rows, protocol())
        self.assertEqual(len(report["folds"]), 3)
        self.assertEqual([fold["origin_at_seconds"] for fold in report["folds"]], [20, 25, 30])
        for fold in report["folds"]:
            self.assertTrue(fold["batch_replay_feature_hash_equal"])
            for name in ("dyadic_logistic", "network_logistic"):
                self.assertEqual(fold["models"][name]["status"], "MODEL_NOT_AVAILABLE")
                self.assertEqual(fold["models"][name]["n"], 0)
                self.assertIsNone(fold["models"][name]["brier"])
            self.assertEqual(fold["models"]["training_prevalence"]["n"], fold["risk_pairs"])
        test = report["splits"]["test"]
        self.assertIsNone(test["network_minus_dyadic_pooled_brier"])
        self.assertEqual(test["network_dyadic_common_pair_origins"], 0)
        self.assertFalse(test["models"]["network_logistic"]["full_planned_risk_scored"])
        self.assertEqual(test["models"]["network_logistic"]["unscored_pair_origins"], test["risk_pair_origin_count"])

    def test_empty_risk_preserves_origins_and_unknown_metrics_without_provider(self):
        with patch.object(module, "_provider", side_effect=AssertionError("empty fitting must not run")):
            report = _comparison_report((), protocol())
        self.assertEqual(len(report["folds"]), 3)
        for split in report["splits"].values():
            self.assertEqual(split["risk_pair_origin_count"], 0)
            self.assertIsNone(split["always_zero_brier"])
            self.assertIsNone(split["network_minus_dyadic_pooled_brier"])
            for model in split["models"].values():
                self.assertEqual(model["n"], 0)
                self.assertIsNone(model["pooled_brier"])
                self.assertIsNone(model["macro_brier"])
                self.assertFalse(model["full_planned_risk_scored"])

    def test_validation_test_overlap_and_pre_fit_origins_rejected(self):
        for validation, test in (([19], [25, 30]), ([20], [24, 30]), ([20], [25, 29])):
            plan = protocol()
            plan["measurement"].update(validation_origins=validation, test_origins=test)
            with self.subTest(validation=validation, test=test), self.assertRaisesRegex(ValueError, "disjoint"):
                _comparison_report((), plan)

    def test_frozen_protocol_and_payload_are_separate_wrapper_gates(self):
        plan = protocol()
        with patch.object(module, "_provider", side_effect=AssertionError("protocol gate must run first")):
            with self.assertRaisesRegex(ValueError, "frozen pre-acquisition protocol"):
                email_eu_dept2_network_report("/does/not/exist.gz", plan)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fictional.gz"
            source.write_bytes(gzip.compress(payload(), mtime=0))
            with patch.object(module, "REFERENCE_PROTOCOL_HASH", content_hash(plan)), patch.object(module, "_provider"):
                with self.assertRaisesRegex(ValueError, "payload fingerprint"):
                    email_eu_dept2_network_report(source, plan)

    def test_wrapper_rejects_metadata_mismatch_before_estimating(self):
        plan = protocol()
        plan["admission"]["required_nodes"] = 5
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fictional.gz"
            source.write_bytes(gzip.compress(payload(), mtime=0))
            with patch.multiple(module, REFERENCE_PROTOCOL_HASH=content_hash(plan),
                                REFERENCE_PAYLOAD_SHA256=sha256(payload()).hexdigest()), \
                    patch.object(module, "_provider"), \
                    patch.object(module, "_comparison_report", side_effect=AssertionError("must not fit")):
                with self.assertRaisesRegex(ValueError, "metadata/extent admission"):
                    email_eu_dept2_network_report(source, plan)

    def test_cli_bad_or_duplicate_protocol_produces_no_report(self):
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "protocol.json"
            for raw in ('{"schema":"changed"}', '{"schema":"first","schema":"second"}'):
                plan_path.write_text(raw, encoding="utf-8")
                out, err = io.StringIO(), io.StringIO()
                with self.subTest(raw=raw), redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                    main(["study", "email-eu-dept2-network", "/does/not/exist.gz", str(plan_path)])
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(out.getvalue(), "")
                self.assertIn("error:", err.getvalue())

    def test_provider_missing_or_wrong_version_is_an_explicit_failure(self):
        with patch.object(module, "version", side_effect=PackageNotFoundError("scikit-learn")):
            with self.assertRaisesRegex(ValueError, "optional network-prediction"):
                module._provider()
        with patch.object(module, "version", return_value="0.0.0"):
            with self.assertRaisesRegex(ValueError, "reviewed scikit-learn"):
                module._provider()


@unittest.skipUnless(HAS_PROVIDER, "optional scikit-learn==1.9.1 provider is not installed")
class NetworkRecurrenceRuntimeTests(unittest.TestCase):
    """Exercise actual upstream scaling, fitting, probabilities and scored output."""

    @classmethod
    def setUpClass(cls):
        cls.plan = protocol()
        cls.examples, cls.training = training(plan=cls.plan)
        cls.fitted = {name: _fit_one(cls.examples, cls.training, cls.plan, name)
                      for name in ("dyadic_logistic", "network_logistic")}
        for fitted in cls.fitted.values():
            if fitted.report["status"] != "FITTED":
                raise AssertionError(f"fictional upstream fit failed: {fitted.report}")

    def test_scaler_uses_training_rows_and_matches_independent_moments(self):
        for name, block in (("dyadic_logistic", "dyadic"), ("network_logistic", "network")):
            saved = self.fitted[name].report["parameter_state"]["scaler"]
            matrix = [row[block + "_features"] for row in self.examples]
            self.assertEqual(saved["n_samples_seen"], 11)
            for column in range(len(matrix[0])):
                mean = math.fsum(row[column] for row in matrix) / len(matrix)
                variance = math.fsum((row[column] - mean) ** 2 for row in matrix) / len(matrix)
                self.assertAlmostEqual(saved["mean"][column], mean, places=14)
                self.assertAlmostEqual(saved["variance"][column], variance, places=14)
                self.assertAlmostEqual(saved["scale"][column], math.sqrt(variance) if variance else 1.0, places=14)

    def test_positive_probability_column_matches_saved_parameter_logistic_formula(self):
        feature = features()
        for name, block in (("dyadic_logistic", "dyadic"), ("network_logistic", "network")):
            fitted = self.fitted[name]
            state = fitted.report["parameter_state"]
            self.assertEqual(state["estimator"]["classes"], [0, 1])
            actual = _predict_one(fitted, feature)
            for row, probability in zip(feature["rows"], actual):
                standardized = [(value - mean) / scale for value, mean, scale in zip(
                    row[block + "_features"], state["scaler"]["mean"], state["scaler"]["scale"])]
                score = state["estimator"]["intercept"][0] + math.fsum(
                    value * coefficient for value, coefficient in zip(standardized, state["estimator"]["coefficients"][0]))
                expected = 1 / (1 + math.exp(-score))
                self.assertAlmostEqual(probability, expected, places=13)
                self.assertGreater(probability, 0)
                self.assertLess(probability, 1)

    def test_fitted_report_scaler_coefficients_and_configuration_cannot_change(self):
        feature = features()
        mutations = (
            lambda fitted: fitted.report.update(training_n=999),
            lambda fitted: fitted.scaler.mean_.__setitem__(0, fitted.scaler.mean_[0] + 1),
            lambda fitted: fitted.estimator.coef_.__setitem__((0, 0), fitted.estimator.coef_[0, 0] + 1),
            lambda fitted: fitted.estimator.set_params(C=2.0),
            lambda fitted: fitted.estimator.classes_.__setitem__(slice(None), [1, 0]),
        )
        for index, mutate in enumerate(mutations):
            fitted = deepcopy(self.fitted["dyadic_logistic"])
            mutate(fitted)
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "changed after fitting"):
                _predict_one(fitted, feature)

    def test_predict_rejects_before_cutoff_wrong_feature_order_and_nonfinite_values(self):
        fitted = self.fitted["dyadic_logistic"]
        with self.assertRaisesRegex(ValueError, "cutoff"):
            _predict_one(fitted, features(origin=15))
        changed = features()
        changed["feature_names"]["dyadic"].reverse()
        with self.assertRaisesRegex(ValueError, "feature order"):
            _predict_one(fitted, changed)
        changed = features()
        changed["rows"][0]["dyadic_features"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite matrix"):
            _predict_one(fitted, changed)

    def test_training_feature_shape_and_nonfinite_values_fail_closed(self):
        for replacement in ([1.0], [float("nan"), 1.0, 2.0]):
            changed = deepcopy(self.examples)
            changed[0]["dyadic_features"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                _fit_one(changed, self.training, self.plan, "dyadic_logistic")

    def test_actual_iteration_limit_warning_is_retained_without_retry(self):
        plan = deepcopy(self.plan)
        plan["estimation"]["parameters"]["max_iter"] = 1
        before = deepcopy(plan)
        fitted = _fit_one(self.examples, self.training, plan, "network_logistic")
        self.assertEqual(fitted.report["status"], "FAILED")
        self.assertEqual(fitted.report["reason"], "upstream_fit_emitted_warning_no_retry")
        self.assertIn("ConvergenceWarning", [warning["category"] for warning in fitted.report["warnings"]])
        self.assertEqual(fitted.report["declared_parameters"]["max_iter"], 1)
        self.assertEqual(fitted.report["parameter_state"]["estimator"]["n_iter"], [1])
        self.assertIsNone(fitted.scaler)
        self.assertIsNone(fitted.estimator)
        self.assertIsNone(_predict_one(fitted, features()))
        self.assertEqual(plan, before)

    def test_all_models_score_identical_frozen_pairs_and_match_manual_brier(self):
        history = tuple(row for row in ROWS if row[3] < 20)
        feature = features()
        forecast = _forecast(history, feature, self.fitted, self.training, self.plan)
        target = tuple(row for row in ROWS if 20 <= row[3] < 25)
        report, _, risk = _score_fold(forecast, target, [0, .2, .4, .6, .8, 1])
        self.assertEqual(forecast["available_models"], list(MODEL_NAMES))
        self.assertEqual(report["risk_pairs"], 7)
        self.assertEqual(report["archive_positive_pairs"], 2)
        self.assertEqual(report["target_positive_pairs_outside_risk"], 1)
        self.assertNotIn((D, B), risk)
        positive = {row[1:3] for row in target}
        for name in MODEL_NAMES:
            expected = math.fsum((row["probabilities"][name] - int((row["source"], row["target"]) in positive)) ** 2
                                 for row in forecast["predictions"]) / 7
            self.assertEqual(report["models"][name]["n"], 7)
            self.assertAlmostEqual(report["models"][name]["brier"], expected, places=14)
            bins = report["probability_diagnostics"][name]["bins"]
            self.assertEqual(sum(item["count"] for item in bins), 7)
            self.assertEqual(sum(item["positive_count"] for item in bins), 2)
        with self.assertRaisesRegex(ValueError, "inside the frozen window"):
            _score_fold(forecast, target + ((99, A, B, 25),), [0, 1])

    def test_model_identity_and_first_forecast_ignore_later_targets(self):
        original = _comparison_report(ROWS, self.plan)
        changed_rows = tuple(row for row in ROWS if row[3] < 20) + ((90, A, C, 20), (91, C, B, 29))
        revised = _comparison_report(changed_rows, self.plan)
        self.assertEqual(original["training"], revised["training"])
        self.assertEqual(original["fitted_models"], revised["fitted_models"])
        self.assertEqual(original["folds"][0]["forecast_hash"], revised["folds"][0]["forecast_hash"])
        self.assertNotEqual(original["folds"][0]["target_rows_hash"], revised["folds"][0]["target_rows_hash"])
        expected = {name: fitted["content_hash"] for name, fitted in original["fitted_models"].items()}
        for fold in original["folds"]:
            self.assertEqual(fold["fitted_model_hashes"], expected)
            self.assertTrue(fold["batch_replay_feature_hash_equal"])
        appended = _comparison_report(ROWS + ((90, D, C, 100),), self.plan)
        self.assertEqual(original, appended)

    def test_split_summary_uses_common_pair_denominator_and_separate_validation(self):
        report = _comparison_report(ROWS, self.plan)
        validation, test = report["splits"]["validation"], report["splits"]["test"]
        self.assertEqual((validation["planned_origins"], test["planned_origins"]), (1, 2))
        n = sum(fold["risk_pairs"] for fold in report["folds"] if fold["split"] == "test")
        self.assertEqual(test["risk_pair_origin_count"], n)
        self.assertEqual(test["network_dyadic_common_pair_origins"], n)
        for model in test["models"].values():
            self.assertEqual((model["n"], model["unscored_pair_origins"], model["scored_origins"]), (n, 0, 2))
            self.assertTrue(model["full_planned_risk_scored"])
        self.assertAlmostEqual(test["network_minus_dyadic_pooled_brier"],
                               test["models"]["network_logistic"]["pooled_brier"]
                               - test["models"]["dyadic_logistic"]["pooled_brier"], places=14)

    def test_real_wrapper_and_cli_emit_aggregate_report_from_controlled_fictional_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            source, plan_path = Path(directory) / "fictional.gz", Path(directory) / "protocol.json"
            source.write_bytes(gzip.compress(payload(), mtime=0))
            plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
            with patch.multiple(module, REFERENCE_PROTOCOL_HASH=content_hash(self.plan),
                                REFERENCE_PAYLOAD_SHA256=sha256(payload()).hexdigest(),
                                REFERENCE_GZIP_SHA256=sha256(source.read_bytes()).hexdigest()):
                report = email_eu_dept2_network_report(source, self.plan)
                out = io.StringIO()
                with redirect_stdout(out):
                    main(["study", "email-eu-dept2-network", str(source), str(plan_path)])
                self.assertEqual(json.loads(out.getvalue()), report)
            self.assertEqual(report["source"]["row_count"], len(ROWS))
            self.assertTrue(report["source"]["reviewed_payload_matches"])
            self.assertEqual(report["admission"]["strict_complete_observation_r1_status"], "NOT_ADMITTED")
            self.assertFalse(report["scope"]["contains_private_actor_records"])
            self.assertNotIn("predictions", report)
            self.assertNotIn("examples", report["training"])
            self.assertEqual(report["runtime"]["packages"]["scikit-learn"], "1.9.1")
            unhashed = deepcopy(report)
            self.assertEqual(unhashed.pop("content_hash"), content_hash(unhashed))


if __name__ == "__main__":
    unittest.main()
