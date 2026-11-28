"""Bounded structural predicate frames; not semantic role or stance labels."""
from .annotation_text import verify_content_bytes
from .chinese_syntax import _hash


OPEN_QUOTES = {"“": "”", "‘": "’", "「": "」", "『": "』"}
CLOSE_QUOTES = frozenset(OPEN_QUOTES.values())
MODIFIER_RELATIONS = frozenset({"advmod", "case", "mark", "aux", "discourse", "punct", "neg"})


def _quote_ranges(text):
    """Scan the whole utterance, independently of parser sentence boundaries."""
    stack, ranges = [], []
    for i, char in enumerate(text):
        if char in OPEN_QUOTES:
            stack.append((i, OPEN_QUOTES[char]))
        elif char in CLOSE_QUOTES:
            if not stack or stack[-1][1] != char:
                return {"status": "UNBALANCED", "ranges": []}
            start, _ = stack.pop()
            ranges.append({"start": start, "end": i + 1})
        elif char in ('"', "'"):
            # This bounded profile does not disambiguate straight quotes.
            return {"status": "UNSUPPORTED_DELIMITER", "ranges": []}
    if stack:
        return {"status": "UNBALANCED", "ranges": []}
    return {"status": "BALANCED", "ranges": sorted(ranges, key=lambda q: q["start"])}


def _base(relation):
    return relation.split(":", 1)[0]


def _validate_sentences(text, sentences):
    """Recheck replayed coordinate artifacts, without inventing token content."""
    if type(sentences) is not list or not sentences:
        raise ValueError("nonempty dependency sentences required")
    previous = 0
    for words in sentences:
        if type(words) is not list or not words:
            raise ValueError("nonempty dependency sentence required")
        for index, word in enumerate(words, 1):
            if type(word) is not dict or set(word) != {"id", "start", "end", "head", "deprel", "upos"}:
                raise ValueError("unexpected dependency coordinate fields")
            start, end, head = word["start"], word["end"], word["head"]
            if (type(word["id"]) is not int or word["id"] != index or
                    type(start) is not int or type(end) is not int or
                    not previous <= start < end <= len(text) or
                    any(not c.isspace() for c in text[previous:start]) or
                    type(head) is not int or not 0 <= head <= len(words) or
                    type(word["deprel"]) is not str or not word["deprel"] or
                    type(word["upos"]) is not str or not word["upos"]):
                raise ValueError("invalid dependency coordinates")
            previous = end
        if sum(w["head"] == 0 for w in words) != 1:
            raise ValueError("expected single dependency root")
        for word in words:
            seen, head = set(), word["id"]
            while head:
                if head in seen:
                    raise ValueError("dependency cycle")
                seen.add(head)
                head = words[head - 1]["head"]
    if any(not c.isspace() for c in text[previous:]):
        raise ValueError("dependency coordinates omitted original text")


