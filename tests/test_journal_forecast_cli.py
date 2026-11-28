"""Saved-file CLI boundaries for receipt-selected forecast inputs."""

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
from sociolab.events import EventDataset, ingest_records
from sociolab.snapshots import materialize_snapshot


EXAMPLES = Path(__file__).resolve().parents[1] / "examples/journal-forecast"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class JournalForecastCliTests(unittest.TestCase):
    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(arguments)
        self.assertEqual(result, 0)
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
        metadata = read(EXAMPLES / "metadata.json")
        dataset = EventDataset.from_mapping(read(EXAMPLES / "empty.events.json"))
        paths = {}
        for name in metadata["stage_order"]:
            stage = metadata["stages"][name]
            dataset = ingest_records(dataset, read(EXAMPLES / stage["batch"]), received_at=stage["received_at"])
            paths[name] = directory / f"journal-{name}.json"
            paths[name].write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
        spec = directory / "history.spec.json"
        spec.write_text((EXAMPLES / "history.spec.json").read_text(), encoding="utf-8")
        return paths, spec

    def test_history_bundle_and_panel_projection_are_consistent_without_fitting(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, spec = self.prepare(Path(temporary))
            before = {path: path.read_bytes() for path in [*paths.values(), spec]}
            command = ["forecast", "journal-history", str(paths["initial"]), str(spec)]
            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("bridge must not fit")):
                text, bundle = self.run_cli(command)
                _, panel = self.run_cli([*command, "--panel-only"])
                replay_text, _ = self.run_cli(["forecast", "journal-history", str(paths["revised_target"]), str(spec)])
            self.assertEqual(bundle["kind"], "JOURNAL_FORECAST_HISTORY")
            self.assertEqual(bundle["provenance"]["knowledge_cutoff"], 24)
            self.assertEqual(bundle["history"], panel)
            self.assertEqual(text, replay_text)
            self.assertFalse(bundle["scope"]["historical_as_of_availability_verified"])
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_target_cli_uses_saved_forecast_and_only_historical_networks(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths, spec = self.prepare(directory)
            _, bundle = self.run_cli(["forecast", "journal-history", str(paths["initial"]), str(spec)])
            history, forecast_spec, prediction = (directory / name for name in ("history.json", "forecast.spec.json", "prediction.json"))
            history.write_text(json.dumps(bundle["history"]))
            forecast_spec.write_text(json.dumps(bundle["specification"]["forecast_specification"]))
            prediction_text, forecast = self.run_cli(["forecast", "create", str(history), str(forecast_spec)])
            prediction.write_text(prediction_text)
            command = ["forecast", "journal-target", str(paths["target"]), str(spec), str(prediction), "--knowledge-cutoff", "33"]
            observed_times = []

            def historical_snapshot(dataset, view, **kwargs):
                observed_times.append(view["at"])
                self.assertIn(view["at"], (0, 10))
                self.assertEqual(kwargs["knowledge_cutoff"], 24)
                return materialize_snapshot(dataset, view, **kwargs)

            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("target/score must not fit")), \
                    patch("sociolab.journal_forecast.materialize_snapshot", side_effect=historical_snapshot):
                _, target_bundle = self.run_cli(command)
                target_text, target = self.run_cli([*command, "--target-only"])
                target_path = directory / "target.json"
                target_path.write_text(target_text)
                _, score = self.run_cli(["forecast", "score", str(prediction), str(target_path)])
            self.assertEqual(target_bundle["target"], target)
            self.assertEqual(target_bundle["forecast_hash"], forecast["content_hash"])
            self.assertEqual(score["forecast_hash"], forecast["content_hash"])
            self.assertEqual(observed_times, [0, 10, 0, 10])
            self.assertEqual(prediction.read_text(), prediction_text)

    def test_invalid_or_implicit_cutoffs_and_duplicate_fields_have_no_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, spec_path = self.prepare(Path(temporary))
            specification = read(spec_path)
            invalid = []
            changed = deepcopy(specification)
            changed["knowledge_cutoff"] = True
            invalid.append(changed)
            changed = deepcopy(specification)
            changed.pop("knowledge_cutoff")
            invalid.append(changed)
            changed = deepcopy(specification)
            changed["future_network"] = "not-admitted"
            invalid.append(changed)
            for value in invalid:
                spec_path.write_text(json.dumps(value))
                self.reject_cli(["forecast", "journal-history", str(paths["initial"]), str(spec_path)])
            spec_path.write_text('{"knowledge_cutoff":24,"knowledge_cutoff":29}')
            self.reject_cli(["forecast", "journal-history", str(paths["initial"]), str(spec_path)])
            self.reject_cli(["forecast", "journal-target", str(paths["target"]), str(spec_path), "unused-prediction.json"])

    def test_target_cli_rejects_an_old_forecast_bound_to_a_new_history_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths, spec = self.prepare(directory)
            _, bundle = self.run_cli(["forecast", "journal-history", str(paths["initial"]), str(spec)])
            history, forecast_spec, prediction = (directory / name for name in ("history.json", "forecast.spec.json", "prediction.json"))
            history.write_text(json.dumps(bundle["history"]))
            forecast_spec.write_text(json.dumps(bundle["specification"]["forecast_specification"]))
            prediction_text, _ = self.run_cli(["forecast", "create", str(history), str(forecast_spec)])
            prediction.write_text(prediction_text)
            changed = read(spec)
            changed["knowledge_cutoff"] = 29
            spec.write_text(json.dumps(changed))
            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("target must not refit")):
                self.reject_cli(["forecast", "journal-target", str(paths["target"]), str(spec),
                                 str(prediction), "--knowledge-cutoff", "33"])
            self.assertEqual(prediction.read_text(), prediction_text)


if __name__ == "__main__":
    unittest.main()
