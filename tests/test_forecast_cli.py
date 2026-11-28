"""Exercise the actual separated prediction/scoring command boundary."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from sociolab.cli import main


EXAMPLES = Path(__file__).resolve().parents[1] / "examples/forecast"


class BehaviorForecastCliTests(unittest.TestCase):
    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        return stdout.getvalue(), json.loads(stdout.getvalue())

    def test_create_before_target_exists_then_score_without_rewriting_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            history = private / "history.json"
            spec = private / "spec.json"
            target = private / "target.json"
            prediction = private / "prediction.json"
            history.write_bytes((EXAMPLES / "synthetic.history.json").read_bytes())
            spec.write_bytes((EXAMPLES / "synthetic.spec.json").read_bytes())
            self.assertFalse(target.exists())
            text, forecast = self.run_cli(["forecast", "create", str(history), str(spec)])
            self.assertEqual(forecast["kind"], "BEHAVIOR_FORECAST")
            self.assertEqual(forecast["history"]["wave_time_indices"], [0, 1])
            prediction.write_text(text, encoding="utf-8")
            frozen = prediction.read_bytes()
            target.write_bytes((EXAMPLES / "synthetic.target.json").read_bytes())
            _, scored = self.run_cli(["forecast", "score", str(prediction), str(target)])
            self.assertEqual(scored["kind"], "BEHAVIOR_FORECAST_SCORE")
            self.assertEqual(scored["forecast_hash"], forecast["content_hash"])
            self.assertEqual(scored["actor_count"], 4)
            self.assertEqual(scored["models"]["persistence"]["clipped"]["mae"], 0.5)
            self.assertEqual(prediction.read_bytes(), frozen)

    def test_future_wave_in_history_is_rejected_before_any_prediction_output(self):
        with tempfile.TemporaryDirectory() as directory:
            history = json.loads((EXAMPLES / "synthetic.history.json").read_text())
            future = json.loads(json.dumps(history["waves"][-1]))
            future["time_index"] = 2
            future["source_revision"] = "unexpected-future-wave"
            history["waves"].append(future)
            path = Path(directory) / "contains-target.json"
            path.write_text(json.dumps(history))
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                main(["forecast", "create", str(path), str(EXAMPLES / "synthetic.spec.json")])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("error:", stderr.getvalue())

    def test_duplicate_specification_fields_cannot_select_a_different_target(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = (EXAMPLES / "synthetic.spec.json").read_text()
            spec = spec.replace('"target_time_index": 2', '"target_time_index": 2, "target_time_index": 3')
            path = Path(directory) / "ambiguous-specification.json"
            path.write_text(spec)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                main(["forecast", "create", str(EXAMPLES / "synthetic.history.json"), str(path)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("duplicate", stderr.getvalue())

    def test_hidden_future_source_changes_leave_the_entire_prediction_identical(self):
        from test_s50_forecast import archive_bytes, synthetic_members

        original = synthetic_members()
        changed = dict(original)
        del changed["s50-network3.dat"]
        changed["s50-alcohol.dat"] = b"".join(
            b" ".join(row.split()[:2]) + b" invalid-future-\xff\n"
            for row in original["s50-alcohol.dat"].splitlines()
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            predictions = []
            for index, members in enumerate((original, changed)):
                archive = path / f"source-{index}.zip"
                history = path / f"history-{index}.json"
                archive.write_bytes(archive_bytes(members))
                history_text, _ = self.run_cli(["forecast", "s50-history", str(archive)])
                history.write_text(history_text)
                text, _ = self.run_cli([
                    "forecast", "create", str(history), str(EXAMPLES / "s50.spec.json"),
                ])
                predictions.append(text)
            self.assertEqual(predictions[0], predictions[1])


if __name__ == "__main__":
    unittest.main()
