"""Endpoint observation counts for a fixed directed, partially observed panel.

This module constructs no graph and imputes no dyad. Unknown states are the
declared complement of the two observed sets, not absent relationships.
"""

from __future__ import annotations

from .partial_panels import PartialNetworkPanel, PartialNetworkWave


_STATES = ("absent", "present", "unknown")


def _period_report(
    before: PartialNetworkWave, after: PartialNetworkWave, dyad_count: int,
) -> dict[str, object]:
    old_present, old_absent = set(before.observed_present), set(before.observed_absent)
    new_present, new_absent = set(after.observed_present), set(after.observed_absent)
    old_known, new_known = old_present | old_absent, new_present | new_absent

    # Only supplied observations are materialized. Even an entirely unknown
    # large roster needs no N-by-N matrix or explicit unknown-dyad set.
    aa = len(old_absent & new_absent)
    ap = len(old_absent & new_present)
    au = len(old_absent - new_known)
    pa = len(old_present & new_absent)
    pp = len(old_present & new_present)
    pu = len(old_present - new_known)
    ua = len(new_absent - old_known)
    up = len(new_present - old_known)
    uu = dyad_count - len(old_known | new_known)
    transition_counts = {
        "absent": {"absent": aa, "present": ap, "unknown": au},
        "present": {"absent": pa, "present": pp, "unknown": pu},
        "unknown": {"absent": ua, "present": up, "unknown": uu},
    }
    return {
        "before_time_index": before.time_index,
        "after_time_index": after.time_index,
        "before_source_revision": before.source_revision,
        "after_source_revision": after.source_revision,
        "transition_counts": transition_counts,
        "known_overlap": aa + ap + pa + pp,
        "observed_hamming_distance": ap + pa,
        "observed_additions": ap,
        "observed_removals": pa,
        "observed_absent_both": aa,
        "observed_present_both": pp,
        "coverage_gained": ua + up,
        "coverage_lost": au + pu,
        "unknown_both": uu,
        "observed_before": len(old_known),
        "observed_after": len(new_known),
        "positive_count_before": len(old_present),
        "positive_count_after": len(new_present),
        "positive_count_change": len(new_present) - len(old_present),
        "positive_net_change_decomposition": {
            "observed_additions_minus_removals": ap - pa,
            "coverage_gained_present_minus_lost_present": up - pu,
            "sum": (ap - pa) + (up - pu),
        },
    }


def partial_panel_report(panel: PartialNetworkPanel) -> dict[str, object]:
    """Count all nine directed endpoint transitions without completing a graph.

    Only observed absent -> present and present -> absent count as observed
    additions/removals. Unknown-to-known transitions gain coverage and the
    reverse lose coverage; unknown at both endpoints remains unknown. Equal
    endpoint states do not establish that a relation stayed unchanged during
    the interval. Source and population declarations are not authenticated.
    """
    if not isinstance(panel, PartialNetworkPanel):
        raise TypeError("partial observation report requires a PartialNetworkPanel")
    actor_count = len(panel.actors)
    dyad_count = actor_count * (actor_count - 1)
    waves = []
    for wave in panel.waves:
        present, absent = len(wave.observed_present), len(wave.observed_absent)
        waves.append({
            "time_index": wave.time_index,
            "source_revision": wave.source_revision,
            "state_counts": {"absent": absent, "present": present, "unknown": dyad_count - present - absent},
            "observed_dyad_count": present + absent,
        })
    return {
        "kind": "PARTIAL_NETWORK_OBSERVATION_REPORT",
        "dataset_id": panel.dataset_id,
        "dataset_hash": panel.content_hash,
        "origin": panel.origin,
        "source_reference": panel.source_reference,
        "relation": panel.relation,
        "population_definition": panel.population_definition,
        "observation_definition": panel.observation_definition,
        "actor_count": actor_count,
        "wave_count": len(panel.waves),
        "dyad_universe_count": dyad_count,
        "state_order": list(_STATES),
        "reported_scope": "fixed directed offdiagonal declared actors",
        "waves": waves,
        "periods": [
            _period_report(before, after, dyad_count)
            for before, after in zip(panel.waves, panel.waves[1:])
        ],
        "graph_analyses": {"status": "NOT_RUN", "reason": "observation-state counts only; no graph constructed"},
        "unknown_dyads_imputed": False,
        "endpoint_comparison_only": True,
        "source_claim_verified": False,
        "population_boundary_qualified": False,
        "model_fitted": False,
        "causal_effect_identified": False,
        "meaning": "declared endpoint observations and coverage changes; no intermediate event counts or causal attribution",
    }
