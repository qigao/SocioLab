# R3c: ICU Chinese segmentation and actual ConvoKit composition

Bounded research adapter for #23, following #32 and #33. No learned semantic classifier, motive inference, empirical language qualification, automatic graph update or future-conflict prediction.

## Provider and exact byte contract

Use the original ICU4C 76.1 sentence and word BreakIterator C APIs through Python ctypes, with explicit trusted operator-supplied absolute shared-library path. The library must expose the versioned _76 C symbols, report ICU/data version 76.1 and Unicode 16.0. See [ICU 76.1](https://github.com/unicode-org/icu/releases/tag/release-76-1) and [boundary analysis](https://unicode-org.github.io/icu/userguide/boundaryanalysis/). No alternate tokenizer or auto-discovery. The currently executed runtime is Linux x86-64 only; no universal native-library distribution support is claimed. A future production package binding is a separate decision.

```python
from sociolab.icu_chinese import segment_icu_chinese, extract_icu_chinese_politeness

segmentation = segment_icu_chinese(content_record_id, content_payload, original_bytes,
                                  library_path=trusted_icu_library_path)
report = extract_icu_chinese_politeness(content_record_id, content_payload, original_bytes,
                                        library_path=trusted_icu_library_path)
```

Use the authorized current record and exact original bytes. #32 validates source hash and both lengths. Admit declared zh, nonblank and at most 1 MiB of source UTF-8 bytes (a bounded engineering profile, not a natural language limit). Call ICU sentence segmentation and then word segmentation independently within each sentence. Convert native UTF-16 break positions to exact original Unicode-codepoint positions; retain all punctuation, emoji and non-whitespace text, omit only whitespace tokens. Reuse #33's token coverage checks. A nonconforming break result fails rather than normalizing or inserting replacement text. Keep all source sentence spans and their mapping to nonempty output sentence groups. The original ICU locale request, effective locale information, warning codes, version/data version and library-file digest are reported. On this host zh reports valid locale zh, actual locale root and open warning -127 (U_USING_DEFAULT_WARNING); do not describe that as verified locale-specific rules. The observed dictionary word output is directly tested. The data-version string and library file hash are reproducibility metadata, not attestation of loaded binaries or all transitive ICU data; the linked local data file hash is recorded below.

The new composed result nests the original ConvoKit feature artifact without changing its schema, including its segmentation hash and feature identity. The outer artifact binds both provider results. No private text or content_ref is returned; record identifiers, digests and offsets still require private handling. No tokenizer accuracy claim or journal freshness/receipt binding is added.

## Executed fictional comparisons

Compared the actual ICU dictionary tokens against a simple codepoint baseline with the **same ICU sentence ranges**. Both use the actual original ConvoKit v5.0.0 extractor and all 26 features. Every cell below lists the selected tokens or the complete set of positive feature names; this is a designed engineering contrast, not an accuracy benchmark.

| Text | ICU words | ICU positive features | Codepoint positive features |
| --- | --- | --- | --- |
| 谢谢您。 | 谢谢 / 您 / 。 | gratitude, you_honorific | you_honorific |
| 我们一起讨论。 | 我们 / 一起 / 讨论 / 。 | together | start_i |
| 我不保证。 | 我不 / 保证 / 。 | promise | start_i |
| 我不同意这个方案。 | 我不 / 同意 / 这个 / 方案 / 。 | none | start_i |
| 你可以考虑吗？ | 你 / 可以 / 考虑 / 吗 / ？ | can_you, hedge, start_you | can_you, hedge, start_you |
| 谢谢您。我们一起讨论。 | 3 + 4 tokens across 2 sentences | gratitude, together, you_honorific | start_i, you_honorific |
| 🙂谢谢您。CRLF 我们一起讨论。𠀀！ (CRLF denotes the actual newline, no inserted space) | 4 + 4 + 2 tokens across 3 sentences | gratitude, together, you_honorific | start_i, you_honorific |

Segmentation changes lexical flags, not necessarily classification quality. A negated guarantee still matches promise; no positive feature in the explicit disagreement sentence does not establish neutral language. ICU can combine 我不; it is a candidate segmentation, not a linguistically certified reference.

## Validation

Python 3.13.5, actual ICU 76.1 / Unicode 16.0 / data 76.1, default locale en_US_POSIX, Linux x86-64. Library-file SHA-256 a8e433e81075732faf255b17d4a25ce28632e41fef1a75e727ee7f4ed73ab151; local libicudata.so.76 SHA-256 a04b2b906193fa1e40f968a3d16d7d6c844a1fafbdd5bce6e9f67b01c124ff24. All five ConvoKit files at commit 91a1df0143668d8e0017f932f97ac878e53b91fa matched the exact hashes in #33; original algorithm/lexicons executed in a private source slice using minimal package shells, no mock for actual extraction. Existing annotation_schema, annotation_text and chinese_politeness source blobs match #33 (354d87ce525193e9e328332a668e237d6ece4551, 9ce37226368d7a0a773bdab0f03667b9ea1dea55, 500d47eeae83c17b888975e9b1df1a9c9e3708e1).

**12 new isolated test methods passed (0 failures/errors/skips)**, including actual ICU and composed-provider comparisons, supplementary Unicode characters, mixed content and combining characters, original coverage, hash/identity, and explicit path/size rejection. One mock composition test checks forwarding only; three additional tests execute both real providers. New tested Git blobs: source 2eb6aebd605cfe5e34ad85727883d47a2ee64103 and tests 5f7ca8c4cc0be978eda1825f3c862805a0333e63. Seven fictional end-to-end comparison cases were also executed and reported above.

```bash
SOCIOLAB_ICU_LIBRARY=/absolute/trusted/libicuuc.so.76 \
PYTHONPATH=src:<trusted-pinned-convokit-root> \
python -m unittest discover -s tests/language_runtime -p test_icu_chinese.py -v
```

DNS prevented repository clone and full package acquisition. The full 564-test prior suite, full ConvoKit distribution and other OS/architectures were not tested this round. No default dependency, vendor file, workflow or installer/consumer test added. Trusted library path is operator configuration, never arbitrary external input.

## Next measurement design (proposal, not frozen or executed)

Select a narrow utterance-level task: explicit speaker-owned disagreement with a named proposal, not negative sentiment, hostility or disagreement with a person. Keep a distinct state for insufficient evidence, quotation/attributed speech, unclear referent, and mixed or ambiguous acts. Positive examples require a specific proposal identity and verified target-utterance spans. Do not label every nonpositive as neutral: use a separate task result and retain existing v1 taxonomy semantics.

Context must be an explicit ordered set of preceding utterances in the same declared conversation, with exact source-time and knowledge-cutoff bindings, source/parent revision checks and no future text; current journal selection remains an implementation prerequisite. Do not infer a conversation from the addressee alone or concatenate arbitrary nearby messages. No actual context API is added here. Predeclare the allowed context size and handling of unknown order, missing context and quotations before an empirical study.

Use independently annotated Chinese references, including target/subject/topic and span agreement, multi-annotator disagreement, frozen conversation/topic-group splits and rights/source audit. Compare lexical/abstain baselines and a pinned semantic model on exactly the same examples. Report accuracy and abstention separately, with joint semantic-target performance, unresolved cases and coverage; no fit/test or real-world validity claim now. R3b feature extractor and ICU are candidate preprocessing, not standalone social-action classifiers. #23 and D4b acceptance boxes remain open.
