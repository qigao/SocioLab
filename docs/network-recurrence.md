# Do historical network features improve archive recurrence prediction?

This bounded comparison advances [R2 / #22](https://github.com/qigao/SocioLab/issues/22):
**does adding reciprocal activity and network position improve prediction of
which previously recorded directed pairs recur in a later released-archive
window?** It compares a dyadic logistic model with a network-feature extension,
using the same training rows, outcome definition, estimator and held-out
windows. Existing rate/recency baselines remain in the comparison.

**Executed finding:** the declared network extension had higher Brier error than
the dyadic model at all four test origins and at the separate validation
origin. Its test pooled Brier was 0.281572 versus 0.248972 for the dyadic model,
a difference of **+0.032600**. This is a negative result for this frozen
feature/model comparison, not evidence that network information can never help.
The [results below](#executed-results) retain the full comparison and the empty
archive periods that materially affect its interpretation.

The outcome is a row in a fixed published file. A negative means no matching
row occurs in that archive window. It does not establish that real
communication was absent, that both people remained eligible, or that a social
relationship ended. This profile does not estimate REM waiting times, language
meaning, psychological motives or causal effects. The
[strict repeat-interaction profile](repeat-interaction.md) retains its stronger
membership and observation requirements.

## What was frozen, and when

The earlier [Dept3 experiment](archive-recurrence.md) informed this design: its
rate baselines showed substantial probability mismatches, and empty archive
periods influenced pooled scores. This is therefore a follow-up design, not a
claim that the model choices were uninformed by prior results.

Dept2 was selected before its raw records were read: it was the lowest-numbered
unread department whose published size fit the existing 200-node / 2,000-pair
budget. Dept1 exceeds those budgets. Dept2 comes from the **same institutional
release as Dept3**, so a new department file is not an independent external
replication or evidence of generalization to another institution.

The [complete protocol](experiments/2026-11-28-dept2-network/protocol.json) was
published in commit
[`938c8e417def93f6e331f04ce52b6deb42f100d2`](https://github.com/qigao/SocioLab/commit/938c8e417def93f6e331f04ce52b6deb42f100d2)
before the single official acquisition. Its raw file SHA-256 is
`947b7a1856ee199e7bcdb959eba667d3f6f593df67f325583e90d16a7d684de7`;
its canonical JSON content hash is
`sha256:67bcbeac8192d0b6f4e928e2b8d5790c6b9c8ac363a35d446e92fc1d21828661`.

| Step on 2026-11-28 | Time, Asia/Tokyo |
| --- | --- |
| Public protocol commit | 15:53:44 |
| Official Dept2 download started | 15:54:46.046825 |
| Official Dept2 download completed | 15:54:53.221546 |
| Aggregate admission audit recorded | 15:54:53.429788 |

Local protocol bytes were checked against the public commit before acquisition.
The source fingerprints and aggregate admission checks were recorded before
any fit, model score or planned-window outcome count was inspected. This
documents the present retrospective research sequence; it does not authenticate
historical receipt availability or predictions issued when the emails occurred.

## Source admission and record semantics

The [official SNAP source page](https://snap.stanford.edu/data/email-Eu-core-temporal.html)
describes internal institutional email and departmental subnetworks. The local
input is the official
[`email-Eu-core-temporal-Dept2.txt.gz`](https://snap.stanford.edu/data/email-Eu-core-temporal-Dept2.txt.gz)
release. Source seconds are relative to the published zero; no UTC dates are
invented for the underlying events. Each recipient of a group message appears
as a directed record, so directed rows are not necessarily independent messages.

| Source field | Observed aggregate |
| --- | ---: |
| Physical rows | 46,772 |
| Anonymous identifiers | 162 |
| Distinct directed nonself pairs | 1,772 |
| Self-pair rows | 0 |
| Compressed bytes | 211,430 |
| Payload bytes | 719,111 |
| Minimum / maximum source seconds | 0 / 69,440,727 |
| Time decreases in physical line order | 27 |
| Repeated triple groups | 754 |
| Additional identical triple rows | 762 |

The compressed SHA-256 is
`8e8dcdb9049a671f2afcb4bc91ff8ad77423a40612ce8318ef0825aa8b44b53d`;
the decompressed payload SHA-256 is
`2488f3de81722acd1a3ed611c3f0f348dc9e9f3e030cb821edb5fd928c53b45f`.
The [acquisition evidence](experiments/2026-11-28-dept2-network/source-acquisition.json)
and [aggregate source audit](experiments/2026-11-28-dept2-network/source-audit.json)
retain exact identities and admission checks. Their no-fit/no-score fields
describe that pre-estimation stage.

The reader preserves every original physical row and its private line identity.
Identical triples are not deduplicated: without message IDs, the study cannot
tell repeated messages from duplicate export rows. Selection uses source time,
not physical prefixes. Equal-time rows form unordered counts; they are not
jittered or assigned an invented sequence. Self-pairs would remain in the
source audit but would not enter features, risk sets or target labels.

The reviewed payload and protocol are mandatory. Recompression is allowed if
the payload remains identical; both actual fingerprints are reported. Malformed
input, wrong identities, size violations or admission mismatches stop the
study. The file reaches beyond day 720, satisfying the frozen artifact-extent
check. That check is not a declaration of complete real follow-up.

## Past-only training and future windows

One day is exactly 86,400 source seconds. History always starts at source zero.
Recent history covers 30 days; each target covers 90 days. Every interval is
left-closed and right-open.

| Role | Origin, days | Historical records | Target records | Use of target |
| --- | ---: | --- | --- | --- |
| Training | 90 | [0, 90) | [90, 180) | Fit both candidates |
| Training | 180 | [0, 180) | [180, 270) | Fit both candidates |
| Validation | 270 | [0, 270) | [270, 360) | Diagnostics only |
| Test | 360 | [0, 360) | [360, 450) | Held-out score |
| Test | 450 | [0, 450) | [450, 540) | Held-out score |
| Test | 540 | [0, 540) | [540, 630) | Held-out score |
| Test | 630 | [0, 630) | [630, 720) | Held-out score |

At each origin, the risk set contains only ordered nonself pairs with at least
one earlier record. It does not use the full-release roster, future activity or
all possible actor pairs. New target-only pairs are counted separately and do
not enlarge an already fixed risk set.

Training examples are built twice, at their own origins. Although fitting
occurs at day 270, a training example at day 90 cannot use records from days
90–270 as features. Its label can use only its declared target [90,180).
Both training label windows close by the fitting cutoff. Repeated pairs can
contribute one example per training origin; these are pair-origin observations,
not independent social relationships.

The two models are fitted once, before validation or test targets are scored.
Validation at day 270 does not select features, regularization, iteration
budgets, models, thresholds or calibrators. It triggers no refit. Later test
origins may use newly observed past records as features, including records from
earlier test windows; the fitted scaling and coefficients stay fixed. This is
a sequential source-time evaluation with a frozen model, not a forecast that
knows all later test histories at day 270.

## The feature comparison

For a pair `i -> j`, let `n_ij` be its count before origin `t`, `r_ij` its count
in the recent window of width `W`, and `last_ij` its last historical source
time. Let `H` be the target horizon. Every listed quantity is transformed by
the natural `log1p` function.

| Feature | Quantity before `log1p` | Dyadic model | Network extension |
| --- | --- | :---: | :---: |
| Historical expected count | `n_ij * H / t` | Yes | Yes |
| Recent expected count | `r_ij * H / W` | Yes | Yes |
| Last-record age in horizons | `(t - last_ij) / H` | Yes | Yes |
| Reverse historical expected count | `n_ji * H / t` | — | Yes |
| Reverse recent expected count | `r_ji * H / W` | — | Yes |
| Source out-degree | Number of historical receivers of `i` | — | Yes |
| Target in-degree | Number of historical senders to `j` | — | Yes |
| Directed two-step paths | Number of distinct `k` with `i -> k -> j`, excluding `i` and `j` | — | Yes |

NetworkX supplies the binary directed historical graph. Repeated records affect
count features, but do not multiply a graph edge, degree or two-step path.
Reverse counts are zero when no corresponding row exists in the historical
release; this is an archive count, not imputation of unknown real contact.
Actor identifiers are used for joining records and constructing the graph,
never as numeric predictors.

The network candidate adds exactly five declared features to the dyadic
candidate. Both use the same rows and fitting configuration. Their comparison
therefore asks whether this particular added information helps this particular
predictive procedure. It does not isolate a causal effect of reciprocity,
centrality, an individual feature or a network intervention.

## Upstream fitting and failure semantics

The optional dependency is `qigao-sociolab[network-prediction]`, whose study
provider is pinned to **scikit-learn 1.9.1**. NetworkX remains the graph
provider. The [provider review](network-recurrence-provider.md) records exact
upstream code, licensing, supported Python versions and missing-data behavior;
[provider-runtime.json](experiments/2026-11-28-dept2-network/provider-runtime.json)
records the installed versions and sanitized wheel provenance.

Each candidate uses an upstream `StandardScaler` fitted only on its training
matrix, followed by `LogisticRegression` with L-BFGS, L2 regularization,
`C=1.0`, `tol=1e-8`, `max_iter=1000`, an intercept, no class reweighting and no
warm start. Computation is limited to one thread. SocioLab does not implement
the optimizer or logistic likelihood.

Feature inputs must be finite before scaling. Unknown covariates are not
zero-filled or mean-filled, and examples are not silently dropped. Fitted
parameters, feature order, training identities, provider version, warnings and
iteration counts are retained. The positive probability column is used only
after confirming the exact binary classes `[0,1]`.

Two different failure cases are intentionally distinguished:

- **A planned fit cannot produce a qualified model:** empty or single-class
  training, an unsuccessful fit, warning-bearing output or invalid fitted
  parameters retains the model slot with its reason. That candidate supplies no
  forecasts, and its scores remain null. Other declared candidates can still
  be reported. No retry, parameter change or substitute estimator is hidden
  behind the failed model's name.
- **Prediction-time integrity fails:** changed scaler/coefficients, inconsistent
  feature identities, invalid probabilities or a prediction warning stops the
  execution. The runner retains execution/error evidence; it does not publish
  a completed comparison assembled around the integrity violation.

Before and after each prediction, the scaler and estimator are checked against
their frozen parameter hash. Successful numerical completion is recorded
separately from predictive performance, calibration or scientific adequacy.

## Baselines, scoring and denominators

Six candidates are declared in advance:

| Candidate | Prediction rule |
| --- | --- |
| Historical Poisson | `1 - exp(-n_ij * H / t)` |
| Recent Poisson | `1 - exp(-r_ij * H / W)` |
| Recent occurrence | 1 if `r_ij > 0`, otherwise 0 |
| Training prevalence | Pooled positive fraction from the two training origins, frozen at day 270 |
| Dyadic logistic | Frozen upstream classifier with the three dyadic features |
| Network logistic | Frozen upstream classifier with all eight features |

The count rates divide by archive-window duration, not verified person
exposure. A separately declared always-zero reference has Brier equal to the
observed archive positive fraction. It helps identify apparent success caused
by many negatives.

All available models use the same risk pairs and binary archive labels at a
given origin. The primary comparison is **test pooled network Brier minus test
pooled dyadic Brier**; a negative value favors the network extension for this
declared score. It is reported only if both models cover the complete test risk
set. Baseline and zero-reference differences likewise require matching full
coverage.

Pooled Brier weights each pair-origin equally. Macro Brier weights each planned
origin equally and is null unless every planned origin has at least one scored
pair. Validation and test are summarized separately. Reports retain planned
origins, model-specific scored origins, missing pair-origin counts and failed
models. No failed model is assigned the denominator of a successful one.

Fixed probability bins are `[0,0.2,0.4,0.6,0.8,1]`. Bins include their left
boundary, with 1 included in the last bin; empty bins retain zero counts and
null averages. Existing Brier, binning and cross-origin arithmetic is reused.
A lower Brier score can reflect better discrimination and does not alone prove
calibration; the [upstream calibration guide](https://scikit-learn.org/1.9/modules/calibration.html)
explains this distinction. No calibrator is fitted, no dependence-aware
uncertainty interval is estimated, and no significance claim follows from the
number of repeated pair-origin observations.

Every planned target window remains present, including windows with no archive
rows. Their all-source row counts are reported so an empty file interval is
visible alongside pair recurrence. No period is removed or moved after looking
at the result. An empty archive period does not explain its own cause.

## Batch replay and changing network state

The replay adapter accepts every newly available line in
`[previous_origin, origin)`, including timestamp ties in any supplied order.
It preserves original line identities, rejects late lines or reused identities,
and changes its history and clock atomically after successful feature creation.
An empty advance still moves the clock and expires recent-window activity.

At each evaluation origin, the study compares the complete feature artifact
from replay with one rebuilt from the same historical rows in batch. This
checks that elapsed time, new records and their induced graph changes give the
same inputs to a frozen classifier. It does not implement an external live
source subscriber, verify that a publisher delivered every record, or infer
that a relationship ended when a record leaves a window. The caller must
supply the interval's records; the archive API cannot discover an omitted line
on its own. Corrections and late receipts require a separately versioned
history contract rather than backdating this append-only replay.

## Reproduce the comparison

Use a supported Python 3.12/3.13 environment with the base dependencies and
`network-prediction` extra. Obtain the archive separately from the official
source and retain it outside the repository. Neither command downloads data.

From the repository root, the CLI writes an aggregate JSON report to stdout:

```sh
PYTHONPATH=src python -m sociolab study email-eu-dept2-network /path/to/email-Eu-core-temporal-Dept2.txt.gz docs/experiments/2026-11-28-dept2-network/protocol.json
```

The execution wrapper runs that CLI and the independent checker, retaining
stdout/stderr fingerprints, source/protocol/checker identities and exit codes:

```sh
PYTHONPATH=src python docs/experiments/2026-11-28-dept2-network/run_case.py /path/to/email-Eu-core-temporal-Dept2.txt.gz /path/to/new-output-directory
```

Use a new output directory. Existing execution artifacts are not overwritten.
The wrapper fixes numerical thread limits and verifies that source files,
protocol, checker and archive stayed unchanged during execution. A failed
subprocess remains visible in `execution.json` and its error log.

The independent checker reconstructs record counts, feature quantities,
probabilities from saved fitted parameters, Brier scores and diagnostics using
the standard library. It does not refit sklearn or substitute another solver.
Agreement checks the recorded computation; it does not establish that the
source measures all real communication or that the fitted model generalizes.

## Executed results

The first recorded execution completed the actual CLI and independent checker
with exit code 0. Both fitted candidates completed without warnings: the
dyadic model took 14 upstream iterations and the network model took 25. Both
used all **1,916 training pair-origin observations**, including **1,376
positives**, and remained frozen throughout validation and testing. No failed
model or planned origin was omitted. Numerical completion did not translate
into a gain from the additional network features.

The full [case report](experiments/2026-11-28-dept2-network/case-report.json)
contains fitted parameters, scaling statistics, warning/iteration records,
training and feature identities, every origin and all probability bins. Its
canonical content hash is
`sha256:02c236fc36c42bbeda9c5e1dfb07705b8a2cc39e4eccc05f99a08c312e941c28`.

### Test comparison across all four planned origins

Every candidate scored the same **6,584 pair-origin observations**: **1,674
positives and 4,910 negatives**, an archive positive fraction of **0.254253**.
All four planned test origins are included in both pooled and macro scores.
Lower Brier is better; the mean prediction is reported separately from either
error score.

| Candidate | Test pooled Brier | Test macro Brier | Mean predicted probability |
| --- | ---: | ---: | ---: |
| Historical Poisson | 0.367413 | 0.355924 | 0.655104 |
| Recent Poisson | 0.215702 | 0.220874 | 0.269443 |
| Recent occurrence | 0.221446 | 0.226591 | 0.274909 |
| Training prevalence | 0.404821 | 0.395806 | 0.718163 |
| Dyadic logistic | 0.248972 | 0.243286 | 0.536304 |
| Network logistic | 0.281572 | 0.273966 | 0.581986 |
| Always-zero reference | 0.254253 | 0.274913 | 0.000000 |

The primary comparison is **network minus dyadic pooled Brier =
+0.03259981224461639**. The network extension is worse on this metric. Its
pooled error is also 0.027319 above the always-zero reference. The dyadic
candidate is 0.005280 below that reference. These descriptive differences do
not establish statistical significance.

Recent Poisson has the lowest pooled and macro Brier among the six declared
candidates. That ranking must be read together with the per-origin outcomes:
the dyadic model is best among the six candidates at each of the first two
test origins, while the recent models benefit from the empty archive periods.
No candidate was selected, refitted or retuned after observing these results.

| Test origin, source days | Risk pairs | Positive pairs | All archive target rows | Dyadic Brier | Network Brier | Network minus dyadic |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 360 | 1,421 | 779 | 7,068 | 0.169544 | 0.176249 | +0.006705 |
| 450 | 1,623 | 895 | 10,277 | 0.163689 | 0.165268 | +0.001579 |
| 540 | 1,770 | 0 | 0 | 0.381027 | 0.441348 | +0.060321 |
| 630 | 1,770 | 0 | 0 | 0.258885 | 0.312997 | +0.054112 |

The first two target windows also contain 202 and 147 directed positive pairs
outside the respective frozen risk sets. They remain outside the scored
denominator. The expanding risk set incorporates them at the next origin only
after those records have become history.

### Validation remains separate

The diagnostic-only validation origin at source day 270 has **1,307 risk pairs,
813 positives and 6,482 target rows**. Its positive fraction is 0.622035. The
network candidate is already worse than the dyadic candidate there, by
0.006310653994086951 Brier. As predeclared, this did not change the models or
subsequent evaluation.

| Candidate | Validation Brier |
| --- | ---: |
| Historical Poisson | 0.196713 |
| Recent Poisson | 0.303138 |
| Recent occurrence | 0.309105 |
| Training prevalence | 0.244348 |
| Dyadic logistic | 0.176245 |
| Network logistic | 0.182556 |
| Always-zero reference | 0.622035 |

With one validation origin, its pooled and macro Brier are identical. These
observations are not merged into the test denominator.

### Internal empty periods and changing archive base rates

The complete Dept2 file contains **no rows** in source-relative days
**[540,630)** or **[630,720)**. These two targets contribute **3,540 of 6,584
test pair-origins, or 53.7667%**, all labeled negative under the archive
definition. At day 630 the recent window is also empty, so recent Poisson and
recent occurrence output zero and receive zero Brier for that target. That
arithmetic result does not establish perfect prediction of real behavior.

These targets are internal to the released file's extent. The recorded
aggregate history count at day 630 is 46,492, the target [630,720) is empty,
and the complete release has 46,772 rows. Therefore **280 rows occur at source
day 720 or later**. The two empty targets are not padding added beyond the
file's final event. Their real cause remains unknown; the results cannot
distinguish real inactivity, incomplete recording, release processing or other
explanations.

Dept3 also had empty targets at the same numbered source-relative windows.
The sources' zero points have not been established as a shared calendar date,
so this does **not** establish that the departments' gaps occurred at the same
real time. It provides no evidence by itself for a synchronized institutional
event or a common recording failure.

The observed training positive fraction was **1,376/1,916 = 0.718163**; the test
fraction was **1,674/6,584 = 0.254253**. This is a substantial change in the
archive labels under the declared windows and changing historical risk sets.
It is not itself a measured change in true relationship persistence. The
frozen training-prevalence predictor makes the mismatch visible: it continues
to predict 0.718163 and has test pooled Brier 0.404821.

All empty periods remain in the primary analysis. Removing them or choosing
new windows after inspection would answer a changed question. The fitted
models' smaller errors in the first two test periods are descriptive context,
not a replacement favorable leaderboard.

### Probability diagnostics

The network model's predicted probabilities exceed the observed archive
fractions in every declared test bin. In its high-probability bin, **2,155
observations** average **0.921762 predicted** versus **0.483063 observed**
(1,041 positives). This is a large descriptive disagreement, despite
warning-free optimization.

| Network probability bin | Pair-origins | Mean prediction | Observed archive fraction |
| --- | ---: | ---: | ---: |
| [0,0.2) | 855 | 0.129649 | 0.029240 |
| [0.2,0.4) | 1,346 | 0.294135 | 0.095840 |
| [0.4,0.6) | 1,116 | 0.497808 | 0.176523 |
| [0.6,0.8) | 1,112 | 0.704217 | 0.253597 |
| [0.8,1] | 2,155 | 0.921762 | 0.483063 |

The dyadic model also overpredicts across these bins. Its high bin averages
0.917484 predicted versus 0.506180 observed. Even the lowest-Brier recent
Poisson baseline is not established as calibrated: its 4,774 zero-probability
observations contain 661 positives, while its 1,810 high-bin observations
average 0.980116 predicted versus 0.559669 observed. Similar overall means can
hide opposing errors. No fitted calibrator or calibration qualification is
claimed.

### What this negative comparison establishes

The predeclared addition of five network features **did not improve this
fixed logistic procedure on this Dept2 archive task**. That conclusion holds
at validation and each individual test origin, as well as in the primary
pooled comparison. The experiment provides a reproducible counterexample to
assuming that a richer network representation will automatically improve
future-record prediction.

It does not show that all network features are useless, that a particular
structural mechanism is absent, or that any coefficient identifies the cause
of a future action. Feature choice, model form, training period, source
measurement and distribution changes remain separate research questions.
The inspected test windows are now known: revising these choices requires an
explicit follow-up protocol and honest exploratory labeling or untouched
evaluation data. The current protocol and results stay fixed.

### Validation and reproducibility evidence

- **527 native tests passed in 12.069 seconds**, including 34 new tests, with
  no failures, errors or skips. Tests used fictional fixtures, not the real
  Dept2 source. Source and test hashes stayed unchanged; the
  [test execution record](experiments/2026-11-28-dept2-network/tests-execution.json)
  and [native test log](experiments/2026-11-28-dept2-network/native-tests.log)
  retain the evidence.
- The actual CLI and independent checker both exited 0, with empty error
  logs. The [execution record](experiments/2026-11-28-dept2-network/execution.json)
  records unchanged code, protocol, checker and source archive identities.
- The [independent check](experiments/2026-11-28-dept2-network/independent-check.json)
  completed **1,653 exact and 1,438 numeric comparisons with zero mismatches**.
  Maximum absolute numeric difference was **1.1368683772161603e-13**, below
  the declared **1e-10** tolerance.
- That checker independently reconstructs source/training counts, labels,
  historical features, scaling statistics and aggregate probabilities/scores
  from saved coefficients. It imports neither SocioLab nor sklearn and does
  not refit or independently prove the optimizer solution. The actual per-pair
  outputs from sklearn are not supplied to the checker, so it checks forecast
  hash format and model identity rather than claiming exact reconstruction of
  every private forecast hash.
- Batch and source-time replay feature artifacts agree at all five prediction
  origins, and fitted parameter identities remain fixed across them. No
  external subscriber, R runtime, installer/consumer test suite or replacement
  numerical solver is introduced by this comparison.

## Attribution, publication and research limits

The source paper is Paranjape, A., Benson, A. R., and Leskovec, J. (2017),
[*Motifs in Temporal Networks*](https://doi.org/10.1145/3018661.3018731), WSDM,
pp. 601–610. The
[SNAP collection](https://snap.stanford.edu/data/index.html) provides additional
collection attribution. No dataset-specific license or explicit
aggregate-publication license was stated on the reviewed official pages.
SNAP's software BSD license is not applied to the dataset.

Local processing and attributed aggregate reporting follow the public research
distribution context; this is an interpretation of that presentation, not an
unrestricted redistribution grant. Raw source rows, participant identifiers
and pair-level prediction arrays are not published here. Public evidence
contains methodology, source fingerprints, aggregate counts, fitted parameter
summaries and execution diagnostics.

The study is admitted for **released-archive recurrence only**. Strict R1
complete-observation admission remains unresolved. Source population selection,
unverified coverage, dependent pair-origin observations and the shared
institution limit interpretation. Improved out-of-time archive scores would
support a bounded predictive finding, while motives, language meaning,
relationship termination and causal intervention effects still require their
own measurements and research designs.
