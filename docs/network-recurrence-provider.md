# Upstream provider for network-feature recurrence comparisons

The bounded R2 comparison uses an **optional, pinned scikit-learn 1.9.1
provider** for regularized binary prediction of released archive records. This
is a logistic classifier with historical network features. It does not estimate
a relational-event waiting-time likelihood, establish real communication
coverage, identify motives, or identify causal effects.

The source/API audit is recorded in
[`provider-audit.json`](experiments/2026-11-28-dept2-network/provider-audit.json).
That file captures the environment **before installation**. Its missing-package
entries are a historical checkpoint, not a claim about the environment used by
a later execution. Actual execution must record its own runtime versions and
outcome. No provider was installed or executed as part of this audit.

## Selection and dependency boundary

SocioLab delegates fitting and probability prediction to the upstream estimator;
it does not implement another optimizer, logistic-loss engine, graph engine or
simulation world. Network features use the existing NetworkX dependency.
scikit-learn is a study-specific optional dependency, separate from the base
package and the existing `saom` extra. The provider is imported only for the
comparison that needs it. A missing provider is an explicit unsupported-runtime
result or clear invocation error, never a fallback to another estimator.

The selected release is **`scikit-learn==1.9.1`**. Its annotated release tag
`f0668270731746c1b4517f0e9e2cd5b8c2ba3784` resolves to commit
`866c0f51e7560ef0303cbcc5f159df5382ea9e3f`. The
[pinned package metadata](https://github.com/scikit-learn/scikit-learn/blob/866c0f51e7560ef0303cbcc5f159df5382ea9e3f/pyproject.toml)
declares BSD-3-Clause licensing and Python >=3.11, with explicit Python 3.12 and
3.13 classifiers. These satisfy SocioLab's declared Python range; they do not
replace an execution check in the actual study environment.

| Upstream runtime dependency | Declared minimum |
| --- | --- |
| NumPy | 1.24.1 |
| SciPy | 1.10.0 |
| joblib | 1.4.0 |
| narwhals | 2.0.1 |
| threadpoolctl | 3.5.0 |

The pre-installation environment contains Python 3.12.14, NumPy 2.5.5, SciPy
1.18.1 and narwhals 2.29.0. It lacks scikit-learn, joblib and threadpoolctl.
Existing versions and metadata were inspected without installing packages or
running an installer/consumer test suite. Dependencies and the exact runtime
used for any later execution must be recorded separately.

## Model and optimizer contract

The adapter uses `sklearn.linear_model.LogisticRegression` with the configuration
frozen in the experiment protocol. The selected family uses `solver="lbfgs"`,
`l1_ratio=0.0`, `fit_intercept=True`, `class_weight=None` and
`warm_start=False`; the protocol supplies the fixed `C`, tolerance and iteration
budget. Fit parameters cannot be changed in response to held-out results.

The
[pinned estimator source](https://github.com/scikit-learn/scikit-learn/blob/866c0f51e7560ef0303cbcc5f159df5382ea9e3f/sklearn/linear_model/_logistic.py)
supplies binary logistic loss, its gradient and the L2 penalty, and calls the
upstream SciPy L-BFGS-B optimizer. With sample weights summing to `S`, it passes
an L2 coefficient of `1 / (C * S)` to its mean-loss implementation. Thus a fixed
`C` must not be described as a sample-size-independent coefficient on the
mean-loss penalty. The initial comparison gives each training pair-origin row
equal weight and does not rebalance classes.

Version 1.9.1 API details matter:

- `penalty` is deprecated. Select L2 using `l1_ratio=0.0`, leaving `penalty` at
  its default. Do not copy an older `penalty="l2"` recipe into this provider.
- `n_jobs` is deprecated and unnecessary for this bounded fit. Do not set it.
- Probability columns follow `classes_`. Validate that the training labels are
  exactly the binary classes 0 and 1, and select the column corresponding to 1.
- The `lbfgs` solver does not use `random_state` to shuffle training examples.
  A seed is not evidence of cross-platform, bit-for-bit numerical identity.
- Use ordinary dense CPU float64 arrays. Record package versions, array shape,
  feature order, model configuration, fitted coefficients and iteration counts
  with the training identity. Numerical reproduction across environments uses
  a declared tolerance rather than an assumed identical floating-point hash.

The [versioned estimator documentation](https://scikit-learn.org/1.9/modules/generated/sklearn.linear_model.LogisticRegression.html)
describes the public API. The fixed commit above is the authority for the
implementation reviewed here; later development versions can change it.

## Missing values, scaling and failure handling

SocioLab validates finite features and labels **before preprocessing**. A known
zero count in the released archive can be represented by zero under this
study's measurement contract. Unknown membership, missing real observation
coverage and an unmeasured covariate cannot be converted into zero.

[`StandardScaler`](https://scikit-learn.org/1.9/modules/generated/sklearn.preprocessing.StandardScaler.html)
fits its feature means and scales on the training matrix only; those fitted
values transform future matrices. Training-origin features themselves use only
their own historical records. A constant training feature receives scale 1
upstream. The scaler can disregard NaNs during fitting and preserve them during
transformation, so scaler success is not a completeness check. The adapter
rejects nonfinite inputs instead of adding an imputer or silently dropping
examples. Upstream
[`check_array`](https://scikit-learn.org/1.9/modules/generated/sklearn.utils.check_array.html)
normally requires a finite, nonempty array; LogisticRegression invokes input
validation before fitting.

| Condition | Required study handling |
| --- | --- |
| Missing or incompatible pinned provider | Clear unsupported-runtime outcome or invocation error; no substitution |
| Empty training matrix | Retain the planned fit as not estimable |
| Only one training label class | Retain not-estimable status and class counts; no artificial labels |
| Unknown or nonfinite feature/label | Reject the affected input; no imputation or row deletion |
| Upstream convergence warning | Retain failed fit and warning evidence; no qualified forecast from that fit |
| Nonfinite or malformed fitted output | Retain failed fit; no probability clipping to disguise the failure |

In the pinned estimator, a single training class raises `ValueError`. The
[pinned convergence helper](https://github.com/scikit-learn/scikit-learn/blob/866c0f51e7560ef0303cbcc5f159df5382ea9e3f/sklearn/utils/optimize.py)
emits `ConvergenceWarning` when the SciPy optimization result has a nonzero
status. The study captures the warning category/text and available `n_iter_`.
It does not retry with a different solver, tolerance, iteration limit,
regularization or feature set after seeing targets. Planned failures remain in
the report even if other candidates succeed. A warning-free finite fit establishes
only numerical completion, not predictive adequacy or scientific validity.

## Training, evaluation and interpretation

All training target windows must close by the declared fit cutoff. The risk
set and features of each training row are reconstructed at that row's own
origin; the later fit cutoff does not permit its features to see its target.
Scaling and fitting use training rows only. Online feature refreshes use the
same declared history and frozen fitted model as batch replay; a timer tick
does not silently retrain or change the model identity.

The same archive target and eligible pair-origin observations are used for
the fitted candidates and existing count/recency baselines. Reuse existing
Brier and fixed probability-bin arithmetic. Retain planned origin counts,
failures and model-specific scoring denominators. A common successful subset,
if reported, must be named explicitly rather than presented as the full plan.
Avoid shuffled pair-level cross-validation: repeated pairs and historical
windows are dependent. These scores do not supply independent-observation
standard errors or causal estimates.

The [upstream calibration guide](https://scikit-learn.org/1.9/modules/calibration.html)
explains that probability quality and calibration are distinct: a lower Brier
score can reflect improved discrimination without improved calibration. A
logistic model's probability output therefore still needs held-out diagnostics.
This initial provider adds no fitted post-processing calibrator. A later
calibration experiment needs its own separated fitting/calibration/evaluation
periods and protocol.

Adding reciprocal or neighborhood features tests whether that stated
historical information helps predict archive records. A coefficient is not a
measured motive, an identified effect of a network intervention, or proof of
true relationship persistence. Archive gaps remain archive gaps unless
separate source evidence establishes their real cause.

## Alternatives reviewed

| Candidate | Decision for this bounded comparison |
| --- | --- |
| scikit-learn 1.9.1 | Selected optional complete estimator; public fit/probability API and reviewed numerical-failure behavior |
| Already-installed SciPy 1.18.1 | Reused indirectly by the selected upstream estimator; direct `minimize` would leave logistic estimator and derivative implementation to SocioLab |
| statsmodels 0.15.0 | Viable alternative, not installed or selected; adding a second estimator provider is unnecessary for the initial comparison |

SciPy's [`minimize` contract](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)
accepts a caller-provided objective and optional derivatives; it is not itself a
logistic estimator. Statsmodels
[release metadata](https://pypi.org/project/statsmodels/0.15.0/) declares Python
>=3.10, explicit Python 3.12/3.13 support and BSD-3-Clause licensing. Its
[regularized GLM](https://www.statsmodels.org/stable/generated/statsmodels.genmod.generalized_linear_model.GLM.fit_regularized.html)
supports an L2 component with a different penalty parameterization. Its
[missing-data documentation](https://www.statsmodels.org/stable/missing.html)
requires an explicit `missing="raise"` policy to avoid the default absence of
missing-value checks. These are source-review observations, not a runtime
qualification of statsmodels or a claim of numerical parity with sklearn.
