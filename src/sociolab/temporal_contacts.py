"""Recorded-bin path comparisons through original NetworkX reachability.

Sparse before/after states express two declared within-bin rules. The input
records remain observations; waiting and a hypothetical signal available to
each source at the window start are analytical assumptions. No observed
transmission, population completeness, or continuous delay is established.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from hashlib import sha256
from importlib.metadata import version
import json
from statistics import fmean, median

import networkx as nx

from .contact_analysis import _validate


_MAX_ACTORS = 200
_MAX_INPUT_ROWS = 50_000
_MAX_EXPANDED_NODES = 200_000
_MAX_EXPANDED_EDGES = 400_000
_START, _BEFORE, _AFTER, _END = range(4)


def _fingerprint(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _fraction(numerator, denominator):
    return numerator / denominator if denominator else None


def _validate_request(actors, records, start, end, minimum_bins, deadlines):
    if type(actors) is tuple and len(actors) > _MAX_ACTORS:
        raise ValueError("temporal analysis exceeds the actor budget")
    if type(records) is tuple and len(records) > _MAX_INPUT_ROWS:
        raise ValueError("temporal analysis exceeds the total input record budget")
    _validate(actors, records)
    if (type(start) is not int or type(end) is not int
            or start < 0 or end <= start or start % 20 or end % 20):
        raise ValueError("temporal window requires nonnegative aligned 20-second boundaries with end > start")
    if type(minimum_bins) is not int or minimum_bins < 1:
        raise ValueError("minimum_bins must be a positive integer")
    if (type(deadlines) is not tuple
            or any(type(value) is not int or not 0 <= value <= end - start for value in deadlines)
            or deadlines != tuple(sorted(set(deadlines)))):
        raise ValueError("deadlines_seconds must be a strictly increasing tuple of integer offsets within the window")


def _expanded_sizes(actor_count, incident_count, record_count):
    nodes = 2 * actor_count + 2 * incident_count
    strict_edges = actor_count + 2 * incident_count + 2 * record_count
    nonstrict_edges = strict_edges + incident_count
    if nodes > _MAX_EXPANDED_NODES:
        raise ValueError("temporal state expansion exceeds the node budget")
    if max(strict_edges, nonstrict_edges) > _MAX_EXPANDED_EDGES:
        raise ValueError("temporal state expansion exceeds the edge budget")
    return nodes, strict_edges, nonstrict_edges


def _strict_graph(actors, records, times_by_actor, start, end):
    graph = nx.DiGraph()
    for actor in actors:
        source = (actor, start, _START)
        terminal = (actor, end, _END)
        graph.add_nodes_from((source, terminal))
        previous = source
        for endpoint in sorted(times_by_actor[actor]):
            before, after = (actor, endpoint, _BEFORE), (actor, endpoint, _AFTER)
            graph.add_edge(previous, before)
            graph.add_edge(before, after)
            previous = after
        graph.add_edge(previous, terminal)
    for endpoint, source, target in records:
        graph.add_edge((source, endpoint, _BEFORE), (target, endpoint, _AFTER))
        graph.add_edge((target, endpoint, _BEFORE), (source, endpoint, _AFTER))
    return graph


def _arrival_endpoints(graph, actors, start):
    arrivals = {}
    for source in actors:
        reachable = nx.single_source_shortest_path_length(graph, (source, start, _START))
        earliest = {}
        # Dictionary keys are reachable states. BFS hop counts are not time.
        for target, endpoint, phase in reachable:
            if phase == _AFTER and target != source:
                if target not in earliest or endpoint < earliest[target]:
                    earliest[target] = endpoint
        arrivals.update(((source, target), endpoint) for target, endpoint in earliest.items())
    return arrivals


def _mode_summary(graph, arrivals, static_pairs, actor_count, start, deadlines, rule):
    pairs = set(arrivals)
    possible = actor_count * (actor_count - 1)
    mutual = sum((target, source) in pairs for source, target in pairs) // 2
    one_way = len(pairs) - 2 * mutual
    offsets = sorted(endpoint - start for endpoint in arrivals.values())
    deadline_counts = [(deadline, bisect_right(offsets, deadline)) for deadline in deadlines]
    return {
        "rule": rule,
        "reachable_ordered_pairs": len(pairs),
        "reachable_ordered_pair_fraction": _fraction(len(pairs), possible),
        "static_reachable_but_not_temporal_ordered_pairs": len(static_pairs - pairs),
        "mutually_reachable_unordered_pairs": mutual,
        "one_way_reachable_unordered_pairs": one_way,
        "unreachable_in_both_directions_unordered_pairs": possible // 2 - mutual - one_way,
        "earliest_bin_endpoint_offset_seconds": {
            "reachable_pair_count": len(offsets),
            "min": min(offsets) if offsets else None,
            "median": median(offsets) if offsets else None,
            "mean": fmean(offsets) if offsets else None,
            "max": max(offsets) if offsets else None,
        },
        "deadlines": [
            {"seconds_from_window_start": deadline,
             "reachable_ordered_pairs": count,
             "reachable_ordered_pair_fraction": _fraction(count, possible)}
            for deadline, count in deadline_counts
        ],
        "expanded_graph": {"node_count": graph.number_of_nodes(), "edge_count": graph.number_of_edges()},
        "reachable_pair_identity_hash": _fingerprint(sorted(pairs)),
        "arrival_identity_hash": _fingerprint([(source, target, arrivals[source, target])
                                               for source, target in sorted(pairs)]),
    }


def temporal_contact_report(
    actors: tuple[int, ...], records: tuple[tuple[int, int, int], ...], *,
    start: int, end: int, minimum_bins: int = 1,
    deadlines_seconds: tuple[int, ...] = (),
) -> dict:
    """Compare strict/non-strict recorded-bin reachability in one window.

    Every source independently starts with a hypothetical signal at ``start``;
    waiting until ``end`` is permitted. Strict paths use at most one contact
    hop per bin; non-strict paths may chain contacts with the same bin label.
    The full-window pair threshold is retrospective and retains every bin of
    a qualifying pair, including bins before that threshold was accumulated.

    All fixed actors remain in the denominator. Only aggregate counts,
    endpoint-label summaries and canonical hashes are exported. Pair hashes
    encode sorted (source, target) pairs; arrival hashes additionally encode
    the absolute recorded endpoint, not its offset from the window start.
    """
    _validate_request(actors, records, start, end, minimum_bins, deadlines_seconds)
    raw = tuple(record for record in records if start < record[0] <= end)
    pair_counts = Counter((source, target) for _, source, target in raw)
    qualifying_pairs = {pair for pair, count in pair_counts.items() if count >= minimum_bins}
    retained = tuple(sorted(record for record in raw if record[1:] in qualifying_pairs))
    raw_nodes = {actor for _, source, target in raw for actor in (source, target)}
    qualified_nodes = {actor for _, source, target in retained for actor in (source, target)}
    times_by_actor = {actor: set() for actor in actors}
    for endpoint, source, target in retained:
        times_by_actor[source].add(endpoint)
        times_by_actor[target].add(endpoint)
    incident_count = sum(len(times) for times in times_by_actor.values())
    # Check both representations before allocating any NetworkX graph.
    expanded_nodes, strict_edges, nonstrict_edges = _expanded_sizes(
        len(actors), incident_count, len(retained))

    static_graph = nx.Graph()
    static_graph.add_nodes_from(actors)
    static_graph.add_edges_from(sorted(qualifying_pairs))
    components = list(nx.connected_components(static_graph))
    static_pairs = {(source, target) for component in components
                    for source in component for target in component if source != target}
    possible = len(actors) * (len(actors) - 1)
    static = {
        "reachable_ordered_pairs": len(static_pairs),
        "reachable_ordered_pair_fraction": _fraction(len(static_pairs), possible),
        "reachable_pair_identity_hash": _fingerprint(sorted(static_pairs)),
        "component_count": len(components),
        "component_sizes": sorted((len(component) for component in components), reverse=True),
        "recorded_pair_count": static_graph.number_of_edges(),
        "zero_qualifying_degree_node_count": len(actors) - len(qualified_nodes),
    }
    graph = _strict_graph(actors, retained, times_by_actor, start, end)
    if graph.number_of_nodes() != expanded_nodes or graph.number_of_edges() != strict_edges:
        raise RuntimeError("strict temporal graph size differs from its exact preflight count")
    strict_arrivals = _arrival_endpoints(graph, actors, start)
    strict = _mode_summary(graph, strict_arrivals, static_pairs, len(actors), start,
                           deadlines_seconds, "strictly_increasing_recorded_bin_endpoints")

    # Reuse the internal graph after preserving strict results; no second copy
    # is needed. These edges permit cycles only within one recorded bin.
    graph.add_edges_from(((actor, endpoint, _AFTER), (actor, endpoint, _BEFORE))
                         for actor in actors for endpoint in sorted(times_by_actor[actor]))
    if graph.number_of_nodes() != expanded_nodes or graph.number_of_edges() != nonstrict_edges:
        raise RuntimeError("non-strict temporal graph size differs from its exact preflight count")
    nonstrict_arrivals = _arrival_endpoints(graph, actors, start)
    nonstrict = _mode_summary(graph, nonstrict_arrivals, static_pairs, len(actors), start,
                              deadlines_seconds, "nondecreasing_recorded_bin_endpoints")
    strict_pairs, nonstrict_pairs = set(strict_arrivals), set(nonstrict_arrivals)
    if not strict_pairs <= nonstrict_pairs <= static_pairs:
        raise RuntimeError("recorded-bin reachability set inclusion failed")
    if any(nonstrict_arrivals[pair] > endpoint for pair, endpoint in strict_arrivals.items()):
        raise RuntimeError("a non-strict earliest endpoint is later than its strict counterpart")
    earlier = sum(nonstrict_arrivals[pair] < endpoint for pair, endpoint in strict_arrivals.items())
    return {
        "kind": "RECORDED_CONTACT_TEMPORAL_ANALYSIS", "engine": "networkx",
        "engine_version": version("networkx"),
        "algorithms": ["networkx.connected_components", "networkx.single_source_shortest_path_length"],
        "actor_count": len(actors), "actor_universe_hash": _fingerprint(actors),
        "possible_ordered_pairs": possible,
        "window": {
            "start_exclusive": start, "end_inclusive": end, "duration_seconds": end - start,
            "minimum_bins_per_pair": minimum_bins,
            "window_bin_count": len(raw), "window_recorded_pair_count": len(pair_counts),
            "zero_record_node_count": len(actors) - len(raw_nodes),
            "qualifying_pair_bin_count": len(retained),
            "qualifying_recorded_pair_count": len(qualifying_pairs),
            "zero_qualifying_degree_node_count": len(actors) - len(qualified_nodes),
            "excluded_below_threshold_pair_count": len(pair_counts) - len(qualifying_pairs),
            "excluded_below_threshold_bin_count": len(raw) - len(retained),
        },
        "static": static, "strict": strict, "nonstrict": nonstrict,
        "comparison": {
            "strict_subset_of_nonstrict": True, "nonstrict_subset_of_static": True,
            "common_pair_nonstrict_arrival_no_later_than_strict": True,
            "same_bin_rule_additional_reachable_ordered_pairs": len(nonstrict_pairs - strict_pairs),
            "common_reachable_ordered_pairs": len(strict_pairs),
            "common_pairs_arrive_earlier_with_nonstrict": earlier,
            "common_pairs_same_arrival": len(strict_pairs) - earlier,
        },
        "scope": {
            "basis": "paths through qualifying recorded 20-second contact bins",
            "window_rule": "start < recorded_bin_endpoint <= end",
            "pair_qualification": "retrospective full-window cumulative bin count; retain every qualifying pair's bin, including early bins",
            "signal_assumption": "each source separately holds a hypothetical signal at the window start",
            "waiting_assumption": "unlimited waiting within this window; retention is a model rule, not observed carrying",
            "strict_rule": "at most one contact hop in each recorded bin",
            "nonstrict_rule": "multiple contact hops with equal bin endpoints are allowed",
            "time_statistic": "earliest reachable recorded bin endpoint minus window start; conditional on reachable ordered nonself pairs",
            "deadline_fraction_denominator": "all fixed ordered nonself actor pairs, including unreachable pairs",
            "hash_scheme": "sha256 of compact UTF-8 JSON; sorted actor list, sorted (source,target) pairs, or sorted (source,target,absolute_bin_endpoint) triples",
            "all_actor_ids_retained": True, "retrospective_pair_filtering": True,
            "pair_filter_uses_later_window_records": minimum_bins > 1,
            "same_bin_physical_event_order_known": False,
            "continuous_transmission_delay_measured": False,
            "physical_transmission_bounds_established": False,
            "physical_contact_observation_complete": None,
            "attendance_or_device_uptime_established": False,
            "time_respecting_transmission_validated": False,
            "actual_transmission_observed": False,
            "causal_effect_identified": False, "forecast_validated": False,
            "raw_records_or_actor_ids_exported": False,
            "per_actor_or_pair_results_exported": False, "expanded_states_exported": False,
            "budgets": {"max_actors": _MAX_ACTORS, "max_input_rows": _MAX_INPUT_ROWS,
                        "max_expanded_nodes": _MAX_EXPANDED_NODES, "max_expanded_edges": _MAX_EXPANDED_EDGES},
        },
    }
