# Dept2 frozen network recurrence comparison

This directory retains the protocol, aggregate results and execution evidence
for the first R2 binary archive-recurrence model comparison. The
[full study report](../../network-recurrence.md) explains the target, input
contract, results and limits; the [provider review](../../network-recurrence-provider.md)
documents the upstream estimator.

## Frozen sequence

1. The protocol and provider source review were published in commit
   [`938c8e417def93f6e331f04ce52b6deb42f100d2`](https://github.com/qigao/SocioLab/commit/938c8e417def93f6e331f04ce52b6deb42f100d2)
   at **2026-11-28 15:53:44 Asia/Tokyo**.
2. The single official Dept2 acquisition started at **15:54:46.046825** and
   finished at **15:54:53.221546**. Local protocol bytes were checked against
   the public commit before acquisition. Aggregate source admission and
   fingerprints were bound before fitting or examining per-origin outcomes.
3. The actual study CLI ran at **16:00:58.589463–16:01:01.453378**, followed by
   the independent checker through **16:01:02.137515**. Both exited 0 on the
   first full execution. No model, split, feature or hyperparameter was changed
   after inspecting held-out results.

Dept3 had already informed this design. Dept2 was a previously unexamined
departmental file in the same institutional release, not an independent
external replication. Source-relative day numbers do not establish calendar
alignment between departments.

## Evidence map

| File | Meaning |
| --- | --- |
| `protocol.json` | Unchanged pre-acquisition source, split, feature, estimator and scoring contract |
| `provider-audit.json` | Historical source/API and pre-installation runtime review |
| `provider-runtime.json` | Installed versions and sanitized wheel provenance for the optional provider |
| `source-acquisition.json` | Public freeze identity, download chronology and response evidence |
| `source-audit.json` | Pre-fit aggregate row audit, source hashes and admission checks |
| `case-report.json` | Training identity, both fitted parameter states, all validation/test origins, scores and bins |
| `independent_check.py` | Standard-library oracle for source/features/scaling/saved-coefficient probabilities/scores |
| `independent-check.json` | Actual independent comparison counts, tolerance and limitations |
| `run_case.py` | Actual CLI/checker subprocess runner; new output directory required |
| `execution.json` | Commands, exit codes, timestamps and unchanged source/protocol/checker/archive identities |
| `study.stderr.log`, `checker.stderr.log` | Retained stderr from the actual successful execution |
| `native-tests.log`, `tests-execution.json` | 527 native tests and source/test identity checks |

The source and provider audits preserve their original pre-fit/pre-installation
stage labels. Later runtime/results files record subsequent work; those stage
labels are not claims that the final experiment remains unexecuted.

## Actual result

Training: 1,916 historical pair-origin observations, 1,376 positives.
Validation: 1,307 observations at day 270, diagnostic only.
Test: 6,584 observations at days 360/450/540/630, 1,674 positives.

| Model | Test pooled Brier |
| --- | ---: |
| Recent Poisson | 0.215702 |
| Recent occurrence | 0.221446 |
| Dyadic logistic | 0.248972 |
| Always-zero reference | 0.254253 |
| Network logistic | 0.281572 |
| Historical Poisson | 0.367413 |
| Frozen training prevalence | 0.404821 |

The primary network-minus-dyadic Brier difference is **+0.032600**; lower
is better. The network candidate is worse at every test origin and at the
separate validation origin. This result concerns this feature block and frozen
model specification, not the general usefulness of networks.

Targets [540,630) and [630,720) source-relative days contain no archive rows.
They contribute 3,540 observations, **53.77%** of the test denominator. There
are 280 rows at or after day 720, so these empty targets are internal archive
gaps. Their real cause is unknown. All planned origins are retained. The
dyadic model has the lowest Brier among these candidates at the two nonempty
test windows; the recent models benefit in the empty windows.

Both logistic fits completed without warnings (14 and 25 iterations). That
numerical result does not establish calibration: the network model's highest
probability bin averages 0.921762 predicted versus 0.483063 observed.

Validation: **527 native tests pass, 34 new, no failures/errors/skips**.
The independent checker passes **1,653 exact and 1,438 numeric comparisons**,
zero mismatches; maximum absolute numeric difference
**1.1368683772161603e-13**, within the declared 1e-10 tolerance. It reconstructs
the probabilities implied by the saved parameters; it does not refit or certify
the optimizer solution or independently reconstruct private forecast hashes.

## Reproduction and identities

Use the reviewed local source file and the optional `network-prediction`
dependency. The runner does not download the data or install packages.

```bash
PYTHONPATH=src python docs/experiments/2026-11-28-dept2-network/run_case.py /path/to/email-Eu-core-temporal-Dept2.txt.gz /new/output/directory
```

| Artifact | SHA-256 |
| --- | --- |
| Protocol file | `947b7a1856ee199e7bcdb959eba667d3f6f593df67f325583e90d16a7d684de7` |
| Reviewed gzip | `8e8dcdb9049a671f2afcb4bc91ff8ad77423a40612ce8318ef0825aa8b44b53d` |
| Reviewed payload | `2488f3de81722acd1a3ed611c3f0f348dc9e9f3e030cb821edb5fd928c53b45f` |
| Case report file | `8805a5dca552a9e81e44f7486db1355edccb67dce69d1da0207c37344e470862` |
| Independent result file | `b9d6fdbb58646e28c93e9fce0d5cf5cd52cd722d10ebd5e77244c0279d0a866b` |

The source, protocol, study code and checker remained unchanged during the
recorded run. Cross-platform floating-point reproduction uses a declared
tolerance; bitwise equality across numerical-library environments is not
promised. Raw participant rows and private per-pair predictions are not
redistributed. No installer/consumer test suite, R runtime, new graph engine,
replacement numerical solver or CI workflow was added.
