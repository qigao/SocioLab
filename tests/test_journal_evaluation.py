"""Synthetic receipt-version plans, leakage gates, and saved-artifact scoring."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.behavior_forecast import make_behavior_forecast, score_behavior_forecast
from sociolab.events import EventDataset, ingest_records
from sociolab.forecast_evaluation import _summaries
from sociolab.journal_evaluation import make_journal_forecast_plan, evaluate_journal_forecasts
from sociolab.journal_forecast import make_journal_forecast_history, make_journal_forecast_target
from sociolab.panels import LongitudinalPanel
from test_journal_forecast import ACTORS, ALIAS, LATER, fixture, observation, raw, revise, with_target


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def rehash(value):
    value["content_hash"] = digest({key: item for key, item in value.items() if key != "content_hash"})
    return value


def schedule(initial_k):
    return {"schema": "sociolab.journal-forecast-schedule.v1", "folds": [
        {"target_time_index": 2, "target_at": 20, "history_knowledge_cutoff": initial_k, "target_knowledge_cutoff": initial_k + 4},
        {"target_time_index": 3, "target_at": 30, "history_knowledge_cutoff": initial_k + 8, "target_knowledge_cutoff": initial_k + 12},
    ]}


def next_spec(initial, initial_k):
    spec = deepcopy(initial)
    spec["knowledge_cutoff"] = initial_k + 8
    spec["waves"].append({"time_index": 2, "at": 20})
    spec["target_at"] = 30
    spec["forecast_specification"]["target_time_index"] = 3
    return spec


def receipt_case(*, initial_network_rank_failure=False):
    initial, initial_spec = fixture()
    if initial_network_rank_failure:
        value = initial.to_dict()
        for record in value["records"]:
            if record["record_id"] in {"tie-AB", "tie-BA", "tie-CD"}:
                record["payload"]["strength"] = 0
        initial = EventDataset.from_mapping(value)
    initial_k = len(initial.records)
    planned = schedule(initial_k)
    plan = make_journal_forecast_plan(initial, initial_spec, planned)
    first_history = make_journal_forecast_history(initial, initial_spec)
    first_forecast = make_behavior_forecast(LongitudinalPanel.from_mapping(first_history["history"]), initial_spec["forecast_specification"])
    journal = with_target(initial)
    first_target = make_journal_forecast_target(journal, initial_spec, first_forecast, initial_k + 4)["target"]
    journal = revise(journal, "behavior-0-" + ACTORS[0], "old-behavior-revised", payload={"actor": ALIAS, "name": "reported_level", "value": 2})
    journal = revise(journal, "tie-AB", "old-tie-revised", payload={
        "layer": "friendship", "source": ACTORS[0], "target": ACTORS[1], "directed": True, "strength": 0})
    journal = revise(journal, "target-" + ACTORS[0], "first-target-revised-for-history", payload={"actor": ALIAS, "name": "reported_level", "value": 6})
    journal = ingest_records(journal, [raw("new-origin-tie", "relation.changed", {
        "layer": "friendship", "source": ACTORS[3], "target": ACTORS[0], "directed": True, "strength": 1}, at=20)], received_at=LATER)
    assert len(journal.records) == initial_k + 8
    second_spec = next_spec(initial_spec, initial_k)
    second_history = make_journal_forecast_history(journal, second_spec)
    second_forecast = make_behavior_forecast(LongitudinalPanel.from_mapping(second_history["history"]), second_spec["forecast_specification"])
    journal = ingest_records(journal, [observation("second-target-" + actor, actor, value, 30)
                                      for actor, value in zip(ACTORS, (5, 4, 7, 3))], received_at=LATER)
    second_target = make_journal_forecast_target(journal, second_spec, second_forecast, initial_k + 12)["target"]
    journal = revise(journal, "first-target-revised-for-history", "first-target-late-score-version", payload={
        "actor": ALIAS, "name": "reported_level", "value": 8})
    return {
        "initial": initial, "initial_spec": initial_spec, "schedule": planned, "plan": plan, "journal": journal,
        "folds": [{"forecast": first_forecast, "target": first_target}, {"forecast": second_forecast, "target": second_target}],
        "histories": [first_history, second_history], "second_spec": second_spec,
    }


class JournalEvaluationTests(unittest.TestCase):
    def test_plan_uses_only_exact_initial_prefix_and_does_not_fit(self):
        initial, spec = fixture()
        declared = schedule(len(initial.records))
        with patch.object(np.linalg, "lstsq", side_effect=AssertionError("planning cannot fit")) as solver, \
                patch("sociolab.behavior_forecast.make_behavior_forecast", side_effect=AssertionError("planning cannot issue")):
            plan = make_journal_forecast_plan(initial, spec, declared)
        solver.assert_not_called()
        self.assertGreater(plan["schedule"]["folds"][-1]["target_knowledge_cutoff"], len(initial.records))
        self.assertEqual(plan["journal"]["initial_prefix_hash"], initial.content_hash)
        self.assertEqual(plan["initial_specification"], spec)
        self.assertEqual(plan["metrics"]["primary_aggregation"], "pooled")
        self.assertEqual(plan["content_hash"], digest({key: value for key, value in plan.items() if key != "content_hash"}))
        with self.assertRaisesRegex(ValueError, "exactly its initial receipt prefix"):
            make_journal_forecast_plan(with_target(initial), spec, declared)

    def test_history_revisions_are_reconstructed_and_reported_without_identity_values(self):
        case = receipt_case()
        report = evaluate_journal_forecasts(case["plan"], case["journal"], case["folds"])
        self.assertEqual(report["actor_count"], 4)
        self.assertEqual(report["fold_count"], 2)
        self.assertEqual(report["actor_forecast_count"], 8)
        self.assertIsNone(report["folds"][0]["history_revision"])
        revision = report["folds"][1]["history_revision"]
        self.assertEqual(revision["overlap_wave_count"], 2)
        self.assertEqual(revision["behavior_changed_wave_count"], 1)
        self.assertEqual(revision["behavior_changed_actor_wave_count"], 1)
        self.assertEqual(revision["network_changed_wave_count"], 1)
        self.assertEqual(revision["network_changed_edge_wave_count"], 1)
        self.assertEqual(revision["source_revision_changed_wave_count"], 2)
        self.assertNotEqual(revision["old_waves_before_hash"], revision["old_waves_after_hash"])
        previous = revision["previous_target_comparison"]
        self.assertEqual(previous["target_time_index"], 2)
        self.assertEqual(previous["changed_actor_count"], 1)
        self.assertNotEqual(previous["prior_target_behavior_hash"], previous["appended_behavior_hash"])
        for index, fold in enumerate(report["folds"]):
            self.assertEqual(fold["history_bundle_hash"], case["histories"][index]["content_hash"])
            self.assertEqual(fold["score_hash"], digest(fold["score"]))
            self.assertEqual(fold["target_hash"], digest(case["folds"][index]["target"]))
        self.assertEqual(report["content_hash"], digest({key: value for key, value in report.items() if key != "content_hash"}))

    def test_evaluation_reuses_real_scorer_and_summary_without_refitting(self):
        case = receipt_case()
        with patch.object(np.linalg, "lstsq", side_effect=AssertionError("evaluation cannot refit")) as solver, \
                patch("sociolab.behavior_forecast.make_behavior_forecast", side_effect=AssertionError("no reissuance")), \
                patch("sociolab.journal_evaluation.score_behavior_forecast", wraps=score_behavior_forecast) as scorer, \
                patch("sociolab.journal_evaluation._summaries", wraps=_summaries) as summaries:
            report = evaluate_journal_forecasts(case["plan"], case["journal"], case["folds"])
        solver.assert_not_called()
        self.assertEqual(scorer.call_count, 2)
        self.assertEqual(summaries.call_count, 1)
        scores = [score_behavior_forecast(fold["forecast"], fold["target"]) for fold in case["folds"]]
        expected_models, expected_comparisons = _summaries(scores)
        self.assertEqual(report["models"], expected_models)
        self.assertEqual(report["comparisons"], expected_comparisons)
        self.assertEqual([fold["score"] for fold in report["folds"]], scores)

    def test_explicit_later_nonmonotone_target_versions_reuse_the_same_forecasts(self):
        case = receipt_case()
        initial_k = len(case["initial"].records)
        different_schedule = deepcopy(case["schedule"])
        different_schedule["folds"][0]["target_knowledge_cutoff"] = initial_k + 13
        self.assertGreater(different_schedule["folds"][0]["target_knowledge_cutoff"], different_schedule["folds"][1]["target_knowledge_cutoff"])
        alternative = make_journal_forecast_plan(case["initial"], case["initial_spec"], different_schedule)
        folds = deepcopy(case["folds"])
        folds[0]["target"] = make_journal_forecast_target(case["journal"], case["initial_spec"], folds[0]["forecast"], initial_k + 13)["target"]
        original = evaluate_journal_forecasts(case["plan"], case["journal"], case["folds"])
        revised = evaluate_journal_forecasts(alternative, case["journal"], folds)
        self.assertEqual([fold["forecast_hash"] for fold in original["folds"]], [fold["forecast_hash"] for fold in revised["folds"]])
        self.assertNotEqual(original["plan_hash"], revised["plan_hash"])
        self.assertNotEqual(original["folds"][0]["target_hash"], revised["folds"][0]["target_hash"])
        self.assertNotEqual(original["models"]["persistence"]["clipped"], revised["models"]["persistence"]["clipped"])
        with self.assertRaisesRegex(ValueError, "declared journal receipt version"):
            evaluate_journal_forecasts(case["plan"], case["journal"], folds)

    def test_same_observed_target_values_with_wrong_receipt_revision_are_rejected(self):
        case = receipt_case()
        folds = deepcopy(case["folds"])
        initial_k = len(case["initial"].records)
        other_version = make_journal_forecast_target(case["journal"], case["initial_spec"], folds[0]["forecast"], initial_k + 5)["target"]
        self.assertEqual(other_version["behavior"], folds[0]["target"]["behavior"])
        self.assertNotEqual(other_version["source_revision"], folds[0]["target"]["source_revision"])
        folds[0]["target"] = other_version
        with self.assertRaisesRegex(ValueError, "including its revision"):
            evaluate_journal_forecasts(case["plan"], case["journal"], folds)

    def test_history_stream_gate_sees_raw_retracted_assertions_and_invalid_values(self):
        initial, spec = fixture()
        for value in (None, True, 2.0, 3):
            with self.subTest(value=value):
                contaminated = ingest_records(initial, [observation("future-known", ACTORS[0], value, 20)], received_at=LATER)
                contaminated = revise(contaminated, "future-known", "future-retracted", retract=True)
                new_spec = {**spec, "knowledge_cutoff": len(contaminated.records)}
                with self.assertRaisesRegex(ValueError, "target-or-later assertion"):
                    make_journal_forecast_plan(contaminated, new_spec, schedule(len(contaminated.records)))
        # The gate is over the entire declared measurement stream, including a
        # known person outside the forecast roster whose assertion was retracted.
        outside = ingest_records(initial, [
            raw("outside-entity", "entity.observed", {"entity_id": "outside-person", "entity_type": "person"}),
            observation("outside-future", "outside-person", None, 30),
        ], received_at=LATER)
        outside = revise(outside, "outside-future", "outside-retracted", retract=True)
        with self.assertRaisesRegex(ValueError, "measurement stream"):
            make_journal_forecast_plan(outside, {**spec, "knowledge_cutoff": len(outside.records)}, schedule(len(outside.records)))

    def test_history_gate_uses_both_occurrence_and_future_interval_extent(self):
        initial, spec = fixture()
        for occurred, interval in ((7, [7, None]), (7, [7, 21]), (7, [25, 30]), (25, [5, 10])):
            with self.subTest(occurred=occurred, interval=interval):
                contaminated = ingest_records(initial, [observation("interval", ACTORS[0], 3, occurred, interval=interval)], received_at=LATER)
                with self.assertRaisesRegex(ValueError, "target-or-later assertion"):
                    make_journal_forecast_plan(contaminated, {**spec, "knowledge_cutoff": len(contaminated.records)}, schedule(len(contaminated.records)))
        ended = ingest_records(initial, [observation("ended-before-target", ACTORS[0], 3, 11, interval=[11, 20])], received_at=LATER)
        make_journal_forecast_plan(ended, {**spec, "knowledge_cutoff": len(ended.records)}, schedule(len(ended.records)))
        different_stream = ingest_records(initial, [
            observation("different-system-future", ACTORS[0], None, 30, system="other-survey"),
            observation("different-attribute-future", ACTORS[0], True, 30, name="other_attribute"),
        ], received_at=LATER)
        make_journal_forecast_plan(different_stream, {**spec, "knowledge_cutoff": len(different_stream.records)}, schedule(len(different_stream.records)))

    def test_target_fact_ancestry_blocks_old_time_or_attribute_revision_bypass(self):
        for attribute, occurred in (("reported_level", 9), ("old_attribute", 20)):
            with self.subTest(attribute=attribute, occurred=occurred):
                initial, spec = fixture()
                initial = ingest_records(initial, [observation("old-fact", ACTORS[1], None, occurred, name=attribute)], received_at=LATER)
                spec["knowledge_cutoff"] = len(initial.records)
                k = len(initial.records)
                declared = schedule(k)
                plan = make_journal_forecast_plan(initial, spec, declared)
                history = make_journal_forecast_history(initial, spec)
                forecast = make_behavior_forecast(LongitudinalPanel.from_mapping(history["history"]), spec["forecast_specification"])
                old = next(record for record in initial.records if record["record_id"] == "old-fact")
                correction = {key: value for key, value in old.items() if key not in {"recorded_at", "ingest_seq"}}
                correction.update(record_id="old-fact-now-target", supersedes="old-fact", occurred_at=20,
                                  payload={"actor": ACTORS[0], "name": "reported_level", "value": 4})
                correction["source"] = {**correction["source"], "record_id": "old-fact-now-target", "revision": "corrected"}
                journal = ingest_records(initial, [correction] + [observation("fresh-target-" + actor, actor, value, 20)
                                        for actor, value in zip(ACTORS[1:], (3, 5, 2))], received_at=LATER)
                target = make_journal_forecast_target(journal, spec, forecast, k + 4)["target"]
                first = {"forecast": forecast, "target": target}
                # The first origin must reject before any second-origin input is
                # used: the original fact existed before issuance under old fields.
                with self.assertRaisesRegex(ValueError, "first received at or before"):
                    evaluate_journal_forecasts(plan, journal, [first, deepcopy(first)])

    def test_future_stream_gate_also_runs_at_later_origins(self):
        case = receipt_case()
        journal = case["journal"].to_dict()
        # Insert a future assertion and retraction just before the second history
        # cutoff, shifting later receipts. The first plan binding remains intact.
        k = len(case["initial"].records)
        base = deepcopy(journal)
        base["records"] = base["records"][:k + 8]
        prefix = EventDataset.from_mapping(base)
        prefix = ingest_records(prefix, [observation("second-origin-future", ACTORS[0], None, 30)], received_at=LATER)
        prefix = revise(prefix, "second-origin-future", "second-origin-retracted", retract=True)
        declared = deepcopy(case["schedule"])
        declared["folds"][1]["history_knowledge_cutoff"] = k + 10
        declared["folds"][1]["target_knowledge_cutoff"] = k + 14
        plan = make_journal_forecast_plan(case["initial"], case["initial_spec"], declared)
        with self.assertRaisesRegex(ValueError, "target-or-later assertion"):
            evaluate_journal_forecasts(plan, prefix, case["folds"])

    def test_tail_appends_do_not_change_evaluation_contents_or_hash(self):
        case = receipt_case()
        original = evaluate_journal_forecasts(case["plan"], case["journal"], case["folds"])
        appended = ingest_records(case["journal"], [observation("much-later-measurement", ACTORS[0], None, 100)], received_at=LATER)
        self.assertNotEqual(appended.content_hash, case["journal"].content_hash)
        self.assertEqual(evaluate_journal_forecasts(case["plan"], appended, case["folds"]), original)

    def test_not_estimable_origin_is_retained_and_whole_plan_metrics_are_null(self):
        case = receipt_case(initial_network_rank_failure=True)
        self.assertEqual(case["folds"][0]["forecast"]["models"]["network_lag_ols"]["status"], "NOT_ESTIMABLE")
        self.assertEqual(case["folds"][1]["forecast"]["models"]["network_lag_ols"]["status"], "OK")
        report = evaluate_journal_forecasts(case["plan"], case["journal"], case["folds"])
        network = report["models"]["network_lag_ols"]
        self.assertEqual(network["status"], "NOT_ESTIMABLE")
        self.assertEqual(network["expected_fold_count"], 2)
        self.assertEqual(network["available_fold_count"], 1)
        self.assertEqual(network["expected_actor_forecast_count"], 8)
        self.assertEqual(network["available_actor_forecast_count"], 4)
        self.assertEqual(network["failed_target_time_indices"], [2])
        self.assertIsNone(network["raw"])
        self.assertIsNone(network["clipped"])
        self.assertEqual(report["models"]["persistence"]["status"], "OK")
        for comparison in report["comparisons"].values():
            self.assertEqual(comparison["status"], "NOT_ESTIMABLE")
            self.assertIsNone(comparison["clipped"])

    def test_strict_schedule_contract_and_no_silent_fold_changes(self):
        initial, spec = fixture()
        k = len(initial.records)
        mutations = [
            lambda value: value.update(extra=True),
            lambda value: value.update(schema="wrong"),
            lambda value: value.update(folds=value["folds"][:1]),
            lambda value: value["folds"][0].update(extra=True),
            lambda value: value["folds"][0].update(history_knowledge_cutoff=True),
            lambda value: value["folds"][0].update(history_knowledge_cutoff=k - 1),
            lambda value: value["folds"][0].update(target_knowledge_cutoff=k),
            lambda value: value["folds"][1].update(history_knowledge_cutoff=k),
            lambda value: value["folds"][1].update(target_time_index=4),
            lambda value: value["folds"][1].update(target_at=31),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                declared = schedule(k)
                mutation(declared)
                with self.assertRaises(ValueError):
                    make_journal_forecast_plan(initial, spec, declared)
        case = receipt_case()
        for folds in ([], case["folds"][:1], list(reversed(case["folds"])), [case["folds"][0]] * 2, tuple(case["folds"])):
            with self.assertRaises(ValueError):
                evaluate_journal_forecasts(case["plan"], case["journal"], folds)
        changed = deepcopy(case["folds"])
        changed[0]["score"] = {}
        with self.assertRaisesRegex(ValueError, "exact fields"):
            evaluate_journal_forecasts(case["plan"], case["journal"], changed)

    def test_tampered_plan_and_initial_journal_binding_are_rejected(self):
        case = receipt_case()
        changed_plan = deepcopy(case["plan"])
        changed_plan["schedule"]["folds"][0]["target_knowledge_cutoff"] += 1
        with self.assertRaisesRegex(ValueError, "content hash"):
            evaluate_journal_forecasts(changed_plan, case["journal"], case["folds"])
        changes = [
            lambda value: value.update(extra=True),
            lambda value: value.update(training_policy="expanding_immutable_prefix"),
            lambda value: value.update(target_version_policy="whatever_is_latest"),
            lambda value: value["journal"].update(initial_panel_hash="invalid"),
            lambda value: value["journal"].update(initial_knowledge_cutoff=True),
            lambda value: value["scope"].update(historical_as_of_availability_verified=True),
            lambda value: value["scope"].update(receipt_prefix_enforced=1),
            lambda value: value["metrics"].update(primary_aggregation="macro"),
        ]
        for mutation in changes:
            changed_plan = deepcopy(case["plan"])
            mutation(changed_plan)
            rehash(changed_plan)
            with self.assertRaises(ValueError):
                evaluate_journal_forecasts(changed_plan, case["journal"], case["folds"])
        for mutation in (
            lambda value: value.update(source_revision="new-envelope"),
            lambda value: value["clock"].update(run_id="different-run"),
            lambda value: next(record for record in value["records"] if record["record_id"] == "behavior-0-" + ACTORS[1])["payload"].update(value=3),
        ):
            journal = case["journal"].to_dict()
            mutation(journal)
            with self.assertRaises(ValueError):
                evaluate_journal_forecasts(case["plan"], EventDataset.from_mapping(journal), case["folds"])

    def test_utc_schedule_uses_exact_source_times_and_equivalent_notation(self):
        initial, spec = fixture(utc=True)
        k = len(initial.records)
        from test_journal_forecast import source_time
        declared = {"schema": "sociolab.journal-forecast-schedule.v1", "folds": [
            {"target_time_index": 2, "target_at": source_time(20, True).replace("Z", "+00:00"),
             "history_knowledge_cutoff": k, "target_knowledge_cutoff": k + 4},
            {"target_time_index": 3, "target_at": source_time(30, True),
             "history_knowledge_cutoff": k + 8, "target_knowledge_cutoff": k + 12},
        ]}
        plan = make_journal_forecast_plan(initial, spec, declared)
        self.assertEqual(plan["schedule"]["folds"][0]["target_at"], spec["target_at"])
        declared["folds"][1]["target_at"] = source_time(31, True)
        with self.assertRaisesRegex(ValueError, "consecutively"):
            make_journal_forecast_plan(initial, spec, declared)

    def test_plan_and_inputs_remain_private_or_unchanged_and_report_is_aggregate(self):
        case = receipt_case()
        before_plan, before_folds = deepcopy(case["plan"]), deepcopy(case["folds"])
        before_journal = case["journal"].to_dict()
        report = evaluate_journal_forecasts(case["plan"], case["journal"], case["folds"])
        self.assertEqual(case["plan"], before_plan)
        self.assertEqual(case["folds"], before_folds)
        self.assertEqual(case["journal"].to_dict(), before_journal)
        self.assertTrue(case["plan"]["scope"]["contains_private_actor_records"])
        serialized = json.dumps(report)
        for actor in ACTORS + [ALIAS]:
            self.assertNotIn(actor, serialized)
        for key in ('"actors"', '"behavior"', '"edges"', '"raw_predictions"', '"clipped_predictions"', '"records"', '"path"'):
            self.assertNotIn(key, serialized)
        self.assertTrue(report["scope"]["history_raw_assertion_future_stream_gate_enforced"])
        self.assertTrue(report["scope"]["target_fact_ancestry_gate_enforced"])
        self.assertTrue(report["scope"]["late_history_revisions_allowed"])
        for flag in ("previous_target_equals_next_history_required", "historical_as_of_availability_verified",
                     "forecast_issued_before_target_observation_verified", "live_subscription", "actor_forecast_rows_independent",
                     "causal_effect_identified", "empirical_forecast_validated", "refitting_performed_by_evaluation"):
            self.assertFalse(report["scope"][flag])


if __name__ == "__main__":
    unittest.main()
