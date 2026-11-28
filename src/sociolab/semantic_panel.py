"""Frozen, receipt-bound longitudinal panel for synthetic semantic research."""
from copy import deepcopy
from math import isfinite

import networkx as nx

from .changes import _project_graph
from .communities import community_report
from .events import parse_time
from .semantic_actions import ACTIONS
from .semantic_llm import _digest
from .semantic_multilayer import build_multilayer_frame, _check_availability
from .semantic_multilayer_structure import (_ids, _cohort, _expression_graph,
    _topic_profile, _centrality)
from .semantic_observations import _dataset_binding, _check_prefixes

PLAN_SCHEMA = "sociolab.semantic-panel-plan.v1"
PANEL_SCHEMA = "sociolab.semantic-longitudinal-panel.v1"
UTC = {"kind": "utc"}


def _exact_fields(value, fields, what):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError("invalid " + what + " fields")


def _settings(value):
    _exact_fields(value, "actors actions population roles affiliation_projection max_pairs seed resolution max_nodes max_edges",
        "panel settings")
    settings = deepcopy(value)
    settings["actors"] = _ids(value["actors"], "fixed cohort")
    settings["actions"] = _ids(value["actions"], "expression actions")
    settings["roles"] = _ids(value["roles"], "attendance roles", nonempty=False)
    _ids([value["population"]], "population")
    if not set(settings["actions"]) <= set(ACTIONS):
        raise ValueError("unknown panel action")
    if value["affiliation_projection"] not in ("none", "count", "newman"):
        raise ValueError("unknown affiliation projection")
    for field in ("seed", "max_pairs", "max_edges"):
        if type(value[field]) is not int or value[field] < 0:
            raise ValueError("invalid nonnegative " + field)
    if type(value["max_nodes"]) is not int or value["max_nodes"] < 1:
        raise ValueError("invalid node budget")
    if (type(value["resolution"]) not in (int, float) or
            not isfinite(value["resolution"]) or value["resolution"] <= 0):
        raise ValueError("invalid resolution")
    return settings


def _schedule(dataset, schedule, registered_at):
    if type(schedule) is not list or not 2 <= len(schedule) <= 32:
        raise ValueError("panel needs 2 to 32 scheduled waves")
    registration = parse_time(registered_at, UTC)
    previous_end, previous_receipt, duration = None, None, None
    ids = []
    for wave in schedule:
        _exact_fields(wave, "wave_id start end as_of", "wave")
        ids.append(wave["wave_id"])
        start, end = (parse_time(wave[k], dataset.clock) for k in ("start", "end"))
        receipt = parse_time(wave["as_of"], UTC)
        if end <= start or (previous_end is not None and start < previous_end):
            raise ValueError("panel requires ordered nonoverlapping positive windows")
        if duration is not None and end - start != duration:
            raise ValueError("panel requires equal-duration windows")
        if receipt < registration or (previous_receipt is not None and receipt <= previous_receipt):
            raise ValueError("wave availability must follow registration and strictly increase")
        if dataset.clock["kind"] == "utc" and end > receipt:
            raise ValueError("UTC window must end no later than its availability")
        previous_end, previous_receipt, duration = end, receipt, end - start
    _ids(ids, "scheduled wave IDs")
    return deepcopy(schedule)


def _registration(dataset, store, journal_cutoff, observation_cutoff, registered_at):
    _check_availability(dataset, store, journal_cutoff, observation_cutoff, registered_at)
    records, journal_hash = _check_prefixes(dataset, store, journal_cutoff, observation_cutoff)
    prefix = store.to_dict()
    prefix["records"] = list(records)
    prefix.pop("store_hash")
    return {"registered_at": registered_at, "journal_cutoff": journal_cutoff,
        "observation_cutoff": observation_cutoff, "journal_prefix_hash": journal_hash,
        "observation_prefix_hash": _digest(prefix)}


def _make_plan(dataset, store, *, registered_at, journal_cutoff, observation_cutoff, schedule, settings):
    binding = _dataset_binding(dataset)
    settings = _settings(settings)
    schedule = _schedule(dataset, schedule, registered_at)
    registration = _registration(dataset, store, journal_cutoff, observation_cutoff, registered_at)
    _cohort(dataset, journal_cutoff, settings["actors"])
    plan = {"schema": PLAN_SCHEMA, "profile": "SYNTHETIC_RESEARCH_ONLY",
        "dataset": binding, "registration": registration, "schedule": schedule,
        "settings": settings, "qualification_status": "NOT_ESTABLISHED",
        "registration_authority": "CALLER_DECLARED_NOT_EXTERNALLY_ATTESTED"}
    plan["plan_hash"] = _digest(plan)
    return plan


