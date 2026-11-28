"""Released-record semantics using invented rows only; no source data is vendored."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import gzip
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sociolab.archive_recurrence as archive_module
from sociolab.archive_recurrence import (
    _archive_fold, _archive_prediction, _source_audit,
    email_eu_dept3_case_report, load_email_eu_dept3_archive,
)
from sociolab.cli import main


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/experiments/2026-11-28-dept3-archive/protocol.json"
A, B, C, D = 100000001, 100000002, 100000003, 100000004
MODELS = ("historical_poisson", "recent_poisson", "recent_occurrence")


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + sha256(raw.encode("utf-8")).hexdigest()


def invented_payload():
    # Physical order deliberately differs from time order, including two equal
    # archive rows. These are authored records, not messages from the real source.
    triples = [
        (A, B, 9), (A, B, 0), (B, A, 2), (C, D, 6),
        (A, B, 5), (A, B, 5), (C, C, 4),
        (A, B, 10), (B, A, 13), (A, C, 11), (C, C, 12), (C, D, 14),
        (A, C, 18), (D, B, 17), (A, B, 16), (C, D, 19),
    ]
    return "".join(f"{source} {target} {when}\n" for source, target, when in triples).encode("ascii")


def fictional_protocol():
    # Controlled trust-boundary fixture for wrapper/CLI tests. It is never a
    # replacement for the committed pre-acquisition research protocol.
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    protocol["study_id"] = "fictional-archive-contract-test"
    protocol["source"] = {"dataset": "invented integer rows", "source_url": "https://example.invalid/invented"}
    protocol["measurement"].update(origins=[10, 15], horizon=4, recent_width=5)
    protocol["analysis"]["probability_bins"] = [0, 0.5, 1]
    protocol["admission"].update(required_rows=16, required_nodes=4, minimum_archive_max_time=19)
    return protocol


class ArchiveRecurrenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "fictional.txt.gz"

    def source(self, payload=None, *, mtime=0):
        self.path.write_bytes(gzip.compress(invented_payload() if payload is None else payload, mtime=mtime))
        return self.path

    def archive(self):
        return load_email_eu_dept3_archive(self.source())

    def first_forecast(self, rows):
        return _archive_prediction(tuple(row for row in rows if row[3] < 10),
                                   origin=10, horizon=4, recent_width=5)

    def fictional_trust(self, protocol, payload=None):
        # Only this invented fixture is admitted inside the local test context.
        return patch.multiple(archive_module,
                              REFERENCE_PROTOCOL_HASH=digest(protocol),
                              REFERENCE_PAYLOAD_SHA256=sha256(invented_payload() if payload is None else payload).hexdigest(),
                              REFERENCE_GZIP_SHA256=sha256(self.path.read_bytes()).hexdigest())

    def test_parser_preserves_physical_identity_direction_duplicates_self_and_unsorted_time(self):
        archive = self.archive()
        self.assertEqual(archive.rows[:7], (
            (1, A, B, 9), (2, A, B, 0), (3, B, A, 2), (4, C, D, 6),
            (5, A, B, 5), (6, A, B, 5), (7, C, C, 4),
        ))
        self.assertEqual(archive.payload_sha256, sha256(invented_payload()).hexdigest())
        self.assertEqual(archive.compressed_sha256, sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual((archive.payload_bytes, archive.compressed_bytes),
                         (len(invented_payload()), len(self.path.read_bytes())))
        with self.assertRaises(AttributeError):
            archive.rows = ()
        audit = _source_audit(archive)
        self.assertEqual((audit["row_count"], audit["node_count"], audit["distinct_directed_pairs"],
                          audit["distinct_nonself_pairs"], audit["self_pair_rows"]), (16, 4, 6, 5, 2))
        self.assertEqual((audit["duplicate_triple_groups"], audit["duplicate_triple_additional_rows"]), (1, 1))
        self.assertEqual((audit["timestamp_tie_groups"], audit["timestamp_tie_additional_rows"]), (1, 1))
        self.assertEqual(audit["time_decreases_in_file_order"], 6)
        self.assertEqual((audit["minimum_relative_second"], audit["maximum_relative_second"]), (0, 19))
        self.assertEqual(audit["duplicate_rows_dropped"], 0)
        self.assertFalse(audit["file_order_used_as_receipt_order"])

    def test_parser_accepts_documented_whitespace_crlf_and_no_final_newline(self):
        archive = load_email_eu_dept3_archive(self.source(b"1\t2\t0\r\n2  1  3"))
        self.assertEqual(archive.rows, ((1, 1, 2, 0), (2, 2, 1, 3)))

    def test_bad_gzip_empty_payload_and_truncated_stream_fail_entire_read(self):
        for raw in (b"", b"not gzip", gzip.compress(b""), gzip.compress(b"1 2 0\n")[:-4]):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.path.write_bytes(raw)
                load_email_eu_dept3_archive(self.path)

    def test_bad_rows_are_rejected_without_silent_dropping(self):
        invalid = [b"\n", b"1 2 0\n\n", b"1 2\n", b"1 2 3 4\n", b"source target time\n",
                   b"1 2 -1\n", b"-1 2 0\n", b"+1 2 0\n", b"01 2 0\n", b"1 2 0.0\n",
                   b"1 2 1e3\n", b"1 2 \xff\n", b"2147483648 2 0\n",
                   b"1 2 9223372036854775808\n", b"1 2 10000000000000000000\n"]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                load_email_eu_dept3_archive(self.source(payload))

    def test_resource_budgets_reject_whole_archive_without_selecting_a_subset(self):
        self.source()
        for name, limit in (("_MAX_COMPRESSED_BYTES", 1), ("_MAX_DECOMPRESSED_BYTES", 1),
                            ("_MAX_ROWS", 1), ("_MAX_NODES", 2), ("_MAX_PAIRS", 1)):
            with self.subTest(name=name), patch.object(archive_module, name, limit), self.assertRaises(ValueError):
                load_email_eu_dept3_archive(self.path)

    def test_history_counts_and_probabilities_have_independent_closed_form_expectations(self):
        archive = self.archive()
        forecast = self.first_forecast(archive.rows)
        self.assertEqual((forecast["history_row_count"], forecast["history_nonself_row_count"],
                          forecast["recent_nonself_row_count"], forecast["history_actor_count"]), (7, 6, 4, 4))
        expected = {
            (A, B): (4, 3, 1 - math.exp(-1.6), 1 - math.exp(-2.4), 1.0),
            (B, A): (1, 0, 1 - math.exp(-0.4), 0.0, 0.0),
            (C, D): (1, 1, 1 - math.exp(-0.4), 1 - math.exp(-0.8), 1.0),
        }
        actual = {(row["source"], row["target"]): row for row in forecast["predictions"]}
        self.assertEqual(set(actual), set(expected))
        for pair, (history_count, recent_count, *probabilities) in expected.items():
            self.assertEqual((actual[pair]["history_count"], actual[pair]["recent_count"]), (history_count, recent_count))
            for model, probability in zip(MODELS, probabilities):
                self.assertAlmostEqual(actual[pair]["probabilities"][model], probability, places=14)
        self.assertEqual(forecast["content_hash"], digest({k: v for k, v in forecast.items() if k != "content_hash"}))

    def test_history_entry_point_rejects_target_rows_and_invalid_windows(self):
        for when in (-1, 10, 11):
            with self.subTest(when=when), self.assertRaisesRegex(ValueError, "strictly before"):
                _archive_prediction(((1, A, B, when),), origin=10, horizon=4, recent_width=5)
        for values in ((0, 4, 5), (10, 0, 5), (10, 4, 0), (10, 4, 11),
                       (True, 4, 1), (10, 4.0, 5)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                _archive_prediction((), origin=values[0], horizon=values[1], recent_width=values[2])

    def test_exact_target_window_scores_only_historical_pairs_and_preserves_independent_bin_arithmetic(self):
        archive = self.archive()
        forecast = self.first_forecast(archive.rows)
        target = tuple(row for row in archive.rows if 10 <= row[3] < 14)
        original = deepcopy(forecast)
        report, _, risk = _archive_fold(forecast, target, [0, 0.5, 1])
        self.assertEqual(forecast, original)
        self.assertEqual(risk, {(A, B), (B, A), (C, D)})
        self.assertEqual((report["risk_pairs"], report["archive_positive_pairs"],
                          report["archive_negative_pairs"], report["target_positive_pairs_outside_risk"]), (3, 2, 1, 1))
        self.assertEqual((report["target_row_count"], report["target_nonself_row_count"]), (4, 3))
        expected = {
            "historical_poisson": [1 - math.exp(-1.6), 1 - math.exp(-0.4), 1 - math.exp(-0.4)],
            "recent_poisson": [1 - math.exp(-2.4), 0.0, 1 - math.exp(-0.8)],
            "recent_occurrence": [1.0, 0.0, 1.0],
        }
        outcomes = [1, 1, 0]
        for model, probabilities in expected.items():
            actual = report["models"][model]
            self.assertEqual(actual["n"], 3)
            self.assertAlmostEqual(actual["brier"], sum((p-y)**2 for p, y in zip(probabilities, outcomes))/3, places=14)
            self.assertAlmostEqual(actual["mean_predicted_probability"], sum(probabilities)/3, places=14)
            self.assertEqual(actual["observed_fraction"], 2/3)
            for index, row in enumerate(report["probability_diagnostics"][model]["bins"]):
                selected = [(p, y) for p, y in zip(probabilities, outcomes) if (p < 0.5) == (index == 0)]
                self.assertEqual(row["count"], len(selected))
                self.assertEqual(row["positive_count"], sum(y for _, y in selected))
                self.assertAlmostEqual(row["sum_predicted_probability"], sum(p for p, _ in selected), places=14)
                self.assertAlmostEqual(row["sum_squared_error"], sum((p-y)**2 for p, y in selected), places=14)
        self.assertEqual(report["always_zero_brier"], 2/3)
        # One row exactly at the right boundary must not be quietly included.
        for when in (9, 14):
            with self.subTest(when=when), self.assertRaisesRegex(ValueError, "half-open"):
                _archive_fold(forecast, ((99, A, B, when),), [0, 1])

    def test_future_tail_changes_source_identity_but_not_historical_forecast(self):
        first_archive = self.archive()
        first = self.first_forecast(first_archive.rows)
        extended = invented_payload() + f"{D} {A} 100\n".encode("ascii")
        next_archive = load_email_eu_dept3_archive(self.source(extended))
        self.assertNotEqual(first_archive.payload_sha256, next_archive.payload_sha256)
        self.assertEqual(self.first_forecast(next_archive.rows), first)
        self.assertFalse(first["scope"]["real_receipt_history_reconstructed"])
        self.assertFalse(first["scope"]["prospective_issuance_verified"])

    def test_empty_history_or_self_only_history_never_becomes_zero_prediction_error(self):
        for history in ((), ((1, A, A, 0),)):
            with self.subTest(history=history):
                forecast = _archive_prediction(history, origin=10, horizon=4, recent_width=5)
                report, _, risk = _archive_fold(forecast, ((2, A, B, 10),), [0, 0.5, 1])
                self.assertEqual(risk, set())
                self.assertEqual(report["status"], "EMPTY_RISK_SET")
                self.assertEqual(report["risk_pairs"], 0)
                self.assertEqual(report["target_positive_pairs_outside_risk"], 1)
                self.assertIsNone(report["always_zero_brier"])
                for model in MODELS:
                    self.assertIsNone(report["models"][model]["brier"])
                    for row in report["probability_diagnostics"][model]["bins"]:
                        self.assertEqual(row["count"], 0)
                        self.assertIsNone(row["observed_fraction"])

    def test_unreviewed_payload_and_altered_protocol_fail_source_case(self):
        self.source()
        protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        self.assertEqual(digest(protocol), archive_module.REFERENCE_PROTOCOL_HASH)
        with self.assertRaisesRegex(ValueError, "reviewed released payload fingerprint"):
            email_eu_dept3_case_report(self.path, protocol)
        protocol["measurement"]["origins"][0] += 1
        with self.assertRaisesRegex(ValueError, "frozen pre-acquisition protocol"):
            email_eu_dept3_case_report(self.path, protocol)

    def test_controlled_fictional_case_recompression_counts_and_pooled_macro_denominators(self):
        self.source()
        protocol = fictional_protocol()
        with self.fictional_trust(protocol):
            report = email_eu_dept3_case_report(self.path, protocol)
            self.path.write_bytes(gzip.compress(invented_payload(), mtime=1))
            recompressed = email_eu_dept3_case_report(self.path, protocol)
        self.assertTrue(report["source"]["reviewed_compressed_bytes_match"])
        self.assertFalse(recompressed["source"]["reviewed_compressed_bytes_match"])
        self.assertEqual(report["models"], recompressed["models"])
        self.assertEqual(report["folds"], recompressed["folds"])
        self.assertEqual(report["counts"], {"planned_origins": 2, "scored_origins": 2,
                                         "risk_pair_origin_count": 7, "scored_pair_origin_count": 7,
                                         "archive_positive_pair_origin_count": 4,
                                         "archive_negative_pair_origin_count": 3})
        self.assertAlmostEqual(report["models"]["recent_occurrence"]["pooled_brier"], 4/7, places=14)
        self.assertAlmostEqual(report["models"]["recent_occurrence"]["macro_brier"], (2/3 + 2/4)/2, places=14)
        self.assertAlmostEqual(report["reference"]["always_zero_brier"], 4/7, places=14)
        change = report["folds"][1]["risk_change"]
        self.assertEqual((change["retained_pairs"], change["new_pairs"], change["removed_pairs"]), (3, 1, 0))
        self.assertEqual(report["admission"]["strict_complete_observation_r1_status"], "NOT_ADMITTED")
        self.assertFalse(report["scope"]["real_communication_forecast_validated"])
        self.assertFalse(report["scope"]["source_membership_or_coverage_assertions_created"])
        self.assertIsNone(report["scope"]["real_communication_coverage_complete"])
        self.assertEqual(report["content_hash"], digest({k: v for k, v in report.items() if k != "content_hash"}))
        def leaves(value):
            if isinstance(value, dict):
                return [leaf for item in value.values() for leaf in leaves(item)]
            if isinstance(value, list):
                return [leaf for item in value for leaf in leaves(item)]
            return [value]
        self.assertTrue(all(value not in (A, B, C, D) for value in leaves(report)))

    def test_case_rejects_predeclared_count_or_extent_mismatch_without_retuning(self):
        self.source()
        for key, bad_value in (("required_rows", 15), ("required_nodes", 3), ("minimum_archive_max_time", 20)):
            protocol = fictional_protocol()
            protocol["admission"][key] = bad_value
            with self.subTest(key=key), self.fictional_trust(protocol), self.assertRaises(ValueError):
                email_eu_dept3_case_report(self.path, protocol)

    def test_cli_reads_explicit_paths_and_never_emits_a_report_for_bad_protocol(self):
        self.source()
        protocol = fictional_protocol()
        protocol_path = self.root / "fictional-protocol.json"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        arguments = ["study", "email-eu-dept3", str(self.path), str(protocol_path)]
        output, error = io.StringIO(), io.StringIO()
        with self.fictional_trust(protocol), redirect_stdout(output), redirect_stderr(error):
            exit_code = main(arguments)
        self.assertEqual(exit_code, 0, error.getvalue())
        report = json.loads(output.getvalue())
        self.assertEqual(report["counts"]["risk_pair_origin_count"], 7)
        protocol_path.write_text('{"schema":"wrong"}', encoding="utf-8")
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            main(arguments)
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("frozen pre-acquisition protocol", error.getvalue())


if __name__ == "__main__":
    unittest.main()
