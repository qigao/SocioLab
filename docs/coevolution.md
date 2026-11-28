# Joint network and ordinal-behavior fitting

SocioLab implements a bounded D5 model: **one observed directed binary network and one observed ordinal behavior, fitted jointly on a fixed actor panel**. It calls the original `cusna==0.1.0` CPU estimator with one explicit effect profile. The result describes a retrospective model of the supplied waves; numerical convergence does not establish a causal influence effect or forecast accuracy.

This is separate from the existing conditional, network-only `saom` command and from the [annotation-count views](annotations.md). An imported language label or event attribute is not automatically converted into a dependent behavior. The broader design remains in [PR #6](https://github.com/qigao/SocioLab/pull/6) and [Issue #5](https://github.com/qigao/SocioLab/issues/5).

## Run the supplied example

Install the optional upstream dependency and run from the repository root:

```bash
python -m pip install -e '.[saom]'
python -m sociolab coevolution inspect examples/coevolution/synthetic.panel.json examples/coevolution/synthetic.model.json > synthetic-model.json
NUMBA_NUM_THREADS=2 python -m sociolab coevolution fit examples/coevolution/synthetic.panel.json examples/coevolution/synthetic.model.json --seed 1234 --n1 64 --nd 64 --n3 128 --batch2 16 --n2 2 2 2 2 > synthetic-fit.json
```

The [example panel](../examples/coevolution/synthetic.panel.json) combines the original upstream `synthetic_panel(20, mean_degree=4, change_frac=0.25, seed=17)` network with deterministic invented measurements on a five-state scale. It has two waves and 11 fitted parameters. The [builder](../examples/coevolution/build_example.py) records how it is made; it does not generate data from a known joint SAOM or establish parameter recovery.

`inspect` constructs the actual upstream model and reports its targets, parameter order and preprocessing without estimating coefficients. `fit` runs all estimator phases. The small budgets above exercise the runtime; inspect the reported diagnostics before using estimates.

Both commands emit strict JSON on stdout. A valid fitted result returns exit code **0** when the numerical gate passes, or **2** after emitting the result when it does not. Invalid inputs or invalid numerical diagnostics fail instead of being relabeled as a nonconverged fit. There is no automatic retry or budget increase.

With the original [Oxford s50 archive](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.zip) saved as `s50_data.zip`, the same interface uses its observed friendship matrices and alcohol variable:

```bash
python -m sociolab coevolution inspect s50_data.zip examples/coevolution/s50.model.json --format s50 > s50-model.json
NUMBA_NUM_THREADS=2 python -m sociolab coevolution fit s50_data.zip examples/coevolution/s50.model.json --format s50 --seed 1234 > s50-fit.json
```

The s50 case has three waves and 13 parameters. The archive is a numerical teaching example without an appropriate population boundary for empirical influence estimation. The command retains that limitation in its result, together with archive provenance. A successful numerical fit does not remove it.

## Input and measurement contract

The network and behavior observations use the existing `sociolab.longitudinal.v1` panel. Every wave supplies a unique revision, increasing integer `time_index`, explicit complete network observations, directed ties between the same ordered actor set, and one behavior value per actor. Missing network or behavior observations are rejected for this profile; SocioLab does not impute them.

The separate model declaration has exactly this shape:

```json
{
  "schema": "sociolab.coevolution.v1",
  "profile": "directed-selection-similarity-v1",
  "behavior": {
    "variable": "synthetic_ordinal_1_to_5",
    "minimum": 1,
    "maximum": 5,
    "measurement_reference": "synthetic:declared-five-state-scale"
  },
  "research_question": "Exercise the retrospective joint model on invented observations; no empirical inference."
}
```

The behavior variable must exactly match the panel. Bounds are exact integers with `0 <= minimum < maximum <= 2147483647`; booleans, fractional values and null observations are not measurements. Every integer between the bounds is an admissible state, and a behavior ministep moves by one state or leaves the value unchanged. The adapter does not round sentiment scores, embeddings or arbitrary labels into this domain.

Both declared endpoints must occur somewhere in the supplied fitting sample. This restriction is necessary because the pinned upstream constructor infers the allowed range from observed values and offers no supported separate bound argument. SocioLab rejects a sample that would silently narrow the declared scale. Constant behavior therefore cannot qualify this profile. The declaration's measurement reference and research question are required nonempty text; they record the caller's choices without authenticating the source or validating the measurement.

The input is a directed relationship. If every observed matrix is symmetric, cusna automatically chooses an undirected paired-flip process. SocioLab rejects that case rather than altering the inferred upstream model. Reciprocal observations alone do not justify changing the declared relationship semantics.

The full canonical panel and specification receive separate content hashes. Results retain actor order, wave revisions, time indices, origin and source reference. These identify the inputs used; they are not proof that the observations occurred.

## The fixed model and its parameters

`directed-selection-similarity-v1` matches the explicit first model in the pinned upstream [coevolution comparison](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/bench/compare_coevol.py). It uses `conditional=False` and `backend="cpu"`.

| Equation | Effects, in order | Modeled role |
| --- | --- | --- |
| Network evaluation | `density`, `recip`, `transTrip` | Baseline tie tendency, reciprocity and transitive closure |
| Network evaluation with current behavior | `altX`, `egoX`, `simX`, each `dyn=True` | Behavior-related selection through alter value, ego value and similarity |
| Behavior evaluation | `linear`, `quad`, `avSim` | Behavior distribution shape and similarity to outgoing network neighbors |

The alter-based behavior term uses **ego's outgoing neighbors**. The declared tie direction must therefore correspond to the intended exposure relationship. Reversing an information-transmission arrow is not a harmless presentation choice. These coefficients parameterize the upstream stochastic process; they are not standalone change probabilities or identified causal effects.

For `P = number_of_waves - 1`, the vector has **`2P + 9` free parameters**:

```text
network rates for periods 1..P
behavior rates for periods 1..P
density, recip, transTrip, altX, egoX, simX
beh linear, beh quad, beh avSim
```

For three waves, indices 0–1 are network rates, 2–3 behavior rates, 4–9 network evaluation effects, and 10–12 behavior evaluation effects. The machine-readable `model_descriptor.parameter_layout` records each index, block, effect or period, and the period's original time indices. `parameter_names` is checked against the actual upstream model.

Rates are jointly estimated parameters with standard errors in that same vector. `period_rates` exposes those values by observed transition. Their units are opportunities per actor over the transition, including opportunities that leave the state unchanged. They are not observed change counts. Each upstream period has a normalized simulation horizon of one; a gap between `time_index` values is retained as provenance and is not used as a calendar-time denominator.

### Live simulated states and estimation targets

Within a simulated period, network choices use current simulated behavior and behavior choices use the current simulated network. The moments used for estimation follow the upstream cross-lagged conventions:

| Target block | Observed target |
| --- | --- |
| Network rate | Endpoint network Hamming distance in each period |
| Behavior rate | Sum of absolute endpoint behavior differences in each period |
| Network evaluation | End-of-period network evaluated with start-of-period behavior |
| Behavior evaluation | End-of-period behavior evaluated with start-of-period observed network |

The evaluation targets sum across periods. Endpoint distances need not equal latent toggle or behavior-ministep counts because changes can reverse within a period. These conventions are exposed as `target_conventions`; they should not be replaced with statistics computed from both endpoint variables without checking the upstream definition.

Behavior centering uses the mean of the per-wave observed means over all supplied fitting waves. Similarity centering pools distinct ordered actor pairs over all fitting waves except the last; the range uses the full fitting sample. The exact constants are reported in `behavior_preprocessing`. This is retrospective preprocessing, not a qualified held-out or future-data transformation.

## Numerical validity and convergence

The default budgets remain `n1=1000`, `nD=1000`, `n3=4000`, `batch2=256`, and `n2=(40,40,60,80)`, with four phase-two subphases. The default run uses 65,320 **full-panel replicates**. Each replicate contains one simulated path for each observed transition; the simulation count is not an actor count or ministep count. `n3` must exceed the actual parameter count so a full-rank statistic covariance is possible.

The adapter checks the actual returned result before reporting a fit:

- Vectors and matrices have the expected dimensions and finite real numeric values; every free parameter has a positive standard error.
- The final derivative matrix `D` and statistic covariance `msf` have full rank. The covariance must be symmetric and positive definite. Both condition numbers are reported; there is no arbitrary condition-number acceptance threshold.
- All joint basic rates remain positive, the trace starts at the declared upstream initialization and ends at the fitted vector, and names, targets and simulation totals agree with the constructed model.
- An observer around the unchanged CPU simulator checks every period path. Reaching cusna's 4,000,000-ministep ceiling or failing to cross the unconditional unit-period boundary fails the fit. `simulation_diagnostics` records checked path counts and maximum steps; it does not alter simulator outputs.

For a numerically valid result, convergence requires **both**:

```text
max(abs(tconv)) < 0.1
0 <= tconv_max < 0.25
```

These strict thresholds follow [RSiena Manual §7.3.2](https://www.stats.ox.ac.uk/~snijders/siena/RSiena_Manual.pdf). Values equal to a threshold do not pass. The result retains `targets`, `sim_means`, `D`, `msf`, matrix ranks and condition numbers, per-parameter ratios, the overall ratio, and `theta_trace` so the numerical conclusion is inspectable.

`D` is the generally nonsymmetric derivative of the fitted moments. `msf` is the covariance of simulated statistic totals, not a coefficient covariance or a covariance of the Monte Carlo mean. Unlike the conditional network-only command, the joint model does not infer rates from simulated stopping-duration summaries.

`convergence_status` is `CONVERGED` or `NOT_CONVERGED`; `convergence_is_validated` refers only to the explicit `convergence_scope="numerical moment matching only"`. `behavior_coevolution_fitted=true` means the joint estimator ran and produced a numerically valid report, including when it has not converged. Source verification, population qualification, empirical-model qualification, forecast validation and causal identification remain false.

## Python API

```python
from sociolab.panels import load_panel
from sociolab.coevolution_input import load_coevolution_spec
from sociolab.coevolution import coevolution_model_report, fit_coevolution_saom

panel = load_panel("examples/coevolution/synthetic.panel.json")
spec = load_coevolution_spec("examples/coevolution/synthetic.model.json")
model = coevolution_model_report(panel, spec)
result = fit_coevolution_saom(
    panel, spec, seed=1234,
    n1=64, nD=64, n3=128, batch2=16, n2=(2, 2, 2, 2),
)
print(result["parameter_names"])
print(result["convergence_status"], result["period_rates"])
```

`CoevolutionSpec` and `validate_coevolution_input` live in `sociolab.coevolution_input`; the latter returns a fresh behavior matrix ordered by panel actors and waves. `coevolution_model_report` and `fit_coevolution_saom` live in `sociolab.coevolution`. The optional cusna dependency is required for inspection as well as fitting. Base native tests do not require cusna. Genuine CPU integration tests are explicitly opted into; a missing optional dependency is an error in this selected suite:

```bash
NUMBA_NUM_THREADS=2 python -m unittest discover -s tests/saom_runtime -v
```

## Reference evidence and remaining limits

The implementation is tied to installed cusna 0.1.0. Its data, statistics, CPU and estimator source matches the text at upstream commit [`313c3d2`](https://github.com/artemmaltsev74-techcom/cusna/tree/313c3d2623c99ed15c1eb6fe713593c6d3915d1d); line-ending differences do not change that source comparison. Current upstream main is not silently substituted.

The focused runtime tests compare a real adapter fit with a fresh direct `MomEstimator` using identical observations and settings. That establishes API and result consistency. It is separate from an independent implementation comparison.

The upstream repository also retains an [RSiena script](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/bench/rsiena_coevol.R), named coefficient/standard-error/target exports, and 3,000 simulation-statistic rows for this s50 profile. Those permit an exact target/order check and a fixed-parameter comparison of CPU simulated means with the retained export. The original published comparison used GPU. The repository states RSiena 1.6.6 generally, but the retained case-specific exports do not include exact runtime/session metadata or full convergence diagnostics. RSiena is not rerun here. Agreement of selected moment means does not prove equality of the complete simulated distribution, and coefficient standard errors are not Monte Carlo errors of independent fitted estimates. Therefore `independent_reference_validated` remains false.

### Measured s50 results on 2026-11-27

The actual CPU fit with seed 1234 and unchanged default budgets **passed the numerical moment-matching gate**. There was no automatic retry or budget retuning. The [raw fit](experiments/2026-11-27-coevolution/s50-seed1234-fit.json), [execution metadata](experiments/2026-11-27-coevolution/s50-seed1234-execution.json) and [verification](experiments/2026-11-27-coevolution/s50-seed1234-verification.json) retain the full evidence:

| Quantity | Recorded result |
| --- | --- |
| Maximum absolute individual convergence ratio | `0.043212643139310135` |
| Overall convergence ratio | `0.09196326022522965` |
| Derivative / statistic covariance rank | `13 / 13`, for 13 parameters |
| Derivative / statistic covariance condition number | `1815.625118597342 / 1714.0097493449045` |
| Full-panel replicates | `65,320` |
| Audited period paths | `130,640` across two transitions |
| Maximum ministeps in a path, by period | `475 / 424`; no step-limit truncation detected |
| Wall time with two Numba threads | `163.797588` seconds |

Verification reconstructs the individual ratios, overall ratio and standard errors from the retained moments, derivative and covariance. The reconstructed standard errors match exactly. The raw CLI output predates one metadata wording correction: `neighbor_direction` now says "ego's outgoing network ties", omitting "observed" because the within-period simulator uses the current network. Verification records both source hashes, checks that this string is the only source difference, and reassesses the numerical arrays under the final code. The original fit JSON is preserved unchanged.

The [published-reference check](experiments/2026-11-27-coevolution/published-reference.json) found maximum absolute target difference `1.1368683772161603e-13`. At the published parameter vector, a separate [CPU simulation comparison](experiments/2026-11-27-coevolution/cpu-reference-simulation.json) used 3,000 full-panel replicates with seed 2024 against the retained 3,000 RSiena replicates with seed 654. The maximum absolute standardized mean difference was `2.3726225747998333`, below the predeclared 13-comparison, family-alpha-0.05 Bonferroni normal critical value `2.890511560691739`. All approximate simultaneous intervals for the differences in these 13 statistic means included zero. This records no detected mean discrepancy under that screen; it does not establish full distribution equivalence or qualify an independent fitted model. The simulation checked 6,000 period paths, with maximum 462 ministeps, and took 8.193883 seconds.

Additional artifacts retain the [model and targets](experiments/2026-11-27-coevolution/s50-model.json) and [validation record](experiments/2026-11-27-coevolution/validation.json). Numerical success leaves the source, population, empirical, forecast and causal limitations above in place.

### Reproduce the evidence

The [qualification script](experiments/2026-11-27-coevolution/run_qualification.py) requires the original Oxford ZIP and a local cusna checkout at exactly `313c3d2623c99ed15c1eb6fe713593c6d3915d1d`. It checks the checkout commit, installed source text and source-array identity. It does not download data or execute R. After installing `.[saom]`, run from the repository root and replace the three paths below with your locations:

```bash
COEVOLUTION_ARCHIVE=/absolute/path/to/s50_data.zip
COEVOLUTION_UPSTREAM=/absolute/path/to/pinned-cusna-checkout
COEVOLUTION_OUTPUT=/absolute/path/to/new-coevolution-results

NUMBA_NUM_THREADS=2 python docs/experiments/2026-11-27-coevolution/run_qualification.py reference --archive "$COEVOLUTION_ARCHIVE" --upstream "$COEVOLUTION_UPSTREAM" --output "$COEVOLUTION_OUTPUT"
NUMBA_NUM_THREADS=2 python docs/experiments/2026-11-27-coevolution/run_qualification.py fit --archive "$COEVOLUTION_ARCHIVE" --upstream "$COEVOLUTION_UPSTREAM" --output "$COEVOLUTION_OUTPUT"
python docs/experiments/2026-11-27-coevolution/run_qualification.py verify --archive "$COEVOLUTION_ARCHIVE" --upstream "$COEVOLUTION_UPSTREAM" --output "$COEVOLUTION_OUTPUT"
```

`reference` writes the model/target comparison and runs the fixed-parameter CPU simulation. `fit` invokes the real CLI with seed 1234 and default budgets, preserving stdout, stderr, exit status, timing and input/source hashes. `verify` reads those retained outputs, checks the source relationship, reassesses diagnostics and records informational coefficient differences; it performs no additional fit. Use the same output directory for all three modes. Runtime depends on the machine and compilation-cache state.

This profile does not admit changing actor composition, multiple dependent networks, multiple behaviors, signed or bipartite ties, incomplete panels, alternate behavior-effect menus, or nonbasic rate effects. Some features exist in other upstream paths; they are not part of this adapter's qualified scope. There is no automatic annotation-to-panel conversion, future-period prediction command or causal intervention estimator. A future forecast would require past-only preprocessing, explicit future rate/exposure assumptions and held-out assessment; a causal interpretation additionally requires a defensible identification design.

The separate [past-only forecast profile](behavior-forecast.md) now creates
persistence and OLS point predictions from a historical panel, then scores a
separate target. It does not use fitted SAOM parameters, all-wave preprocessing
or SAOM future-rate assumptions. Its s50 numerical holdout does not change the
joint model's forecast or causal qualification flags.
