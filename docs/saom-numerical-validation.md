# SAOM numerical validation — 2026-11-27

This record extends the [initial runtime review](validation-2026-11-27.md).
It qualifies the numerical diagnostics for the fixed upstream CPU,
conditional, network-only model with effects `density`, `recip`, `transTrip`.
Independent-estimator equivalence and empirical influence inference remain
unqualified. All execution evidence is local; no CI workflow was added.

**Result:** the full-default s50 CLI fit with seed 4321 passes the new numerical
screen and exits 0. A preceding full-default run with seed 1234 also meets
both ratio thresholds, but its legacy report did not retain the matrices
needed for the complete new screen. Both original reports are preserved.

## Convergence contract

The [RSiena manual](https://www.stats.ox.ac.uk/~snijders/siena/RSiena_Manual.pdf#page=76),
dated 25 October 2026, describes individual absolute convergence ratios below
0.1 and an overall ratio below 0.25 as practical criteria. SocioLab adopts
strict inequalities for an explicit, reproducible numerical screen:

```text
max(abs(tconv)) < 0.1 AND 0 <= tconv_max < 0.25
```

These are diagnostics of moment matching, not coefficient significance
tests, goodness-of-fit tests, or mathematical guarantees. `tconv_max` is the
multivariate statistic; it is not `max(abs(tconv))`.

Before classification, all returned vectors and matrices must have the
expected shapes, numeric dtypes, and finite values. All three free-effect
standard errors must be positive. The final derivative matrix `D` must have
numerical rank three; it is a Jacobian and need not be symmetric or positive
definite. The statistic covariance `msf` must be symmetric, have numerical
rank three, and be positive definite. Conditional durations, their SDs, and
the parameter trace are checked as well. `n3 <= 3` is rejected before fitting
because that many samples cannot produce a full-rank three-statistic sample
covariance.

The adapter reports condition numbers, using NumPy's numerical rank rules,
without inventing a universal condition-number cutoff. Passing the screen
does not guarantee well-conditioned inference in every application. It also
does not prove that earlier optimization phases avoided the upstream
pseudoinverse path. The pinned [upstream result calculation](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/mom.py#L483-L505)
can use a pseudoinverse and takes the absolute value of covariance diagonal
entries when forming SEs; finite SEs alone therefore do not qualify a fit.
SocioLab adds no optimizer, matrix repair, retry, or replacement estimates.

A valid fit that misses the thresholds returns `NOT_CONVERGED` with all
diagnostics preserved. Invalid or unusable diagnostics raise errors.
`convergence_is_validated=true` has the explicit scope **numerical moment
matching only**. `independent_reference_validated`,
`behavior_coevolution_fitted`, `population_boundary_qualified`, and
`causal_effect_identified` remain false.

## Reproduction and report semantics

Use the versions in the [runtime record](validation-2026-11-27.md), install
the optional `.[saom]` dependency, and obtain the ZIP from the
[original Oxford source](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.zip).
The archive is not bundled or silently downloaded. From the repository root:

```bash
PYTHONPATH=src NUMBA_NUM_THREADS=2 python -m sociolab saom /path/to/s50_data.zip \
  --format s50 --seed 4321 > fit.json
```

The CLI emits strict JSON. Exit **0** means the numerical screen passed;
exit **2** means a valid nonconverged report was emitted. Invalid input or
upstream failures raise errors. A writable `NUMBA_CACHE_DIR` was supplied in
the recorded environment; timings include a warm kernel cache. Python API
callers receive valid nonconverged reports and must check the status.

Defaults remain `n1=1000`, `nD=1000`, `n3=4000`, `batch2=256`,
`n2=(40,40,60,80)`. Each default run uses **65,320 full-panel replicates**:

```text
1000 + 4*1000 + 256*(40+40+60+80) + 4000 = 65320
```

With two s50 periods this corresponds to 130,640 period paths, not 65,320
actor ministeps. `msf` is the sample covariance of simulated statistic totals
across full-panel replicates (`ddof=1`), not the covariance of their sample
means or of coefficients. `rate_est` is the per-period mean conditional
simulated duration; `rate_sd` is its SD with `ddof=0`, not a
standard error. Observation time indices are not forwarded as calendar-rate
denominators. These meanings follow the pinned [cusna implementation](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/mom.py).

## Input and deterministic reference

The original ZIP's SHA-256 is
`57dfd0d2a5f924f36cb1ff0c70d2e3a83370e142400af4edc28f4c5c29fea955`.
The canonical panel SHA-256 is
`dd71009fe43cf7a32538c740d3b67f73bb1e601bb18146677b384d7d7213b001`.
Per-member hashes are preserved in each report. The three parsed network
arrays equal the upstream example arrays at cusna commit
`313c3d2623c99ed15c1eb6fe713593c6d3915d1d`; their differently formatted text
files need not have equal byte hashes. Each array is 50×50, binary, has zero
diagonal and no missing dyads. Tie counts are 113, 116, and 122.

Constructing the actual upstream estimator produces these deterministic
targets, in effect order `density`, `recip`, `transTrip`:

| Quantity | Value |
| --- | --- |
| First period endpoint evaluation targets | `[116, 70, 88]` |
| Second period endpoint evaluation targets | `[122, 90, 137]` |
| Summed evaluation targets | `[238, 160, 225]` |
| Conditional distance targets | `[115, 106]` |

The density statistic here counts ties; it is not NetworkX's normalized
density. These checks establish data and statistic-convention agreement,
not optimizer equivalence. Only the network is fitted; the supplied alcohol
observations are not used as behavior or covariates.

## Full-default results and retained evidence

Both runs use the original ZIP, two Numba threads, and the unchanged default
budgets. Neither run was retuned or automatically retried.

| Check | Seed 1234 | Seed 4321 |
| --- | ---: | ---: |
| Full-panel replicates | 65,320 | 65,320 |
| Maximum absolute individual ratio | 0.0206155147 | 0.0144973325 |
| Overall convergence ratio | 0.0432655145 | 0.0661364037 |
| Wall time, seconds | 112.754 | 114.354 |
| Invocation | Python API, initial adapter | New CLI |
| Acceptance evidence | Both ratio thresholds met | Full numerical screen passed; exit 0 |

The seed-1234 fit ran at commit `5286c95f018f498fe24ec66bd8b2729d43b4013b`.
Its legacy `convergence_is_validated=false` field is retained unchanged;
that API hard-coded the field and did not expose `D` or `msf`. It is not
retroactively labeled as passing the complete new matrix screen.

The seed-4321 report retains `D` and `msf`, both with numerical rank three.
Their condition numbers are **55.840991995** and **166.866057671**.
The covariance is symmetric and positive definite, with eigenvalues
approximately `[29.5504, 230.6472, 4930.9606]`. Independent arithmetic from the
raw matrices reproduces the reported convergence ratios and standard errors.
This is a check of the recorded quantities, not an independent model fit.

The CLI process loaded the working-tree source before a final change that
rejects boolean and string diagnostic arrays. Metadata records both source
hashes. The retained actual numeric diagnostics were revalidated through the
final gate and produce an identical assessment; no full fit was rerun for
that type-only change. The final adapter SHA-256 is
`694a1313fc58e31d0b920999f4cb4986d0fef720e03c7c812de9acde19175e6c`,
and CLI SHA-256 is
`162df528950dd9f9ea6bbeb35347fa89284fd209625e9e68e3c5cb2f8a8b7a4b`.
The submitted commit and complete tree are recorded in PR #4.

| Evidence | Files |
| --- | --- |
| Seed 1234, unchanged legacy output | [report](experiments/2026-11-27-saom/seed1234-report.json), [execution](experiments/2026-11-27-saom/seed1234-execution.json) |
| Seed 4321, actual CLI output | [report](experiments/2026-11-27-saom/seed4321-report.json), [execution](experiments/2026-11-27-saom/seed4321-execution.json) |
| Seed 4321, verification | [matrix calculations](experiments/2026-11-27-saom/seed4321-verification.json), [final gate](experiments/2026-11-27-saom/seed4321-final-gate-verification.json) |

The execution records retain exact commands, source hashes, versions,
environment settings, timing, and scratch paths used during the experiments.
The seed-4321 process emitted no stderr. Its report SHA-256 is
`2a7ffbd0e321e93740e75a9cf4283dd47edd6c3a97314b662327b796b517db54`.

## Published coefficient comparison

The pinned upstream [generating R script](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/bench/rsiena_gof.R)
uses the same three networks, conditional estimation, seed 321, and
`n3=3000`. It takes RSiena's default density/reciprocity effects and adds
`transTrip`; it supplies no behavior, covariates, missingness perturbations,
composition changes, or degree constraint. The [saved coefficient vector](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/bench/out/gof_estimates.csv)
is an **informational reference**. The script was inspected, not executed.
The source URLs, file hashes, parameters, and missing evidence are preserved
in [published-reference.json](experiments/2026-11-27-saom/published-reference.json).

| Effect | Published RSiena | CPU seed 1234 | CPU seed 4321 | Seed 4321 minus published |
| --- | ---: | ---: | ---: | ---: |
| density | -2.6811321870 | -2.6788853059 | -2.6795018987 | +0.0016302883 |
| recip | 2.4631654344 | 2.4560449638 | 2.4543587987 | -0.0088066357 |
| transTrip | 0.6208074718 | 0.6208535320 | 0.6222704319 | +0.0014629602 |

This matching conditional export contains no standard errors, coefficient
covariance, `D`, `msf`, individual convergence ratios, or overall convergence
ratio. It also lacks a saved fitted model and per-run session metadata. The
upstream project reports R 4.6.1 / RSiena 1.6.6 in its environment description,
but this is not a verified session record for the exact CSV. The full effects
table was not exported either. Therefore no uncertainty-aware independent
acceptance tolerance can be justified from that file alone.

Other upstream artifacts refer to unconditional, six-effect, degree-limited,
or altered-missingness fits and cannot supply those missing diagnostics.
The `0.035` convergence number in the upstream GoF comparison belongs to a
separate GPU cusna run, not to the saved RSiena coefficients. The GoF
distribution p-values are not parameter convergence ratios. Accordingly,
**`independent_reference_validated=false` remains mandatory**.

## Tests and remaining acceptance

The base source suite passes **55/55 tests**, and the explicit optional CPU
suite passes **3/3 tests**, with no skips or substituted estimator. The base
tests exercise strict boundaries, malformed/nonnumeric diagnostics, singular
or indefinite matrices, and an admissible nonsymmetric `D`. The optional
suite compares a real adapter fit with a separate direct upstream fit,
rejects inferred symmetric dynamics, and verifies real CLI nonconvergence
with exit code 2. Small synthetic fits remain integration tests.

The executed platform is Linux x86_64 / Python 3.12.14, with cusna 0.1.0,
NumPy 2.3.5, and Numba 0.68.1. Python 3.13 and other platforms are not
qualified by these executions. There is no Actions run or distribution
installation acceptance claim.

Remaining Issue #2 work includes a matching independently converged reference
with uncertainty and session provenance, and explicit upstream directed-mode
control for fully reciprocal observations. Issue #3 tracks qualification of
an empirical cohort, its relationship layers, missingness, and population
boundary. The [Oxford source description](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.htm)
restricts s50 to numerical illustration because it is an incompletely
delineated subset. Numerical convergence cannot remove that limitation.
