"""Conservative human-reference admission audit, not a graph writer."""
from .annotation_schema import validate_method
from .language_context import bind_language_context
from .semantic_llm import _digest, _json, _model_profile
from . import semantic_actions as sa


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError("unexpected admission record fields")


def _checked_digest(value, field):
    if type(value) is not dict or value.get(field) != _digest({k: v for k, v in value.items() if k != field}):
        raise ValueError("digest mismatch: " + field)


def freeze_review_input(context, people, topics):
    """Model-independent identity for full-utterance reference decisions."""
    pa, ta, ma = sa._bindings(context, people, topics)
    result = {"schema": "sociolab.semantic-action-review-input.v1",
        "profile": sa.PROFILE, "context_hash": context["context_hash"],
        "people_hashes": {k: _digest(v) for k, v in people.items()},
        "topic_hashes": {k: _digest(v) for k, v in topics.items()},
        "schema_hash": _digest(sa._schema(pa, ta, ma))}
    result["review_input_hash"] = _digest(result)
    return result


def _rebind(dataset, context, original_bytes, cutoff):
    ids = [e["content_record_id"] for e in context["entries"]]
    return bind_language_context(dataset, knowledge_cutoff=cutoff, target_record_id=ids[-1],
        preceding_record_ids=ids[:-1], original_bytes=original_bytes,
        conversation={k: context["conversation"][k] for k in
            ("id", "revision", "source_ref", "interaction_record_ids")})


