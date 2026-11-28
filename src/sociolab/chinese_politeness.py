"""Bounded ConvoKit feature adapter, not a social-action classifier."""

from __future__ import annotations

from hashlib import sha1, sha256
from importlib import import_module, resources
import json

from .annotation_text import verify_content_bytes


UPSTREAM_COMMIT = "91a1df0143668d8e0017f932f97ac878e53b91fa"
_PREFIX = "politeness_collections/"
_ZH = _PREFIX + "politeness_cscw_zh/"
_BLOBS = {
    _PREFIX + "marker_utils.py": "59f9ec0d025773fa33accd74871bc1eb3b4019e6",
    _ZH + "strategy_extractor.py": "a1d3edfc6e3ece6691326823efd27998297c22f2",
    _ZH + "lexicons/ngram_markers.json": "ffc794b6f39ed597489f39d026fb23ce4d01681f",
    _ZH + "lexicons/starter_markers.json": "b418cbb0d7035437d4751ba4f6926774c9b151b8",
    _ZH + "lexicons/non_starter_markers.json": "e9340026d7719f0f0d2a8ff7e869f1f6eb7623dd",
}
_REGEX = frozenset({"please", "start_question", "can_you", "could_you"})


def _digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(data).hexdigest()


def _provider():
    root = resources.files("convokit")
    for path, expected in _BLOBS.items():
        data = root.joinpath(path).read_bytes()
        actual = sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()
        if actual != expected:
            raise ValueError(f"ConvoKit source blob mismatch: {path}")
    module = import_module("convokit.politeness_collections.politeness_cscw_zh.strategy_extractor")
    return module


def _tokens(text: str, sentences: list) -> list:
    """Only omit whitespace; preserve every other source codepoint in order."""
    if type(sentences) is not list or not sentences:
        raise ValueError("at least one segmented sentence is required")
    previous = 0
    parses = []
    for sentence in sentences:
        if type(sentence) is not list or not sentence:
            raise ValueError("each sentence requires at least one token")
        parsed = []
        for span in sentence:
            if type(span) is not dict or set(span) != {"start", "end"}:
                raise ValueError("token requires exact codepoint start/end")
            start, end = span["start"], span["end"]
            if (type(start) is not int or type(end) is not int
                    or not previous <= start < end <= len(text)):
                raise ValueError("invalid or unordered token span")
            if any(not char.isspace() for char in text[previous:start]):
                raise ValueError("segmentation omitted non-whitespace text")
            token = text[start:end]
            if any(char.isspace() for char in token):
                raise ValueError("token contains whitespace")
            # Match the upstream PolitenessStrategies preprocessing.
            parsed.append({"tok": token.lower()})
            previous = end
        parses.append(parsed)
    if any(not char.isspace() for char in text[previous:]):
        raise ValueError("segmentation omitted non-whitespace text")
    return parses


def extract_chinese_politeness(
    content_record_id: str, content: dict, data: bytes, sentences: list,
) -> dict:
    """Extract upstream features from exact bytes and caller-declared segmentation.

    Caller selects the current journal record and authorized bytes. No tokenizer,
    context retrieval, label inference, graph update or empirical qualification.
    The result is private; upstream token coordinates are not semantic evidence.
    """
    if type(content_record_id) is not str or not content_record_id or content_record_id.strip() != content_record_id:
        raise ValueError("content record ID must be nonempty trimmed text")
    text = verify_content_bytes(content, data)
    if content["language"] != "zh":
        raise ValueError("this profile requires declared language zh")
    parses = _tokens(text, sentences)
    module = _provider()
    features, markers = module.get_chinese_politeness_strategy_features(parses)
    if set(features) != set(module.STRATEGIES) or set(markers) != set(features) or len(features) != 26:
        raise ValueError("unexpected upstream feature set")

    def coordinate(entry) -> list[int]:
        token, sentence, index = entry
        if (type(sentence) is not int or type(index) is not int
                or not 0 <= sentence < len(parses)
                or not 0 <= index < len(parses[sentence])
                or token != parses[sentence][index]["tok"]):
            raise ValueError("upstream marker does not match supplied token")
        return [sentence, index]

    coordinates = {}
    for name in sorted(features):
        entries = markers[name]
        if type(features[name]) is not int or features[name] != int(bool(entries)):
            raise ValueError("unexpected upstream feature value")
        # Regex helpers flatten token triples; lexical helpers retain groups.
        # Do not invent regex-match boundaries or convert either to label spans.
        if name in _REGEX:
            coordinates[name] = {"layout": "flat_tokens", "entries": [coordinate(e) for e in entries]}
        else:
            coordinates[name] = {"layout": "token_groups", "entries": [[coordinate(e) for e in group] for group in entries]}
    result = {
        "schema": "sociolab.chinese-politeness-features.v1",
        "content_record_id": content_record_id,
        "content_revision": content["content_revision"],
        "content_hash": content["content_hash"],
        "interaction_record_id": content["interaction_record_id"],
        "provider": {"id": "convokit.politeness_cscw_zh", "commit": UPSTREAM_COMMIT,
                     "verified_source_blobs": dict(_BLOBS)},
        "segmentation": {"unit": "unicode_codepoint", "profile": "caller-supplied-v1",
                         "hash": _digest(sentences), "sentence_count": len(parses),
                         "token_count": sum(map(len, parses))},
        "features": features,
        "marker_token_coordinates": coordinates,
        "qualification_status": "NOT_ESTABLISHED",
        "semantic_annotation_created": False,
        "context_used": False,
    }
    result["content_hash_of_result"] = _digest(result)
    return result
