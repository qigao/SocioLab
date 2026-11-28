"""Predeclared multi-origin evaluation of receipt-bound interaction forecasts.

This module schedules and aggregates the existing repeat-interaction profile.
It does not add a predictor, infer missing outcomes, or authenticate when a
plan or prediction was created. Missing saved forecasts remain visible slots.
"""

from __future__ import annotations

from copy import deepcopy
import math

from .behavior_forecast import _fields, _integer
from .events import EventDataset, parse_time
from .repeat_interaction import (
    _MODELS, _probability_bins, diagnose_repeat_interaction_forecast,
    make_repeat_interaction_forecast,
)
from .snapshots import content_hash


_PROFILE = "receipt-repeat-pairs-multi-origin-v1"
_PLAN_FIELDS = {
    "schema", "kind", "profile", "initial_specification", "schedule", "journal",
    "policies", "scope", "content_hash",
}
_TIME_FIELDS = {"origin_at", "recent_start", "target_end"}
_SCOPE = {
    "analysis": "retrospective_receipt_version_multi_origin_evaluation",
    "plan_uses_initial_receipt_prefix_only": True,
    "prospective_plan_timestamp_authenticated": False,
    "prospective_issuance_verified": False,
    "receipt_timestamps_authenticated": False,
    "observation_declarations_authenticated": False,
    "empirical_forecast_validated": False,
    "probability_calibration_validated": False,
    "calibration_fitted": False,
    "population_boundary_qualified": False,
    "relationship_state_inferred": False,
    "window_expiry_is_relationship_termination": False,
    "causal_effect_identified": False,
    "dependent_pairs_treated_as_iid": False,
    "uncertainty_intervals": False,
    "automatic_forecast_issuance": False,
}
_POLICIES = {
    "history": "fixed_start_expanding_as_known_receipt_prefix",
    "risk_set": "each_origin_history_positive_ordered_pairs",
    "roster": "fixed_canonical_actors_and_alias_map",
    "recent_window": "constant_duration",
    "target_windows": "constant_duration_nonoverlapping",
    "history_cutoffs": "nondecreasing_across_supplied_forecasts",
    "target_versions": "explicit_per_evaluation_fold",
    "previous_target_equals_next_history_required": False,
    "missing_forecast": "explicit_null_slot_unknown_risk_count",
    "pooled_brier": "pair_origin_weighted_on_scorable_subset",
    "macro_brier": "equal_origin_weight_null_unless_every_origin_has_scored_pairs",
    "probability_bins": "predeclared_left_closed_final_bin_includes_one",
}


def _schedule(value: dict, initial: dict, clock: dict) -> dict:
    _fields(value, {"schema", "folds", "probability_bins"}, "repeat-interaction schedule")
    if value["schema"] != "sociolab.repeat-interaction-schedule.v1":
        raise ValueError("unsupported repeat-interaction schedule schema")
    folds = value["folds"]
    if type(folds) is not list or not 2 <= len(folds) <= 100:
        raise ValueError("repeat-interaction schedule requires 2 to 100 origins")
    initial_times = {key: parse_time(initial[key], clock) for key in _TIME_FIELDS}
    horizon = initial_times["target_end"] - initial_times["origin_at"]
    recent_width = initial_times["origin_at"] - initial_times["recent_start"]
    previous_end = None
    normalized = []
    for index, fold in enumerate(folds):
        _fields(fold, _TIME_FIELDS, "scheduled repeat-interaction fold")
        times = {key: parse_time(fold[key], clock) for key in _TIME_FIELDS}
        if index == 0 and times != initial_times:
            raise ValueError("first scheduled fold must match the initial specification windows")
        if times["target_end"] - times["origin_at"] != horizon:
            raise ValueError("all target windows must have the initial horizon")
        if times["origin_at"] - times["recent_start"] != recent_width:
            raise ValueError("all recent windows must have the initial duration")
        if previous_end is not None and times["origin_at"] < previous_end:
            raise ValueError("scheduled target windows must increase without overlap")
        previous_end = times["target_end"]
        normalized.append(deepcopy(fold) if index else {key: initial[key] for key in sorted(_TIME_FIELDS)})
    return {"schema": value["schema"], "folds": normalized,
            "probability_bins": _probability_bins(value["probability_bins"])}


