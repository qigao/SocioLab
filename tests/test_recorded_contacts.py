"""Source interpretation and admission gates; no real rows are vendored."""

import gzip
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout

from sociolab.cli import main
from sociolab.recorded_contacts import load_recorded_contact_archive, hypertext2009_case_report


class RecordedContactSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "invented.dat.gz"

    def source(self, payload):
        self.path.write_bytes(gzip.compress(payload, mtime=0))
        return self.path

    def test_canonical_undirected_bins_preserve_orientation_audit(self):
        data = load_recorded_contact_archive(self.source(b"20\t7\t3\n20\t3\t9\n40\t9\t7\n"))
        self.assertEqual(data.actors, (3, 7, 9))
        self.assertEqual(data.records, ((20, 3, 7), (20, 3, 9), (40, 7, 9)))
        self.assertEqual(data.reversed_order_rows, 2)
        self.assertEqual(len(data.payload_sha256), 64)
        with self.assertRaises(AttributeError):
            data.records = ()

    def test_duplicate_pair_bins_reject_in_either_orientation(self):
        for second in (b"20\t1\t2\n", b"20\t2\t1\n"):
            with self.subTest(second=second), self.assertRaisesRegex(ValueError, "duplicates"):
                load_recorded_contact_archive(self.source(b"20\t1\t2\n" + second))

    def test_time_grid_order_bounds_and_self_pairs_reject(self):
        for payload in (b"0\t1\t2\n", b"21\t1\t2\n", b"604820\t1\t2\n",
                        b"40\t1\t2\n20\t1\t3\n", b"20\t1\t1\n",
                        b"20\t2147483648\t1\n"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                load_recorded_contact_archive(self.source(payload))

    def test_fields_require_exact_ascii_integer_tsv(self):
        for payload in (b"20 1 2\n", b"20\t01\t2\n", b"20\t+1\t2\n",
                        b"20\t1.0\t2\n", b"20\t1\t2\textra\n",
                        b"20\t1\t2\n\n", b"t\ti\tj\n", b"20\t\xff\t2\n"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                load_recorded_contact_archive(self.source(payload))

    def test_crlf_and_no_final_newline_are_format_valid_but_not_reviewed(self):
        a = load_recorded_contact_archive(self.source(b"20\t1\t2\r\n40\t1\t3"))
        self.assertEqual(a.records, ((20, 1, 2), (40, 1, 3)))
        with self.assertRaisesRegex(ValueError, "reviewed.*fingerprint"):
            hypertext2009_case_report(self.path)

    def test_bad_empty_and_truncated_gzip_reject(self):
        for raw in (b"", b"not gzip", gzip.compress(b""), gzip.compress(b"20\t1\t2\n")[:-4]):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    load_recorded_contact_archive(self.path)

    def test_resource_limits_apply_before_analysis(self):
        self.source(b"20\t1\t2\n40\t1\t3\n")
        for name, limit in (("_MAX_COMPRESSED_BYTES", 8), ("_MAX_DECOMPRESSED_BYTES", 8),
                            ("_MAX_RECORDS", 1), ("_MAX_ACTORS", 2)):
            with self.subTest(name=name), patch("sociolab.recorded_contacts." + name, limit):
                with self.assertRaises(ValueError):
                    load_recorded_contact_archive(self.path)

    def test_case_cli_rejects_unreviewed_source_without_fake_report(self):
        self.source(b"20\t1\t2\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            main(["study", "hypertext2009", str(self.path)])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("reviewed Hypertext 2009", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
