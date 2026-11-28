"""Synthetic, receipt-bound forecasts using independent declared outcome journals.

Keep saved semantic-panel features at their issued versions. Train only on
past outcome records and score separately on explicitly selected later receipts.
"""
from copy import deepcopy
from math import fsum, isfinite, sqrt

import numpy as np

from .behavior_forecast import _condition_number, _errors, _predictions, _runtime
from .events import EventDataset, parse_time
from .journal_forecast import _behavior_at, _prefix as outcome_prefix
from .journal_evaluation import _future_stream_gate, _target_ancestry_gate
from .semantic_llm import _digest
from .semantic_panel import _verify_plan as verify_panel_plan, verify_semantic_panel
from .semantic_multilayer_structure import _cohort

UTC = {"kind": "utc"}
PLAN = "sociolab.semantic-forecast-plan.v1"
FORECAST = "sociolab.semantic-forecast-artifact.v1"
MODELS = {
    "persistence": ("own_lag",),
    "own_lag_ols": ("intercept", "own_lag"),
    "language_ols": ("intercept", "own_lag", "selected_topic_expression_count"),
    "language_network_ols": ("intercept", "own_lag", "selected_topic_expression_count",
                             "coattendance_neighbors"),
}


def _fields(value, names, label):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError("invalid " + label + " fields")


def _check_hash(value, field):
    if type(value) is not dict or value.get(field) != _digest({k: v for k, v in value.items() if k != field}):
        raise ValueError("digest mismatch: " + field)


def _text(value, label):
    if type(value) is not str or not value.strip() or value.strip() != value:
        raise ValueError("nonempty trimmed " + label + " required")


def _source(value):
    _fields(value, "system attribute minimum maximum measurement_reference", "outcome source")
    for field in ("system", "attribute", "measurement_reference"):
        _text(value[field], field)
    low, high = value["minimum"], value["maximum"]
    if type(low) is not int or type(high) is not int or low < 0 or not 1 <= high-low <= 99:
        raise ValueError("outcome scale requires 2 to 100 declared nonnegative integer levels")
    return deepcopy(value)


def _outcome_context(dataset, outcomes, actors, source, cutoff, as_of, journal_cutoff):
    if (not isinstance(outcomes, EventDataset) or outcomes.origin != "synthetic" or
            outcomes.dataset_id == dataset.dataset_id or outcomes.clock != dataset.clock):
        raise ValueError("separate synthetic outcome journal with matching source clock required")
    if type(cutoff) is not int:
        raise ValueError("explicit outcome receipt cutoff required")
    context = outcome_prefix(outcomes, cutoff)
    instant = parse_time(as_of, UTC)
    if cutoff and parse_time(outcomes.records[cutoff-1]["recorded_at"], UTC) > instant:
        raise ValueError("outcome receipts unavailable at declared origin")
    if any(r["source"]["system"] == source["system"] for r in dataset.records[:journal_cutoff]):
        raise ValueError("declared outcome system must be separate from selected feature journal sources")
    for record in context["receipt_records"]:
        if record["kind"] not in ("entity.observed", "identity.mapped", "actor.attribute.observed"):
            raise ValueError("outcome journal admits only identity and attribute observations")
        if record["kind"] == "actor.attribute.observed" and record["source"]["system"] != source["system"]:
            raise ValueError("outcome attributes must belong to the declared separate source system")
    _cohort(outcomes, cutoff, actors)
    return context


def _behavior_spec(actors, source, cutoff, target_at):
    return {"actors": actors, "knowledge_cutoff": cutoff, "target_at": target_at,
        "behavior_source": {"system": source["system"], "attribute": source["attribute"]},
        "forecast_specification": {"behavior": {"minimum": source["minimum"], "maximum": source["maximum"]}}}


