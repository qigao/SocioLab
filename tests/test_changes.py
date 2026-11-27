import json
from pathlib import Path
import sys
import unittest

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sociolab.changes import compare_snapshots
from sociolab.snapshots import NetworkSnapshot, content_hash


def _record(record_id, fact_id, seq, *, operation="assert", supersedes=None):
    return {
        "record_id": record_id, "fact_id": fact_id, "source_system": "fixture",
        "operation": operation, "supersedes": supersedes,
        "kind": "relation.observed", "ingest_seq": seq,
    }


def _snapshot(
    persons, edges, *, at=1, directed=False, activities=None, absent=(),
    history=None, complete=True, dataset_id="dynamic-fixture", layer="cooperation",
    clock=None,
):
    """Synthetic snapshot inputs, validated by the actual snapshot contract."""
    history = [_record("r1", "f1", 1)] if history is None else history
    history = [{**_record("coverage", "coverage", 1), "kind": "coverage.observed"}] + [
        {**record, "ingest_seq": record["ingest_seq"] + 1} for record in history
    ]
    edges = [
        dict(edge) if isinstance(edge, dict) else {
            "source": edge[0], "target": edge[1], "strength": 1, "evidence": ["r1"],
        }
        for edge in edges
    ]
    bipartite = activities is not None
    view = {
        "schema": "sociolab.view.v1", "population": "test-population",
        "layer": "participation" if bipartite else layer,
        "mode": "participation" if bipartite else "state", "directed": directed,
        "actions": [], "roles": [], "topics": [],
    }
    view.update({"start": at, "end": at + 1} if bipartite else {"at": at})
    data = {
        "schema": "sociolab.snapshot.v1",
        "dataset": {
            "dataset_id": dataset_id, "origin": "synthetic", "source_revision": "export-1",
            "clock": clock or {"kind": "ticks", "run_id": "case"},
            "content_hash": content_hash({"fixture_history": history}),
            "known_records_hash": content_hash(history),
        },
        "view": view, "knowledge_cutoff": len(history),
        "directed": directed, "bipartite": bipartite,
        "persons": list(persons), "activities": list(activities or ()), "edges": edges,
        "coverage": {
            "complete": complete,
            "actors": {actor: "complete" if complete else "partial" for actor in persons},
            "evidence": ["coverage"],
        },
        "population": {
            "policy": "eligible_any_overlap" if bipartite else "eligible_at",
            "eligible": list(persons), "absent": list(absent), "unknown": [],
            "exposure": {actor: 1 for actor in persons},
        },
        "provenance": {
            "selected_records": sorted({"coverage"} | {record for edge in edges for record in edge["evidence"]}),
            "record_history": history,
        },
    }
    return NetworkSnapshot.create(data)


_PEOPLE = list("ABCDEF")
_TRIANGLES = [("A", "B"), ("A", "C"), ("B", "C"), ("D", "E"), ("D", "F"), ("E", "F")]