def collect_predicate_frames(content_record_id, content, original_bytes, evidence):
    """Read exact syntax evidence and propose structural source-role candidates.

    The caller selects current content and a trusted parser result. Hash checks
    prove consistency, not source authenticity. Do not map grammatical subjects
    to semantic stance holders or infer an annotation from these candidates.
    """
    text = verify_content_bytes(content, original_bytes)
    if content["language"] != "zh" or not text.strip() or len(original_bytes) > 4096:
        raise ValueError("bounded nonblank Chinese syntax input required")
    if type(evidence) is not dict or evidence.get("schema") != "sociolab.chinese-dependency-evidence.v1":
        raise ValueError("Chinese dependency evidence required")
    if evidence.get("result_hash") != _hash({k: v for k, v in evidence.items() if k != "result_hash"}):
        raise ValueError("syntax evidence digest mismatch")
    if (evidence["content_record_id"] != content_record_id or
            any(evidence[k] != content[k] for k in
                ("content_revision", "content_hash", "interaction_record_id")) or
            evidence["offset_unit"] != "unicode_codepoint" or
            evidence["semantic_annotation_created"] is not False):
        raise ValueError("syntax evidence does not bind exact content")
    sentences = evidence["sentences"]
    _validate_sentences(text, sentences)
    quotes = _quote_ranges(text)
    frames = []

    def inside(word, quote):
        return quote["start"] < word["start"] and word["end"] < quote["end"]

    for sentence_index, words in enumerate(sentences):
        by_id = {w["id"]: w for w in words}
        children = {w["id"]: [] for w in words}
        for word in words:
            if word["head"]:
                children[word["head"]].append(word)

        def coordinate(word):
            return {"sentence": sentence_index, "word_id": word["id"],
                    "start": word["start"], "end": word["end"]}

        def linked(word, relations):
            return [w for w in children[word["id"]] if _base(w["deprel"]) in relations]

        def compact(word):
            return {**coordinate(word), "deprel": word["deprel"], "upos": word["upos"]}

        for word in words:
            # No list of attitude verbs; this profile collects all VERB heads.
            if word["upos"] != "VERB":
                continue
            subjects = linked(word, {"nsubj", "csubj"})
            ancestors = []
            head = word["head"]
            while head:
                ancestor = by_id[head]
                ancestors.append(ancestor)
                head = ancestor["head"]
            containing = [q for q in quotes["ranges"] if inside(word, q)]
            crossing = any(q["start"] < word["end"] and word["start"] < q["end"]
                           and not inside(word, q) for q in quotes["ranges"])
            holder = {"role": "UNRESOLVED", "coordinate": None, "reason": "no_unique_direct_nominal_subject"}
            if quotes["status"] != "BALANCED" or crossing:
                holder["reason"] = "quotation_scope_unresolved"
            elif len(subjects) == 1 and subjects[0]["deprel"] == "nsubj":
                subject = subjects[0]
                surface = text[subject["start"]:subject["end"]]
                if containing:
                    # Only one balanced direct quote and a ccomp governor
                    # outside the quote can supply a candidate attribution.
                    holder["reason"] = "embedded_or_nested_quotation_unresolved"
                    if len(containing) == 1 and inside(subject, containing[0]) and (
                            surface == "我" and _base(word["deprel"]) == "ccomp" and ancestors):
                        quote = containing[0]
                        governor = ancestors[0]
                        owners = linked(governor, {"nsubj", "csubj"})
                        if (governor["end"] <= quote["start"] and len(owners) == 1 and
                                owners[0]["deprel"] == "nsubj" and owners[0]["end"] <= quote["start"]):
                            holder = {"role": "QUOTE_GOVERNOR_SUBJECT_CANDIDATE",
                                "coordinate": coordinate(owners[0]),
                                "reason": "first_person_in_direct_ccomp_quote"}
                elif any(inside(subject, q) for q in quotes["ranges"]):
                    holder["reason"] = "subject_predicate_quote_scope_mismatch"
                elif surface == "我":
                    if not ancestors or all(_base(w["deprel"]) == "parataxis" for w in [word, *ancestors[:-1]]):
                        holder = {"role": "SOURCE_SPEAKER_CANDIDATE", "coordinate": coordinate(subject),
                                  "reason": "first_person_outside_quote_in_root_or_parataxis"}
                    else:
                        holder["reason"] = "embedded_first_person_unresolved"
                elif subject["upos"] == "PROPN":
                    holder = {"role": "EXPLICIT_SUBJECT_HEAD", "coordinate": coordinate(subject),
                              "reason": "proper_noun_grammatical_subject_only"}
                else:
                    holder["reason"] = "pronoun_or_other_subject_requires_resolution"
            frames.append({
                "predicate": compact(word),
                "direct_subjects": [compact(w) for w in subjects],
                "direct_objects": [compact(w) for w in linked(word, {"obj", "iobj"})],
                "clausal_dependents": [compact(w) for w in linked(word, {"ccomp", "xcomp", "advcl", "parataxis", "conj"})],
                "modifiers": [compact(w) for w in linked(word, MODIFIER_RELATIONS)],
                "ancestors": [{"head": compact(w),
                    "subjects": [compact(s) for s in linked(w, {"nsubj", "csubj"})],
                    "modifiers": [compact(s) for s in linked(w, MODIFIER_RELATIONS)]}
                    for w in ancestors],
                "quote_ranges": containing,
                "holder_candidate": holder,
                "assertion_status": "NOT_ESTABLISHED",
                "semantic_topic": None,
            })
    result = {"schema": "sociolab.chinese-predicate-frames.v1",
        "content_record_id": content_record_id, "content_revision": content["content_revision"],
        "content_hash": content["content_hash"], "interaction_record_id": content["interaction_record_id"],
        "syntax_result_hash": evidence["result_hash"], "offset_unit": "unicode_codepoint",
        "quotation_scan": quotes, "frames": frames,
        "semantic_annotation_created": False, "qualification_status": "NOT_ESTABLISHED"}
    result["result_hash"] = _hash(result)
    return result
