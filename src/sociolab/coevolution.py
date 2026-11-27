"""Explicit retrospective network/ordinal-behavior fitting with cusna CPU.

The fixed profile matches a published upstream RSiena comparison. This module
adapts input, checks the actual parameter layout, and reports diagnostics. It
does not supply another estimator, a forward predictor, or a causal model.
"""

from __future__ import annotations

from importlib.metadata import version
from platform import python_version

import numpy as np

from .coevolution_input import CoevolutionSpec, validate_coevolution_input
from .panels import LongitudinalPanel
from .saom import _assess_mom_diagnostics, _diagnostic_array, saom_wave_matrices


_NETWORK_EFFECTS = ("density", "recip", "transTrip", "altX", "egoX", "simX")
_DYNAMIC_EFFECTS = frozenset({"altX", "egoX", "simX"})
_BEHAVIOR_EFFECTS = ("linear", "quad", "avSim")


def _record_cpu_batch(result, *, n_sims: int, period: int, step_limit: int, audit: dict) -> None:
    """Observe original CPU output before MomEstimator discards path lengths."""
    steps = np.asarray(result["steps"])
    if steps.shape != (n_sims,) or steps.dtype.kind not in "iu" or np.any(steps < 0):
        raise ValueError("upstream coevolution returned invalid CPU step counts")
    if np.any(steps >= step_limit):
        raise ValueError("upstream coevolution reached its CPU path step limit; truncated paths cannot qualify a fit")
    elapsed = _diagnostic_array(result["ntim"], (n_sims,), "CPU period end times")
    if np.any(elapsed <= 1.0):
        raise ValueError("upstream unconditional coevolution path did not finish its unit period")
    maximum = int(steps.max())
    audit["batch_calls"] += 1
    audit["period_paths_checked"] += n_sims
    audit["max_steps_per_path"] = max(audit["max_steps_per_path"], maximum)
    audit["max_steps_by_period"][period] = max(audit["max_steps_by_period"][period], maximum)


def _parameter_layout(panel: LongitudinalPanel) -> list[dict[str, object]]:
    layout = []
    for block, label in (("network_rate", "net"), ("behavior_rate", "beh")):
        for period, (before, after) in enumerate(zip(panel.waves, panel.waves[1:]), 1):
            layout.append({
                "index": len(layout), "name": f"rate {label} (p{period})", "block": block,
                "period": period, "from_time_index": before.time_index,
                "to_time_index": after.time_index,
            })
    for block, effects in (("network_evaluation", _NETWORK_EFFECTS),
                           ("behavior_evaluation", _BEHAVIOR_EFFECTS)):
        for effect in effects:
            name = "beh " + effect if block == "behavior_evaluation" else effect
            layout.append({"index": len(layout), "name": name, "block": block, "effect": effect})
    return layout


