"""Exact archive-presence checks using authored fictional rows only."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sociolab.archive_features as feature_module
from sociolab.archive_observation import audit_archive_windows
from sociolab.snapshots import content_hash


A, B, C, D = 100000021, 100000022, 100000023, 100000024
ROWS = ((1, A, B, 10), (2, B, A, 2), (3, C, C, 20),
        (4, A, B, 10), (5, C, D, 30), (6, A, B, 21))


def window(identifier="example", start=0, end=40):
    return {"id": identifier, "start": start, "end": end}


class ArchiveObservationTests(unittest.TestCase):
    def test_half_open_windows_preserve_physical_rows_and_exact_boundaries(self):
        declared = [window("before", 0, 10), window("duplicates", 10, 20),
                    window("mixed", 20, 30), window("last", 30, 31)]
        report = audit_archive_windows(ROWS, declared)
        self.assertEqual([item["row_count"] for item in report["windows"]], [1, 2, 2, 1])
        self.assertEqual([item["nonself_row_count"] for item in report["windows"]], [1, 2, 1, 1])
        self.assertEqual([item["first_record_in_window_seconds"] for item in report["windows"]], [2, 10, 20, 30])
        self.assertEqual([item["last_record_in_window_seconds"] for item in report["windows"]], [2, 10, 21, 30])
        self.assertEqual(report["windows"][1]["target_rows_hash"], content_hash((ROWS[0], ROWS[3])))
        self.assertEqual(report["windows"][2]["target_rows_hash"], content_hash((ROWS[2], ROWS[5])))
        self.assertEqual(report["source_rows_hash"], content_hash(ROWS))
        self.assertEqual((report["source_row_count"], report["distinct_record_time_count"]), (6, 5))

    def test_nearest_record_bounds_distinguish_internal_leading_and_trailing_empty_windows(self):
        report = audit_archive_windows(ROWS, [window("leading", 0, 2), window("internal", 22, 30),
                                              window("trailing", 31, 40)])
        leading, internal, trailing = report["windows"]
        self.assertEqual((leading["previous_record_at_seconds"], leading["next_record_at_seconds"]), (None, 2))
        self.assertEqual((internal["previous_record_at_seconds"], internal["next_record_at_seconds"]), (21, 30))
        self.assertEqual((trailing["previous_record_at_seconds"], trailing["next_record_at_seconds"]), (30, None))
        self.assertEqual([item["empty_window_internally_bounded"] for item in report["windows"]], [False, True, False])
        for item in report["windows"]:
            self.assertEqual(item["target_rows_hash"], content_hash(()))
            self.assertEqual(item["archive_row_status"], "NO_ARCHIVE_ROWS")
            self.assertIsNone(item["first_record_in_window_seconds"])
            self.assertIsNone(item["last_record_in_window_seconds"])

    def test_nonempty_windows_are_not_marked_as_empty_gaps_despite_external_bounds(self):
        item = audit_archive_windows(ROWS, [window(start=10, end=20)])["windows"][0]
        self.assertEqual((item["previous_record_at_seconds"], item["next_record_at_seconds"]), (2, 20))
        self.assertFalse(item["empty_window_internally_bounded"])
        self.assertEqual(item["archive_row_status"], "ARCHIVE_ROWS_PRESENT")

    def test_self_only_window_is_present_without_nonself_pairs(self):
        item = audit_archive_windows(ROWS, [window(start=20, end=21)])["windows"][0]
        self.assertEqual(item["row_count"], 1)
        self.assertEqual(item["nonself_row_count"], 0)
        self.assertEqual(item["distinct_actor_count"], 1)
        self.assertEqual(item["distinct_nonself_pair_count"], 0)
        self.assertEqual(item["archive_row_status"], "ARCHIVE_ROWS_PRESENT")
        self.assertFalse(item["empty_window_internally_bounded"])

    def test_real_coverage_remains_unknown_for_present_and_empty_archive_windows(self):
        report = audit_archive_windows(ROWS, [window("present", 0, 21), window("empty", 22, 30)])
        for item in report["windows"]:
            self.assertEqual(item["real_coverage_status"], "UNKNOWN")
            self.assertEqual(item["real_coverage_evidence"], [])
            self.assertFalse(item["membership_eligibility_verified"])
            self.assertEqual(item["strict_complete_observation_r1_status"], "NOT_ADMITTED")
        self.assertFalse(report["scope"]["coverage_events_created"])
        self.assertFalse(report["scope"]["real_observation_coverage_inferred"])
        self.assertFalse(report["scope"]["real_communication_absence_inferred"])
        self.assertFalse(report["scope"]["relationship_termination_inferred"])

    def test_gap_uses_distinct_record_times_open_endpoints_and_separate_elapsed_quantity(self):
        report = audit_archive_windows(ROWS, [window()])
        self.assertEqual((report["first_record_seconds"], report["last_record_seconds"]), (2, 30))
        gap = report["longest_between_record_gap"]
        self.assertEqual(gap["maximum_elapsed_seconds"], 10)
        self.assertEqual(gap["tied_maximum_count"], 1)
        self.assertEqual(gap["first_20_intervals"], [{"left_record_seconds": 10, "right_record_seconds": 20,
                                                    "elapsed_seconds": 10, "interior_integer_seconds": 9}])
        self.assertEqual(gap["interval_boundary"], "open_both_record_endpoints_excluded")
        self.assertFalse(gap["intervals_truncated"])
        self.assertFalse(report["scope"]["recording_start_or_end_inferred"])

    def test_adjacent_integer_records_have_zero_interior_timestamp_values(self):
        rows = ((1, A, B, 0), (2, B, A, 1))
        gap = audit_archive_windows(rows, [window(start=0, end=1)])["longest_between_record_gap"]
        self.assertEqual(gap["status"], "AVAILABLE")
        self.assertEqual(gap["maximum_elapsed_seconds"], 1)
        self.assertEqual(gap["first_20_intervals"][0]["interior_integer_seconds"], 0)

    def test_no_rows_or_one_distinct_time_does_not_invent_recording_boundaries(self):
        for rows, endpoint in (((), None), (((1, A, B, 0), (2, B, A, 0)), 0)):
            with self.subTest(rows=rows):
                report = audit_archive_windows(rows, [window(start=0, end=100)])
                self.assertEqual(report["first_record_seconds"], endpoint)
                self.assertEqual(report["last_record_seconds"], endpoint)
                gap = report["longest_between_record_gap"]
                self.assertEqual(gap["status"], "NOT_AVAILABLE")
                self.assertIsNone(gap["maximum_elapsed_seconds"])
                self.assertEqual(gap["tied_maximum_count"], 0)
                self.assertEqual(gap["first_20_intervals"], [])
                self.assertFalse(gap["intervals_truncated"])

    def test_tied_longest_gaps_are_counted_but_output_is_bounded(self):
        rows = tuple((index + 1, A, B, 3 * index) for index in range(26))
        gap = audit_archive_windows(rows, [window(end=76)])["longest_between_record_gap"]
        self.assertEqual((gap["maximum_elapsed_seconds"], gap["tied_maximum_count"]), (3, 25))
        self.assertEqual(len(gap["first_20_intervals"]), 20)
        self.assertEqual(gap["first_20_intervals"][-1]["left_record_seconds"], 57)
        self.assertEqual(gap["first_20_intervals"][-1]["right_record_seconds"], 60)
        self.assertTrue(gap["intervals_truncated"])

    def test_input_order_and_timestamp_ties_do_not_change_evidence_identity(self):
        expected = audit_archive_windows(ROWS, [window()])
        self.assertEqual(audit_archive_windows(tuple(reversed(ROWS)), [window()]), expected)
        self.assertEqual(audit_archive_windows([list(row) for row in reversed(ROWS)], [window()]), expected)
        unique = tuple(row for row in ROWS if row[0] != 4)
        without_duplicate = audit_archive_windows(unique, [window()])
        self.assertEqual(expected["longest_between_record_gap"], without_duplicate["longest_between_record_gap"])
        self.assertNotEqual(expected["source_rows_hash"], without_duplicate["source_rows_hash"])

    def test_later_tail_changes_retrospective_bounds_without_claiming_past_only_forecast(self):
        first = audit_archive_windows(((1, A, B, 2),), [window(start=10, end=20)])
        later = audit_archive_windows(((1, A, B, 2), (2, B, A, 30)), [window(start=10, end=20)])
        self.assertEqual(first["windows"][0]["row_count"], later["windows"][0]["row_count"])
        self.assertFalse(first["windows"][0]["empty_window_internally_bounded"])
        self.assertTrue(later["windows"][0]["empty_window_internally_bounded"])
        self.assertNotEqual(first["content_hash"], later["content_hash"])
        self.assertFalse(later["scope"]["past_only_forecast"])
        self.assertTrue(later["scope"]["later_archive_records_used_for_gap_boundaries"])

    def test_valid_adjacent_windows_accept_zero_and_maximum_source_boundaries(self):
        last = 2**63 - 1
        rows = ((1, A, B, 0), (2, A, B, last - 1), (3, B, A, last))
        report = audit_archive_windows(rows, [window("zero", 0, 1), window("upper", last - 1, last)])
        self.assertEqual([item["row_count"] for item in report["windows"]], [1, 1])
        self.assertEqual(report["windows"][-1]["next_record_at_seconds"], last)
        adjacent = [window(str(index), index, index + 1) for index in range(100)]
        self.assertEqual(len(audit_archive_windows((), adjacent)["windows"]), 100)

    def test_invalid_window_fields_types_identifiers_and_order_are_rejected(self):
        invalid = [None, (), [], [window()] * 101, [None], [{"id": "x", "start": 0}],
                   [{**window(), "extra": 1}], [window(identifier="")], [window(identifier="  ")],
                   [window(identifier=1)], [window(identifier="x" * 101)], [window(start=True)],
                   [window(end=1.0)], [window(start=-1)], [window(start=5, end=5)],
                   [window(start=6, end=5)], [window(end=2**63)],
                   [window("x", 0, 2), window("x", 2, 3)],
                   [window("a", 0, 3), window("b", 2, 5)],
                   [window("a", 3, 5), window("b", 0, 2)]]
        for declared in invalid:
            with self.subTest(windows=declared), self.assertRaises(ValueError):
                audit_archive_windows(ROWS, declared)

    def test_shared_row_validation_and_resource_budgets_remain_effective(self):
        for rows in (None, ((1, A, B),), ((True, A, B, 1),), ((1, A, B, -1),),
                     ((1, A, B, 1), (1, B, A, 2))):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                audit_archive_windows(rows, [window()])
        for name, limit in (("_MAX_ROWS", 5), ("_MAX_NODES", 3), ("_MAX_PAIRS", 2)):
            with self.subTest(budget=name), patch.object(feature_module, name, limit), self.assertRaises(ValueError):
                audit_archive_windows(ROWS, [window()])

    def test_inputs_are_unchanged_on_success_and_failure_and_report_hash_is_complete(self):
        rows, declared = [list(row) for row in ROWS], [window()]
        before = deepcopy((rows, declared))
        report = audit_archive_windows(rows, declared)
        self.assertEqual((rows, declared), before)
        unhashed = deepcopy(report)
        self.assertEqual(unhashed.pop("content_hash"), content_hash(unhashed))
        invalid = [window("a", 0, 20), window("b", 10, 30)]
        invalid_before = deepcopy(invalid)
        with self.assertRaises(ValueError):
            audit_archive_windows(rows, invalid)
        self.assertEqual(rows, before[0])
        self.assertEqual(invalid, invalid_before)


if __name__ == "__main__":
    unittest.main()
