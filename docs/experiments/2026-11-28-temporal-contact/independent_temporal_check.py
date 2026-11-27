#!/usr/bin/env python3
"""Independently check the reviewed log's temporal reachability aggregates.

Reads the original gzip TSV with the standard library and uses NetworkX
descendants on sparse (actor, time) graphs. It imports no SocioLab module and
does not use the production before/after graph representation. Source IDs,
ordered pairs and earliest-arrival maps remain in memory; outputs contain only
aggregate counts and content hashes.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import time

import networkx as nx


HERE = Path(__file__).resolve().parent
REVIEWED_PAYLOAD_SHA256 = "ed7fcc05f614cd47ffa230183ce2375af140fd13ca98a253d236f9ba043f695e"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return "sha256:" + sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def read_source(path):
    compressed = path.read_bytes()
    payload = gzip.decompress(compressed)
    if sha256(payload) != REVIEWED_PAYLOAD_SHA256:
        raise ValueError("Source payload differs from the reviewed official TSV")
    rows, actors, seen = [], set(), set()
    previous = 0
    reversed_rows = 0
    for values in csv.reader(io.StringIO(payload.decode("ascii")), delimiter="\t"):
        if len(values) != 3:
            raise ValueError("Source requires three TSV fields")
        time, first, second = map(int, values)
        if time <= 0 or time % 20 or time < previous or first == second:
            raise ValueError("Source has an invalid time, ordering or self-pair")
        previous = time
        reversed_rows += first > second
        low, high = sorted((first, second))
        row = (time, low, high)
        if row in seen:
            raise ValueError("Source contains a repeated undirected pair-bin")
        seen.add(row)
        rows.append(row)
        actors.update((low, high))
    if not rows:
        raise ValueError("The reviewed source cannot be empty")
    return tuple(rows), tuple(sorted(actors)), {
        "compressed_bytes": len(compressed), "compressed_sha256": sha256(compressed),
        "payload_bytes": len(payload), "payload_sha256": sha256(payload),
        "row_count": len(rows), "node_count": len(actors),
        "distinct_recorded_pairs": len({(a, b) for _, a, b in rows}),
        "first_bin_endpoint_seconds": rows[0][0], "last_bin_endpoint_seconds": rows[-1][0],
        "reversed_pair_order_rows_canonicalized": reversed_rows,
        "duplicate_rows_dropped": 0, "self_pairs_dropped": 0,
    }


def expand_actor_times(actors, records, start, end, strict):
    """Use distinct time points, never the production before/after states."""
    times = {actor: {start, end} for actor in actors}
    for endpoint, first, second in records:
        times[first].add(endpoint)
        times[second].add(endpoint)
        if strict:
            times[first].add(endpoint - 20)
            times[second].add(endpoint - 20)
    graph = nx.DiGraph()
    for actor in actors:
        ordered = sorted(times[actor])
        graph.add_nodes_from((actor, time) for time in ordered)
        graph.add_edges_from(((actor, before), (actor, after))
                             for before, after in zip(ordered, ordered[1:]))
    for endpoint, first, second in records:
        departure = endpoint - 20 if strict else endpoint
        graph.add_edge((first, departure), (second, endpoint))
        graph.add_edge((second, departure), (first, endpoint))
    return graph


def earliest_arrivals(actors, graph, start):
    """Project upstream reachable states to earliest target-bin endpoints."""
    arrivals = {}
    for source in actors:
        for target, endpoint in nx.descendants(graph, (source, start)):
            if target == source:
                continue
            pair = (source, target)
            if pair not in arrivals or endpoint < arrivals[pair]:
                arrivals[pair] = endpoint
    return arrivals


def mode_result(actors, records, start, end, strict, deadlines, static_pair_count):
    graph = expand_actor_times(actors, records, start, end, strict)
    arrivals = earliest_arrivals(actors, graph, start)
    elapsed = sorted(endpoint - start for endpoint in arrivals.values())
    possible = len(actors) * (len(actors) - 1)
    ordered_pairs = sorted(arrivals)
    triples = [(source, target, arrivals[(source, target)]) for source, target in ordered_pairs]
    mutual = sum((target, source) in arrivals for source, target in ordered_pairs) // 2
    one_way = len(arrivals) - 2 * mutual
    incidences = len({(actor, endpoint) for endpoint, first, second in records for actor in (first, second)})
    result = {
        "reachable_ordered_pairs": len(arrivals),
        "reachable_ordered_pair_fraction": len(arrivals) / possible if possible else None,
        "static_reachable_but_not_temporal_ordered_pairs": static_pair_count - len(arrivals),
        "mutually_reachable_unordered_pairs": mutual,
        "one_way_reachable_unordered_pairs": one_way,
        "unreachable_in_both_directions_unordered_pairs": math.comb(len(actors), 2) - mutual - one_way,
        "reachable_pair_identity_hash": fingerprint(ordered_pairs),
        "arrival_identity_hash": fingerprint(triples),
        "earliest_bin_endpoint_offset_seconds": {
            "reachable_pair_count": len(elapsed),
            "min": min(elapsed) if elapsed else None,
            "max": max(elapsed) if elapsed else None,
            "mean": statistics.mean(elapsed) if elapsed else None,
            "median": statistics.median(elapsed) if elapsed else None,
        },
        "deadlines": [{"seconds_from_window_start": deadline,
                       "reachable_ordered_pairs": sum(value <= deadline for value in elapsed),
                       "reachable_ordered_pair_fraction": sum(value <= deadline for value in elapsed) / possible if possible else None}
                      for deadline in deadlines],
        # Independent arithmetic for the published phase representation only.
        # Actual search above uses a different actor/time graph, whose sizes
        # are separately recorded and are never substituted for these values.
        "expanded_graph": {
            "node_count": 2 * len(actors) + 2 * incidences,
            "edge_count": len(actors) + (2 if strict else 3) * incidences + 2 * len(records),
        },
    }
    representation = {"node_count": graph.number_of_nodes(), "edge_count": graph.number_of_edges()}
    return result, arrivals, representation


def recompute(records, actors, protocol):
    computed = {"kind": "RECORDED_CONTACT_TEMPORAL_STUDY", "engine": "networkx",
                "engine_version": nx.__version__, "scenarios": []}
    independent_sizes = []
    for scenario in protocol["scenarios"]:
        windows = []
        minimum = scenario["minimum_bins_per_pair"]
        for index, (start, end) in enumerate(scenario["windows"]):
            raw = [row for row in records if start < row[0] <= end]
            counts = Counter((first, second) for _, first, second in raw)
            qualified_pairs = {pair for pair, count in counts.items() if count >= minimum}
            kept = [row for row in raw if row[1:] in qualified_pairs]
            static = nx.Graph()
            static.add_nodes_from(actors)
            static.add_edges_from(sorted(qualified_pairs))
            static_pairs = {(source, target)
                            for source, distances in nx.all_pairs_shortest_path_length(static)
                            for target in distances if source != target}
            strict, strict_arrivals, strict_size = mode_result(
                actors, kept, start, end, True, scenario["arrival_deadlines_seconds"], len(static_pairs))
            nonstrict, nonstrict_arrivals, nonstrict_size = mode_result(
                actors, kept, start, end, False, scenario["arrival_deadlines_seconds"], len(static_pairs))
            strict_pairs, nonstrict_pairs = set(strict_arrivals), set(nonstrict_arrivals)
            if not strict_pairs <= nonstrict_pairs <= static_pairs:
                raise ValueError("Independent temporal/static pair inclusion failed")
            if any(nonstrict_arrivals[pair] > endpoint for pair, endpoint in strict_arrivals.items()):
                raise ValueError("Relaxed mode has a later earliest endpoint for a strict-reachable pair")
            raw_actors = {actor for _, first, second in raw for actor in (first, second)}
            zero_degree = sum(degree == 0 for _, degree in static.degree())
            component_sizes = sorted((len(component) for component in nx.connected_components(static)), reverse=True)
            earlier = sum(nonstrict_arrivals[pair] < endpoint for pair, endpoint in strict_arrivals.items())
            windows.append({
                "window_index": index, "kind": "RECORDED_CONTACT_TEMPORAL_ANALYSIS",
                "engine": "networkx", "engine_version": nx.__version__,
                "actor_count": len(actors), "actor_universe_hash": fingerprint(actors),
                "possible_ordered_pairs": len(actors) * (len(actors) - 1),
                "window": {
                    "start_exclusive": start, "end_inclusive": end, "duration_seconds": end - start,
                    "minimum_bins_per_pair": minimum, "window_bin_count": len(raw),
                    "window_recorded_pair_count": len(counts),
                    "zero_record_node_count": len(actors) - len(raw_actors),
                    "qualifying_pair_bin_count": len(kept), "qualifying_recorded_pair_count": len(qualified_pairs),
                    "zero_qualifying_degree_node_count": zero_degree,
                    "excluded_below_threshold_pair_count": len(counts) - len(qualified_pairs),
                    "excluded_below_threshold_bin_count": len(raw) - len(kept),
                },
                "static": {
                    "reachable_ordered_pairs": len(static_pairs),
                    "reachable_ordered_pair_fraction": len(static_pairs) / (len(actors) * (len(actors) - 1)),
                    "reachable_pair_identity_hash": fingerprint(sorted(static_pairs)),
                    "component_count": len(component_sizes), "component_sizes": component_sizes,
                    "recorded_pair_count": len(qualified_pairs), "zero_qualifying_degree_node_count": zero_degree,
                },
                "strict": strict, "nonstrict": nonstrict,
                "comparison": {
                    "strict_subset_of_nonstrict": strict_pairs <= nonstrict_pairs,
                    "nonstrict_subset_of_static": nonstrict_pairs <= static_pairs,
                    "common_pair_nonstrict_arrival_no_later_than_strict": True,
                    "same_bin_rule_additional_reachable_ordered_pairs": len(nonstrict_pairs - strict_pairs),
                    "common_reachable_ordered_pairs": len(strict_pairs),
                    "common_pairs_arrive_earlier_with_nonstrict": earlier,
                    "common_pairs_same_arrival": len(strict_pairs) - earlier,
                },
                "scope": {"pair_filter_uses_later_window_records": minimum > 1},
            })
            independent_sizes.append({"scenario": scenario["name"], "window_index": index,
                                      "strict": strict_size, "nonstrict": nonstrict_size})
        computed["scenarios"].append({"scenario": scenario["name"], "minimum_bins_per_pair": minimum,
                                      "arrival_deadlines_seconds": scenario["arrival_deadlines_seconds"],
                                      "windows": windows})
    return computed, independent_sizes


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
        if type(actual) in (int, float) and type(expected) in (int, float):
            equal = math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
        else:
            equal = type(actual) is type(expected) and actual == expected
        if not equal:
            mismatches.append({"path": path, "computed": actual, "reported": expected})

    visit(computed, reported, "$")
    return {"aggregate_value_comparison_count": checks,
            "matched_comparison_count": checks - len(mismatches),
            "mismatch_count": len(mismatches), "mismatches": mismatches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-gzip", type=Path, required=True)
    parser.add_argument("--case-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    begin = time.perf_counter()
    protocol_bytes = (HERE / "protocol.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    if protocol["source_payload_sha256"] != REVIEWED_PAYLOAD_SHA256:
        raise ValueError("Protocol source identity differs from the reviewed payload")
    report_bytes = args.case_report.read_bytes()
    reported = json.loads(report_bytes)
    records, actors, source = read_source(args.raw_gzip)
    computed, sizes = recompute(records, actors, protocol)
    computed["source"] = {key: value for key, value in source.items()
                          if key not in {"first_bin_endpoint_seconds", "last_bin_endpoint_seconds"}}
    comparison = compare(computed, reported)
    output = {
        "kind": "INDEPENDENT_RECORDED_CONTACT_TEMPORAL_CHECK",
        "status": "PASS" if comparison["mismatch_count"] == 0 else "FAIL",
        "started_utc": started, "wall_time_seconds": time.perf_counter() - begin,
        "networkx_version": nx.__version__, "checker_sha256": sha256(Path(__file__).read_bytes()),
        "inputs": {"raw_gzip_name": args.raw_gzip.name,
                   "raw_gzip_sha256": source["compressed_sha256"],
                   "decompressed_tsv_sha256": source["payload_sha256"],
                   "case_report_name": args.case_report.name, "case_report_sha256": sha256(report_bytes),
                   "protocol_sha256": sha256(protocol_bytes)},
        "method": {
            "parser": "stdlib gzip, csv and Counter; exact reviewed decompressed payload required",
            "sociolab_imports": False,
            "path_engine": "original networkx.descendants on independently built actor/time DiGraphs",
            "strict_graph": "each contact u-v at endpoint t adds (u,t-20)->(v,t) and reverse; actor waiting arcs join successive retained time points",
            "nonstrict_graph": "each contact u-v at endpoint t adds (u,t)<->(v,t); actor waiting arcs join successive retained time points",
            "source_initialization": "one hypothetical source at window start per original actor; exclude self destinations",
            "earliest_arrival": "minimum reachable target-state timestamp; absolute endpoint hashes, offset summary/deadline arithmetic",
            "production_graph_size_check": "Independent actor/bin incidence arithmetic: nodes=2N+2I; edges=N+2I+2R strict, N+3I+2R nonstrict. These are not the checker representation sizes.",
            "static_engine": "original networkx.all_pairs_shortest_path_length; ordered nonself reachable destinations",
            "float_absolute_tolerance": 1e-12, "float_relative_tolerance": 1e-10,
            "comparison_count_definition": "selected scalar leaves and sequence lengths; excludes report-only interpretation fields",
        },
        "comparison": comparison,
        "independently_computed": computed,
        "independent_graph_sizes": sizes,
        "scope_limits": [
            "Both graph constructions use the same declared bin conventions and the original NetworkX dependency.",
            "The alternate sparse actor/time encoding checks the production phase encoding and aggregate arithmetic; it is not a second graph solver.",
            "Per-source availability at window start and unlimited waiting are assumptions, not observations of attendance or retained information.",
            "Whole-window multi-bin filtering retains early records of pairs qualifying from later records in the same window.",
            "Strict/nonstrict/static inclusion concerns these recorded-bin models, not physical or statistical bounds on real transmission.",
            "No sensor completeness, actual delivery, temporal community, temporal group centrality, forecast or causal effect is validated.",
            "Original IDs, ordered-pair lists, source rows and earliest-arrival maps remain in memory and are not exported.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"status": output["status"], "networkx_version": nx.__version__,
                      "aggregate_value_comparison_count": comparison["aggregate_value_comparison_count"],
                      "mismatch_count": comparison["mismatch_count"], "wall_time_seconds": output["wall_time_seconds"]}, sort_keys=True))
    return bool(comparison["mismatch_count"])


if __name__ == "__main__":
    raise SystemExit(main())
