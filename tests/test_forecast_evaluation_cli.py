"""Exercise saved-file rolling evaluation through the real CLI boundary."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from sociolab.cli import main


EXAMPLES = Path(__file__).resolve().parents[1] / "examples/forecast-evaluation"


class ForecastEvaluationCliTests(unittest.TestCase):
    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        return stdout.getvalue(), json.loads(stdout.getvalue())

    def reject_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            main(arguments)
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error:", stderr.getvalue())

    def prepare(self, directory):
        directory.mkdir()
        fixture = json.loads((EXAMPLES / "synthetic.panel.json").read_text())
        spec = json.loads((EXAMPLES / "initial.spec.json").read_text())
        plan_path = directory / "plan.json"
        with patch.object(np.linalg, "lstsq", side_effect=AssertionError("planning must not fit")):
            plan_text, _ = self.run_cli([
                "forecast", "plan", str(EXAMPLES / "initial.history.json"),
                str(EXAMPLES / "initial.spec.json"), "--targets", "2", "3",
            ])
        plan_path.write_text(plan_text)
        entries = []
        for time in (2, 3):
            paths = {name: directory / f"{name}-{time}.json"
                     for name in ("history", "forecast", "target", "specification")}
            paths["history"].write_text(json.dumps({**fixture, "waves": fixture["waves"][:time]}))
            paths["specification"].write_text(json.dumps({**spec, "target_time_index": time}))
            self.assertFalse(paths["target"].exists())
            forecast_text, _ = self.run_cli([
                "forecast", "create", str(paths["history"]), str(paths["specification"]),
            ])
            paths["forecast"].write_text(forecast_text)
            target = {
                "schema": "sociolab.behavior-target.v1",
                **{key: fixture[key] for key in
                   ("dataset_id", "origin", "source_reference", "behavior_variable")},
                "time_index": time, "source_revision": f"invented-target-{time}",
                "behavior": fixture["waves"][time]["behavior"],
            }
            paths["target"].write_text(json.dumps(target))
            entries.append({name: paths[name].name for name in ("history", "forecast", "target")})
        manifest = {"schema": "sociolab.behavior-forecast-fold-manifest.v1", "folds": entries}
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        return plan_path, manifest_path, manifest

    def test_relative_manifest_saved_forecasts_and_targets_evaluate_without_refitting(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "inputs"
            plan, manifest, _ = self.prepare(directory)
            before = {path.name: path.read_bytes() for path in directory.iterdir()}
            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("evaluation must not fit")):
                text, report = self.run_cli(["forecast", "evaluate", str(plan), str(manifest)])
            self.assertEqual(report["kind"], "BEHAVIOR_FORECAST_EVALUATION")
            self.assertEqual(report["target_time_indices"], [2, 3])
            self.assertEqual(report["actor_count"], 4)
            self.assertEqual(report["fold_count"], 2)
            self.assertEqual(report["actor_forecast_count"], 8)
            self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})
            for actor in ("A", "B", "C", "D"):
                self.assertNotIn(json.dumps(actor), text)
            self.assertNotIn(str(directory), text)

    def test_bad_or_incomplete_manifest_rejects_without_partial_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "inputs"
            plan, manifest_path, manifest = self.prepare(directory)
            invalid = []
            changed = deepcopy(manifest)
            changed["folds"].pop()
            invalid.append(changed)
            changed = deepcopy(manifest)
            changed["folds"][0]["score"] = "untrusted-score.json"
            invalid.append(changed)
            changed = deepcopy(manifest)
            changed["folds"][0]["history"] = " "
            invalid.append(changed)
            for value in invalid:
                manifest_path.write_text(json.dumps(value))
                self.reject_cli(["forecast", "evaluate", str(plan), str(manifest_path)])
            manifest_path.write_text('{"schema":"sociolab.behavior-forecast-fold-manifest.v1","folds":[],"folds":[]}')
            self.reject_cli(["forecast", "evaluate", str(plan), str(manifest_path)])

    def test_invalid_schedule_is_rejected_before_any_fit_or_plan_output(self):
        for targets in (("2",), ("2", "4"), ("3", "4"), ("2", "2")):
            with self.subTest(targets=targets), \
                    patch.object(np.linalg, "lstsq", side_effect=AssertionError("planning must not fit")):
                self.reject_cli([
                    "forecast", "plan", str(EXAMPLES / "initial.history.json"),
                    str(EXAMPLES / "initial.spec.json"), "--targets", *targets,
                ])


if __name__ == "__main__":
    unittest.main()
