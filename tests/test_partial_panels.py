"""Native contract tests; no optional estimator or source archive is needed."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab import partial_panels
from sociolab.partial_panels import PartialNetworkPanel, PartialNetworkWave, load_partial_panel


def example():
    return {
        "schema": "sociolab.partial-network.v1",
        "dataset_id": "synthetic-partial",
        "origin": "synthetic",
        "source_reference": None,
        "actors": ["alice", "bob", "carol"],
        "relation": "friendship",
        "population_definition": "The same three synthetic actors at both waves.",
        "observation_definition": "Listed pairs are observed; all other nonself pairs are unknown.",
        "waves": [
            {"time_index": 0, "source_revision": "synthetic-w0",
             "observed_present": [["alice", "bob"]],
             "observed_absent": [["carol", "alice"]]},
            {"time_index": 2, "source_revision": "synthetic-w2",
             "observed_present": [["bob", "alice"], ["carol", "alice"]],
             "observed_absent": [["alice", "bob"]]},
        ],
    }


class PartialPanelTests(unittest.TestCase):
    def test_unknown_outgoing_observations_preserve_known_incoming(self):
        panel = PartialNetworkPanel.from_mapping(example())
        first = panel.waves[0]
        self.assertIn(("alice", "bob"), first.observed_present)
        self.assertFalse(any(source == "bob" for source, _ in first.observed_present))
        self.assertFalse(any(source == "bob" for source, _ in first.observed_absent))
        self.assertEqual(first.observed_absent, (("carol", "alice"),))
        self.assertNotIn(("alice", "carol"), first.observed_absent)
        self.assertEqual(panel.actors, ("alice", "bob", "carol"))
        self.assertEqual(first.to_dict(), example()["waves"][0])

    def test_all_unknown_waves_remain_valid_descriptions(self):
        data = example()
        for wave in data["waves"]:
            wave["observed_present"] = []
            wave["observed_absent"] = []
        panel = PartialNetworkPanel.from_mapping(data)
        self.assertEqual(panel.to_dict(), data)
        self.assertEqual(panel.waves, (
            PartialNetworkWave(0, "synthetic-w0", (), ()),
            PartialNetworkWave(2, "synthetic-w2", (), ()),
        ))
        self.assertNotIn("network_complete", panel.to_dict()["waves"][0])

    def test_roundtrip_file_and_canonical_hash(self):
        data = example()
        panel = PartialNetworkPanel.from_mapping(data)
        self.assertEqual(panel.to_dict(), data)
        self.assertEqual(PartialNetworkPanel.from_mapping(panel.to_dict()), panel)
        self.assertRegex(panel.content_hash, r"^sha256:[0-9a-f]{64}$")
        reordered = dict(reversed(list(data.items())))
        self.assertEqual(PartialNetworkPanel.from_mapping(reordered).content_hash, panel.content_hash)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "partial.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(load_partial_panel(path), panel)

    def test_hash_binds_absence_unknown_direction_and_all_metadata(self):
        original = example()
        baseline = PartialNetworkPanel.from_mapping(original).content_hash
        changes = []
        for key in ("dataset_id", "relation", "population_definition", "observation_definition"):
            data = deepcopy(original)
            data[key] += " changed"
            changes.append(data)
        data = deepcopy(original)
        data["actors"].append("dora")
        changes.append(data)
        data = deepcopy(original)
        data["origin"] = "external_observation"
        data["source_reference"] = "https://example.org/study"
        changes.append(data)
        for field, value in (("source_revision", "revised-w0"), ("time_index", 1),
                             ("observed_absent", []),
                             ("observed_present", [["bob", "alice"]])):
            data = deepcopy(original)
            data["waves"][0][field] = value
            changes.append(data)
        for index, data in enumerate(changes):
            with self.subTest(change=index):
                self.assertNotEqual(PartialNetworkPanel.from_mapping(data).content_hash, baseline)
        observed = PartialNetworkPanel.from_mapping(changes[5])
        self.assertNotEqual(replace(observed, source_reference="https://example.org/other").content_hash,
                            observed.content_hash)

    def test_caller_and_serialized_mutations_cannot_change_panel(self):
        data = example()
        panel = PartialNetworkPanel.from_mapping(data)
        baseline = panel.content_hash
        data["actors"][0] = "changed"
        data["waves"][0]["observed_present"][0][0] = "changed"
        dumped = panel.to_dict()
        dumped["actors"].clear()
        dumped["waves"][0]["observed_absent"][0][0] = "changed"
        self.assertEqual(panel.content_hash, baseline)
        self.assertEqual(panel.to_dict(), example())
        with self.assertRaises(FrozenInstanceError):
            panel.relation = "changed"
        with self.assertRaises(FrozenInstanceError):
            panel.waves[0].observed_absent = ()

    def test_present_and_absent_are_disjoint_but_opposite_directions_are_distinct(self):
        data = example()
        data["waves"][0]["observed_absent"] = [["bob", "alice"]]
        panel = PartialNetworkPanel.from_mapping(data)
        self.assertEqual(panel.waves[0].observed_present, (("alice", "bob"),))
        self.assertEqual(panel.waves[0].observed_absent, (("bob", "alice"),))
        data["waves"][0]["observed_absent"] = [["alice", "bob"]]
        with self.assertRaisesRegex(ValueError, "both observed"):
            PartialNetworkPanel.from_mapping(data)
        with self.assertRaisesRegex(ValueError, "both observed"):
            PartialNetworkWave(0, "w0", (("alice", "bob"),), (("alice", "bob"),))

    def test_unknown_id_and_diagonal_are_rejected_in_either_observation_set(self):
        for field in ("observed_present", "observed_absent"):
            for pair in (["alice", "alice"], ["alice", "outsider"], ["outsider", "bob"]):
                with self.subTest(field=field, pair=pair):
                    data = example()
                    data["waves"][0][field] = [pair]
                    with self.assertRaises(ValueError):
                        PartialNetworkPanel.from_mapping(data)

    def test_actors_and_pairs_require_sorted_unique_exact_strings(self):
        for actors in (["alice", "alice", "carol"], ["bob", "alice", "carol"],
                       ["alice", [], "carol"], ["alice", True, "carol"],
                       [" alice", "bob", "carol"]):
            with self.subTest(actors=actors):
                data = example()
                data["actors"] = actors
                with self.assertRaises(ValueError):
                    PartialNetworkPanel.from_mapping(data)
        for field in ("observed_present", "observed_absent"):
            for pairs in ([["alice", "bob"], ["alice", "bob"]],
                          [["carol", "bob"], ["alice", "carol"]],
                          [["alice", []]], [["alice", False]], [["alice", ""]],
                          [["alice"]], ["alice", "bob"], [("alice", "bob")]):
                with self.subTest(field=field, pairs=pairs):
                    data = example()
                    data["waves"][0][field] = pairs
                    with self.assertRaises(ValueError):
                        PartialNetworkPanel.from_mapping(data)

    def test_direct_constructors_enforce_immutable_types_without_typeerror(self):
        panel = PartialNetworkPanel.from_mapping(example())
        for changes in ({"actors": list(panel.actors)}, {"actors": ("alice", [], "carol")},
                        {"waves": list(panel.waves)}, {"waves": (panel.waves[0], {})},
                        {"relation": []}, {"population_definition": False},
                        {"observation_definition": ""}, {"origin": []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(panel, **changes)
        for pairs in ([('alice', 'bob')], (["alice", "bob"],),
                      (("alice", []),), (("alice",),), (True,)):
            for field in ("observed_present", "observed_absent"):
                with self.subTest(field=field, pairs=pairs), self.assertRaises(ValueError):
                    replace(panel.waves[0], **{field: pairs})

    def test_wave_times_and_revisions_are_unambiguous(self):
        for time in (True, False, -1, 0.0, float("nan"), float("inf"), "0", None):
            with self.subTest(time=time), self.assertRaises(ValueError):
                PartialNetworkWave(time, "w0", (), ())
        for field, value in (("time_index", 0), ("time_index", -1),
                             ("source_revision", "synthetic-w0"),
                             ("source_revision", " "), ("source_revision", [])):
            with self.subTest(field=field, value=value):
                data = example()
                data["waves"][1][field] = value
                with self.assertRaises(ValueError):
                    PartialNetworkPanel.from_mapping(data)

    def test_exact_fields_reject_legacy_or_alternative_missingness_aliases(self):
        for field, value in (("network_complete", True), ("behavior", {}),
                             ("composition", []), ("missing_dyads", []), ("edges", [])):
            for location in ("panel", "wave"):
                with self.subTest(field=field, location=location):
                    data = example()
                    (data if location == "panel" else data["waves"][0])[field] = value
                    with self.assertRaises(ValueError):
                        PartialNetworkPanel.from_mapping(data)
        for field in example():
            data = example()
            del data[field]
            with self.subTest(missing_panel_field=field), self.assertRaises(ValueError):
                PartialNetworkPanel.from_mapping(data)
        for field in example()["waves"][0]:
            data = example()
            del data["waves"][0][field]
            with self.subTest(missing_wave_field=field), self.assertRaises(ValueError):
                PartialNetworkPanel.from_mapping(data)
        data = example()
        data["schema"] = "sociolab.longitudinal.v1"
        with self.assertRaises(ValueError):
            PartialNetworkPanel.from_mapping(data)
        with self.assertRaises(ValueError):
            PartialNetworkPanel.from_mapping(None)

    def test_source_and_scope_are_required_declarations(self):
        data = example()
        data["origin"] = "external_observation"
        for reference in (None, "http://example.org/study", "https://has space", True, []):
            data["source_reference"] = reference
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                PartialNetworkPanel.from_mapping(data)
        data["source_reference"] = "https://example.org/study"
        panel = PartialNetworkPanel.from_mapping(data)
        self.assertEqual(panel.source_reference, data["source_reference"])
        self.assertNotIn("empirical_admitted", panel.to_dict())
        with self.assertRaises(ValueError):
            replace(panel, origin="synthetic")
        for field in ("dataset_id", "relation", "population_definition", "observation_definition"):
            for value in ("", " ", " leading", "trailing ", [], None, "bad\ud800"):
                with self.subTest(field=field, value=repr(value)), self.assertRaises(ValueError):
                    replace(panel, **{field: value})

    def test_actor_and_wave_count_bounds_apply_to_mapping_and_constructor(self):
        panel = PartialNetworkPanel.from_mapping(example())
        for count in (1, 501):
            data = example()
            data["actors"] = [f"actor-{index:03d}" for index in range(count)]
            for wave in data["waves"]:
                wave["observed_present"] = wave["observed_absent"] = []
            with self.subTest(actor_count=count), self.assertRaises(ValueError):
                PartialNetworkPanel.from_mapping(data)
            with self.assertRaises(ValueError):
                replace(panel, actors=tuple(data["actors"]))
        empty = [PartialNetworkWave(index, f"w{index}", (), ()) for index in range(21)]
        for count in (1, 21):
            with self.subTest(wave_count=count), self.assertRaises(ValueError):
                replace(panel, waves=tuple(empty[:count]))
            data = example()
            data["waves"] = [wave.to_dict() for wave in empty[:count]]
            with self.assertRaises(ValueError):
                PartialNetworkPanel.from_mapping(data)
        largest = replace(panel, actors=tuple(f"actor-{i:03d}" for i in range(500)),
                          waves=tuple(empty[:20]))
        self.assertEqual(PartialNetworkPanel.from_mapping(largest.to_dict()), largest)

    def test_total_observation_limit_counts_both_states_and_all_waves(self):
        panel = PartialNetworkPanel.from_mapping(example())  # Five observed dyad records.
        with patch.object(partial_panels, "_MAX_OBSERVED_DYADS", 5):
            self.assertEqual(PartialNetworkPanel.from_mapping(example()), panel)
        with patch.object(partial_panels, "_MAX_OBSERVED_DYADS", 4):
            with self.assertRaisesRegex(ValueError, "dyad record limit"):
                PartialNetworkPanel.from_mapping(example())
            with self.assertRaisesRegex(ValueError, "dyad record limit"):
                replace(panel)
        with patch.object(partial_panels, "_MAX_OBSERVED_DYADS", 1):
            with self.assertRaisesRegex(ValueError, "dyad record limit"):
                PartialNetworkWave(0, "w0", (("alice", "bob"),), (("carol", "alice"),))

    def test_duplicate_json_keys_are_rejected_before_field_validation(self):
        raw = json.dumps(example())
        cases = (raw.replace('"origin": "synthetic"',
                             '"origin": "external_observation", "origin": "synthetic"', 1),
                 raw.replace('"observed_absent": [["carol", "alice"]]',
                             '"observed_absent": [], "observed_absent": [["carol", "alice"]]', 1))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "partial.json"
            for ambiguous in cases:
                path.write_text(ambiguous, encoding="utf-8")
                with self.subTest(duplicate=True), self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                    load_partial_panel(path)

    def test_bounded_json_read_invalid_encoding_and_nonfinite_constants(self):
        raw = json.dumps(example()).encode("utf-8")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "partial.json"
            path.write_bytes(raw)
            with patch.object(partial_panels, "_MAX_JSON_BYTES", len(raw)):
                self.assertEqual(load_partial_panel(path).to_dict(), example())
            with patch.object(partial_panels, "_MAX_JSON_BYTES", len(raw) - 1):
                with self.assertRaisesRegex(ValueError, "byte limit"):
                    load_partial_panel(path)
            for invalid in (b"\xff", raw.replace(b'"time_index": 0', b'"time_index": NaN', 1),
                            raw.replace(b'"time_index": 0', b'"time_index": Infinity', 1)):
                path.write_bytes(invalid)
                with self.subTest(invalid_encoding_or_number=True), self.assertRaises(ValueError):
                    load_partial_panel(path)


if __name__ == "__main__":
    unittest.main()
