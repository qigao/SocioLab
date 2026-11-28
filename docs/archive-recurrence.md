# Repeat-record prediction in the released Dept3 email archive

This bounded study advances [R1 / #21](https://github.com/qigao/SocioLab/issues/21)
using a separate measurement contract: **for an ordered pair already present in
past records, will another matching row appear in a specified future window of
this fixed released archive?**

A negative label means that the archive contains no matching row in that window.
It does not establish that the people had no real communication, remained
eligible throughout the window, or ended a relationship. The
[strict complete-observation R1 profile](repeat-interaction.md) retains its
membership, coverage and follow-up requirements. Its earlier
[source admission decision](repeat-interaction-source-review.md) is unchanged.

## Protocol and acquisition sequence

The source and analysis choices were frozen before this session downloaded or
read the raw event archive. Dept3 was chosen from published metadata because its
size fits the existing 200-person / 2,000-pair budget; prediction results did not
select the department, windows or models.

The frozen [protocol](experiments/2026-11-28-dept3-archive/protocol.json) was
published in commit
[`4c93277b7098d2e98e6a4d22874c8e0b9f976d5b`](https://github.com/qigao/SocioLab/commit/4c93277b7098d2e98e6a4d22874c8e0b9f976d5b).
Its file SHA-256 is
`78c90e80dd149b3b69fd3139a3d945b67a9ca5c5725bd1d70d074dae45953d02`.
The canonical JSON content hash used by the implementation is
`sha256:d3f841be83127fdcaa4c6ca26129d845ac276c32e6e527b0324aa90c1e8da7e0`.
These identify different byte encodings of the same declared protocol.

| Step | Recorded time on 2026-11-28, Asia/Tokyo |
| --- | --- |
| Official metadata review, before raw acquisition | 14:54:37.122199 +09:00 |
| Protocol commit timestamp | 14:57:16 +09:00 |
| Raw download started | 14:58:08.703557 +09:00 |
| Raw download completed | 14:58:17.347625 +09:00 |

The [metadata review](experiments/2026-11-28-dept3-archive/metadata-review.json)
records the pre-acquisition stage. The
[acquisition record](experiments/2026-11-28-dept3-archive/source-acquisition.json)
retains UTC timestamps, the exact command and successful HTTP response; the
[source audit](experiments/2026-11-28-dept3-archive/source-audit.json) binds the
downloaded fingerprints and structural findings before model scoring. Its
`models_scored: false` field describes that audit stage.

This sequence documents the present retrospective study. It is not evidence of
historical receipt availability or predictions issued when the underlying email
events originally occurred. Git metadata and content hashes are provenance
records, not independent authentication of real-world observation or issuance.

## Fixed source and structural audit

The [official SNAP dataset page](https://snap.stanford.edu/data/email-Eu-core-temporal.html)
describes internal institutional email and department subnetworks. Each recipient
of a message contributes a directed edge, including recipients of group email.
Department identifiers do not map to whole-network identifiers by equality.
The three fields are sender, recipient and **source-relative seconds starting at
zero**; the format heading's `UNIXTS` wording does not justify inventing UTC dates.

The reviewed download is
[`email-Eu-core-temporal-Dept3.txt.gz`](https://snap.stanford.edu/data/email-Eu-core-temporal-Dept3.txt.gz).

| Fingerprint | Value |
| --- | --- |
| Compressed bytes | 59,124 |
| Compressed SHA-256 | `b1f92288e855044bbc74bacac39d42b12e59ec2a0130ad8df419786eb46a7bff` |
| Decompressed bytes | 178,184 |
| Payload SHA-256 | `87f766b9e9547cb315c2fc1e49ed6eff2c60c121579b22d095079a401bbb3eb9` |

All 12,216 physical lines parsed as three canonical nonnegative integers. The
file contains 89 identifiers and 1,506 distinct directed nonself pairs, matching
the published metadata; no self-pair, blank line or malformed row was found.
Source times range from 0 to 69,317,577 seconds. This exceeds the predeclared
720-day artifact-extent threshold. It does not establish a continuous real-world
observation interval or a real follow-up closure time.

The original file has **four decreases in successive timestamps**. Selection
therefore filters all lines by source time; neither physical file prefixes nor
line order represent chronological or receipt history. Each line keeps its
original one-based identity for provenance.

There are **164 repeated triple groups, accounting for 165 additional rows**.
All are retained. Without source message IDs, the study cannot determine whether
identical triples represent distinct messages or export duplication. Rates here
count published rows. There are also 1,344 groups with multiple rows at the same
second, including 3,305 additional same-second rows. Their order is not used to
invent within-second behavior or causation. Group-message recipient expansion
also prevents interpreting all directed rows as independent messages.

The reader rejects malformed or oversized input without dropping rows. The
case runner accepts only the reviewed payload and frozen protocol; mismatches
stop the study rather than select new windows. Recompression is permitted when
the decompressed payload is identical. Both actual fingerprints and whether the
compressed bytes match the original acquisition are reported.

## Past-only risk sets and windows

One day means exactly 86,400 source-relative seconds. History begins at the
published zero and expands at each origin. Recent history lasts 30 days and the
prediction horizon lasts 90 days. All intervals include their left boundary and
exclude their right boundary.

| Origin, days | History | Recent history | Target |
| ---: | --- | --- | --- |
| 180 | [0, 180) | [150, 180) | [180, 270) |
| 270 | [0, 270) | [240, 270) | [270, 360) |
| 360 | [0, 360) | [330, 360) | [360, 450) |
| 450 | [0, 450) | [420, 450) | [450, 540) |
| 540 | [0, 540) | [510, 540) | [540, 630) |
| 630 | [0, 630) | [600, 630) | [630, 720) |

At each origin, the risk set contains only directed nonself pairs with at least
one prior archive row. Actor counts likewise use historical nonself endpoints.
The full release's 89 identifiers are not used to construct all possible pairs
or select future-active people. A target-only pair remains outside the frozen
risk set and is counted separately. Self-pairs would remain in the source audit
but would enter neither predictions nor target labels.

The archive publisher's own population selection remains a limitation: selecting
history endpoints within this release cannot recover unrepresented members or
eliminate selection already imposed when the source was published.

## Baselines, labels and common arithmetic

The study uses the existing fixed baselines. With historical count `n`, recent
count `nr`, historical width `W`, recent width `Wr` and target horizon `H`:

| Baseline | Prediction |
| --- | --- |
| Historical Poisson | `1 - exp(-n * H / W)` |
| Recent Poisson | `1 - exp(-nr * H / Wr)` |
| Recent occurrence | 1 when `nr > 0`, otherwise 0 |

`W` and `Wr` are **archive-window durations**, not verified person exposure.
The probability calculations, Brier arithmetic, fixed bins and cross-origin
aggregation share the existing repeat-interaction helpers. This study creates
no `EventDataset` membership/coverage assertions and does not call the strict
R1 scorer with fabricated completeness. It has its own source admission and
record-label contract.

The predictor receives only rows strictly before its origin. After probabilities
are fixed, target rows label each risk pair: at least one matching row is 1,
otherwise 0. Every model uses the same archive labels. Target data do not fit
parameters, change the risk set or tune the declared windows.

Pooled Brier weights each pair-origin observation equally. Macro Brier weights
the six planned origins equally and is null if any origin has an empty risk set.
Repeated observations of the same pair are not independent relationships.
Bins are fixed at `[0, 0.2, 0.4, 0.6, 0.8, 1]`; bins include their left edge,
with 1 included in the final bin. Empty bins retain zero counts and null means.

An **always-zero reference** is declared in advance. For binary labels its Brier
score equals the positive fraction, since `(0-y)^2 = y`. Model Brier minus this
reference helps expose poor performance even when archive positives are sparse;
it is a descriptive comparison, not significance testing or a new fitted model.
No model tuning, confidence interval, dependence-adjusted inference or
calibration-validation claim is made by these calculations.

## Reproduction and output

Obtain the archive from the official URL and retain it outside the repository.
From the repository root in the existing supported environment:

```sh
PYTHONPATH=src python -m sociolab study email-eu-dept3 /path/to/email-Eu-core-temporal-Dept3.txt.gz docs/experiments/2026-11-28-dept3-archive/protocol.json
```

The command reads local files and writes an aggregate JSON report to stdout; it
does not download data. The execution wrapper also takes the archive and a
separate output directory:

```sh
PYTHONPATH=src python docs/experiments/2026-11-28-dept3-archive/run_case.py /path/to/email-Eu-core-temporal-Dept3.txt.gz /path/to/dept3-output
```

Reports retain source/protocol identities, per-origin counts and metrics,
probability bins, risk-set changes and the always-zero reference. Pair-level
prediction arrays remain internal. Raw participant rows, identifiers and private
prediction arrays are not part of the public research report. Source audit,
independent arithmetic comparison and execution evidence remain distinct from
scientific interpretation of any observed model differences.

## Attribution and reuse scope

The source paper is Paranjape, A., Benson, A. R., and Leskovec, J. (2017),
[*Motifs in Temporal Networks*](https://doi.org/10.1145/3018661.3018731),
WSDM, pp. 601–610. The [project page](https://snap.stanford.edu/temporal-motifs/)
provides the research context; the
[SNAP collection](https://snap.stanford.edu/data/index.html) asks dataset users
to cite the collection and supplies a Leskovec/Krevl (2014) citation.

No dataset-specific license or explicit aggregate-publication license was found
on the reviewed primary pages. The
[SNAP BSD license page](https://snap.stanford.edu/snap/license.html) concerns
software and is not applied to these data. Local processing and attributed
aggregate reporting follow the source's public research-distribution context;
that is an interpretation of its presentation, not a statement of unrestricted
reuse or redistribution rights. This repository publishes methodology, input
fingerprints and aggregate evidence without redistributing source rows.

## Executed results

The frozen study completed all six planned origins with **7,375 pair-origin
observations**, of which 1,590 were archive positives and 5,785 archive negatives.
These are repeated evaluations of directed pairs, not 7,375 independent
relationships. The full [case report](experiments/2026-11-28-dept3-archive/case-report.json)
retains all planned windows, counts, probability bins and input identities.

### Scores and the empty target periods

Brier is mean squared probability error; smaller values are better for these
specified archive labels.

| Fixed predictor | Pooled Brier | Equal-origin macro Brier | Mean prediction |
| --- | ---: | ---: | ---: |
| Historical Poisson | 0.226381 | 0.222725 | 0.484004 |
| Recent Poisson | 0.188356 | 0.205546 | 0.188292 |
| Recent occurrence | 0.194305 | 0.211766 | 0.194034 |

The declared always-zero reference has pooled Brier **0.215593**, equal to the
archive positive fraction. Recent Poisson is lower by 0.027237, recent occurrence
by 0.021288, while historical Poisson is higher by 0.010788. These are descriptive
loss differences for this release and plan, not uncertainty-qualified improvement
estimates or evidence of real communication prediction.

The ranking needs the per-origin evidence:

| Origin, days | Risk pairs | Archive positives | All target rows | Historical Brier | Recent Poisson Brier | Recent occurrence Brier | Always-zero Brier |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 180 | 845 | 402 | 2,659 | 0.206719 | 0.325791 | 0.334911 | 0.475740 |
| 270 | 1,042 | 340 | 1,773 | 0.223006 | 0.264672 | 0.271593 | 0.326296 |
| 360 | 1,163 | 387 | 1,773 | 0.194918 | 0.247641 | 0.253654 | 0.332760 |
| 450 | 1,317 | 461 | 2,380 | 0.184975 | 0.236877 | 0.242217 | 0.350038 |
| 540 | 1,504 | 0 | 0 | 0.277758 | 0.158292 | 0.168218 | 0.000000 |
| 630 | 1,504 | 0 | 0 | 0.248976 | 0.000000 | 0.000000 | 0.000000 |

**The released file has no rows in either [540,630) or [630,720) days.** This is
not merely an absence among the historical risk pairs: the entire selected
target intervals are empty. These periods contribute 3,008 observations, or
40.7864% of the pooled denominator. Their zero labels are correct under the
frozen archive-record definition. Their cause is not established; the experiment
cannot distinguish actual silence, collection gaps or publication selection.
There are another 117 rows at day 720 or later, so these are internal archive
gaps rather than targets padded beyond the final published event. Their later
presence does not resolve the cause of the empty periods.

Historical Poisson has the lowest Brier of the three models at each of the first
four origins; the recent models do better in the two empty target periods. Thus
the overall ranking is strongly affected by the archive's empty periods and by
the expanding risk-set weights. No empty period was removed, no window was
shifted, and no model was tuned after this result. A zero error in the last
period is agreement with an empty released target, not demonstrated perfect
prediction of people's behavior.

### Probability diagnostics

The recent Poisson predictor has only two populated probability bins:

| Probability group | Pair-origin count | Mean predicted probability | Archive positive fraction |
| --- | ---: | ---: | ---: |
| Probability 0 | 5,944 | 0.000000 | 0.133917 (796 positives) |
| [0.8,1] | 1,431 | 0.970410 | 0.554857 (794 positives) |

This follows from the fixed formula: the horizon is three times the recent
window, so one recent row already produces `1-exp(-3)`, approximately 0.950213.
With integer row counts, predictions are either zero or at least that value.
The middle bins are therefore structurally empty, not lost output.

The high-probability group's prediction exceeds its observed archive frequency,
while the zero group still contains positive outcomes. A pooled mean prediction
near the pooled positive fraction would not establish calibration. Historical
Poisson also overpredicts in aggregate: mean 0.484004 versus observed 0.215593.
These diagnostics identify limitations of the fixed baselines; they do not
identify latent motivation, relationship endings or causal influence.

### Verification evidence

The [execution record](experiments/2026-11-28-dept3-archive/execution.json) records
two successful subprocesses: the actual source CLI and the independent checker.
Source, protocol, checker and archive hashes remained unchanged. No raw source
rows or private pair predictions were included in the public outputs.

The [standard-library checker](experiments/2026-11-28-dept3-archive/independent_check.py)
imports no SocioLab code and independently computes source-time counts,
probabilities using `1-exp(-x)`, Brier scores, risk changes and bins. Its
[result](experiments/2026-11-28-dept3-archive/independent-check.json) has
**727 exact comparisons and 673 numeric comparisons, zero mismatches**, and
maximum absolute numeric difference **2.2737367544323206e-13**, below the
predeclared checker tolerance of 1e-12. Exact forecast hashes are reconstructed
separately with the documented `expm1` serialization expression; the numerical
oracle remains independent. All six forecast, history-row and target-row hashes
are checked.

The [native test record](experiments/2026-11-28-dept3-archive/tests-execution.json)
and [log](experiments/2026-11-28-dept3-archive/native-tests.log) record **493 passing
tests**, including **14 new tests**, in 10.838 seconds, with no failures, errors
or skips. Source/test hashes stayed unchanged. Existing strict R1 score/hash
compatibility tests pass after the arithmetic extraction. No dependency,
installer/consumer test, R runtime or CI workflow was added.

This completes one bounded released-record temporal holdout and its software
checks. Real-world observation coverage, externally validated prediction,
dependence-aware uncertainty, calibrated probabilities, relationship-state
measurement and causal interpretation remain open research requirements.
