"""Explicit observation masks for the original fixed-cohort cusna CPU model.

Unknown source dyads stay NaN at the adapter boundary. Initialization and
latent simulation are upstream operations and never become observations.
This profile has no behavior, composition, structural zeros or covariates.
"""

from __future__ import annotations

from importlib.metadata import version
from platform import python_version

import numpy as np

from .partial_panels import PartialNetworkPanel
from .partial_changes import partial_panel_report
from .saom import _assess_mom_diagnostics, _diagnostic_array

_EFFECTS = ("density", "recip", "transTrip")
_PROFILE = "directed-fixed-cohort-missing-network-v1"


def partial_saom_wave_matrices(panel: PartialNetworkPanel) -> list[np.ndarray]:
    """Return fresh 0/1/NaN matrices; omitted off-diagonal dyads are unknown."""
    if not isinstance(panel, PartialNetworkPanel):
        raise TypeError("partial SAOM requires a PartialNetworkPanel")
    ids = {actor: index for index, actor in enumerate(panel.actors)}
    matrices = []
    for wave in panel.waves:
        matrix = np.full((len(ids), len(ids)), np.nan, dtype=np.float64)
        # The diagonal is outside the observation universe and not a zero tie.
        np.fill_diagonal(matrix, 0.0)
        for source, target in wave.observed_absent:
            matrix[ids[source], ids[target]] = 0.0
        for source, target in wave.observed_present:
            matrix[ids[source], ids[target]] = 1.0
        matrices.append(matrix)
    return matrices


def _settings(seed, n1, nD, n3, batch2, n2) -> dict:
    values = (seed, n1, nD, n3, batch2)
    if (any(type(value) is not int for value in values) or seed < 0
            or any(value <= 0 for value in values[1:])):
        raise ValueError("partial SAOM seed/budgets must be nonnegative/positive exact integers")
    if type(n2) is not tuple or len(n2) != 4 or any(type(x) is not int or x <= 0 for x in n2):
        raise ValueError("partial SAOM n2 requires four positive integer iteration counts")
    if n3 <= len(_EFFECTS):
        raise ValueError("partial SAOM n3 must exceed the three free effects")
    return {"seed": seed, "n1": n1, "nD": nD, "n3": n3, "batch2": batch2, "n2": n2}


def _prepare(panel: PartialNetworkPanel, settings: dict):
    observations = partial_panel_report(panel)
    for period in observations["periods"]:
        if period["known_overlap"] == 0:
            raise ValueError("partial conditional SAOM requires known-overlap dyads in every period")
        if period["observed_hamming_distance"] == 0:
            raise ValueError("partial conditional SAOM requires positive observed distance in every period")

    from cusna.saom.data import SaomData
    from cusna.saom.mom import MomEstimator
    from cusna.saom.stats import EffectSpec

    if version("cusna") != "0.1.0":
        raise ValueError("this partial-network profile is scoped to cusna 0.1.0")
    matrices = partial_saom_wave_matrices(panel)
    data = SaomData(matrices)
    if data.symmetric:
        raise ValueError("directed partial SAOM is unsupported when cusna infers an undirected model")
    if data.has_structural or data.beh is not None or data.composition is not None:
        raise ValueError("partial-network profile does not support structural ties, behavior or composition")
    for index, matrix in enumerate(matrices):
        missing = np.isnan(matrix)
        if not np.array_equal(data.miss[index], missing):
            raise ValueError("upstream changed the source missingness mask")
        if not np.array_equal(data.imputed[index][~missing], matrix[~missing]):
            raise ValueError("upstream changed a known source observation")
    estimator = MomEstimator(data, effects=[EffectSpec(name) for name in _EFFECTS],
                             conditional=True, backend="cpu", **settings)
    if estimator.param_names != list(_EFFECTS) or estimator.p != 3:
        raise ValueError("upstream partial-network parameter layout differs from the selected profile")
    for index, period in enumerate(observations["periods"]):
        keep, force = data.stat_keep_force(index)
        distance_mask = data.kmask_dist(index)
        if (int(distance_mask.sum()) != period["known_overlap"]
                or data.observed_distance(index) != period["observed_hamming_distance"]
                or not np.array_equal(keep, distance_mask) or force.any()):
            raise ValueError("upstream period masks disagree with explicit source observations")
    return observations, data, estimator


