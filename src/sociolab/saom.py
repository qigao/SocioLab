"""Direct Python SAOM reference through upstream cusna (CPU only).

This is a *network-only* Method-of-Moments fit; behavior covariates are not
modelled, no RSiena-style peer-influence/selection decomposition is claimed.
An s50 educational excerpt never qualifies for population causal inference.
"""

from __future__ import annotations

from importlib.metadata import version
from math import isfinite
from platform import python_version

import numpy as np

from .panels import LongitudinalPanel
from .s50 import load_s50_archive

_EFFECTS = ("density", "recip", "transTrip")
_CONVERGENCE_REFERENCE = (
    "https://www.stats.ox.ac.uk/~snijders/siena/RSiena_Manual.pdf#page=76"
)


def _diagnostic_array(value: object, shape: tuple[int, ...], name: str) -> np.ndarray:
    raw = np.asarray(value)
    if raw.shape != shape or raw.dtype.kind not in "iuf":
        raise ValueError(f"upstream SAOM returned invalid {name} shape or type")
    array = np.asarray(raw, dtype=np.float64)
    if not np.isfinite(array).all():
        raise ValueError(f"upstream SAOM returned nonfinite {name}")
    return array


def _assess_mom_diagnostics(
    *, theta: object, se: object, tconv: object, tconv_max: object,
    targets: object, sim_means: object, D: object, msf: object,
    parameter_count: int = len(_EFFECTS),
) -> dict[str, object]:
    """Validate upstream output and assess numerical moment matching only.

    RSiena manual section 7.3.2 supplies the convergence criteria. Matrix
    checks reject unusable diagnostics; they do not alter the fitted model,
    regularize a covariance matrix, or calculate replacement estimates.
    The caller supplies the count from its verified model specification,
    including free rate parameters; it is never inferred from fitted output.
    """
    if type(parameter_count) is not int or parameter_count <= 0:
        raise ValueError("SAOM parameter_count must be a positive integer")
    p = parameter_count
    vectors = {
        name: _diagnostic_array(value, (p,), name)
        for name, value in (
            ("theta", theta), ("se", se), ("tconv", tconv),
            ("targets", targets), ("sim_means", sim_means),
        )
    }
    derivative = _diagnostic_array(D, (p, p), "D")
    covariance = _diagnostic_array(msf, (p, p), "msf")
    overall = float(_diagnostic_array(tconv_max, (), "tconv_max"))
    if overall < 0:
        raise ValueError("upstream SAOM returned negative tconv_max")
    if np.any(vectors["se"] <= 0):
        raise ValueError("upstream SAOM standard errors must be positive for all free effects")
    if not np.allclose(covariance, covariance.T, rtol=1e-12, atol=0.0):
        raise ValueError("upstream SAOM statistic covariance msf is not symmetric")
    derivative_rank = int(np.linalg.matrix_rank(derivative))
    covariance_rank = int(np.linalg.matrix_rank(covariance))
    if derivative_rank != p or covariance_rank != p:
        raise ValueError("upstream SAOM returned rank-deficient D or msf diagnostics")
    try:
        np.linalg.cholesky(covariance)
    except np.linalg.LinAlgError as error:
        raise ValueError("upstream SAOM statistic covariance msf is not positive definite") from error
    derivative_condition = float(np.linalg.cond(derivative))
    covariance_condition = float(np.linalg.cond(covariance))
    if not all(isfinite(x) for x in (derivative_condition, covariance_condition)):
        raise ValueError("upstream SAOM returned nonfinite matrix condition numbers")

    max_abs_tconv = float(np.max(np.abs(vectors["tconv"])))
    converged = max_abs_tconv < 0.1 and 0 <= overall < 0.25
    return {
        "estimates": vectors["theta"].tolist(),
        "standard_errors": vectors["se"].tolist(),
        "tconv": vectors["tconv"].tolist(),
        "tconv_max": overall,
        "max_abs_tconv": max_abs_tconv,
        "convergence_status": "CONVERGED" if converged else "NOT_CONVERGED",
        "convergence_is_validated": converged,
        "convergence_scope": "numerical moment matching only",
        "convergence_criteria": {
            "max_abs_tconv_lt": 0.1,
            "tconv_max_gte": 0.0,
            "tconv_max_lt": 0.25,
            "reference": _CONVERGENCE_REFERENCE,
        },
        "diagnostics": {
            "targets": vectors["targets"].tolist(),
            "sim_means": vectors["sim_means"].tolist(),
            "D": derivative.tolist(),
            "msf": covariance.tolist(),
            "D_meaning": "Jacobian of expected statistics with respect to parameters",
            "msf_meaning": "covariance of simulated statistic totals across full-panel replicates",
            "derivative_rank": derivative_rank,
            "derivative_condition_number": derivative_condition,
            "statistic_covariance_rank": covariance_rank,
            "statistic_covariance_condition_number": covariance_condition,
        },
    }


def saom_wave_matrices(panel: LongitudinalPanel) -> list[np.ndarray]:
    """Convert an *explicitly complete* directed panel, preserving row order.

    This only prepares data. It does not estimate or simulate social models.
    No missing tie is ever silently converted to a zero.
    """
    if not isinstance(panel, LongitudinalPanel):
        raise TypeError("SAOM requires a versioned LongitudinalPanel")
    if any(not wave.network_complete for wave in panel.waves):
        raise ValueError("incomplete network observations require explicit upstream missingness masks")
    ids = {actor: i for i, actor in enumerate(panel.actors)}
    n = len(ids)
    matrices: list[np.ndarray] = []
    for wave in panel.waves:
        matrix = np.zeros((n, n), dtype=np.uint8)
        for source, target in wave.edges:
            matrix[ids[source], ids[target]] = 1
        matrices.append(matrix)
    return matrices