def _plan(dataset, store, panel_plan, outcomes, *, outcome_source, action,
          initial_history_waves, registration_outcome_cutoff):
    verify_panel_plan(dataset, store, panel_plan)
    source = _source(outcome_source)
    actors = panel_plan["settings"]["actors"]
    schedule = panel_plan["schedule"]
    if not 2 <= len(actors) <= 200:
        raise ValueError("forecast cohort requires 2 to 200 people")
    if type(initial_history_waves) is not int or not 3 <= initial_history_waves <= len(schedule)-2:
        raise ValueError("at least three history waves and two planned forecast folds required")
    if type(action) is not str or action not in panel_plan["settings"]["actions"]:
        raise ValueError("forecast action must be selected by the panel plan")
    if any(parse_time(a["end"], dataset.clock) != parse_time(b["start"], dataset.clock)
           for a,b in zip(schedule, schedule[1:])):
        raise ValueError("forecast schedule requires contiguous equal-duration waves")
    reg = panel_plan["registration"]
    ctx = _outcome_context(dataset, outcomes, actors, source, registration_outcome_cutoff,
        reg["registered_at"], reg["journal_cutoff"])
    first_target = schedule[initial_history_waves]["end"]
    _future_stream_gate(outcomes, _behavior_spec(actors, source, registration_outcome_cutoff, first_target))
    folds = []
    for i in range(initial_history_waves, len(schedule)):
        origin, target = schedule[i-1], schedule[i]
        if dataset.clock["kind"] == "utc" and parse_time(target["end"], dataset.clock) <= parse_time(origin["as_of"], UTC):
            raise ValueError("UTC target must occur after its forecast origin")
        folds.append({"fold_id": target["wave_id"], "history_wave_count": i,
            "origin_wave_id": origin["wave_id"], "origin_as_of": origin["as_of"],
            "target_at": target["end"], "score_as_of": target["as_of"]})
    result = {"schema": PLAN, "profile": "SYNTHETIC_RESEARCH_ONLY",
        "panel_plan_hash": panel_plan["plan_hash"], "actors": actors,
        "outcome_source": source, "outcome_dataset": ctx["prefix_envelope"],
        "registration_outcome_cutoff": registration_outcome_cutoff,
        "registration_outcome_prefix_hash": ctx["prefix_content_hash"],
        "action": action, "initial_history_waves": initial_history_waves, "folds": folds,
        "model_features": {name: list(fields) for name,fields in MODELS.items()},
        "outcome_independence": "SEPARATE_DECLARED_SOURCE_NOT_EXTERNALLY_VERIFIED",
        "primary_metric": "clipped_pooled_mae_all_planned_folds",
        "qualification_status": "NOT_ESTABLISHED"}
    result["plan_hash"] = _digest(result)
    return result


def freeze_semantic_forecast_plan(dataset, store, panel_plan, outcomes, *, outcome_source,
                                  action, initial_history_waves):
    """Freeze model features and all future folds against the initial prefixes."""
    reg = panel_plan["registration"]
    if len(dataset.records) != reg["journal_cutoff"] or len(store.records) != reg["observation_cutoff"]:
        raise ValueError("forecast registration requires exact panel registration prefixes")
    return _plan(dataset, store, panel_plan, outcomes, outcome_source=outcome_source,
        action=action, initial_history_waves=initial_history_waves,
        registration_outcome_cutoff=len(outcomes.records))


def _verify_plan(dataset, store, panel_plan, outcomes, plan):
    _check_hash(plan, "plan_hash")
    rebuilt = _plan(dataset, store, panel_plan, outcomes,
        outcome_source=plan["outcome_source"], action=plan["action"],
        initial_history_waves=plan["initial_history_waves"],
        registration_outcome_cutoff=plan["registration_outcome_cutoff"])
    if rebuilt != plan:
        raise ValueError("forecast plan does not replay exactly")


def _feature_values(wave, values, actors, action):
    rows = {r["actor_id"]: r for r in wave["features"]["rows"]}
    if set(rows) != set(actors):
        raise ValueError("issued feature roster differs from fixed cohort")
    return [[1.0, float(values[a]),
        float(rows[a]["expression_actions"][action]["person_topic"]["selected_expression_count"]),
        rows[a]["attendance"]["coattendance_neighbors"]] for a in actors]


def _matrix(rows, names):
    columns = ("intercept", "own_lag", "selected_topic_expression_count", "coattendance_neighbors")
    return [[row[columns.index(name)] for name in names] for row in rows]


