from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.dataset import NetworkDataset, load_network

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/synthetic_chain.json"


class DatasetTest(unittest.TestCase):
    def test_source_fields_and_exact_roundtrip(self):
        dataset = load_network(EXAMPLE)
        self.assertEqual(dataset.origin, "synthetic")
        self.assertEqual(dataset.relation, "contact_opportunity")
        self.assertEqual(dataset.time_index, 0)
        self.assertEqual(dataset.actors, ("alice", "bob", "carol"))
        self.assertEqual(NetworkDataset.from_mapping(dataset.to_dict()), dataset)
        self.assertRegex(dataset.content_hash, r"^sha256:[0-9a-f]{64}$")

    def test_reject_unknown_and_missing_fields(self):
        data = load_network(EXAMPLE).to_dict()
        data["private_message"] = "do not export"
        with self.assertRaises(ValueError):
            NetworkDataset.from_mapping(data)
        data.pop("private_message")
        data.pop("relation")
        with self.assertRaises(ValueError):
            NetworkDataset.from_mapping(data)

    def test_no_synthetic_reverse_edge_or_unknown_actor(self):
        dataset = load_network(EXAMPLE)
        graph = dataset.to_graph()
        self.assertTrue(graph.has_edge("alice", "bob"))
        self.assertFalse(graph.has_edge("bob", "alice"))
        raw = dataset.to_dict()
        raw["edges"] = [["alice", "outside"]]
        with self.assertRaises(ValueError):
            NetworkDataset.from_mapping(raw)

    def test_reject_duplicate_edge_and_wrong_time(self):
        original = load_network(EXAMPLE).to_dict()
        original["edges"].append(["alice", "bob"])
        with self.assertRaises(ValueError):
            NetworkDataset.from_mapping(original)
        original["edges"].pop()
        original["time_index"] = True
        with self.assertRaises(ValueError):
            NetworkDataset.from_mapping(original)


if __name__ == "__main__":
    unittest.main()
