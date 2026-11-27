from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.dataset import load_network
from sociolab.diffusion import threshold_report

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/synthetic_chain.json"


class UpstreamThresholdTest(unittest.TestCase):
    def assert_random_state_equal(self, first, second):
        self.assertEqual(first[0], second[0])
        np.testing.assert_array_equal(first[1], second[1])
        self.assertEqual(first[2:], second[2:])

    def test_actual_ndlib_threshold_execution(self):
        random_state = np.random.get_state()
        working_directory = Path.cwd()
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
        self.assert_random_state_equal(random_state, np.random.get_state())
        self.assertEqual(Path.cwd(), working_directory)

    def test_direction_is_not_implicitly_reversed(self):
        result = threshold_report(
            load_network(EXAMPLE), seeds=("carol",), threshold=0.5,
            steps=3, random_seed=7,
        )
        self.assertEqual(result["adopted_by_step"], [["carol"]] * 4)

    def test_concurrent_reports_preserve_caller_random_state(self):
        data = load_network(EXAMPLE)
        random_state = np.random.get_state()
        with ThreadPoolExecutor(max_workers=2) as executor:
            forward = executor.submit(
                threshold_report, data, seeds=("alice",), threshold=0.5,
                steps=3, random_seed=11,
            )
            backward = executor.submit(
                threshold_report, data, seeds=("carol",), threshold=0.5,
                steps=3, random_seed=23,
            )
            self.assertEqual(forward.result()["adopted_by_step"][-1], ["alice", "bob", "carol"])
            self.assertEqual(backward.result()["adopted_by_step"], [["carol"]] * 4)
        self.assert_random_state_equal(random_state, np.random.get_state())

    def test_actual_upstream_worker_failure_is_reported(self):
        # NDlib passes the seed to NumPy's legacy generator, which rejects
        # values above its uint32 range. Exercise a real failing child call.
        with self.assertRaisesRegex(RuntimeError, "NDlib threshold worker") as failure:
            threshold_report(
                load_network(EXAMPLE), seeds=("alice",), threshold=0.5,
                steps=3, random_seed=2**32,
            )
        self.assertIn("ValueError", str(failure.exception))
        self.assertIn("Seed must be between", str(failure.exception))

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
