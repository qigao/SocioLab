"""Aggregate weighting and bound-source checks using fictional evidence only."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import gzip
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.archive_recurrence import _source_audit, load_email_eu_dept3_archive
from sociolab.cli import main
import sociolab.observation_sensitivity as module
from sociolab.observation_sensitivity import archive_observation_report, weight_sensitivity
from sociolab.snapshots import content_hash


ZERO = "always_zero_reference"
DAY = 86400
A, B, C = 100000031, 100000032, 100000033
ROWS = ((1, A, B, 0), (2, A, B, DAY), (3, B, A, 2 * DAY),
        (4, C, C, 91 * DAY), (5, A, B, 300 * DAY))


def fold(risk=2, positive=0, records=0, a=0.0, b=0.5):
    return {"risk_pairs": risk, "archive_positive_pairs": positive, "target_row_count": records,
            "models": {"a": {"n": risk, "brier": a if risk else None},
                       "b": {"n": risk, "brier": b if risk else None}}}


def mixed_folds():
    return [fold(positive=1, records=2, a=0.5, b=0.25), fold()]


def comparison(report, a="a", b="b"):
    return next(item for item in report["pairwise_comparisons"]
                if item["model_a"] == a and item["model_b"] == b)


def write_case(path, report, reference):
    report.pop("content_hash", None)
    report["content_hash"] = content_hash(report)
    raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    bound = deepcopy(reference)
    bound.update(report_file_sha256=sha256(raw).hexdigest(), report_content_hash=report["content_hash"])
    return bound


def fictional_case(directory, profile):
    """Bind an authored file to hand-computed fixed-probability fold scores."""
    directory = Path(directory)
    archive_path, report_path = directory / "fictional.txt.gz", directory / "fictional-case.json"
    payload = "".join(f"{source} {target} {when}\n" for _, source, target, when in ROWS).encode()
    archive_path.write_bytes(gzip.compress(payload, mtime=0))
    reference = deepcopy(module._REFERENCES[profile])
    reference.update(study_id="authored-observation-audit-case", study_commit="fictional-bound-study",
                     payload_sha256=sha256(payload).hexdigest(), origins_days=(1, 91, 181),
                     protocol_hash=content_hash({"fixture": profile}))
    models = reference["models"]
    report = {"schema": reference["schema"], "study_id": reference["study_id"],
              "protocol_hash": reference["protocol_hash"],
              "source": _source_audit(load_email_eu_dept3_archive(archive_path)), "folds": []}
    for index, day in enumerate(reference["origins_days"]):
        origin, end = day * DAY, (day + 90) * DAY
        history = tuple(row for row in ROWS if row[3] < origin)
        target = tuple(row for row in ROWS if origin <= row[3] < end)
        risk = {row[1:3] for row in history if row[1] != row[2]}
        targets = {row[1:3] for row in target if row[1] != row[2]}
        n, positives = len(risk), len(risk & targets)
        item = {"origin_at_seconds": origin, "target_end_seconds": end,
                "target_row_count": len(target), "target_rows_hash": content_hash(target),
                "history_rows_hash": content_hash(history), "risk_pairs": n,
                "archive_positive_pairs": positives, "archive_negative_pairs": n - positives,
                "target_positive_pairs_outside_risk": len(targets - risk),
                "forecast_hash": content_hash({"authored_probability_forecast_origin": origin}), "models": {}}
        for model_index, name in enumerate(models):
            probability = (model_index + 1) / (len(models) + 1)
            error = positives * (1 - probability) ** 2 + (n - positives) * probability**2
            item["models"][name] = {"n": n, "brier": error / n if n else None}
        if profile == "email-eu-dept2-network":
            item["split"] = "validation" if index == 0 else "test"
        report["folds"].append(item)
    selected = report["folds"] if profile == "email-eu-dept3" else report["folds"][1:]
    n = sum(item["risk_pairs"] for item in selected)
    pooled = {name: {"pooled_brier": math.fsum(item["models"][name]["n"] * item["models"][name]["brier"]
                                              for item in selected) / n} for name in models}
    zero = sum(item["archive_positive_pairs"] for item in selected) / n
    if profile == "email-eu-dept3":
        report.update(models=pooled, reference={"always_zero_brier": zero})
    else:
        report["splits"] = {"test": {"models": pooled, "always_zero_brier": zero}}
    reference = write_case(report_path, report, reference)
    return archive_path, report_path, report, reference


class WeightSensitivityTests(unittest.TestCase):
    def test_primary_subset_and_intermediate_weights_match_independent_arithmetic(self):
        report = weight_sensitivity(mixed_folds(), ("a", "b"))
        self.assertEqual(report["defined_weight_domain"], "[0,1]")
        self.assertEqual(report["risk_pair_origins"], 4)
        self.assertEqual(report["strata"]["nonempty"]["risk_pair_origins"], 2)
        self.assertEqual(report["strata"]["empty"]["risk_pair_origins"], 2)
        for row in report["models"]["a"]["grid"]:
            weight = row["empty_window_weight"]
            self.assertEqual(row["effective_risk_weight"], 2 + 2 * weight)
            self.assertAlmostEqual(row["weighted_brier"], 1 / (2 + 2 * weight))
        self.assertEqual(report["models"]["a"]["grid"][0]["weighted_brier"], 0.5)
        self.assertEqual(report["models"]["a"]["grid"][-1]["weighted_brier"], 0.25)
        self.assertEqual(report["models"]["b"]["grid"][-1]["weighted_brier"], 0.375)
        self.assertEqual(report["primary_empty_window_weight"], 1.0)

    def test_interior_ranking_switch_and_pairwise_differences_use_the_shared_denominator(self):
        report = weight_sensitivity(mixed_folds(), ("a", "b"))
        pair = comparison(report)
        ranking = pair["ranking"]
        self.assertEqual(ranking["status"], "INTERIOR_CROSSING")
        self.assertEqual(ranking["equality_weight"], 0.5)
        self.assertEqual(ranking["nonempty_error_difference"], 0.5)
        self.assertEqual(ranking["empty_error_difference"], -1.0)
        for weight, value in zip(report["weights"], pair["grid_differences"]):
            self.assertAlmostEqual(value, (0.5 - weight) / (2 + 2 * weight))
        self.assertEqual(pair["grid_differences"][2], 0.0)
        self.assertGreater(pair["grid_differences"][0], 0)
        self.assertLess(pair["grid_differences"][-1], 0)

    def test_endpoint_equalities_all_weight_ties_and_zero_slope_are_distinct(self):
        cases = [
            ([fold(records=1, a=0.25, b=0.25), fold(a=0.5, b=0)], "ENDPOINT_EQUALITY", 0.0),
            ([fold(records=1, a=0.5, b=0), fold(a=0, b=0.5)], "ENDPOINT_EQUALITY", 1.0),
            ([fold(records=1, a=0.25, b=0.25), fold(a=0.5, b=0.5)], "TIED_ALL_DEFINED_WEIGHTS", None),
            ([fold(records=1, a=0.5, b=0.25), fold(a=0.5, b=0.5)], "NO_CROSSING_CONSTANT_SIGN", None),
        ]
        for folds, status, root in cases:
            with self.subTest(status=status, root=root):
                ranking = comparison(weight_sensitivity(folds, ("a", "b")))["ranking"]
                self.assertEqual(ranking["status"], status)
                self.assertEqual(ranking["equality_weight"], root)

    def test_roots_outside_weight_range_do_not_become_crossings(self):
        cases = [([fold(records=1, a=0.5, b=0), fold(a=0.5, b=0)], True, False),
                 ([fold(records=1, a=1, b=0), fold(a=0, b=0.5)], False, True)]
        for folds, below, above in cases:
            ranking = comparison(weight_sensitivity(folds, ("a", "b")))["ranking"]
            self.assertEqual(ranking["status"], "NO_CROSSING_ON_DEFINED_DOMAIN")
            self.assertIsNone(ranking["equality_weight"])
            self.assertEqual((ranking["root_below_zero"], ranking["root_above_one"]), (below, above))

    def test_subnormal_equality_ratio_never_becomes_a_false_zero_endpoint(self):
        tiny = 5e-324
        scenarios = [
            (fold(risk=2, a=0, b=1), "NUMERICALLY_UNRESOLVED_EQUALITY", False),
            (fold(risk=2, a=1, b=0), "NO_CROSSING_ON_DEFINED_DOMAIN", True),
        ]
        for empty, status, below in scenarios:
            for names in (("a", "b"), ("b", "a")):
                with self.subTest(status=status, model_order=names):
                    folds = [fold(risk=1, records=1, a=tiny, b=0), empty]
                    report = weight_sensitivity(folds, names)
                    ranking = comparison(report, *names)["ranking"]
                    # The true ratio is +/- tiny/2. Its floating representation
                    # underflows, but the nonzero numerator excludes a tie at 0.
                    self.assertNotEqual(ranking["numerator_at_zero"], 0.0)
                    self.assertEqual(ranking["status"], status)
                    self.assertIsNone(ranking["equality_weight"])
                    self.assertEqual(ranking["root_below_zero"], below)
                    self.assertFalse(ranking["root_above_one"])

    def test_all_empty_plan_excludes_weight_zero_and_its_algebraic_root(self):
        report = weight_sensitivity([fold(a=0.25, b=0.5)], ("a", "b"))
        self.assertEqual(report["defined_weight_domain"], "(0,1]")
        for name in ("a", "b", ZERO):
            self.assertIsNone(report["models"][name]["grid"][0]["weighted_brier"])
        self.assertEqual([row["weighted_brier"] for row in report["models"]["a"]["grid"]][1:], [0.25] * 4)
        pair = comparison(report)
        self.assertEqual(pair["ranking"]["status"], "NO_CROSSING_ON_DEFINED_DOMAIN")
        self.assertIsNone(pair["ranking"]["equality_weight"])
        self.assertIsNone(pair["ranking"]["at_weight_zero"])
        self.assertEqual(pair["grid_differences"], [None, -0.25, -0.25, -0.25, -0.25])

    def test_no_empty_windows_keep_scores_constant_and_no_risk_keeps_metrics_null(self):
        nonempty = weight_sensitivity([fold(positive=1, records=2, a=0.25, b=0.5)], ("a", "b"))
        self.assertEqual([row["weighted_brier"] for row in nonempty["models"]["a"]["grid"]], [0.25] * 5)
        self.assertEqual(nonempty["defined_weight_domain"], "[0,1]")
        empty_risk = weight_sensitivity([fold(risk=0, records=1)], ("a", "b"))
        self.assertEqual(empty_risk["defined_weight_domain"], "NONE")
        for item in empty_risk["models"].values():
            self.assertEqual(item["status"], "NO_RISK")
            self.assertFalse(item["complete_plan_coverage"])
            self.assertTrue(all(row["weighted_brier"] is None for row in item["grid"]))
        for item in empty_risk["pairwise_comparisons"]:
            self.assertEqual(item["status"], "NO_RISK")
            self.assertIsNone(item["ranking"])

    def test_missing_and_partial_models_keep_counts_without_borrowing_denominators(self):
        for slot in (None, {"n": 1, "brier": 0.25}, {"n": 0, "brier": None}):
            folds = mixed_folds()
            if slot is None:
                del folds[1]["models"]["a"]
            else:
                folds[1]["models"]["a"] = slot
            report = weight_sensitivity(folds, ("a", "b"))
            item = report["models"]["a"]
            self.assertEqual(item["status"], "INCOMPLETE_MODEL_COVERAGE")
            self.assertEqual(item["unavailable_or_partial_origins"], [1])
            self.assertEqual(item["scored_pair_origins"], 2 + (slot["n"] if slot else 0))
            self.assertEqual(item["unscored_pair_origins"], 4 - item["scored_pair_origins"])
            self.assertTrue(all(row["weighted_brier"] is None for row in item["grid"]))
            self.assertTrue(report["models"]["b"]["complete_plan_coverage"])
            self.assertEqual(comparison(report)["status"], "INCOMPLETE_MODEL_COVERAGE")
            self.assertIsNone(comparison(report)["ranking"])

    def test_derived_zero_reference_uses_exact_positive_error_sums(self):
        report = weight_sensitivity([fold(risk=25, positive=7, records=7), fold(risk=3)], ("a", "b"))
        zero = report["models"][ZERO]
        self.assertEqual(zero["strata"]["nonempty"]["sum_squared_error"], 7.0)
        self.assertEqual(zero["strata"]["empty"]["sum_squared_error"], 0.0)
        self.assertEqual(zero["grid"][0]["weighted_brier"], 7 / 25)
        self.assertEqual(zero["grid"][-1]["weighted_brier"], 7 / 28)

    def test_self_only_target_presence_belongs_to_nonempty_archive_stratum(self):
        report = weight_sensitivity([fold(risk=2, positive=0, records=1, a=0.25), fold()], ("a", "b"))
        self.assertEqual(report["strata"]["nonempty"]["risk_pair_origins"], 2)
        self.assertEqual(report["strata"]["nonempty"]["positive_pair_origins"], 0)
        self.assertEqual(report["models"]["a"]["grid"][0]["weighted_brier"], 0.25)

    def test_weights_and_model_names_are_bounded_finite_and_unambiguous(self):
        invalid_weights = [None, (), (0,), (0, 0.5), (0.1, 1), (0, 0.5, 0.5, 1),
                           (0, 0.75, 0.25, 1), (0, -1, 1), (0, 2, 1), (False, 1),
                           (0, float("nan"), 1), (0, float("inf"), 1), (0, 10**1000, 1),
                           tuple(index / 21 for index in range(22))]
        for weights in invalid_weights:
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                weight_sensitivity(mixed_folds(), ("a", "b"), weights)
        for names in (None, (), ("",), (True,), ("a", "a"), (ZERO,), ("x" * 101,), tuple(str(i) for i in range(17))):
            with self.subTest(names=names), self.assertRaises(ValueError):
                weight_sensitivity(mixed_folds(), names)

    def test_fold_counts_scores_and_required_fields_reject_unknown_or_inconsistent_values(self):
        invalid = [None, True, (), [], [fold()] * 101, [True], [{}]]
        for key, value in (("risk_pairs", None), ("risk_pairs", True), ("risk_pairs", -1),
                           ("risk_pairs", 2001), ("archive_positive_pairs", 3),
                           ("archive_positive_pairs", True), ("archive_positive_pairs", 1),
                           ("target_row_count", None), ("target_row_count", -1), ("models", [])):
            item = fold()
            item[key] = value
            invalid.append([item])
        for slot in (True, {}, {"n": 1}, {"brier": 0.5}, {"n": True, "brier": 0.5},
                     {"n": 3, "brier": 0.5}, {"n": 0, "brier": 0},
                     {"n": 2, "brier": None}, {"n": 2, "brier": True},
                     {"n": 2, "brier": -0.1}, {"n": 2, "brier": 1.1},
                     {"n": 2, "brier": float("nan")}, {"n": 2, "brier": float("inf")},
                     {"n": 2, "brier": 10**1000}):
            item = fold()
            item["models"]["a"] = slot
            invalid.append([item])
        for folds in invalid:
            with self.subTest(folds=folds), self.assertRaises(ValueError):
                weight_sensitivity(folds, ("a", "b"))

    def test_original_inputs_and_primary_semantics_are_preserved(self):
        folds = mixed_folds()
        before = deepcopy(folds)
        report = weight_sensitivity(folds, ("a", "b"))
        self.assertEqual(folds, before)
        self.assertEqual(report["analysis_status"], "POST_RESULT_EXPLORATORY_WEIGHTING")
        for key in ("model_refitted", "archive_labels_changed", "model_selected", "real_coverage_correction",
                    "unknown_label_bounds", "confidence_interval", "selected_windows_removed_from_primary"):
            self.assertFalse(report["scope"][key])
        unhashed = deepcopy(report)
        self.assertEqual(unhashed.pop("content_hash"), content_hash(unhashed))


class BoundObservationReportTests(unittest.TestCase):
    def test_both_profiles_bind_fictional_source_and_preserve_original_artifacts(self):
        for profile in ("email-eu-dept3", "email-eu-dept2-network"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                archive, case, saved, reference = fictional_case(directory, profile)
                before = archive.read_bytes(), case.read_bytes()
                with patch.dict(module._REFERENCES, {profile: reference}):
                    report = archive_observation_report(profile, archive, case)
                self.assertEqual((archive.read_bytes(), case.read_bytes()), before)
                self.assertEqual(report["prior_study"]["report_content_hash"], saved["content_hash"])
                self.assertEqual(len(report["observation_audit"]["windows"]), 3)
                self.assertEqual([item["row_count"] for item in report["observation_audit"]["windows"]], [2, 1, 0])
                self.assertEqual(report["observation_audit"]["windows"][1]["nonself_row_count"], 0)
                self.assertTrue(report["observation_audit"]["windows"][2]["empty_window_internally_bounded"])
                for item in report["primary_score_reproduction"].values():
                    self.assertLessEqual(item["absolute_difference"], 1e-12)
                self.assertIn(ZERO, report["primary_score_reproduction"])
                self.assertFalse(report["scope"]["models_refitted_or_private_predictions_reconstructed"])
                self.assertFalse(report["scope"]["coverage_events_created"])
                self.assertEqual(report["scope"]["real_coverage_status"], "UNKNOWN")

    def test_dept2_audits_validation_but_keeps_it_out_of_test_sensitivity(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, case, saved, reference = fictional_case(directory, "email-eu-dept2-network")
            with patch.dict(module._REFERENCES, {"email-eu-dept2-network": reference}):
                report = archive_observation_report("email-eu-dept2-network", archive, case)
            self.assertEqual([item["split"] for item in report["study_windows"]], ["validation", "test", "test"])
            sensitivity = report["weight_sensitivity"]
            self.assertEqual((sensitivity["planned_origins"], sensitivity["risk_pair_origins"]), (2, 4))
            self.assertEqual(sensitivity["strata"]["nonempty"]["risk_pair_origins"], 2)
            self.assertEqual(sensitivity["strata"]["nonempty"]["positive_pair_origins"], 0)
            self.assertEqual(sensitivity["models"][ZERO]["grid"][-1]["weighted_brier"], 0.0)
            self.assertEqual(saved["folds"][0]["archive_positive_pairs"], 1)

    def test_recompression_is_allowed_while_payload_identity_and_saved_case_remain_fixed(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, case, _, reference = fictional_case(directory, "email-eu-dept3")
            original = archive.read_bytes()
            archive.write_bytes(gzip.compress(gzip.decompress(original), mtime=12345))
            self.assertNotEqual(archive.read_bytes(), original)
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}):
                report = archive_observation_report("email-eu-dept3", archive, case)
            self.assertEqual(report["source"]["payload_sha256"], reference["payload_sha256"])
            self.assertEqual(report["source"]["compressed_sha256"], sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(report["prior_study"]["report_file_sha256"], sha256(case.read_bytes()).hexdigest())

    def test_saved_case_bytes_are_bound_even_when_json_meaning_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, case, _, reference = fictional_case(directory, "email-eu-dept3")
            case.write_bytes(case.read_bytes() + b"\n")
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), self.assertRaisesRegex(ValueError, "exact previously published"):
                archive_observation_report("email-eu-dept3", archive, case)

    def test_modified_payload_and_rehashed_report_cannot_bypass_independent_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, case, saved, reference = fictional_case(directory, "email-eu-dept3")
            archive.write_bytes(gzip.compress(gzip.decompress(archive.read_bytes()) + f"{A} {B} {301 * DAY}\n".encode()))
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), self.assertRaisesRegex(ValueError, "reviewed archive payload"):
                archive_observation_report("email-eu-dept3", archive, case)
            archive, case, saved, reference = fictional_case(directory, "email-eu-dept3")
            saved["folds"][0]["risk_pairs"] += 1
            write_case(case, saved, reference)  # Caller can rehash, but the accepted reference does not change.
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), self.assertRaisesRegex(ValueError, "exact previously published"):
                archive_observation_report("email-eu-dept3", archive, case)

    def test_bound_report_semantics_still_reject_wrong_origin_horizon_counts_source_and_primary_score(self):
        mutations = [
            (lambda r: r["folds"][0].update(origin_at_seconds=2 * DAY), "origins differ"),
            (lambda r: r["folds"][0].update(target_end_seconds=92 * DAY), "horizon differs"),
            (lambda r: r["folds"][0].update(target_row_count=3), "target/history/count"),
            (lambda r: r["folds"][0].update(archive_positive_pairs=0), "target/history/count"),
            (lambda r: r["source"].update(node_count=4), "source audit differs"),
            (lambda r: r["models"]["historical_poisson"].update(pooled_brier=0.9), "weight one"),
            (lambda r: r["reference"].update(always_zero_brier=0.9), "weight one"),
        ]
        for mutate, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                archive, case, saved, reference = fictional_case(directory, "email-eu-dept3")
                mutate(saved)
                reference = write_case(case, saved, reference)
                with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), self.assertRaisesRegex(ValueError, message):
                    archive_observation_report("email-eu-dept3", archive, case)

    def test_split_and_content_hash_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, case, saved, reference = fictional_case(directory, "email-eu-dept2-network")
            saved["folds"][0]["split"] = "test"
            reference = write_case(case, saved, reference)
            with patch.dict(module._REFERENCES, {"email-eu-dept2-network": reference}), self.assertRaisesRegex(ValueError, "validation/test split"):
                archive_observation_report("email-eu-dept2-network", archive, case)
            archive, case, saved, reference = fictional_case(directory, "email-eu-dept3")
            saved["study_id"] = "different"
            raw = (json.dumps(saved) + "\n").encode()
            case.write_bytes(raw)
            reference["report_file_sha256"] = sha256(raw).hexdigest()
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), self.assertRaisesRegex(ValueError, "identity"):
                archive_observation_report("email-eu-dept3", archive, case)

    def test_actual_cli_emits_fictional_aggregate_report_and_rejects_tampering_without_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, case, _, reference = fictional_case(directory, "email-eu-dept3")
            stdout, stderr = io.StringIO(), io.StringIO()
            argv = ["study", "archive-observation", "email-eu-dept3", str(archive), str(case)]
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(argv), 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["schema"], "sociolab.bound-archive-observation-report.v1")
            self.assertEqual(result["weight_sensitivity"]["risk_pair_origins"], 5)
            self.assertEqual(stderr.getvalue(), "")
            case.write_bytes(case.read_bytes() + b" ")
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                main(argv)
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("exact previously published", stderr.getvalue())

    def test_unknown_profile_and_duplicate_json_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "supports only"):
            archive_observation_report("unsupported", "/unused", "/unused")
        with tempfile.TemporaryDirectory() as directory:
            archive, case, _, reference = fictional_case(directory, "email-eu-dept3")
            raw = b'{"schema":"one","schema":"two"}'
            case.write_bytes(raw)
            reference["report_file_sha256"] = sha256(raw).hexdigest()
            with patch.dict(module._REFERENCES, {"email-eu-dept3": reference}), self.assertRaises(ValueError):
                archive_observation_report("email-eu-dept3", archive, case)


if __name__ == "__main__":
    unittest.main()
