"""Independent Chinese dependency evidence, not a stance-holder classifier."""
from hashlib import file_digest, sha1, sha256
from importlib.metadata import version
import json
import os
from pathlib import Path

from .annotation_text import verify_content_bytes

STANZA_VERSION = "1.10.1"
RESOURCES_VERSION = "1.10.0"
RESOURCES_COMMIT = "f06522caadca99c72200e20ee158fe5e63b75e97"
RESOURCES_BLOB = "0e8014221888c221b166b0b14e0301052cc2e353"
PACKAGES = {"tokenize": "gsdsimp", "pos": "gsdsimp_nocharlm",
            "lemma": "gsdsimp_nocharlm", "depparse": "gsdsimp_nocharlm"}
# The pinned official resources registry publishes MD5 for these five files.
MODEL_MD5 = {
    "tokenize/gsdsimp.pt": "48f993223d568afedc2893f7cd76719c",
    "pos/gsdsimp_nocharlm.pt": "ca35e2cf0410c75d15cb7c8429ffa7b4",
    "lemma/gsdsimp_nocharlm.pt": "43f3f3b26bbfd5322a09f18f1d748c9a",
    "depparse/gsdsimp_nocharlm.pt": "734c741755aad6cddee6683b22ce3621",
    "pretrain/fasttext157.pt": "bc4c8895d62eb3e9028d16dfc2491bc9",
}


def _hash(value):
    return "sha256:" + sha256(json.dumps(value, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _files(directory):
    root = Path(directory)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("explicit absolute trusted Stanza model directory required")
    resource = (root / "resources.json").read_bytes()
    if sha1(f"blob {len(resource)}\0".encode("ascii") + resource).hexdigest() != RESOURCES_BLOB:
        raise ValueError("unexpected Stanza resources blob")
    hashes = {"resources.json": sha256(resource).hexdigest()}
    for relative, md5 in MODEL_MD5.items():
        path = root / "zh-hans" / relative
        with path.open("rb") as source:
            if file_digest(source, "md5").hexdigest() != md5:
                raise ValueError("upstream model checksum mismatch: " + relative)
        with path.open("rb") as source:
            hashes["zh-hans/" + relative] = file_digest(source, "sha256").hexdigest()
    return hashes


def _coordinates(text, document):
    sentences = []
    previous = 0
    for sentence in document.sentences:
        rows = []
        for token in sentence.tokens:
            if len(token.words) != 1:
                raise ValueError("Chinese syntax profile requires one word per token")
            word = token.words[0]
            start, end = token.start_char, token.end_char
            if (type(start) is not int or type(end) is not int or
                    not previous <= start < end <= len(text) or
                    any(not char.isspace() for char in text[previous:start]) or
                    text[start:end] != token.text or word.text != token.text):
                raise ValueError("syntax token does not bind exact original text")
            if type(word.id) is not int or word.id != len(rows) + 1:
                raise ValueError("unexpected word index")
            if type(word.head) is not int or not isinstance(word.deprel, str) or not isinstance(word.upos, str):
                raise ValueError("invalid dependency output")
            rows.append({"id": word.id, "start": start, "end": end,
                         "head": word.head, "deprel": word.deprel, "upos": word.upos})
            previous = end
        if not rows or sum(row["head"] == 0 for row in rows) != 1:
            raise ValueError("expected one dependency root per sentence")
        for row in rows:
            head, visited = row["id"], set()
            while head:
                if head in visited or not 1 <= head <= len(rows):
                    raise ValueError("invalid dependency tree")
                visited.add(head)
                head = rows[head - 1]["head"]
        sentences.append(rows)
    if not sentences or any(not char.isspace() for char in text[previous:]):
        raise ValueError("syntax output omitted original text")
    return sentences


class LocalChineseSyntax:
    """Explicit offline Stanza GSDSimp CPU pipeline; no model fallback."""
    def __init__(self, directory):
        if os.environ.get("TORCH_FORCE_WEIGHTS_ONLY_LOAD") != "1":
            raise ValueError("require PyTorch weights-only loading in the native runtime")
        if version("stanza") != STANZA_VERSION:
            raise ValueError("unexpected Stanza runtime version")
        hashes = _files(directory)
        import stanza
        import torch
        self._torch = torch
        self._pipeline = stanza.Pipeline(lang="zh-hans", dir=str(directory),
            package=None, processors=PACKAGES, download_method=None, use_gpu=False)
        if _files(directory) != hashes:
            raise ValueError("model files changed during loading")
        self.identity = {"provider": "stanfordnlp/stanza", "version": STANZA_VERSION,
            "resources_version": RESOURCES_VERSION, "resources_commit": RESOURCES_COMMIT,
            "packages": dict(PACKAGES), "file_sha256": hashes, "torch": version("torch"),
            "device": "cpu", "load_policy": "weights_only"}

    def extract(self, content_record_id, content, original_bytes):
        """Caller selects current record; output contains only private coordinates."""
        text = verify_content_bytes(content, original_bytes)
        if content["language"] != "zh" or not text.strip() or len(original_bytes) > 4096:
            raise ValueError("bounded nonblank Chinese syntax input required")
        if type(content_record_id) is not str or not content_record_id.strip():
            raise ValueError("content record ID required")
        with self._torch.inference_mode():
            document = self._pipeline(text)
        result = {"schema": "sociolab.chinese-dependency-evidence.v1",
            "content_record_id": content_record_id, "content_revision": content["content_revision"],
            "content_hash": content["content_hash"], "interaction_record_id": content["interaction_record_id"],
            "provider": self.identity, "offset_unit": "unicode_codepoint",
            "sentences": _coordinates(text, document),
            "semantic_annotation_created": False, "qualification_status": "NOT_ESTABLISHED"}
        result["result_hash"] = _hash(result)
        return result
