# Multi-origin repeat-interaction validation — 2026-11-28

This directory preserves software validation evidence for the multi-origin
evaluation slice of R1. It is not a real-source prediction experiment.

- `tests-execution.json`: exact native command, Python version, execution times,
  479-test result, 25 new tests, complete source/test hashes before and after,
  and log SHA-256.
- `native-tests.log`: complete native test output, with no failures/errors/skips.

Reproduce the native suite from the repository root in its existing supported
environment:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

The new tests check independent authored probability/error expectations,
coverage and missing-origin denominators, changing past-only risk sets, target
revisions, exact old-version replay, unchanged single-origin report identities,
UTC arithmetic, malformed input handling and CLI manifest resolution. They are
engineering tests, not observations of real people or calibration evidence.

The [source review](../../repeat-interaction-source-review.md) records actual
file/metadata inspection and each candidate's current admission decision.
Source observations, participant identifiers and raw research data are not
included in this evidence directory. No R runtime, model dependency, installer
test, consumer test or CI workflow was added.