def _prepare_model(panel: LongitudinalPanel, spec: CoevolutionSpec, **settings):
    behavior = validate_coevolution_input(panel, spec)
    waves = saom_wave_matrices(panel)

    from cusna.saom.data import SaomData
    from cusna.saom.mom import MomEstimator
    from cusna.saom.stats import BehEffectSpec, EffectSpec

    data = SaomData(waves, behavior=behavior)
    if data.symmetric:
        raise ValueError(
            "directed coevolution is unsupported for these symmetric observed waves: "
            "cusna infers an undirected model"
        )
    beh = data.beh
    if (beh is None or beh.zmin != spec.minimum or beh.zmax != spec.maximum
            or beh.range != spec.maximum - spec.minimum
            or np.any(beh.miss) or not np.array_equal(beh.imputed, behavior)):
        raise ValueError("upstream coevolution changed the declared behavior observations or bounds")
    effects = [EffectSpec(name, dyn=name in _DYNAMIC_EFFECTS) for name in _NETWORK_EFFECTS]
    behavior_effects = [BehEffectSpec(name) for name in _BEHAVIOR_EFFECTS]
    estimator = MomEstimator(
        data, effects=effects, beh_effects=behavior_effects,
        conditional=False, backend="cpu", **settings,
    )
    layout = _parameter_layout(panel)
    names = [row["name"] for row in layout]
    count = len(layout)
    if (list(estimator.param_names) != names or estimator.p != count
            or estimator.coevol is not True or estimator.conditional is not False
            or estimator.backend != "cpu" or estimator.R != 0):
        raise ValueError("upstream coevolution returned an unexpected model specification")
    targets = _diagnostic_array(estimator.targets, (count,), "targets")
    initial = _diagnostic_array(estimator.default_theta0(), (count,), "initial_theta")
    preprocessing = {
        "minimum": int(beh.zmin), "maximum": int(beh.zmax), "range": float(beh.range),
        "overall_mean": float(beh.overall_mean), "similarity_mean": float(beh.sim_mean),
        "scope": "supplied fitting waves only; retrospective model",
        "centering": "mean of per-wave observed means over all supplied fitting waves",
        "similarity_centering": "ordered distinct-actor pairs in all fitting waves except the final wave",
        "range_basis": "declared bounds must equal the observed fitting-sample extrema",
        "missing_values_imputed": False, "held_out_preprocessing_qualified": False,
    }
    if not np.isfinite([preprocessing["overall_mean"], preprocessing["similarity_mean"]]).all():
        raise ValueError("upstream coevolution returned nonfinite behavior preprocessing")
    report = {
        "kind": "COEVOLUTION_MODEL_SPECIFICATION",
        "model": "cusna.saom.mom.MomEstimator", "engine": "cusna",
        "engine_version": version("cusna"), "backend": "cpu", "conditional": False,
        "network_only": False, "behavior_coevolution_fitted": False,
        "model_descriptor": {
            "profile": spec.profile, "directed": True,
            "network_count": 1, "behavior_count": 1,
            "network_effects": [{"name": name, "dynamic_behavior": name in _DYNAMIC_EFFECTS}
                                for name in _NETWORK_EFFECTS],
            "behavior_effects": list(_BEHAVIOR_EFFECTS),
            "parameter_count": count, "parameter_layout": layout,
            "composition_change": False,
            "neighbor_direction": "ego's outgoing network ties",
        },
        "parameter_names": names, "targets": targets.tolist(),
        "target_conventions": {
            "network_rate": "per-period endpoint Hamming distance, not the number of latent toggles",
            "behavior_rate": "per-period sum of absolute endpoint changes, not latent ministep count",
            "network_evaluation": "end-of-period network with start-of-period behavior covariate",
            "behavior_evaluation": "end-of-period behavior with start-of-period observed network",
        },
        "initial_theta": initial.tolist(), "behavior_preprocessing": preprocessing,
        "dataset_id": panel.dataset_id, "dataset_hash": panel.content_hash,
        "origin": panel.origin, "source_reference": panel.source_reference,
        "actors": list(panel.actors), "relation": panel.relation,
        "behavior_variable": panel.behavior_variable,
        "waves": [{"time_index": wave.time_index, "source_revision": wave.source_revision}
                  for wave in panel.waves],
        "specification": spec.to_dict(), "specification_hash": spec.content_hash,
        "fit_scope": "retrospective_supplied_panel",
        "rate_units": "opportunities per actor over each observed transition; time_index gaps are not calendar denominators",
        "source_claim_verified": False, "population_boundary_qualified": False,
        "independent_reference_validated": False, "empirical_model_qualified": False,
        "forecast_validated": False, "causal_effect_identified": False,
        "runtime_versions": {"python": python_version(), "numpy": version("numpy"),
                             "numba": version("numba")},
        "meaning": "declared joint model and genuine upstream targets; no coefficients have been estimated",
    }
    return estimator, report


def coevolution_model_report(panel: LongitudinalPanel, spec: CoevolutionSpec) -> dict[str, object]:
    """Inspect actual upstream targets and parameter order without fitting."""
    _, report = _prepare_model(panel, spec)
    return report


