# R3u: Frozen semantic behavior forecast and separate outcome scoring

Refs #23. [R3t CI #6](https://github.com/qigao/SocioLab/actions/runs/46159679885) passed all 111 methods on `dce36603`, including the empty activity partition repair and the complete three-wave panel. R3u asks whether historical selected language and co-participation features add predictive information about a separately declared behavioral outcome.

## Bounded scope

This is a synthetic engineering study, not empirical social-behavior prediction. The outcome uses a **different EventDataset** with the same source clock, a different dataset ID and an explicitly declared source system separate from feature-journal systems at registration and issuance. Only entity, identity and attribute records are allowed in that outcome journal; all attribute records use the declared outcome system. Use the existing journal point-behavior selector, receipt prefix, future-stream and target ancestry checks. Identity correspondence between journals, source independence, timestamps, and pre-registration are caller declarations, not independently authenticated facts.

Freeze a 2–200 person canonical cohort from the panel plan, contiguous equal-duration windows, at least three initial history waves and at least two subsequent forecast folds. Outcome observations occur exactly at each window end. Freeze the outcome source, attribute, integer scale (2–100 levels), measurement reference, action and model columns before evaluation. UTC targets must occur strictly after their origin's availability; tick clocks do not supply an inferred mapping to wall time.

## Models and evaluation

Each model fits the same fixed actor/transition rows, with y(t+1) as its training label. Own history and separately issued semantic features at t are the only predictors. OLS is the existing NumPy `lstsq` implementation with an intercept; no model selection, hyperparameter tuning, imputation or fallback.

| Model | Features |
| --- | --- |
| persistence | last observed outcome |
| own_lag_ols | intercept, own outcome |
| language_ols | intercept, own outcome, selected person/topic expression count for one frozen action |
| language_network_ols | preceding columns plus historical co-participation neighbor count |

The selected expression count is not complete language coverage and is not a measured attitude. The co-participation neighbor count uses the native projection and is not influence or a social tie. If any required historical or origin network feature is unavailable, that model is NOT_ESTIMABLE. Insufficient rows and rank deficiency are also explicit unavailable reasons. Do not interpret a missing measurement as zero or drop actors. Other models retain their original definitions. Retain raw and scale-clipped point forecasts and least-squares diagnostics. Predictions are private artifacts.

## Receipt and leakage boundaries

```python
from sociolab.semantic_forecast import (
    freeze_semantic_forecast_plan, issue_semantic_forecast,
    score_semantic_forecast, evaluate_semantic_forecasts,
)

study = freeze_semantic_forecast_plan(dataset, store, panel_plan, initial_outcome_journal,
    outcome_source={
        "system": "independent-observer", "attribute": "task_completion_level",
        "minimum": 0, "maximum": 6, "measurement_reference": "synthetic:observer",
    }, action="support", initial_history_waves=3)

forecast = issue_semantic_forecast(origin_dataset, origin_store, panel_plan,
    issued_history_panel, history_outcome_journal, study, fold_id="w4")
# Save forecast before obtaining the separately received target outcome.
score = score_semantic_forecast(later_dataset, later_store, panel_plan,
    issued_history_panel, later_outcome_journal, study, forecast,
    target_cutoff=explicit_target_receipt_prefix)

report = evaluate_semantic_forecasts(later_dataset, later_store, panel_plan,
    later_outcome_journal, study, [
        {"panel": saved_history_1, "forecast": saved_forecast_1, "target_cutoff": L1},
        {"panel": saved_history_2, "forecast": saved_forecast_2, "target_cutoff": L2},
    ])
```

Registration binds the exact initial feature/sidecar prefixes and outcome prefix. Issue from the exact saved panel ending at the planned origin and the supplied outcome receipt prefix available by that origin. Rebuild all saved feature waves at their original cutoffs; never insert later revisions into issued features. Outcome training labels use effective point measurements as known at the current forecast origin, with exact evidence hashes. Require exactly one known integer value for every fixed actor and history time. Reject any raw target-or-later assertion in the declared outcome stream even if retracted. No target input exists at issue.

Scoring reconstructs history and validates the saved prediction bindings and predictions against saved coefficients without refitting. Require a strictly later target receipt prefix available by the frozen target wave deadline; check that every selected target fact's original receipt both follows the history cutoff and has a declared timestamp after issuance. This rejects old facts revised into targets and backdated later appends. Require unchanged identity resolution for target measurements. A different selected target cutoff is a different scoring version and does not alter a saved forecast. Hashes and replay check consistency, not authorship, OLS coefficient authenticity or actual historical issuance. No external leakage/independence guarantee beyond these explicit source and receipt checks.

All planned folds must be supplied in order. Earlier issued feature waves and receipts must remain identical across origins; outcome history cutoffs strictly increase. Score all fixed actors with the original MAE/RMSE routine, retaining per-fold aggregate raw and clipped losses. Pool losses using the same actor-forecast denominator; RMSE is pooled from squared RMSEs, not averaged. The primary metric is clipped pooled MAE across **all** planned folds. If any model lacks a fold, its full-plan metrics and comparisons are null with explicit coverage. Negative language-minus-baseline or network-minus-language MAE difference favors the augmented model on that synthetic task only. Do not estimate uncertainty from repeated actor rows as if independent people.

## Native validation

Twelve new tests plus 111 preceding methods. The genuine NumPy two-origin fixture constructs a separate synthetic outcome stream in five batches, issues two forecasts before supplying their respective targets, verifies rank and the persistence pooled MAE of 7/6, scores without refitting, and logs a complete aggregate comparison. The test also exercises missing network features, missing/ambiguous outcomes, retracted early targets, late and backdated receipts, target ancestry, target revision replay, plan binding, forged predictions, rank deficiency, incomplete fold coverage, and rewritten history rejection. Authored outcomes and fixture relationships are synthetic, not blinded external evidence. Exact-head native CI pending at submission. No default dependency change, installer/consumer test, model download, real-data admission, or causal claim.
