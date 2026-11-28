"""Experimental predicate-level NLI evidence; no social-action decision."""
from .annotation_text import verify_content_bytes
from .chinese_predicate_frames import collect_predicate_frames
from .disagreement_nli import LocalNliProvider, _digest

PROFILE = "predicate-opposition-screen.v1"
HYPOTHESIS = "反对。"
LOCAL_MODIFIERS = frozenset({"advmod", "neg", "aux"})


def _probe_specs(text, frames):
    """Use exact contiguous predicate+local-modifier substrings.

    These fragments may omit arguments, ancestor negation and speech scope.
    They are lexical semantic probes, never asserted clauses or topic evidence.
    """
    specs = []
    for index, frame in enumerate(frames):
        predicate = frame["predicate"]
        modifiers = [m for m in frame["modifiers"]
            if m["deprel"].split(":", 1)[0] in LOCAL_MODIFIERS]
        spans = [predicate, *modifiers]
        start = min(s["start"] for s in spans)
        end = max(s["end"] for s in spans)
        specs.append({"frame_index": index, "predicate": predicate,
            "probe_span": {"start": start, "end": end},
            "premise": text[start:end], "hypothesis": HYPOTHESIS,
            "holder_candidate": frame["holder_candidate"],
            "scope": "LOCAL_FRAGMENT_NOT_ASSERTION"})
    return specs


def native_entailment(row):
    if row["status"] != "SCORED":
        return False
    s = row["scores"]
    return s["entailment"] > max(s["neutral"], s["contradiction"])


def screen_global_candidate(global_row, predicate_rows):
    """A post-result diagnostic intersection, not a negative-label policy.

    No threshold fitting, no multiplication of uncalibrated scores, no
    assertion of joint proposal resolution. Missing support is abstention.
    """
    supporting = [r["frame_index"] for r in predicate_rows
        if r["holder_candidate"]["role"] == "SOURCE_SPEAKER_CANDIDATE"
        and native_entailment(r)]
    return {"global_native_entailment": native_entailment(global_row),
        "supporting_frame_indices": supporting,
        "status": ("RETAINED_UNQUALIFIED_CANDIDATE" if
            native_entailment(global_row) and supporting else "UNRESOLVED"),
        "joint_topic_binding": "NOT_ESTABLISHED"}


def collect_predicate_nli(content_record_id, content, original_bytes, syntax_evidence, provider):
    """Rebind exact dependency frames before scoring every native VERB head."""
    if not isinstance(provider, LocalNliProvider):
        raise ValueError("explicit local NLI provider required")
    text = verify_content_bytes(content, original_bytes)
    frames = collect_predicate_frames(content_record_id, content, original_bytes, syntax_evidence)
    rows = []
    for spec in _probe_specs(text, frames["frames"]):
        premise, hypothesis = spec["premise"], spec["hypothesis"]
        rows.append({**{k: v for k, v in spec.items() if k not in ("premise", "hypothesis")},
            "pair_hash": _digest([premise, hypothesis]), **provider.score(premise, hypothesis)})
    result = {"schema": "sociolab.predicate-nli-evidence.v1", "profile": PROFILE,
        "content_record_id": content_record_id, "content_revision": content["content_revision"],
        "content_hash": content["content_hash"], "syntax_result_hash": syntax_evidence["result_hash"],
        "frame_result_hash": frames["result_hash"], "provider": provider.identity,
        "rows": rows, "semantic_annotation_created": False,
        "assertion_status": "NOT_ESTABLISHED", "qualification_status": "NOT_ESTABLISHED"}
    result["result_hash"] = _digest(result)
    return result
