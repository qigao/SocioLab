# R3p: Semantic action admission audit

Refs #23. Both preceding exact-head native workflows passed:

- [#42 reasoning CI #1](https://github.com/qigao/SocioLab/actions/runs/46151031672): 41 test methods; 24 genuine Qwen3-8B completions. Off/on valid outputs 10/12 and 7/12, state/proposal matches 6/12 and 7/12, state/proposal/holder matches 5/12 and 6/12. Reasoning was actually observed in 12/12 on-mode responses and 0/12 off-mode responses. The on mode traded fewer erroneous positives for more invalid outputs. No default-mode qualification.
- [#43 multi-action CI #1](https://github.com/qigao/SocioLab/actions/runs/46151374920): 48 test methods, ten genuine completions, 8/10 valid outputs, six exact event-set matches, six of 12 authored reference actions matched, eight actions produced. The model incorrectly interpreted negated disagreement as affirmative support, and selected a different mediation target. Two multi-action cases had invalid output.

Original reports are preserved in `docs/experiments/2026-11-28-llm/native-run-1-reasoning.json` and `native-run-1-semantic-actions.json`. All expectations are authored diagnostics, not independent human labels.

## Boundary

An LLM output is a candidate, even if its schema and evidence spans are valid. This layer does not replace the LLM with lexical or syntactic inference. It checks a model-independent, separately supplied pair of full-utterance human-format reference decisions. Actual reviewer identity, authority, independence, semantic validity, catalog authenticity and observation completeness must be established by the caller. Two different method IDs and matching hashes are not authentication.

The new audit is deliberately separate from journal annotation v1 (which currently assumes one decision for each content/method/taxonomy). It does not extend that schema, create multiple conflicting v1 annotations, or write observed network edges.

## Interface

```python
from sociolab.semantic_admission import freeze_review_input, assess_semantic_admission

reference = freeze_review_input(context, people, topics)
# Obtain two separate full-utterance reference decisions outside the LLM.
# Each review has method={kind:"human", id:..., version:...},
# review_input_hash, admission_cutoff and decision.
audit = assess_semantic_admission(dataset, context, frozen, model_report,
    original_bytes=authorized_bytes, people=people, topics=topics,
    model_key="qwen3-8b", reasoning_mode="off",
    admission_cutoff=K, reviews=review_records)
```

The decisions use the existing multi-action schema and opaque aliases; they contain original evidence quotes when supplied, which are converted to exact original offsets. Freeze review identity independently of model, prompt and reasoning mode, but bind exact context and declared catalogs. References must be whole-utterance decisions rather than votes to approve a model prediction. The audit verifies the original extraction receipt prefix and the explicitly selected admission receipt prefix. Stale or ambiguous content, changed interaction binding or noncanonical person identity fails rather than moving old evidence to a new record. A later cutoff is not retrospective authorization for an earlier forecast.

Replay normalized saved model candidates through the existing strict alias and evidence validator; bind request/model/plan identity. Rehashed structurally inconsistent spans fail. Hash checks do not prove that the report originated from a real model. The two reviewer sets must agree exactly on the full candidate set, including evidence coordinates, ignoring action ordering. Unresolved reviews withhold every candidate. Evidence disagreement is deliberately not auto-adjudicated. Missing and extra candidates remain visible.

A model candidate exactly matching the agreed set can be retained as a **reviewed direct expression candidate** only if it is direct, affirmative, asserted, has a resolved subject/topic, and is not a person self-target. This is not a confirmed real-world behavior, a latent attitude or a verified relationship. A reviewed report/quotation remains a claim; a reviewed negation, condition, question or hypothetical remains separate from an affirmative assertion. Unresolved model output withholds even a matching partial candidate. Invalid/incomplete output is distinct from a reviewed no-action decision. All audit outputs explicitly remain NOT_ADMITTED / NOT_ESTABLISHED and no semantic annotation or graph mutation is performed.

## Validation

Nine authored boundary test methods and four replay methods use the actual #43 archived model reports. The replay fixtures independently specify the expected structures in code, but were authored after the experiment and are not actual independent human review. Check reported vs direct expression, the negation error, conditionality, missing predictions on invalid output, stale receipt binding, consensus, mismatched evidence and exact review identity. The scoped Linux CPU workflow runs these 13 new tests plus the existing 47 semantic/context/study contract methods. No model download or new inference is required for replay. CI pending at submission.

Next: obtain genuine independently reviewed corpus decisions and a versioned observation-layer policy. A separate multi-event journal/projection contract must preserve event identity, source time, review availability, corrections and distinct person/topic/activity roles. Only then evaluate descriptive temporal network changes and eventual future-behavior predictions. No production automatic admission or empirical accuracy claim.
