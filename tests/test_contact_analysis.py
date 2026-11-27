"""Native recorded-contact analysis checks using the genuine NetworkX adapters."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab import contact_analysis
from sociolab.communities import community_report
from sociolab.keyplayers import score_key_group, select_key_group


ACTORS = (1, 2, 3, 4, 5, 6)


def fixture():
    records = [
        (20, 1, 2), (40, 1, 2), (60, 1, 2),
        (20, 1, 3), (40, 1, 3), (60, 1, 3),
        (20, 2, 3), (40, 2, 3), (60, 2, 3),
        (100, 4, 5), (36000, 3, 4),
        (36020, 5, 6), (43200, 4, 6),
        (86400, 2, 6),
        (86420, 1, 2), (86440, 1, 2), (86460, 1, 2),
        (86500, 1, 3), (86520, 2, 3),
        (86600, 3, 6), (86620, 3, 6), (86640, 3, 6),
        (122400, 5, 6), (122420, 4, 6), (129600, 1, 6),
        (129620, 2, 5),
    ]
    return tuple(sorted(records))


def graph_for(records, start, end, minimum_bins=1):
    counts = Counter((a, b) for t, a, b in records if start < t <= end)
    graph = nx.Graph()
    graph.add_nodes_from(ACTORS)
    graph.add_edges_from(pair for pair, count in counts.items() if count >= minimum_bins)
    return graph, counts


class RecordedContactAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = fixture()
        cls.report = contact_analysis.recorded_contact_analysis(ACTORS, cls.records)

    def test_endpoint_windows_and_nonconsecutive_bin_threshold(self):
        main, threshold, extended = self.report["scenarios"]
        self.assertEqual([w["window_bin_count"] for w in main["windows"]], [11, 9])
        self.assertEqual([w["window_bin_count"] for w in extended["windows"]], [13, 11])
        self.assertEqual([w["structure"]["binary_pair_count"] for w in main["windows"]], [5, 5])
        self.assertEqual([w["structure"]["binary_pair_count"] for w in threshold["windows"]], [3, 2])
        self.assertEqual([w["qualifying_pair_bin_count"] for w in threshold["windows"]], [9, 6])
        self.assertEqual([w["excluded_below_threshold_bin_count"] for w in threshold["windows"]], [2, 3])
        self.assertEqual(self.report["settings"]["window_rule"], "start < recorded_bin_endpoint <= end")
        noncontinuous = ((20, 1, 2), (100, 1, 2), (300, 1, 2))
        result = contact_analysis.recorded_contact_analysis(ACTORS, noncontinuous)
        self.assertEqual(result["scenarios"][1]["windows"][0]["structure"]["binary_pair_count"], 1)

    def test_fixed_universe_keeps_zero_record_and_threshold_isolates_distinct(self):
        for scenario in self.report["scenarios"]:
            self.assertEqual([w["structure"]["actor_count"] for w in scenario["windows"]], [6, 6])
            self.assertEqual(scenario["community_comparison"]["compared_actor_count"], 6)
        main, threshold, _ = self.report["scenarios"]
        self.assertEqual(main["windows"][0]["zero_record_node_count"], 1)
        self.assertEqual(main["windows"][0]["structure"]["zero_qualifying_degree_node_count"], 1)
        self.assertEqual(threshold["windows"][0]["zero_record_node_count"], 1)
        self.assertEqual(threshold["windows"][0]["structure"]["zero_qualifying_degree_node_count"], 3)
        structure = main["windows"][0]["structure"]
        self.assertEqual(structure["component_sizes"], [5, 1])
        self.assertEqual(structure["reachable_unordered_pairs"], 10)
        self.assertAlmostEqual(structure["reachable_unordered_pair_fraction"], 10 / 15)
        self.assertAlmostEqual(structure["mean_other_nodes_structurally_reachable"], 20 / 6)
        self.assertEqual(structure["bridge_count"], 2)

    def test_same_primary_partition_defines_cross_groups_in_all_scenarios(self):
        primary, _ = graph_for(self.records, 0, 36000)
        detected = community_report(primary, algorithm="louvain", seed=0, resolution=1, weight=None)
        membership = {actor: i for i, group in enumerate(detected["communities"]) for actor in group}
        baseline_zero = set(nx.isolates(primary))
        expected_hash = "sha256:" + sha256(json.dumps(detected["communities"], separators=(",", ":")).encode()).hexdigest()
        for scenario in self.report["scenarios"]:
            self.assertEqual(scenario["fixed_primary_baseline_partition_hash"], expected_hash)
            for window in scenario["windows"]:
                graph, counts = graph_for(self.records, window["start_exclusive"], window["end_inclusive"], scenario["minimum_bins_per_pair"])
                cross = [(a, b) for a, b in graph.edges if membership[a] != membership[b]]
                touching = [(a, b) for a, b in cross if a in baseline_zero or b in baseline_zero]
                actual = window["fixed_primary_baseline_cross_groups"]
                self.assertEqual(actual["pair_counts"]["cross_primary_baseline_community"], len(cross))
                self.assertEqual(actual["pair_counts"]["cross_touching_primary_baseline_zero_record_nodes"], len(touching))
                self.assertEqual(actual["bin_counts"]["cross_primary_baseline_community"], sum(counts[tuple(sorted(pair))] for pair in cross))
        gained = self.report["scenarios"][0]["pair_changes"]["recorded_pair_gained"]
        self.assertEqual(gained["total"], 2)
        self.assertEqual(gained["cross_touching_primary_baseline_zero_record_nodes"], 2)

    def test_archive_group_selected_once_and_rescored_without_replacement(self):
        with patch.object(contact_analysis, "select_key_group", wraps=select_key_group) as select:
            with patch.object(contact_analysis, "score_key_group", wraps=score_key_group) as score:
                report = contact_analysis.recorded_contact_analysis(ACTORS, self.records)
        self.assertEqual(select.call_count, 1)
        self.assertEqual(score.call_count, 6)
        self.assertEqual(report["reference_group"]["selection_decision_count"], 1)
        self.assertEqual(report["reference_group"]["upstream_selection_call_count"], 1)
        self.assertTrue(report["reference_group"]["selected_once"])
        archive = nx.Graph()
        archive.add_nodes_from(ACTORS)
        archive.add_edges_from((a, b) for _, a, b in self.records)
        original = select_key_group(archive, 2, max_nodes=200, max_edges=3000)
        expected_hash = "sha256:" + sha256(json.dumps(original["members"], separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(report["reference_group"]["identity_hash"], expected_hash)
        self.assertTrue(report["reference_group"]["hindsight"])
        self.assertFalse(report["reference_group"]["baseline_optimal_claim"])
        for scenario in report["scenarios"]:
            for window in scenario["windows"]:
                graph, _ = graph_for(self.records, window["start_exclusive"], window["end_inclusive"], scenario["minimum_bins_per_pair"])
                expected = score_key_group(graph, original["members"])
                self.assertEqual(window["fixed_reference_group"]["identity_hash"], expected_hash)
                self.assertAlmostEqual(window["fixed_reference_group"]["score"], expected["score"])

    def test_unsupported_archive_selection_is_not_hidden_by_dropping_nodes(self):
        result = contact_analysis.recorded_contact_analysis(ACTORS, ((20, 1, 2), (40, 2, 3)))
        self.assertEqual(result["reference_group"]["status"], "NOT_RUN")
        self.assertEqual(result["reference_group"]["reason"], "full_archive_graph_is_disconnected")
        self.assertEqual(result["reference_group"]["selection_decision_count"], 1)
        self.assertEqual(result["reference_group"]["upstream_selection_call_count"], 0)
        self.assertFalse(result["reference_group"]["selected_once"])
        self.assertEqual(result["full_archive"]["actor_count"], 6)
        for scenario in result["scenarios"]:
            for window in scenario["windows"]:
                self.assertEqual(window["structure"]["actor_count"], 6)
                self.assertEqual(window["fixed_reference_group"]["status"], "NOT_RUN")
        empty = contact_analysis.recorded_contact_analysis(ACTORS, ())
        self.assertEqual(empty["scenarios"][0]["windows"][0]["structure"]["component_sizes"], [1] * 6)
        self.assertEqual(empty["scenarios"][0]["community_comparison"]["matched_member_fraction"], 1)

    def test_output_is_aggregate_and_claims_remain_scoped(self):
        forbidden = {"actors", "persons", "members", "edges", "node_order", "edge_order", "isolates"}
        def check(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value))
                for child in value.values(): check(child)
            elif isinstance(value, list):
                for child in value: check(child)
        check(self.report)
        json.dumps(self.report, allow_nan=False)
        self.assertFalse(self.report["scope"]["sensor_coverage_verified"])
        self.assertIsNone(self.report["scope"]["physical_contact_observation_complete"])
        self.assertFalse(self.report["scope"]["time_respecting_transmission_validated"])
        self.assertFalse(self.report["scope"]["causal_effect_identified"])
        self.assertFalse(self.report["scope"]["row_level_records_exported"])
        self.assertEqual(sum(sum(row) for row in self.report["scenarios"][0]["community_comparison"]["overlap_counts"]), len(ACTORS))

    def test_analysis_boundary_rejects_malformed_records(self):
        cases = [((20, 2, 1),), ((20, 1, 1),), ((20, 1, 7),),
                 ((0, 1, 2),), ((21, 1, 2),), ((40, 1, 2), (20, 1, 2)),
                 ((20, 1, 2), (20, 1, 2)), ((True, 1, 2),)]
        for records in cases:
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    contact_analysis.recorded_contact_analysis(ACTORS, records)
        with self.assertRaises(ValueError):
            contact_analysis.recorded_contact_analysis((1, 1, 2), ())
        with self.assertRaises(ValueError):
            contact_analysis.recorded_contact_analysis(ACTORS, [])


if __name__ == "__main__":
    unittest.main()