def freeze_semantic_panel(dataset, store, *, registered_at, schedule, settings):
    """Freeze a schedule against the exact supplied registration prefixes."""
    return _make_plan(dataset, store, registered_at=registered_at,
        journal_cutoff=len(dataset.records), observation_cutoff=len(store.records),
        schedule=schedule, settings=settings)


def _verify_plan(dataset, store, plan):
    if type(plan) is not dict or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported panel plan")
    if plan.get("plan_hash") != _digest({k: v for k, v in plan.items() if k != "plan_hash"}):
        raise ValueError("panel plan digest mismatch")
    reg = plan["registration"]
    rebuilt = _make_plan(dataset, store, registered_at=reg["registered_at"],
        journal_cutoff=reg["journal_cutoff"], observation_cutoff=reg["observation_cutoff"],
        schedule=plan["schedule"], settings=plan["settings"])
    if rebuilt != plan:
        raise ValueError("panel registration does not replay exactly")


def _within_budget(graph, settings):
    return len(graph) <= settings["max_nodes"] and graph.number_of_edges() <= settings["max_edges"]


def _degree_counts(graph, actors):
    return {a: {"in_neighbors": graph.in_degree(a), "out_neighbors": graph.out_degree(a),
        "in_expression_count": graph.in_degree(a, weight="strength"),
        "out_expression_count": graph.out_degree(a, weight="strength"),
        "unweighted_betweenness": None} for a in actors}


def _features(frame, settings):
    actors = settings["actors"]
    rows = {a: {"actor_id": a, "expression_actions": {}} for a in actors}
    expression, attendance = {}, frame["participation"]
    for action in settings["actions"]:
        graph, selected, excluded = _expression_graph(frame, actors, action)
        topic = _topic_profile(frame, actors, action)
        if _within_budget(graph, settings):
            counts = _centrality(graph)
            communities = community_report(graph, algorithm="louvain", seed=settings["seed"],
                resolution=settings["resolution"], weight="strength")
            status = "OK"
        else:
            counts, communities = _degree_counts(graph, actors), None
            status = "NOT_RUN_STRUCTURE_BUDGET_EXCEEDED"
        expression[action] = {"structure_status": status, "communities": communities,
            "person_person_event_ids": selected, "outside_cohort_event_ids": excluded,
            "person_topic": topic, "coverage": "SELECTED_CANDIDATES_NOT_POPULATION_COMPLETE"}
        for actor in actors:
            rows[actor]["expression_actions"][action] = {
                "person_person": counts[actor], "person_topic": topic["person_counts"][actor]}

    native = set(attendance["persons"])
    complete = attendance["coverage"]["complete"]
    incidences = {a: [] for a in actors}
    for edge in attendance["edges"]:
        if edge["source"] in incidences:
            incidences[edge["source"]].append(edge)
    projected, centrality, communities = None, None, None
    if not complete:
        status = "NOT_RUN_INCOMPLETE_PARTICIPATION_COVERAGE"
    elif settings["affiliation_projection"] == "none":
        status = "NOT_RUN_PROJECTION_NOT_REQUESTED"
    else:
        graph = _project_graph(frame["affiliation"])
        if _within_budget(graph, settings):
            projected = graph
            centrality = nx.betweenness_centrality(graph, normalized=True, weight=None)
            communities = community_report(graph, algorithm="louvain", seed=settings["seed"],
                resolution=settings["resolution"], weight="strength")
            status = "OK"
        else:
            status = "NOT_RUN_STRUCTURE_BUDGET_EXCEEDED"
    for actor in actors:
        eligible = actor in native
        evidence = sorted({e for edge in incidences[actor] for e in edge["evidence"]})
        rows[actor]["attendance"] = {
            "scope": "OUTSIDE_NATIVE_ELIGIBLE_SCOPE" if not eligible else
                "COMPLETE_DECLARED_VIEW" if complete else "INCOMPLETE_DECLARED_COVERAGE",
            "selected_incidence_count": len(incidences[actor]) if eligible else None,
            "complete_view_incidence_count": len(incidences[actor]) if eligible and complete else None,
            "evidence": evidence,
            "coattendance_neighbors": projected.degree(actor) if projected is not None and actor in projected else None,
            "coattendance_weight": projected.degree(actor, weight="strength")
                if projected is not None and actor in projected else None,
            "coattendance_unweighted_betweenness": centrality[actor]
                if centrality is not None and actor in centrality else None}
    return {"rows": [rows[a] for a in actors], "expression": expression,
        "attendance": {"native_persons": sorted(native), "coverage": attendance["coverage"],
            "projection": settings["affiliation_projection"], "structure_status": status,
            "communities": communities}}


