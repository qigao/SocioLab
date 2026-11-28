# R3b: Original ConvoKit Chinese politeness features

This is the first actual upstream language-feature execution for #23 / D4b, stacked on #32. It is **not** a qualified social-action classifier, learned model, motive measurement or future-conflict forecast.

## Provider scope

Use the original `get_chinese_politeness_strategy_features` from [ConvoKit v5.0.0, commit 91a1df0](https://github.com/CornellNLP/ConvoKit/tree/91a1df0143668d8e0017f932f97ac878e53b91fa/convokit/politeness_collections/politeness_cscw_zh), under its [MIT license](https://github.com/CornellNLP/ConvoKit/blob/91a1df0143668d8e0017f932f97ac878e53b91fa/LICENSE.md). This lexical/regex extractor produces 26 binary features. The full package has numerous additional dependencies and lists Python versions through 3.12 in its setup metadata; the complete distribution is not installed or qualified here. There is no change to the default dependency manifest. No upstream files are vendored. Use an explicitly provisioned trusted ConvoKit environment that exposes the pinned source resources; no alternate extractor or fallback.

Before extracting, the adapter checks these five exact source Git blob identities. These checks aid reproducibility, not runtime security or source authenticity attestation.

| Relative path in convokit | Git blob SHA |
| --- | --- |
| politeness_collections/marker_utils.py | 59f9ec0d025773fa33accd74871bc1eb3b4019e6 |
| politeness_collections/politeness_cscw_zh/strategy_extractor.py | a1d3edfc6e3ece6691326823efd27998297c22f2 |
| politeness_collections/politeness_cscw_zh/lexicons/ngram_markers.json | ffc794b6f39ed597489f39d026fb23ce4d01681f |
| politeness_collections/politeness_cscw_zh/lexicons/starter_markers.json | b418cbb0d7035437d4751ba4f6926774c9b151b8 |
| politeness_collections/politeness_cscw_zh/lexicons/non_starter_markers.json | e9340026d7719f0f0d2a8ff7e869f1f6eb7623dd |

## Input and private result

```python
from sociolab.chinese_politeness import extract_chinese_politeness

# For the fictional text 谢谢您。 the supplied segmentation is 谢谢 / 您 / 。
sentences = [[{"start": 0, "end": 2}, {"start": 2, "end": 3}, {"start": 3, "end": 4}]]
result = extract_chinese_politeness(content_record_id, content_payload, original_bytes, sentences)
```

Use the current exact journal record and authorized original bytes. Reuses #32 verification (content hash, strict UTF-8, both lengths); accepts declared language zh only. The caller supplies ordered sentence groups of nonempty half-open codepoint token spans. All non-whitespace source characters must be covered without overlap; whitespace cannot occur inside a token. Extract text directly from verified bytes; lowercase as the upstream high-level transformer does. No independent tokenizer, language detection, context selection, or source retrieval is included.

Retain the original private segmentation alongside the result. Its hash, original content ID/revision/hash, provider identity, 26 flags, token coordinates and canonical result digest bind the feature run. Lexical markers are nested token groups, but the four regex strategies flatten their token triples. The adapter preserves that shape and checks coordinates against the supplied token strings, without reconstructing nonexistent regex boundaries or assigning annotation evidence spans. Neither token groups nor positive flags are qualified semantic evidence. The result contains no utterance text or content_ref, but is private because record IDs/hashes/coordinates may identify the input. Do not publish real participant outputs.

## Actually executed fictional contrasts

| Text | Supplied tokenization | Selected observed result |
| --- | --- | --- |
| 谢谢您。 | 谢谢 / 您 / 。 | gratitude=1, you_honorific=1 |
| 谢谢您。 | 谢 / 谢 / 您 / 。 | gratitude=0, you_honorific=1; original content hash unchanged, segmentation hash changes |
| 我不保证。 | 我 / 不 / 保证 / 。 | promise=1, start_i=1; no cooperation commitment label |
| 我不同意这个方案。 | 我 / 不同意 / 这个 / 方案 / 。 | only start_i=1; no disagreement classifier |
| 你可以考虑吗？ | 你 / 可以 / 考虑 / 吗 / ？ | can_you=1, hedge=1, start_you=1; can_you coordinates are flat |

These results illustrate tokenization sensitivity and the difference between a lexical marker and an actual social action. In particular, negation does not remove the upstream promise flag. No automatic mapping into the eight registered labels, inferred person targets, relationship edges or behavior scores is implemented.

## Validation and reproduction

Local Python 3.13.5. Direct Git cloning and package acquisition were unavailable due to DNS. Retrieved the five files using GitHub at the pinned commit, reconstructed their exact bytes in a private isolated source directory and verified all five Git blobs before execution. Retained original MIT license (blob 24162d9095fe1ba447e2c2782bc290e48146d10e). Minimal empty package shells enabled the original imports; they are not the full ConvoKit package. The actual extractor and marker utility and all lexicons were byte-identical to upstream. No mock was used for successful extraction; failure-path tests patch provider lookup only.

With the pinned source on PYTHONPATH, execute the provider-specific tests separately from default native discovery (like the optional SAOM runtime suite):

```bash
PYTHONPATH=src:<trusted-provider-source-root> python -m unittest discover -s tests/language_runtime -v
```

Isolated source-slice results: 12 new provider/boundary test methods pass; 16 existing annotation_text methods also pass in the no-provider source slice; 28 total, no errors/failures/skips. Existing annotation_schema blob 354d87ce525193e9e328332a668e237d6ece4551 and annotation_text blob 9ce37226368d7a0a773bdab0f03667b9ea1dea55 match #32. Executed source blob 500d47eeae83c17b888975e9b1df1a9c9e3708e1 and test blob 094c903b6acf547fd8ef167a67fc8763eddf35ee. The repository-wide prior 564-test suite and full provider install were not executed. No new CI or consumer/install test suite.

## Research handoff

Next: independently qualified Chinese segmentation and private current-record/receipt binding, then independent annotation of explicit topic-directed disagreement, with separate addressee, person subject and topic fields, exact spans, uncertainty and a frozen held-out conversation/topic split. Use the feature provider as candidate covariates only. No real data, gold annotations, weights, classifiers, accuracy estimates or future-conflict outcomes were acquired here. D4b and #23 remain open.
