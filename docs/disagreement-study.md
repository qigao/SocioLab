# R3e: Explicit proposal-disagreement study protocol

This slice evaluates supplied decisions. It is not a Chinese disagreement
classifier, and it creates neither semantic annotations nor network edges.
ConvoKit and ICU features remain unchanged.

## Freeze before labeling

Use the private `bind_language_context` entry point from R3d to obtain each
context, then declare a case ID, partition (development or test), and candidate
proposals as `{"id": "...", "family": "..."}` before the reference or candidate
decisions are seen. The proposal identity is distinct from the interaction's
topic field. Assign shared conversations and proposal families to the same
partition. Include plausible alternative proposal IDs where applicable.

`freeze_disagreement_plan(cases)` binds the ordered case list and each context
digest. It rejects known cross-partition overlap of conversation IDs,
proposal IDs/families, content hashes (including preceding messages), and
dataset-scoped interaction/content IDs. Both partitions must be present.
The protocol checks declared groups and exact identity only; near-duplicate
detection, actual conversation membership, and semantic proposal-family
assignment require independent verification. A digest is not authentication,
and no historical proof of pre-label freezing is implied.

## Reference and candidate decisions

Each case has exactly one of three task decisions:

- DISAGREEMENT: speaker explicitly opposes a declared proposal; give its ID
  and nonempty evidence in the target utterance.
- NO_DISAGREEMENT: no explicit speaker-owned opposition in scope; no
  proposal ID.
- UNRESOLVED: insufficient context, ambiguous referent or other uncertainty;
  no proposal ID.

A quoted disagreement is not necessarily the speaker's own opposition.
Opposing a separate implementation detail is not automatically opposing the
whole proposal. This version admits at most one opposed proposal per decision;
multi-target cases require another protocol or abstention. Evidence consists
of ordered, nonoverlapping half-open Unicode codepoint spans in the original
target, not ICU token indices. Valid spans alone do not establish the
semantic truth of a decision.

Provide two independently produced human review sets as
`{"id": "...", "plan_hash": "...", "decisions": {...}}`. Provide a separate
candidate as `{"method": {"kind": "...", "id": "...", "version": "..."},
"plan_hash": "...", "decisions": {...}}`. Map case IDs to decisions with
fields state, proposal_id, evidence. The evaluator checks distinct declared
reviewer IDs and the plan identity; actual independence and execution of the
declared candidate must be established outside the evaluator.

## Evaluation

Call `evaluate_disagreement(plan, target_inputs=..., reviewers=...,
candidate=...)`. The target inputs for exactly the test cases must contain
content_record_id, payload and original bytes (data). The evaluator reuses
R3a content verification and checks the record ID and content revision
against the frozen context. Preceding bytes and context membership are
verified at the private R3d binding boundary, not re-retrieved here.

Only unanimous, non-UNRESOLVED reference decisions form the eligible
reference set; missing and conflicting reviews remain visible. Missing or
unresolved candidates are not negative predictions. Report reference and
candidate coverage, label-only and joint label/proposal accuracy among
matched decisions, joint correctness over all eligible references,
joint positive recall over eligible reference positives, and joint positive
precision over eligible predicted positives. Report exact evidence agreement
separately; no denominator means null rather than zero or perfect accuracy.
Candidate and reviewer identities are bound to their decision-set hashes.
Keep all study inputs, reports, and proposal identifiers private.

## Executed evidence and limits

Python 3.13.5: 11 new DisagreementStudyTests and 10 R3d SelectionTests
passed in an isolated source slice (21 total). The contexts and reviewer
decisions are fictional fixtures, not human-labeled corpus results; the
all-abstain comparator tests scoring only. Real journal integration,
full checkout regression, an independently curated Chinese corpus, a
pinned semantic classifier and a blinded held-out run remain outstanding.
The previous two real journal tests were not executed because of DNS/source
retrieval limitations. No dependencies, CI workflows or installer/consumer
tests added. Qualification remains NOT_ESTABLISHED.
