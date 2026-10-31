from pathlib import Path
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sociolab.communities import karate_community_report
from sociolab.cli import main
from sociolab.references import karate_club_report


class CommunityReferenceTest(unittest.TestCase):
    def test_actual_upstream_partition_and_modularity(self):
        with patch('networkx.community.greedy_modularity_communities', wraps=nx.community.greedy_modularity_communities) as algorithm:
            result = karate_community_report()
            algorithm.assert_called_once()
        self.assertEqual(result['engine'], 'networkx')
        self.assertEqual(result['kind'], 'REFERENCE_MODEL_RESULT')
        self.assertFalse(result['labels_used_for_detection'])
        self.assertTrue(result['historical_faction_labels_are_post_fission'])
        self.assertFalse(result['causal_effect_identified'])
        self.assertEqual(result['source_record_hash'], karate_club_report()['source_record_hash'])
        groups = [set(int(v) for v in item['actors']) for item in result['detected_communities']]
        self.assertEqual(set.union(*groups), set(range(34)))
        self.assertEqual(sum(len(x) for x in groups), 34)
        self.assertEqual(result['community_count'], len(groups))
        observed = [
            {n for n, attr in nx.karate_club_graph().nodes(data=True) if attr['club'] == label}
            for label in ('Mr. Hi', 'Officer')
        ]
        self.assertAlmostEqual(
            result['detected_modularity'],
            nx.community.modularity(nx.karate_club_graph(), groups, weight=None),
        )
        self.assertAlmostEqual(
            result['post_fission_observed_group_modularity'],
            nx.community.modularity(nx.karate_club_graph(), observed, weight=None),
        )
        for item in result['detected_communities']:
            self.assertEqual(sum(item['post_fission_group_counts'].values()), item['size'])

    def test_cli_uses_actual_upstream(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['communities']), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['algorithm'], 'networkx.community.greedy_modularity_communities')
        self.assertFalse(report['causal_effect_identified'])

    def test_fixed_reference_is_reproducible(self):
        a = karate_community_report()
        b = karate_community_report()
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
