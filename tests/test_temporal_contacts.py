"""Small temporal-order examples executed by the original NetworkX engine."""

from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab import temporal_contacts


def fingerprint(value):
    return "sha256:" + sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def analyze(records, *, actors=(1, 2, 3), start=0, end=100, minimum_bins=1, deadlines=()):
    return temporal_contacts.temporal_contact_report(
        actors, records, start=start, end=end, minimum_bins=minimum_bins, deadlines_seconds=deadlines)


class TemporalContactTests(unittest.TestCase):
    def test_chronological_chain_has_direction_and_endpoint_arrivals(self):
        report = analyze(((20, 1, 2), (40, 2, 3)), end=40, deadlines=(0, 20, 40))
        self.assertEqual(report["possible_ordered_pairs"], 6)
        self.assertEqual(report["static"]["reachable_ordered_pairs"], 6)
        expected_pairs = [(1, 2), (1, 3), (2, 1), (2, 3), (3, 2)]
        expected_arrivals = [(1, 2, 20), (1, 3, 40), (2, 1, 20), (2, 3, 40), (3, 2, 40)]
        for name in ("strict", "nonstrict"):
            mode = report[name]
            self.assertEqual(mode["reachable_ordered_pairs"], 5)
            self.assertAlmostEqual(mode["reachable_ordered_pair_fraction"], 5 / 6)
            self.assertEqual(mode["reachable_pair_identity_hash"], fingerprint(expected_pairs))
            self.assertEqual(mode["arrival_identity_hash"], fingerprint(expected_arrivals))
            self.assertEqual(mode["mutually_reachable_unordered_pairs"], 2)
            self.assertEqual(mode["one_way_reachable_unordered_pairs"], 1)
            self.assertEqual(mode["unreachable_in_both_directions_unordered_pairs"], 0)
            self.assertEqual(mode["static_reachable_but_not_temporal_ordered_pairs"], 1)
            self.assertEqual(mode["earliest_bin_endpoint_offset_seconds"],
                             {"reachable_pair_count": 5, "min": 20, "median": 40, "mean": 32.0, "max": 40})
            self.assertEqual([d["reachable_ordered_pairs"] for d in mode["deadlines"]], [0, 2, 5])

    def test_reversing_bin_order_changes_direction_without_changing_static_graph(self):
        forward = analyze(((20, 1, 2), (40, 2, 3)))
        reverse = analyze(((20, 2, 3), (40, 1, 2)))
        self.assertEqual(forward["static"], reverse["static"])
        expected = [(1, 2), (2, 1), (2, 3), (3, 1), (3, 2)]
        self.assertEqual(reverse["strict"]["reachable_pair_identity_hash"], fingerprint(expected))
        self.assertNotEqual(forward["strict"]["reachable_pair_identity_hash"],
                            reverse["strict"]["reachable_pair_identity_hash"])

    def test_simultaneous_chain_distinguishes_rules_and_ignores_row_order(self):
        records = ((20, 1, 2), (20, 2, 3))
        report = analyze(records)
        self.assertEqual(report, analyze(tuple(reversed(records))))
        self.assertEqual(report["strict"]["reachable_ordered_pairs"], 4)
        self.assertEqual(report["nonstrict"]["reachable_ordered_pairs"], 6)
        self.assertEqual(report["comparison"]["same_bin_rule_additional_reachable_ordered_pairs"], 2)
        self.assertEqual(report["strict"]["expanded_graph"], {"node_count": 12, "edge_count": 13})
        self.assertEqual(report["nonstrict"]["expanded_graph"], {"node_count": 12, "edge_count": 16})
        self.assertEqual(report["strict"]["earliest_bin_endpoint_offset_seconds"]["max"], 20)

    def test_repeated_contact_in_a_later_bin_permits_waiting_and_changes_arrival(self):
        report = analyze(((20, 1, 2), (20, 2, 3), (40, 2, 3)), deadlines=(20, 40))
        self.assertEqual(report["strict"]["reachable_ordered_pairs"], 5)
        self.assertEqual(report["nonstrict"]["reachable_ordered_pairs"], 6)
        self.assertEqual(report["strict"]["earliest_bin_endpoint_offset_seconds"]["max"], 40)
        self.assertEqual(report["nonstrict"]["earliest_bin_endpoint_offset_seconds"]["max"], 20)
        self.assertEqual(report["comparison"]["common_pairs_arrive_earlier_with_nonstrict"], 1)
        self.assertEqual(report["comparison"]["common_pairs_same_arrival"], 4)
        self.assertEqual([d["reachable_ordered_pairs"] for d in report["strict"]["deadlines"]], [4, 5])

    def test_long_record_gap_is_waiting_not_bfs_hop_time(self):
        report = analyze(((20, 1, 2), (1000, 2, 3)), end=1000, deadlines=(20, 999, 1000))
        self.assertEqual(report["strict"]["earliest_bin_endpoint_offset_seconds"]["max"], 1000)
        self.assertEqual([d["reachable_ordered_pairs"] for d in report["strict"]["deadlines"]], [2, 2, 5])
        self.assertEqual(report["strict"]["expanded_graph"], {"node_count": 14, "edge_count": 15})

    def test_empty_window_retains_all_nodes_and_has_no_arrival_statistics(self):
        report = analyze(((20, 1, 2),), actors=(1, 2, 3, 4), start=40, end=100, deadlines=(0, 60))
        self.assertEqual(report["actor_count"], 4)
        self.assertEqual(report["possible_ordered_pairs"], 12)
        self.assertEqual(report["window"]["zero_record_node_count"], 4)
        self.assertEqual(report["window"]["qualifying_pair_bin_count"], 0)
        for name in ("strict", "nonstrict"):
            self.assertEqual(report[name]["reachable_ordered_pairs"], 0)
            self.assertEqual(report[name]["reachable_ordered_pair_fraction"], 0.0)
            self.assertEqual(report[name]["expanded_graph"], {"node_count": 8, "edge_count": 4})
            self.assertEqual(report[name]["unreachable_in_both_directions_unordered_pairs"], 6)
            self.assertEqual(report[name]["earliest_bin_endpoint_offset_seconds"],
                             {"reachable_pair_count": 0, "min": None, "median": None, "mean": None, "max": None})
        json.dumps(report, allow_nan=False)

    def test_self_is_excluded_and_targets_are_counted_once_across_states(self):
        report = analyze(((20, 1, 2), (40, 1, 2), (60, 1, 2)))
        self.assertEqual(report["possible_ordered_pairs"], 6)
        self.assertEqual(report["window"]["zero_record_node_count"], 1)
        for name in ("strict", "nonstrict"):
            self.assertEqual(report[name]["reachable_ordered_pairs"], 2)
            self.assertEqual(report[name]["earliest_bin_endpoint_offset_seconds"]["reachable_pair_count"], 2)
            self.assertEqual(report[name]["arrival_identity_hash"], fingerprint([(1, 2, 20), (2, 1, 20)]))
        singleton = analyze((), actors=(7,), end=20, deadlines=(20,))
        self.assertEqual(singleton["possible_ordered_pairs"], 0)
        self.assertIsNone(singleton["strict"]["reachable_ordered_pair_fraction"])
        self.assertIsNone(singleton["strict"]["deadlines"][0]["reachable_ordered_pair_fraction"])

    def test_window_endpoints_and_offset_summaries_preserve_absolute_hash_labels(self):
        records = ((20, 1, 2), (40, 2, 3), (60, 1, 3), (80, 1, 2))
        report = analyze(records, start=20, end=60, deadlines=(20, 40))
        self.assertEqual(report["window"]["window_bin_count"], 2)
        expected = [(1, 3, 60), (2, 1, 60), (2, 3, 40), (3, 1, 60), (3, 2, 40)]
        self.assertEqual(report["strict"]["arrival_identity_hash"], fingerprint(expected))
        self.assertEqual(report["strict"]["earliest_bin_endpoint_offset_seconds"]["min"], 20)
        self.assertEqual(report["strict"]["earliest_bin_endpoint_offset_seconds"]["max"], 40)
        self.assertEqual([d["reachable_ordered_pairs"] for d in report["strict"]["deadlines"]], [2, 5])

    def test_three_bin_filter_is_retrospective_and_retains_early_qualifying_records(self):
        records = ((20, 1, 2), (40, 2, 3), (60, 1, 2), (80, 1, 2))
        report = analyze(records, minimum_bins=3, deadlines=(20, 80))
        window = report["window"]
        self.assertEqual(window["window_bin_count"], 4)
        self.assertEqual(window["window_recorded_pair_count"], 2)
        self.assertEqual(window["qualifying_pair_bin_count"], 3)
        self.assertEqual(window["qualifying_recorded_pair_count"], 1)
        self.assertEqual(window["zero_record_node_count"], 0)
        self.assertEqual(window["zero_qualifying_degree_node_count"], 1)
        self.assertEqual(window["excluded_below_threshold_pair_count"], 1)
        self.assertEqual(window["excluded_below_threshold_bin_count"], 1)
        self.assertEqual(report["strict"]["earliest_bin_endpoint_offset_seconds"]["max"], 20)
        self.assertEqual(report["strict"]["deadlines"][0]["reachable_ordered_pairs"], 2)
        self.assertTrue(report["scope"]["retrospective_pair_filtering"])
        self.assertTrue(report["scope"]["pair_filter_uses_later_window_records"])

    def test_actual_networkx_reachability_is_called_for_each_source_and_rule(self):
        original = nx.single_source_shortest_path_length
        with patch.object(nx, "single_source_shortest_path_length", wraps=original) as calls:
            report = analyze(((20, 1, 2), (20, 2, 3)))
        self.assertEqual(calls.call_count, 6)
        self.assertTrue(all(isinstance(call.args[0], nx.DiGraph) for call in calls.call_args_list))
        self.assertEqual(report["engine"], "networkx")
        self.assertEqual(report["strict"]["reachable_ordered_pairs"], 4)
        self.assertEqual(report["nonstrict"]["reachable_ordered_pairs"], 6)

    def test_expansion_budgets_fail_before_any_graph_is_allocated(self):
        records = ((20, 1, 2),)
        for setting, limit in (("_MAX_EXPANDED_NODES", 9), ("_MAX_EXPANDED_EDGES", 10)):
            # This fixture has 10 states, 9 strict edges, and 11 non-strict
            # edges: the second budget must account for both rules upfront.
            with self.subTest(setting=setting), patch.object(temporal_contacts, setting, limit):
                with patch.object(nx, "Graph", side_effect=AssertionError("graph allocated")):
                    with patch.object(nx, "DiGraph", side_effect=AssertionError("graph allocated")):
                        with self.assertRaisesRegex(ValueError, "expansion exceeds"):
                            analyze(records)
        with self.assertRaisesRegex(ValueError, "actor budget"):
            analyze((), actors=tuple(range(201)))
        with self.assertRaisesRegex(ValueError, "total input record budget"):
            analyze(((20, 1, 2),) * 50_001, start=40, end=100)

    def test_invalid_observations_are_rejected_without_correction(self):
        invalid = [
            [(20, 1, 2)], ((20, 1, 2), (20, 1, 2)), ((40, 1, 2), (20, 2, 3)),
            ((0, 1, 2),), ((21, 1, 2),), ((20, 2, 1),), ((20, 1, 1),),
            ((20, 1, 4),), ((20, True, 2),), ((20.0, 1, 2),),
        ]
        for records in invalid:
            with self.subTest(records=records), self.assertRaises(ValueError):
                analyze(records)
        for actors in ((), (1, 1, 2), (2, 1, 3), [1, 2, 3], (True, 2, 3)):
            with self.subTest(actors=actors), self.assertRaises(ValueError):
                analyze((), actors=actors)

    def test_invalid_windows_thresholds_and_deadlines_are_rejected(self):
        for start, end in ((-20, 40), (0, 0), (40, 20), (1, 40), (0, 41), (0, 40.0), (False, 40)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                analyze((), start=start, end=end)
        for value in (0, -1, 1.0, True, "1", None):
            with self.subTest(minimum_bins=value), self.assertRaises(ValueError):
                analyze((), minimum_bins=value)
        for deadlines in ([20], (-1,), (101,), (20, 20), (40, 20), (True,), (20.0,)):
            with self.subTest(deadlines=deadlines), self.assertRaises(ValueError):
                analyze((), deadlines=deadlines)

    def test_exported_data_are_aggregate_and_keep_model_limits_explicit(self):
        report = analyze(((20, 1, 2), (20, 2, 3)))
        forbidden = {"actors", "records", "pairs", "members", "states", "nodes", "edges",
                     "arrival_by_pair", "reachable_by_source"}
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        inspect(report)
        for key in ("physical_transmission_bounds_established", "actual_transmission_observed",
                    "time_respecting_transmission_validated", "continuous_transmission_delay_measured",
                    "causal_effect_identified", "forecast_validated", "expanded_states_exported"):
            self.assertFalse(report["scope"][key])
        for key in ("strict_subset_of_nonstrict", "nonstrict_subset_of_static",
                    "common_pair_nonstrict_arrival_no_later_than_strict"):
            self.assertTrue(report["comparison"][key])
        self.assertEqual(report["actor_universe_hash"], fingerprint((1, 2, 3)))
        self.assertFalse(report["scope"]["pair_filter_uses_later_window_records"])
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
