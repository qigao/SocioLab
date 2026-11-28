# R3j: Independent Chinese dependency evidence for attribution

Refs #23. Follows #37 R3i, which ran 96 real NLI attribution probes.
[CI #7](https://github.com/qigao/SocioLab/actions/runs/46146816510) passed 36 test methods. The named hypothesis with context produced 4 TP, 3 FP, 5 TN, 0 FN for the speaker, and 5 TP, 2 FP, 5 TN, 0 FN for the named third party. The explicit attribution hypothesis produced no true positives under native argmax. Neither is qualified. The complete result is retained in `docs/experiments/2026-11-28-nli/native-run-7-attribution.json`. The cases are authored diagnostic contrasts, not independent human annotations or an empirical accuracy estimate.

## Why syntax first

A source speaker, grammatical subject of an attitude predicate, quoted speaker, and semantic topic are different roles. In “小陈说：‘我反对这个提议。’”, the journal identifies who transmitted the utterance; it does not determine who “我” denotes inside the quotation. Dependency edges are candidate evidence for clauses and predicate arguments, not a full quotation scope, semantic role, modality or coreference resolver.

Candidate screen:
- [LTP](https://github.com/HIT-SCIR/ltp) offers SRL and dependency analysis, but its stated licensing restricts commercial use. Do not add it as a default dependency.
- [Stanza](https://stanfordnlp.github.io/stanza/depparse.html) provides original Universal Dependencies parsing. The [zh-hans model card](https://huggingface.co/stanfordnlp/stanza-zh-hans) declares Apache-2.0. This is a research evaluation; review the actual release and underlying training-data terms before product distribution.

Use a bounded Stanza 1.10.1 CPU profile with `tokenize=gsdsimp`, `pos/lemma/depparse=gsdsimp_nocharlm`, and `pretrain/fasttext157`. The registry comes from [resources commit f06522c](https://github.com/stanfordnlp/stanza-resources/blob/f06522caadca99c72200e20ee158fe5e63b75e97/resources_1.10.0.json), Git blob 0e8014221888c221b166b0b14e0301052cc2e353. The five model MD5s are pinned from the official registry. Record SHA-256 of the actual loaded files; MD5 and Git blob identity are reproducibility checks, not security attestation. Use only trusted official model files and an isolated native runtime with PyTorch weights-only loading enforced; no insecure checkpoint fallback.

## API and boundaries

```python
from sociolab.chinese_syntax import LocalChineseSyntax
provider = LocalChineseSyntax(absolute_trusted_model_directory)
evidence = provider.extract(content_record_id, content_payload, original_bytes)
```

The caller selects current journal content. Verify the original bytes, language and lengths before parsing. Limit this initial profile to nonblank Chinese input, at most 4096 UTF-8 bytes. Stanza uses its own native tokenization and parsing; ICU/ConvoKit outputs remain unchanged. Record exact original codepoint spans, UPOS tags, dependency relation names, sentence-local 1-based word IDs and heads (0 means root). Require one word per token in this Chinese profile, exact coverage except whitespace, and a valid single-root dependency tree. Fail instead of guessing offsets, replacing missing text or inventing relationships.

The output is private, contains no utterance text, and is not a semantic annotation. The model has not been qualified for quote scope, SRL, omitted subjects, negation, stance, or person/topic resolution.

## Native execution gate

Run the independent workflow on Linux x64 / Python 3.12 / PyTorch CPU 2.8.0. Four boundary test methods cover source offsets, omission/mismatch, invalid tree and multiple roots. A real-checkpoint test reuses exact journal/context binding and parses 18 fictional utterances, including all 12 previous attribution cases, nested/reported speech, negation, quoted questions and explicit disagreement. The retained log includes readable words only for invented cases, alongside exact evidence reports and model fingerprints. No automatic model-accuracy assertions or social labels; inspect actual syntax before deciding whether a separate SRL/quotation resolver is necessary.

No default dependency or NLI template changes; no installation/consumer tests. CI is required to establish actual runtime support. Full independent annotated source, semantic evaluation and R3 qualification remain open.
