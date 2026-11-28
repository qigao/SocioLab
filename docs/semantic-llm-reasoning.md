# R3n: Controlled LLM reasoning contrast

Refs #23. Preceding [8B CI #1](https://github.com/qigao/SocioLab/actions/runs/46150535594) succeeded on `3e795858`: 35 test methods and 12 actual Qwen3-8B completions. Compared with the archived 4B run, valid outputs decreased 12→10, state/proposal matches increased 5→6, and state/proposal/holder matches increased 4→5. Conditionality improved, while reported speech, quotation, target and ambiguity errors remained. The two invalid 8B outputs remain distinct from negative or unresolved decisions. Original complete results are preserved in `docs/experiments/2026-11-28-llm/native-run-1-qwen3-8b.json`.

## Experiment

Keep the official Qwen3-8B Q4_K_M file, llama.cpp b12635, original task prompt, exact 12 authored messages, proposal aliases, temperature, seed and JSON output contract. Do not edit the original observations or select a semantic threshold. Run two fresh CPU server processes, sequentially in one native workflow:

| Setting | Control | Treatment |
| --- | --- | --- |
| Server reasoning | off | on |
| Request enable_thinking | false | true |
| Reasoning response format | deepseek | deepseek |
| Server reasoning budget | 1024 | 1024 |
| Total requested completion tokens | 1536 | 1536 |
| Context window | 8192 | 8192 |

A larger completion budget and explicit server configuration distinguish both new modes from the historical default-server/384-token profile. The new off/on pair is the controlled comparison; do not attribute a difference from the archived 8B result solely to reasoning. Server reasoning budget is a declared runtime configuration, not a guarantee of exactly 1024 generated tokens. Record numeric usage only when provided.

The client checks original case, plan and request fingerprints; only reasoning settings and the completion budget may differ from archived requests. Explicit modes have distinct immutable input-plan identities. The server flag and request setting are both provided, but actual reasoning extraction must be observed: at least one response with nonempty reasoning_content in on mode, none in off mode. If this gate fails, do not claim a real reasoning comparison. Preserve truncated, invalid, abstaining and wrong cases. No automatic retry, repair, fallback or qualification.

## API

```python
provider = LocalLlamaSemanticProvider(port, absolute_model_file,
    model_key="qwen3-8b", reasoning_mode="on")
frozen = freeze_llm_inputs(study_plan, proposal_descriptions,
    model_key="qwen3-8b", reasoning_mode="on")
report = score_semantic_case(dataset, study_plan, frozen, case_id,
    original_bytes=authorized_bytes, proposal_texts=proposal_descriptions,
    provider=provider)
```

Explicit profiles are off and on. The legacy default retains the previous input-plan and request identities. Provider/plan and request-mode mismatches fail before the network request. The provider accepts only the configured local loopback model and never persists raw completion or reasoning text. It retains final decision evidence and hashes, a reasoning-present boolean, final-content-present boolean and optional nonnegative integer token usage. The CI server logs are kept outside the retained artifact; only fictional candidate reports and non-text telemetry are published in CI logs.

Five additional contract test methods verify mode separation, exact settings, mismatch rejection, incomplete completion handling and telemetry minimization. The workflow executes the original context/study regressions and 12 actual cases per mode. Actual paired execution and results remain pending. These are exploratory authored diagnostics, not a held-out corpus. No new default dependencies, installer/consumer tests, semantic qualification, or journal/graph writes.
