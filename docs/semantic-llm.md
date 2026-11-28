# R3l: LLM-first semantic measurement

Refs #23 and the explicit architecture decision to use a large language model for semantic interpretation. Stacked on #39 (`400bc5f3`, archived real predicate-frame evidence). The previous predicate/NLI screen experiment is not a required production stage.

## Architectural boundary

- Journal selects current exact records, past-only context and authorized bytes.
- ICU, ConvoKit, Stanza and NLI remain optional preliminary measurements and supporting evidence. Their output is not the final semantic decision and must not veto a model answer solely because a grammatical candidate is absent.
- A language model interprets the original dialogue and declared proposal identities in context. In the first bounded task it decides speaker-owned proposal disagreement. Later profiles can add multiple semantic actions, people, topics, modality, temporal reference and evidence from multiple messages.
- A deterministic verifier checks schema, known IDs, original evidence offsets, provenance and explicit uncertainty. Correct structure is not proof of correct interpretation.
- Independent human references and blinded evaluation precede automatic annotation. NetworkX consumes qualified observations, not model speculation about motives, intent or future behavior.

## First reproducible provider

Use the official [Qwen3-4B GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/a9a60d009fa7ff9606305047c2bf77ac25dbec49/Qwen3-4B-Q4_K_M.gguf), Q4_K_M, Apache-2.0 model card. The 2.5 GB file SHA-256 is 7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5. Use [llama.cpp b12635](https://github.com/ggml-org/llama.cpp/releases/tag/b12635) CPU archive with [published digest](https://github.com/ggml-org/llama.cpp/attestations/70877262), 2945ac207127915c459d650f3253e12ab0f20fde60cff38ed5bef0ffaaf6d961. Pin both artifacts and record the runtime version. This relatively small quantized model is an engineering reference, not a claim of sufficient semantic accuracy. Larger local or explicitly authorized remote providers can implement future versioned profiles; no cloud transport or remote data upload exists here.

The local provider accepts an explicit trusted model file and numeric loopback port only. CI verifies the archive and model, starts its own llama-server with 8192 context tokens and context shift disabled, uses its native chat template, disables thinking for the bounded structured extraction, and sends schema-constrained JSON requests. No proxy, redirect or alternative provider. The client checks the GGUF bytes and response alias; the running server's identity outside this controlled CI remains an operator declaration rather than attestation.

## API

```python
from sociolab.semantic_llm import (
    LocalLlamaSemanticProvider, freeze_llm_inputs, score_semantic_case,
)
frozen = freeze_llm_inputs(study_plan, proposal_descriptions)
provider = LocalLlamaSemanticProvider(port, absolute_model_file)
report = score_semantic_case(dataset, study_plan, frozen, case_id,
    original_bytes=authorized_bytes, proposal_texts=proposal_descriptions,
    provider=provider)
```

Reuse the existing R3e study plan and R3d context reconstruction at the exact receipt prefix. Freeze proposal-description hashes, prompt identity, provider profile and budgets. Submit only the selected original messages with opaque participant aliases and explicit candidate proposal aliases. No access to future records; proposals themselves require independent provenance. Reject an oversized input rather than truncating. Treat dialogue and proposal text as untrusted data, not instructions.

The model returns four string fields: state (DISAGREEMENT / NO_DISAGREEMENT / UNRESOLVED), holder (SPEAKER / OTHER / BOTH / NONE / UNRESOLVED), proposal (known alias or NONE) and evidence_quote (verbatim contiguous substring of the target). A positive must be speaker-owned and identify exactly one declared proposal. Multi-target or unresolved cases should abstain. The verifier derives original Unicode codepoint offsets from an exact unique substring, rejects fabricated/repeated evidence and unknown aliases; it does not guess corrected output. Preserve incomplete/invalid model results separately from valid abstention. Do not infer actual named third-party identities from the holder category. Do not write journal annotations or social edges.

The report contains a candidate decision compatible with the existing study evaluator, holder category, request/response hashes, model identity and context binding. Raw original utterances and model output text are not persisted by the adapter. All reports remain private.

## Native execution gate

Run nine new contract test methods and existing 12 journal/context plus 11 disagreement-study tests. A separate genuine-model smoke executes 12 authored Chinese cases, including the two context-dependent proposal contrasts, attribution, quotation, double negation, conditionality, wrong target, unresolved referent, and a lexical synonym. Report valid outputs, resolved coverage and exact state/proposal matches, retaining all invalid, uncertain and wrong cases. The reference expectations are authored diagnostics, not independent human labels. Require actual structured output from the real model, not a semantic accuracy threshold. Full corpus qualification, independent actor/topic reference binding, model comparison and graph integration remain open.

The scoped CI workflow obtains the original artifacts via curl and verifies their digests. No new default dependencies, installer/consumer tests or vendor files. Native model execution results are pending the exact-head workflow.
