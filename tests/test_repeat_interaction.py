"""Future-window, receipt and observation risks through the real journal APIs."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
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
from sociolab.repeat_interaction import (
    make_repeat_interaction_forecast, score_repeat_interaction_forecast,
)


ACTORS = ["fictional-person-A", "fictional-person-B", "fictional-person-C", "fictional-person-D"]
A, B, C, D = ACTORS
ALIAS = "fictional-alias-A"
RECEIPT = "2026-01-01T00:00:00.000010Z"
LATER = "2026-01-01T00:00:00.000020Z"
MODELS = ("historical_poisson", "recent_poisson", "recent_occurrence")


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


def at(value, utc=False):
    if value is None or not utc:
        return value
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value)
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def raw(record_id, kind, payload, *, when=0, interval=None):
    return {
        "record_id": record_id, "fact_id": record_id, "operation": "assert", "supersedes": None,
        "kind": kind, "occurred_at": when, "valid_interval": interval,
        "source": {"system": "fictional-study", "record_id": record_id,
                   "revision": "fixture-1", "evidence_ref": "synthetic:" + record_id},
        "payload": payload,
    }


def interaction(record_id, source, target, when, *, utc=False, action="reply", topic="task"):
    return raw(record_id, "interaction.observed", {
        "actor": source, "target": target, "action": action, "topic": topic,
    }, when=at(when, utc))


def coverage(record_id, actors, start, end=None, *, utc=False):
    return raw(record_id, "coverage.observed", {
        "population": "fictional-cohort", "layer": "communication",
        "actors": list(actors), "status": "complete",
    }, when=at(start, utc), interval=[at(start, utc), at(end, utc)])


def membership(record_id, actor, start, end=None, *, status="present", utc=False):
    return raw(record_id, "membership.observed", {
        "actor": actor, "population": "fictional-cohort", "status": status,
    }, when=at(start, utc), interval=[at(start, utc), at(end, utc)])


def fixture(*, utc=False, events=True, coverage_end=None, member_starts=None, member_ends=None):
    dataset = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "fictional-repeat-interactions",
        "origin": "synthetic", "source_revision": "fixture-envelope-1",
        "clock": {"kind": "utc"} if utc else {"kind": "ticks", "run_id": "fictional-repeat-run"},
        "records": [],
    })
    starts, ends = member_starts or {}, member_ends or {}
    records = [raw("entity-" + actor, "entity.observed", {
        "entity_id": actor, "entity_type": "person",
    }, when=at(0, utc)) for actor in ACTORS + [ALIAS]]
    records.append(raw("alias-map", "identity.mapped", {"alias": ALIAS, "canonical": A}, when=at(0, utc)))
    for actor in ACTORS:
        start = starts.get(actor, 0)
        if start:
            records.append(membership("before-member-" + actor, actor, 0, start, status="absent", utc=utc))
        records.append(membership("member-" + actor, actor, start, ends.get(actor), utc=utc))
    records.append(coverage("history-coverage", ACTORS, 0, coverage_end, utc=utc))
    if events:
        records.extend([
            interaction("AB-at-start", A, B, 0, utc=utc),
            interaction("AB-at-recent", A, B, 5, utc=utc),
            interaction("AB-last", ALIAS, B, 9, utc=utc),
            interaction("BA-old", B, A, 2, utc=utc),
            interaction("CD-recent", C, D, 6, utc=utc),
        ])
    dataset = ingest_records(dataset, records, received_at=RECEIPT)
    spec = {
        "schema": "sociolab.repeat-interaction-spec.v1", "knowledge_cutoff": len(dataset.records),
        "source_reference": None, "observation_reference": "Invented directed reply observation protocol.",
        "actors": list(ACTORS), "population": "fictional-cohort", "layer": "communication",
        "actions": ["reply"], "topics": ["task"],
        "history_start": at(0, utc), "recent_start": at(5, utc),
        "origin_at": at(10, utc), "target_end": at(14, utc),
        "risk_set": "history_positive_ordered_pairs",
    }
    return dataset, spec


def target_spec(dataset, *, through=14, utc=False):
    return {
        "schema": "sociolab.repeat-interaction-target.v1", "knowledge_cutoff": len(dataset.records),
        "observed_through": at(through, utc),
        "observation_reference": "Invented follow-up observation declaration.",
    }


def with_target(dataset, *, utc=False):
    return ingest_records(dataset, [
        interaction("future-AB-at-origin", A, B, 10, utc=utc),
        interaction("future-AB-repeat", A, B, 12, utc=utc),
        interaction("future-BA", B, A, 13, utc=utc),
        interaction("future-CD-at-end", C, D, 14, utc=utc),
        interaction("future-new-pair", A, C, 11, utc=utc),
    ], received_at=LATER)


def revise(dataset, record_id, new_id, *, when=None, payload=None, retract=False):
    old = next(row for row in dataset.records if row["record_id"] == record_id)
    row = {key: deepcopy(value) for key, value in old.items() if key not in {"ingest_seq", "recorded_at"}}
    row.update(record_id=new_id, supersedes=record_id, operation="retract" if retract else "assert")
    row["source"].update(record_id=new_id, revision="fixture-correction-2")
    if when is not None:
        row["occurred_at"] = when
    if retract:
        row["payload"] = None
    elif payload is not None:
        row["payload"] = payload
    return ingest_records(dataset, [row], received_at=LATER)


def expected_probabilities():
    # Analytic values from five authored events; no implementation helper is used.
    return {
        (A, B): {"historical_poisson": 1 - math.exp(-1.2),
                 "recent_poisson": 1 - math.exp(-1.6), "recent_occurrence": 1.0},
        (B, A): {"historical_poisson": 1 - math.exp(-0.4),
                 "recent_poisson": 0.0, "recent_occurrence": 0.0},
        (C, D): {"historical_poisson": 1 - math.exp(-0.4),
                 "recent_poisson": 1 - math.exp(-0.8), "recent_occurrence": 1.0},
    }


class RepeatInteractionTests(unittest.TestCase):
    def assert_unscored_models(self, report):
        self.assertEqual(set(report["models"]), set(MODELS))
        for model in report["models"].values():
            self.assertEqual((model["status"], model["n"]), ("UNSCORED", 0))
            for metric in ("brier", "mean_predicted_probability", "observed_fraction"):
                self.assertIsNone(model[metric])

    def assert_metrics(self, report, outcomes):
        probabilities = expected_probabilities()
        for name in MODELS:
            values = [probabilities[pair][name] for pair in outcomes]
            expected_brier = sum((probabilities[pair][name] - y) ** 2 for pair, y in outcomes.items()) / len(outcomes)
            actual = report["models"][name]
            self.assertEqual((actual["status"], actual["n"]), ("SCORED", len(outcomes)))
            self.assertAlmostEqual(actual["brier"], expected_brier, places=14)
            self.assertAlmostEqual(actual["mean_predicted_probability"], sum(values) / len(values), places=14)
            self.assertEqual(actual["observed_fraction"], sum(outcomes.values()) / len(outcomes))

    def test_source_window_boundaries_aliases_direction_and_independent_probabilities(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        rows = {(row["source"], row["target"]): row for row in forecast["predictions"]}
        self.assertEqual(set(rows), {(A, B), (B, A), (C, D)})
        for pair, counts in { (A, B): (3, 2, 1), (B, A): (1, 0, 8), (C, D): (1, 1, 4) }.items():
            self.assertEqual(tuple(rows[pair][key] for key in ("history_count", "recent_count", "last_event_age")), counts)
            for name, expected in expected_probabilities()[pair].items():
                self.assertAlmostEqual(rows[pair]["probabilities"][name], expected, places=14)
        self.assertEqual(forecast["windows"], {"history_width": 10, "recent_width": 5,
                                              "horizon": 4, "source_time_unit": "tick"})
        self.assertEqual(forecast["content_hash"], canonical_hash({k: v for k, v in forecast.items() if k != "content_hash"}))
        self.assertFalse(forecast["scope"]["window_expiry_is_relationship_termination"])
        self.assertFalse(forecast["scope"]["empirical_forecast_validated"])

    def test_scoring_binary_targets_excludes_right_boundary_and_never_expands_risk(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = with_target(dataset)
        report = score_repeat_interaction_forecast(later, forecast, target_spec(later))
        self.assertEqual(report["status"], "SCORED")
        self.assertEqual(report["counts"], {
            "risk_pairs": 3, "scorable_pairs": 3, "unscored_pairs": 0,
            "known_positive_pairs": 2, "scorable_positive_pairs": 2,
            "scorable_negative_pairs": 1, "known_positive_unscored_pairs": 0,
        })
        self.assert_metrics(report, {(A, B): 1, (B, A): 1, (C, D): 0})
        self.assertEqual(report["content_hash"], canonical_hash({k: v for k, v in report.items() if k != "content_hash"}))
        self.assertFalse(report["scope"]["contains_private_actor_records"])
        self.assertTrue(all(actor not in json.dumps(report) for actor in ACTORS + [ALIAS]))

    def test_utc_microsecond_durations_give_same_probabilities_as_equivalent_ticks(self):
        tick_dataset, tick_spec = fixture()
        utc_dataset, utc_spec = fixture(utc=True)
        tick = make_repeat_interaction_forecast(tick_dataset, tick_spec)
        utc = make_repeat_interaction_forecast(utc_dataset, utc_spec)
        self.assertEqual(tick["predictions"], utc["predictions"])
        self.assertEqual(utc["windows"]["source_time_unit"], "microsecond")
        later = with_target(utc_dataset, utc=True)
        report = score_repeat_interaction_forecast(later, utc, target_spec(later, utc=True))
        self.assert_metrics(report, {(A, B): 1, (B, A): 1, (C, D): 0})

    def test_empty_risk_set_does_not_become_all_possible_pairs_or_zero_error(self):
        dataset, spec = fixture(events=False)
        forecast = make_repeat_interaction_forecast(dataset, spec)
        self.assertEqual(forecast["predictions"], [])
        later = with_target(dataset)
        report = score_repeat_interaction_forecast(later, forecast, target_spec(later))
        self.assertEqual(report["status"], "UNSCORED")
        self.assertTrue(all(value == 0 for value in report["counts"].values()))
        self.assert_unscored_models(report)

    def test_recent_window_equal_to_history_has_equal_poisson_baselines(self):
        dataset, spec = fixture()
        spec["recent_start"] = spec["history_start"]
        forecast = make_repeat_interaction_forecast(dataset, spec)
        for row in forecast["predictions"]:
            self.assertEqual(row["history_count"], row["recent_count"])
            self.assertEqual(row["probabilities"]["historical_poisson"], row["probabilities"]["recent_poisson"])

    def test_distinct_same_time_facts_count_but_duplicate_delivery_does_not(self):
        dataset, spec = fixture()
        new = interaction("distinct-AB-at-recent", A, B, 5)
        later = ingest_records(dataset, [new], received_at=LATER)
        repeated = ingest_records(later, [deepcopy(new)], received_at=LATER)
        updated_spec = {**spec, "knowledge_cutoff": len(later.records)}
        once = make_repeat_interaction_forecast(later, updated_spec)
        self.assertEqual(once, make_repeat_interaction_forecast(repeated, updated_spec))
        ab = next(row for row in once["predictions"] if (row["source"], row["target"]) == (A, B))
        self.assertEqual((ab["history_count"], ab["recent_count"]), (4, 3))
        self.assertAlmostEqual(ab["probabilities"]["historical_poisson"], 1 - math.exp(-1.6), places=14)

    def test_incomplete_history_is_rejected_even_when_all_events_are_observed(self):
        dataset, spec = fixture(coverage_end=4)
        later = ingest_records(dataset, [coverage("after-gap", ACTORS, 5)], received_at=LATER)
        with self.assertRaises(ValueError):
            make_repeat_interaction_forecast(later, {**spec, "knowledge_cutoff": len(later.records)})

    def test_known_absence_in_history_is_not_full_exposure(self):
        dataset, spec = fixture(member_starts={D: 2})
        with self.assertRaises(ValueError):
            make_repeat_interaction_forecast(dataset, spec)

    def test_full_history_without_origin_presence_is_rejected(self):
        dataset, spec = fixture(member_ends={D: 10})
        with self.assertRaises(ValueError):
            make_repeat_interaction_forecast(dataset, spec)

    def test_history_roster_is_exact_instead_of_silently_dropping_extra_members(self):
        dataset, spec = fixture()
        extra = "fictional-person-E"
        later = ingest_records(dataset, [
            raw("extra-entity", "entity.observed", {"entity_id": extra, "entity_type": "person"}),
            membership("extra-member", extra, 0),
            coverage("extra-coverage", [extra], 0),
        ], received_at=LATER)
        with self.assertRaises(ValueError):
            make_repeat_interaction_forecast(later, {**spec, "knowledge_cutoff": len(later.records)})

    def test_raw_future_assertions_cannot_be_hidden_by_retraction_or_correction(self):
        for disposition in ("active", "retracted", "corrected-to-history"):
            with self.subTest(disposition=disposition):
                dataset, spec = fixture()
                leaked = ingest_records(dataset, [interaction("future-leak", A, B, 10)], received_at=LATER)
                if disposition == "retracted":
                    leaked = revise(leaked, "future-leak", "withdraw-future", retract=True)
                elif disposition == "corrected-to-history":
                    leaked = revise(leaked, "future-leak", "move-future-to-past", when=8)
                with self.assertRaisesRegex(ValueError, "target-or-later"):
                    make_repeat_interaction_forecast(leaked, {**spec, "knowledge_cutoff": len(leaked.records)})

    def test_unselected_action_or_topic_does_not_leak_into_the_declared_task(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = ingest_records(dataset, [
            interaction("different-action-future", A, B, 20, action="utterance"),
            interaction("different-topic-future", A, B, 20, topic="another-topic"),
            raw("future-attribute", "actor.attribute.observed", {
                "actor": A, "name": "fictional-other-value", "value": 3,
            }, when=20),
        ], received_at=LATER)
        expanded = make_repeat_interaction_forecast(later, {**spec, "knowledge_cutoff": len(later.records)})
        self.assertEqual(expanded["predictions"], forecast["predictions"])
        self.assertNotEqual(expanded["content_hash"], forecast["content_hash"])

    def test_immature_followup_retains_only_earlier_positives_and_scores_no_model(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = with_target(dataset)
        for through, positive_pairs in ((10, 0), (12, 1)):
            with self.subTest(through=through):
                report = score_repeat_interaction_forecast(later, forecast, target_spec(later, through=through))
                self.assertEqual(report["status"], "UNSCORED")
                self.assertEqual(report["counts"]["known_positive_pairs"], positive_pairs)
                self.assertEqual(report["counts"]["known_positive_unscored_pairs"], positive_pairs)
                self.assertEqual(report["counts"]["unscored_pairs"], 3)
                self.assertEqual(report["unscored_reasons"]["followup_not_closed"], 3)
                self.assert_unscored_models(report)

    def test_coverage_gap_keeps_known_positive_unscored_and_uses_same_pairs_for_all_models(self):
        dataset, spec = fixture(coverage_end=10)
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = ingest_records(dataset, [
            coverage("target-AB", [A, B], 10),
            coverage("target-CD-first", [C, D], 10, 11),
            coverage("target-CD-last", [C, D], 12),
            interaction("target-AB-positive", A, B, 10),
            interaction("target-CD-positive", C, D, 13),
        ], received_at=LATER)
        report = score_repeat_interaction_forecast(later, forecast, target_spec(later))
        self.assertEqual(report["status"], "PARTIALLY_SCORED")
        self.assertEqual(report["counts"], {
            "risk_pairs": 3, "scorable_pairs": 2, "unscored_pairs": 1,
            "known_positive_pairs": 2, "scorable_positive_pairs": 1,
            "scorable_negative_pairs": 1, "known_positive_unscored_pairs": 1,
        })
        self.assertEqual(report["unscored_reasons"]["coverage_incomplete"], 1)
        self.assert_metrics(report, {(A, B): 1, (B, A): 0})

    def test_target_unknown_and_known_absence_are_distinct_and_neither_is_a_negative(self):
        for status, reason in (("unknown", "membership_unknown"), ("absent", "membership_not_full_horizon")):
            with self.subTest(status=status):
                dataset, spec = fixture(member_ends={D: 12})
                forecast = make_repeat_interaction_forecast(dataset, spec)
                rows = [interaction("target-CD-before-loss", C, D, 11)]
                if status == "absent":
                    rows.append(membership("D-left", D, 12, status="absent"))
                later = ingest_records(dataset, rows, received_at=LATER)
                report = score_repeat_interaction_forecast(later, forecast, target_spec(later))
                self.assertEqual(report["status"], "PARTIALLY_SCORED")
                self.assertEqual(report["counts"]["scorable_pairs"], 2)
                self.assertEqual(report["counts"]["known_positive_unscored_pairs"], 1)
                self.assertEqual(report["unscored_reasons"][reason], 1)
                self.assert_metrics(report, {(A, B): 0, (B, A): 0})

    def test_returning_before_target_end_does_not_erase_an_internal_membership_gap(self):
        dataset, spec = fixture(member_ends={D: 11})
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = ingest_records(dataset, [
            membership("D-returned", D, 12),
            interaction("target-CD-after-return", C, D, 13),
        ], received_at=LATER)
        report = score_repeat_interaction_forecast(later, forecast, target_spec(later))
        self.assertEqual(report["counts"]["known_positive_unscored_pairs"], 1)
        self.assertEqual(report["unscored_reasons"]["membership_unknown"], 1)
        self.assertEqual(report["counts"]["scorable_pairs"], 2)

    def test_mature_followup_without_coverage_is_unscored_even_with_positive_events(self):
        dataset, spec = fixture(coverage_end=10)
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = with_target(dataset)
        report = score_repeat_interaction_forecast(later, forecast, target_spec(later))
        self.assertEqual(report["status"], "UNSCORED")
        self.assertEqual(report["unscored_reasons"]["coverage_incomplete"], 3)
        self.assertEqual(report["counts"]["known_positive_unscored_pairs"], 2)
        self.assert_unscored_models(report)

    def test_closed_empty_followup_scores_negatives_with_explicit_complete_coverage(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        report = score_repeat_interaction_forecast(dataset, forecast, target_spec(dataset))
        self.assertEqual(report["status"], "SCORED")
        self.assertEqual(report["counts"]["scorable_negative_pairs"], 3)
        self.assert_metrics(report, {(A, B): 0, (B, A): 0, (C, D): 0})

    def test_a_history_fact_revised_into_the_target_is_not_new_future_evidence(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = revise(dataset, "AB-last", "old-fact-moved-to-target", when=11)
        with self.assertRaisesRegex(ValueError, "first received"):
            score_repeat_interaction_forecast(later, forecast, target_spec(later))

    def test_target_revision_changes_new_score_but_preserves_old_cutoff_and_forecast(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = with_target(dataset)
        original_spec = target_spec(later)
        original = score_repeat_interaction_forecast(later, forecast, original_spec)
        changed = revise(later, "future-BA", "target-BA-withdrawn", retract=True)
        self.assertEqual(score_repeat_interaction_forecast(changed, forecast, original_spec), original)
        revised = score_repeat_interaction_forecast(changed, forecast, target_spec(changed))
        self.assertEqual(revised["counts"]["scorable_positive_pairs"], 1)
        self.assertNotEqual(revised["content_hash"], original["content_hash"])
        self.assertEqual(make_repeat_interaction_forecast(changed, spec), forecast)

    def test_late_history_correction_does_not_rewrite_frozen_predictions(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        changed = revise(dataset, "AB-last", "AB-revised-time", when=4)
        self.assertEqual(make_repeat_interaction_forecast(changed, spec), forecast)
        revised = make_repeat_interaction_forecast(changed, {**spec, "knowledge_cutoff": len(changed.records)})
        self.assertNotEqual(revised["predictions"], forecast["predictions"])
        self.assertEqual(revised["predictions"][0]["history_count"], forecast["predictions"][0]["history_count"])
        self.assertEqual(revised["predictions"][0]["recent_count"], 1)

    def test_rehashing_modified_predictions_cannot_bypass_exact_history_replay(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = with_target(dataset)
        for field in ("probability", "count"):
            with self.subTest(field=field):
                edited = deepcopy(forecast)
                if field == "probability":
                    edited["predictions"][0]["probabilities"]["historical_poisson"] = 0.99
                else:
                    edited["predictions"][0]["history_count"] += 1
                edited["content_hash"] = canonical_hash({k: v for k, v in edited.items() if k != "content_hash"})
                with self.assertRaisesRegex(ValueError, "original journal history"):
                    score_repeat_interaction_forecast(later, edited, target_spec(later))

    def test_saved_forecast_rejects_changed_historical_source_bytes(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = with_target(dataset)
        mapping = later.to_dict()
        mapping["records"][0]["source"]["evidence_ref"] = "synthetic:changed-history"
        changed = EventDataset.from_mapping(mapping)
        with self.assertRaisesRegex(ValueError, "original journal history"):
            score_repeat_interaction_forecast(changed, forecast, target_spec(changed))

    def test_target_alias_remapping_is_rejected_but_unrelated_new_entity_is_allowed(self):
        dataset, spec = fixture()
        forecast = make_repeat_interaction_forecast(dataset, spec)
        later = with_target(dataset)
        changed = revise(later, "alias-map", "different-alias-map", payload={"alias": ALIAS, "canonical": D})
        with self.assertRaisesRegex(ValueError, "alias map"):
            score_repeat_interaction_forecast(changed, forecast, target_spec(changed))
        unrelated = ingest_records(later, [raw("new-unrelated-entity", "entity.observed", {
            "entity_id": "fictional-unrelated-person", "entity_type": "person",
        }, when=11)], received_at=LATER)
        report = score_repeat_interaction_forecast(unrelated, forecast, target_spec(unrelated))
        self.assertEqual(report["counts"]["risk_pairs"], 3)
        self.assert_metrics(report, {(A, B): 1, (B, A): 1, (C, D): 0})


class RepeatInteractionCliTests(unittest.TestCase):
    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(arguments)
        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        return stdout.getvalue(), json.loads(stdout.getvalue())

    def reject_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            main(arguments)
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error:", stderr.getvalue())

    def test_saved_cli_forecast_scores_aggregate_and_leaves_all_inputs_unchanged(self):
        dataset, spec = fixture()
        later = with_target(dataset)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            history, specification, target, followup, prediction = (
                directory / name for name in ("history.json", "spec.json", "target.json", "followup.json", "prediction.json")
            )
            for path, value in ((history, dataset.to_dict()), (specification, spec),
                                (target, later.to_dict()), (followup, target_spec(later))):
                path.write_text(json.dumps(value), encoding="utf-8")
            text, forecast = self.run_cli(["forecast", "interaction-create", str(history), str(specification)])
            prediction.write_text(text, encoding="utf-8")
            before = {path: path.read_bytes() for path in (history, specification, target, followup, prediction)}
            score_text, report = self.run_cli(["forecast", "interaction-score", str(target), str(prediction), str(followup)])
            self.assertEqual(forecast, make_repeat_interaction_forecast(dataset, spec))
            self.assertEqual(report, score_repeat_interaction_forecast(later, forecast, target_spec(later)))
            self.assertTrue(all(actor not in score_text for actor in ACTORS + [ALIAS]))
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_cli_rejects_future_history_without_partial_output(self):
        dataset, spec = fixture()
        later = with_target(dataset)
        spec["knowledge_cutoff"] = len(later.records)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            journal, specification = directory / "journal.json", directory / "spec.json"
            journal.write_text(json.dumps(later.to_dict()), encoding="utf-8")
            specification.write_text(json.dumps(spec), encoding="utf-8")
            self.reject_cli(["forecast", "interaction-create", str(journal), str(specification)])

    def test_cli_rejects_rehashed_forecast_edit_and_duplicate_target_fields(self):
        dataset, spec = fixture()
        later = with_target(dataset)
        forecast = make_repeat_interaction_forecast(dataset, spec)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            journal, prediction, followup = directory / "journal.json", directory / "prediction.json", directory / "followup.json"
            journal.write_text(json.dumps(later.to_dict()), encoding="utf-8")
            followup.write_text(json.dumps(target_spec(later)), encoding="utf-8")
            edited = deepcopy(forecast)
            edited["predictions"][0]["probabilities"]["recent_occurrence"] = 0.5
            edited["content_hash"] = canonical_hash({k: v for k, v in edited.items() if k != "content_hash"})
            prediction.write_text(json.dumps(edited), encoding="utf-8")
            command = ["forecast", "interaction-score", str(journal), str(prediction), str(followup)]
            self.reject_cli(command)
            prediction.write_text(json.dumps(forecast), encoding="utf-8")
            followup.write_text('{"knowledge_cutoff":1,"knowledge_cutoff":2}', encoding="utf-8")
            self.reject_cli(command)


if __name__ == "__main__":
    unittest.main()
