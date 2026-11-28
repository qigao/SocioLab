"""Private proposal-NLI scores; not a qualified social-action classifier."""
from hashlib import sha256
from importlib.metadata import version
import json
import math
from pathlib import Path

MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
REVISION = "704310ca0bb8eb15bca150fc1e11083cd423dd02"
LABELS = ("entailment", "neutral", "contradiction")
PINNED_SHA256 = {
    "model.safetensors": "65af59b1ff4450b09ecbf13ca35c840dbf038b26ff8e10e5ea89ca724828ed1e",
    "tokenizer.json": "3aca3ce69a0a35aeb144a52c4f1d41c4246b8785f8f398315cc8fb6b24057810",
    "spm.model": "13c8d666d62a7bc4ac8f040aab68e942c861f93303156cc28f5c7e885d86d6e3",
}
FILES = frozenset(PINNED_SHA256) | {"config.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json"}
PROFILE = "speaker-owned-proposal-opposition-nli.v1"
MAX_TOKENS = 512


def _digest(value):
    return "sha256:" + sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _text_hash(text):
    if type(text) is not str or not text.strip():
        raise ValueError("nonblank original proposal text required")
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()


def _check_digest(value, field):
    if type(value) is not dict or value.get(field) != _digest({k: v for k, v in value.items() if k != field}):
        raise ValueError("digest mismatch: " + field)


def freeze_nli_inputs(study_plan, proposal_texts):
    """Freeze caller-supplied proposal definitions before any scored evaluation."""
    _check_digest(study_plan, "plan_hash")
    if study_plan.get("schema") != "sociolab.disagreement-plan.v1":
        raise ValueError("disagreement study plan required")
    proposal_ids = {p["id"] for c in study_plan["cases"] for p in c["proposals"]}
    if type(proposal_texts) is not dict or set(proposal_texts) != proposal_ids:
        raise ValueError("exact frozen proposal set required")
    result = {"schema": "sociolab.disagreement-nli-inputs.v1", "profile": PROFILE,
        "study_plan_hash": study_plan["plan_hash"], "model_id": MODEL_ID, "model_revision": REVISION,
        "proposal_hashes": {p: _text_hash(text) for p, text in proposal_texts.items()},
        "max_tokens": MAX_TOKENS, "qualification_status": "NOT_ESTABLISHED"}
    result["input_plan_hash"] = _digest(result)
    return result


def _pairs(context, original_bytes, proposals, mode):
    """Inputs have already passed the real journal binding in score_case."""
    if mode not in ("target_only", "with_context"):
        raise ValueError("unknown context mode")
    entries = context["entries"]
    # Target-first aliases remain identical across both experimental modes.
    actors = {}
    for entry in [entries[-1], *entries[:-1]]:
        for key in ("actor", "addressee"):
            actors.setdefault(entry[key], "人物" + str(len(actors) + 1))
    if mode == "target_only":
        entries = entries[-1:]
    messages = []
    for entry in entries:
        speaker = actors[entry["actor"]]
        addressee = actors[entry["addressee"]]
        messages.append({"角色": "目标消息" if entry["role"] == "target" else "前文",
            "说话者": speaker, "听话者": addressee,
            "内容": original_bytes[entry["content_record_id"]].decode("utf-8", errors="strict")})
    premise = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    speaker = messages[-1]["说话者"]
    return [(pid, premise, f"目标消息中，{speaker}本人明确反对这个提案：{json.dumps(text, ensure_ascii=False)}。")
        for pid, text in proposals.items()]


def _snapshot_files(directory):
    path = Path(directory)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("explicit absolute trusted model directory required")
    if {p.name for p in path.iterdir()} != FILES:
        raise ValueError("model directory must contain exactly the seven required files")
    hashes = {}
    for name in sorted(FILES):
        with (path / name).open("rb") as source:
            from hashlib import file_digest
            hashes[name] = file_digest(source, "sha256").hexdigest()
        if name in PINNED_SHA256 and hashes[name] != PINNED_SHA256[name]:
            raise ValueError("upstream file hash mismatch: " + name)
    return hashes