def _materialize(dataset, store, plan, receipts):
    _verify_plan(dataset, store, plan)
    if type(receipts) is not list or len(receipts) > len(plan["schedule"]):
        raise ValueError("invalid issued wave sequence")
    settings, reg = plan["settings"], plan["registration"]
    previous = (reg["journal_cutoff"], reg["observation_cutoff"])
    waves = []
    for slot, receipt in zip(plan["schedule"], receipts):
        _exact_fields(receipt, "wave_id journal_cutoff observation_cutoff activity_links", "wave receipt")
        k, s = receipt["journal_cutoff"], receipt["observation_cutoff"]
        if receipt["wave_id"] != slot["wave_id"]:
            raise ValueError("waves must be issued in frozen order without gaps")
        if type(k) is not int or type(s) is not int or k < previous[0] or s < previous[1]:
            raise ValueError("wave receipt prefixes must be nondecreasing")
        frame = build_multilayer_frame(dataset, store, journal_cutoff=k, observation_cutoff=s,
            as_of=slot["as_of"], start=slot["start"], end=slot["end"],
            population=settings["population"], roles=settings["roles"],
            activity_links=receipt["activity_links"], affiliation_projection=settings["affiliation_projection"],
            max_pairs=settings["max_pairs"])
        _cohort(dataset, k, settings["actors"])
        wave = {"wave_id": slot["wave_id"], "window": frame["window"], "as_of": slot["as_of"],
            "journal_cutoff": k, "observation_cutoff": s, "frame_hash": frame["frame_hash"],
            "journal_prefix_hash": frame["expression"]["journal_prefix_hash"],
            "observation_prefix_hash": frame["expression"]["observation_prefix_hash"],
            "activity_link_plan_hash": frame["activity_link_plan_hash"],
            "activity_context_links": frame["activity_context_links"],
            "withheld_activity_links": frame["withheld_activity_links"],
            "features": _features(frame, settings)}
        wave["wave_hash"] = _digest(wave)
        waves.append(wave)
        previous = (k, s)
    result = {"schema": PANEL_SCHEMA, "profile": "SYNTHETIC_RESEARCH_ONLY",
        "plan_hash": plan["plan_hash"], "receipts": deepcopy(receipts), "waves": waves,
        "pending_wave_ids": [w["wave_id"] for w in plan["schedule"][len(waves):]],
        "qualification_status": "NOT_ESTABLISHED", "external_availability_attested": False,
        "future_prediction": False, "causal_effect_identified": False}
    result["panel_hash"] = _digest(result)
    return result


def start_semantic_panel(dataset, store, plan):
    return _materialize(dataset, store, plan, [])


def verify_semantic_panel(dataset, store, plan, panel):
    """Rebuild saved waves at their original cutoffs, even on extended journals."""
    if type(panel) is not dict or panel.get("schema") != PANEL_SCHEMA:
        raise ValueError("unsupported semantic panel")
    if panel.get("panel_hash") != _digest({k: v for k, v in panel.items() if k != "panel_hash"}):
        raise ValueError("semantic panel digest mismatch")
    rebuilt = _materialize(dataset, store, plan, panel["receipts"])
    if rebuilt != panel:
        raise ValueError("semantic panel does not replay exactly")
    return rebuilt


def append_semantic_wave(dataset, store, plan, panel, *, wave_id, activity_links):
    """Append a wave using the entire supplied journal/store at its declared origin.

    Caller owns issuance and durable storage. An actual historical issuance is
    not proven by a supplied timestamp. Later receipts cannot revise an issued wave.
    """
    saved = verify_semantic_panel(dataset, store, plan, panel)
    if not saved["pending_wave_ids"] or wave_id != saved["pending_wave_ids"][0]:
        raise ValueError("next scheduled wave required")
    receipt = {"wave_id": wave_id, "journal_cutoff": len(dataset.records),
        "observation_cutoff": len(store.records), "activity_links": deepcopy(activity_links)}
    result = _materialize(dataset, store, plan, saved["receipts"] + [receipt])
    if result["waves"][:-1] != saved["waves"]:
        raise ValueError("issued wave revision is forbidden")
    return result
