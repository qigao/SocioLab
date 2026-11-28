# Archive observation and weighting audit — 2026-11-28

This companion analysis follows the completed Dept3 and Dept2 archive studies.
Their results were already known. The analysis is explicitly **post-result and
exploratory**, not a new preregistered prediction experiment. It audits the same
released files, preserves the original labels and reports, and uses their saved
aggregate errors without refitting or reconstructing private predictions.

The [method and results](../../archive-observation.md) explain the CLI and
interpretation. The [primary-source review](../../archive-observation-source-review.md)
records what the publisher and original papers establish and leave unresolved.
Research tracking remains in [R2 / #22](https://github.com/qigao/SocioLab/issues/22)
and [R1 / #21](https://github.com/qigao/SocioLab/issues/21).

## Observation findings

All **11 audited windows** retain `real_coverage_status: UNKNOWN` and strict R1
status `NOT_ADMITTED`. Seven contain archive rows and four are wholly empty.
Each file has two wholly empty targets, source-relative days `[540,630)` and
`[630,720)`, bracketed by earlier and later released records.

| Quantity | Dept3 | Dept2 |
| --- | ---: | ---: |
| Audited windows | 6 study | 1 validation + 4 test |
| Windows in score weighting | 6 study | 4 test |
| Risk pair-origins in nonempty windows | 4,367 | 3,044 |
| Risk pair-origins in empty windows | 3,008 | 3,540 |
| Maximum open interval: left record, seconds | 45,310,383 | 45,571,539 |
| Maximum open interval: right record, seconds | 68,905,594 | 68,887,206 |
| Elapsed seconds between the records | 23,595,211 | 23,315,667 |
| Integer second values strictly inside | 23,595,210 | 23,315,666 |
| Elapsed source-relative days | 273.092720 | 269.857257 |

Each maximum is unique. These are open intervals between distinct recorded
timestamps, not verified recording outages or periods of no real interaction.
The intervals begin inside the partly populated `[450,540)` targets. Weighting
only wholly empty windows therefore does not account for every record-free
portion of the files, let alone unknown real capture. Absolute dates, shared
departmental calendar alignment, gap causes and temporal eligibility remain
unestablished. The full-file audit is retrospective and uses later records;
it is not a past-only live outage detector.

## Score sensitivity findings

Every risk pair-origin in a wholly empty target receives the same relative
weight `w`; nonempty targets retain weight one. This is a weight per observation,
not the empty group's fraction of the weighted sample. All models share the
same weighting. The fixed grid is `0, 0.25, 0.5, 0.75, 1`.

`w = 1` reproduces the original pooled primary score. `w = 0` describes the
nonempty-archive subset after results were seen; it is not a corrected target
or evidence of complete coverage. Brier is squared probability error; lower is
better under the declared released-record target.

| Study / model | w = 0, descriptive subset | w = 1, original primary |
| --- | ---: | ---: |
| Dept3 historical Poisson | 0.200905 | 0.226381 |
| Dept3 recent Poisson | 0.263580 | 0.188356 |
| Dept3 recent occurrence | 0.270208 | 0.194305 |
| Dept3 always-zero reference | 0.364094 | 0.215593 |
| Dept2 historical Poisson | 0.204498 | 0.367413 |
| Dept2 recent Poisson | 0.289208 | 0.215702 |
| Dept2 recent occurrence | 0.294350 | 0.221446 |
| Dept2 frozen training prevalence | 0.275807 | 0.404821 |
| Dept2 dyadic logistic | 0.166422 | 0.248972 |
| Dept2 network logistic | 0.170394 | 0.281572 |
| Dept2 always-zero reference | 0.549934 | 0.254253 |

For Dept3, historical and recent Poisson are equal at
**w = 0.49392898903907445**; historical has lower error below that weight and
recent above it. For Dept2, recent Poisson and dyadic logistic are equal at
**w = 0.6304886937652309**; dyadic has lower error below that weight and recent
above it. These are equality points of the stored aggregate score functions,
not statistical thresholds or selected operating settings.

Dept2 network logistic remains worse than dyadic logistic for **every w in
[0,1]**. Its squared-error difference is positive in both groups: 12.090553799258544
for nonempty windows and 202.54661001929594 for empty windows. Thus this negative
result is not removed by this common weighting. It concerns the declared model
and feature procedure, not all possible uses of network information.

The full JSON reports retain every candidate, every grid value and all **6
Dept3 / 21 Dept2 pairwise comparisons**, including the always-zero reference.
Missing or partial scoring would retain explicit slots and null all-plan scores;
no model-specific intersection is manufactured. This analysis supplies no
unknown-label bounds, missingness correction, calibration qualification,
confidence intervals or causal claims.

## Execution and independent verification

The existing native suite passed **564 tests**, including **37 new tests**, in
12.557 seconds. There were no failures, errors or skips. These tests use authored
fixtures, not the real email archives. The source/test hash maps stayed unchanged.

The real-source runner completed four subprocesses: each profile's CLI followed
by its independent checker. All four exited zero with empty stderr. All source,
plan, checker, original study and archive identities stayed unchanged. The
existing original case reports and protocols were not rewritten.

| Independent check | Exact comparisons | Numeric comparisons | Mismatches | Maximum absolute difference |
| --- | ---: | ---: | ---: | ---: |
| Dept3 | 527 | 160 | 0 | 6.591949208711867e-17 |
| Dept2 | 697 | 396 | 0 | 6.938893903907228e-17 |
| Total | 1,224 | 556 | 0 | 6.938893903907228e-17 |

The numeric tolerance is `1e-12`. Original primary-score reproduction differs
by at most `2.7755575615628914e-17` for Dept3 and exactly zero for Dept2.

The independent checker uses only the Python standard library. It directly
filters source-time windows, reconstructs counts and identities, calculates
gaps and per-fold weighted sums, and verifies all pairwise equality domains.
Its root classification uses integer cross-products, independently of the
production implementation's `Fraction` path. It does not import SocioLab, call
a model provider, refit the optimizer or independently verify the original
private prediction probabilities.

## Evidence files

| File | Role |
| --- | --- |
| [analysis-plan.json](analysis-plan.json) | Declared post-result scope, fixed weights and failure rules |
| [source-review.json](source-review.json) | Primary-source statements, provenance limits and admission decision |
| [dept3-observation-report.json](dept3-observation-report.json) | Bound Dept3 window audit, scores and all pairwise comparisons |
| [dept2-observation-report.json](dept2-observation-report.json) | Bound Dept2 audit, separate validation and test-only sensitivity |
| [dept3-independent-check.json](dept3-independent-check.json) | Dept3 verification counts, differences and scope |
| [dept2-independent-check.json](dept2-independent-check.json) | Dept2 verification counts, differences and scope |
| [execution.json](execution.json) | Commands, timestamps, exit codes and before/after identities |
| [tests-execution.json](tests-execution.json) | Native validation command and source/test identity maps |
| [native-tests.log](native-tests.log) | Complete native validation output |
| [run_case.py](run_case.py) | Four-step reproduction runner with unchanged-input checks |
| [independent_check.py](independent_check.py) | Standalone source/count/score checker |

The four `*-audit.stderr.log` / `*-checker.stderr.log` files preserve empty
stderr from the successful executions. Raw email rows and private pair forecasts
are not part of these aggregate evidence files. No new source or dependency was
acquired, and no installer/consumer test suite or CI workflow was added.

## Reproduction

Use the reviewed archives already held locally and a fresh output directory:

```sh
python docs/experiments/2026-11-28-archive-observation/run_case.py \
  /path/to/email-Eu-core-temporal-Dept3.txt.gz \
  /path/to/email-Eu-core-temporal-Dept2.txt.gz \
  /path/to/new-audit-output
```

The runner resolves the exact original reports from the repository and sets
`PYTHONPATH` for the CLI. It refuses to overwrite prior output evidence. A changed
case report, source payload, target schedule or original primary score stops
execution. Recompression of an identical source payload is accepted and its
compressed identity is reported. Nothing is downloaded or fitted by this run.

Before a stronger observation or prospective prediction claim, research still
needs a source with a defensible coverage/membership contract and an independently
specified future evaluation. Further adaptation on these examined files is
development work; this sensitivity analysis does not supply that qualification.