def _infer_pair(torch, tokenizer, model, premise, hypothesis):
    # Never truncate away the actual target message or its negation.
    batch = tokenizer(premise, hypothesis, truncation=False, return_tensors="pt")
    count = int(batch["input_ids"].shape[-1])
    if count <= 0:
        raise ValueError("empty NLI input")
    if count > MAX_TOKENS:
        return {"status": "INPUT_TOO_LONG", "token_count": count, "scores": None}
    with torch.inference_mode():
        logits = model(**batch).logits
        if tuple(logits.shape) != (1, 3) or not torch.isfinite(logits).all().item():
            raise ValueError("invalid NLI logits")
        values = torch.softmax(logits[0].to(dtype=torch.float64), dim=-1).tolist()
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
        raise ValueError("invalid NLI scores")
    return {"status": "SCORED", "token_count": count, "scores": dict(zip(LABELS, values))}


class LocalNliProvider:
    """Explicit local CPU model; no downloads or fallback model."""
    def __init__(self, directory):
        hashes = _snapshot_files(directory)
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True,
            trust_remote_code=False, use_fast=True)
        self._model = AutoModelForSequenceClassification.from_pretrained(str(directory),
            local_files_only=True, trust_remote_code=False, use_safetensors=True,
            torch_dtype=torch.float32).to("cpu").eval()
        cfg = self._model.config
        if cfg.model_type != "deberta-v2" or cfg.id2label != dict(enumerate(LABELS)) or cfg.max_position_embeddings != MAX_TOKENS:
            raise ValueError("unexpected pinned model configuration")
        vocab = self._tokenizer.get_vocab()
        if (not self._tokenizer.is_fast or not vocab or min(vocab.values()) < 0
                or max(vocab.values()) >= self._model.get_input_embeddings().num_embeddings):
            raise ValueError("unexpected tokenizer configuration")
        if _snapshot_files(directory) != hashes:
            raise ValueError("snapshot changed during model loading")
        self.identity = {"model_id": MODEL_ID, "revision": REVISION, "file_sha256": hashes,
            "runtime": {name: version(name) for name in ("torch", "transformers", "tokenizers")},
            "device": "cpu", "dtype": "float32", "label_order": list(LABELS)}

    def score(self, premise, hypothesis):
        return _infer_pair(self._torch, self._tokenizer, self._model, premise, hypothesis)


def score_case(dataset, study_plan, input_plan, case_id, *, original_bytes, proposal_texts, provider, mode):
    """Rebind R3d context at its exact receipt prefix before any model call."""
    from .language_context import bind_language_context
    from .disagreement_study import freeze_disagreement_plan
    if study_plan != freeze_disagreement_plan(study_plan["cases"]):
        raise ValueError("invalid study plan")
    if input_plan != freeze_nli_inputs(study_plan, proposal_texts):
        raise ValueError("frozen NLI input plan mismatch")
    cases = [c for c in study_plan["cases"] if c["case_id"] == case_id]
    if len(cases) != 1:
        raise ValueError("case must exist exactly once")
    case = cases[0]
    expected = case["context"]
    ids = [e["content_record_id"] for e in expected["entries"]]
    conversation = {k: expected["conversation"][k] for k in ("id", "revision", "source_ref", "interaction_record_ids")}
    context = bind_language_context(dataset, knowledge_cutoff=expected["knowledge_cutoff"],
        target_record_id=ids[-1], preceding_record_ids=ids[:-1], conversation=conversation,
        original_bytes=original_bytes)
    if context != expected:
        raise ValueError("context differs from frozen study case")
    if not isinstance(provider, LocalNliProvider):
        raise ValueError("explicit local NLI provider required")
    proposals = {p["id"]: proposal_texts[p["id"]] for p in case["proposals"]}
    rows = []
    for pid, premise, hypothesis in _pairs(context, original_bytes, proposals, mode):
        rows.append({"proposal_id": pid, "pair_hash": _digest([premise, hypothesis]),
            **provider.score(premise, hypothesis)})
    result = {"schema": "sociolab.disagreement-nli-scores.v1", "case_id": case_id,
        "partition": case["partition"], "context_hash": context["context_hash"],
        "input_plan_hash": input_plan["input_plan_hash"], "mode": mode,
        "provider": provider.identity, "rows": rows, "qualification_status": "NOT_ESTABLISHED",
        "semantic_annotation_created": False, "evidence_spans_inferred": False}
    result["result_hash"] = _digest(result)
    return result