def _history(dataset, store, panel_plan, panel, outcomes, plan, fold_id, cutoff):
    _verify_plan(dataset, store, panel_plan, outcomes, plan)
    saved = verify_semantic_panel(dataset, store, panel_plan, panel)
    folds = [f for f in plan["folds"] if f["fold_id"] == fold_id]
    if len(folds) != 1:
        raise ValueError("fold must be in frozen forecast schedule")
    fold = folds[0]
    waves = saved["waves"]
    if len(waves) != fold["history_wave_count"] or waves[-1]["wave_id"] != fold["origin_wave_id"]:
        raise ValueError("forecast requires the exact issued history panel through its origin")
    if type(cutoff) is not int or cutoff < plan["registration_outcome_cutoff"]:
        raise ValueError("outcome history cutoff precedes registration")
    ctx = _outcome_context(dataset, outcomes, plan["actors"], plan["outcome_source"], cutoff,
        fold["origin_as_of"], waves[-1]["journal_cutoff"])
    spec = _behavior_spec(plan["actors"], plan["outcome_source"], cutoff, fold["target_at"])
    _future_stream_gate(outcomes, spec)
    series, evidence, labels = [], [], []
    for wave in waves:
        values, refs = _behavior_at(outcomes, spec, wave["window"]["end"], ctx)
        # Use past features as issued; labels may be revised as known at this origin.
        series.append(_feature_values(wave, values, plan["actors"], plan["action"]))
        labels.append([float(values[a]) for a in plan["actors"]])
        evidence.extend(refs)
    flat = [r for wave in series[:-1] for r in wave]
    y = np.asarray([v for wave in labels[1:] for v in wave], dtype=np.float64)
    train = {name: _matrix(flat, names) for name,names in MODELS.items() if name != "persistence"}
    last = {name: _matrix(series[-1], names) for name,names in MODELS.items()}
    binding = {"fold": fold, "panel_hash": saved["panel_hash"],
        "origin_wave_hash": waves[-1]["wave_hash"], "outcome_history_cutoff": cutoff,
        "outcome_history_prefix_hash": ctx["prefix_content_hash"], "history_outcome_evidence_hash": _digest(evidence),
        "label_hash": _digest(y.tolist()), "training_row_count": len(y),
        "training_feature_hashes": {name: _digest(matrix) for name,matrix in train.items()},
        "forecast_feature_hashes": {name: _digest(matrix) for name,matrix in last.items()}}
    return binding, train, last, y, ctx


def _missing(matrix):
    return any(value is None for row in matrix for value in row)


def _fit(train, last, y, source, name):
    low, high = source["minimum"], source["maximum"]
    if name == "persistence":
        raw, clipped, count = _predictions(np.asarray(last[name], dtype=np.float64)[:,0], low, high)
        return {"status": "OK", "reason": None, "algorithm": "last_observed_behavior",
            "coefficients": None, "rank": None, "singular_values": None, "condition_number": None,
            "raw_predictions": raw, "clipped_predictions": clipped, "clipping_count": count}
    coefficients = rank = singular = condition = None
    if _missing(train[name]) or _missing(last[name]):
        reason = "missing_required_feature"
    else:
        x = np.asarray(train[name], dtype=np.float64)
        coef, residual, rank, singular = np.linalg.lstsq(x, y, rcond=None)
        if not all(np.isfinite(a).all() for a in (coef, residual, singular)):
            raise ValueError("nonfinite least squares diagnostics")
        coefficients, rank, singular = coef.tolist(), int(rank), singular.tolist()
        condition = _condition_number(singular)
        reason = ("insufficient_training_rows" if x.shape[0] <= x.shape[1] else
                  "rank_deficient_training_design" if rank != x.shape[1] else None)
    raw = clipped = count = None
    if reason is None:
        raw, clipped, count = _predictions(np.asarray(last[name], dtype=np.float64) @ np.asarray(coefficients), low, high)
    return {"status": "OK" if reason is None else "NOT_ESTIMABLE", "reason": reason,
        "algorithm": "numpy.linalg.lstsq", "coefficients": coefficients, "rank": rank,
        "singular_values": singular, "condition_number": condition, "raw_predictions": raw,
        "clipped_predictions": clipped, "clipping_count": count}


def issue_semantic_forecast(dataset, store, panel_plan, panel, outcomes, plan, *, fold_id):
    """Fit on the supplied historical prefix only; no target argument exists."""
    binding, train, last, y, _ = _history(dataset, store, panel_plan, panel, outcomes, plan,
        fold_id, len(outcomes.records))
    origin = panel["waves"][-1]
    if len(dataset.records) != origin["journal_cutoff"] or len(store.records) != origin["observation_cutoff"]:
        raise ValueError("issue from the exact feature journal and sidecar origin prefixes")
    result = {"schema": FORECAST, "profile": "SYNTHETIC_RESEARCH_ONLY",
        "plan_hash": plan["plan_hash"], "actors": plan["actors"], "input": binding,
        "models": {name: _fit(train, last, y, plan["outcome_source"], name) for name in MODELS},
        "runtime": _runtime(), "external_issuance_attested": False,
        "qualification_status": "NOT_ESTABLISHED"}
    result["forecast_hash"] = _digest(result)
    return result


