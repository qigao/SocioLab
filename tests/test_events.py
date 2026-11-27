"""Receipt-time replay, typed references and source-event identity invariants."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.events import EventDataset, ingest_records, load_event_dataset, parse_time


RECEIPT = "2026-11-27T10:00:00.000001Z"
LATER = "2026-11-27T10:00:01Z"


def empty_dataset(clock=None):
    return EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "synthetic-events",
        "origin": "synthetic", "source_revision": "source-export-1",
        "clock": {"kind": "ticks", "run_id": "run-1"} if clock is None else clock,
        "records": [],
    })


def raw_record(record_id, kind, payload, *, fact_id=None, supersedes=None,
               operation="assert", occurred_at=0, valid_interval=None, system="study"):
    return {
        "record_id": record_id, "fact_id": record_id if fact_id is None else fact_id,
        "operation": operation, "supersedes": supersedes, "kind": kind,
        "occurred_at": occurred_at, "valid_interval": valid_interval,
        "source": {"system": system, "record_id": record_id,
                   "revision": "source-export-1", "evidence_ref": "source:fixture"},
        "payload": payload,
    }


def entity_record(entity_id, entity_type="person", *, occurred_at=0):
    return raw_record(f"declare-{entity_id}", "entity.observed",
                      {"entity_id": entity_id, "entity_type": entity_type},
                      occurred_at=occurred_at)


def populated_dataset():
    return ingest_records(empty_dataset(), [
        entity_record("alice"), entity_record("bob"), entity_record("alice-alias"),
        entity_record("meeting", "activity"),
    ], received_at=RECEIPT)


def interaction(record_id="speech", **kwargs):
    return raw_record(record_id, "interaction.observed", {
        "actor": "alice", "target": "bob", "action": "utterance", "topic": None,
    }, **kwargs)


class EventDatasetTest(unittest.TestCase):
    def test_exact_roundtrip_and_public_values_do_not_mutate_journal(self):
        original = populated_dataset().to_dict()
        dataset = EventDataset.from_mapping(original)
        expected = dataset.to_dict()
        digest = dataset.content_hash
        original["records"][0]["payload"]["entity_id"] = "changed"
        dataset.records[0]["source"]["system"] = "changed"
        dataset.as_known()[0]["payload"]["entity_id"] = "changed"
        dataset.clock["run_id"] = "changed"
        dataset.entities_at()["alice"] = "activity"
        self.assertEqual(dataset.to_dict(), expected)
        self.assertEqual(dataset.content_hash, digest)
        self.assertEqual(EventDataset.from_mapping(expected), dataset)
        self.assertEqual(dataset.dataset_id, "synthetic-events")
        self.assertEqual(dataset.origin, "synthetic")
        self.assertEqual(dataset.source_revision, "source-export-1")
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

    def test_import_assigns_receipts_and_deduplicates_without_changing_them(self):
        original = populated_dataset()
        raw = interaction()
        imported = ingest_records(original, [raw, deepcopy(raw)], received_at=LATER)
        self.assertEqual(len(original.records), 4)
        self.assertEqual(len(imported.records), 5)
        self.assertEqual(imported.records[-1]["ingest_seq"], 5)
        self.assertEqual(imported.records[-1]["recorded_at"], LATER)
        repeated = ingest_records(imported, [raw], received_at="2026-01-01T00:00:00Z")
        self.assertIs(repeated, imported)
        self.assertEqual(repeated.content_hash, imported.content_hash)
        self.assertEqual(imported.source_revision, original.source_revision)

    def test_same_record_id_with_changed_source_content_fails(self):
        raw = interaction()
        original = ingest_records(populated_dataset(), [raw], received_at=LATER)
        for field in ("payload", "source"):
            bad = deepcopy(raw)
            if field == "payload":
                bad[field]["topic"] = "different"
            else:
                bad[field]["revision"] = "different"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "different source content"):
                ingest_records(original, [bad], received_at=LATER)

    def test_identical_actions_with_distinct_ids_remain_two_events(self):
        dataset = ingest_records(populated_dataset(), [interaction("first"), interaction("second")], received_at=LATER)
        self.assertEqual([r["record_id"] for r in dataset.as_known() if r["kind"] == "interaction.observed"], ["first", "second"])

    def test_corrections_and_retractions_preserve_historical_versions(self):
        dataset = ingest_records(populated_dataset(), [interaction(occurred_at=12)], received_at=LATER)
        correction = interaction("corrected", fact_id="speech", supersedes="speech", occurred_at=5)
        dataset = ingest_records(dataset, [correction], received_at=LATER)
        self.assertEqual(dataset.as_known(5)[-1]["record_id"], "speech")
        self.assertEqual(dataset.as_known(5)[-1]["occurred_at"], 12)
        self.assertEqual(dataset.as_known(6)[-1]["record_id"], "corrected")
        self.assertEqual(dataset.as_known(6)[-1]["occurred_at"], 5)
        withdrawal = raw_record("withdrawn", "interaction.observed", None,
                                fact_id="speech", supersedes="corrected", operation="retract")
        dataset = ingest_records(dataset, [withdrawal], received_at=LATER)
        self.assertEqual(len(dataset.as_known()), 4)
        self.assertEqual(dataset.as_known(6)[-1]["record_id"], "corrected")
        restored = interaction("restored", fact_id="speech", supersedes="withdrawn")
        self.assertEqual(ingest_records(dataset, [restored], received_at=LATER).as_known()[-1]["record_id"], "restored")

    def test_missing_predecessors_cross_fact_source_kind_and_forks_fail(self):
        base = ingest_records(populated_dataset(), [interaction()], received_at=LATER)
        revised = ingest_records(base, [interaction("r2", fact_id="speech", supersedes="speech")], received_at=LATER)
        cases = [
            (base, interaction("missing", fact_id="speech", supersedes="unknown")),
            (base, interaction("self", fact_id="speech", supersedes="self")),
            (base, interaction("cross-fact", fact_id="other", supersedes="speech")),
            (base, interaction("cross-source", fact_id="speech", supersedes="speech", system="other")),
            (revised, interaction("fork", fact_id="speech", supersedes="speech")),
            (base, interaction("second-root", fact_id="speech")),
            (base, raw_record("cross-kind", "actor.attribute.observed", {"actor": "alice", "name": "score", "value": 1}, fact_id="speech", supersedes="speech")),
        ]
        for dataset, raw in cases:
            with self.subTest(record_id=raw["record_id"]), self.assertRaises(ValueError):
                ingest_records(dataset, [raw], received_at=LATER)

    def test_fact_ids_are_scoped_to_source_system(self):
        dataset = ingest_records(populated_dataset(), [
            interaction("s1", fact_id="same"),
            interaction("s2", fact_id="same", system="other"),
        ], received_at=LATER)
        self.assertEqual(len(dataset.as_known()), 6)

    def test_entities_and_identity_mapping_respect_knowledge_cutoff(self):
        dataset = populated_dataset()
        self.assertEqual(dataset.entities_at(1), {"alice": "person"})
        self.assertEqual(dataset.entities_at(0), {})
        mapping = raw_record("alias-v1", "identity.mapped", {"alias": "alice-alias", "canonical": "alice"})
        dataset = ingest_records(dataset, [mapping], received_at=LATER)
        self.assertEqual(dataset.identity_map_at(4), {})
        self.assertEqual(dataset.identity_map_at(5), {"alice-alias": "alice"})
        correction = raw_record("alias-v2", "identity.mapped", {"alias": "alice-alias", "canonical": "bob"}, fact_id="alias-v1", supersedes="alias-v1")
        dataset = ingest_records(dataset, [correction], received_at=LATER)
        self.assertEqual(dataset.identity_map_at(5), {"alice-alias": "alice"})
        self.assertEqual(dataset.identity_map_at(), {"alice-alias": "bob"})
        dataset.identity_map_at()["alice-alias"] = "changed"
        self.assertEqual(dataset.identity_map_at(), {"alice-alias": "bob"})

    def test_identity_chains_resolve_and_cycles_unknowns_and_type_merges_fail(self):
        base = populated_dataset()
        one = raw_record("map-one", "identity.mapped", {"alias": "alice-alias", "canonical": "alice"})
        dataset = ingest_records(base, [one], received_at=LATER)
        two = raw_record("map-two", "identity.mapped", {"alias": "alice", "canonical": "bob"})
        chained = ingest_records(dataset, [two], received_at=LATER)
        self.assertEqual(chained.identity_map_at(), {"alice": "bob", "alice-alias": "bob"})
        for alias, canonical in (("alice", "alice-alias"), ("bob", "unknown"), ("bob", "meeting"), ("bob", "bob")):
            with self.subTest(alias=alias, canonical=canonical), self.assertRaises(ValueError):
                ingest_records(dataset, [raw_record("bad-map", "identity.mapped", {"alias": alias, "canonical": canonical})], received_at=LATER)

    def test_identity_merge_cannot_turn_active_relation_into_self_tie(self):
        base = ingest_records(populated_dataset(), [interaction()], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "self-tie"):
            ingest_records(base, [raw_record("merge", "identity.mapped", {"alias": "alice", "canonical": "bob"})], received_at=LATER)

    def test_entity_retraction_rejects_dangling_active_facts_at_that_prefix(self):
        base = ingest_records(populated_dataset(), [interaction()], received_at=LATER)
        remove_alice = raw_record("remove-alice", "entity.observed", None,
                                  fact_id="declare-alice", supersedes="declare-alice", operation="retract")
        remove_speech = raw_record("remove-speech", "interaction.observed", None,
                                   fact_id="speech", supersedes="speech", operation="retract")
        with self.assertRaisesRegex(ValueError, "known person"):
            ingest_records(base, [remove_alice, remove_speech], received_at=LATER)
        result = ingest_records(base, [remove_speech, remove_alice], received_at=LATER)
        self.assertNotIn("alice", result.entities_at())
        self.assertIn("alice", result.entities_at(5))
        self.assertEqual(result.as_known(5)[-1]["record_id"], "speech")

    def test_observed_membership_requires_interval_and_change_requires_point(self):
        payload = {"actor": "alice", "population": "cohort", "status": "present"}
        observed = raw_record("presence", "membership.observed", payload, occurred_at=1, valid_interval=[0, 10])
        changed = raw_record("left", "membership.changed", {**payload, "status": "absent"}, occurred_at=10)
        result = ingest_records(populated_dataset(), [observed, changed], received_at=LATER)
        self.assertEqual(result.as_known()[-2]["valid_interval"], [0, 10])
        self.assertIsNone(result.as_known()[-1]["valid_interval"])
        for raw in (raw_record("bad", "membership.observed", payload), raw_record("bad", "membership.changed", payload, valid_interval=[0, None])):
            with self.subTest(kind=raw["kind"]), self.assertRaises(ValueError):
                ingest_records(populated_dataset(), [raw], received_at=LATER)

    def test_typed_activity_participation_coverage_and_reference_validation(self):
        good = [
            raw_record("held", "activity.observed", {"activity": "meeting", "activity_type": "meeting", "status": "held"}, valid_interval=[0, 20]),
            raw_record("attended", "participation.observed", {"actor": "alice", "activity": "meeting", "role": "speaker", "status": "attended"}, valid_interval=[2, 10]),
            raw_record("coverage", "coverage.observed", {"population": "cohort", "layer": "communication", "actors": ["alice", "bob"], "status": "partial"}, valid_interval=[0, 20]),
            raw_record("attribute", "actor.attribute.observed", {"actor": "alice", "name": "observed_score", "value": None}),
            raw_record("zero", "relation.observed", {"layer": "trust_rating", "source": "alice", "target": "bob", "directed": True, "strength": 0}),
        ]
        result = ingest_records(populated_dataset(), good, received_at=LATER)
        self.assertEqual(result.as_known()[-3]["payload"]["status"], "partial")
        self.assertIsNone(result.as_known()[-2]["payload"]["value"])
        self.assertEqual(result.as_known()[-1]["payload"]["strength"], 0)
        bad_activity = deepcopy(good[0])
        bad_activity["payload"]["activity"] = "alice"
        bad_participant = deepcopy(good[1])
        bad_participant["payload"]["actor"] = "meeting"
        bad_coverage = deepcopy(good[2])
        bad_coverage["payload"]["actors"] = ["alice", "unknown"]
        for raw in (bad_activity, bad_participant, bad_coverage):
            with self.subTest(kind=raw["kind"]), self.assertRaises(ValueError):
                ingest_records(populated_dataset(), [raw], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "known person"):
            ingest_records(empty_dataset(), [interaction(), entity_record("alice"), entity_record("bob")], received_at=RECEIPT)

    def test_numeric_and_shape_errors_are_value_errors(self):
        relation = raw_record("relation", "relation.changed", {"layer": "trust", "source": "alice", "target": "bob", "directed": True, "strength": 1})
        for strength in (True, "1", [], -1, float("nan"), float("inf"), 10 ** 1000):
            raw = deepcopy(relation)
            raw["payload"]["strength"] = strength
            with self.subTest(strength_type=type(strength).__name__), self.assertRaises(ValueError):
                ingest_records(populated_dataset(), [raw], received_at=LATER)
        invalid = []
        for field, value in (("kind", []), ("source", []), ("payload", []), ("operation", {}), ("valid_interval", [0, True])):
            raw = interaction()
            raw[field] = value
            invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                ingest_records(populated_dataset(), [raw], received_at=LATER)
        for attribute in ([], {}, float("nan"), float("inf")):
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                ingest_records(populated_dataset(), [raw_record("attr", "actor.attribute.observed", {"actor": "alice", "name": "score", "value": attribute})], received_at=LATER)

    def test_receipt_prefix_order_and_raw_receipt_injection_fail(self):
        for field, value in (("ingest_seq", 2), ("ingest_seq", True), ("recorded_at", "2026-11-26T00:00:00Z")):
            mapping = populated_dataset().to_dict()
            mapping["records"][1][field] = value
            if field == "ingest_seq" and value == 2:
                mapping["records"][1][field] = 3
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                EventDataset.from_mapping(mapping)
        injected = interaction()
        injected["ingest_seq"] = 5
        injected["recorded_at"] = LATER
        with self.assertRaises(ValueError):
            ingest_records(populated_dataset(), [injected], received_at=LATER)
        with self.assertRaisesRegex(ValueError, "nondecreasing"):
            ingest_records(populated_dataset(), [interaction()], received_at="2026-01-01T00:00:00Z")
        for cutoff in (-1, 5, True, "1", 1.0):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                populated_dataset().as_known(cutoff)

    def test_file_loading_rejects_duplicate_json_and_undeclared_schema(self):
        mapping = populated_dataset().to_dict()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            self.assertEqual(load_event_dataset(path).to_dict(), mapping)
            duplicate = json.dumps(mapping).replace('"system": "study"', '"system": "other", "system": "study"', 1)
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                load_event_dataset(path)
        for field, value in (("origin", []), ("clock", {"kind": "ticks"}), ("records", ()), ("schema", "other")):
            bad = deepcopy(mapping)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                EventDataset.from_mapping(bad)
        with self.assertRaises(ValueError):
            ingest_records(populated_dataset(), [raw_record("label", "annotation.recorded", {})], received_at=LATER)

    def test_utc_and_ticks_are_exact_distinct_clock_domains(self):
        utc = {"kind": "utc"}
        ticks = {"kind": "ticks", "run_id": "run-1"}
        self.assertEqual(parse_time("1970-01-01T00:00:00Z", utc), 0)
        self.assertEqual(parse_time("1970-01-01T00:00:00.000001+00:00", utc), 1)
        self.assertEqual(parse_time("1969-12-31T23:59:59.999999Z", utc), -1)
        self.assertEqual(parse_time(123, ticks), 123)
        dataset = ingest_records(empty_dataset(utc), [entity_record("alice", occurred_at="2026-11-27T10:00:00.123456Z")], received_at=RECEIPT)
        self.assertEqual(dataset.records[0]["occurred_at"], "2026-11-27T10:00:00.123456Z")
        for value in (True, 0.0, -1, "1", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time(value, ticks)
        for value in (0, "2026-11-27", "2026-11-27T10:00:00", "2026-11-27T10:00:00+09:00", "2026-11-27T10:00:00.1234567Z", "2026-02-30T10:00:00Z"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time(value, utc)


if __name__ == "__main__":
    unittest.main()