def _model_report(panel: PartialNetworkPanel, observations, data, estimator) -> dict:
    targets = _diagnostic_array(estimator.targets, (3,), "partial-network targets")
    period_targets = _diagnostic_array(estimator.eval_targets, (data.n_periods, 3), "period targets")
    periods = []
    for index, original in enumerate(observations["periods"]):
        missing_either = data.miss[index] | data.miss[index + 1]
        periods.append({
            "before_time_index": original["before_time_index"],
            "after_time_index": original["after_time_index"],
            "known_overlap": original["known_overlap"],
            "conditional_target_distance": data.observed_distance(index),
            "moment_targets": period_targets[index].tolist(),
            "unknown_at_either_endpoint": int(missing_either.sum()),
            "permitted_dyads": int(data.permitted(index).sum()),
            "unknown_dyads_permitted_to_toggle": int((missing_either & data.permitted(index)).sum()),
        })
    return {
        "kind": "PARTIAL_NETWORK_SAOM_MODEL", "profile": _PROFILE,
        "engine": "cusna", "engine_version": version("cusna"), "backend": "cpu",
        "conditional": True, "network_only": True, "effect_names": list(_EFFECTS),
        "targets": targets.tolist(), "periods": periods,
        "input": observations,
        "dataset_id": panel.dataset_id, "dataset_hash": panel.content_hash,
        "origin": panel.origin, "source_reference": panel.source_reference,
        "initialization": [{
            "time_index": wave.time_index, "unknown_dyads": int(data.miss[index].sum()),
            "unknown_initialized_to_zero": int((data.miss[index] & (data.imputed[index] == 0)).sum()),
            "unknown_initialized_to_one": int((data.miss[index] & (data.imputed[index] == 1)).sum()),
        } for index, wave in enumerate(panel.waves)],
        "missingness_policy": {
            "source_encoding": "explicit observed present=1, observed absent=0, all other off-diagonal dyads=NaN",
            "initialization": "upstream first-wave missing cells initialize to zero; later missing cells carry forward prior initialized values",
            "moment_and_distance_scope": "dyads missing at either endpoint are excluded by upstream period masks",
            "statistic_network": "upstream masks unknown dyads to zero only for computing moment statistics; this does not create source observations",
            "latent_simulation": "unknown dyads remain eligible for changes and can affect latent network dynamics",
            "missingness_mechanism_modeled": False,
            "source_observations_reclassified": False,
            "known_incoming_preserved": True,
        },
        "time_handling": "ordered waves; time-index gaps do not rescale conditional durations or establish event times",
        "model_fitted": False, "behavior_coevolution_fitted": False,
        "source_claim_verified": False, "population_boundary_qualified": False,
        "empirical_admitted": False, "independent_reference_validated": False,
        "causal_effect_identified": False,
    }


def partial_network_model_report(panel: PartialNetworkPanel) -> dict[str, object]:
    """Inspect actual upstream initialization, masks and targets without fitting."""
    observations, data, estimator = _prepare(panel, _settings(1234, 1000, 1000, 4000, 256, (40, 40, 60, 80)))
    return _model_report(panel, observations, data, estimator)


def _record_conditional_batch(record, result, *, n_sims, period, target, max_steps):
    """Inspect original CPU counters; do not mutate arrays, settings or RNGs."""
    steps = np.asarray(result["steps"])
    if steps.shape != (n_sims,) or steps.dtype.kind not in "iu":
        raise ValueError("upstream returned invalid conditional path counters")
    distances = _diagnostic_array(result["dist"], (n_sims,), "conditional path distances")
    final_distances = _diagnostic_array(result["dist_stat"], (n_sims,), "final conditional path distances")
    durations = _diagnostic_array(result["ntim"], (n_sims,), "conditional path durations")
    if (np.any(steps <= 0) or np.any(steps >= max_steps)
            or np.any(distances != target) or np.any(final_distances != target)
            or np.any(durations <= 0)):
        raise ValueError("upstream conditional path failed to reach its target below the step cap")
    item = record[period]
    item["path_count"] += n_sims
    item["batch_calls"] += 1
    item["max_steps"] = max(item["max_steps"], int(steps.max()))
    item["max_duration"] = max(item["max_duration"], float(durations.max()))
    item["min_duration"] = min(item["min_duration"], float(durations.min()))


