# Dept3 released-record recurrence study — 2026-11-28

This experiment evaluates recurrence in one fixed published email archive.
It does not qualify complete real communication observation or relationship
termination. See the [contract and full interpretation](../../archive-recurrence.md).

The protocol was publicly committed before source acquisition as
[`4c93277b7098d2e98e6a4d22874c8e0b9f976d5b`](https://github.com/qigao/SocioLab/commit/4c93277b7098d2e98e6a4d22874c8e0b9f976d5b).
It fixes six source-relative origins, 90-day targets, 30-day recent windows,
past-only directed risk pairs, the three existing baselines and probability bins.

| Artifact | What it records |
| --- | --- |
| `protocol.json` | Unchanged pre-acquisition study choices and scope. |
| `metadata-review.json` | Official information and reuse review before downloading raw events. |
| `source-acquisition.json` | Actual download, HTTP result and acquisition timestamps. |
| `source-audit.json` | Complete file/structure audit before scores were calculated. |
| `case-report.json` | All six origins, 7,375 pair-origin labels, scores, bins and source identities. |
| `independent_check.py` / `independent-check.json` | Separate standard-library arithmetic/hash verification and its passing result. |
| `run_case.py` / `execution.json` | Actual CLI and checker execution, input/code hashes and output hashes. |
| `study.stderr.log` / `checker.stderr.log` | Empty stderr from the two successful subprocesses. |
| `tests-execution.json` / `native-tests.log` | 493 passing native tests, including 14 new tests; unchanged code/test hashes. |

The result retains two empty target intervals, days [540,630) and [630,720).
They contribute 3,008 of the 7,375 pair-origin observations and materially affect
the pooled model ranking. Their cause is unknown. No windows were removed or
retuned after inspecting this result.

Reproduce using a local copy of the reviewed official gzip in the project's
existing supported Python environment:

```sh
PYTHONPATH=src python docs/experiments/2026-11-28-dept3-archive/run_case.py /path/to/email-Eu-core-temporal-Dept3.txt.gz /path/to/new-output-directory
```

Use a new output directory; the runner does not overwrite retained study files.
The CLI and independent checker also accept explicit paths as documented in
their help. No raw source data or private pair predictions are distributed here.
The source audit's `models_scored: false` describes the audit stage; later
execution and scores are recorded separately.
