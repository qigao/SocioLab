"""CLI streaming output and fail-fast integration with real saved checkpoints."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sociolab.cli import main
from test_tracking_store import inputs, batch


class TrackingCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        dataset, registration = inputs()
        self.dataset = self.directory / "journal.json"
        self.registration = self.directory / "registration.json"
        self.store = self.directory / "store"
        self.dataset.write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
        self.registration.write_text(json.dumps(registration), encoding="utf-8")

    def invoke(self, arguments, source=""):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch("sys.stdin", io.StringIO(source)):
            result = main(arguments)
        self.assertEqual(result, 0)
        self.assertEqual(error.getvalue(), "")
        return output.getvalue()

    def initialize(self):
        return json.loads(self.invoke(["tracking", "init", str(self.dataset), str(self.registration), str(self.store)]))

    def test_real_init_stream_and_restart_emit_one_receipt_per_delivery(self):
        self.assertEqual(self.initialize()["status"], "INITIALIZED")
        delivery = json.dumps(batch()) + "\n"
        output = self.invoke(["tracking", "run", str(self.store)], delivery + delivery)
        receipts = [json.loads(line) for line in output.splitlines()]
        self.assertEqual([r["status"] for r in receipts], ["APPLIED", "NO_NEW_RECORDS"])
        self.assertEqual(receipts[0]["checkpoint_hash"], receipts[1]["checkpoint_hash"])
        inspected = json.loads(self.invoke(["tracking", "inspect", str(self.store)]))
        self.assertEqual(inspected["checkpoint_hash"], receipts[0]["checkpoint_hash"])
        self.assertEqual(self.invoke(["tracking", "run", str(self.store)], ""), "")
        self.assertEqual(len(list(self.store.glob("[0-9]*.json"))), 2)

    def test_invalid_second_line_reports_error_without_losing_the_first_commit(self):
        self.initialize()
        output, error = io.StringIO(), io.StringIO()
        source = json.dumps(batch()) + "\n{}\n" + json.dumps(batch("unread")) + "\n"
        with redirect_stdout(output), redirect_stderr(error), patch("sys.stdin", io.StringIO(source)):
            with self.assertRaises(SystemExit) as failure:
                main(["tracking", "run", str(self.store)])
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("input line 2", error.getvalue())
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(self.invoke(["tracking", "inspect", str(self.store)]))["sequence"], 1)


if __name__ == "__main__":
    unittest.main()
