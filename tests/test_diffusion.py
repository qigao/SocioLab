from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.dataset import load_network
from sociolab.diffusion import threshold_report

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/synthetic_chain.json"


class UpstreamThresholdTest(unittest.TestCase):
    def test_actual_ndlib_threshold_execution(self):
        result = threshold_report(
            load_network(EXAMPLE), seeds=("alice",), threshold=0.5,
            steps=3, random_seed=7,
        )
        self.assertEqual(result["kind"], "REFERENCE_MODEL_RESULT")
        self.assertEqual(result["engine"], "ndlib")
        self.assertEqual(result["model"], "ThresholdModel")
        self.assertEqual(result["adopted_by_step"], [
            ["alice"], ["alice", "bob"],
            ["alice", "bob", "carol"], ["alice", "bob", "carol"],
        ])

    def test_direction_is_not_implicitly_reversed(self):
        result = threshold_report(
            load_network(EXAMPLE), seeds=("carol",), threshold=0.5,
            steps=3, random_seed=7,
        )
        self.assertEqual(result["adopted_by_step"], [["carol"]] * 4)

    def test_fail_closed_configuration(self):
        data = load_network(EXAMPLE)
        for seeds, threshold, steps in (
            (("nobody",), 0.5, 2), (("alice",), float("nan"), 2),
            (("alice",), 1.5, 2), (("alice",), 0.5, 0),
        ):
            with self.subTest(seeds=seeds, threshold=threshold, steps=steps):
                with self.assertRaises(ValueError):
                    threshold_report(data, seeds=seeds, threshold=threshold, steps=steps)


if __name__ == "__main__":
    unittest.main()
