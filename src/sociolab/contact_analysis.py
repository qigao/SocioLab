"""Aggregate comparisons of archived 20-second proximity detections.

The graph describes qualifying records in a supplied artifact. An absent edge
does not establish absence of physical contact, attendance, or sensor coverage.
This module does not construct a completeness-qualified NetworkSnapshot.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from importlib.metadata import version
import json

import networkx as nx

from .communities import community_report, compare_communities
from .keyplayers import score_key_group, select_key_group


_SCENARIOS = (
    ("primary_10h", ((0, 36000), (86400, 122400)), 1),
    ("minimum_3_bins_10h", ((0, 36000), (86400, 122400)), 3),
    ("window_12h", ((0, 43200), (86400, 129600)), 1),
)
_COMMUNITY_SETTINGS = {"algorithm": "louvain", "seed": 0, "resolution": 1.0, "weight": None}


def _fingerprint(value) -> str:
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _validate(actors, records):
    if (type(actors) is not tuple or not actors
            or any(type(actor) is not int for actor in actors)
            or actors != tuple(sorted(set(actors)))):
        raise ValueError("contact analysis requires a nonempty sorted immutable integer actor universe")
    if type(records) is not tuple:
        raise ValueError("contact analysis requires immutable validated records")
    known, previous_time, seen = set(actors), 0, set()
    for record in records:
        if type(record) is not tuple or len(record) != 3 or any(type(value) is not int for value in record):
            raise ValueError("contact records must be integer endpoint/source/target tuples")
        endpoint, source, target = record
        if endpoint <= 0 or endpoint % 20 or endpoint < previous_time:
            raise ValueError("contact bin endpoints must be positive sorted multiples of 20 seconds")
        if source >= target or source not in known or target not in known or record in seen:
            raise ValueError("contact records require unique canonical nonself pairs in the actor universe")
        previous_time = endpoint
        seen.add(record)


def _graph(actors, counts, minimum_bins=1):
    graph = nx.Graph()
    graph.add_nodes_from(actors)
    graph.add_edges_from(sorted(pair for pair, count in counts.items() if count >= minimum_bins))
    return graph


def _window_counts(records, start, end):
    return Counter((source, target) for endpoint, source, target in records if start < endpoint <= end)


def _structure(graph):
    sizes = sorted((len(component) for component in nx.connected_components(graph)), reverse=True)
    count = len(graph)
    reachable = sum(size * (size - 1) // 2 for size in sizes)
    possible = count * (count - 1) // 2
    return {
        "actor_count": count, "binary_pair_count": graph.number_of_edges(),
        "component_count": len(sizes), "component_sizes": sizes,
        "zero_qualifying_degree_node_count": sum(1 for _ in nx.isolates(graph)),
        "reachable_unordered_pairs": reachable, "possible_unordered_pairs": possible,
        "reachable_unordered_pair_fraction": reachable / possible if possible else None,
        "mean_other_nodes_structurally_reachable": 2 * reachable / count,
        "bridge_count": sum(1 for _ in nx.bridges(graph)),
        "recorded_graph_density": nx.density(graph),
    }


def _community_summary(report):
    return {
        "status": report["status"], "community_count": report["community_count"],
        "community_sizes": [len(group) for group in report["communities"]],
        "singleton_community_count": sum(len(group) == 1 for group in report["communities"]),
        "multi_node_community_count": sum(len(group) > 1 for group in report["communities"]),
        "modularity": report["modularity"],
    }


def _community_comparison(before, after, actors):
    compared = compare_communities(before["communities"], after["communities"], observable=actors)
    overlap = [[0] * len(after["communities"]) for _ in before["communities"]]
    for row in compared["lineage"]:
        overlap[row["before_index"]][row["after_index"]] = row["overlap_count"]
    return {
        "comparison_universe": "all fixed artifact actor IDs; not a claim of complete sensor observation",
        "compared_actor_count": len(actors),
        "overlap_counts": overlap,
        "overlap_order": "rows and columns follow the reported before/after community sizes",
        "same_partition": compared["membership_stability"]["same_partition"],
        "matched_member_fraction": compared["membership_stability"]["matched_member_fraction"],
        "positive_overlap_count": len(compared["lineage"]),
        "lineage_link_counts": {
            name: sum(name in row["events"] for row in compared["lineage"])
            for name in ("continuation", "split", "merge")
        },
        "matched_community_count": len(compared["matches"]),
        "equal_weight_candidate_set_count": len(compared["matching_ambiguity"]["equal_weight_candidates"]),
        "unique_matching_optimum_assessed": False,
    }


def _pair_classes(pairs, baseline_membership, baseline_zero):
    pairs = set(pairs)
    cross = {pair for pair in pairs if baseline_membership[pair[0]] != baseline_membership[pair[1]]}
    touching = {pair for pair in cross if pair[0] in baseline_zero or pair[1] in baseline_zero}
    return {
        "total": len(pairs),
        "within_primary_baseline_community": len(pairs) - len(cross),
        "cross_primary_baseline_community": len(cross),
        "cross_touching_primary_baseline_zero_record_nodes": len(touching),
        "cross_between_primary_baseline_nonzero_record_nodes": len(cross) - len(touching),
    }


def _cross_counts(counts, baseline_membership, baseline_zero):
    pair_counts = _pair_classes(counts, baseline_membership, baseline_zero)
    cross = {pair: count for pair, count in counts.items()
             if baseline_membership[pair[0]] != baseline_membership[pair[1]]}
    touching = {pair: count for pair, count in cross.items()
                if pair[0] in baseline_zero or pair[1] in baseline_zero}
    return {
        "pair_counts": pair_counts,
        "bin_counts": {
            "total": sum(counts.values()),
            "within_primary_baseline_community": sum(counts.values()) - sum(cross.values()),
            "cross_primary_baseline_community": sum(cross.values()),
            "cross_touching_primary_baseline_zero_record_nodes": sum(touching.values()),
            "cross_between_primary_baseline_nonzero_record_nodes": sum(cross.values()) - sum(touching.values()),
        },
        "primary_baseline_zero_record_nodes_touched_by_qualifying_cross_pairs": len(
            {actor for pair in touching for actor in pair if actor in baseline_zero}),
    }


def _select_reference_group(graph):
    if len(graph) < 4:
        reason = "two_person_group_requires_at_least_two_outside_nodes"
    elif len(graph) > 200 or graph.number_of_edges() > 3000:
        reason = "declared_full_archive_selection_budget_exceeded"
    elif not nx.is_connected(graph):
        reason = "full_archive_graph_is_disconnected"
    else:
        selected = select_key_group(graph, 2, max_nodes=200, max_edges=3000)
        members = tuple(selected["members"])
        return members, {
            "status": "OK", "group_size": 2, "identity_hash": _fingerprint(members),
            "full_archive_score": selected["score"],
            "upstream_selection_score_rounded": selected["selection_score_rounded"],
        }
    return None, {"status": "NOT_RUN", "reason": reason, "group_size": 2, "identity_hash": None}


def _score_reference_group(graph, members, selection):
    if members is None:
        return {"status": "NOT_RUN", "reason": "full_archive_reference_group_unavailable", "identity_hash": None}
    result = score_key_group(graph, members)
    return {
        "status": result["status"], "identity_hash": selection["identity_hash"],
        "same_members_as_full_archive_selection": True,
        "score": result["score"], "outside_node_count": result["outside_node_count"],
        "members_with_qualifying_records": sum(graph.degree(member) > 0 for member in members),
        "zero_qualifying_degree_member_count": sum(graph.degree(member) == 0 for member in members),
        "member_qualifying_degree_sum": sum(graph.degree(member) for member in members),
    }


def recorded_contact_analysis(
    actors: tuple[int, ...], records: tuple[tuple[int, int, int], ...],
) -> dict:
    """Analyze three predeclared window/threshold scenarios; export aggregates.

    Actors are the fixed, retrospectively observed artifact universe. Records
    are unique canonical (20-second bin endpoint, lower ID, higher ID) tuples.
    Full-artifact group selection is explicitly retrospective, performed once,
    and followed by scoring exactly that group in every scenario/window.
    """
    _validate(actors, records)
    archive_counts = Counter((source, target) for _, source, target in records)
    archive_graph = _graph(actors, archive_counts)
    members, selection = _select_reference_group(archive_graph)

    primary_counts = _window_counts(records, *_SCENARIOS[0][1][0])
    primary_graph = _graph(actors, primary_counts)
    primary_community = community_report(primary_graph, **_COMMUNITY_SETTINGS)
    baseline_membership = {actor: index for index, community in enumerate(primary_community["communities"])
                           for actor in community}
    baseline_zero = set(nx.isolates(primary_graph))
    partition_hash = _fingerprint(primary_community["communities"])
    scenarios = []
    for name, intervals, minimum_bins in _SCENARIOS:
        window_reports, communities, qualified_counts = [], [], []
        for index, (start, end) in enumerate(intervals):
            raw_counts = _window_counts(records, start, end)
            counts = Counter({pair: count for pair, count in raw_counts.items() if count >= minimum_bins})
            graph = _graph(actors, counts)
            detected = primary_community if name == "primary_10h" and index == 0 else community_report(graph, **_COMMUNITY_SETTINGS)
            recorded_nodes = {actor for pair in raw_counts for actor in pair}
            window_reports.append({
                "window_index": index, "start_exclusive": start, "end_inclusive": end,
                "duration_seconds": end - start,
                "window_bin_count": sum(raw_counts.values()),
                "window_recorded_pair_count": len(raw_counts),
                "zero_record_node_count": len(actors) - len(recorded_nodes),
                "qualifying_pair_bin_count": sum(counts.values()),
                "excluded_below_threshold_pair_count": len(raw_counts) - len(counts),
                "excluded_below_threshold_bin_count": sum(raw_counts.values()) - sum(counts.values()),
                "structure": _structure(graph), "communities": _community_summary(detected),
                "fixed_primary_baseline_cross_groups": _cross_counts(counts, baseline_membership, baseline_zero),
                "fixed_reference_group": _score_reference_group(graph, members, selection),
            })
            communities.append(detected)
            qualified_counts.append(counts)
        old, new = set(qualified_counts[0]), set(qualified_counts[1])
        changes = {"recorded_pair_gained": new - old, "recorded_pair_lost": old - new,
                   "recorded_pair_retained": old & new}
        scenarios.append({
            "scenario": name, "minimum_bins_per_pair": minimum_bins,
            "threshold_meaning": "cumulative qualifying 20-second records within the window; continuity is not required",
            "fixed_primary_baseline_partition_hash": partition_hash,
            "windows": window_reports,
            "pair_changes": {key: _pair_classes(pairs, baseline_membership, baseline_zero)
                             for key, pairs in changes.items()},
            "community_comparison": _community_comparison(communities[0], communities[1], actors),
        })

    return {
        "kind": "RECORDED_CONTACT_WINDOW_ANALYSIS", "engine": "networkx",
        "engine_version": version("networkx"),
        "measurement_basis": "archived 20-second proximity detections",
        "actor_universe": {
            "count": len(actors), "identity_hash": _fingerprint(actors),
            "meaning": "fixed retrospectively observed artifact IDs; not a verified attendance or enrolled-population roster",
            "all_ids_retained_in_every_window": True,
        },
        "settings": {
            "bin_seconds": 20, "window_rule": "start < recorded_bin_endpoint <= end",
            "graph": "simple undirected unit topology of qualifying recorded pairs",
            "community": dict(_COMMUNITY_SETTINGS),
            "cross_group_partition": "primary_10h first-window partition, held fixed for every scenario",
            "group_selection": {"size": 2, "max_nodes": 200, "max_edges": 3000},
        },
        "full_archive": {"bin_count": len(records), **_structure(archive_graph)},
        "primary_baseline": {
            "partition_hash": partition_hash, "zero_record_node_count": len(baseline_zero),
            "communities": _community_summary(primary_community),
        },
        "reference_group": {
            **selection, "selection_scope": "all supplied archive records, including records outside comparison windows",
            "selection_algorithm": "networkx.prominent_group(greedy=True)",
            "objective": "normalized_unweighted_group_betweenness",
            "hindsight": True, "selection_decision_count": 1,
            "upstream_selection_call_count": int(members is not None),
            "selected_once": members is not None, "baseline_optimal_claim": False,
            "global_optimum_claim": False, "future_prediction": False,
        },
        "scenarios": scenarios,
        "scope": {
            "absence_meaning": "no recorded pair meeting the declared window and bin-count threshold; not verified absence of physical contact",
            "zero_record_degree_meaning": "no logged contact in this window; not established absence, departure, or social isolation",
            "pair_change_meaning": "changes between qualifying recorded-pair sets; not relationship formation or dissolution",
            "reachability_meaning": "static potential in an aggregated recorded graph; not time-respecting or actual transmission",
            "group_score_meaning": "structural position of a retrospective reference group; not social influence or an intervention effect",
            "cross_group_meaning": "between primary baseline algorithmic communities, with baseline zero-record nodes separated",
            "sensor_coverage_verified": False, "physical_contact_observation_complete": None,
            "source_claim_verified": False, "causal_effect_identified": False,
            "future_prediction": False, "time_respecting_transmission_validated": False,
            "row_level_records_exported": False,
        },
    }
