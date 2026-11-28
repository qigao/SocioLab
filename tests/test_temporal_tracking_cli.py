"""The same CLI routes receipt batches and explicit time controls distinctly."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sociolab.cli import main
from test_temporal_tracking_store import temporal_inputs, advance
from test_tracking_store import batch


class TemporalTrackingCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        dataset, registration = temporal_inputs()
        self.journal, self.registration = self.root / "journal.json", self.root / "registration.json"
        self.journal.write_text(json.dumps(dataset.to_dict()))
        self.registration.write_text(json.dumps(registration))
        self.store = self.root / "store"
        self.run_cli(["tracking", "init", str(self.journal), str(self.registration), str(self.store)])

    def run_cli(self, arguments, source=""):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch("sys.stdin", io.StringIO(source)):
            result = main(arguments)
        self.assertEqual(result, 0)
        self.assertEqual(error.getvalue(), "")
        return output.getvalue()

    def test_mixed_stream_and_restarted_inspection_bind_both_axes(self):
        source = "".join(json.dumps(value) + "\n" for value in (advance(6), batch(), advance(6)))
        receipts = [json.loads(line) for line in self.run_cli(["tracking", "run", str(self.store)], source).splitlines()]
        self.assertEqual([r["status"] for r in receipts], ["APPLIED", "APPLIED", "NO_TIME_ADVANCE"])
        self.assertEqual([r["cursor"] for r in receipts], [6, 6, 6])
        self.assertEqual([r["knowledge_cutoff"] for r in receipts], [11, 12, 12])
        self.assertEqual([r["transition_cause"] for r in receipts], ["source_time_advance", "receipt_batch", "source_time_advance"])
        inspected = json.loads(self.run_cli(["tracking", "inspect", str(self.store)]))
        self.assertEqual(inspected["checkpoint_hash"], receipts[-1]["checkpoint_hash"])
        self.assertEqual(inspected["cursor"], 6)

    def test_invalid_control_after_time_commit_stops_with_line_number_and_retains_progress(self):
        source = json.dumps(advance(7)) + "\n" + json.dumps(advance(6)) + "\n"
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch("sys.stdin", io.StringIO(source)):
            with self.assertRaises(SystemExit) as failure:
                main(["tracking", "run", str(self.store)])
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("input line 2", error.getvalue())
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        inspected = json.loads(self.run_cli(["tracking", "inspect", str(self.store)]))
        self.assertEqual((inspected["sequence"], inspected["knowledge_cutoff"], inspected["cursor"]), (1, 11, 7))


if __name__ == "__main__":
    unittest.main()
