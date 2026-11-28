# What do empty archive windows tell us?

The earlier [Dept3 recurrence study](archive-recurrence.md) and
[Dept2 network comparison](network-recurrence.md) showed that empty archive
windows materially affect pooled prediction scores. This companion analysis
audits those windows and describes how their contribution affects model
comparisons. It uses the already examined releases and saved results.

**This is a post-result observation audit and exploratory weighting analysis.**
It does not refit a model, issue new predictions, change archive labels or
establish why the records are absent. The original studies and their primary
scores remain intact. No new dataset or dependency is introduced.

## Separate record presence from real observation

Each declared window receives two distinct descriptions:

| Field | Meaning |
| --- | --- |
| `ARCHIVE_ROWS_PRESENT` | At least one physical source row occurs in the window |
| `NO_ARCHIVE_ROWS` | No physical source row occurs in the window |
| `real_coverage_status: UNKNOWN` | Complete capture of eligible real interactions has not been established |

Coverage remains **UNKNOWN in both kinds of window**. A positive record count
does not establish complete capture; a zero count does not establish a real
recording outage, inactivity or relationship termination. No coverage or
membership events are manufactured from either condition.

The [primary-source review](archive-observation-source-review.md) preserves the
publisher's broad internal-email scope claim. It also records unresolved
coverage, temporal membership and calendar mapping. The current temporal
release's 803-day description differs from the older related collection's
18-month description, and the reviewed materials do not reconcile them.
Neither description is silently chosen as a calendar transformation.

Strict R1 complete-observation admission remains **NOT_ADMITTED**. A negative
under the original archive target continues to mean no matching released row;
it does not become a verified negative about real communication.

## Bound inputs and unchanged original studies

The CLI supports two reviewed profiles. Each is bound to the exact bytes and
content identity of its previously published case report, its original protocol
identity and its reviewed source payload. A different report, rewritten JSON
encoding, source payload or schedule is rejected. Recompression is allowed
when the decompressed payload is unchanged; the supplied compressed identity
is reported separately.

| Profile | Original report | Audited windows | Primary weighting sample |
| --- | --- | --- | --- |
| `email-eu-dept3` | Dept3 recurrence report from PR #29 | Origins 180/270/360/450/540/630 days | All six original study windows |
| `email-eu-dept2-network` | Dept2 comparison report from PR #30 | Validation at 270; tests at 360/450/540/630 days | The four test windows only |

Every target lasts 90 source-relative days. Windows include their left boundary
and exclude their right boundary. One day is 86,400 seconds. The Dept2
validation window is audited but remains outside its test weighting analysis.

The command rechecks source-derived historical risk pairs, target presence,
positive counts, outside-risk pairs and row identities against the saved case.
It then uses the saved aggregate Brier errors. It neither reconstructs private
per-pair predictions nor calls a numerical fitting provider. Original forecast
identities remain linked in the companion report.

## Window and gap audit

The audit retains all physical rows, including duplicate triples and self
records, when describing source presence. Self records do not become scored
nonself interactions. This distinction matters: the empty-window grouping is
defined by **all source rows**, not by whether a model's historical risk pairs
had a positive target.

For each window the report includes row, actor and nonself-pair counts; its
source-time boundaries; the first and last record inside it; and the nearest
record strictly before its start and at or after its end. An empty window is
internally bounded when it has both an earlier and a later source record.
This establishes a property of the file, not complete real follow-up.

The complete release's distinct source timestamps also determine the longest
between-record interval. Its endpoints are record times, and the interval is
**open at both ends**. If neighboring record times are `a` and `b`, elapsed
time is `b - a`; the number of integer second values strictly inside is
`max(b - a - 1, 0)`. These are different reported quantities. Neither is
labeled a verified duration of lost observation.

Tied times do not create a positive-duration gap. When several intervals share
the maximum elapsed time, the report gives the full tie count and up to the
first 20 tied intervals, with an explicit truncation flag. Fewer than two
distinct record times produces an unavailable gap result.

This audit uses the complete released file, including later records that bound
an earlier empty interval. It is **retrospective**, and appending a later row
can change its gap description. It must not be inserted into an earlier
forecast as if that later endpoint had already been known.

Source zero is not mapped to a real date. Similar numbered intervals in Dept2
and Dept3 do not establish calendar synchronization between departments.

## Common weighting sensitivity

Let `N_P` be the number of declared pair-origin risk observations in windows with at
least one archive row, and `N_E` the corresponding count in wholly empty
archive windows. For model `m`, let `S_mP` and `S_mE` be sums of squared
probability errors in those two groups, recovered from each saved fold as
`Brier * n`.

Every observation in an empty window receives the same common weight `w`.
The weight is shared across all models:

\[
B_m(w) = \frac{S_{mP} + w S_{mE}}{N_P + w N_E}.
\]

