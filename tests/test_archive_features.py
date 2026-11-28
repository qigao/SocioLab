"""Analytic and replay tests with authored fictional integer archive rows."""

from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sociolab.archive_features as features_module
from sociolab.archive_features import (
    ArchiveFeatureReplay, DYADIC_FEATURE_NAMES, NETWORK_FEATURE_NAMES, make_archive_features,
)
from sociolab.archive_recurrence import _archive_prediction
from sociolab.snapshots import content_hash


A, B, C, D = 100000001, 100000002, 100000003, 100000004
HISTORY = (
    (1, A, B, 9), (2, A, B, 0), (3, B, A, 2), (4, A, C, 4),
    (5, C, B, 6), (6, A, C, 6), (7, D, C, 8), (8, B, D, 7),
    (9, A, A, 5), (10, A, B, 5), (11, A, B, 5), (12, B, B, 9),
)


def build(rows=HISTORY, *, origin=10, horizon=4, recent_width=5):
    return make_archive_features(rows, origin=origin, horizon=horizon, recent_width=recent_width)


def pair(artifact, source, target):
    return next(row for row in artifact["rows"] if (row["source"], row["target"]) == (source, target))


class ArchiveFeatureTests(unittest.TestCase):
    def test_independent_feature_values_and_binary_graph(self):
        artifact = build()
        row = pair(artifact, A, B)
        expected_dyadic = [math.log(2.6), math.log(3.4), math.log(1.25)]
        expected_network = expected_dyadic + [math.log(1.4), 0.0, math.log(3), math.log(3), math.log(2)]
        for actual, expected in zip(row["dyadic_features"], expected_dyadic):
            self.assertAlmostEqual(actual, expected, places=14)
        for actual, expected in zip(row["network_features"], expected_network):
            self.assertAlmostEqual(actual, expected, places=14)
        self.assertEqual(artifact["feature_names"], {"dyadic": list(DYADIC_FEATURE_NAMES),
                                                    "network": list(NETWORK_FEATURE_NAMES)})
        self.assertEqual(len(artifact["rows"]), 6)
        self.assertEqual(artifact["history_row_count"], 12)
        baseline = _archive_prediction(HISTORY, origin=10, horizon=4, recent_width=5)
        self.assertEqual(artifact["baseline_forecast_hash"], baseline["content_hash"])
        unhashed = deepcopy(artifact)
        self.assertEqual(unhashed.pop("content_hash"), content_hash(unhashed))

    def test_direction_reverse_activity_and_two_step_paths(self):
        artifact = build()
        ab, ba = pair(artifact, A, B), pair(artifact, B, A)
        self.assertAlmostEqual(ba["network_features"][3], ab["dyadic_features"][0])
        self.assertAlmostEqual(ba["network_features"][4], ab["dyadic_features"][1])
        self.assertEqual(ba["network_features"][-1], 0.0)
        # A->C->B contributes to A->B. B->D->C contributes to B->C only
        # if B->C itself is already in the historical prediction risk set.
        self.assertFalse(any((row["source"], row["target"]) == (B, C) for row in artifact["rows"]))
        self.assertEqual(pair(artifact, A, C)["network_features"][-1], 0.0)

    def test_duplicate_rows_change_record_counts_but_not_degrees_or_path_count(self):
        full = pair(build(), A, B)
        without_duplicate = pair(build(tuple(row for row in HISTORY if row[0] != 11)), A, B)
        self.assertGreater(full["dyadic_features"][0], without_duplicate["dyadic_features"][0])
        self.assertGreater(full["dyadic_features"][1], without_duplicate["dyadic_features"][1])
        self.assertEqual(full["network_features"][5:], without_duplicate["network_features"][5:])
        self.assertEqual(full["dyadic_features"][2], without_duplicate["dyadic_features"][2])

    def test_self_rows_remain_in_evidence_but_do_not_add_features_or_graph_edges(self):
        no_self = tuple(row for row in HISTORY if row[1] != row[2])
        self.assertEqual(build()["rows"], build(no_self)["rows"])
        self.assertNotEqual(build()["history_rows_hash"], build(no_self)["history_rows_hash"])
        self_only = build(((1, A, A, 3),))
        self.assertEqual(self_only["rows"], [])
        self.assertTrue(self_only["scope"]["contains_private_actor_records"])

    def test_recent_left_boundary_and_origin_future_rejection(self):
        rows = ((1, A, B, 4), (2, A, B, 5), (3, A, B, 9))
        self.assertAlmostEqual(pair(build(rows), A, B)["dyadic_features"][1], math.log(2.6))
        for when in (10, 11):
            with self.subTest(when=when), self.assertRaisesRegex(ValueError, "strictly before"):
                build(rows + ((4, A, B, when),))
        with self.assertRaisesRegex(ValueError, "fixed zero"):
            build((), origin=4, recent_width=5)

    def test_history_identity_is_independent_of_iteration_and_timestamp_tie_order(self):
        shuffled = HISTORY[7:] + HISTORY[:7]
        self.assertEqual(build(), build(tuple(reversed(shuffled))))
        self.assertEqual(build(), build([list(row) for row in shuffled]))

    def test_appending_a_future_tail_cannot_change_a_prior_feature_artifact(self):
        future = HISTORY + ((13, D, A, 10), (14, A, B, 100), (15, 100000005, A, 100))
        history = tuple(row for row in future if row[3] < 10)
        self.assertEqual(build(), build(history))
        self.assertNotIn(100000005, {actor for row in build()["rows"] for actor in (row["source"], row["target"])})

    def test_empty_history_has_finite_empty_feature_rows(self):
        artifact = build(())
        self.assertEqual(artifact["rows"], [])
        self.assertEqual(artifact["history_row_count"], 0)
        self.assertEqual(artifact["history_rows_hash"], content_hash(()))

    def test_invalid_rows_fail_without_coercion(self):
        bad = [None, "bad", ((1, A, B),), ((1, A, B, 1, 2),), ((True, A, B, 1),),
               ((1, A, B, 1.0),), ((0, A, B, 1),), ((100001, A, B, 1),),
               ((1, -1, B, 1),), ((1, A, 2**31, 1),), ((1, A, B, -1),),
               ((1, A, B, 2**63),), ((1, A, B, 1), (1, B, A, 2))]
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                build(rows)

    def test_duration_and_resource_limits_are_explicit(self):
        for name, value in (("origin", True), ("origin", 0), ("horizon", -1),
                            ("horizon", 2**63), ("recent_width", 1.0)):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                build((), **{name: value})
        with self.assertRaises(ValueError):
            build((), origin=2**63 - 2, horizon=4)
        for name, limit in (("_MAX_ROWS", 2), ("_MAX_NODES", 3), ("_MAX_PAIRS", 5)):
            with self.subTest(limit=name), patch.object(features_module, name, limit), self.assertRaises(ValueError):
                build()

    def test_replay_matches_batch_at_every_origin_including_empty_interval(self):
        stream = HISTORY + ((13, D, A, 10), (14, A, B, 14))
        replay = ArchiveFeatureReplay(horizon=4, recent_width=5)
        previous = 0
        for origin in (5, 10, 15, 25):
            added = tuple(reversed(tuple(row for row in stream if previous <= row[3] < origin)))
            actual = replay.advance(origin, added)
            historical = tuple(row for row in stream if row[3] < origin)
            self.assertEqual(actual, build(historical, origin=origin))
            self.assertEqual(replay.origin, origin)
            self.assertEqual(replay.history_rows, historical)
            previous = origin
        # The empty final interval changes age and expires all recent counts.
        self.assertEqual(pair(actual, A, B)["dyadic_features"][1], 0.0)
        self.assertGreater(pair(actual, A, B)["dyadic_features"][2], 0.0)

    def test_replay_rejects_invalid_clock_late_rows_reuse_and_future_rows_atomically(self):
        replay = ArchiveFeatureReplay(horizon=4, recent_width=5)
        initial = tuple(row for row in HISTORY if row[3] < 5)
        before = replay.advance(5, initial)
        bad_calls = ((5, ()), (4, ()), (10, ((20, A, B, 4),)),
                     (10, ((20, A, B, 10),)), (10, ((2, A, B, 6),)),
                     (10, ((20, A, B, 6), (20, B, A, 7))))
        for origin, rows in bad_calls:
            with self.subTest(origin=origin, rows=rows), self.assertRaises(ValueError):
                replay.advance(origin, rows)
            self.assertEqual(replay.origin, 5)
            self.assertEqual(replay.history_rows, initial)
            self.assertEqual(build(replay.history_rows, origin=5), before)
        later = tuple(row for row in HISTORY if 5 <= row[3] < 10)
        self.assertEqual(replay.advance(10, later), build())

    def test_replay_rolls_back_resource_and_window_errors(self):
        replay = ArchiveFeatureReplay(horizon=4, recent_width=5)
        with self.assertRaises(ValueError):
            replay.advance(4, ((1, A, B, 1),))
        self.assertEqual((replay.origin, replay.history_rows), (0, ()))
        initial = ((1, A, B, 1),)
        replay.advance(5, initial)
        with patch.object(features_module, "_MAX_NODES", 2), self.assertRaises(ValueError):
            replay.advance(10, ((2, C, A, 5),))
        self.assertEqual((replay.origin, replay.history_rows), (5, initial))
        actual = replay.advance(10, ((2, C, A, 5),))
        self.assertEqual(actual, build(initial + ((2, C, A, 5),)))


if __name__ == "__main__":
    unittest.main()