def _replay_candidate(candidate, binding):
    """Reconstruct exact quote inputs from stored normalized coordinates."""
    pa, ta, ma, texts, target, speaker = binding
    _fields(candidate, "status actions")
    if type(candidate["actions"]) is not list or len(candidate["actions"]) > sa.MAX_ACTIONS:
        raise ValueError("invalid saved action array")
    persons = {v: k for k, v in pa.items()}
    topics = {v: k for k, v in ta.items()}
    messages = {e["content_record_id"]: alias for alias, e in ma.items()}
    raw_actions = []
    for action in candidate["actions"]:
        _fields(action, "actor_id action subject topic_id topic_status attribution polarity modality evidence assertion_status")
        _fields(action["subject"], "kind id")
        subject = action["subject"]
        if subject["kind"] == "person":
            subject_alias = persons[subject["id"]]
        elif subject["kind"] == "topic":
            subject_alias = topics[subject["id"]]
        elif subject == {"kind": "unresolved", "id": None}:
            subject_alias = "UNKNOWN"
        else:
            raise ValueError("invalid saved subject")
        if action["topic_status"] == "resolved":
            topic_alias = topics[action["topic_id"]]
        elif action["topic_status"] in ("none", "unresolved") and action["topic_id"] is None:
            topic_alias = "NONE" if action["topic_status"] == "none" else "UNKNOWN"
        else:
            raise ValueError("invalid saved topic")
        evidence = []
        if type(action["evidence"]) is not list or not 1 <= len(action["evidence"]) <= sa.MAX_EVIDENCE:
            raise ValueError("invalid saved evidence array")
        for span in action["evidence"]:
            _fields(span, "content_record_id content_revision content_hash role unit start end")
            alias = messages[span["content_record_id"]]
            start, end = span["start"], span["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(texts[alias]):
                raise ValueError("invalid saved evidence offsets")
            evidence.append({"message": alias, "quote": texts[alias][start:end]})
        raw_actions.append({"actor": "UNKNOWN" if action["actor_id"] is None else persons[action["actor_id"]],
            "action": action["action"], "subject": subject_alias, "topic": topic_alias,
            "attribution": action["attribution"], "polarity": action["polarity"],
            "modality": action["modality"], "evidence": evidence})
    rebuilt = sa._validate_output(_json({"status": candidate["status"], "actions": raw_actions}), *binding)
    if rebuilt != candidate:
        raise ValueError("saved candidate does not replay exactly")
    return rebuilt


def _action_map(candidate):
    return {_digest(a): a for a in candidate["actions"]}


def _check_model(report, context, frozen, request, binding, model_key, reasoning_mode):
    _checked_digest(report, "result_hash")
    model_id, model_hash, alias = _model_profile(model_key)
    expected = {"schema": "sociolab.semantic-actions-result.v1", "profile": sa.PROFILE,
        "context_hash": context["context_hash"], "input_hash": frozen["input_hash"],
        "source_speaker_id": context["entries"][-1]["actor"],
        "target_content_record_id": context["entries"][-1]["content_record_id"],
        "request_hash": _digest(request), "semantic_annotation_created": False,
        "qualification_status": "NOT_ESTABLISHED"}
    if any(report.get(k) != v for k, v in expected.items()):
        raise ValueError("model report does not bind exact input")
    provider = report["provider"]
    if any(provider.get(k) != v for k, v in {"model_id": model_id, "model_sha256": model_hash,
            "model_alias": alias, "runtime": frozen["runtime"]}.items()):
        raise ValueError("model report provider mismatch")
    if provider.get("reasoning_mode", "legacy") != reasoning_mode:
        raise ValueError("model report reasoning mode mismatch")
    status, candidate = report["status"], report["candidate"]
    if status == "VALID_UNQUALIFIED_CANDIDATES" and report["finish_reason"] == "stop":
        try:
            return _replay_candidate(candidate, binding)
        except (KeyError, TypeError) as error:
            raise ValueError("invalid saved candidate binding") from error
    if candidate is None and ((status == "INVALID_MODEL_OUTPUT" and report["finish_reason"] == "stop")
            or (status == "INCOMPLETE_MODEL_OUTPUT" and report["finish_reason"] != "stop")):
        return None
    raise ValueError("inconsistent model result status")


def _eligibility(action, source_speaker):
    if action["attribution"] == "UNRESOLVED" or action["actor_id"] is None:
        return "UNRESOLVED_ATTRIBUTION"
    if action["attribution"] != "DIRECT":
        return "REVIEWED_REPORTED_OR_QUOTED_CLAIM"
    if action["actor_id"] != source_speaker:
        raise ValueError("direct candidate has wrong source speaker")
    if action["polarity"] != "AFFIRMED":
        return "REVIEWED_NEGATED_OR_UNRESOLVED_POLARITY"
    if action["modality"] != "ASSERTED":
        return "REVIEWED_NONASSERTED_OR_UNRESOLVED_MODALITY"
    if action["subject"]["kind"] == "unresolved" or action["topic_status"] == "unresolved":
        return "UNRESOLVED_SEMANTIC_TARGET"
    if action["subject"] == {"kind": "person", "id": source_speaker}:
        return "SELF_SUBJECT_NOT_INTERPERSONAL"
    return "REVIEWED_DIRECT_EXPRESSION_CANDIDATE"


def assess_semantic_admission(dataset, context, frozen, model_report, *, original_bytes,
        people, topics, model_key, reasoning_mode, admission_cutoff, reviews):
    """Compare two declared human full-utterance decisions, never mutate journal.

    Review independence, identities, catalog authenticity and observation
    completeness are external obligations. Exact agreement is a narrow
    review criterion, not scientific qualification or automatic admission.
    """
    if frozen != sa.freeze_actions_input(context, people, topics,
            model_key=model_key, reasoning_mode=reasoning_mode):
        raise ValueError("frozen action input mismatch")
    initial_cutoff = context["knowledge_cutoff"]
    if type(admission_cutoff) is not int or admission_cutoff < initial_cutoff:
        raise ValueError("admission cutoff must not precede the extraction cutoff")
    if _rebind(dataset, context, original_bytes, initial_cutoff) != context:
        raise ValueError("original extraction context mismatch")
    current = _rebind(dataset, context, original_bytes, admission_cutoff)
    if current["entries"] != context["entries"] or current["conversation"] != context["conversation"]:
        raise ValueError("stale selected context at admission cutoff")
    for cutoff in (initial_cutoff, admission_cutoff):
        entities, identities = dataset.entities_at(cutoff), dataset.identity_map_at(cutoff)
        if any(entities.get(p) != "person" or identities.get(p, p) != p for p in people):
            raise ValueError("person catalog requires known canonical persons")
    request, *binding = sa._request(context, original_bytes, people, topics,
        model_key=model_key, reasoning_mode=reasoning_mode)
    model = _check_model(model_report, context, frozen, request, binding, model_key, reasoning_mode)
    review_input = freeze_review_input(context, people, topics)
    if type(reviews) is not list or len(reviews) != 2:
        raise ValueError("two declared human review sets required")
    reference_sets, methods, review_hashes = [], [], []
    for review in reviews:
        _fields(review, "method review_input_hash admission_cutoff decision")
        method = validate_method(review["method"])
        if method["kind"] != "human":
            raise ValueError("human reference method required")
        if (review["review_input_hash"] != review_input["review_input_hash"] or
                type(review["admission_cutoff"]) is not int or review["admission_cutoff"] != admission_cutoff):
            raise ValueError("review input or cutoff mismatch")
        reference = sa._validate_output(_json(review["decision"]), *binding)
        methods.append(method)
        reference_sets.append(reference)
        review_hashes.append(_digest({"method": method, "review_input_hash": review_input["review_input_hash"],
            "admission_cutoff": admission_cutoff, "reference": reference}))
    if methods[0]["id"] == methods[1]["id"]:
        raise ValueError("distinct declared reviewer identities required")
    a, b = reference_sets
    a_map, b_map = _action_map(a), _action_map(b)
    consensus = ("REVIEW_UNRESOLVED" if "UNRESOLVED" in (a["status"], b["status"]) else
        "REFERENCE_DISAGREEMENT" if a["status"] != b["status"] or a_map != b_map else
        "EXACT_DECLARED_REFERENCE_AGREEMENT")
    model_map = {} if model is None else _action_map(model)
    agreed = a_map if consensus == "EXACT_DECLARED_REFERENCE_AGREEMENT" else {}
    rows, eligible = [], []
    for key, action in model_map.items():
        if consensus != "EXACT_DECLARED_REFERENCE_AGREEMENT":
            status = consensus
        elif key not in agreed:
            status = "NOT_IN_AGREED_REFERENCE"
        elif model["status"] != "CANDIDATES":
            status = "MODEL_UNRESOLVED"
        else:
            status = _eligibility(action, context["entries"][-1]["actor"])
        rows.append({"action_hash": key, "action": action, "disposition": status})
        if status == "REVIEWED_DIRECT_EXPRESSION_CANDIDATE":
            eligible.append(key)
    target = context["entries"][-1]
    result = {"schema": "sociolab.semantic-action-admission-audit.v1",
        "context_hash": context["context_hash"], "current_context_hash": current["context_hash"],
        "extraction_cutoff": initial_cutoff, "admission_cutoff": admission_cutoff,
        "target_content_record_id": target["content_record_id"],
        "interaction_record_id": target["interaction_record_id"], "source_speaker_id": target["actor"],
        "occurred_at": target["occurred_at"], "model_result_hash": model_report["result_hash"],
        "model_status": model_report["status"], "review_input_hash": review_input["review_input_hash"],
        "review_methods": methods, "review_hashes": review_hashes,
        "review_independence": "DECLARED_NOT_AUTHENTICATED", "reference_status": consensus,
        "reference_sets": reference_sets, "rows": rows,
        "agreed_reference_count": len(agreed) if consensus == "EXACT_DECLARED_REFERENCE_AGREEMENT" else None,
        "exact_matched_action_count": len(set(model_map) & set(agreed)) if consensus == "EXACT_DECLARED_REFERENCE_AGREEMENT" else None,
        "missing_agreed_reference_hashes": sorted(set(agreed) - set(model_map)),
        "reviewed_direct_expression_candidate_hashes": eligible,
        "observation_status": "NOT_ADMITTED", "qualification_status": "NOT_ESTABLISHED",
        "semantic_annotation_created": False, "network_mutated": False}
    result["result_hash"] = _digest(result)
    return result
