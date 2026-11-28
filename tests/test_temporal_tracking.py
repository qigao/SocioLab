"""Source-time and receipt transitions through the original snapshot engine."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from sociolab.affiliations import affiliation_report
from sociolab.changes import compare_snapshots
from sociolab.events import EventDataset, ingest_records, parse_time
from sociolab.snapshots import NetworkSnapshot, content_hash, materialize_snapshot
from sociolab.temporal_tracking import (
    initialize_temporal_tracking, apply_temporal_tracking_batch,
    advance_temporal_tracking, validate_temporal_tracking_state,
)
from test_network_tracking import population_dataset


RECEIPT = "2026-11-28T00:00:00Z"
LATER = "2026-11-28T00:01:00Z"
ACTORS = ["A", "B", "C", "D"]
FLAGS = ("observed_graph_changed", "population_changed", "coverage_changed", "evidence_changed")


def source_time(value, utc=False):
    if not utc:
        return value
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value)
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def raw(identifier, kind, payload, *, at=0, interval=None):
    return {
        "record_id": identifier, "fact_id": identifier, "operation": "assert", "supersedes": None,
        "kind": kind, "occurred_at": at, "valid_interval": interval,
        "source": {"system": "invented-temporal-test", "record_id": identifier,
                   "revision": "v1", "evidence_ref": "synthetic:" + identifier},
        "payload": payload,
    }


def dataset(*, utc=False, coverage_end=None, membership_end=None):
    at = lambda value: source_time(value, utc)
    empty = EventDataset.from_mapping({
        "schema": "sociolab.events.v1", "dataset_id": "invented-temporal-test", "origin": "synthetic",
        "source_revision": "fixed-envelope", "clock": {"kind": "utc"} if utc else {"kind": "ticks", "run_id": "temporal-test"},
        "records": [],
    })
    records = [raw("person-" + actor, "entity.observed", {"entity_id": actor, "entity_type": "person"}, at=at(0))
               for actor in ACTORS + ["alias-A"]]
    records.append(raw("identity", "identity.mapped", {"alias": "alias-A", "canonical": "A"}, at=at(0)))
    for actor in ACTORS:
        end = at(membership_end) if actor == "A" and membership_end is not None else None
        records.append(raw("member-" + actor, "membership.observed", {"actor": actor, "population": "team", "status": "present"},
                           at=at(0), interval=[at(0), end]))
    for layer in ("cooperation", "communication"):
        end = None if coverage_end is None else at(coverage_end)
        records.append(raw("coverage-" + layer, "coverage.observed", {
            "population": "team", "layer": layer, "actors": ACTORS, "status": "complete"}, at=at(0), interval=[at(0), end]))
    records.append(raw("tie-AB", "relation.observed", {
        "source": "A", "target": "B", "layer": "cooperation", "directed": False, "strength": 1},
        at=at(0), interval=[at(0), at(10)]))
    for when, actor, target in ((0, "A", "B"), (4, "C", "D"), (5, "alias-A", "B"), (9, "B", "C"), (10, "C", "D")):
        records.append(raw("message-" + str(when), "interaction.observed", {
            "actor": actor, "target": target, "action": "utterance", "topic": None}, at=at(when)))
    return ingest_records(empty, records, received_at=RECEIPT)


def registration(cursor=10, *, utc=False, modes=("state", "events"), width=5):
    return {
        "schema": "sociolab.temporal-tracking-spec.v1", "initial_cursor": source_time(cursor, utc),
        "source_time_unit": "microsecond" if utc else "tick", "views": [
            {"view_id": mode, "view": {
                "schema": "sociolab.view.v1", "population": "team", "layer": "cooperation" if mode == "state" else "communication",
                "mode": mode, "directed": mode != "state", **({"actions": ["utterance"]} if mode == "events" else {}),
            }, "window_width": None if mode == "state" else width, "analysis": {}} for mode in modes
        ],
    }


def revision(state, identifier, new_identifier, **updates):
    old = next(record for record in state["dataset"]["records"] if record["record_id"] == identifier)
    record = deepcopy({key: value for key, value in old.items() if key not in {"recorded_at", "ingest_seq"}})
    record.update(record_id=new_identifier, supersedes=identifier)
    record["source"] = {**record["source"], "record_id": new_identifier, "revision": "v2"}
    record.update(deepcopy(updates))
    return record


def rehash(value):
    value["content_hash"] = content_hash({key: item for key, item in value.items() if key != "content_hash"})
    return value


def edges(state, index=0):
    return {(edge["source"], edge["target"], edge["strength"]) for edge in state["views"][index]["snapshot"]["edges"]}


class TemporalTrackingTests(unittest.TestCase):
    def test_initialization_normalizes_templates_without_mutating_inputs_and_replays_upstream(self):
        source, spec = dataset(), registration()
        original, source_original = deepcopy(spec), source.to_dict()
        with patch("sociolab.network_tracking.materialize_snapshot", wraps=materialize_snapshot) as materializer:
            state = initialize_temporal_tracking(source, spec)
        self.assertEqual(materializer.call_count, 2)
        self.assertEqual(spec, original)
        self.assertEqual(source.to_dict(), source_original)
        self.assertEqual(state["sequence"], 0)
        self.assertIsNone(state["previous_state_hash"])
        self.assertEqual(state["cursor"], 10)
        self.assertEqual(state["cursor_value"], 10)
        self.assertEqual(state["knowledge_cutoff"], len(source.records))
        for declared in state["registration"]["views"]:
            self.assertFalse({"at", "start", "end"} & set(declared["view"]))
            self.assertEqual(declared["analysis"]["algorithm"], "greedy")
        with patch("sociolab.temporal_tracking.materialize_snapshot", wraps=materialize_snapshot) as replay:
            validated = validate_temporal_tracking_state(state)
        self.assertEqual(replay.call_count, 2)
        self.assertEqual(validated, state)
        self.assertIsNot(validated["dataset"], state["dataset"])
        spec["views"][0]["view"]["population"] = "edited-input"
        self.assertEqual(state["registration"]["views"][0]["view"]["population"], "team")

    def test_window_advance_without_receipts_selects_half_open_endpoints_and_retains_old_version(self):
        state = initialize_temporal_tracking(dataset(), registration(modes=("events",)))
        old = deepcopy(state)
        self.assertEqual(edges(state), {("A", "B", 1), ("B", "C", 1)})  # start=5 included, end=10 excluded
        with patch("sociolab.network_tracking.compare_snapshots", wraps=compare_snapshots) as comparison:
            result = advance_temporal_tracking(state, 11)
        comparison.assert_called_once()
        advanced, transition = result["state"], result["transition"]
        self.assertEqual(edges(advanced), {("B", "C", 1), ("C", "D", 1)})
        self.assertEqual(state, old)
        self.assertEqual(advanced["dataset"], state["dataset"])
        self.assertEqual(advanced["knowledge_cutoff"], state["knowledge_cutoff"])
        self.assertEqual(advanced["sequence"], 1)
        self.assertEqual(advanced["previous_state_hash"], state["content_hash"])
        self.assertEqual(transition["cause"], "source_time_advance")
        self.assertEqual(transition["status"], "APPLIED")
        self.assertEqual((transition["before_cursor"], transition["after_cursor"]), (10, 11))
        self.assertEqual((transition["before_cursor_value"], transition["after_cursor_value"]), (10, 11))
        self.assertEqual(transition["source"], {
            "appended_record_count": 0, "new_assertion_count": 0, "revised_assertion_count": 0, "retraction_count": 0,
            "first_ingest_seq": None, "last_ingest_seq": None, "recorded_at": None,
            "appended_records_hash": content_hash([]), "record_ids": [],
        })
        change = transition["views"][0]
        self.assertTrue(change["observed_graph_changed"])
        self.assertFalse(change["population_changed"])
        self.assertFalse(change["coverage_changed"])
        self.assertTrue(change["evidence_changed"])
        self.assertEqual(change["comparison"]["report"]["engine"], "networkx")
        self.assertEqual(change["comparison"]["report"]["source_changes"]["new_records"], [])

    def test_state_interval_expires_at_its_end_without_new_source_records(self):
        state = initialize_temporal_tracking(dataset(), registration(9, modes=("state",)))
        result = advance_temporal_tracking(state, 10)
        self.assertEqual(edges(state), {("A", "B", 1)})
        self.assertEqual(edges(result["state"]), set())
        self.assertTrue(result["transition"]["views"][0]["observed_graph_changed"])
        self.assertEqual(result["state"]["knowledge_cutoff"], state["knowledge_cutoff"])
        self.assertFalse(result["transition"]["scope"]["window_expiry_proves_real_relation_ended"])

    def test_time_only_version_with_unchanged_components_and_equal_time_retry(self):
        state = initialize_temporal_tracking(dataset(), registration(10, modes=("state",)))
        with patch("sociolab.network_tracking.compare_snapshots", side_effect=AssertionError("no semantic change")):
            advanced = advance_temporal_tracking(state, 11)
            repeated = advance_temporal_tracking(advanced["state"], 11)
        self.assertEqual(advanced["state"]["sequence"], 1)
        self.assertNotEqual(advanced["state"]["content_hash"], state["content_hash"])
        view = advanced["transition"]["views"][0]
        self.assertNotEqual(view["before_snapshot_hash"], view["after_snapshot_hash"])
        self.assertTrue(all(not view[flag] for flag in FLAGS))
        self.assertEqual(view["comparison"], {"status": "NOT_RUN", "reason": "no_observable_change"})
        self.assertEqual(repeated["state"], advanced["state"])
        self.assertEqual(repeated["transition"]["status"], "NO_TIME_ADVANCE")
        self.assertEqual(repeated["transition"]["before_state_hash"], repeated["transition"]["after_state_hash"])
        with self.assertRaisesRegex(ValueError, "backwards"):
            advance_temporal_tracking(advanced["state"], 10)

    def test_receipt_and_source_time_are_independent_and_retries_replay_only_new_tail(self):
        state = advance_temporal_tracking(initialize_temporal_tracking(dataset(), registration()), 11)["state"]
        duplicate = {key: value for key, value in state["dataset"]["records"][0].items() if key not in {"recorded_at", "ingest_seq"}}
        fresh = raw("unrelated", "actor.attribute.observed", {"actor": "A", "name": "note", "value": "invented"}, at=1000)
        mixed = apply_temporal_tracking_batch(state, [duplicate, fresh], received_at=LATER)
        replayed = apply_temporal_tracking_batch(state, [fresh], received_at=LATER)
        self.assertEqual(mixed, replayed)
        self.assertEqual(mixed["state"]["cursor"], 11)
        self.assertEqual(mixed["state"]["knowledge_cutoff"], state["knowledge_cutoff"] + 1)
        self.assertEqual(mixed["transition"]["cause"], "receipt_batch")
        self.assertEqual(mixed["transition"]["source"]["record_ids"], ["unrelated"])
        for change in mixed["transition"]["views"]:
            self.assertTrue(all(not change[flag] for flag in FLAGS))
        for batch in ([], [duplicate], [fresh]):
            retry = apply_temporal_tracking_batch(mixed["state"], batch, received_at="2020-01-01T00:00:00Z")
            self.assertEqual(json.dumps(retry["state"], sort_keys=True), json.dumps(mixed["state"], sort_keys=True))
            self.assertEqual(retry["transition"]["status"], "NO_NEW_RECORDS")
            self.assertTrue(all(not change[flag] for change in retry["transition"]["views"] for flag in FLAGS))

    def test_late_time_correction_rebuilds_current_window_without_changing_prior_versions(self):
        initial = initialize_temporal_tracking(dataset(), registration(modes=("events",)))
        state = advance_temporal_tracking(initial, 12)["state"]
        original, old_initial = deepcopy(state), deepcopy(initial)
        correction = revision(state, "message-5", "late-time", occurred_at=11)
        with patch("sociolab.network_tracking.compare_snapshots", wraps=compare_snapshots) as comparison:
            result = apply_temporal_tracking_batch(state, [correction], received_at=LATER)
        comparison.assert_called_once()
        self.assertEqual(state, original)
        self.assertEqual(initial, old_initial)
        self.assertNotIn(("A", "B", 1), edges(state))
        self.assertIn(("A", "B", 1), edges(result["state"]))
        self.assertEqual(result["state"]["cursor"], 12)
        self.assertEqual(result["transition"]["source"]["revised_assertion_count"], 1)

    def test_alias_and_same_value_revisions_keep_graph_and_evidence_changes_separate(self):
        state = initialize_temporal_tracking(dataset(), registration(modes=("events",)))
        same = revision(state, "message-5", "reconfirmed-message")
        unchanged = apply_temporal_tracking_batch(state, [same], received_at=LATER)
        flags = unchanged["transition"]["views"][0]
        self.assertFalse(flags["observed_graph_changed"])
        self.assertTrue(flags["evidence_changed"])
        self.assertEqual(flags["comparison"]["reason"], "no_observable_change")
        mapping = revision(unchanged["state"], "identity", "corrected-identity", payload={"alias": "alias-A", "canonical": "D"})
        changed = apply_temporal_tracking_batch(unchanged["state"], [mapping], received_at=LATER)
        self.assertIn(("D", "B", 1), edges(changed["state"]))
        self.assertIn(("A", "B", 1), edges(state))
        self.assertTrue(changed["transition"]["views"][0]["observed_graph_changed"])

    def test_membership_expiry_is_unknown_and_recovery_uses_immediate_incomplete_predecessor(self):
        state = initialize_temporal_tracking(dataset(membership_end=10), registration(9, modes=("state",)))
        with patch("sociolab.network_tracking.compare_snapshots", side_effect=AssertionError("incomplete comparison")):
            expired = advance_temporal_tracking(state, 10)
            absence = raw("known-absence", "membership.observed", {"actor": "A", "population": "team", "status": "absent"}, at=10, interval=[10, None])
            restored = apply_temporal_tracking_batch(expired["state"], [absence], received_at=LATER)
        snapshot = expired["state"]["views"][0]["snapshot"]
        self.assertIn("A", snapshot["population"]["unknown"])
        self.assertNotIn("A", snapshot["population"]["absent"])
        change = restored["transition"]["views"][0]
        self.assertFalse(change["before_complete"])
        self.assertTrue(change["after_complete"])
        self.assertEqual(change["before_snapshot_hash"], snapshot["content_hash"])
        self.assertEqual(change["comparison"]["reason"], "incomplete_before_or_after_coverage")

    def test_coverage_expiry_can_change_only_coverage_and_evidence(self):
        # Keep the relation observed at both cursors while coverage reaches its end.
        source = dataset(coverage_end=10).to_dict()
        tie = next(record for record in source["records"] if record["record_id"] == "tie-AB")
        tie["valid_interval"][1] = 20
        state = initialize_temporal_tracking(EventDataset.from_mapping(source), registration(8, modes=("state",)))
        result = advance_temporal_tracking(state, 10)
        change = result["transition"]["views"][0]
        self.assertFalse(change["observed_graph_changed"])
        self.assertFalse(change["population_changed"])
        self.assertTrue(change["coverage_changed"])
        self.assertTrue(change["evidence_changed"])
        self.assertEqual(change["comparison"]["reason"], "incomplete_before_or_after_coverage")

    def test_utc_microseconds_and_equivalent_spellings_are_exact_and_idempotent(self):
        source, spec = dataset(utc=True), registration(utc=True, modes=("events",))
        spec["initial_cursor"] = "2026-01-01T00:00:00.000010+00:00"
        state = initialize_temporal_tracking(source, spec)
        self.assertEqual(state["cursor"], "2026-01-01T00:00:00.000010Z")
        self.assertEqual(state["cursor_value"], parse_time(spec["initial_cursor"], source.clock))
        equal = advance_temporal_tracking(state, spec["initial_cursor"])
        self.assertEqual(equal["state"], state)
        self.assertEqual(equal["transition"]["status"], "NO_TIME_ADVANCE")
        advanced = advance_temporal_tracking(state, "2026-01-01T00:00:00.000011+00:00")
        self.assertEqual(advanced["state"]["cursor_value"] - state["cursor_value"], 1)
        view = advanced["state"]["views"][0]["snapshot"]["view"]
        self.assertEqual(view["start"], "2026-01-01T00:00:00.000006Z")
        self.assertEqual(view["end"], "2026-01-01T00:00:00.000011Z")
        self.assertEqual(edges(advanced["state"]), {("B", "C", 1), ("C", "D", 1)})

    def test_invalid_units_widths_ticks_utc_precision_and_window_underflow_are_rejected(self):
        source = dataset()
        invalid = []
        for width in (0, -1, True, 1.0, float("inf"), None, 11):
            spec = registration(modes=("events",), width=width)
            invalid.append(spec)
        for cursor in (True, 10.0, -1, "10"):
            invalid.append({**registration(), "initial_cursor": cursor})
        invalid.append({**registration(), "source_time_unit": "microsecond"})
        invalid.append({**registration(), "extra": None})
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                initialize_temporal_tracking(source, spec)
        for name, value in (("at", 10), ("start", 0), ("end", 10), ("unknown", True)):
            spec = registration()
            spec["views"][0]["view"][name] = value
            with self.assertRaises(ValueError):
                initialize_temporal_tracking(source, spec)
        spec = registration()
        spec["views"][0]["window_width"] = 1
        with self.assertRaises(ValueError):
            initialize_temporal_tracking(source, spec)
        utc_source = dataset(utc=True)
        for cursor in ("2026-01-01T00:00:00", "2026-01-01T00:00:00.0000001Z", "2026-01-01T01:00:00+01:00", "10000-01-01T00:00:00Z"):
            spec = {**registration(utc=True), "initial_cursor": cursor}
            with self.assertRaises(ValueError):
                initialize_temporal_tracking(utc_source, spec)
        for cursor, width in (("0001-01-01T00:00:00Z", 1), ("2026-01-01T00:00:00Z", 10 ** 30)):
            spec = {**registration(utc=True, modes=("events",), width=width), "initial_cursor": cursor}
            with self.assertRaisesRegex(ValueError, "UTC calendar"):
                initialize_temporal_tracking(utc_source, spec)

    def test_rehashed_cursor_template_snapshot_and_scope_tampering_fail_replay(self):
        state = advance_temporal_tracking(initialize_temporal_tracking(dataset(), registration(modes=("events",))), 11)["state"]
        altered = deepcopy(state)
        altered.update(cursor=12, cursor_value=12)
        with self.assertRaisesRegex(ValueError, "does not match replay"):
            validate_temporal_tracking_state(rehash(altered))
        altered = deepcopy(state)
        altered["registration"]["views"][0]["window_width"] = 4
        altered["registration_hash"] = content_hash(altered["registration"])
        with self.assertRaisesRegex(ValueError, "does not match replay"):
            validate_temporal_tracking_state(rehash(altered))
        altered = deepcopy(state)
        snapshot = altered["views"][0]["snapshot"]
        snapshot.pop("content_hash")
        snapshot["edges"][0]["strength"] = 2
        altered["views"][0]["snapshot"] = NetworkSnapshot.create(snapshot).to_dict()
        with self.assertRaisesRegex(ValueError, "does not match replay"):
            validate_temporal_tracking_state(rehash(altered))
        for key, value in (("cursor_value", True), ("knowledge_cutoff", True), ("sequence", True), ("extra", None)):
            altered = deepcopy(state)
            altered[key] = value
            with self.assertRaises(ValueError):
                validate_temporal_tracking_state(rehash(altered))
        altered = deepcopy(state)
        altered["scope"]["explicit_source_time_advance"] = 1
        with self.assertRaisesRegex(ValueError, "scope"):
            validate_temporal_tracking_state(rehash(altered))

    def test_time_operations_reuse_projection_budget_before_any_structural_comparison(self):
        source, _ = population_dataset(67, participation=True)
        spec = {
            "schema": "sociolab.temporal-tracking-spec.v1", "initial_cursor": 2, "source_time_unit": "tick",
            "views": [{"view_id": "attendance", "view": {"schema": "sociolab.view.v1", "population": "cohort", "layer": "participation",
                "mode": "participation", "directed": False}, "window_width": 2, "analysis": {"projection": "count"}}],
        }
        state = initialize_temporal_tracking(source, spec)
        self.assertEqual(len(state["views"][0]["snapshot"]["edges"]), 67)
        with patch("sociolab.network_tracking.affiliation_report", wraps=affiliation_report) as projection, \
                patch("sociolab.network_tracking.compare_snapshots", side_effect=AssertionError("projection exceeds whole-analysis budget")):
            result = advance_temporal_tracking(state, 4)
        self.assertGreaterEqual(projection.call_count, 1)
        self.assertEqual(result["state"]["views"][0]["snapshot"]["edges"], [])
        self.assertEqual(result["transition"]["views"][0]["comparison"], {"status": "NOT_RUN", "reason": "analysis_budget_exceeded"})

    def test_operation_failures_preserve_inputs_and_do_not_hide_upstream_errors(self):
        state = initialize_temporal_tracking(dataset(), registration(modes=("events",)))
        original = deepcopy(state)
        with patch("sociolab.network_tracking.compare_snapshots", side_effect=RuntimeError("upstream failure")):
            with self.assertRaisesRegex(RuntimeError, "upstream failure"):
                advance_temporal_tracking(state, 11)
        self.assertEqual(state, original)
        reused = {key: value for key, value in state["dataset"]["records"][0].items() if key not in {"recorded_at", "ingest_seq"}}
        reused["source"] = {**reused["source"], "revision": "different"}
        with self.assertRaisesRegex(ValueError, "record ID reused"):
            apply_temporal_tracking_batch(state, [reused], received_at=LATER)
        self.assertEqual(state, original)
        for cursor in (True, 11.0, "11", -1):
            with self.assertRaises(ValueError):
                advance_temporal_tracking(state, cursor)
            self.assertEqual(state, original)


if __name__ == "__main__":
    unittest.main()
