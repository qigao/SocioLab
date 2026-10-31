from pathlib import Path
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sociolab.cli import main
from sociolab.keyplayers import karate_keyplayers_report
from sociolab.references import karate_club_report


class UpstreamKeyPlayerTest(unittest.TestCase):
    def test_real_upstream_group_selection(self):
        with patch('networkx.prominent_group', wraps=nx.prominent_group) as original:
            report = karate_keyplayers_report(2)
            original.assert_called_once()
        self.assertEqual(report['engine'], 'networkx')
        self.assertEqual(report['kind'], 'REFERENCE_MODEL_RESULT')
        self.assertFalse(report['directed'])
        self.assertEqual(report['relation'], 'undirected_observed_social_interaction')
        selected = [int(actor) for actor in report['selected_actor_ids']]
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(set(selected)), 2)
        self.assertTrue(all(actor in nx.karate_club_graph() for actor in selected))
        # The 3.7 release contains upstream fixes that can change scores:
        # validate against the *same installed upstream version*, not 3.6.1
        # golden outputs. Never replace either algorithm with local code.
        independently_measured = nx.group_betweenness_centrality(
            nx.karate_club_graph(), selected, normalized=True, weight=None,
        )
        self.assertAlmostEqual(report['upstream_group_betweenness'], independently_measured)
        self.assertLess(abs(report['upstream_selection_score'] - independently_measured), 0.011)
        self.assertGreaterEqual(independently_measured, 0)
        self.assertLessEqual(independently_measured, 1)
        self.assertFalse(report['global_optimum_claim'])
        self.assertEqual(report['source_record_hash'], karate_club_report()['source_record_hash'])

    def test_singleton_group_is_same_as_upstream_node_betweenness(self):
        report = karate_keyplayers_report(1)
        actor = int(report['selected_actor_ids'][0])
        self.assertAlmostEqual(
            report['upstream_group_betweenness'],
            nx.betweenness_centrality(nx.karate_club_graph())[actor],
        )

    def test_reject_invalid_group_sizes_before_invoking_upstream(self):
        for size in (0, 5, -1, True, 1.0, None):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    karate_keyplayers_report(size)

    def test_cli_calls_upstream_and_prints_typed_report(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['keyplayers', '--size', '1']), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['selected_actor_ids'], ['0'])
        self.assertEqual(report['group_size'], 1)
        self.assertFalse(report['global_optimum_claim'])


if __name__ == '__main__':
    unittest.main()
