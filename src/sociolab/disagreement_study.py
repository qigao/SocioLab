"""Private frozen-plan evaluation for explicit proposal disagreement, not classification."""
from copy import deepcopy
from hashlib import sha256
import json

from .annotation_schema import validate_method
from .annotation_text import verify_content_bytes


STATES = frozenset({"DISAGREEMENT", "NO_DISAGREEMENT", "UNRESOLVED"})


def _hash(value):
    return "sha256:" + sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _fields(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError("unexpected record fields")


def _id(value):
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("invalid identifier")
    value.encode("utf-8", errors="strict")


def freeze_disagreement_plan(cases):
    """Bind declared groups before labels; reject known cross-partition overlap.

    Contexts must be produced by bind_language_context in the private caller.
    Hash consistency does not authenticate their provenance or the declared groups.
    """
    if type(cases) is not list or not cases:
        raise ValueError("nonempty case list required")
    assigned, ids, families, partitions = {}, set(), {}, set()
    for case in cases:
        _fields(case, "case_id partition context proposals")
        cid, partition, context = case["case_id"], case["partition"], case["context"]
        _id(cid)
        if cid in ids or partition not in ("development", "test"):
            raise ValueError("duplicate case or invalid partition")
        ids.add(cid)
        partitions.add(partition)
        if type(context) is not dict or context.get("schema") != "sociolab.language-context.v1":
            raise ValueError("language context required")
        if context.get("context_hash") != _hash({k: v for k, v in context.items() if k != "context_hash"}):
            raise ValueError("context digest mismatch")
        if context["semantic_annotation_created"] is not False:
            raise ValueError("prelabel context required")
        entries = context["entries"]
        if not entries or [e["role"] for e in entries] != ["preceding"] * (len(entries)-1) + ["target"]:
            raise ValueError("invalid target/context order")
        if entries[-1]["language"] != "zh":
            raise ValueError("declared Chinese target required")
        groups = [("conversation", context["conversation"]["id"])]
        for entry in entries:
            groups.extend((("content-hash", entry["content_hash"]),
                ("content-record", context["dataset"]["dataset_id"], entry["content_record_id"]),
                ("interaction-record", context["dataset"]["dataset_id"], entry["interaction_record_id"])))
        proposals = case["proposals"]
        if type(proposals) is not list or not proposals:
            raise ValueError("declare candidate proposals independently of labels")
        seen = set()
        for proposal in proposals:
            _fields(proposal, "id family")
            pid, family = proposal["id"], proposal["family"]
            _id(pid)
            _id(family)
            if pid in seen or families.setdefault(pid, family) != family:
                raise ValueError("duplicate proposal or inconsistent family")
            seen.add(pid)
            groups.extend((("proposal", pid), ("proposal-family", family)))
        for group in groups:
            for part in group:
                _id(part)
            if assigned.setdefault(group, partition) != partition:
                raise ValueError("cross-partition group overlap: " + group[0])
    if partitions != {"development", "test"}:
        raise ValueError("both development and test partitions required")
    plan = {"schema": "sociolab.disagreement-plan.v1", "cases": deepcopy(cases),
        "qualification_status": "NOT_ESTABLISHED"}
    plan["plan_hash"] = _hash(plan)
    return plan


def _decision(decision, case, text):
    _fields(decision, "state proposal_id evidence")
    state, pid, spans = decision["state"], decision["proposal_id"], decision["evidence"]
    if type(state) is not str or state not in STATES or type(spans) is not list:
        raise ValueError("invalid task decision")
    if state == "DISAGREEMENT":
        if pid not in [p["id"] for p in case["proposals"]] or not spans:
            raise ValueError("positive decision requires declared proposal and evidence")
    elif pid is not None:
        raise ValueError("nonpositive decision must not assign a proposal")
    previous = 0
    for span in spans:
        _fields(span, "start end")
        start, end = span["start"], span["end"]
        if type(start) is not int or type(end) is not int or not previous <= start < end <= len(text):
            raise ValueError("invalid ordered nonoverlapping codepoint evidence")
        previous = end
    return state, pid


def evaluate_disagreement(plan, *, target_inputs, reviewers, candidate):
    """Test-only comparison with two declared reviewers; missing is not negative.

    Agreement on state/target defines an eligible reference; disagreement or
    unresolved judgments stay unscored. Evidence agreement is reported separately.
    No raw text, automatic annotations, graph updates or qualification.
    """
    if plan != freeze_disagreement_plan(plan["cases"]):
        raise ValueError("plan identity mismatch")
    test = {c["case_id"]: c for c in plan["cases"] if c["partition"] == "test"}
    if type(target_inputs) is not dict or set(target_inputs) != set(test):
        raise ValueError("exact test target inputs required")
    if type(reviewers) is not list or len(reviewers) != 2:
        raise ValueError("two reviewer sets required")
    for reviewer in reviewers:
        _fields(reviewer, "id plan_hash decisions")
        _id(reviewer["id"])
        if reviewer["plan_hash"] != plan["plan_hash"]:
            raise ValueError("reviewer plan identity mismatch")
    if reviewers[0]["id"] == reviewers[1]["id"]:
        raise ValueError("distinct declared reviewers required")
    _fields(candidate, "method plan_hash decisions")
    method = validate_method(candidate["method"])
    if candidate["plan_hash"] != plan["plan_hash"]:
        raise ValueError("candidate plan identity mismatch")
    maps = [r["decisions"] for r in reviewers] + [candidate["decisions"]]
    if any(type(m) is not dict or not set(m) <= set(test) for m in maps):
        raise ValueError("decisions may refer only to test cases")
    rows = []
    for cid, case in test.items():
        inp = target_inputs[cid]
        _fields(inp, "content_record_id payload data")
        entry = case["context"]["entries"][-1]
        if inp["content_record_id"] != entry["content_record_id"]:
            raise ValueError("target record does not bind frozen content")
        payload = inp["payload"]
        text = verify_content_bytes(payload, inp["data"])
        for field in ("interaction_record_id", "content_revision", "content_hash", "language", "length"):
            if payload[field] != entry[field]:
                raise ValueError("target does not bind frozen content")
        ds = [m.get(cid) for m in maps]
        keys = [_decision(d, case, text) if cid in m else None for m, d in zip(maps, ds)]
        a, b, p = keys
        eligible = a is not None and a == b and a[0] != "UNRESOLVED"
        matched = eligible and p is not None and p[0] != "UNRESOLVED"
        positive = eligible and a[0] == "DISAGREEMENT"
        rows.append({"case_id": cid, "reference_status": "AGREED" if eligible else
            "MISSING" if a is None or b is None else "UNRESOLVED" if a == b else "DISAGREED",
            "reference_state": a[0] if eligible else None, "reference_proposal_id": a[1] if eligible else None,
            "candidate_status": p[0] if p is not None else "MISSING",
            "candidate_proposal_id": p[1] if p is not None else None,
            "matched": bool(matched), "label_correct": bool(matched and a[0] == p[0]),
            "joint_correct": bool(matched and a == p),
            "reference_positive": bool(positive),
            "reviewer_exact_evidence_agreement": ds[0]["evidence"] == ds[1]["evidence"] if positive else None,
            "candidate_exact_evidence_both": ds[2]["evidence"] == ds[0]["evidence"] == ds[1]["evidence"] if positive and matched and a == p else None})
    n = sum(r["reference_status"] == "AGREED" for r in rows)
    matched = sum(r["matched"] for r in rows)
    correct = sum(r["joint_correct"] for r in rows)
    positives = sum(r["reference_positive"] for r in rows)
    tp = sum(r["reference_positive"] and r["joint_correct"] for r in rows)
    predicted = sum(r["matched"] and r["candidate_status"] == "DISAGREEMENT" for r in rows)
    def fraction(num, den):
        return {"numerator": num, "denominator": den, "value": num / den if den else None}
    return {"schema": "sociolab.disagreement-evaluation.v1", "plan_hash": plan["plan_hash"],
        "reviewer_ids": [r["id"] for r in reviewers], "reference_hashes": [_hash(r) for r in reviewers],
        "candidate_method": method, "candidate_hash": _hash(candidate),
        "rows": rows, "test_count": len(rows),
        "eligible_reference_count": n, "reference_coverage": fraction(n, len(rows)),
        "candidate_coverage": fraction(matched, n),
        "label_accuracy_matched": fraction(sum(r["label_correct"] for r in rows), matched),
        "joint_accuracy_matched": fraction(correct, matched),
        "joint_correct_over_reference": fraction(correct, n), "joint_positive_recall": fraction(tp, positives),
        "joint_positive_precision": fraction(tp, predicted), "qualification_status": "NOT_ESTABLISHED"}
