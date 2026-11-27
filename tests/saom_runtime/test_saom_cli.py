"""The real optional CPU command must expose nonconvergence to callers."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from cusna.saom.data import synthetic_panel

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sociolab.cli import main
from test_saom_runtime import _panel


class SAOMCLITests(unittest.TestCase):
    def test_actual_nonconverged_fit_emits_diagnostics_and_nonzero_exit(self):
        data = synthetic_panel(20, mean_degree=4, change_frac=0.25, seed=17)
        panel = _panel(data.waves, "cli-upstream-synthetic-20")
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "panel.json"
            path.write_text(json.dumps(panel.to_dict()), encoding="utf-8")
            with redirect_stdout(output):
                status = main([
                    "saom", str(path), "--format", "panel", "--seed", "1234",
                    "--n1", "64", "--nd", "64", "--n3", "128",
                    "--batch2", "16", "--n2", "2", "2", "2", "2",
                ])
        report = json.loads(output.getvalue())
        self.assertEqual(status, 2)
        self.assertEqual(report["convergence_status"], "NOT_CONVERGED")
        self.assertFalse(report["convergence_is_validated"])
        self.assertFalse(report["independent_reference_validated"])
        self.assertFalse(report["causal_effect_identified"])
        self.assertEqual(report["engine"], "cusna")
        self.assertEqual(report["dataset_hash"], panel.content_hash)
        self.assertEqual(report["nD"], 64)
        self.assertEqual(report["n2"], [2, 2, 2, 2])
        self.assertEqual(report["n_simulations"], 576)
        self.assertIn("D", report["diagnostics"])
        self.assertIn("msf", report["diagnostics"])


if __name__ == "__main__":
    unittest.main()
