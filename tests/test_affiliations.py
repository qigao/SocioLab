from pathlib import Path
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.affiliations import davis_affiliation_report
from sociolab.cli import main


class DavisAffiliationReferenceTest(unittest.TestCase):
    def test_real_upstream_reference_and_bipartite_projection(self):
        with patch("networkx.davis_southern_women_graph", wraps=nx.davis_southern_women_graph) as loader:
            report = davis_affiliation_report()
            loader.assert_called_once_with()
        self.assertEqual(report["kind"], "REFERENCE_DATASET_RESULT")
        self.assertEqual(report["engine"], "networkx")
        self.assertEqual(report["person_count"], 18)
        self.assertEqual(report["event_count"], 14)
        self.assertEqual(report["observed_attendance_count"], 89)
        self.assertEqual(report["women_projected_coattendance_edge_count"], 139)
        self.assertFalse(report["directed"])
        self.assertTrue(report["bipartite"])
        self.assertIn("inferred", report["projection_kind"])
        self.assertFalse(report["has_longitudinal_network_waves"])
        self.assertFalse(report["causal_effect_identified"])
        self.assertRegex(report["source_record_hash"], r"^sha256:[0-9a-f]{64}$")

    def test_deterministic_observational_provenance(self):
        first = davis_affiliation_report()
        second = davis_affiliation_report()
        self.assertEqual(first["source_record_hash"], second["source_record_hash"])
        self.assertEqual(first["top_women_by_events_attended"], second["top_women_by_events_attended"])

    def test_cli_executes_actual_upstream(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["davis"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["observed_attendance_count"], 89)
        self.assertEqual(result["projection_kind"], "inferred_shared_event_count_not_observed_person_tie")

    def test_reject_wrong_observational_source(self):
        original = nx.davis_southern_women_graph()
        modified = original.copy()
        modified.add_edge("E1", "E2")  # invalid intramode relation
        with patch("networkx.davis_southern_women_graph", return_value=modified):
            with self.assertRaises(ValueError):
                davis_affiliation_report()


if __name__ == "__main__":
    unittest.main()