def make_repeat_interaction_plan(dataset: EventDataset, initial_spec: dict, schedule: dict) -> dict:
    """Bind the initial eligible history, window rules and fixed probability bins.

    Only the initial receipt cutoff is consumed. Future receipt counts are not
    guessed in advance. The plan contains the private actor roster; it is not an
    independently registered or timestamped prospective research protocol.
    """
    initial = make_repeat_interaction_forecast(dataset, initial_spec)
    declared = _schedule(schedule, initial["specification"], dataset.clock)
    plan = {
        "schema": "sociolab.repeat-interaction-plan.v1", "kind": "REPEAT_INTERACTION_PLAN",
        "profile": _PROFILE, "initial_specification": initial["specification"], "schedule": declared,
        "journal": {
            "envelope": initial["journal"],
            "initial_knowledge_cutoff": initial["provenance"]["knowledge_cutoff"],
            "initial_prefix_hash": initial["provenance"]["prefix_content_hash"],
            "initial_forecast_hash": initial["content_hash"],
        },
        "policies": deepcopy(_POLICIES),
        "scope": {**_SCOPE, "contains_private_actor_records": True},
    }
    plan["content_hash"] = content_hash(plan)
    return plan


def _validated_plan(dataset: EventDataset, plan: dict) -> dict:
    _fields(plan, _PLAN_FIELDS, "repeat-interaction plan")
    if plan["content_hash"] != content_hash({key: value for key, value in plan.items() if key != "content_hash"}):
        raise ValueError("repeat-interaction plan hash does not match its contents")
    expected = make_repeat_interaction_plan(dataset, plan["initial_specification"], plan["schedule"])
    if content_hash(plan) != content_hash(expected):
        raise ValueError("saved plan does not match its initial journal history and declared profile")
    return expected


def _risk_change(current: set, previous: set | None) -> dict:
    return {
        "risk_set_hash": content_hash(sorted(current)),
        "compared_with_previous_planned_origin": previous is not None,
        "retained_pairs": None if previous is None else len(current & previous),
        "new_pairs": None if previous is None else len(current - previous),
        "removed_pairs": None if previous is None else len(previous - current),
    }


def _model_summary(diagnostics: list[dict], model: str, planned_count: int, bins: list) -> dict:
    scored = [item["score"]["models"][model] for item in diagnostics]
    n = sum(item["n"] for item in scored)
    nonempty = [item for item in scored if item["n"]]
    # Same pair may recur across origins. No independent-sample inference is made.
    result = {
        "n": n,
        "pooled_brier": math.fsum(item["brier"] * item["n"] for item in nonempty) / n if n else None,
        "macro_brier": (math.fsum(item["brier"] for item in nonempty) / planned_count
                        if len(nonempty) == planned_count else None),
        "mean_predicted_probability": (math.fsum(item["mean_predicted_probability"] * item["n"]
                                                for item in nonempty) / n if n else None),
        "observed_fraction": (math.fsum(item["observed_fraction"] * item["n"]
                                       for item in nonempty) / n if n else None),
        "bins": [],
    }
    for index, (lower, upper) in enumerate(zip(bins, bins[1:])):
        rows = [item["models"][model]["bins"][index] for item in diagnostics]
        count = sum(row["count"] for row in rows)
        probability_sum = math.fsum(row["sum_predicted_probability"] for row in rows)
        positives = sum(row["positive_count"] for row in rows)
        error_sum = math.fsum(row["sum_squared_error"] for row in rows)
        result["bins"].append({
            "lower": lower, "upper": upper, "upper_inclusive": index == len(bins) - 2,
            "count": count, "sum_predicted_probability": probability_sum,
            "positive_count": positives, "sum_squared_error": error_sum,
            "mean_predicted_probability": probability_sum / count if count else None,
            "observed_fraction": positives / count if count else None,
            "brier": error_sum / count if count else None,
        })
    return result


