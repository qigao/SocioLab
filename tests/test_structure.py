from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.dataset import load_network
from sociolab.structure import structural_report

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/synthetic_chain.json"


class StructureTest(unittest.TestCase):
    def test_real_upstream_networkx_directed_graph(self):
        dataset = load_network(EXAMPLE)
        report = structural_report(dataset)
        self.assertEqual(report["kind"], "REFERENCE_MODEL_RESULT")
        self.assertEqual(report["engine"], "networkx")
        self.assertEqual(report["relation"], "contact_opportunity")
        self.assertTrue(report["directed"])
        self.assertEqual(report["edge_count"], 2)
        self.assertEqual(report["weak_components"], [["alice", "bob", "carol"]])
        self.assertEqual(report["out_reachable_count"], {"alice": 2, "bob": 1, "carol": 0})
        self.assertGreater(report["betweenness_centrality"]["bob"], 0)
        self.assertEqual(report["betweenness_centrality"]["alice"], 0)


if __name__ == "__main__":
    unittest.main()