The fixed descriptive grid is **0, 0.25, 0.5, 0.75, 1**. The original primary
comparison is **w = 1**, and the command checks that it reproduces the saved
pooled scores within its declared numerical tolerance.
The share of total weight assigned to empty windows is
`w N_E / (N_P + w N_E)`, which generally differs from `w` itself.

**w = 0 describes only the nonempty-archive subset.** It is not an estimate of
the true probability that observation was complete. It does not qualify the
remaining windows, correct missingness, or replace the original primary
result. Intermediate values describe alternative contributions of the empty
windows; they do not estimate a missing-data mechanism.

The always-zero predictor is retained as a reference. Its squared-error sum
equals the number of positive archive labels. The analysis reports the same
weighting grid for that reference and every declared model.

### Failed and partial model coverage

A model receives an all-plan weighted score only when its scored count matches
the declared risk count at every planned origin. Missing, failed or partially
scored slots remain visible with null all-plan scores. Reducing a window's
weight does not silently remove a failed slot from this eligibility check.
The command does not create a favorable model-specific intersection.

When all windows are empty, the denominator is zero at `w = 0`, so that score
is null; the defined domain is `(0,1]`. With no risk observations anywhere,
all scores and comparisons remain undefined. A zero denominator is never
reported as zero prediction error.

### Pairwise ranking changes

Every eligible unordered pair of models, including the zero reference, receives
a comparison. For models `a` and `b`, define:

\[
A = S_{aP} - S_{bP}, \qquad C = S_{aE} - S_{bE}.
\]

Their score difference has numerator `A + w C` and the same positive
denominator. If `C` is nonzero, a potential equality occurs at `w = -A/C`.
It is reported as a crossing only when it lies within the defined weight
domain and the denominator is positive. Endpoint equalities, constant signs,
ties throughout the defined domain and unavailable comparisons are distinct
results.

Root classification uses the exact ratio of the stored floating-point
coefficients. If an interior root rounds to an endpoint for export, the result
is `NUMERICALLY_UNRESOLVED_EQUALITY` with a null weight.
These crossings describe the stored aggregate errors. They are not statistical
significance tests, causal thresholds or fitted model choices.
The analysis reports all eligible pairs, rather than selecting one favorable
crossing after inspection.

## Interpretation boundary

The weighting calculation answers: **how much does the relative contribution
of these empty archive windows affect the recorded score comparison?**

It does not provide bounds on unknown real interaction labels. Such bounds
would require a separately specified target, assumptions about which labels
are unknown, and appropriate information about predictions and dependence.
This companion analysis supplies none of those assumptions by inference from
row counts. It also supplies no confidence intervals and does not treat repeated
pair-origin observations as independent samples.

A model can remain worse across the entire weight range, or its rank can change
as the empty windows receive less weight. Either is a descriptive property of
the existing archive experiment. Neither establishes the real cause of a gap
or turns a conditional subset result into validated prospective performance.

## Executed companion results

The executed [Dept3 report](experiments/2026-11-28-archive-observation/dept3-observation-report.json)
and [Dept2 report](experiments/2026-11-28-archive-observation/dept2-observation-report.json)
contain all window evidence and all 6 and 21 model-pair comparisons respectively.
Every model has complete plan coverage in these two bound studies.

### Archive presence and internal gaps

| Target window, source-relative days | Dept3 rows | Dept2 rows | Dept2 role |
| --- | ---: | ---: | --- |
| [180,270) | 2,659 | — | Outside its declared plan |
| [270,360) | 1,773 | 6,482 | Validation; excluded from weighting |
| [360,450) | 1,773 | 7,068 | Test |
| [450,540) | 2,380 | 10,277 | Test |
| [540,630) | 0 | 0 | Test |
| [630,720) | 0 | 0 | Test |

All **11 audited windows have real coverage UNKNOWN**, including every window
with records. Both empty windows in each release have an earlier and a later
record; each lies inside that release's unique longest between-record interval.

| Release | Longest open interval in source seconds | Elapsed seconds | Interior integer seconds |
| --- | --- | ---: | ---: |
| Dept3 | `45,310,383 < t < 68,905,594` | 23,595,211 | 23,595,210 |
| Dept2 | `45,571,539 < t < 68,887,206` | 23,315,667 | 23,315,666 |

The longest gaps **begin inside the [450,540) windows that still contain rows**.
Whole-empty-window weighting therefore describes one grouping of observations;
it does not capture every window's exposure to a record gap or correct real
observation coverage. These endpoints establish neither an outage cause nor
a shared calendar interval between departments.

### Dept3: six original windows

The sample contains 7,375 pair-origins: 4,367 in four windows with records and
3,008 in two empty windows. All 1,590 positive archive labels occur in the
former group. Brier scores below are rounded to nine decimal places; lower is
better. The **w = 1 column reproduces the original primary comparison**.

