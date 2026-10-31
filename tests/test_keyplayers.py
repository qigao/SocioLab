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
        self.assertEqual(report['selected_actor_ids'], ['0', '33'])
        self.assertAlmostEqual(report['upstream_group_betweenness'], 0.6845574116743472)
        self.assertEqual(report['upstream_selection_score'], 0.68)
        self.assertFalse(report['global_optimum_claim'])
        self.assertEqual(report['source_record_hash'], karate_club_report()['source_record_hash'])

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
