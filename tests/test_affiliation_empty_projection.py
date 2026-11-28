"""Exact affiliation projection boundaries and nonempty upstream regression."""
import unittest

import networkx as nx

from sociolab.affiliations import affiliation_report, davis_affiliation_report


class EmptyActivityProjectionTests(unittest.TestCase):
    def test_people_only_projection_retains_all_isolates(self):
        graph = nx.Graph()
        graph.add_nodes_from(("A", "B", "C"), bipartite=0)
        for policy in ("count", "newman"):
            with self.subTest(policy=policy):
                result = affiliation_report(graph, ["C", "A", "B"],
                    projection=policy, max_pairs=0)
                self.assertEqual(result["persons"], ["A", "B", "C"])
                self.assertEqual(result["activities"], [])
                self.assertEqual(result["incidence_count"], 0)
                self.assertEqual(result["projected_edge_count"], 0)
                self.assertEqual(result["projected_edges"], [])
                self.assertEqual(result["projected_isolates"], ["A", "B", "C"])
                self.assertEqual(result["person_isolates"], ["A", "B", "C"])
                self.assertEqual(result["projection_status"], "OK")
                self.assertEqual(result["algorithm"], "networkx.empty_graph")
                self.assertEqual(result["settings"]["pair_upper_bound"], 0)
                self.assertEqual(result["projection"], policy)
        self.assertEqual(list(graph.nodes), ["A", "B", "C"])
        self.assertEqual(graph.number_of_edges(), 0)

    def test_empty_graph_and_activity_only_graph(self):
        for graph in (nx.Graph(), nx.empty_graph(["activity"])):
            for policy in ("count", "newman"):
                with self.subTest(nodes=list(graph), policy=policy):
                    result = affiliation_report(graph, [], projection=policy, max_pairs=0)
                    self.assertEqual(result["persons"], [])
                    self.assertEqual(result["projected_edge_count"], 0)
                    self.assertEqual(result["projected_isolates"], [])
                    self.assertEqual(result["activities"], sorted(graph))

    def test_no_projection_is_not_a_zero_edge_projection(self):
        result = affiliation_report(nx.empty_graph(["A", "B"]), ["A", "B"],
            projection="none", max_pairs=0)
        self.assertEqual(result["projection_status"], "NOT_REQUESTED")
        self.assertIsNone(result["projected_edge_count"])
        self.assertIsNone(result["projected_isolates"])
        self.assertIsNone(result["algorithm"])

    def test_invalid_person_only_incidence_remains_rejected(self):
        graph = nx.Graph()
        graph.add_edge("A", "B")
        for policy in ("count", "newman"):
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError,
                    "every incidence must connect a person and an activity"):
                affiliation_report(graph, ["A", "B"], projection=policy)

    def test_nonempty_activity_uses_original_upstream_weighting(self):
        graph = nx.Graph()
        graph.add_nodes_from(("A", "B", "C"), bipartite=0)
        graph.add_node("meeting", bipartite=1, evidence=["activity"])
        graph.add_edges_from((a, "meeting", {"evidence": ["attendance-"+a]})
            for a in ("A", "B", "C"))
        for policy, algorithm, strength in (
                ("count", "weighted_projected_graph", 1),
                ("newman", "collaboration_weighted_projected_graph", 0.5)):
            with self.subTest(policy=policy):
                result = affiliation_report(graph, ["A", "B", "C"],
                    projection=policy, max_pairs=3)
                self.assertEqual(result["algorithm"],
                    "networkx.algorithms.bipartite."+algorithm)
                self.assertEqual(result["projected_edge_count"], 3)
                self.assertEqual(result["projected_isolates"], [])
                for edge in result["projected_edges"]:
                    self.assertEqual(edge["strength"], strength)
                    self.assertEqual(edge["activities"], ["meeting"])
                    self.assertIn("activity", edge["evidence"])
                with self.assertRaisesRegex(ValueError, "exceeds max_pairs"):
                    affiliation_report(graph, ["A", "B", "C"], projection=policy,
                        max_pairs=2)
        self.assertEqual(davis_affiliation_report()["women_projected_coattendance_edge_count"], 139)