def fit_network_saom(
    panel: LongitudinalPanel,
    *,
    seed: int = 1234,
    n1: int = 1000,
    nD: int = 1000,
    n3: int = 4000,
    batch2: int = 256,
    n2: tuple[int, ...] = (40, 40, 60, 80),
) -> dict[str, object]:
    """Run *cusna's* genuine MoM estimator, never a local SAOM algorithm.

    Reduced simulation counts give only a numerical software smoke check.
    The caller is responsible for data provenance and population boundary.
    Symmetric observations are rejected when upstream infers an undirected
    model, since the panel contract requires directed tie dynamics.
    """
    counts = (seed, n1, nD, n3, batch2)
    if any(type(x) is not int for x in counts) or seed < 0 or any(x <= 0 for x in counts[1:]):
        raise ValueError("SAOM seed and simulation budgets must be finite nonnegative/positive integers")
    if type(n2) is not tuple or len(n2) != 4 or any(type(x) is not int or x <= 0 for x in n2):
        raise ValueError("SAOM n2 must be a tuple of four positive iteration counts")
    if n3 <= len(_EFFECTS):
        raise ValueError("SAOM n3 must exceed the number of free effects for a full-rank covariance")
    waves = saom_wave_matrices(panel)

    # Required upstream estimator. No private copy, fake coefficients or
    # conditional fallback.  Install SocioLab's [saom] extra to run this.
    from cusna.saom.data import SaomData
    from cusna.saom.mom import MomEstimator
    from cusna.saom.stats import EffectSpec

    data = SaomData(waves)
    # cusna 0.1.0 infers the model from observed matrix symmetry and has no
    # documented input option to force directed dynamics. Reciprocal
    # observations do not authorize paired changes to both directed ties.
    if data.symmetric:
        raise ValueError(
            "directed SAOM is unsupported for these symmetric observed waves: "
            "cusna infers an undirected model"
        )
    effects = [EffectSpec(name) for name in _EFFECTS]
    estimator = MomEstimator(
        data, effects=effects, backend="cpu", conditional=True,
        seed=seed, n1=n1, nD=nD, n3=n3, batch2=batch2, n2=n2,
    )
    fitted = estimator.estimate(verbose=False)
    names = list(fitted.param_names)
    if names != list(_EFFECTS) or fitted.backend != "cpu" or fitted.conditional is not True:
        raise ValueError("upstream SAOM returned an unexpected model specification")
    assessment = _assess_mom_diagnostics(
        theta=fitted.theta, se=fitted.se, tconv=fitted.tconv,
        tconv_max=fitted.tconv_max, targets=fitted.targets,
        sim_means=fitted.sim_means, D=fitted.D, msf=fitted.msf,
    )
    n_periods = len(panel.waves) - 1
    rate_est = _diagnostic_array(fitted.rate_est, (n_periods,), "rate_est")
    rate_sd = _diagnostic_array(fitted.rate_sd, (n_periods,), "rate_sd")
    if np.any(rate_est < 0) or np.any(rate_sd < 0):
        raise ValueError("upstream SAOM returned negative conditional rate diagnostics")
    trace = _diagnostic_array(
        fitted.theta_trace, (estimator.nsub + 2, len(_EFFECTS)), "theta_trace",
    )
    return {
        "kind": "REFERENCE_MODEL_RESULT",
        "model": "cusna.saom.mom.MomEstimator",
        "engine": "cusna",
        "engine_version": version("cusna"),
        "backend": "cpu",
        "conditional": True,
        "network_only": True,
        "behavior_coevolution_fitted": False,
        "effect_names": names,
        **assessment,
        "rate_est": rate_est.tolist(),
        "rate_sd": rate_sd.tolist(),
        "rate_est_meaning": "per-period conditional mean simulated duration",
        "rate_sd_meaning": "standard deviation of simulated durations (ddof=0), not standard error",
        "theta_trace": trace.tolist(),
        "n_simulations": int(fitted.n_sims),
        "n_simulations_unit": "full-panel replicates",
        "dataset_id": panel.dataset_id,
        "dataset_hash": panel.content_hash,
        "origin": panel.origin,
        "source_claim_verified": False,
        "population_boundary_qualified": False,
        "causal_effect_identified": False,
        "independent_reference_validated": False,
        "seed": seed,
        "n1": n1, "nD": nD, "n3": n3, "batch2": batch2, "n2": list(n2),
        "algorithm_settings": {
            "firstg": float(estimator.firstg),
            "nsub": int(estimator.nsub),
            "diagonalize": float(estimator.diagonalize),
            "maxdegree": int(estimator.maxdegree),
            "initial_theta": trace[0].tolist(),
        },
        "runtime_versions": {
            "python": python_version(),
            "numpy": version("numpy"),
            "numba": version("numba"),
        },
        "meaning": "upstream network-only numerical SAOM fit; not peer behavior influence or causal effect",
    }


def fit_s50_network_reference(path: str, **kwargs: object) -> dict[str, object]:
    """Official-format s50 is only a boundary-incomplete teaching excerpt."""
    panel, provenance = load_s50_archive(path)
    report = fit_network_saom(panel, **kwargs)
    return {
        **report,
        "source_archive_sha256": provenance["source_archive_sha256"],
        "source_member_sha256": provenance["source_member_sha256"],
        "sample_has_valid_population_boundary": False,
        "usage_limit": "s50 numerical compatibility only; not a population-estimable influence effect",
    }