def fit_coevolution_saom(
    panel: LongitudinalPanel,
    spec: CoevolutionSpec,
    *,
    seed: int = 1234,
    n1: int = 1000,
    nD: int = 1000,
    n3: int = 4000,
    batch2: int = 256,
    n2: tuple[int, ...] = (40, 40, 60, 80),
) -> dict[str, object]:
    """Fit the fixed, unconditional one-network/one-behavior upstream model.

    A valid nonconverged result is returned with its diagnostics. Callers must
    inspect convergence_status. Neither convergence nor a completed fit
    establishes measurement quality, forecast accuracy, or causal effects.
    """
    if not isinstance(panel, LongitudinalPanel) or not isinstance(spec, CoevolutionSpec):
        raise TypeError("coevolution requires a LongitudinalPanel and CoevolutionSpec")
    counts = (seed, n1, nD, n3, batch2)
    if any(type(x) is not int for x in counts) or seed < 0 or any(x <= 0 for x in counts[1:]):
        raise ValueError("coevolution seed and simulation budgets must be nonnegative/positive integers")
    if type(n2) is not tuple or len(n2) != 4 or any(type(x) is not int or x <= 0 for x in n2):
        raise ValueError("coevolution n2 must be a tuple of four positive iteration counts")
    parameter_count = 2 * (len(panel.waves) - 1) + len(_NETWORK_EFFECTS) + len(_BEHAVIOR_EFFECTS)
    if n3 <= parameter_count:
        raise ValueError("coevolution n3 must exceed the total free-parameter count including both rates")
    estimator, report = _prepare_model(
        panel, spec, seed=seed, n1=n1, nD=nD, n3=n3, batch2=batch2, n2=n2,
    )
    from cusna.saom.cpu import MAX_STEPS

    periods = len(panel.waves) - 1
    audit = {"backend": "cpu", "kernel_step_limit": int(MAX_STEPS),
             "batch_calls": 0, "period_paths_checked": 0, "max_steps_per_path": 0,
             "max_steps_by_period": [0] * periods, "truncated_paths_detected": False}
    original_cpu = estimator._cpu

    def audited_cpu(*args, **kwargs):
        result = original_cpu(*args, **kwargs)
        _record_cpu_batch(result, n_sims=args[3], period=kwargs["period"],
                          step_limit=int(MAX_STEPS), audit=audit)
        return result

    # The original simulator and all returned statistics are unchanged. The
    # pinned estimator otherwise drops the step-limit evidence from MomResult.
    estimator._cpu = audited_cpu
    fitted = estimator.estimate(verbose=False)
    if (list(fitted.param_names) != report["parameter_names"] or fitted.backend != "cpu"
            or fitted.conditional is not False or fitted.rate_est is not None
            or fitted.rate_sd is not None):
        raise ValueError("upstream coevolution returned unexpected parameter or rate semantics")
    assessment = _assess_mom_diagnostics(
        theta=fitted.theta, se=fitted.se, tconv=fitted.tconv, tconv_max=fitted.tconv_max,
        targets=fitted.targets, sim_means=fitted.sim_means, D=fitted.D, msf=fitted.msf,
        parameter_count=parameter_count,
    )
    if assessment["diagnostics"]["targets"] != report["targets"]:
        raise ValueError("upstream coevolution changed the model's observation targets")
    trace = _diagnostic_array(fitted.theta_trace, (estimator.nsub + 2, parameter_count), "theta_trace")
    if (np.any(np.asarray(assessment["estimates"])[:2 * periods] <= 0)
            or np.any(trace[:, :2 * periods] <= 0)):
        raise ValueError("upstream coevolution returned nonpositive basic rate parameters")
    if not np.array_equal(trace[0], report["initial_theta"]) or not np.array_equal(trace[-1], assessment["estimates"]):
        raise ValueError("upstream coevolution parameter trace does not match its initial/final estimates")
    expected_simulations = n1 + estimator.nsub * nD + sum(n2) * batch2 + n3
    if type(fitted.n_sims) is not int or fitted.n_sims != expected_simulations:
        raise ValueError("upstream coevolution returned an unexpected simulation count")
    if audit["period_paths_checked"] != expected_simulations * periods:
        raise ValueError("upstream coevolution CPU audit does not cover every period path")
    period_rates = []
    for m, (before, after) in enumerate(zip(panel.waves, panel.waves[1:])):
        period_rates.append({
            "period": m + 1, "from_time_index": before.time_index, "to_time_index": after.time_index,
            "network": {"parameter_index": m, "estimate": assessment["estimates"][m],
                        "standard_error": assessment["standard_errors"][m]},
            "behavior": {"parameter_index": periods + m, "estimate": assessment["estimates"][periods + m],
                         "standard_error": assessment["standard_errors"][periods + m]},
        })
    return {
        **report, "kind": "COEVOLUTION_MODEL_RESULT", "behavior_coevolution_fitted": True,
        **assessment, "period_rates": period_rates,
        "rate_estimation": "jointly fitted basic rates in the parameter vector; no conditional-duration estimates",
        "theta_trace": trace.tolist(), "n_simulations": fitted.n_sims,
        "simulation_diagnostics": audit,
        "n_simulations_unit": "full-panel replicates",
        "seed": seed, "n1": n1, "nD": nD, "n3": n3, "batch2": batch2, "n2": list(n2),
        "algorithm_settings": {
            "firstg": float(estimator.firstg), "nsub": int(estimator.nsub),
            "diagonalize": float(estimator.diagonalize), "maxdegree": int(estimator.maxdegree),
        },
        "meaning": "upstream retrospective joint SAOM fit; convergence assesses numerical moment matching only",
    }
