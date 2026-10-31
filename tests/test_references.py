from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.references import karate_club_report


class PublishedSocialReferenceTest(unittest.TestCase):
    def test_karate_real_networkx_source_and_not_fake_directed_v19(self):
        report = karate_club_report()
        self.assertEqual(report["engine"], "networkx")
        self.assertEqual(report["kind"], "REFERENCE_DATASET_RESULT")
        self.assertEqual(report["population_size"], 34)
        self.assertEqual(report["edge_count"], 78)
        self.assertEqual(report["connected_component_count"], 1)
        self.assertFalse(report["directed"])
        self.assertEqual(report["relation"], "undirected_observed_social_interaction")
        self.assertEqual(report["post_fission_club_counts"], {"Mr. Hi": 17, "Officer": 17})
        self.assertEqual(report["top_unweighted_betweenness"][0]["actor"], "0")
        self.assertGreater(report["top_unweighted_betweenness"][0]["score"], 0.4)
        self.assertRegex(report["source_record_hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertFalse(report["has_longitudinal_waves"])
        self.assertFalse(report["post_fission_club_is_baseline_covariate"])

    def test_same_published_source_produces_same_hash(self):
        a, b = karate_club_report(), karate_club_report()
        self.assertEqual(a["source_record_hash"], b["source_record_hash"])
        self.assertEqual(a["top_unweighted_betweenness"], b["top_unweighted_betweenness"])


if __name__ == "__main__":
    unittest.main()
