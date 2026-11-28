"""Saved-file receipt-plan CLI integration without evaluation-time refitting."""

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


EXAMPLES = Path(__file__).resolve().parents[1] / "examples/journal-evaluation"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class JournalEvaluationCliTests(unittest.TestCase):
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
            paths[name].write_text(json.dumps(dataset.to_dict()))
        for label, schedule in (("original", "schedule.json"), ("revised", "revised-target.schedule.json")):
            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("planning must not fit")):
                text, _ = self.run_cli(["forecast", "journal-plan", str(paths["initial"]),
                                        str(EXAMPLES / "initial-history.spec.json"), str(EXAMPLES / schedule)])
            paths["plan-" + label] = directory / f"plan-{label}.json"
            paths["plan-" + label].write_text(text)
        entries = []
        initial = read(EXAMPLES / "initial-history.spec.json")
        for index, (time, history_stage, history_cutoff, target_cutoff) in enumerate(((2, "initial", 24, 28), (3, "second_history", 36, 40))):
            spec = deepcopy(initial)
            spec["knowledge_cutoff"] = history_cutoff
            spec["target_at"] = time * 10
            spec["forecast_specification"]["target_time_index"] = time
            if index:
                spec["waves"].append({"time_index": 2, "at": 20})
            source_spec = directory / f"history-{time}.spec.json"
            source_spec.write_text(json.dumps(spec))
            history_text, _ = self.run_cli(["forecast", "journal-history", str(paths[history_stage]), str(source_spec), "--panel-only"])
            history = directory / f"history-{time}.json"
            history.write_text(history_text)
            forecast_spec = directory / f"forecast-{time}.spec.json"
            forecast_spec.write_text(json.dumps(spec["forecast_specification"]))
            prediction_text, _ = self.run_cli(["forecast", "create", str(history), str(forecast_spec)])
            prediction = directory / f"forecast-{time}.json"
            prediction.write_text(prediction_text)
            target_text, _ = self.run_cli(["forecast", "journal-target", str(paths["revised_target"]),
                                           str(source_spec), str(prediction), "--knowledge-cutoff", str(target_cutoff), "--target-only"])
            target = directory / f"target-{time}.json"
            target.write_text(target_text)
            entries.append({"forecast": prediction.name, "target": target.name})
            if time == 2:
                changed_text, _ = self.run_cli(["forecast", "journal-target", str(paths["revised_target"]),
                                                str(source_spec), str(prediction), "--knowledge-cutoff", "41", "--target-only"])
                (directory / "target-2-revised.json").write_text(changed_text)
        manifest = {"schema": "sociolab.journal-forecast-fold-manifest.v1", "folds": entries}
        paths["manifest-original"] = directory / "folds-original.json"
        paths["manifest-original"].write_text(json.dumps(manifest))
        revised = deepcopy(manifest)
        revised["folds"][0]["target"] = "target-2-revised.json"
        paths["manifest-revised"] = directory / "folds-revised.json"
        paths["manifest-revised"].write_text(json.dumps(revised))
        return paths, manifest

    def test_saved_relative_folds_allow_revision_and_replay_after_later_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths, _ = self.prepare(directory)
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            command = ["forecast", "journal-evaluate", str(paths["plan-original"])]
            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("evaluation must not refit")):
                text, report = self.run_cli([*command, str(paths["target_second"]), str(paths["manifest-original"])])
                replay, _ = self.run_cli([*command, str(paths["revised_target"]), str(paths["manifest-original"])])
                _, revised = self.run_cli(["forecast", "journal-evaluate", str(paths["plan-revised"]),
                                           str(paths["revised_target"]), str(paths["manifest-revised"])])
            self.assertEqual(report["kind"], "JOURNAL_FORECAST_EVALUATION")
            self.assertEqual(report["actor_forecast_count"], 8)
            self.assertEqual(text, replay)
            self.assertEqual(report["folds"][1]["history_revision"]["previous_target_comparison"]["changed_actor_count"], 1)
            self.assertNotEqual(report["content_hash"], revised["content_hash"])
            self.assertEqual([f["forecast_hash"] for f in report["folds"]], [f["forecast_hash"] for f in revised["folds"]])
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
            for actor in ("A", "B", "C", "D", "C_alias"):
                self.assertNotIn(json.dumps(actor), text)
            self.assertNotIn(str(directory), text)

    def test_manifest_shape_order_and_target_version_mismatch_reject_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths, manifest = self.prepare(directory)
            invalid = []
            changed = deepcopy(manifest)
            changed["folds"].pop()
            invalid.append(changed)
            changed = deepcopy(manifest)
            changed["folds"].reverse()
            invalid.append(changed)
            changed = deepcopy(manifest)
            changed["folds"][0]["score"] = "arbitrary-score.json"
            invalid.append(changed)
            changed = deepcopy(manifest)
            changed["folds"][0]["forecast"] = " "
            invalid.append(changed)
            changed = deepcopy(manifest)
            changed["folds"][0]["target"] = "target-2-revised.json"
            invalid.append(changed)
            command = ["forecast", "journal-evaluate", str(paths["plan-original"]),
                       str(paths["revised_target"]), str(paths["manifest-original"])]
            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("rejections must not refit")):
                for value in invalid:
                    paths["manifest-original"].write_text(json.dumps(value))
                    self.reject_cli(command)
                paths["manifest-original"].write_text('{"schema":"sociolab.journal-forecast-fold-manifest.v1","folds":[],"folds":[]}')
                self.reject_cli(command)

    def test_planning_requires_only_exact_initial_prefix_and_valid_explicit_schedule(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = read(EXAMPLES / "metadata.json")
            dataset = EventDataset.from_mapping(read(EXAMPLES / "empty.events.json"))
            for stage in ("initial", "target_first"):
                entry = metadata["stages"][stage]
                dataset = ingest_records(dataset, read(EXAMPLES / entry["batch"]), received_at=entry["received_at"])
            journal = directory / "later.json"
            journal.write_text(json.dumps(dataset.to_dict()))
            command = ["forecast", "journal-plan", str(journal), str(EXAMPLES / "initial-history.spec.json")]
            with patch.object(np.linalg, "lstsq", side_effect=AssertionError("planning cannot fit")):
                self.reject_cli([*command, str(EXAMPLES / "schedule.json")])
                prefix = dataset.to_dict()
                prefix["records"] = prefix["records"][:24]
                journal.write_text(json.dumps(prefix))
                schedule = read(EXAMPLES / "schedule.json")
                schedule["folds"][0]["target_knowledge_cutoff"] = True
                path = directory / "invalid-schedule.json"
                path.write_text(json.dumps(schedule))
                self.reject_cli([*command, str(path)])
                self.reject_cli(command)


if __name__ == "__main__":
    unittest.main()
