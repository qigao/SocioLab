# R3m: Controlled local LLM model comparison

Refs #23. The first LLM-first run (#40, HEAD c202c586, [CI #1](https://github.com/qigao/SocioLab/actions/runs/46149509495)) passed 33 test methods and executed 12 actual Qwen3-4B Q4_K_M completions. All 12 outputs were structurally valid and resolved, but only 5/12 matched the authored state/proposal reference. Seven cases were incorrectly made positive (third-party assertion, direct quotation, conditional, wrong target, unresolved referent, quotation followed by own support, nested quotation). The double-negation case matched state/proposal but attributed opposition to OTHER. Preserve the original complete report objects in `docs/experiments/2026-11-28-llm/native-run-1-qwen3-4b.json`.

## Change one experimental dimension

Allow explicit `qwen3-4b` and `qwen3-8b` model profiles with separate file hashes, server aliases and frozen input identities. The original 4B request, prompt, output contract, inference settings and input plan remain unchanged. Neither model is selected automatically. A mismatched plan, model hash or request alias fails; there is no fallback or cloud upload.

Use the official [Qwen3-8B Q4_K_M GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF/blob/6a569868d07d3bd59e8b97fb001bf8c0b254bb20/Qwen3-8B-Q4_K_M.gguf), 5,027,783,488 bytes, at commit 6a569868d07d3bd59e8b97fb001bf8c0b254bb20. SHA-256 d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785 is published in the upstream LFS pointer. Keep llama.cpp b12635, CPU, context size 8192, seed, temperature, nonthinking mode, 384 output-token limit, all 12 authored inputs and exact prompt. The different runner invocation and quantized checkpoints mean this is a descriptive comparison, not isolation of a theoretical parameter-count effect.

## API

```python
provider = LocalLlamaSemanticProvider(port, absolute_model_file, model_key="qwen3-8b")
frozen = freeze_llm_inputs(study_plan, proposal_descriptions, model_key="qwen3-8b")
report = score_semantic_case(dataset, study_plan, frozen, case_id,
    original_bytes=authorized_bytes, proposal_texts=proposal_descriptions, provider=provider)
```

The test reconstructs the earlier 4B plan/context/request, checks the archived per-case and summary hashes, then verifies that the only request change is the model alias. The baseline is not replaced or re-tuned. Compare exact state/proposal matches and list every improved/regressed case; report a newly authored holder reference for each case, separate holder matches, and the conjunction of state/proposal/holder. Holder references were added after seeing initial outputs, so these are post-result exploratory measurements only; they do not establish independent reference validity. A holder label is not a real-world belief, and valid evidence offsets do not prove semantic correctness.

The new native workflow runs the original contract/journal/study tests plus two new model-selection boundary tests, then executes the same 12 real cases against the official 8B snapshot. No default dependency or installer/consumer tests. No accuracy threshold or graph mutation. Actual 8B execution remains pending. A stronger model may help, but prompt design, thinking mode, model selection and independent blinded evaluation remain separate subsequent gates.
