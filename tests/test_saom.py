"""Matrix-adapter invariants only; real cusna estimator admission is pending."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.panels import LongitudinalPanel, load_panel
from sociolab.saom import saom_wave_matrices, fit_network_saom

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/synthetic_longitudinal.json"


class SAOMInputTests(unittest.TestCase):
    def test_directed_source_identity_and_order(self):
        panel = load_panel(EXAMPLE)
        matrices = saom_wave_matrices(panel)
        self.assertEqual(len(matrices), 3)
        self.assertEqual([m.shape for m in matrices], [(3, 3)] * 3)
        self.assertTrue(all(m.dtype == np.uint8 for m in matrices))
        self.assertEqual([int(m.sum()) for m in matrices], [1, 2, 1])
        self.assertEqual([int(m[0, 1]) for m in matrices], [1, 1, 0])
        self.assertEqual([int(m[1, 0]) for m in matrices], [0, 0, 0])
        self.assertEqual([int(m[1, 2]) for m in matrices], [0, 1, 1])

    def test_cannot_count_unobserved_ties_as_zero(self):
        panel = load_panel(EXAMPLE)
        data = panel.to_dict()
        data["waves"][1]["network_complete"] = False
        with self.assertRaisesRegex(ValueError, "incomplete network"):
            saom_wave_matrices(LongitudinalPanel.from_mapping(data))

    def test_no_fake_saom_or_invalid_budget(self):
        panel = load_panel(EXAMPLE)
        for kwargs in ({"seed": True}, {"n1": 0}, {"nD": -1},
                       {"n2": (1, 1)}, {"n2": (1, 1, 1, True)},
                       {"batch2": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    fit_network_saom(panel, **kwargs)

    def test_reject_wrong_type(self):
        with self.assertRaises(TypeError):
            saom_wave_matrices({"actors": ["alice"]})


if __name__ == "__main__":
    unittest.main()
