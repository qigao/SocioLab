"""Receipt-cutoff and measurement boundaries through the real journal tools."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
from sociolab.journal_forecast import make_journal_forecast_history, make_journal_forecast_target
from sociolab.panels import LongitudinalPanel
from sociolab.snapshots import materialize_snapshot


ACTORS = ["private-A", "private-B", "private-C", "private-D"]
ALIAS = "known-alias-A"
RECEIPT = "2026-01-01T00:00:01Z"
LATER = "2026-01-01T00:00:02Z"


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + sha256(raw.encode("utf-8")).hexdigest()


def source_time(value, utc=False):
    if not utc:
        return value
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value)
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def raw(record_id, kind, payload, *, at=0, interval=None, system="study"):
    return {
        "record_id": record_id, "fact_id": record_id, "operation": "assert", "supersedes": None,
        "kind": kind, "occurred_at": at, "valid_interval": interval,
        "source": {"system": system, "record_id": record_id, "revision": "source-1", "evidence_ref": "synthetic:" + record_id},
        "payload": payload,
    }


def observation(record_id, actor, value, at, *, system="survey", name="reported_level", interval=None):
    return raw(record_id, "actor.attribute.observed", {"actor": actor, "name": name, "value": value},
               at=at, system=system, interval=interval)


def forecast_spec():
    return {
        "schema": "sociolab.behavior-forecast.v1", "profile": "own-lag-outgoing-gap-ols-v1",
        "behavior": {"variable": "ordinal_level", "minimum": 0, "maximum": 10,
                     "measurement_reference": "Invented point survey with integer levels 0 through 10."},
        "target_time_index": 2, "research_question": "Does the origin network add predictive information?",
    }


def fixture(*, utc=False):
    dataset = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "synthetic-journal-forecast",
        "origin": "synthetic", "source_revision": "stable-journal-envelope-1",
        "clock": {"kind": "utc"} if utc else {"kind": "ticks", "run_id": "invented-run"}, "records": [],
    })
    at = lambda value: source_time(value, utc)
    records = [raw("entity-" + actor, "entity.observed", {"entity_id": actor, "entity_type": "person"}, at=at(0))
               for actor in ACTORS + [ALIAS]]
    records.append(raw("identity-A", "identity.mapped", {"alias": ALIAS, "canonical": ACTORS[0]}, at=at(0)))
    records.extend(raw("member-" + actor, "membership.observed", {
        "actor": actor, "population": "cohort", "status": "present"}, at=at(0), interval=[at(0), None]) for actor in ACTORS)
    records.append(raw("coverage", "coverage.observed", {
        "population": "cohort", "layer": "friendship", "actors": ACTORS, "status": "complete"},
        at=at(0), interval=[at(0), None]))
    for name, when, left, right, strength in (
        ("AB", 0, 0, 1, 1), ("BA", 0, 1, 0, 1), ("CD", 0, 2, 3, 1),
        ("AB-end", 10, 0, 1, 0), ("AC", 10, 0, 2, 1), ("CD-end", 10, 2, 3, 0), ("DB", 10, 3, 1, 1),
    ):
        records.append(raw("tie-" + name, "relation.changed", {
            "layer": "friendship", "source": ACTORS[left], "target": ACTORS[right],
            "directed": True, "strength": strength}, at=at(when)))
    for wave, values in ((0, (1, 2, 3, 4)), (10, (3, 2, 5, 5))):
        for actor, value in zip(ACTORS, values):
            records.append(observation(f"behavior-{wave}-{actor}", ALIAS if actor == ACTORS[0] else actor, value, at(wave)))
    dataset = ingest_records(dataset, records, received_at=RECEIPT)
    spec = {
        "schema": "sociolab.journal-forecast-history.v1", "knowledge_cutoff": len(dataset.records),
        "source_reference": None, "actors": list(ACTORS), "population": "cohort", "layer": "friendship",
        "behavior_source": {"system": "survey", "attribute": "reported_level"},
        "waves": [{"time_index": 0, "at": at(0)}, {"time_index": 1, "at": at(10)}],
        "target_at": at(20), "forecast_specification": forecast_spec(),
    }
    return dataset, spec


def with_target(dataset, *, utc=False, actor_a=ALIAS, received_at=LATER):
    return ingest_records(dataset, [observation(f"target-{actor}", actor_a if actor == ACTORS[0] else actor, value,
                                                source_time(20, utc))
                                    for actor, value in zip(ACTORS, (4, 3, 5, 2))], received_at=received_at)


def saved_forecast(dataset, spec):
    bundle = make_journal_forecast_history(dataset, spec)
    return bundle, make_behavior_forecast(LongitudinalPanel.from_mapping(bundle["history"]), spec["forecast_specification"])


def alter_record(dataset, record_id, change):
    value = dataset.to_dict()
    selected = next(record for record in value["records"] if record["record_id"] == record_id)
    change(selected)
    return EventDataset.from_mapping(value)


def revise(dataset, record_id, new_id, *, payload=None, retract=False):
    old = next(record for record in dataset.records if record["record_id"] == record_id)
    record = {key: value for key, value in old.items() if key not in {"ingest_seq", "recorded_at"}}
    record.update(record_id=new_id, supersedes=record_id, operation="retract" if retract else "assert")
    record["payload"] = None if retract else payload
    record["source"] = {**record["source"], "record_id": new_id, "revision": "corrected-2"}
    return ingest_records(dataset, [record], received_at=LATER)


class JournalForecastTests(unittest.TestCase):
    def test_real_snapshots_and_exact_point_behavior_form_the_original_panel(self):
        dataset, spec = fixture()
        with patch("sociolab.journal_forecast.materialize_snapshot", wraps=materialize_snapshot) as materializer, \
                patch.object(np.linalg, "lstsq", side_effect=AssertionError("bridge cannot fit")) as solver:
            bundle = make_journal_forecast_history(dataset, spec)
        solver.assert_not_called()
        self.assertEqual(materializer.call_count, 2)
        self.assertEqual([call.args[1]["at"] for call in materializer.call_args_list], [0, 10])
        self.assertTrue(all(call.kwargs == {"knowledge_cutoff": spec["knowledge_cutoff"]} for call in materializer.call_args_list))
        panel = LongitudinalPanel.from_mapping(bundle["history"])
        self.assertEqual(list(panel.actors), ACTORS)
        self.assertEqual(panel.waves[0].edges, ((ACTORS[0], ACTORS[1]), (ACTORS[1], ACTORS[0]), (ACTORS[2], ACTORS[3])))
        self.assertEqual(panel.waves[1].edges, ((ACTORS[0], ACTORS[2]), (ACTORS[1], ACTORS[0]), (ACTORS[3], ACTORS[1])))
        self.assertEqual(dict(panel.waves[0].behavior), dict(zip(ACTORS, (1, 2, 3, 4))))
        self.assertEqual(dict(panel.waves[1].behavior), dict(zip(ACTORS, (3, 2, 5, 5))))
        provenance = bundle["provenance"]
        self.assertEqual(provenance["receipt_records"], dataset.to_dict()["records"])
        self.assertEqual(provenance["prefix_content_hash"], dataset.content_hash)
        self.assertEqual(provenance["prefix_records_hash"], canonical_hash(list(dataset.records)))
        self.assertNotIn("records", provenance["prefix_envelope"])
        self.assertEqual(provenance["identity_state_hash"], canonical_hash({key: provenance[key] for key in
                         ("entities", "identity_map", "entity_identity_evidence")}))
        for wave, manifest in zip(panel.waves, provenance["waves"]):
            self.assertEqual(manifest["source_time_unit"], "tick")
            self.assertEqual(manifest["parsed_at"], manifest["at"])
            self.assertEqual(wave.source_revision, canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}))
            self.assertEqual(wave.source_revision, manifest["manifest_hash"])
            self.assertEqual(manifest["behavior_evidence"][0]["record"]["payload"]["actor"], ALIAS)
            self.assertEqual(manifest["behavior_evidence"][0]["resolved_actor"], ACTORS[0])
            self.assertEqual(manifest["snapshot"]["dataset"]["content_hash"], provenance["prefix_content_hash"])
        self.assertEqual(bundle["content_hash"], canonical_hash({key: value for key, value in bundle.items() if key != "content_hash"}))

    def test_target_replays_only_history_graphs_and_calls_no_fitter(self):
        dataset, spec = fixture()
        history_bundle, forecast = saved_forecast(dataset, spec)
        later = with_target(dataset)
        # This future network declaration is incompatible with the state profile.
        # A target-network materialization would fail; behavior extraction must not.
        later = ingest_records(later, [raw("future-network", "relation.changed", {
            "layer": "friendship", "source": ACTORS[0], "target": ACTORS[3], "directed": False, "strength": 7}, at=20)], received_at=LATER)
        with patch("sociolab.journal_forecast.materialize_snapshot", wraps=materialize_snapshot) as materializer, \
                patch.object(np.linalg, "lstsq", side_effect=AssertionError("target bridge cannot refit")) as solver, \
                patch("sociolab.behavior_forecast.make_behavior_forecast", side_effect=AssertionError("cannot recreate forecast")):
            bundle = make_journal_forecast_target(later, spec, forecast, len(later.records))
        solver.assert_not_called()
        self.assertEqual(materializer.call_count, 2)
        self.assertEqual([call.args[1]["at"] for call in materializer.call_args_list], [0, 10])
        self.assertTrue(all(call.kwargs["knowledge_cutoff"] == spec["knowledge_cutoff"] for call in materializer.call_args_list))
        self.assertEqual(bundle["forecast_hash"], forecast["content_hash"])
        self.assertEqual(bundle["history_bundle_hash"], history_bundle["content_hash"])
        self.assertEqual(bundle["target"]["behavior"], dict(zip(ACTORS, (4, 3, 5, 2))))
        self.assertEqual(bundle["provenance"]["prefix_content_hash"], later.content_hash)
        self.assertNotIn("receipt_records", bundle["provenance"])
        self.assertEqual(bundle["target"]["source_revision"], canonical_hash({key: value for key, value in bundle["provenance"].items() if key != "manifest_hash"}))
        self.assertFalse(bundle["scope"]["target_network_materialized"])
        self.assertTrue(bundle["scope"]["historical_network_replayed"])
        self.assertEqual(score_behavior_forecast(forecast, bundle["target"])["actor_count"], 4)
        self.assertFalse(forecast["scope"]["historical_as_of_availability_verified"])

    def test_old_cutoff_bundles_are_identical_after_valid_late_records(self):
        dataset, spec = fixture()
        original, forecast = saved_forecast(dataset, spec)
        later = with_target(dataset)
        target_cutoff = len(later.records)
        target_bundle = make_journal_forecast_target(later, spec, forecast, target_cutoff)
        later = revise(later, "behavior-0-" + ACTORS[0], "late-history-correction", payload={
            "actor": ALIAS, "name": "reported_level", "value": 2})
        later = revise(later, "target-" + ACTORS[0], "late-target-correction", payload={
            "actor": ALIAS, "name": "reported_level", "value": 8})
        later = ingest_records(later, [
            raw("late-alias-entity", "entity.observed", {"entity_id": "unrelated-alias", "entity_type": "person"}),
            raw("late-alias-map", "identity.mapped", {"alias": "unrelated-alias", "canonical": ACTORS[2]}),
        ], received_at=LATER)
        self.assertEqual(make_journal_forecast_history(later, spec), original)
        self.assertEqual(make_journal_forecast_target(later, spec, forecast, target_cutoff), target_bundle)
        self.assertNotEqual(original["provenance"]["prefix_content_hash"], later.content_hash)
        changed_spec = deepcopy(spec)
        changed_spec["knowledge_cutoff"] = len(later.records)
        changed = make_journal_forecast_history(later, changed_spec)
        self.assertEqual(changed["history"]["waves"][0]["behavior"][ACTORS[0]], 2)
        self.assertNotEqual(changed["content_hash"], original["content_hash"])

    def test_duplicates_missing_retractions_and_unselected_sources(self):
        dataset, spec = fixture()
        duplicate = ingest_records(dataset, [observation("duplicate", ACTORS[0], 1, 0)], received_at=LATER)
        duplicate_spec = {**spec, "knowledge_cutoff": len(duplicate.records)}
        with self.assertRaisesRegex(ValueError, "exactly one"):
            make_journal_forecast_history(duplicate, duplicate_spec)
        removed = revise(dataset, "behavior-0-" + ACTORS[0], "retract-old-measurement", retract=True)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            make_journal_forecast_history(removed, {**spec, "knowledge_cutoff": len(removed.records)})
        changed = alter_record(dataset, "behavior-10-" + ACTORS[0], lambda record: record.update(occurred_at=9))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            make_journal_forecast_history(changed, spec)
        ignored = ingest_records(dataset, [
            observation("different-system", ACTORS[0], None, 0, system="different"),
            observation("different-name", ACTORS[0], True, 0, name="another_attribute"),
            observation("different-time", ACTORS[0], 2.0, 7),
        ], received_at=LATER)
        bundle = make_journal_forecast_history(ignored, {**spec, "knowledge_cutoff": len(ignored.records)})
        self.assertEqual(bundle["history"]["waves"][0]["behavior"][ACTORS[0]], 1)

    def test_selected_invalid_values_are_rejected_instead_of_filtered(self):
        dataset, spec = fixture()
        _, forecast = saved_forecast(dataset, spec)
        for value in (True, 2.0, None, "2", -1, 11):
            with self.subTest(value=value):
                invalid = alter_record(dataset, "behavior-0-" + ACTORS[0], lambda record: record["payload"].update(value=value))
                with self.assertRaisesRegex(ValueError, "known integer"):
                    make_journal_forecast_history(invalid, spec)
                later = with_target(dataset)
                invalid = alter_record(later, "target-" + ACTORS[0], lambda record: record["payload"].update(value=value))
                with self.assertRaisesRegex(ValueError, "known integer"):
                    make_journal_forecast_target(invalid, spec, forecast, len(invalid.records))
        invalid_extra = ingest_records(dataset, [observation("invalid-duplicate", ACTORS[0], None, 0)], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "known integer"):
            make_journal_forecast_history(invalid_extra, {**spec, "knowledge_cutoff": len(invalid_extra.records)})

    def test_intervals_overlap_selection_even_when_occurrence_time_differs(self):
        dataset, spec = fixture()
        _, forecast = saved_forecast(dataset, spec)
        for occurred, interval in ((0, [0, 5]), (7, [0, 5]), (7, [10, None])):
            interval_dataset = ingest_records(dataset, [observation("interval", ACTORS[0], 1, occurred, interval=interval)], received_at=LATER)
            with self.assertRaisesRegex(ValueError, "point measurements"):
                make_journal_forecast_history(interval_dataset, {**spec, "knowledge_cutoff": len(interval_dataset.records)})
        later = with_target(dataset)
        overlapping = ingest_records(later, [observation("target-interval", ACTORS[0], 4, 15, interval=[20, 30])], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "point measurements"):
            make_journal_forecast_target(overlapping, spec, forecast, len(overlapping.records))
        ended = ingest_records(later, [observation("ended-interval", ACTORS[0], 4, 15, interval=[15, 20])], received_at=LATER)
        bundle = make_journal_forecast_target(ended, spec, forecast, len(ended.records))
        self.assertEqual(bundle["target"]["behavior"][ACTORS[0]], 4)

    def test_complete_population_and_binary_directed_network_are_required(self):
        dataset, spec = fixture()
        variants = [
            alter_record(dataset, "coverage", lambda record: record["payload"].update(status="partial")),
            alter_record(dataset, "member-" + ACTORS[-1], lambda record: record["payload"].update(status="absent")),
            alter_record(dataset, "tie-AB", lambda record: record["payload"].update(strength=2)),
            alter_record(dataset, "tie-AB", lambda record: record["payload"].update(directed=False)),
        ]
        for invalid in variants:
            with self.assertRaises(ValueError):
                make_journal_forecast_history(invalid, spec)
        # A contradictory network source cannot be removed using the behavior
        # source filter. The selected layer retains all its original evidence.
        contrary = ingest_records(dataset, [raw("other-source-tie", "relation.changed", {
            "layer": "friendship", "source": ACTORS[0], "target": ACTORS[1], "directed": True, "strength": 2},
            system="another-network-source")], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            make_journal_forecast_history(contrary, {**spec, "knowledge_cutoff": len(contrary.records)})
        extra = ingest_records(dataset, [
            raw("extra-person", "entity.observed", {"entity_id": "extra-person", "entity_type": "person"}),
            raw("extra-membership", "membership.observed", {"actor": "extra-person", "population": "cohort", "status": "present"}, interval=[0, None]),
            raw("extra-coverage", "coverage.observed", {"population": "cohort", "layer": "friendship", "actors": ["extra-person"], "status": "complete"}, interval=[0, None]),
        ], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "fixed actor roster"):
            make_journal_forecast_history(extra, {**spec, "knowledge_cutoff": len(extra.records)})

    def test_target_allows_unrelated_new_alias_but_rejects_new_measurement_alias(self):
        dataset, spec = fixture()
        _, forecast = saved_forecast(dataset, spec)
        alias_added = ingest_records(dataset, [
            raw("new-alias-entity", "entity.observed", {"entity_id": "new-alias", "entity_type": "person"}),
            raw("new-alias-map", "identity.mapped", {"alias": "new-alias", "canonical": ACTORS[0]}),
        ], received_at=LATER)
        unrelated = with_target(alias_added)
        make_journal_forecast_target(unrelated, spec, forecast, len(unrelated.records))
        selected = with_target(alias_added, actor_a="new-alias")
        with self.assertRaisesRegex(ValueError, "history-known actor"):
            make_journal_forecast_target(selected, spec, forecast, len(selected.records))

    def test_target_rejects_changed_selected_alias_and_frozen_actor_identity(self):
        dataset, spec = fixture()
        _, forecast = saved_forecast(dataset, spec)
        changed_alias = revise(dataset, "identity-A", "identity-A-corrected", payload={"alias": ALIAS, "canonical": ACTORS[1]})
        changed_alias = with_target(changed_alias)
        with self.assertRaisesRegex(ValueError, "unchanged identity resolution"):
            make_journal_forecast_target(changed_alias, spec, forecast, len(changed_alias.records))
        # Use an isolated D-to-new-canonical mapping; existing relation endpoints
        # remain distinct, so the underlying journal legitimately admits it.
        changed_actor = ingest_records(dataset, [
            raw("new-canonical-entity", "entity.observed", {"entity_id": "new-canonical", "entity_type": "person"}),
            raw("roster-map", "identity.mapped", {"alias": ACTORS[3], "canonical": "new-canonical"}),
        ], received_at=LATER)
        changed_actor = with_target(changed_actor)
        with self.assertRaisesRegex(ValueError, "frozen roster"):
            make_journal_forecast_target(changed_actor, spec, forecast, len(changed_actor.records))

    def test_target_binding_rejects_changed_history_envelope_clock_spec_or_artifact(self):
        dataset, spec = fixture()
        _, forecast = saved_forecast(dataset, spec)
        later = with_target(dataset)
        mutations = [
            lambda data: data.update(source_revision="different-envelope"),
            lambda data: data["clock"].update(run_id="different-run"),
            lambda data: next(record for record in data["records"] if record["record_id"] == "behavior-0-" + ACTORS[0])["payload"].update(value=2),
        ]
        for mutation in mutations:
            raw_data = later.to_dict()
            mutation(raw_data)
            changed = EventDataset.from_mapping(raw_data)
            with self.assertRaisesRegex(ValueError, "saved forecast must match"):
                make_journal_forecast_target(changed, spec, forecast, len(changed.records))
        changed_spec = deepcopy(spec)
        changed_spec["forecast_specification"]["research_question"] = "a different question"
        with self.assertRaisesRegex(ValueError, "saved forecast must match"):
            make_journal_forecast_target(later, changed_spec, forecast, len(later.records))
        changed_forecast = deepcopy(forecast)
        changed_forecast["models"]["persistence"]["raw_predictions"][0] = 2.0
        with self.assertRaisesRegex(ValueError, "content hash"):
            make_journal_forecast_target(later, spec, changed_forecast, len(later.records))

    def test_utc_microsecond_intervals_and_receipt_order_are_exact(self):
        dataset, spec = fixture(utc=True)
        # Shift the original ten-microsecond schedule to a one-microsecond gap.
        raw_data = dataset.to_dict()
        for record in raw_data["records"]:
            if record["occurred_at"] == source_time(10, True):
                record["occurred_at"] = source_time(1, True)
        dataset = EventDataset.from_mapping(raw_data)
        spec["waves"][1]["at"] = source_time(1, True)
        spec["target_at"] = source_time(2, True)
        bundle, forecast = saved_forecast(dataset, spec)
        parsed = [wave["parsed_at"] for wave in bundle["provenance"]["waves"]]
        self.assertEqual(parsed[1] - parsed[0], 1)
        self.assertTrue(all(wave["source_time_unit"] == "microsecond" for wave in bundle["provenance"]["waves"]))
        equivalent = deepcopy(spec)
        equivalent["waves"][1]["at"] = equivalent["waves"][1]["at"].replace("Z", "+00:00")
        self.assertEqual(make_journal_forecast_history(dataset, equivalent)["history"]["waves"][1]["behavior"], bundle["history"]["waves"][1]["behavior"])
        premature = dataset.to_dict()
        for record in premature["records"]:
            record["recorded_at"] = source_time(0, True)
        with self.assertRaisesRegex(ValueError, "receipt earlier"):
            make_journal_forecast_history(EventDataset.from_mapping(premature), spec)
        # A later target is likewise rejected when its event timestamp is after
        # the accepted receipt; the general journal itself allows such data.
        early_history = dataset.to_dict()
        for record in early_history["records"]:
            record["recorded_at"] = source_time(1, True)
        early_dataset = EventDataset.from_mapping(early_history)
        _, early_forecast = saved_forecast(early_dataset, spec)
        later = ingest_records(early_dataset, [observation("early-target-" + actor, actor, 3, source_time(2, True)) for actor in ACTORS],
                               received_at=source_time(1, True))
        with self.assertRaisesRegex(ValueError, "receipt earlier"):
            make_journal_forecast_target(later, spec, early_forecast, len(later.records))
        wrong = deepcopy(spec)
        wrong["target_at"] = source_time(3, True)
        with self.assertRaisesRegex(ValueError, "same exact gap"):
            make_journal_forecast_history(dataset, wrong)

    def test_ticks_are_not_compared_numerically_to_utc_receipts(self):
        dataset, spec = fixture()
        raw_data = dataset.to_dict()
        for record in raw_data["records"]:
            record["recorded_at"] = "1960-01-01T00:00:00Z"
        # UTC microseconds here are negative; the source ticks remain valid and
        # are not accidentally compared against an unrelated clock domain.
        bundle = make_journal_forecast_history(EventDataset.from_mapping(raw_data), spec)
        self.assertEqual(bundle["history"]["waves"][1]["time_index"], 1)

    def test_strict_spec_fields_types_roster_and_schedule(self):
        dataset, spec = fixture()
        mutations = [
            lambda value: value.update(extra="unknown"),
            lambda value: value.update(schema="wrong"),
            lambda value: value.update(knowledge_cutoff=True),
            lambda value: value.update(knowledge_cutoff=-1),
            lambda value: value.update(knowledge_cutoff=len(dataset.records) + 1),
            lambda value: value.update(source_reference="https://example.invalid/source"),
            lambda value: value.update(actors=[ACTORS[0]]),
            lambda value: value.update(actors=list(reversed(ACTORS))),
            lambda value: value.update(actors=sorted([ALIAS] + ACTORS[1:])),
            lambda value: value.update(actors=sorted(["unknown"] + ACTORS[1:])),
            lambda value: value.update(actors=ACTORS + [ACTORS[-1]]),
            lambda value: value.update(actors=[f"unknown-{index:03}" for index in range(201)]),
            lambda value: value.update(waves=value["waves"][:1]),
            lambda value: value.update(waves=value["waves"] * 17),
            lambda value: value["waves"][0].update(extra=True),
            lambda value: value["waves"][0].update(time_index=True),
            lambda value: value["waves"][1].update(time_index=0),
            lambda value: value["waves"][1].update(at=0),
            lambda value: value["waves"][1].update(at=True),
            lambda value: value.update(target_at=21),
            lambda value: value["forecast_specification"].update(target_time_index=3),
            lambda value: value["behavior_source"].update(extra="filter"),
            lambda value: value["behavior_source"].update(system=" "),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                changed = deepcopy(spec)
                mutate(changed)
                with self.assertRaises(ValueError):
                    make_journal_forecast_history(dataset, changed)
        _, forecast = saved_forecast(dataset, spec)
        later = with_target(dataset)
        for cutoff in (True, None, spec["knowledge_cutoff"] - 1, len(later.records) + 1):
            with self.assertRaises(ValueError):
                make_journal_forecast_target(later, spec, forecast, cutoff)
        with self.assertRaises(TypeError):
            make_journal_forecast_history(dataset.to_dict(), spec)

    def test_unequal_index_or_source_gaps_are_rejected_before_materialization(self):
        dataset, spec = fixture()
        for waves in (
            [{"time_index": 0, "at": 0}, {"time_index": 1, "at": 10}, {"time_index": 3, "at": 20}],
            [{"time_index": 0, "at": 0}, {"time_index": 1, "at": 10}, {"time_index": 2, "at": 21}],
        ):
            changed = deepcopy(spec)
            changed["waves"] = waves
            with patch("sociolab.journal_forecast.materialize_snapshot") as materializer:
                with self.assertRaisesRegex(ValueError, "constant gap"):
                    make_journal_forecast_history(dataset, changed)
                materializer.assert_not_called()

    def test_external_reference_and_rejected_simulation_origin(self):
        dataset, spec = fixture()
        raw_data = dataset.to_dict()
        raw_data["origin"] = "external_observation"
        external = EventDataset.from_mapping(raw_data)
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            make_journal_forecast_history(external, spec)
        spec["source_reference"] = "https://example.invalid/declared-study"
        bundle = make_journal_forecast_history(external, spec)
        self.assertEqual(bundle["history"]["source_reference"], spec["source_reference"])
        raw_data["origin"] = "simulation_export"
        with self.assertRaisesRegex(ValueError, "origin"):
            make_journal_forecast_history(EventDataset.from_mapping(raw_data), spec)

    def test_inputs_are_immutable_and_private_scope_does_not_claim_authentication(self):
        dataset, spec = fixture()
        before_data, before_spec = dataset.to_dict(), deepcopy(spec)
        bundle, forecast = saved_forecast(dataset, spec)
        before_forecast = deepcopy(forecast)
        later = with_target(dataset)
        before_later = later.to_dict()
        target = make_journal_forecast_target(later, spec, forecast, len(later.records))
        self.assertEqual(dataset.to_dict(), before_data)
        self.assertEqual(later.to_dict(), before_later)
        self.assertEqual(spec, before_spec)
        self.assertEqual(forecast, before_forecast)
        for result in (bundle, target):
            self.assertTrue(result["scope"]["receipt_prefix_enforced"])
            self.assertTrue(result["scope"]["contains_private_actor_records"])
            for flag in ("historical_as_of_availability_verified", "receipt_timestamps_externally_authenticated",
                         "forecast_issued_before_target_observation_verified", "live_subscription", "models_fitted_by_bridge",
                         "content_hash_proves_prospective_timestamp", "cross_cutoff_immutable_prefix_compatibility_established"):
                self.assertFalse(result["scope"][flag])
        bundle["specification"]["actors"][0] = "changed-returned-value"
        bundle["provenance"]["receipt_records"][0]["source"]["revision"] = "changed-returned-evidence"
        self.assertEqual(spec, before_spec)
        self.assertEqual(dataset.to_dict(), before_data)


if __name__ == "__main__":
    unittest.main()
