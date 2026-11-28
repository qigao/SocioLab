# R3o: Multi-action semantic extraction

Refs #23. Follows the LLM-first decision and #42 reasoning profile. The existing single-disagreement adapter and its historical reports remain unchanged. The preliminary ICU/ConvoKit/Stanza/NLI outputs are not decision gates.

## Candidate representation

A target utterance can express multiple actions by different attributed people and about different objects. This bounded profile extracts the six non-neutral, non-uncertain action labels already registered in sociolab.social-actions v1: disagreement, support, cooperation_commitment, mediation, insult and threat. It does not yet claim complete speech-act coverage.

Every candidate separates:

- Source speaker (from the selected journal interaction) from attributed actor (a known canonical person or unresolved).
- Action, subject (person/topic/unresolved), and associated topic (resolved/none/unresolved).
- Direct speech, report, quotation and unresolved attribution.
- Affirmed, negated or unresolved polarity, and asserted, conditional, question, hypothetical or unresolved modality.
- Original evidence spans, bound individually to message ID, content revision, SHA-256 and Unicode codepoint coordinates. At least one span must belong to the target; preceding messages may support reference resolution but do not create a new action on their own.

Quoted and reported claims do not prove that the attributed person actually performed the action. Negation and hypothetical or conditional expressions are not confirmed behavior. Even an affirmed direct assertion is still an unqualified model candidate. Every action has assertion_status NOT_ESTABLISHED.

## Interface

```python
from sociolab.semantic_actions import freeze_actions_input, extract_semantic_actions
from sociolab.semantic_llm import LocalLlamaSemanticProvider

provider = LocalLlamaSemanticProvider(port, absolute_model_file,
    model_key="qwen3-8b", reasoning_mode="off")
frozen = freeze_actions_input(context, people, topics,
    model_key="qwen3-8b", reasoning_mode="off")
report = extract_semantic_actions(dataset, context, frozen,
    original_bytes=authorized_bytes, people=people, topics=topics, provider=provider)
```

people maps canonical journal person IDs to explicitly declared descriptions. It must include all context participants, and every listed person must exist at the exact selected receipt cutoff. The catalog does not infer or create real-world identities. topics maps declared topic IDs to descriptions; these descriptions are not independently authenticated or proven to be available at the historical utterance time. Do not use later knowledge for prediction. The selected context is reconstructed and compared exactly before the request. Catalogs, model, prompt, schema, context and request identities are hashed. Opaque aliases are used for IDs; text and declared descriptions remain private and are sent only to the explicitly configured local model.

The output distinguishes valid candidates, no in-scope action, and unresolved interpretation. Invalid or incomplete model outputs remain separate transport/model statuses; neither is silently converted into a no-action result. An unresolved response may retain partial candidates. A valid empty response is a model decision, not proof of absence. The deterministic verifier checks exact fields, known aliases, direct attribution ownership, topic/subject consistency, duplicate candidates and nonoverlapping exact evidence within each action. It does not repair incorrect interpretations.

The profile limits catalogs to 16 people and 16 topics, eight actions and four evidence spans per action, and uses the existing bounded input and completion settings. These are initial engineering limits, not claims about natural dialogue. No raw model output or original text is stored by the adapter. No journal annotation, relationship edge, or network mutation is produced. A separate evaluation and admission contract must qualify candidates before they become observations.

## Native validation

Eight new contract methods cover multiple people/topics, quotation/report roles, evidence binding, modality/polarity, unresolved and empty outcomes, catalog identity, actual journal rebind and invalid/incomplete output handling. Mocked model boundaries are explicitly limited to the contract tests.

The scoped Linux CPU workflow runs the original semantic/context/study regression plus the new tests, then ten actual Qwen3-8B Q4_K_M completions with the pinned llama.cpp runtime and explicit nonthinking profile. The new authored cases exercise two topics, reported and quoted third-party claims alongside own statements, commitment, negation, conditionality, insult, mediation, threat and no-action text. Retain every structurally valid, invalid, incomplete, missing, extra and mismatched candidate. Compare unordered event multisets with authored expectations across actor/action/subject/topic/attribution/polarity/modality. Evidence structure is checked but evidence semantic accuracy is not independently measured. These diagnostic references are not a held-out corpus. No new default dependency, installer/consumer test, qualification threshold or automatic graph writes. Actual runtime results are pending the exact-head CI.

The reasoning-mode comparison in #42 is a separate experiment. This first multi-action smoke deliberately uses the explicit off configuration, not a claim that off is superior. Once both results are available, choose a versioned model/prompt/reasoning profile based on measured quality and coverage, then evaluate independent human annotations and a separate admission layer.