class ChangesTest(unittest.TestCase):
    def test_bridge_loss_preserves_partition_but_reduces_structural_access(self):
        before = _snapshot(_PEOPLE, _TRIANGLES + [("C", "D")])
        after = _snapshot(_PEOPLE, _TRIANGLES, at=2)
        report = compare_snapshots(before, after, algorithm="greedy", group_size=2)

        self.assertEqual(report["kind"], "DESCRIPTIVE_NETWORK_CHANGE")
        self.assertEqual(report["inputs"]["before"]["snapshot_hash"], before.content_hash)
        self.assertEqual(report["inputs"]["after"]["view"]["at"], 2)
        self.assertEqual(report["structure"]["before"]["bridges"], [["C", "D"]])
        self.assertEqual(set(report["structure"]["before"]["reachable_count"].values()), {5})
        self.assertEqual(set(report["structure"]["after"]["reachable_count"].values()), {2})
        self.assertEqual(report["structure"]["after"]["component_count"], 2)
        self.assertTrue(report["communities"]["lineage"]["membership_stability"]["same_partition"])
        self.assertEqual(report["communities"]["before"]["communities"], [list("ABC"), list("DEF")])
        self.assertEqual(report["key_groups"]["original"]["members"], ["C", "D"])
        self.assertAlmostEqual(report["key_groups"]["original"]["before"]["score"], 2 / 3)
        self.assertEqual(report["key_groups"]["original"]["after"]["score"], 0)
        self.assertEqual(report["key_groups"]["new_selection"]["reason"], "disconnected_group_selection_not_qualified")
        self.assertFalse(report["causal_effect_identified"])
        json.dumps(report, allow_nan=False)

    def test_source_corrections_and_retractions_preserve_edge_evidence(self):
        initial = [_record("r1", "f1", 1), _record("r2", "f2", 2)]
        revised = initial + [
            _record("r3", "f1", 3, supersedes="r1"),
            _record("r4", "f2", 4, operation="retract", supersedes="r2"),
            _record("r5", "f3", 5),
        ]
        before = _snapshot(list("ABC"), [
            {"source": "A", "target": "B", "strength": 1, "evidence": ["r1"]},
            {"source": "B", "target": "C", "strength": 1, "evidence": ["r2"]},
        ], history=initial)
        after = _snapshot(list("ABC"), [
            {"source": "A", "target": "B", "strength": 2, "evidence": ["r3"]},
            {"source": "A", "target": "C", "strength": 1, "evidence": ["r5"]},
        ], history=revised)
        report = compare_snapshots(before, after)

        source = report["source_changes"]
        self.assertEqual([r["record_id"] for r in source["new_records"]], ["r5"])
        self.assertEqual([r["record_id"] for r in source["corrected_records"]], ["r3"])
        self.assertEqual(source["corrected_records"][0]["supersedes"], "r1")
        self.assertEqual([r["record_id"] for r in source["retracted_records"]], ["r4"])
        self.assertEqual(source["selected_evidence_removed"], ["r1", "r2"])
        self.assertEqual(report["relations"]["reweighted"][0]["after"]["evidence"], ["r3"])
        self.assertEqual(report["relations"]["removed"][0]["evidence"], ["r2"])
        self.assertEqual(report["relations"]["added"][0]["evidence"], ["r5"])

    def test_evidence_replacement_is_not_a_topology_or_weight_change(self):
        before = _snapshot(list("ABC"), [("A", "B")])
        history = [_record("r1", "f1", 1), _record("r2", "f1", 2, supersedes="r1")]
        after = _snapshot(list("ABC"), [
            {"source": "A", "target": "B", "strength": 1, "evidence": ["r2"]},
        ], history=history)
        report = compare_snapshots(before, after)
        for field in ("added", "removed", "reweighted"):
            self.assertEqual(report["relations"][field], [])
        self.assertEqual(len(report["relations"]["evidence_changed"]), 1)
        self.assertEqual(report["structure"]["before"], report["structure"]["after"])

    def test_membership_change_keeps_original_group_unavailable_after_departure(self):
        before = _snapshot(list("ABCD"), [("A", "B"), ("B", "C"), ("C", "D")], absent=["E"])
        after = _snapshot(list("ABCE"), [("A", "B"), ("B", "C"), ("C", "E")], absent=["D"], at=2)
        report = compare_snapshots(before, after, group_members=["D", "A"])
        self.assertEqual(report["population"]["joined"], ["E"])
        self.assertEqual(report["population"]["left"], ["D"])
        self.assertEqual(report["population"]["common_observable"], list("ABC"))
        self.assertEqual(report["population"]["unknown_after"], [])
        original = report["key_groups"]["original"]
        self.assertEqual(original["members"], ["A", "D"])
        self.assertEqual(original["before"]["status"], "OK")
        self.assertEqual(original["after"], {"status": "UNAVAILABLE", "reason": "members_absent", "missing_members": ["D"]})
        self.assertEqual(report["key_groups"]["new_selection"]["status"], "OK")

    def test_newly_observed_person_is_not_assumed_to_have_joined(self):
        before = _snapshot(list("ABC"), [("A", "B")])
        after = _snapshot(list("ABCD"), [("A", "B")], at=2)
        report = compare_snapshots(before, after)
        self.assertEqual(report["population"]["eligible_added"], ["D"])
        self.assertEqual(report["population"]["joined"], [])
        self.assertEqual(report["population"]["newly_observed_eligible"], ["D"])

    def test_mismatched_policy_identity_and_missing_coverage_fail_explicitly(self):
        before = _snapshot(list("ABC"), [("A", "B")])
        cases = [
            (_snapshot(list("ABC"), [("A", "B")], layer="trust"), "view policy"),
            (_snapshot(list("ABC"), [("A", "B")], dataset_id="another"), "dataset identity"),
            (_snapshot(list("ABC"), [("A", "B")], clock={"kind": "ticks", "run_id": "another"}), "clock"),
            (_snapshot(list("ABC"), [("A", "B")], complete=False), "coverage"),
        ]
        for after, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    compare_snapshots(before, after)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            compare_snapshots(before, before, group_size=2, group_members=["A"])

    def test_directed_components_and_descendants_keep_edge_orientation(self):
        before = _snapshot(list("ABCD"), [("A", "B"), ("B", "C")], directed=True)
        after = _snapshot(list("ABCD"), [("B", "A"), ("B", "C")], directed=True, at=2)
        report = compare_snapshots(before, after, group_members=["B"])
        self.assertEqual(report["structure"]["before"]["out_reachable_count"], {"A": 2, "B": 1, "C": 0, "D": 0})
        self.assertEqual(report["structure"]["after"]["out_reachable_count"], {"A": 0, "B": 2, "C": 0, "D": 0})
        self.assertEqual(report["structure"]["after"]["weak_component_count"], 2)
        self.assertEqual(report["structure"]["after"]["strong_component_count"], 4)
        self.assertEqual(report["structure"]["after"]["isolates"], ["D"])
        self.assertIsNone(report["structure"]["after"]["bridges"])
        self.assertEqual(report["relations"]["removed"][0]["source"], "A")
        self.assertEqual(report["relations"]["added"][0]["source"], "B")
        self.assertEqual(report["key_groups"]["original"]["after"]["status"], "OK")
        self.assertEqual(report["key_groups"]["new_selection"]["reason"], "directed_group_selection_not_qualified")

    def test_real_partitions_retain_full_split_and_merge_lineage(self):
        clique = nx.complete_graph(_PEOPLE)
        before = _snapshot(_PEOPLE, list(clique.edges()))
        after = _snapshot(_PEOPLE, _TRIANGLES, at=2)
        split = compare_snapshots(before, after, algorithm="greedy")["communities"]["lineage"]
        merge = compare_snapshots(after, before, algorithm="greedy")["communities"]["lineage"]
        self.assertEqual(len(split["lineage"]), 2)
        self.assertTrue(all("split" in link["events"] for link in split["lineage"]))
        self.assertEqual(len(merge["lineage"]), 2)
        self.assertTrue(all("merge" in link["events"] for link in merge["lineage"]))
        self.assertFalse(split["membership_stability"]["same_partition"])

    def test_bipartite_defaults_preserve_incidence_without_person_analysis(self):
        before = _snapshot(_PEOPLE, [(p, "meeting") for p in _PEOPLE], activities=["meeting"])
        after = _snapshot(_PEOPLE, [(p, "meeting") for p in _PEOPLE[:-1]], activities=["meeting"], at=2)
        report = compare_snapshots(before, after, group_size=2)
        self.assertEqual(report["activities"]["before_incidence_count"], 6)
        self.assertEqual(report["activities"]["after_incidence_count"], 5)
        self.assertEqual(report["relations"]["removed"][0]["source"], "F")
        self.assertEqual(report["activities"]["before"]["projected_edges"], [])
        self.assertEqual(report["communities"]["before"]["status"], "NOT_RUN")
        self.assertEqual(report["key_groups"]["status"], "NOT_RUN")
        self.assertEqual(report["structure"]["before"]["status"], "NOT_RUN")
        self.assertFalse(report["derived_projection"])

    def test_requested_newman_projection_marks_derived_edges_and_skips_weighted_groups(self):
        before = _snapshot(_PEOPLE, [(p, "meeting") for p in _PEOPLE], activities=["meeting"])
        after = _snapshot(_PEOPLE, [(p, "meeting") for p in _PEOPLE[:-1]], activities=["meeting"], at=2)
        report = compare_snapshots(before, after, projection="newman", group_size=2)
        self.assertTrue(report["derived_projection"])
        self.assertEqual(report["analysis_relation"], "derived_co_participation")
        old_edges = report["activities"]["before"]["projected_edges"]
        self.assertEqual(len(old_edges), 15)
        self.assertEqual({e["strength"] for e in old_edges}, {0.2})
        self.assertEqual(old_edges[0]["activities"], ["meeting"])
        self.assertEqual(old_edges[0]["evidence"], ["r1"])
        delta = report["activities"]["projected_relation_changes"]
        self.assertEqual(len(delta["removed"]), 5)
        self.assertEqual(len(delta["reweighted"]), 10)
        self.assertEqual(report["structure"]["after"]["isolates"], ["F"])
        self.assertEqual(report["key_groups"]["original"]["before"]["reason"], "weighted_group_selection_not_qualified")

    def test_incidence_evidence_changes_preserve_person_activity_roles(self):
        before = _snapshot(["zoe"], [("zoe", "activity")], activities=["activity"])
        history = [_record("r1", "f1", 1), _record("r2", "f1", 2, supersedes="r1")]
        after = _snapshot(["zoe"], [
            {"source": "zoe", "target": "activity", "strength": 1, "evidence": ["r2"]},
        ], activities=["activity"], history=history)
        report = compare_snapshots(before, after, max_pairs=0)
        change = report["relations"]["evidence_changed"][0]
        self.assertEqual((change["source"], change["target"]), ("zoe", "activity"))
        self.assertEqual(change["after"]["evidence"], ["r2"])

    def test_empty_edges_are_reported_without_invented_modularity(self):
        snapshot = _snapshot(list("ABC"), [])
        report = compare_snapshots(snapshot, snapshot, group_size=1)
        self.assertEqual(report["structure"]["before"]["isolates"], list("ABC"))
        self.assertEqual(report["communities"]["before"]["status"], "NO_EDGES")
        self.assertIsNone(report["communities"]["before"]["modularity"])
        self.assertTrue(report["communities"]["lineage"]["membership_stability"]["same_partition"])
        self.assertEqual(report["key_groups"]["new_selection"]["status"], "NOT_RUN")
        json.dumps(report, allow_nan=False)

    def test_selection_budget_does_not_change_the_structural_population(self):
        snapshot = _snapshot(_PEOPLE, _TRIANGLES + [("C", "D")])
        report = compare_snapshots(snapshot, snapshot, group_size=2, max_nodes=5)
        self.assertEqual(report["structure"]["before"]["node_count"], 6)
        self.assertEqual(report["key_groups"]["new_selection"]["reason"], "group_selection_budget_exceeded")


if __name__ == "__main__":
    unittest.main()