def evaluate_repeat_interaction_forecasts(dataset: EventDataset, plan: dict, folds: list[dict]) -> dict:
    """Replay every supplied prediction and preserve every planned origin.

    Each fold has origin_at, forecast and target. A missing saved prediction must
    be an explicit forecast=null/target=null slot; this does not claim to know
    whether a forecast was ever issued or why it was omitted. Other invalid
    inputs raise rather than being silently converted into missing folds.
    """
    declared = _validated_plan(dataset, plan)
    schedule = declared["schedule"]
    if type(folds) is not list or len(folds) != len(schedule["folds"]):
        raise ValueError("supply exactly one fold, including explicit missing slots, for every planned origin")
    initial = declared["initial_specification"]
    initial_cutoff = initial["knowledge_cutoff"]
    initial_aliases = dataset.identity_map_at(initial_cutoff)
    previous_cutoff = initial_cutoff
    previous_risk = None
    diagnostics, reports = [], []
    for index, (fold, window) in enumerate(zip(folds, schedule["folds"])):
        _fields(fold, {"origin_at", "forecast", "target"}, "repeat-interaction evaluation fold")
        if parse_time(fold["origin_at"], dataset.clock) != parse_time(window["origin_at"], dataset.clock):
            raise ValueError("evaluation folds must match the scheduled origin order")
        report = {"index": index, **deepcopy(window)}
        if fold["forecast"] is None:
            if fold["target"] is not None:
                raise ValueError("a missing forecast slot must also have a null target")
            report.update(status="FORECAST_NOT_SUPPLIED", risk_pairs=None, score=None,
                          diagnostic_hash=None, risk_change=None)
            previous_risk = None
        else:
            prediction = fold["forecast"]
            if type(prediction) is not dict or type(prediction.get("specification")) is not dict:
                raise ValueError("supplied forecast must contain a repeat-interaction specification")
            cutoff = _integer(prediction["specification"].get("knowledge_cutoff"), "history knowledge_cutoff")
            if cutoff < previous_cutoff or (index == 0 and cutoff != initial_cutoff):
                raise ValueError("history cutoffs must begin at the initial K and never decrease")
            expected_spec = {**deepcopy(initial), **deepcopy(window), "knowledge_cutoff": cutoff}
            if content_hash(prediction["specification"]) != content_hash(expected_spec):
                raise ValueError("forecast specification must preserve the plan's roster, stream and window rules")
            if dataset.identity_map_at(cutoff) != initial_aliases:
                raise ValueError("every forecast origin must preserve the initial alias map")
            diagnostic = diagnose_repeat_interaction_forecast(
                dataset, prediction, fold["target"], schedule["probability_bins"],
            )
            diagnostics.append(diagnostic)
            score = diagnostic["score"]
            current_risk = {(row["source"], row["target"]) for row in prediction["predictions"]}
            report.update(status=score["status"], risk_pairs=len(current_risk),
                          history_knowledge_cutoff=cutoff,
                          score=score, diagnostic_hash=diagnostic["content_hash"],
                          risk_change=_risk_change(current_risk, previous_risk))
            previous_cutoff, previous_risk = cutoff, current_risk
        reports.append(report)
    counts = {
        "planned_origins": len(reports), "supplied_forecast_origins": len(diagnostics),
        "missing_forecast_origins": len(reports) - len(diagnostics),
        "scorable_origins": sum(item["score"]["counts"]["scorable_pairs"] > 0 for item in diagnostics),
        "fully_scored_origins": sum(item["score"]["status"] == "SCORED" for item in diagnostics),
    }
    for field in ("risk_pairs", "scorable_pairs", "unscored_pairs", "known_positive_pairs",
                  "scorable_positive_pairs", "scorable_negative_pairs", "known_positive_unscored_pairs"):
        counts[field + "_across_supplied_origins"] = sum(item["score"]["counts"][field] for item in diagnostics)
    counts["full_plan_risk_pair_origin_count"] = (
        None if counts["missing_forecast_origins"] else counts["risk_pairs_across_supplied_origins"])
    n = counts["scorable_pairs_across_supplied_origins"]
    reasons = {reason: sum(item["score"]["unscored_reasons"][reason] for item in diagnostics)
               for reason in ("followup_not_closed", "membership_unknown",
                              "membership_not_full_horizon", "coverage_incomplete")}
    all_scored = counts["fully_scored_origins"] == counts["planned_origins"]
    result = {
        "schema": "sociolab.repeat-interaction-evaluation.v1", "kind": "REPEAT_INTERACTION_EVALUATION",
        "profile": _PROFILE, "plan_hash": declared["content_hash"],
        "initial_prefix_hash": declared["journal"]["initial_prefix_hash"],
        "status": "UNSCORED" if not n else ("SCORED" if all_scored else "PARTIALLY_SCORED"),
        "counts": counts, "unscored_reasons": reasons, "folds": reports,
        "probability_bins": schedule["probability_bins"],
        "models": {model: _model_summary(diagnostics, model, len(reports), schedule["probability_bins"])
                   for model in _MODELS},
        "policies": deepcopy(_POLICIES),
        "scope": {**_SCOPE, "contains_private_actor_records": False, "output": "aggregate_only",
                  "all_models_use_same_scoring_pairs": True,
                  "sample_unit": "ordered_pair_origin_not_independent_relationship",
                  "missing_forecast_reason_verified": False,
                  "descriptive_probability_bins_only": True,
                  "target_information_used_to_refit": False,
                  "late_history_revisions_allowed": True},
    }
    result["content_hash"] = content_hash(result)
    return result
