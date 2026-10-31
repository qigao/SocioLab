"""Direct Python SAOM reference through upstream cusna (CPU only).

This is a *network-only* Method-of-Moments fit; behavior covariates are not
modelled, no RSiena-style peer-influence/selection decomposition is claimed.
An s50 educational excerpt never qualifies for population causal inference.
"""

from __future__ import annotations

from importlib.metadata import version
from math import isfinite

import numpy as np

from .panels import LongitudinalPanel
from .s50 import load_s50_archive

_EFFECTS = ("density", "recip", "transTrip")


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
    """
    counts = (seed, n1, nD, n3, batch2)
    if any(type(x) is not int for x in counts) or seed < 0 or any(x <= 0 for x in counts[1:]):
        raise ValueError("SAOM seed and simulation budgets must be finite nonnegative/positive integers")
    if type(n2) is not tuple or len(n2) != 4 or any(type(x) is not int or x <= 0 for x in n2):
        raise ValueError("SAOM n2 must be a tuple of four positive iteration counts")
    waves = saom_wave_matrices(panel)

    # Required upstream estimator. No private copy, fake coefficients or
    # conditional fallback.  Install SocioLab's [saom] extra to run this.
    from cusna.saom.data import SaomData
    from cusna.saom.mom import MomEstimator
    from cusna.saom.stats import EffectSpec

    data = SaomData(waves)
    effects = [EffectSpec(name) for name in _EFFECTS]
    fitted = MomEstimator(
        data, effects=effects, backend="cpu", conditional=True,
        seed=seed, n1=n1, nD=nD, n3=n3, batch2=batch2, n2=n2,
    ).estimate(verbose=False)
    names = list(fitted.param_names)
    coefficients = list(map(float, fitted.theta))
    errors = list(map(float, fitted.se))
    tconv = list(map(float, fitted.tconv))
    max_tconv = float(fitted.tconv_max)
    if (names != list(_EFFECTS) or len(coefficients) != len(names)
            or len(errors) != len(names) or len(tconv) != len(names)
            or not all(isfinite(x) for x in coefficients + errors + tconv + [max_tconv])):
        raise ValueError("upstream SAOM returned invalid parameter diagnostics")
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
        "estimates": coefficients,
        "standard_errors": errors,
        "tconv": tconv,
        "tconv_max": max_tconv,
        "n_simulations": int(fitted.n_sims),
        "dataset_id": panel.dataset_id,
        "dataset_hash": panel.content_hash,
        "origin": panel.origin,
        "source_claim_verified": False,
        "population_boundary_qualified": False,
        "causal_effect_identified": False,
        "seed": seed,
        "n1": n1, "nD": nD, "n3": n3, "batch2": batch2, "n2": list(n2),
        "convergence_is_validated": False,
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
