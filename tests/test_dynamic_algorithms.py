"""Native contracts exercised against the actual pinned NetworkX algorithms."""

from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

import networkx as nx
from networkx.algorithms import bipartite

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sociolab.affiliations import affiliation_report
from sociolab.communities import community_report, compare_communities
from sociolab.keyplayers import score_key_group, select_key_group


def bridge_graph():
    graph = nx.Graph()
    graph.add_nodes_from("ABCDEF")
    graph.add_edges_from([
        ("A", "B"), ("A", "C"), ("B", "C"),
        ("C", "D"), ("D", "E"), ("D", "F"), ("E", "F"),
    ])
    return graph


def event_graph():
    graph = nx.Graph()
    graph.add_nodes_from("ABCDEFG", bipartite=0)
    graph.add_nodes_from(["event:all", "event:empty"], bipartite=1)
    graph.nodes["event:all"]["evidence"] = ["activity-record"]
    for actor in "ABCDEF":
        graph.add_edge(actor, "event:all", evidence=[f"attendance:{actor}"])
    return graph


class DynamicCommunityTest(unittest.TestCase):
    def test_actual_weighted_directed_and_undirected_upstream(self):
        for directed in (False, True):
            graph = nx.DiGraph() if directed else nx.Graph()
            graph.add_nodes_from("ABCDE")
            graph.add_weighted_edges_from([
                ("A", "B", 3), ("B", "A", 3), ("B", "C", 0.1),
                ("C", "D", 3), ("D", "C", 3),
            ], weight="strength")
            for method in ("louvain", "greedy"):
                with self.subTest(directed=directed, method=method):
                    report = community_report(graph, algorithm=method, seed=42)
                    if method == "louvain":
                        expected = nx.community.louvain_communities(
                            graph, weight="strength", resolution=1, seed=42,
                        )
                    else:
                        expected = nx.community.greedy_modularity_communities(
                            graph, weight="strength", resolution=1,
                        )
                    self.assertEqual(
                        {frozenset(c) for c in report["communities"]},
                        {frozenset(c) for c in expected},
                    )
                    self.assertAlmostEqual(
                        report["modularity"],
                        nx.community.modularity(graph, expected, weight="strength"),
                    )
                    self.assertEqual(report["isolates"], ["E"])
                    self.assertEqual(report["directed"], directed)
                    json.dumps(report, allow_nan=False)

    def test_canonical_input_order_and_no_caller_mutation(self):
        first = bridge_graph()
        second = nx.Graph()
        second.add_nodes_from(reversed(list(first)))
        second.add_edges_from(reversed(list(first.edges())))
        original_nodes, original_edges = list(second), list(second.edges())
        self.assertEqual(community_report(first), community_report(second))
        self.assertEqual(original_nodes, list(second))
        self.assertEqual(original_edges, list(second.edges()))

    def test_empty_and_no_edge_status_preserves_isolates(self):
        empty = community_report(nx.Graph())
        self.assertEqual(empty["status"], "EMPTY_GRAPH")
        self.assertEqual(empty["communities"], [])
        self.assertIsNone(empty["modularity"])
        graph = nx.Graph()
        graph.add_nodes_from(["B", "A"])
        report = community_report(graph)
        self.assertEqual(report["status"], "NO_EDGES")
        self.assertEqual(report["communities"], [["A"], ["B"]])
        self.assertEqual(report["isolates"], ["A", "B"])
        self.assertIsNone(report["modularity"])

    def test_signed_nonfinite_and_unsupported_inputs_fail(self):
        for value in (-1, 0, float("nan"), float("inf"), True, "1"):
            graph = nx.Graph()
            graph.add_edge("A", "B", strength=value)
            with self.subTest(weight=value), self.assertRaises(ValueError):
                community_report(graph)
        for graph in (nx.MultiGraph([("A", "B")]), nx.Graph([("A", "A")]),
                      nx.Graph([("A", 1)]), nx.Graph([("", "B")])):
            with self.subTest(graph=graph), self.assertRaises(ValueError):
                community_report(graph)
        for settings in ({"resolution": 0}, {"resolution": True}, {"seed": True},
                         {"algorithm": "signed"}, {"weight": ""}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                community_report(bridge_graph(), **settings)


class CommunityLineageTest(unittest.TestCase):
    def test_label_only_change_has_full_stability_and_same_ids(self):
        result = compare_communities(
            {"old-one": ["B", "A"], "old-two": ["D", "C"]},
            {"renamed-two": ["C", "D"], "renamed-one": ["A", "B"]},
        )
        self.assertEqual(result["membership_stability"], {
            "same_partition": True, "matched_member_fraction": 1.0,
        })
        self.assertEqual(result["before_communities"], result["after_communities"])
        self.assertEqual(result["entered"], [])
        self.assertEqual(len(result["lineage"]), 2)

    def test_split_merge_keep_all_links_and_population_changes(self):
        before = [list("ABCD"), list("EF")]
        after = [list("AB"), list("CD"), list("EFG")]
        with patch("networkx.max_weight_matching", wraps=nx.max_weight_matching) as upstream:
            split = compare_communities(before, after)
            upstream.assert_called_once()
        self.assertEqual(split["entered"], ["G"])
        self.assertEqual(split["left"], [])
        self.assertEqual(len(split["lineage"]), 3)
        self.assertEqual(len(split["matches"]), 2)
        self.assertEqual(sum("split" in link["events"] for link in split["lineage"]), 2)
        self.assertFalse(split["membership_stability"]["same_partition"])
        self.assertAlmostEqual(split["membership_stability"]["matched_member_fraction"], 2 / 3)
        self.assertTrue(split["matching_ambiguity"]["equal_weight_candidates"])
        self.assertFalse(split["matching_ambiguity"]["unique_optimum_assessed"])
        merged = compare_communities(after, before)
        self.assertEqual(merged["left"], ["G"])
        self.assertEqual(sum("merge" in link["events"] for link in merged["lineage"]), 2)

    def test_observation_subset_and_noncomparison(self):
        result = compare_communities(
            [list("ABCD"), list("EF")], [list("AB"), list("CD"), list("EFG")],
            observable=list("ABEF"),
        )
        self.assertTrue(result["membership_stability"]["same_partition"])
        self.assertEqual(result["unobserved_common"], ["C", "D"])
        self.assertEqual(result["entered"], ["G"])
        none = compare_communities([["A"]], [["B"]])
        self.assertEqual(none["status"], "NO_COMMON_OBSERVABLE")
        self.assertIsNone(none["membership_stability"]["same_partition"])
        self.assertIsNone(none["membership_stability"]["matched_member_fraction"])
        self.assertEqual(none["lineage"], [])

    def test_invalid_partitions_and_unknown_observation_are_rejected(self):
        for bad in ([["A"], ["A"]], [["A", "A"]], [[], ["A"]], [["A", 1]], "A"):
            with self.subTest(partition=bad), self.assertRaises(ValueError):
                compare_communities(bad, [["A"]])
        with self.assertRaises(ValueError):
            compare_communities([["A"]], [["A"]], observable=["unknown"])


class GenericGroupTest(unittest.TestCase):
    def test_real_upstream_selection_and_rescore(self):
        graph = bridge_graph()
        expected_score, expected_members = nx.prominent_group(
            graph, 2, greedy=True, normalized=True, weight=None, endpoints=False,
        )
        report = select_key_group(graph, 2)
        self.assertEqual(report["members"], sorted(expected_members))
        self.assertEqual(report["selection_score_rounded"], expected_score)
        self.assertAlmostEqual(report["score"], nx.group_betweenness_centrality(
            graph, expected_members, normalized=True, weight=None, endpoints=False,
        ))
        self.assertFalse(report["global_optimum_claim"])
        self.assertAlmostEqual(report["score"], 2 / 3)

    def test_reproduced_exclusion_bug_has_explicit_scope_rejection(self):
        # In NetworkX 3.7 this actual graph with C=['C'] produced selection
        # score 1.0 for ['E', 'F'], whose measured group betweenness is 0.0.
        # The restriction does not depend on process-specific set iteration.
        with patch("networkx.prominent_group", wraps=nx.prominent_group) as upstream:
            with self.assertRaisesRegex(ValueError, "exclusion-related selection-score inconsistency"):
                select_key_group(bridge_graph(), 2, excluded=["C"])
            upstream.assert_not_called()

    def test_directed_and_disconnected_candidate_scores_use_upstream(self):
        directed = nx.DiGraph([("A", "B"), ("B", "C"), ("C", "D")])
        disconnected = bridge_graph()
        disconnected.remove_edge("C", "D")
        for graph, members in ((directed, ["B"]), (disconnected, ["C", "D"])):
            with self.subTest(directed=graph.is_directed()):
                report = score_key_group(graph, members)
                self.assertAlmostEqual(report["score"], nx.group_betweenness_centrality(
                    graph, members, normalized=True, weight=None, endpoints=False,
                ))
                with self.assertRaises(ValueError):
                    select_key_group(graph, 1)

    def test_group_scope_budgets_and_missing_members(self):
        graph = bridge_graph()
        for kwargs in ({"group_size": True}, {"group_size": 0}, {"group_size": 5},
                       {"max_nodes": 5}, {"max_edges": 6}, {"excluded": list("ABCDE")},
                       {"excluded": ["missing"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                select_key_group(graph, **kwargs)
        for members in ([], ["A", "A"], ["A", "missing"], list("ABCDE")):
            with self.subTest(members=members), self.assertRaises(ValueError):
                score_key_group(graph, members)
        for key in ("strength", "weight", "distance"):
            weighted = graph.copy()
            weighted["A"]["B"][key] = 2
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_key_group(weighted)
            with self.subTest(scoring_key=key), self.assertRaises(ValueError):
                score_key_group(weighted, ["C", "D"])


class GenericAffiliationTest(unittest.TestCase):
    def test_six_person_event_provenance_and_isolates(self):
        graph = event_graph()
        for method, function in (
            ("count", bipartite.weighted_projected_graph),
            ("newman", bipartite.collaboration_weighted_projected_graph),
        ):
            with self.subTest(projection=method):
                report = affiliation_report(graph, list("ABCDEFG"), projection=method)
                expected = function(graph, list("ABCDEFG"))
                self.assertEqual(report["incidence_count"], 6)
                self.assertEqual(report["projected_edge_count"], 15)
                self.assertEqual(report["person_isolates"], ["G"])
                self.assertEqual(report["projected_isolates"], ["G"])
                for edge in report["projected_edges"]:
                    self.assertAlmostEqual(edge["strength"], expected[edge["source"]][edge["target"]]["weight"])
                    self.assertEqual(edge["activities"], ["event:all"])
                ab = report["projected_edges"][0]
                self.assertEqual((ab["source"], ab["target"]), ("A", "B"))
                self.assertEqual(ab["evidence"], ["activity-record", "attendance:A", "attendance:B"])
                self.assertEqual(ab["strength"], 1 if method == "count" else 0.2)
                json.dumps(report, allow_nan=False)

    def test_no_projection_and_preallocation_budget(self):
        graph = event_graph()
        with patch("networkx.algorithms.bipartite.weighted_projected_graph", wraps=bipartite.weighted_projected_graph) as project:
            original = affiliation_report(graph, list("ABCDEFG"), max_pairs=0)
            self.assertEqual(original["projection_status"], "NOT_REQUESTED")
            self.assertEqual(original["incidence_count"], 6)
            self.assertEqual(original["projected_edges"], [])
            self.assertIsNone(original["projected_edge_count"])
            with self.assertRaises(ValueError):
                affiliation_report(graph, list("ABCDEFG"), projection="count", max_pairs=14)
            project.assert_not_called()
        self.assertEqual(
            affiliation_report(graph, list("ABCDEFG"), projection="count", max_pairs=15)["projected_edge_count"], 15,
        )

    def test_partition_direction_intensity_and_evidence_scope(self):
        original = event_graph()
        invalid = [nx.DiGraph(original), nx.MultiGraph(original)]
        same_side = original.copy()
        same_side.add_edge("A", "B")
        invalid.append(same_side)
        weighted = original.copy()
        weighted["A"]["event:all"]["weight"] = 5
        invalid.append(weighted)
        wrong_evidence = original.copy()
        wrong_evidence["A"]["event:all"]["evidence"] = "raw body"
        invalid.append(wrong_evidence)
        for graph in invalid:
            with self.subTest(graph=graph), self.assertRaises(ValueError):
                affiliation_report(graph, list("ABCDEFG"), projection="count")
        with self.assertRaises(ValueError):
            affiliation_report(original, ["not-present"])
        with self.assertRaises(ValueError):
            affiliation_report(original, ["A", "A"])


if __name__ == "__main__":
    unittest.main()
