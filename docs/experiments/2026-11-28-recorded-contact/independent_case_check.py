#!/usr/bin/env python3
"""Independently check aggregate recorded-contact results from the original TSV.

Requires NetworkX; imports no SocioLab code. Only aggregate values and content
hashes are written. Actor IDs, selected members, and pair lists stay in memory.

Example (from the repository root):
    python docs/experiments/2026-11-28-recorded-contact/independent_case_check.py \
        --raw-gzip /path/to/ht2009_contact_list.dat.gz \
        --case-report docs/experiments/2026-11-28-recorded-contact/case-report.json \
        --output docs/experiments/2026-11-28-recorded-contact/case-verification.json
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path

import networkx as nx


REVIEWED_PAYLOAD_SHA256 = "ed7fcc05f614cd47ffa230183ce2375af140fd13ca98a253d236f9ba043f695e"
SCENARIOS = (
    ("primary_10h", ((0, 36000), (86400, 122400)), 1),
    ("minimum_3_bins_10h", ((0, 36000), (86400, 122400)), 3),
    ("window_12h", ((0, 43200), (86400, 129600)), 1),
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return "sha256:" + sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def read_source(path):
    compressed = path.read_bytes()
    payload = gzip.decompress(compressed)
    if sha256(payload) != REVIEWED_PAYLOAD_SHA256:
        raise ValueError("Source payload differs from the reviewed official TSV")
    records, seen, actors = [], set(), set()
    reversed_rows = 0
    for fields in csv.reader(io.StringIO(payload.decode("ascii")), delimiter="\t"):
        if len(fields) != 3:
            raise ValueError("Expected exactly three TSV columns")
        endpoint, first, second = map(int, fields)
        if endpoint <= 0 or endpoint % 20 or first == second:
            raise ValueError("Source contains an invalid bin or self pair")
        reversed_rows += first > second
        pair = tuple(sorted((first, second)))
        row = (endpoint, *pair)
        if row in seen:
            raise ValueError("Source contains a duplicate unordered pair-bin")
        records.append(row)
        seen.add(row)
        actors.update(pair)
    if not records:
        raise ValueError("Source is empty")
    return records, sorted(actors), {
        "compressed_bytes": len(compressed),
        "compressed_sha256": sha256(compressed),
        "payload_bytes": len(payload),
        "payload_sha256": sha256(payload),
        "row_count": len(records),
        "node_count": len(actors),
        "distinct_recorded_pairs": len({(a, b) for _, a, b in records}),
        "first_bin_endpoint_seconds": min(t for t, _, _ in records),
        "last_bin_endpoint_seconds": max(t for t, _, _ in records),
        "reversed_pair_order_rows_canonicalized": reversed_rows,
        "duplicate_rows_dropped": 0,
        "self_pairs_dropped": 0,
    }


def make_graph(actors, pairs):
    graph = nx.Graph()
    graph.add_nodes_from(actors)
    graph.add_edges_from(sorted(pairs))
    return graph


def structure(graph):
    n = len(graph)
    sizes = sorted(map(len, nx.connected_components(graph)), reverse=True)
    # Count actual BFS-reachable destinations independently of the report's
    # connected-component size formula; paths remain static, not temporal.
    ordered_reachable = sum(len(lengths) - 1 for _, lengths in nx.all_pairs_shortest_path_length(graph))
    if ordered_reachable % 2:
        raise ValueError("Undirected reachability must have symmetric counts")
    reachable = ordered_reachable // 2
    possible = math.comb(n, 2)
    return {
        "actor_count": n,
        "binary_pair_count": graph.number_of_edges(),
        "component_count": len(sizes),
        "component_sizes": sizes,
        "zero_qualifying_degree_node_count": sum(degree == 0 for _, degree in graph.degree()),
        "reachable_unordered_pairs": reachable,
        "possible_unordered_pairs": possible,
        "reachable_unordered_pair_fraction": reachable / possible,
        "mean_other_nodes_structurally_reachable": ordered_reachable / n,
        "bridge_count": sum(1 for _ in nx.bridges(graph)),
        "recorded_graph_density": nx.density(graph),
    }


def partition(graph):
    groups = nx.community.louvain_communities(graph, weight=None, resolution=1.0, seed=0)
    return sorted((sorted(group) for group in groups), key=tuple)


def community_summary(graph, groups):
    sizes = [len(group) for group in groups]
    return {
        "status": "OK",
        "community_count": len(groups),
        "community_sizes": sizes,
        "singleton_community_count": sizes.count(1),
        "multi_node_community_count": sum(size > 1 for size in sizes),
        "modularity": nx.community.modularity(graph, groups, weight=None, resolution=1.0),
    }


def group_score(graph, members):
    return nx.group_betweenness_centrality(
        graph, members, normalized=True, weight=None, endpoints=False,
    )


def classify(counts, memberships, baseline_zero):
    result = dict.fromkeys((
        "total", "within_primary_baseline_community", "cross_primary_baseline_community",
        "cross_touching_primary_baseline_zero_record_nodes",
        "cross_between_primary_baseline_nonzero_record_nodes",
    ), 0)
    for (first, second), amount in counts.items():
        result["total"] += amount
        if memberships[first] == memberships[second]:
            result["within_primary_baseline_community"] += amount
        else:
            result["cross_primary_baseline_community"] += amount
            suffix = (
                "cross_touching_primary_baseline_zero_record_nodes"
                if first in baseline_zero or second in baseline_zero
                else "cross_between_primary_baseline_nonzero_record_nodes"
            )
            result[suffix] += amount
    return result


def recompute(records, actors, source):
    archive_counts = Counter((a, b) for _, a, b in records)
    archive = make_graph(actors, archive_counts)
    if not nx.is_connected(archive) or len(archive) > 200 or archive.number_of_edges() > 3000:
        raise ValueError("Archive is outside the declared reference-group selection scope")
    rounded_score, selected = nx.prominent_group(
        archive, 2, C=None, greedy=True, normalized=True, weight=None, endpoints=False,
    )
    members = sorted(selected)
    if len(members) != 2 or len(set(members)) != 2 or not set(members) <= set(actors):
        raise ValueError("Native NetworkX selected an invalid reference group")
    group_hash = fingerprint(members)
    baseline_counts = Counter((a, b) for t, a, b in records if 0 < t <= 36000)
    baseline = make_graph(actors, baseline_counts)
    baseline_partition = partition(baseline)
    partition_hash = fingerprint(baseline_partition)
    memberships = {actor: index for index, group in enumerate(baseline_partition) for actor in group}
    baseline_zero = set(nx.isolates(baseline))
    computed = {
        "source": source,
        "analysis": {
            "engine": "networkx", "engine_version": nx.__version__,
            "actor_universe": {"count": len(actors), "identity_hash": fingerprint(actors)},
            "full_archive": {"bin_count": len(records), **structure(archive)},
            "primary_baseline": {
                "partition_hash": partition_hash, "zero_record_node_count": len(baseline_zero),
                "communities": community_summary(baseline, baseline_partition),
            },
            "reference_group": {
                "status": "OK", "group_size": len(members), "identity_hash": group_hash,
                "full_archive_score": group_score(archive, members),
                "upstream_selection_score_rounded": float(rounded_score),
            },
            "scenarios": [],
        },
    }
    for name, bounds, minimum in SCENARIOS:
        windows, pair_sets = [], []
        for index, (start, end) in enumerate(bounds):
            all_counts = Counter((a, b) for t, a, b in records if start < t <= end)
            qualified = {pair: count for pair, count in all_counts.items() if count >= minimum}
            graph = make_graph(actors, qualified)
            groups = partition(graph)
            recorded = {actor for pair in all_counts for actor in pair}
            touched_zero = {
                actor for pair in qualified if memberships[pair[0]] != memberships[pair[1]]
                for actor in pair if actor in baseline_zero
            }
            member_degrees = [graph.degree(member) for member in members]
            windows.append({
                "window_index": index, "start_exclusive": start, "end_inclusive": end,
                "duration_seconds": end - start,
                "window_bin_count": sum(all_counts.values()),
                "window_recorded_pair_count": len(all_counts),
                "zero_record_node_count": len(actors) - len(recorded),
                "qualifying_pair_bin_count": sum(qualified.values()),
                "excluded_below_threshold_pair_count": len(all_counts) - len(qualified),
                "excluded_below_threshold_bin_count": sum(all_counts.values()) - sum(qualified.values()),
                "structure": structure(graph),
                "communities": community_summary(graph, groups),
                "fixed_primary_baseline_cross_groups": {
                    "pair_counts": classify(dict.fromkeys(qualified, 1), memberships, baseline_zero),
                    "bin_counts": classify(qualified, memberships, baseline_zero),
                    "primary_baseline_zero_record_nodes_touched_by_qualifying_cross_pairs": len(touched_zero),
                },
                "fixed_reference_group": {
                    "status": "OK", "identity_hash": group_hash,
                    "same_members_as_full_archive_selection": True,
                    "score": group_score(graph, members),
                    "outside_node_count": len(actors) - len(members),
                    "members_with_qualifying_records": sum(degree > 0 for degree in member_degrees),
                    "zero_qualifying_degree_member_count": member_degrees.count(0),
                    "member_qualifying_degree_sum": sum(member_degrees),
                },
            })
            pair_sets.append(set(qualified))
        before, after = pair_sets
        changes = {
            label: classify(dict.fromkeys(pairs, 1), memberships, baseline_zero)
            for label, pairs in (
                ("recorded_pair_gained", after - before),
                ("recorded_pair_lost", before - after),
                ("recorded_pair_retained", before & after),
            )
        }
        computed["analysis"]["scenarios"].append({
            "scenario": name, "minimum_bins_per_pair": minimum,
            "fixed_primary_baseline_partition_hash": partition_hash,
            "windows": windows, "pair_changes": changes,
        })
    return computed


def compare(computed, reported):
    checks, mismatches = 0, []

    def visit(actual, expected, path):
        nonlocal checks
        if isinstance(actual, dict) and isinstance(expected, dict):
            for key, value in actual.items():
                if key not in expected:
                    checks += 1
                    mismatches.append({"path": path + "." + key, "reason": "missing_report_field"})
                else:
                    visit(value, expected[key], path + "." + key)
            return
        if isinstance(actual, list) and isinstance(expected, list):
            visit(len(actual), len(expected), path + ".length")
            for index, (left, right) in enumerate(zip(actual, expected)):
                visit(left, right, f"{path}[{index}]")
            return
        checks += 1
        if isinstance(actual, float) and type(expected) in (int, float):
            equal = math.isfinite(expected) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
        else:
            equal = type(actual) is type(expected) and actual == expected
        if not equal:
            # All compared paths are selected aggregate fields; raw identities
            # and member/pair arrays are never supplied to this comparator.
            mismatches.append({"path": path, "computed": actual, "reported": expected})

    visit(computed, reported, "$")
    return {"aggregate_value_comparison_count": checks,
            "matched_comparison_count": checks - len(mismatches),
            "mismatch_count": len(mismatches), "mismatches": mismatches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-gzip", required=True, type=Path)
    parser.add_argument("--case-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report_bytes = args.case_report.read_bytes()
    report = json.loads(report_bytes)
    records, actors, source = read_source(args.raw_gzip)
    computed = recompute(records, actors, source)
    comparison = compare(computed, report)
    output = {
        "kind": "INDEPENDENT_RECORDED_CONTACT_AGGREGATE_CHECK",
        "status": "PASS" if not comparison["mismatch_count"] else "FAIL",
        "networkx_version": nx.__version__,
        "checker_sha256": sha256(Path(__file__).read_bytes()),
        "inputs": {
            "raw_gzip_name": args.raw_gzip.name,
            "raw_gzip_sha256": source["compressed_sha256"],
            "decompressed_tsv_sha256": source["payload_sha256"],
            "case_report_name": args.case_report.name,
            "case_report_sha256": sha256(report_bytes),
        },
        "method": {
            "parser": "stdlib gzip, csv and Counter; all original TSV rows checked",
            "sociolab_imports": False,
            "native_networkx_algorithms": [
                "connected_components", "all_pairs_shortest_path_length", "bridges",
                "community.louvain_communities", "community.modularity",
                "prominent_group", "group_betweenness_centrality",
            ],
            "canonical_order": "ascending original integer node IDs and unordered pairs",
            "community_settings": {"seed": 0, "resolution": 1.0, "weight": None},
            "reference_group_selection_calls": 1,
            "group_score_calls": 7,
            "group_scoring": {"normalized": True, "weight": None, "endpoints": False},
            "float_absolute_tolerance": 1e-12, "float_relative_tolerance": 1e-10,
            "comparison_count_definition": "selected scalar leaves and sequence lengths; excludes report-only fields",
        },
        "comparison": comparison,
        "independently_computed": computed,
        "scope_limits": [
            "Checks the declared recorded-contact graph calculation, not sensor completeness, attendance, or social ties.",
            "The actor universe and fixed reference group use the entire archive retrospectively.",
            "Zero graph degree is not asserted to be true social or physical isolation.",
            "Reachability counts static paths, not time-respecting contact paths.",
            "Native NetworkX is a shared dependency; this is an independent integration and arithmetic check, not a second algorithm implementation.",
            "Community matching, lineage narrative, causal effects, predictive validity and population inference are outside this check.",
            "No actor IDs, selected group members, raw rows or pair lists are exported.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"status": output["status"], "networkx_version": nx.__version__,
                      "aggregate_value_comparison_count": comparison["aggregate_value_comparison_count"],
                      "mismatch_count": comparison["mismatch_count"]}, sort_keys=True))
    return bool(comparison["mismatch_count"])


if __name__ == "__main__":
    raise SystemExit(main())