def _validate_models(models, train, last, y, source):
    """Check saved predictions against their declared coefficients; never refit."""
    if type(models) is not dict or set(models) != set(MODELS):
        raise ValueError("exact frozen forecast model set required")
    low, high = source["minimum"], source["maximum"]
    for name, model in models.items():
        _fields(model, "status reason algorithm coefficients rank singular_values condition_number raw_predictions clipped_predictions clipping_count", "model")
        if name == "persistence":
            if (model["algorithm"] != "last_observed_behavior" or model["reason"] is not None or
                    any(model[f] is not None for f in ("coefficients","rank","singular_values","condition_number"))):
                raise ValueError("invalid persistence diagnostics")
            reason = None
            expected = _predictions(np.asarray(last[name],dtype=np.float64)[:,0],low,high)
        else:
            if model["algorithm"] != "numpy.linalg.lstsq":
                raise ValueError("unexpected forecast algorithm")
            p = len(MODELS[name])
            if _missing(train[name]) or _missing(last[name]):
                if any(model[f] is not None for f in ("coefficients","rank","singular_values","condition_number")):
                    raise ValueError("missing features cannot have fitted diagnostics")
                reason = "missing_required_feature"
            else:
                coef, rank, singular = model["coefficients"], model["rank"], model["singular_values"]
                if (type(coef) is not list or len(coef) != p or type(rank) is not int or
                        not 0 <= rank <= min(len(y),p) or type(singular) is not list or len(singular) != min(len(y),p) or
                        any(type(v) not in (int,float) or not isfinite(v) for v in coef+singular) or
                        any(v < 0 for v in singular) or model["condition_number"] != _condition_number(singular)):
                    raise ValueError("invalid saved least squares diagnostics")
                reason = ("insufficient_training_rows" if len(y) <= p else
                    "rank_deficient_training_design" if rank != p else None)
            expected = (None,None,None) if reason else _predictions(
                np.asarray(last[name],dtype=np.float64) @ np.asarray(model["coefficients"],dtype=np.float64),low,high)
        if model["status"] != ("OK" if reason is None else "NOT_ESTIMABLE") or model["reason"] != reason:
            raise ValueError("saved forecast status is inconsistent")
        if (model["raw_predictions"], model["clipped_predictions"], model["clipping_count"]) != expected:
            raise ValueError("saved predictions do not match frozen feature inputs and coefficients")