| Model | w = 0 | w = 0.25 | w = 0.5 | w = 0.75 | w = 1, primary |
| --- | ---: | ---: | ---: | ---: | ---: |
| `historical_poisson` | 0.200904720 | 0.210080700 | 0.216906029 | 0.222181412 | 0.226380974 |
| `recent_poisson` | 0.263580423 | 0.236486309 | 0.216333013 | 0.200756278 | 0.188356140 |
| `recent_occurrence` | 0.270208381 | 0.242869701 | 0.222534492 | 0.206817152 | 0.194305085 |
| `always_zero_reference` | 0.364094344 | 0.310607541 | 0.270822688 | 0.240072475 | 0.215593220 |

Their equality weight is approximately `w = 0.493928989`. Historical Poisson
has lower error below it; recent Poisson has lower error above it through
`w = 1`. Thus their ordering depends on the contribution
assigned to the empty windows. The original result remains the `w = 1` result;
the `w = 0` comparison describes the selected nonempty-archive subset.

### Dept2: four test windows; validation separate

The test sample contains 6,584 pair-origins: 3,044 in two windows with records
and 3,540 in two empty windows. Its 1,674 positive archive labels occur in the
former group. The validation window at day 270 contributes to none of these
weighted scores.

| Model | w = 0 | w = 0.25 | w = 0.5 | w = 0.75 | w = 1, primary |
| --- | ---: | ---: | ---: | ---: | ---: |
| `historical_poisson` | 0.204497941 | 0.272748881 | 0.315905479 | 0.345658466 | 0.367412852 |
| `recent_poisson` | 0.289208434 | 0.258413980 | 0.238941957 | 0.225517571 | 0.215702110 |
| `recent_occurrence` | 0.294349540 | 0.263807585 | 0.244495222 | 0.231180909 | 0.221445930 |
| `training_prevalence` | 0.275807408 | 0.329855806 | 0.364031818 | 0.387593416 | 0.404820867 |
| `dyadic_logistic` | 0.166422180 | 0.201005398 | 0.222873140 | 0.237949182 | 0.248972278 |
| `network_logistic` | 0.170394110 | 0.216970581 | 0.246421927 | 0.266726250 | 0.281572090 |
| `always_zero_reference` | 0.549934297 | 0.426062611 | 0.347735771 | 0.293735743 | 0.254252734 |

Dyadic logistic has lower error than recent Poisson below the equality weight
of approximately `w = 0.630488694`; recent Poisson has lower error above it through
`w = 1`. **Network logistic remains worse than dyadic logistic
throughout [0,1]**, including all intermediate weights. Its excess Brier error
is 0.003971930 at `w = 0` and 0.032599812 at `w = 1`. This recorded disadvantage
cannot be removed by changing this common empty-window weight alone.

Both reported equality weights are per-observation multipliers. They do not
mean that the corresponding fraction of the sample was retained, or that
capture was complete with that probability. No weight is selected as a new
primary analysis, and no statistical significance is claimed.

### Execution and independent checks

The [execution record](experiments/2026-11-28-archive-observation/execution.json)
reports all four audit/checker subprocesses successful, with both archives,
original study artifacts, and source/test file identities unchanged. All
`w = 1` scores reproduce their saved primary values within `1e-12`.

| Independent check | Exact comparisons | Numeric comparisons | Mismatches |
| --- | ---: | ---: | ---: |
| [Dept3](experiments/2026-11-28-archive-observation/dept3-independent-check.json) | 527 | 160 | 0 |
| [Dept2](experiments/2026-11-28-archive-observation/dept2-independent-check.json) | 697 | 396 | 0 |

The largest absolute numeric difference is `6.938893903907228e-17`.
These standard-library checks independently reconstruct source window/gap
aggregates and saved-score algebra; they do not independently verify the
original per-pair prediction probabilities. The
[native test log](experiments/2026-11-28-archive-observation/native-tests.log)
records **564 passing tests**. These implementation checks do not establish
real coverage, temporal membership, gap causes or causal validity.

## Reproduction

Supply the reviewed local archive and the exact original case-report file.
Neither command downloads a source, installs dependencies or fits a model.

```sh
PYTHONPATH=src python -m sociolab study archive-observation email-eu-dept3 /path/to/email-Eu-core-temporal-Dept3.txt.gz docs/experiments/2026-11-28-dept3-archive/case-report.json

PYTHONPATH=src python -m sociolab study archive-observation email-eu-dept2-network /path/to/email-Eu-core-temporal-Dept2.txt.gz docs/experiments/2026-11-28-dept2-network/case-report.json
```

Output is an aggregate companion JSON report. Invalid source/report identity,
changed target evidence or failure to reproduce a saved primary score stops
the command. The original case reports, prediction artifacts and protocols
are preserved. Raw participant rows and private prediction arrays are not
published by this audit.
