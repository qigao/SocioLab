from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.panels import LongitudinalPanel, NetworkWave, load_panel, longitudinal_structure_report

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/synthetic_longitudinal.json"


class LongitudinalPanelTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_actual_upstream_networkx_multiwave_metrics(self):
        with patch("networkx.density", wraps=nx.density) as density:
            record = longitudinal_structure_report(load_panel(EXAMPLE))
            self.assertEqual(density.call_count, 3)
        self.assertEqual(record["kind"], "REFERENCE_MODEL_RESULT")
        self.assertEqual(record["engine"], "networkx")
        self.assertEqual(record["wave_count"], 3)
        self.assertEqual([w["time_index"] for w in record["waves"]], [0, 2, 3])
        self.assertEqual([w["directed_edge_count"] for w in record["waves"]], [1, 2, 1])
        self.assertEqual([w["directed_density"] for w in record["waves"]], [1 / 6, 2 / 6, 1 / 6])
        self.assertEqual([w["weak_components"] for w in record["waves"]], [2, 1, 2])
        self.assertEqual([w["added_tie_count"] for w in record["waves"]], [None, 1, 0])
        self.assertEqual([w["removed_tie_count"] for w in record["waves"]], [None, 0, 1])
        self.assertEqual([w["missing_behavior_count"] for w in record["waves"]], [1, 0, 0])
        self.assertFalse(record["causal_effect_identified"])
        self.assertFalse(record["saom_model_fitted"])
        self.assertFalse(record["source_claim_verified"])

    def test_exact_canonical_roundtrip_and_hash(self):
        panel = load_panel(EXAMPLE)
        self.assertEqual(LongitudinalPanel.from_mapping(panel.to_dict()), panel)
        self.assertRegex(panel.content_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(panel.content_hash, load_panel(EXAMPLE).content_hash)
        self.assertEqual(panel.waves[0].behavior[-1], ("carol", None))

    def test_no_private_fields_or_relabeling(self):
        self.data["secret_message"] = "not an observed tie"
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)
        del self.data["secret_message"]
        self.data["relation"] = "trust"
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)

    def test_time_and_revision_monotonicity(self):
        self.data["waves"][1]["time_index"] = 0
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)
        self.data["waves"][1]["time_index"] = 2
        self.data["waves"][2]["source_revision"] = "synthetic-v1-w1"
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)

    def test_missing_ties_must_not_be_treated_as_absent(self):
        self.data["waves"][1]["network_complete"] = False
        dataset = LongitudinalPanel.from_mapping(self.data)
        with self.assertRaisesRegex(ValueError, "unobserved ties"):
            longitudinal_structure_report(dataset)

    def test_behavior_roster_and_measurements(self):
        self.data["waves"][0]["behavior"].pop("bob")
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)
        self.data["waves"][0]["behavior"]["bob"] = True
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)

    def test_unknown_actor_and_duplicate_directed_tie(self):
        self.data["waves"][0]["edges"] = [["alice", "unknown"]]
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)
        self.data["waves"][0]["edges"] = [["alice", "bob"], ["alice", "bob"]]
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)

    def test_public_dataclass_constructors_cannot_bypass_input_validation(self):
        original = load_panel(EXAMPLE)
        with self.assertRaises(ValueError):
            LongitudinalPanel(
                original.dataset_id, original.origin, original.source_reference,
                ("unknown", "unknown"), original.relation,
                original.behavior_variable, original.waves,
            )
        with self.assertRaises(ValueError):
            NetworkWave(0, "w0", True, (("alice", "alice"),), (("alice", 0),))

    def test_claimed_external_data_require_source_reference(self):
        self.data["origin"] = "external_observation"
        with self.assertRaises(ValueError):
            LongitudinalPanel.from_mapping(self.data)
        self.data["source_reference"] = "https://example.org/study"
        record = longitudinal_structure_report(LongitudinalPanel.from_mapping(self.data))
        self.assertFalse(record["source_claim_verified"])
        self.assertFalse(record["causal_effect_identified"])


if __name__ == "__main__":
    unittest.main()
