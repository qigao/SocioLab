"""Exact endpoint-count tests; no graph construction or estimator fixtures."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.partial_changes import partial_panel_report
from sociolab.partial_panels import PartialNetworkPanel, PartialNetworkWave, load_partial_panel


EXAMPLE = Path(__file__).resolve().parents[1] / "examples/partial/coverage.panel.json"
STATES = ("absent", "present", "unknown")


def make_panel(*, before_present=(), before_absent=(), after_present=(), after_absent=(), actors=("A", "B")):
    return PartialNetworkPanel(
        dataset_id="synthetic-partial-counts", origin="synthetic", source_reference=None,
        actors=actors, relation="synthetic_directed_tie",
        population_definition="The same invented actors are eligible at both endpoints.",
        observation_definition="Listed positive and negative observations are explicit; all other pairs are unknown.",
        waves=(
            PartialNetworkWave(0, "synthetic-source-w0", tuple(sorted(before_present)), tuple(sorted(before_absent))),
            PartialNetworkWave(2, "synthetic-source-w2", tuple(sorted(after_present)), tuple(sorted(after_absent))),
        ),
    )


class PartialNetworkChangesTests(unittest.TestCase):
    def assert_accounting(self, report):
        universe = report["dyad_universe_count"]
        for index, period in enumerate(report["periods"]):
            cells = period["transition_counts"]
            before = report["waves"][index]["state_counts"]
            after = report["waves"][index + 1]["state_counts"]
            self.assertEqual(sum(cells[a][b] for a in STATES for b in STATES), universe)
            for state in STATES:
                self.assertEqual(sum(cells[state].values()), before[state])
                self.assertEqual(sum(cells[old][state] for old in STATES), after[state])
            self.assertEqual(period["known_overlap"] + period["coverage_lost"], period["observed_before"])
            self.assertEqual(period["known_overlap"] + period["coverage_gained"], period["observed_after"])
            self.assertEqual(period["known_overlap"] + period["coverage_gained"] + period["coverage_lost"] + period["unknown_both"], universe)
            self.assertEqual(period["observed_hamming_distance"], period["observed_additions"] + period["observed_removals"])
            decomposition = period["positive_net_change_decomposition"]
            self.assertEqual(decomposition["sum"], decomposition["observed_additions_minus_removals"] + decomposition["coverage_gained_present_minus_lost_present"])
            self.assertEqual(decomposition["sum"], period["positive_count_change"])
            self.assertEqual(period["positive_count_change"], after["present"] - before["present"])

    def test_four_person_example_populates_all_nine_cells_without_disclosing_edges(self):
        panel = load_partial_panel(EXAMPLE)
        report = partial_panel_report(panel)
        self.assertEqual(report["kind"], "PARTIAL_NETWORK_OBSERVATION_REPORT")
        self.assertEqual(report["dataset_hash"], panel.content_hash)
        self.assertEqual(report["reported_scope"], "fixed directed offdiagonal declared actors")
        self.assertEqual(report["state_order"], list(STATES))
        self.assertEqual(report["actor_count"], 4)
        self.assertEqual(report["dyad_universe_count"], 12)
        period = report["periods"][0]
        self.assertEqual([[period["transition_counts"][a][b] for b in STATES] for a in STATES],
                         [[1, 1, 1], [1, 1, 1], [1, 1, 4]])
        self.assertEqual(period["known_overlap"], 4)
        self.assertEqual(period["observed_hamming_distance"], 2)
        self.assertEqual((period["observed_additions"], period["observed_removals"]), (1, 1))
        self.assertEqual((period["coverage_gained"], period["coverage_lost"], period["unknown_both"]), (2, 2, 4))
        self.assertEqual((period["observed_before"], period["observed_after"]), (6, 6))
        self.assertEqual((period["positive_count_before"], period["positive_count_after"]), (3, 3))
        self.assertEqual(report["graph_analyses"]["status"], "NOT_RUN")
        self.assertTrue(report["endpoint_comparison_only"])
        for flag in ("unknown_dyads_imputed", "source_claim_verified", "population_boundary_qualified",
                     "model_fitted", "causal_effect_identified"):
            self.assertFalse(report[flag])
        self.assertNotIn("actors", report)
        self.assertNotIn("edges", report)
        for actor in panel.actors:
            self.assertNotIn('"' + actor + '"', json.dumps(report, allow_nan=False))
        self.assert_accounting(report)

    def test_opposite_directions_are_distinct_observations(self):
        report = partial_panel_report(make_panel(
            before_present=(("A", "B"),), before_absent=(("B", "A"),),
            after_present=(("B", "A"),), after_absent=(("A", "B"),),
        ))
        period = report["periods"][0]
        self.assertEqual(period["observed_present_both"], 0)
        self.assertEqual(period["observed_absent_both"], 0)
        self.assertEqual(period["known_overlap"], 2)
        self.assertEqual(period["observed_hamming_distance"], 2)
        self.assertEqual((period["observed_additions"], period["observed_removals"]), (1, 1))
        self.assertEqual(period["positive_count_change"], 0)
        self.assertEqual(report["graph_analyses"]["status"], "NOT_RUN")
        self.assert_accounting(report)

    def test_unknown_present_exchanges_change_coverage_not_observed_ties(self):
        for before, after, difference in (((), (("A", "B"),), 1), ((("A", "B"),), (), -1)):
            with self.subTest(difference=difference):
                report = partial_panel_report(make_panel(before_present=before, after_present=after))
                period = report["periods"][0]
                self.assertEqual(period["known_overlap"], 0)
                self.assertEqual(period["observed_hamming_distance"], 0)
                self.assertEqual(period["observed_additions"], 0)
                self.assertEqual(period["observed_removals"], 0)
                self.assertEqual(period["positive_count_change"], difference)
                self.assertEqual(period["positive_net_change_decomposition"]["observed_additions_minus_removals"], 0)
                self.assertEqual(period["positive_net_change_decomposition"]["coverage_gained_present_minus_lost_present"], difference)
                self.assertEqual((period["coverage_gained"], period["coverage_lost"]),
                                 (1, 0) if difference == 1 else (0, 1))
                self.assert_accounting(report)

    def test_all_unknown_roster_has_no_fabricated_observations(self):
        actors = tuple(f"p{index:04d}" for index in range(500))
        report = partial_panel_report(make_panel(actors=actors))
        universe = 500 * 499
        self.assertEqual(report["dyad_universe_count"], universe)
        self.assertTrue(all(wave["state_counts"] == {"absent": 0, "present": 0, "unknown": universe}
                            for wave in report["waves"]))
        period = report["periods"][0]
        self.assertEqual(period["unknown_both"], universe)
        self.assertEqual(period["known_overlap"], 0)
        self.assertEqual(period["observed_hamming_distance"], 0)
        self.assertEqual((period["coverage_gained"], period["coverage_lost"]), (0, 0))
        self.assert_accounting(report)

    def test_known_absence_changes_hash_and_coverage_even_with_identical_positive_edges(self):
        unknown = make_panel(before_present=(("A", "B"),), after_present=(("A", "B"),))
        absent = make_panel(before_present=(("A", "B"),), after_present=(("A", "B"),), after_absent=(("B", "A"),))
        old, new = partial_panel_report(unknown), partial_panel_report(absent)
        self.assertNotEqual(old["dataset_hash"], new["dataset_hash"])
        self.assertEqual(old["periods"][0]["positive_count_change"], new["periods"][0]["positive_count_change"])
        period = new["periods"][0]
        self.assertEqual(period["transition_counts"]["unknown"]["absent"], 1)
        self.assertEqual(period["coverage_gained"], 1)
        self.assertEqual(period["observed_hamming_distance"], 0)
        self.assert_accounting(old)
        self.assert_accounting(new)

    def test_periods_preserve_all_declared_waves_revisions_and_time_gaps(self):
        data = make_panel(after_present=(("A", "B"),)).to_dict()
        data["waves"].append({"time_index": 9, "source_revision": "synthetic-source-w9",
                              "observed_present": [], "observed_absent": [["A", "B"]]})
        report = partial_panel_report(PartialNetworkPanel.from_mapping(data))
        self.assertEqual(report["wave_count"], 3)
        self.assertEqual([(row["before_time_index"], row["after_time_index"]) for row in report["periods"]], [(0, 2), (2, 9)])
        self.assertEqual([row["source_revision"] for row in report["waves"]],
                         ["synthetic-source-w0", "synthetic-source-w2", "synthetic-source-w9"])
        self.assertEqual([row["known_overlap"] for row in report["periods"]], [0, 1])
        self.assertEqual([row["observed_hamming_distance"] for row in report["periods"]], [0, 1])
        self.assert_accounting(report)

    def test_report_requires_the_validated_partial_panel_type(self):
        with self.assertRaisesRegex(TypeError, "PartialNetworkPanel"):
            partial_panel_report({})


if __name__ == "__main__":
    unittest.main()
