# R3k: Dependency predicate frames and bounded quotation candidates

Refs #23. The preceding [R3j native run](https://github.com/qigao/SocioLab/actions/runs/46147196618) succeeded at `d0b1bf11`: four coordinate/tree boundary tests and one real-model smoke with 18 Chinese utterances. The original output objects are retained in `docs/experiments/2026-11-28-syntax/native-run-1.json` (archive-only parent commit `56e1779c`).

## Observed evidence and remaining failure

- Direct opposition gives a nominal subject of the attitude predicate. Different subjects in coordinated clauses are distinguishable.
- In the direct quote “小陈说：‘我反对这个提议。’”, the parse attaches 我 to 反对 as nsubj, and 反对 to 说 as ccomp. The final closing quote is a separate parser sentence. Quote scope therefore cannot be reconstructed by looking at just one sentence.
- In “我不同意这个方案”, 不 is advmod of 同意 and 我 is nsubj. In “我没有反对这个提议”, 反对 is xcomp under 没有 and has no direct subject. In the conditional example 如果 is case of 反对.
- The parser can split proper names into separate words and can attach indirect reported speech unexpectedly. These are syntactic observations, not reliable resolved entities or semantic labels.

## API

```python
from sociolab.chinese_predicate_frames import collect_predicate_frames

frames = collect_predicate_frames(content_record_id, content_payload,
                                  original_bytes, syntax_evidence)
```

The caller supplies authorized exact content and an actual selected parser result.
Reverify content bytes, revision, record binding, result digest, coordinate
coverage and tree shape. Hashes establish consistency, not the authenticity or
currency of a source. The caller still owns journal selection.

Collect every native VERB head, not a dictionary of attitude keywords.
Retain direct grammatical subjects, objects, clausal dependents, modifiers,
ancestors and their subjects/modifiers, using original codepoint coordinates.
This is a structural frame, not semantic role labeling.

Scan the entire original utterance for balanced curly/corner quote delimiters,
including across Stanza sentence boundaries. Straight quotes, mismatches and
unclosed quotes remain unresolved; no guessed quote scope. Nested quotes
are retained but do not resolve a first-person holder.

A narrow structural candidate profile distinguishes:
- SOURCE_SPEAKER_CANDIDATE: a unique direct nominal 我 subject outside quotes,
  in a root or parataxis chain.
- EXPLICIT_SUBJECT_HEAD: a unique direct proper-noun subject head outside quotes;
  not an independently identified person or a complete name span.
- QUOTE_GOVERNOR_SUBJECT_CANDIDATE: a single balanced quote containing a
  first-person direct subject of a ccomp predicate, with a unique nominal
  subject of its outside preceding governor. A governor is a structural
  candidate, not a verified speech act or quoted speaker.
- UNRESOLVED: every other case, including nested/unbalanced quotations,
  unresolved pronouns and missing/ambiguous direct subjects.

Each candidate is only a coordinate and reason, not an actor ID. Questions,
conditionality, polarity, embedded claims, proposal resolution and actual
speaker ownership remain unqualified. Every frame retains
`assertion_status=NOT_ESTABLISHED` and `semantic_topic=null`. No automatic
annotation or network edge is written; no utterance text is returned.

## Execution plan

The scoped native workflow runs the original syntax boundary tests, eight new
replay/quote test methods, the original real-parser smoke, and a new real-parser
smoke for six authored structural cases. The replay tests reuse all 18 archived
actual parse objects and check post-result structural expectations; they are
not independent reference labels. The six fresh cases exercise nested and
unclosed quotes, quote-following own clauses, double negation, different
targets and omitted subjects. These tests check structure and abstention
invariants, not classification accuracy. Runtime results remain pending until
the new exact-head CI completes.

No new default dependencies, changes to the Stanza or NLI algorithms, or
installer/consumer tests. Next: separately bind independently reviewed
predicate/argument spans and quotation ownership, evaluate joint holder,
polarity, modality and topic; only then consider semantic measurement.