def fit_partial_network_saom(
    panel: PartialNetworkPanel, *, seed: int = 1234, n1: int = 1000,
    nD: int = 1000, n3: int = 4000, batch2: int = 256,
    n2: tuple[int, ...] = (40, 40, 60, 80),
) -> dict[str, object]:
    """Fit the original conditional three-effect CPU model with explicit masks.

    Successful numerical diagnostics do not qualify source/population boundaries,
    the missingness mechanism, predictions, or causal effects.
    """
    settings = _settings(seed, n1, nD, n3, batch2, n2)
    observations, data, estimator = _prepare(panel, settings)
    report = _model_report(panel, observations, data, estimator)
    from cusna.saom.cpu import MAX_STEPS

    paths = [{"period_index": index, "target_distance": data.observed_distance(index),
              "path_count": 0, "batch_calls": 0, "max_steps": 0,
              "min_duration": float("inf"), "max_duration": 0.0}
             for index in range(data.n_periods)]
    original_cpu = estimator._cpu

    def observe(*args, **kwargs):
        period = kwargs["period"]
        if kwargs["conditional"] is not True or kwargs["target_dist"] != paths[period]["target_distance"]:
            raise ValueError("upstream conditional CPU call changed its stopping specification")
        result = original_cpu(*args, **kwargs)
        _record_conditional_batch(paths, result, n_sims=args[3], period=period,
                                  target=paths[period]["target_distance"], max_steps=MAX_STEPS)
        return result

    estimator._cpu = observe
    fitted = estimator.estimate(verbose=False)
    if (list(fitted.param_names) != list(_EFFECTS) or fitted.backend != "cpu"
            or fitted.conditional is not True):
        raise ValueError("upstream returned an unexpected partial-network model specification")
    if not np.array_equal(fitted.targets, report["targets"]):
        raise ValueError("upstream fitted targets differ from the inspected partial-network model")
    assessment = _assess_mom_diagnostics(
        theta=fitted.theta, se=fitted.se, tconv=fitted.tconv, tconv_max=fitted.tconv_max,
        targets=fitted.targets, sim_means=fitted.sim_means, D=fitted.D, msf=fitted.msf,
    )
    rates = _diagnostic_array(fitted.rate_est, (data.n_periods,), "conditional durations")
    rate_sd = _diagnostic_array(fitted.rate_sd, (data.n_periods,), "conditional duration SD")
    trace = _diagnostic_array(fitted.theta_trace, (estimator.nsub + 2, 3), "theta_trace")
    if np.any(rates <= 0) or np.any(rate_sd < 0):
        raise ValueError("upstream returned invalid conditional duration summaries")
    if any(item["path_count"] != fitted.n_sims or item["path_count"] == 0 for item in paths):
        raise ValueError("audited CPU paths do not match the upstream simulation count")
    return {
        **report, "kind": "PARTIAL_NETWORK_SAOM_FIT", "model_fitted": True,
        "model": "cusna.saom.mom.MomEstimator", **assessment,
        "rate_est": rates.tolist(), "rate_sd": rate_sd.tolist(),
        "rate_est_meaning": "per-period conditional mean simulated duration",
        "rate_sd_meaning": "standard deviation of simulated durations (ddof=0), not standard error",
        "theta_trace": trace.tolist(), "n_simulations": int(fitted.n_sims),
        "n_simulations_unit": "full-panel replicates",
        "cpu_path_audit": {"all_paths_reached_target": True, "step_cap": int(MAX_STEPS),
                           "total_period_paths": sum(item["path_count"] for item in paths),
                           "periods": paths},
        **{key: list(value) if key == "n2" else value for key, value in settings.items()},
        "algorithm_settings": {"firstg": float(estimator.firstg), "nsub": int(estimator.nsub),
                               "diagonalize": float(estimator.diagonalize), "maxdegree": int(estimator.maxdegree),
                               "initial_theta": trace[0].tolist()},
        "runtime_versions": {"python": python_version(), "numpy": version("numpy"), "numba": version("numba")},
        "meaning": "conditional network-only numerical fit to explicitly masked observations; empirical and causal qualification remain open",
    }