def score_semantic_forecast(dataset, store, panel_plan, panel, outcomes, plan, forecast, *, target_cutoff):
    """Replay issued features and outcome history, then score an explicit later target version."""
    _check_hash(forecast, "forecast_hash")
    _fields(forecast, "schema profile plan_hash actors input models runtime external_issuance_attested qualification_status forecast_hash", "forecast")
    if (forecast["schema"] != FORECAST or forecast["profile"] != "SYNTHETIC_RESEARCH_ONLY" or
            forecast["plan_hash"] != plan["plan_hash"] or forecast["actors"] != plan["actors"] or
            forecast["runtime"] != _runtime() or forecast["external_issuance_attested"] is not False or
            forecast["qualification_status"] != "NOT_ESTABLISHED"):
        raise ValueError("forecast profile, plan, roster or runtime mismatch")
    original = forecast["input"]
    k = original["outcome_history_cutoff"]
    binding, train, last, y, history_ctx = _history(dataset, store, panel_plan, panel, outcomes, plan,
        original["fold"]["fold_id"], k)
    if binding != original:
        raise ValueError("forecast input does not replay exactly")
    _validate_models(forecast["models"], train, last, y, plan["outcome_source"])
    fold = binding["fold"]
    if type(target_cutoff) is not int or target_cutoff <= k:
        raise ValueError("target outcome cutoff must be later than forecast history")
    ctx = _outcome_context(dataset, outcomes, plan["actors"], plan["outcome_source"], target_cutoff,
        fold["score_as_of"], panel["waves"][-1]["journal_cutoff"])
    spec = _behavior_spec(plan["actors"], plan["outcome_source"], target_cutoff, fold["target_at"])
    actual, evidence = _behavior_at(outcomes, spec, fold["target_at"], ctx, issuance=history_ctx)
    _target_ancestry_gate(outcomes, {"provenance":{"behavior_evidence":evidence}}, k, target_cutoff)
    # Also reject a later-appended target whose declared receipt timestamp
    # says that its fact already existed by the forecast origin.
    first_receipts = {}
    for record in ctx["receipt_records"]:
        key = (record["source"]["system"], record["fact_id"])
        first_receipts.setdefault(key, record["recorded_at"])
    origin_time = parse_time(fold["origin_as_of"], UTC)
    for item in evidence:
        record = item["record"]
        key = (record["source"]["system"], record["fact_id"])
        if parse_time(first_receipts[key], UTC) <= origin_time:
            raise ValueError("target fact receipt timestamp must follow the forecast origin")
    target = np.asarray([actual[a] for a in plan["actors"]], dtype=np.float64)
    scores = {}
    for name, model in forecast["models"].items():
        ok = model["status"] == "OK"
        scores[name] = {"status":model["status"], "reason":model["reason"],
            "n_evaluated":len(target) if ok else 0,
            "raw":_errors(model["raw_predictions"],target) if ok else None,
            "clipped":_errors(model["clipped_predictions"],target) if ok else None}
    result = {"schema":"sociolab.semantic-forecast-score.v1","profile":"SYNTHETIC_RESEARCH_ONLY",
        "plan_hash":plan["plan_hash"],"fold_id":fold["fold_id"],"forecast_hash":forecast["forecast_hash"],
        "target_cutoff":target_cutoff,"target_prefix_hash":ctx["prefix_content_hash"],
        "target_evidence_hash":_digest(evidence),"actor_count":len(target),"models":scores,
        "qualification_status":"NOT_ESTABLISHED","causal_effect_identified":False}
    result["score_hash"] = _digest(result)
    return result


def evaluate_semantic_forecasts(dataset, store, panel_plan, outcomes, plan, folds):
    """Require all planned folds; aggregate only complete model coverage."""
    _verify_plan(dataset, store, panel_plan, outcomes, plan)
    if type(folds) is not list or len(folds) != len(plan["folds"]):
        raise ValueError("all planned forecast folds required")
    scores = []
    for expected, item in zip(plan["folds"], folds):
        _fields(item, "panel forecast target_cutoff", "fold manifest")
        score = score_semantic_forecast(dataset, store, panel_plan, item["panel"], outcomes,
            plan, item["forecast"], target_cutoff=item["target_cutoff"])
        if score["fold_id"] != expected["fold_id"]:
            raise ValueError("fold manifest must follow frozen order")
        scores.append(score)
    total = len(plan["actors"])*len(scores)
    models = {}
    for name in MODELS:
        rows = [s["models"][name] for s in scores]
        covered = sum(r["n_evaluated"] for r in rows)
        metrics = None
        if covered == total:
            metrics = {variant:{
                "mae":fsum(r[variant]["mae"]*r["n_evaluated"] for r in rows)/total,
                "rmse":sqrt(fsum(r[variant]["rmse"]**2*r["n_evaluated"] for r in rows)/total)}
                for variant in ("raw","clipped")}
        models[name] = {"status":"OK" if metrics is not None else "NOT_ESTIMABLE",
            "n_evaluated":covered,"n_planned":total,"metrics":metrics,
            "unavailable_folds":[s["fold_id"] for s,r in zip(scores,rows) if r["status"]!="OK"]}
    comparisons = {}
    for name, base in (("language_ols","own_lag_ols"),("language_network_ols","own_lag_ols"),
                       ("language_network_ols","language_ols")):
        a,b = models[name]["metrics"],models[base]["metrics"]
        comparisons[name+"_minus_"+base] = None if a is None or b is None else a["clipped"]["mae"]-b["clipped"]["mae"]
    result = {"schema":"sociolab.semantic-forecast-evaluation.v1","profile":"SYNTHETIC_RESEARCH_ONLY",
        "plan_hash":plan["plan_hash"],"fold_count":len(scores),"actor_forecast_count":total,
        "scores":scores,"models":models,"clipped_pooled_mae_differences":comparisons,
        "qualification_status":"NOT_ESTABLISHED","external_issuance_attested":False,
        "empirical_accuracy_established":False,"causal_effect_identified":False}
    result["result_hash"] = _digest(result)
    return result
