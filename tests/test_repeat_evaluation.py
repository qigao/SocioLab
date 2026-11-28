"""Multi-origin denominators, past-only risk sets and evaluation version replay."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.cli import main
from sociolab.events import EventDataset, ingest_records
from sociolab.repeat_evaluation import make_repeat_interaction_plan, evaluate_repeat_interaction_forecasts
from sociolab.repeat_interaction import make_repeat_interaction_forecast
from test_repeat_interaction import (
    A, B, C, D, ACTORS, ALIAS, LATER, MODELS, at, canonical_hash,
    coverage, fixture, interaction, revise, target_spec, with_target,
)


def schedule(*, utc=False, count=2):
    return {"schema": "sociolab.repeat-interaction-schedule.v1", "probability_bins": [0, 0.5, 1],
            "folds": [{"origin_at": at(t, utc), "recent_start": at(t - 5, utc),
                       "target_end": at(t + 4, utc)} for t in (10, 15, 20)[:count]]}


def case(*, utc=False, count=2):
    initial, spec = fixture(utc=utc)
    declared = schedule(utc=utc, count=count)
    plan = make_repeat_interaction_plan(initial, spec, declared)
    first = make_repeat_interaction_forecast(initial, spec)
    journal = with_target(initial, utc=utc)
    first_target = target_spec(journal, utc=utc)
    second_spec = {**deepcopy(spec), **declared["folds"][1], "knowledge_cutoff": len(journal.records)}
    second = make_repeat_interaction_forecast(journal, second_spec)
    journal = ingest_records(journal, [
        interaction("second-AB", A, B, 16, utc=utc),
        interaction("second-AC", A, C, 18, utc=utc),
        interaction("second-new-CB", C, B, 17, utc=utc),
    ], received_at=LATER)
    folds = [{"origin_at": at(10, utc), "forecast": first, "target": first_target},
             {"origin_at": at(15, utc), "forecast": second,
              "target": target_spec(journal, through=19, utc=utc)}]
    if count == 3:
        folds.append({"origin_at": at(20, utc), "forecast": None, "target": None})
    return initial, spec, declared, plan, journal, folds


def rehash(value):
    value["content_hash"] = canonical_hash({key: item for key, item in value.items() if key != "content_hash"})
    return value


class RepeatEvaluationTests(unittest.TestCase):
    def test_pooled_and_macro_use_different_explicit_denominators(self):
        _, _, _, plan, journal, folds = case()
        report = evaluate_repeat_interaction_forecasts(journal, plan, folds)
        counts = report["counts"]
        self.assertEqual(report["status"], "SCORED")
        self.assertEqual((counts["planned_origins"], counts["supplied_forecast_origins"],
                          counts["scorable_origins"], counts["full_plan_risk_pair_origin_count"]), (2, 2, 2, 7))
        self.assertEqual(counts["scorable_positive_pairs_across_supplied_origins"], 4)
        # Authored event counts and outcomes, not scorer-derived expectations.
        first_counts, first_recent, first_y = [3, 1, 1], [2, 0, 1], [1, 1, 0]
        second_counts, second_recent, second_y = [5, 1, 2, 2], [2, 1, 1, 1], [1, 1, 0, 0]
        for model in MODELS:
            if model == "historical_poisson":
                p1 = [1 - math.exp(-n * 4 / 10) for n in first_counts]
                p2 = [1 - math.exp(-n * 4 / 15) for n in second_counts]
            elif model == "recent_poisson":
                p1 = [1 - math.exp(-n * 4 / 5) for n in first_recent]
                p2 = [1 - math.exp(-n * 4 / 5) for n in second_recent]
            else:
                p1, p2 = [int(n > 0) for n in first_recent], [int(n > 0) for n in second_recent]
            errors1 = [(p - y) ** 2 for p, y in zip(p1, first_y)]
            errors2 = [(p - y) ** 2 for p, y in zip(p2, second_y)]
            actual = report["models"][model]
            self.assertEqual(actual["n"], 7)
            self.assertAlmostEqual(actual["pooled_brier"], sum(errors1 + errors2) / 7, places=14)
            self.assertAlmostEqual(actual["macro_brier"], (sum(errors1) / 3 + sum(errors2) / 4) / 2, places=14)
            self.assertAlmostEqual(actual["mean_predicted_probability"], sum(p1 + p2) / 7, places=14)
            self.assertAlmostEqual(actual["observed_fraction"], 4 / 7, places=14)
            for index, (lower, upper) in enumerate(((0, 0.5), (0.5, 1))):
                selected = [(p, y) for p, y in zip(p1 + p2, first_y + second_y)
                            if lower <= p and (p < upper or index == 1)]
                bin_row = actual["bins"][index]
                self.assertEqual(bin_row["count"], len(selected))
                self.assertEqual(bin_row["positive_count"], sum(y for _, y in selected))
                self.assertAlmostEqual(bin_row["sum_squared_error"], sum((p-y)**2 for p, y in selected), places=14)
        self.assertEqual(report["content_hash"], canonical_hash({k: v for k, v in report.items() if k != "content_hash"}))
        self.assertTrue(all(actor not in json.dumps(report) for actor in ACTORS + [ALIAS]))

    def test_each_origin_freezes_own_past_risk_and_target_cannot_add_pair(self):
        _, _, _, plan, journal, folds = case()
        report = evaluate_repeat_interaction_forecasts(journal, plan, folds)
        first, second = report["folds"]
        self.assertEqual((first["risk_pairs"], second["risk_pairs"]), (3, 4))
        change = second["risk_change"]
        self.assertEqual((change["retained_pairs"], change["new_pairs"], change["removed_pairs"]), (3, 1, 0))
        self.assertFalse(first["risk_change"]["compared_with_previous_planned_origin"])
        self.assertEqual(second["score"]["counts"]["known_positive_pairs"], 2)

    def test_history_correction_can_remove_a_risk_pair(self):
        initial, spec = fixture()
        plan = make_repeat_interaction_plan(initial, spec, schedule())
        first = make_repeat_interaction_forecast(initial, spec)
        revised = revise(initial, "CD-recent", "remove-CD-history", retract=True)
        second_spec = {**spec, **schedule()["folds"][1], "knowledge_cutoff": len(revised.records)}
        second = make_repeat_interaction_forecast(revised, second_spec)
        report = evaluate_repeat_interaction_forecasts(revised, plan, [
            {"origin_at": 10, "forecast": first, "target": target_spec(initial)},
            {"origin_at": 15, "forecast": second, "target": target_spec(revised, through=19)},
        ])
        change = report["folds"][1]["risk_change"]
        self.assertEqual((change["retained_pairs"], change["new_pairs"], change["removed_pairs"]), (2, 0, 1))

    def test_same_history_cutoff_with_a_later_timer_origin_is_valid(self):
        initial, spec = fixture()
        plan = make_repeat_interaction_plan(initial, spec, schedule())
        forecasts = [make_repeat_interaction_forecast(initial, {**spec, **window})
                     for window in schedule()["folds"]]
        report = evaluate_repeat_interaction_forecasts(initial, plan, [
            {"origin_at": t, "forecast": prediction, "target": target_spec(initial, through=end)}
            for t, end, prediction in zip((10, 15), (14, 19), forecasts)])
        self.assertEqual(report["status"], "SCORED")
        self.assertEqual(report["counts"]["scorable_negative_pairs_across_supplied_origins"], 6)

    def test_missing_forecast_keeps_origin_and_unknown_full_plan_risk(self):
        _, _, _, plan, journal, folds = case(count=3)
        report = evaluate_repeat_interaction_forecasts(journal, plan, folds)
        self.assertEqual(report["status"], "PARTIALLY_SCORED")
        self.assertEqual(report["counts"]["missing_forecast_origins"], 1)
        self.assertIsNone(report["counts"]["full_plan_risk_pair_origin_count"])
        self.assertEqual(report["counts"]["risk_pairs_across_supplied_origins"], 7)
        self.assertEqual(report["folds"][2]["status"], "FORECAST_NOT_SUPPLIED")
        for model in report["models"].values():
            self.assertIsNone(model["macro_brier"])
            self.assertIsNotNone(model["pooled_brier"])

    def test_missing_middle_origin_does_not_bridge_risk_comparison(self):
        initial, spec = fixture()
        declared = schedule(count=3)
        plan = make_repeat_interaction_plan(initial, spec, declared)
        folds = [{"origin_at": window["origin_at"],
                  "forecast": make_repeat_interaction_forecast(initial, {**spec, **window}),
                  "target": target_spec(initial, through=window["target_end"])} for window in declared["folds"]]
        folds[1].update(forecast=None, target=None)
        report = evaluate_repeat_interaction_forecasts(initial, plan, folds)
        self.assertFalse(report["folds"][2]["risk_change"]["compared_with_previous_planned_origin"])

    def test_all_missing_preserves_empty_bins_and_null_metrics(self):
        initial, spec = fixture()
        plan = make_repeat_interaction_plan(initial, spec, schedule())
        report = evaluate_repeat_interaction_forecasts(initial, plan, [
            {"origin_at": t, "forecast": None, "target": None} for t in (10, 15)])
        self.assertEqual(report["status"], "UNSCORED")
        for model in report["models"].values():
            self.assertEqual(model["n"], 0)
            self.assertIsNone(model["pooled_brier"])
            self.assertIsNone(model["macro_brier"])
            self.assertTrue(all(row["count"] == 0 and row["observed_fraction"] is None for row in model["bins"]))

    def test_supplied_empty_initial_risk_is_distinct_from_a_missing_forecast(self):
        initial, spec = fixture(events=False)
        plan = make_repeat_interaction_plan(initial, spec, schedule())
        first = make_repeat_interaction_forecast(initial, spec)
        history = ingest_records(initial, [interaction("new-history-AB", A, B, 11)], received_at=LATER)
        second = make_repeat_interaction_forecast(history, {
            **spec, **schedule()["folds"][1], "knowledge_cutoff": len(history.records)})
        journal = ingest_records(history, [interaction("new-target-AB", A, B, 16)], received_at=LATER)
        report = evaluate_repeat_interaction_forecasts(journal, plan, [
            {"origin_at": 10, "forecast": first, "target": target_spec(history)},
            {"origin_at": 15, "forecast": second, "target": target_spec(journal, through=19)},
        ])
        self.assertEqual(report["status"], "PARTIALLY_SCORED")
        self.assertEqual(report["counts"]["missing_forecast_origins"], 0)
        self.assertEqual(report["counts"]["full_plan_risk_pair_origin_count"], 1)
        self.assertEqual(report["folds"][0]["risk_pairs"], 0)
        self.assertTrue(all(model["n"] == 1 and model["macro_brier"] is None for model in report["models"].values()))

    def test_incomplete_followup_retains_positive_evidence_without_scoring_it(self):
        _, _, _, plan, journal, folds = case()
        folds[1]["target"]["observed_through"] = 18
        report = evaluate_repeat_interaction_forecasts(journal, plan, folds)
        self.assertEqual(report["counts"]["scorable_pairs_across_supplied_origins"], 3)
        self.assertEqual(report["unscored_reasons"]["followup_not_closed"], 4)
        self.assertEqual(report["counts"]["known_positive_unscored_pairs_across_supplied_origins"], 1)
        for model in report["models"].values():
            self.assertEqual(sum(row["count"] for row in model["bins"]), 3)
            self.assertIsNone(model["macro_brier"])

    def test_partial_target_coverage_uses_same_pairs_for_every_model(self):
        _, _, _, plan, journal, folds = case()
        journal = revise(journal, "history-coverage", "coverage-end-15", payload={
            "population": "fictional-cohort", "layer": "communication", "actors": list(ACTORS), "status": "complete"})
        value = journal.to_dict()
        value["records"][-1]["valid_interval"] = [0, 15]
        journal = EventDataset.from_mapping(value)
        journal = ingest_records(journal, [coverage("AB-followup", [A, B], 15, 19)], received_at=LATER)
        folds[1]["target"] = target_spec(journal, through=19)
        report = evaluate_repeat_interaction_forecasts(journal, plan, folds)
        self.assertEqual(report["status"], "PARTIALLY_SCORED")
        self.assertEqual(report["unscored_reasons"]["coverage_incomplete"], 2)
        self.assertEqual(report["counts"]["scorable_pairs_across_supplied_origins"], 5)
        self.assertTrue(all(model["n"] == 5 for model in report["models"].values()))
        # Both origins have some eligible pairs, so full-plan macro is defined.
        self.assertTrue(all(model["macro_brier"] is not None for model in report["models"].values()))

    def test_target_revision_versions_are_independent_and_old_report_replays(self):
        _, _, _, plan, journal, folds = case()
        old = evaluate_repeat_interaction_forecasts(journal, plan, folds)
        changed = revise(journal, "future-BA", "target-BA-retracted", retract=True)
        newer = deepcopy(folds)
        newer[0]["target"] = target_spec(changed)
        new = evaluate_repeat_interaction_forecasts(changed, plan, newer)
        self.assertGreater(newer[0]["target"]["knowledge_cutoff"], newer[1]["target"]["knowledge_cutoff"])
        self.assertNotEqual(old["content_hash"], new["content_hash"])
        self.assertEqual(old["folds"][1], new["folds"][1])
        self.assertEqual(evaluate_repeat_interaction_forecasts(changed, plan, folds), old)

    def test_plan_and_old_versions_ignore_a_later_journal_tail(self):
        initial, spec, declared, plan, journal, folds = case()
        self.assertEqual(make_repeat_interaction_plan(journal, spec, declared), plan)
        self.assertEqual(plan["journal"]["initial_prefix_hash"], initial.content_hash)
        old = evaluate_repeat_interaction_forecasts(journal, plan, folds)
        later = ingest_records(journal, [interaction("later", D, A, 100)], received_at=LATER)
        self.assertEqual(evaluate_repeat_interaction_forecasts(later, plan, folds), old)

    def test_equivalent_utc_microsecond_windows_have_same_arithmetic(self):
        _, _, _, tick_plan, tick_journal, tick_folds = case()
        _, _, _, utc_plan, utc_journal, utc_folds = case(utc=True)
        tick = evaluate_repeat_interaction_forecasts(tick_journal, tick_plan, tick_folds)
        utc = evaluate_repeat_interaction_forecasts(utc_journal, utc_plan, utc_folds)
        self.assertEqual(tick["counts"], utc["counts"])
        self.assertEqual(tick["models"], utc["models"])

    def test_schedule_rejects_overlap_changed_widths_unordered_or_missing_origins(self):
        initial, spec = fixture()
        variants = []
        for key, value in (("origin_at", 13), ("recent_start", 9), ("target_end", 20)):
            bad = schedule()
            bad["folds"][1][key] = value
            variants.append(bad)
        bad = schedule()
        bad["folds"].reverse()
        variants.append(bad)
        bad = schedule()
        bad["folds"].pop()
        variants.append(bad)
        for bad in variants:
            with self.subTest(schedule=bad), self.assertRaises(ValueError):
                make_repeat_interaction_plan(initial, spec, bad)

    def test_invalid_or_rehashed_forecast_is_not_a_missing_slot(self):
        _, _, _, plan, journal, folds = case()
        bad = deepcopy(folds)
        bad[1]["forecast"]["predictions"][0]["probabilities"]["historical_poisson"] = 0.123
        rehash(bad[1]["forecast"])
        with self.assertRaisesRegex(ValueError, "original journal history"):
            evaluate_repeat_interaction_forecasts(journal, plan, bad)
        for field, value in (("history_start", 1), ("topics", []), ("actors", [A, B])):
            bad = deepcopy(folds)
            bad[1]["forecast"]["specification"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "plan's roster, stream and window"):
                evaluate_repeat_interaction_forecasts(journal, plan, bad)

    def test_missing_fold_reordered_origins_null_mismatch_and_cutoff_regression_fail(self):
        _, _, _, plan, journal, folds = case()
        variants = [folds[:1], list(reversed(folds))]
        bad = deepcopy(folds)
        bad[1]["forecast"] = None
        variants.append(bad)
        bad = deepcopy(folds)
        bad[1]["forecast"]["specification"]["knowledge_cutoff"] = 0
        variants.append(bad)
        for bad in variants:
            with self.subTest(folds=bad), self.assertRaises(ValueError):
                evaluate_repeat_interaction_forecasts(journal, plan, bad)

    def test_modified_policy_and_modified_initial_prefix_are_rejected(self):
        _, _, _, plan, journal, folds = case()
        bad = deepcopy(plan)
        bad["policies"]["risk_set"] = "intersection_with_future"
        rehash(bad)
        with self.assertRaisesRegex(ValueError, "initial journal history"):
            evaluate_repeat_interaction_forecasts(journal, bad, folds)
        value = journal.to_dict()
        value["records"][0]["source"]["revision"] = "tampered-past"
        changed = EventDataset.from_mapping(value)
        with self.assertRaisesRegex(ValueError, "initial journal history"):
            evaluate_repeat_interaction_forecasts(changed, plan, folds)

    def test_real_cli_round_trip_relative_paths_and_explicit_missing_slot(self):
        initial, spec, declared, expected_plan, journal, folds = case(count=3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def save(name, value):
                path = root / name
                path.write_text(json.dumps(value), encoding="utf-8")
                return str(path)
            def run(arguments):
                output, error = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    result = main(arguments)
                self.assertEqual(result, 0, error.getvalue())
                return json.loads(output.getvalue())
            plan = run(["forecast", "interaction-plan", save("initial.json", initial.to_dict()),
                        save("spec.json", spec), save("schedule.json", declared)])
            self.assertEqual(plan, expected_plan)
            entries = []
            for index, fold in enumerate(folds):
                if fold["forecast"] is None:
                    entries.append(fold)
                else:
                    forecast_name, target_name = f"forecast-{index}.json", f"target-{index}.json"
                    save(forecast_name, fold["forecast"])
                    save(target_name, fold["target"])
                    entries.append({"origin_at": fold["origin_at"], "forecast": forecast_name, "target": target_name})
            report = run(["forecast", "interaction-evaluate", save("journal.json", journal.to_dict()),
                          save("plan.json", plan), save("folds.json", {
                              "schema": "sociolab.repeat-interaction-fold-manifest.v1", "folds": entries})])
            self.assertEqual(report, evaluate_repeat_interaction_forecasts(journal, plan, folds))


if __name__ == "__main__":
    unittest.main()
