# Partially observed directed networks

SocioLab's `sociolab.partial-network.v1` contract records **observed present**, **observed absent**, and **unknown** dyads on one fixed actor roster. A dyad omitted from both explicit observation sets is unknown. The format supports one directed binary relationship across multiple observation waves.

The `partial` commands provide three separate results: native observation counts, inspection of the actual upstream missing-data model, and a conditional CPU fit. Source declarations, initialization, numerical convergence and empirical qualification remain distinct throughout this path.

The fitting profile is experimental. The recorded fixed-parameter CPU comparison detects differences from the retained RSiena reference in two moment means; independent reference qualification remains open. The observation-counting contract does not depend on estimator equivalence. See the [benchmark evidence](#pinned-benchmark-evidence) below.

## Commands and results

| Command | Work performed | Result kind | Optional cusna required? |
| --- | --- | --- | --- |
| `partial inspect` | Counts source observations and all nine endpoint transitions | `PARTIAL_NETWORK_OBSERVATION_REPORT` | No |
| `partial model` | Constructs the original upstream data/model objects and reports initialization, masks and targets; performs no simulation or fit | `PARTIAL_NETWORK_SAOM_MODEL` | Yes |
| `partial fit` | Runs the original conditional CPU estimator with path and numerical diagnostics | `PARTIAL_NETWORK_SAOM_FIT` | Yes |

Run the checked-in observation example from the repository root:

```bash
python -m pip install -e .
python -m sociolab partial inspect examples/partial/coverage.panel.json > coverage-report.json
```

To inspect the upstream model for that same input:

```bash
python -m pip install -e '.[saom]'
python -m sociolab partial model examples/partial/coverage.panel.json > coverage-model.json
```

The four-actor example exercises observation semantics and model construction. It does not establish sufficient information for a numerically usable three-parameter fit. For a separately prepared panel that meets the model's guards, the fitting interface is:

```bash
NUMBA_NUM_THREADS=2 python -m sociolab partial fit /path/to/partial-panel.json --seed 1234 > partial-fit.json
```

Default budgets are `n1=1000`, `nD=1000`, `n3=4000`, `batch2=256`, and `n2=(40,40,60,80)`. The CLI exposes `--n1`, `--nd`, `--n3`, `--batch2`, and `--n2` followed by four integers. Seeds are nonnegative exact integers; simulation budgets are positive exact integers, and `n3` must exceed the three free effects. Reduced budgets exercise the software with less simulation; they do not establish accuracy or qualification.

## Exact input contract

The [synthetic example](../examples/partial/coverage.panel.json) has the complete accepted shape:

```json
{
  "schema": "sociolab.partial-network.v1",
  "dataset_id": "synthetic-four-person-nine-transitions",
  "origin": "synthetic",
  "source_reference": null,
  "actors": ["A", "B", "C", "D"],
  "relation": "synthetic_directed_tie",
  "population_definition": "Four invented actors have fixed eligibility at both observation times.",
  "observation_definition": "The two listed sets are invented endpoint observations; all other directed offdiagonal pairs are unknown.",
  "waves": [
    {
      "time_index": 0,
      "source_revision": "synthetic-nine-transitions-w0",
      "observed_present": [["B", "A"], ["B", "C"], ["B", "D"]],
      "observed_absent": [["A", "B"], ["A", "C"], ["A", "D"]]
    },
    {
      "time_index": 1,
      "source_revision": "synthetic-nine-transitions-w1",
      "observed_present": [["A", "C"], ["B", "C"], ["C", "B"]],
      "observed_absent": [["A", "B"], ["B", "A"], ["C", "A"]]
    }
  ]
}
```

For the actor roster `actors`, the observation universe contains all `n * (n - 1)` ordered pairs of distinct actors. Each pair has exactly one state at each wave:

| Representation | State | Required interpretation |
| --- | --- | --- |
| Listed in `observed_present` | Present | An explicit positive observation of this directed relationship |
| Listed in `observed_absent` | Absent | An explicit negative observation within the declared population and observation scope |
| Listed in neither set | Unknown | The input supplies no observed binary state for that dyad at this wave |

The two lists are disjoint. Both must be supplied, even when empty. A fully unknown wave is represented by two empty lists; a fully observed wave has every nonself dyad in exactly one list. There is no `network_complete` switch or default-zero interpretation.

An unknown `A -> B` can coexist with an observed `B -> A`. An actor's missing outgoing survey responses do not erase known incoming nominations. The importer never propagates an unknown row into the corresponding column, removes an actor, or renumbers identities.

### Validation and bounds

| Field or boundary | Validation |
| --- | --- |
| Envelope and wave objects | Exactly the fields shown above; unknown or missing fields fail |
| Actor roster | 2–500 nonempty, trimmed UTF-8 strings, unique and sorted; identical for every wave |
| Relationship | One nonempty, trimmed UTF-8 name, carried unchanged as a declaration |
| Scope declarations | `population_definition` and `observation_definition` are required nonempty, trimmed UTF-8 strings |
| Waves | 2–20 waves in strictly increasing `time_index` order |
| Time indices | Nonnegative exact integers; booleans and fractional values fail |
| Revisions | Nonempty, trimmed UTF-8 strings, unique across waves |
| Directed pairs | Two-element lists of known actor IDs, unique and lexicographically sorted within each observation set |
| Diagonal | Self dyads fail in either observation set, including explicitly absent self dyads |
| Total observations | At most 1,000,000 records across all present and absent lists and all waves |
| JSON file | At most 64 MiB, or 67,108,864 bytes; UTF-8; duplicate object keys and nonfinite numeric constants fail |

`origin="synthetic"` requires `source_reference=null`. `origin="external_observation"` requires an HTTPS reference. The parser checks the declaration's form; it does not authenticate the citation, measurement, cohort selection or eligibility boundary.

The two scope definitions should explain who belongs to the analysis population throughout the periods and what source evidence establishes positive and negative observations. Survey nonresponse, item nonresponse and unavailable measurements may leave dyads unknown within that population. Actual joining/leaving, structural impossibility and an alter being ineligible for nomination are different conditions: this fixed-cohort profile has no representation or model for them. Encoding those conditions as `NaN` would make the affected dyads eligible for latent changes under a different assumption.

The computed `content_hash` covers every canonical input field, including explicit absences, actor identities, scope declarations, source reference and wave revisions. Removing an absence changes a dyad to unknown and changes the hash. The hash identifies the declared panel; fingerprints and interpretation of original source files belong in accompanying provenance evidence. No raw-source fingerprint or verification claim is inferred from an HTTPS reference.

## Nine endpoint transitions

`partial inspect` constructs no graph and performs no imputation. Its `transition_counts` classify every directed nonself dyad by its two endpoint states. For the four-actor example, the complete table is:

| Before / after | Absent | Present | Unknown |
| --- | ---: | ---: | ---: |
| Absent | 1 | 1 | 1 |
| Present | 1 | 1 | 1 |
| Unknown | 1 | 1 | 4 |

The nine cells' counts sum to the twelve possible directed nonself dyads. Each wave contains three observed present dyads, three observed absent dyads and six unknown dyads. The report distinguishes:

- **One observed addition:** absent at the first endpoint and present at the second.
- **One observed removal:** present at the first endpoint and absent at the second.
- **Two dyads gaining coverage:** unknown becomes observed absent or observed present.
- **Two dyads losing coverage:** an observed state becomes unknown.
- **Four dyads known at both endpoints**, giving an observed Hamming distance of **two**.

The positive count stays **3 → 3**. Its change decomposes into observed additions minus removals, plus unknown-to-present minus present-to-unknown. A positive-count difference alone cannot distinguish changes in known dyads from changes in coverage.

The API calls these classifications `observed_additions` and `observed_removals`. They describe endpoint differences. They do not count intermediate events, identify when a tie changed, or establish that a dyad with equal endpoint states remained unchanged throughout the interval. No causal attribution follows from these counts.

`time_index` preserves wave order and the supplied index values. Gaps between indices do not establish calendar durations or intermediate observation times.

## Upstream missing-data model

The fixed profile is `directed-fixed-cohort-missing-network-v1`: **cusna 0.1.0, conditional method of moments, CPU**, with `density`, `recip` and `transTrip` in that order. There are **three free evaluation coefficients**, regardless of the number of periods. Behavior, composition, structural zeros/ones, covariates and multiplex networks are outside this profile.

The source review is pinned to upstream commit [`313c3d2623c99ed15c1eb6fe713593c6d3915d1d`](https://github.com/artemmaltsev74-techcom/cusna/tree/313c3d2623c99ed15c1eb6fe713593c6d3915d1d). The installed package's relevant source was compared with those files; the recorded comparison accounts for CRLF/LF line endings. The adapter also checks the installed distribution version.

### Observations, initialization, targets and latent states

| Stage | Treatment of an unknown source dyad |
| --- | --- |
| SocioLab boundary | A fresh float matrix contains `NaN`; explicitly observed states become exactly `0` or `1` |
| Upstream initialization | First-wave missing cells initialize to zero; later missing cells recursively carry forward the previous initialized value |
| Period distance and moments | A dyad missing at either endpoint is excluded by the period masks; the masked statistic network uses zero at those positions |
| Latent CPU simulation | Missing dyads remain eligible to toggle and can affect the evolving network |

These are separate representations. A missing dyad initialized to one remains unknown in the source report. Setting it to zero in a statistic network does not establish an observed absence. This path does not estimate a survey response mechanism or validate assumptions about why values are missing.

The [pinned data implementation](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/data.py) defines initialization, directed missing masks, observed distance, statistic masks and permitted ties. SocioLab verifies that the upstream mask equals the source `NaN` pattern and that initialization preserves every known observation, including incoming observations for an actor whose outgoing row is unknown.

For each period, the conditional target distance is the number of observed `0 -> 1` plus `1 -> 0` endpoint differences on dyads known at both endpoints. Unknown-to-known transitions do not contribute to that distance. Moment targets evaluate the masked end-of-period network; the three effect totals are summed across periods by the [pinned estimator](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/mom.py).

`partial model` exposes the original upstream values: per-period `moment_targets`, summed `targets`, conditional target distances, known overlap, unknown dyads at either endpoint, and which dyads remain permitted to toggle. Its `initialization` block reports how many unknown cells initialize to zero or one. The nested `input` remains the native observation report.

### Model admission guards

Native inspection accepts wholly unknown waves and zero-distance comparisons. Both `partial model` and `partial fit` require **positive known overlap and positive observed Hamming distance in every adjacent period**. A wholly unknown wave necessarily fails these checks. A period with known observations but only coverage changes also fails when its observed distance is zero.

The positive-distance restriction matters for the pinned conditional CPU loop: it performs a ministep before checking the stopping condition. This adapter does not pass a zero target through that loop or substitute another estimator regime. See the [original CPU implementation](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/cpu.py).

Cusna infers symmetric dynamics when every wave's values, missingness mask and structural mask are symmetric. SocioLab rejects that inferred mode for this directed profile. An asymmetric missingness mask remains asymmetric; reciprocal observed ties alone do not authorize paired undirected updates.

The adapter checks the three-parameter layout, absence of structural ties/behavior/composition, exact period distance, and agreement between source known-overlap counts and upstream distance/statistic masks. Passing these guards establishes a supported model construction. Source and population qualification remain separate.

## Fit diagnostics and CPU path audit

`partial fit` observes the original CPU simulator without replacing its algorithm, changing its output or modifying its random state. Every returned path must have a finite positive stopping duration, a positive integer ministep count strictly below the pinned **4,000,000-step cap**, and both its running and final-state masked distances equal to the period's exact target. A path that reaches the cap fails even if its final distance happens to match. Each period's audited path count must also agree with the estimator's reported full-panel replicate count.

`cpu_path_audit` retains per-period target distances, path and batch counts, maximum steps, and minimum/maximum durations. The conditional process stops at its target distance; it is not required to cross a unit-time boundary. The audit therefore checks positive finite duration rather than applying the unconditional model's time-horizon rule.

`rate_est` contains the per-period means of simulated stopping durations from the final simulation phase. `rate_sd` is their **standard deviation with `ddof=0`**, not a rate standard error. These duration summaries are separate from the three evaluation coefficients and their standard errors. They are not calendar-day rates, and gaps in `time_index` do not rescale them. `n_simulations` counts full-panel replicates; each replicate includes one path per period.

The numerical screen preserves the established [SAOM diagnostic policy](saom-numerical-validation.md): finite numeric vectors and matrices of the expected sizes, positive coefficient standard errors, full-rank derivative `D` and statistic covariance `msf`, symmetric positive-definite `msf`, and finite matrix condition numbers. There is no arbitrary condition-number cutoff or local regularization. Here coefficient vectors have length three, `D` and `msf` are `3 x 3`, and duration vectors have one entry per period. The fitted targets must equal those inspected before estimation.

A numerically valid report passes the convergence screen only when both conditions hold:

```text
max(abs(tconv)) < 0.1
0 <= tconv_max < 0.25
```

`convergence_is_validated` refers to **numerical moment matching only**. Model and fit reports retain `source_claim_verified=false`, `population_boundary_qualified=false`, `empirical_admitted=false`, `independent_reference_validated=false` and `causal_effect_identified=false`. The adapter supplies no automatic retry, replacement estimate or missingness-mechanism qualification.

### Exit status

| Outcome | JSON result | CLI exit |
| --- | --- | ---: |
| Valid native observation report | Observation counts; no model qualification | 0 |
| Valid upstream model inspection | Initialization, masks and targets; `model_fitted=false` | 0 |
| Numerically valid fit that passes the convergence screen | `CONVERGED` fit report | 0 |
| Numerically valid fit that fails the convergence screen | `NOT_CONVERGED` fit report is still emitted | 2 |
| Malformed input or an explicit model, path or diagnostic validation failure | Error on stderr; no usable fit report | 2 |

Missing optional dependencies and other uncaught upstream failures propagate as errors. The Python fitting function returns valid nonconverged reports, so API callers must inspect `convergence_status` themselves. A successful process exit does not authenticate the dataset or admit an empirical study.

## Python interface

```python
from sociolab.partial_panels import load_partial_panel
from sociolab.partial_changes import partial_panel_report
from sociolab.partial_saom import partial_network_model_report

panel = load_partial_panel("examples/partial/coverage.panel.json")
observations = partial_panel_report(panel)
model = partial_network_model_report(panel)
print(observations["periods"][0]["transition_counts"])
print(model["targets"], model["model_fitted"])
```

`PartialNetworkPanel.from_mapping(mapping)` accepts the JSON structure above. Its immutable direct constructor takes `dataset_id`, `origin`, `source_reference`, `actors`, `relation`, `population_definition`, `observation_definition`, and `waves`. Direct construction requires tuples for the roster and waves. Each `PartialNetworkWave(time_index, source_revision, observed_present, observed_absent)` uses tuples of directed-pair tuples. Direct constructors perform the same semantic validation as the JSON loader.

`to_dict()` returns a fresh JSON-compatible structure; mutating it or the original input mapping cannot change the panel. `content_hash` returns its canonical SHA-256. `partial_saom_wave_matrices(panel)` returns independent float matrices, ordered by the global actor roster and wave order. It prepares data without performing estimation. `fit_partial_network_saom(panel, ...)` uses the same explicit budgets as the CLI; its Python keyword for the derivative-phase budget is `nD`.

## Pinned benchmark evidence

The upstream [missing-data generator](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/bench/make_missing_data.py) introduces artificial missingness into the s50 teaching example. Its [RSiena reference script](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/bench/rsiena_missing.R) uses the same conditional three-effect model. These are reference sources; SocioLab does not add an R runtime.

The [recorded source and constructor review](experiments/2026-11-27-partial-network/source-review.json) verifies the following deterministic input/mask/target quantities:

| Quantity | Recorded value |
| --- | --- |
| Unknown nonself dyads in waves 1, 2, 3 | `0, 107, 104` |
| Known overlap in periods 1, 2 | `2343, 2247` |
| Conditional observed distances | `113, 98` |
| Period-1 moments: density, recip, transTrip | `114, 68, 81` |
| Period-2 moments: density, recip, transTrip | `115, 80, 108` |
| Summed targets | `229, 148, 189` |

The [actual CLI model report](experiments/2026-11-27-partial-network/reference-model.json) and [input provenance](experiments/2026-11-27-partial-network/reference-provenance.json) reproduce those quantities using the new explicit sets. The original matrices and the transformed row-level panel are not committed. The qualification runner verifies all 17 downloaded reference files by byte count and SHA-256 and checks the four installed engine modules against their pinned source after newline normalization.

### Fixed-parameter CPU comparison: differences detected

The [separate CPU experiment](experiments/2026-11-27-partial-network/cpu-reference-simulation.json) starts a fresh original estimator at the retained RSiena coefficients `[-2.65831340351818, 2.47103651029328, 0.613095696581655]`, with CPU seed `2024` and 3,000 full-panel replicates. It compares centered statistic totals with the 3,000 rows of `miss_sf.csv`, generated by the retained conditional RSiena simulation script with seed `654`. The `V1/V2/V3` columns are bound to the verified named estimate/target order `density/recip/transTrip`.

| Effect | CPU mean deviation | Retained reference mean deviation | Difference | Approximate simultaneous interval for the difference |
| --- | ---: | ---: | ---: | --- |
| density | 2.264000 | 0.940667 | 1.323333 | `[0.033876, 2.612790]` |
| recip | 1.529333 | 0.236667 | 1.292667 | `[0.122278, 2.463055]` |
| transTrip | 6.220667 | 4.096667 | 2.124000 | `[-1.486627, 5.734627]` |

For each effect, the difference's Monte Carlo standard error is `sqrt(var_cpu / 3000 + var_reference / 3000)`, using sample variances with `ddof=1`. The predeclared two-sided Bonferroni normal critical value is `2.3939797998185104`, for three means and family alpha `0.05`. This is an approximate independent-replicate mean screen; it measures Monte Carlo uncertainty at that fixed coefficient vector, not observational or parameter uncertainty.

**The density and reciprocity intervals exclude zero.** Their standardized differences are `2.456874` and `2.644095`; the transitive-triplet difference is `1.408291`. This run therefore does not pass the limited mean screen. The result is retained without changing the seed, adding retries or relaxing the criterion. It does not alone identify the cause of the discrepancy or establish the size of any general implementation error. A complete independent model qualification needs more than this comparison; even intervals including zero would not constitute an equivalence test.

All 6,000 original CPU period paths reached their exact observed targets below the step cap; their maximum step counts were 615 and 452. CPU conditional duration means were `6.490674` and `5.000282`, compared with retained means `6.510827` and `5.026041`. The reference contains no duration samples or variances, so these differences are descriptive and receive no significance test.

The reference exports individual coefficient convergence ratios and standard errors, but does not retain the exact RSiena version/session, overall convergence value, full coefficient covariance or fitted object. The published `comparison_missing.md` uses the GPU backend and cannot qualify this CPU adapter. `independent_reference_validated=false` remains explicit. Artificial missingness on s50 does not establish a general observation mechanism or a valid empirical population boundary.

### One full-default CPU fit: numerical screen passed

The [unchanged CLI fit output](experiments/2026-11-27-partial-network/s50-missing-seed1234-fit.json) comes from a separate fresh estimator, seed `1234`, two Numba threads, and the default budgets above. The [execution record](experiments/2026-11-27-partial-network/s50-missing-seed1234-execution.json) retains source hashes, stdout/stderr hashes and process status. This single run took **232.118 seconds**, returned **exit 0**, and performed **65,320 full-panel replicates**. No retry or search for a converged seed was used.

| Effect | Estimate | Standard error | Individual convergence ratio |
| --- | ---: | ---: | ---: |
| density | -2.660497 | 0.124702 | -0.009233 |
| recip | 2.482285 | 0.220121 | -0.025774 |
| transTrip | 0.605817 | 0.078759 | -0.020953 |

The maximum absolute individual ratio is **0.025773897609799014** and the overall ratio is **0.04732571848803804**. Both `D` and `msf` have rank three; their condition numbers are about **53.90** and **131.94**, and `msf` is positive definite. The [arithmetic verification](experiments/2026-11-27-partial-network/s50-missing-seed1234-verification.json) reproduces the saved SEs and all ratios from the matrices, without refitting or modifying results.

Every one of the **130,640 period paths** reached its masked target below the upstream cap. Maximum step counts were **683** and **500**. Final-phase conditional mean durations were `6.567046` and `5.045577`, with duration SDs `1.127130` and `0.877535`; the SDs are not coefficient or rate standard errors.

This is successful numerical moment matching within the original CPU estimator. It does not supersede the fixed-parameter discrepancies above, establish estimator equivalence or admit the s50 excerpt or Mauldin as an empirical population. The fit retains all empirical, source, independent-reference and causal qualification flags as false.

### Tests and independent review

The [validation record](experiments/2026-11-27-partial-network/validation.json) records **244 native tests** and **9 genuine CPU integration tests**, all passing without skips. The new native tests exercise the exact input contract, nine-cell counts, directed observation semantics, CLI failures and conditional path guards. The new runtime tests compare the adapter with a separate fresh original cusna estimator on a predetermined synthetic missingness pattern; estimates, diagnostics, durations and traces agree within `1e-9`. Direct upstream phase-3 final networks also independently reach their masked distance targets.

The [reference arithmetic review](experiments/2026-11-27-partial-network/reference-arithmetic-verification.json) independently recomputes all retained reference means and sample variances using Python's standard library, then recomputes the differences and intervals from the saved CPU summaries. Its arithmetic status is `PASSED`, while its mean-screen outcome remains `all_intervals_include_zero=false`. These statuses answer different questions.

### Reproduction

Install `.[saom]` and provide the 17 original files listed in `source-review.json`, preserving their `prototype/...` paths beneath a local directory. The runner checks fingerprints; it neither downloads files nor starts R. Use a new output directory to retain a distinct execution record:

```bash
NUMBA_NUM_THREADS=2 python docs/experiments/2026-11-27-partial-network/run_qualification.py inspect --reference-root /path/to/pinned-reference-files --output /path/to/reproduction
NUMBA_NUM_THREADS=2 python docs/experiments/2026-11-27-partial-network/run_qualification.py simulate --reference-root /path/to/pinned-reference-files --output /path/to/reproduction
NUMBA_NUM_THREADS=2 python docs/experiments/2026-11-27-partial-network/run_qualification.py fit --reference-root /path/to/pinned-reference-files --output /path/to/reproduction
python docs/experiments/2026-11-27-partial-network/run_qualification.py verify --output /path/to/reproduction
```

The fixed-parameter simulation and fitted-model experiment use separate fresh estimators and fixed seeds. The latter invokes the actual `partial fit` CLI in a subprocess, keeps its unchanged stdout/stderr and exit status, and removes its temporary row-level panel afterward. `verify` recomputes SEs and convergence ratios from the saved diagnostic matrices; it is an arithmetic check, not an independent simulation replay.

## Relationship to the existing contracts

The complete `sociolab.longitudinal.v1` path retains its original completeness requirements. This new format has separate classes and commands; an incomplete v1 input is not silently reinterpreted. The [joint network/behavior profile](coevolution.md) continues to require its complete observations and declared ordinal measurement. Partial-network observations do not enable behavior missingness or composition change in that profile.

The [Mauldin source audit](mauldin-source-admission.md) remains an audit with unresolved source-admission questions. Its unlisted nominations cannot be populated into `observed_absent` without a justified eligible-alter boundary and observation rule. Survey participation is not an outgoing-item completeness mask, and program departure is not automatically a structural-zero column. This partial-data software path does not resolve those study-specific choices or convert the source audit into an admitted empirical model.
