# R3d: Private language context selection

Following #34 and tracking #23. This is input admission, not a semantic classifier or qualified same-conversation source.

## Contract

```python
from sociolab.language_context import bind_language_context

context = bind_language_context(
    dataset,
    knowledge_cutoff=K,
    target_record_id=target_content_id,
    preceding_record_ids=ordered_previous_content_ids,
    conversation={
        "id": conversation_id,
        "revision": membership_revision,
        "source_ref": membership_evidence_reference,
        "interaction_record_ids": ordered_previous_interaction_ids + [target_interaction_id],
    },
    original_bytes=authorized_bytes_by_content_id,
)
```

The public entry point uses the existing annotation_report and exact EventDataset receipt prefix. Every selected content must be CURRENT with one effective parent and no competing content. Reuse exact byte verification before retaining any metadata. Only selected byte keys are allowed. Target language must be declared zh; preceding languages are retained, not inferred. Nonblank text only; at most eight preceding utterances and a combined 1 MiB of UTF-8 bytes, chosen as an initial bounded engineering profile rather than a scientifically selected context window.

Order is strictly increasing by the existing source-clock parser, target last. Equal source times are unresolved, not broken by receipt order. The caller explicitly supplies the exact ordered interaction membership list; it must match selected content parents. The current journal schema does not authenticate conversation identity, source membership, source chronology or availability of the external membership declaration at K. Do not infer conversation from actor, addressee, topic or temporal proximity. The declaration is private and marked CALLER_DECLARED_NOT_AUTHENTICATED. Selection completeness is NOT_ESTABLISHED; no missing message is a negative. A retrospective cutoff may include corrected historical content, and is not equivalent to knowledge at the time the target was uttered.

Result binds the existing prefix fingerprints, exact content IDs/revisions/hashes, source times, actor, addressee, interaction topic and explicit declaration by canonical context digest. It includes neither text nor content_ref; conversation source_ref and identifiers/digests still require private handling. No automatic retrieval or journal mutation, no labels or graph changes, no provider execution in this slice. Downstream provider invocation must rebind its exact inputs to this contract; a saved hash alone does not establish validity.

## Next measurement gate (proposal)

Freeze an utterance-level explicit topic-directed disagreement task, separately from interpersonal attack. Distinguish the speaker's own rejection, attributed speech, double negation, unclear referent, and insufficient context; abstention is not neutral. A proposal identity must be resolved independently; a topic on the interaction is not proof that it is the semantic target.

An authored illustration: a preceding message introduces proposal A; the target says 我不同意这个方案。 The context artifact binds both utterances without assigning disagreement or assuming that the addressee is the subject. Compare target-only and explicitly selected context on the same frozen references. Use lexical/abstain baselines and a pinned independently assessed semantic model, keeping ConvoKit features separate. Evaluate reference coverage, abstention, label/subject/topic joint accuracy and evidence spans; split by conversation and proposal group (including related duplicates) before training or selection. No empirical dataset, human references, model execution or qualification yet.

## Executed validation

Python 3.13.5 local isolated source slice. All **10 SelectionTests** pass, no failures/errors/skips in that selected class. The report and time parser inputs are authored fixtures; the original annotation_schema.py and annotation_text.py are byte-identical to the parent blobs 354d87ce525193e9e328332a668e237d6ece4551 and 9ce37226368d7a0a773bdab0f03667b9ea1dea55. The new module and tests have exact verified Git blobs 0e7d179bdca8f46507e74ae091c0005595a6e886 and 552e234418653351f073b0dcee76acb1d12f8cf2. Tests include future and tied source times, declaration mismatch, missing/extra bytes, tampering on each message, limits, no text output, deterministic identity and unmodified inputs.

Two JournalIntegrationTests are authored to run against the real EventDataset and annotation_report, covering receipt-prefix replay, same-byte revision and ambiguous content. **Not executed here**: full checkout and source materialization were unavailable (DNS/raw source retrieval failure). No full suite or integration pass claimed. Execute in a full checkout:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_language_context.py -v
```

No dependency, CI workflow, installer/consumer tests, schema or existing provider changes. Keep D4b and #23 open.
