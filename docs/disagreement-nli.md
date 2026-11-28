# R3f: Local multilingual NLI scoring

Refs #23, follows the frozen disagreement study in #36. This is a
candidate scoring provider, not a qualified classifier, span extractor,
automatic annotation source or network mutation.

## Provider

- Model: [MoritzLaurer/mDeBERTa-v3-base-mnli-xnli](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli/tree/704310ca0bb8eb15bca150fc1e11083cd423dd02).
- Immutable revision: 704310ca0bb8eb15bca150fc1e11083cd423dd02.
- Upstream model card declares MIT and reports multilingual XNLI results.
  Those results do not establish speaker-owned proposal opposition accuracy.
- CPU float32 model, fast tokenizer, eval and inference mode, safetensors
  only, offline local files only, remote code disabled, no alternate model.
- The three published large-file SHA-256 values are pinned in source.
  The four small configuration files' observed hashes and runtime package
  versions are recorded in the report; they are not independently pinned
  to upstream in this slice. Provision the snapshot from a trusted source.
  File hashing is reproducibility metadata, not runtime attestation.

## Prepare and score

Use the existing R3d context and R3e study plan. Before reference decisions
or model scoring, freeze the exact proposal descriptions by ID with
`freeze_nli_inputs(study_plan, proposal_texts)`. Descriptions must be
chosen from independent proposal evidence, not composed from the answer.
The digest checks identity, not the truth or temporal availability of the
descriptions. The caller supplies the entire declared description set.

Load `LocalNliProvider(absolute_model_directory)`, then call
`score_case(dataset, study_plan, input_plan, case_id,
original_bytes=..., proposal_texts=..., provider=..., mode=...)`.
The scorer reconstructs the R3e plan and R3d context at the same receipt
cutoff, checks the exact original bytes, and requires the frozen context
and proposal descriptions to match before model invocation.

The premise is a JSON sequence of preceding/target utterances with opaque
speaker/addressee aliases. In target_only mode only the target utterance
is shown; in with_context mode the preceding messages are included.
The target and its speaker alias remain identical between the two modes,
as does each proposal hypothesis. Each hypothesis asks whether the
target speaker personally and explicitly opposes that proposal. This
format is an experimental design, not a validated prompting method.
The model receives the original text through its native tokenizer;
ICU and ConvoKit remain independent candidate measurements.

Each proposal yields all three original NLI softmax scores. The tokenized
pair must fit 512 tokens; longer pairs return INPUT_TOO_LONG without
silent truncation or a model call. No threshold, argmax-to-social-label
mapping or automatic span generation is supplied. NLI contradiction
is not interpersonal conflict and softmax scores are not calibrated
social-action probabilities. A later development-only decision policy
and independent held-out study are necessary.

Reports contain private identifiers, input/context fingerprints, model
file hashes, runtime versions, pair fingerprints and scores, not raw
utterances or proposal descriptions. Keep them private. No network or
journal write.

## Explicit real-runtime experiment

In a trusted online environment, provision PyTorch, Transformers and
the fast tokenizer dependencies compatible with the checkout's Python
runtime. Runtime versions remain to be qualified for the real checkpoint.

Download only the seven files to a fresh trusted directory (no model
weights are committed):

```bash
export SOCIOLAB_NLI_MODEL_DIR="$(pwd)/nli-snapshot"
mkdir -p "$SOCIOLAB_NLI_MODEL_DIR"
base=https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli/resolve/704310ca0bb8eb15bca150fc1e11083cd423dd02
for file in config.json tokenizer_config.json special_tokens_map.json added_tokens.json tokenizer.json spm.model model.safetensors; do
  curl --fail --location "$base/$file" -o "$SOCIOLAB_NLI_MODEL_DIR/$file" || exit 1
done
PYTHONPATH=src python -m unittest discover -s tests/language_runtime -p test_disagreement_nli_pretrained.py -v
```

This explicit smoke runs four authored Chinese cases (two alternative
proposal contexts, attributed speech and negation), two modes and two
candidate proposals per case: 16 actual model pairs. It prints the private
reports only for these fictional fixtures. The test asserts structural
integrity, not assumed semantic correctness.

## Executed validation

On Linux x86-64, Python 3.13.5, PyTorch 2.10.0+cpu:

```bash
PYTHONPATH=src python -m unittest discover -s tests/language_runtime -p test_disagreement_nli.py -v
```

10/10 isolated tests passed. Five use real PyTorch arithmetic over
authored logits with mocked tokenizer/model boundaries. Five check
proposal and context-mode preparation, JSON delimiting, and local
snapshot hash/directory constraints. The pretrained smoke source
compiled successfully but was not executed. The three local source/test
Git blobs match the published files:

- bda6f3708e563c5228ea3a41792167617a6410c8 (provider)
- 7aecb7f1c4b5b003881a9afeb7f9e1253f6cdf22 (local tests)
- 5fb4e6de9e7888d5e16a6635a8e7c9753f0c8d08 (pretrained smoke)

The environment lacks Transformers and cached weights, and curl cannot
resolve huggingface.co. Real checkpoint initialization, inference,
journal integration, full regression and empirical qualification remain
unverified. No CI workflow or default dependency change.
