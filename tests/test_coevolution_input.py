"""Declared ordinal scale and complete matrix admission without optional cusna."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.coevolution_input import (
    PROFILE, SCHEMA, CoevolutionSpec, load_coevolution_spec, validate_coevolution_input,
)
from sociolab.panels import LongitudinalPanel


def specification(**changes):
    values = {
        "behavior_variable": "declared_ordinal_measurement",
        "minimum": 1, "maximum": 3,
        "measurement_reference": "synthetic:instrument-v1",
        "research_question": "Do the declared network and ordinal measurements coevolve?",
    }
    values.update(changes)
    return CoevolutionSpec(**values)


def panel_mapping():
    return {
        "schema": "sociolab.longitudinal.v1", "dataset_id": "coevolution-input-fixture",
        "origin": "synthetic", "source_reference": None,
        "actors": ["actor-01", "actor-02", "actor-10"],
        "relation": "directed_observed_social_tie",
        "behavior_variable": "declared_ordinal_measurement",
        "waves": [
            {"time_index": 0, "source_revision": "wave-0", "network_complete": True,
             "edges": [["actor-01", "actor-02"]],
             "behavior": {"actor-10": 3, "actor-02": 2, "actor-01": 1}},
            {"time_index": 2, "source_revision": "wave-2", "network_complete": True,
             "edges": [["actor-02", "actor-10"]],
             "behavior": {"actor-10": 2, "actor-02": 1, "actor-01": 3}},
            {"time_index": 7, "source_revision": "wave-7", "network_complete": True,
             "edges": [["actor-10", "actor-01"]],
             "behavior": {"actor-10": 1, "actor-02": 3, "actor-01": 2}},
        ],
    }


class CoevolutionSpecTest(unittest.TestCase):
    def test_exact_schema_roundtrip_hash_and_immutable_public_values(self):
        spec = specification()
        original = spec.to_dict()
        self.assertEqual(set(original), {"schema", "profile", "behavior", "research_question"})
        self.assertEqual(original["schema"], SCHEMA)
        self.assertEqual(original["profile"], PROFILE)
        self.assertEqual(CoevolutionSpec.from_mapping(original), spec)
        self.assertRegex(spec.content_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(CoevolutionSpec.from_mapping(original).content_hash, spec.content_hash)
        changed = spec.to_dict()
        changed["behavior"]["minimum"] = 0
        changed["research_question"] = "different"
        self.assertEqual(spec.to_dict(), original)
        self.assertNotEqual(specification(research_question="A different declared question").content_hash, spec.content_hash)
        with self.assertRaises(FrozenInstanceError):
            spec.minimum = 0

    def test_direct_constructor_validates_text_profile_and_bounds(self):
        invalid = [
            {"behavior_variable": " "}, {"behavior_variable": " leading"},
            {"measurement_reference": None}, {"measurement_reference": "trailing "},
            {"research_question": []}, {"research_question": ""},
            {"measurement_reference": "invalid-\ud800"},
            {"profile": "unregistered"}, {"profile": []},
            {"minimum": True}, {"maximum": True}, {"minimum": 1.0},
            {"maximum": 3.0}, {"maximum": "3"}, {"minimum": -1},
            {"minimum": 3}, {"minimum": 4}, {"maximum": 2 ** 31},
            {"maximum": float("inf")}, {"minimum": float("nan")},
            {"maximum": 10 ** 1000},
        ]
        for changes in invalid:
            with self.subTest(fields=list(changes)), self.assertRaises(ValueError):
                specification(**changes)

    def test_mapping_rejects_undeclared_fields_and_malformed_shapes(self):
        original = specification().to_dict()
        invalid = [None, [], {**original, "schema": "sociolab.coevolution.v2"},
                   {**original, "schema": []}, {**original, "effects": ["anything"]}]
        for field in original:
            missing = deepcopy(original)
            del missing[field]
            invalid.append(missing)
        for behavior in (None, [], {}, {**original["behavior"], "rounding": "nearest"}):
            invalid.append({**original, "behavior": behavior})
        for value in invalid:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                CoevolutionSpec.from_mapping(value)

    def test_file_loader_rejects_duplicate_keys_at_each_level(self):
        encoded = json.dumps(specification().to_dict())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coevolution.json"
            path.write_text(encoded, encoding="utf-8")
            self.assertEqual(load_coevolution_spec(path), specification())
            ambiguous = [
                encoded.replace('"schema": ', '"schema": "other", "schema": ', 1),
                encoded.replace('"minimum": 1', '"minimum": 0, "minimum": 1', 1),
            ]
            for content in ambiguous:
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                    load_coevolution_spec(path)

    def test_measurement_reference_is_preserved_as_a_declaration(self):
        spec = specification(measurement_reference="instrument:survey-v3/item-7",
                             research_question="研究预先声明的测量")
        self.assertEqual(spec.to_dict()["behavior"]["measurement_reference"], "instrument:survey-v3/item-7")
        self.assertEqual(CoevolutionSpec.from_mapping(spec.to_dict()), spec)
        self.assertNotIn("source_claim_verified", spec.to_dict())


class CoevolutionInputTest(unittest.TestCase):
    def test_actor_and_all_wave_order_are_preserved_without_source_mutation(self):
        panel = LongitudinalPanel.from_mapping(panel_mapping())
        before = panel.to_dict()
        behavior = validate_coevolution_input(panel, specification())
        self.assertEqual(behavior.dtype, np.float64)
        self.assertEqual(behavior.shape, (3, 3))
        np.testing.assert_array_equal(behavior, [[1, 3, 2], [2, 1, 3], [3, 2, 1]])
        self.assertEqual([wave.time_index for wave in panel.waves], [0, 2, 7])
        behavior[0, 0] = 99
        self.assertEqual(panel.to_dict(), before)
        self.assertEqual(validate_coevolution_input(panel, specification())[0, 0], 1)

    def test_two_waves_and_more_waves_use_the_same_actor_by_wave_contract(self):
        mapping = panel_mapping()
        mapping["waves"] = mapping["waves"][:2]
        two_waves = validate_coevolution_input(LongitudinalPanel.from_mapping(mapping), specification())
        self.assertEqual(two_waves.shape, (3, 2))
        np.testing.assert_array_equal(two_waves, [[1, 3], [2, 1], [3, 2]])
        extra = deepcopy(mapping["waves"][-1])
        extra.update(time_index=10, source_revision="wave-10")
        mapping["waves"].append(extra)
        three_waves = validate_coevolution_input(LongitudinalPanel.from_mapping(mapping), specification())
        np.testing.assert_array_equal(three_waves[:, :2], two_waves)

    def test_missing_behavior_at_any_wave_is_rejected_without_imputation(self):
        for wave_index in range(3):
            mapping = panel_mapping()
            mapping["waves"][wave_index]["behavior"]["actor-02"] = None
            panel = LongitudinalPanel.from_mapping(mapping)
            with self.subTest(wave=wave_index), self.assertRaisesRegex(ValueError, "complete behavior"):
                validate_coevolution_input(panel, specification())
            self.assertIsNone(dict(panel.waves[wave_index].behavior)["actor-02"])

    def test_incomplete_network_is_rejected_even_with_complete_behavior(self):
        mapping = panel_mapping()
        mapping["waves"][1]["network_complete"] = False
        with self.assertRaisesRegex(ValueError, "complete network"):
            validate_coevolution_input(LongitudinalPanel.from_mapping(mapping), specification())

    def test_behavior_variable_must_match_the_explicit_specification(self):
        panel = LongitudinalPanel.from_mapping(panel_mapping())
        with self.assertRaisesRegex(ValueError, "variable must match"):
            validate_coevolution_input(panel, specification(behavior_variable="other_measurement"))

    def test_observed_endpoints_must_equal_declared_bounds_not_shrink_the_domain(self):
        panel = LongitudinalPanel.from_mapping(panel_mapping())
        for bounds in ((0, 3), (1, 4), (0, 4)):
            with self.subTest(bounds=bounds), self.assertRaisesRegex(ValueError, "extrema must equal"):
                validate_coevolution_input(panel, specification(minimum=bounds[0], maximum=bounds[1]))
        constant = panel_mapping()
        for wave in constant["waves"]:
            wave["behavior"] = {actor: 2 for actor in constant["actors"]}
        with self.assertRaisesRegex(ValueError, "extrema must equal"):
            validate_coevolution_input(LongitudinalPanel.from_mapping(constant), specification())

    def test_values_outside_declared_domain_fail_before_numeric_conversion(self):
        for value in (0, 4, 2 ** 31, 10 ** 1000):
            mapping = panel_mapping()
            mapping["waves"][1]["behavior"]["actor-02"] = value
            panel = LongitudinalPanel.from_mapping(mapping)
            with self.subTest(value_size=value.bit_length()), self.assertRaisesRegex(ValueError, "outside declared ordinal bounds"):
                validate_coevolution_input(panel, specification())

    def test_int32_endpoints_remain_exact_float64_input_without_overflow(self):
        high = int(np.iinfo(np.int32).max)
        mapping = panel_mapping()
        for index, wave in enumerate(mapping["waves"]):
            wave["behavior"] = {actor: high - ((row + index) % 2)
                                for row, actor in enumerate(mapping["actors"])}
        behavior = validate_coevolution_input(
            LongitudinalPanel.from_mapping(mapping), specification(minimum=high - 1, maximum=high),
        )
        self.assertEqual(behavior.min(), high - 1)
        self.assertEqual(behavior.max(), high)
        np.testing.assert_array_equal(behavior.astype(np.int64), [[high, high - 1, high],
                                                                [high - 1, high, high - 1],
                                                                [high, high - 1, high]])

    def test_future_observations_cannot_satisfy_bounds_for_a_separate_fit_prefix(self):
        mapping = panel_mapping()
        for wave in mapping["waves"][:2]:
            wave["behavior"] = {actor: min(value, 2) for actor, value in wave["behavior"].items()}
        full_panel = LongitudinalPanel.from_mapping(mapping)
        prefix = deepcopy(mapping)
        prefix["waves"] = prefix["waves"][:2]
        fit_panel = LongitudinalPanel.from_mapping(prefix)
        # A later observed category belongs to that separate panel, not this fit.
        self.assertEqual(validate_coevolution_input(full_panel, specification()).max(), 3)
        with self.assertRaisesRegex(ValueError, "extrema must equal"):
            validate_coevolution_input(fit_panel, specification())

    def test_unversioned_input_objects_are_rejected(self):
        panel = LongitudinalPanel.from_mapping(panel_mapping())
        with self.assertRaisesRegex(ValueError, "LongitudinalPanel"):
            validate_coevolution_input(panel.to_dict(), specification())
        with self.assertRaisesRegex(ValueError, "CoevolutionSpec"):
            validate_coevolution_input(panel, specification().to_dict())


if __name__ == "__main__":
    unittest.main()
