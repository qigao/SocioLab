# R3v: Known-law forecast controls

Refs #23. [R3u native CI #1](https://github.com/qigao/SocioLab/actions/runs/46161894141) passed all 123 methods on `acab4bf6`. Its actual two-origin result, six actor-forecasts, is archived unchanged in [native-run-1-semantic-forecast.json](experiments/2026-11-28-llm/native-run-1-semantic-forecast.json). Clipped pooled MAE: persistence 1.166667, own-lag OLS 1.057264, language OLS 1.074510, language plus network OLS 1.457051. The augmentation did not improve this fixture. Do not tune the model or discard the unfavorable result.

## Controlled recovery, not empirical prediction

Before interpreting real behavioral data, check whether the existing feature and forecast pipeline can recover known signals and a null incremental signal. Use exactly the frozen R3u model families with no production-model changes. The fixture builds a genuine versioned feature journal and reviewed-expression sidecar for four invented people, six source windows with authored support-expression and attendance patterns, and a seventh target-only window. The expression candidates and two reviews are authored fixtures, **not new LLM inference or independent human review**. An independent arithmetic specification of the expected selected-expression and co-attendance neighbor counts is checked against each actual issued feature wave.

Initial behavior levels are 1, 2, 4, 5. For person i and wave t the synthetic generator is

```
y(i,t+1) = y(i,t) + 1 + bL * L(i,t) + bN * N(i,t)
```

where L is the predeclared support-expression count (0 or 1) and N is the predeclared number of other attendees sharing that wave's activity (0–3). The generator reads the predeclared fixture patterns, never the extracted feature values or fitted predictions. Its outcome journal is separately declared but intentionally generated using the same exogenous patterns; this is not an independent empirical outcome.

| Frozen control | bL | bN |
| --- | ---: | ---: |
| Own-history only (null incremental signal) | 0 | 0 |
| Language only | 2 | 0 |
| Network only | 0 | 1 |
| Joint signal | 2 | 1 |

The scale is fixed at 0–99. Initial feature registration precedes wave issuance. In each scenario use four initial history waves, then three expanding-history held-out forecast origins. Issue each forecast before supplying its target outcome batch and score all four people on every planned fold. Retain all forecasts' coefficient diagnostics and aggregate scores in CI. The full augmented design is expected to have rank four at each origin and recover [1,1,bL,bN] within 1e-9 decimal-place assertion precision; its raw pooled MAE is expected to be numerically zero. The null control requires all OLS models to reproduce the same known law. The language-only control requires the language model to recover the signal while own-lag misses it; network-only and joint controls require a nonzero language-only residual error. These are predeclared deterministic checks of an in-family law, not statistical significance tests. They do not establish calibration, power, robustness to noise or model misspecification, or predictive validity for actual people.

The complete plan covers 4 scenarios × 3 folds × 4 actors = 48 actor-forecasts (192 model-level predictions). They are neither 48 independent people nor an empirical benchmark. No replacement or refit of the archived R3u scores. No new default dependency, model downloads, installer/consumer tests, automated real-data admission or causal inference.

## Validation

Five new tests: feature reconstruction plus four control laws. Re-run 123 prior methods, for 128 planned methods. Native CI pending. Once the known-law controls pass, prioritize obtaining a genuinely independently measured behavioral outcome stream and independent semantic review, with frozen prospective test origins, rather than adding more synthetic predictors.
