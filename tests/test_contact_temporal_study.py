"""Real source-admission failures; no reviewed data or engine results are faked."""

from contextlib import redirect_stderr, redirect_stdout
import gzip
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from sociolab.cli import main
from sociolab.contact_temporal_study import hypertext2009_temporal_case_report
from sociolab.recorded_contacts import REFERENCE_PAYLOAD_SHA256, load_recorded_contact_archive


class ContactTemporalSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # Even the official filename cannot admit invented source contents.
        self.path = Path(temporary.name) / "ht2009_contact_list.dat.gz"

    def invented_archive(self):
        self.path.write_bytes(gzip.compress(b"20\t1\t2\n40\t1\t3\n", mtime=0))
        return self.path

    def assert_cli_rejected(self, command, message):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            main(["study", command, str(self.path)])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(message, stderr.getvalue())

    def test_format_valid_unreviewed_payload_rejected_before_engine_import(self):
        archive = load_recorded_contact_archive(self.invented_archive())
        self.assertEqual(archive.records, ((20, 1, 2), (40, 1, 3)))
        self.assertNotEqual(archive.payload_sha256, REFERENCE_PAYLOAD_SHA256)
        # Blocking the optional next import proves admission fails first. This
        # supplies no engine, result, or altered source fingerprint.
        with patch.dict(sys.modules, {"sociolab.temporal_contacts": None}):
            with self.assertRaisesRegex(ValueError, "this temporal case requires.*fingerprint"):
                hypertext2009_temporal_case_report(self.path)

    def test_study_subcommands_keep_distinct_source_admission_errors(self):
        self.invented_archive()
        cases = (
            ("hypertext2009-temporal", "this temporal case requires the reviewed Hypertext 2009 TSV payload fingerprint"),
            ("hypertext2009", "this case requires the reviewed Hypertext 2009 TSV payload fingerprint"),
        )
        for command, message in cases:
            with self.subTest(command=command):
                self.assert_cli_rejected(command, message)

    def test_temporal_cli_rejects_bad_and_truncated_gzip_without_report(self):
        for raw in (b"not a gzip archive", gzip.compress(b"20\t1\t2\n", mtime=0)[:-4]):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                self.assert_cli_rejected("hypertext2009-temporal", "invalid contact gzip stream")


if __name__ == "__main__":
    unittest.main()
