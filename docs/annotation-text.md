# R3a: Exact content bytes and annotation evidence

First bounded engineering step for #23 / D4b; no language provider or automatic classification yet.

## Private byte boundary

Use the existing journal and annotation_report to select a current, unambiguous content revision and, where applicable, the exact annotation at the declared receipt cutoff. Retrieve the authorized bytes through the source application's private path. Do not treat an arbitrary content_ref as a filesystem path or URL. This helper does not open any files or make any network requests.

```python
from sociolab.annotation_text import verify_content_bytes, verify_annotation_evidence

# Inputs are the exact record ID, existing payloads and authorized original bytes.
text = verify_content_bytes(content_payload, original_bytes)
offsets = verify_annotation_evidence(
    content_record_id, content_payload, original_bytes, annotation_payload,
)
```

The first function returns private text only when the original SHA-256, UTF-8 byte count and strict-decoded Unicode codepoint count match the declared content payload. No BOM stripping, newline conversion, normalization, replacement characters or implicit encoding. The second validates the existing annotation schema, binds the exact record ID/revision/hash, and maps each half-open evidence span into both coordinate systems. UTF-8 spans that split a codepoint are rejected even if their numeric bounds fit. Span order, declared units and cross-unit equivalent spans are retained; the helper does not merge evidence or alter labels. Codepoint boundaries are not grapheme-cluster boundaries.

The result contains only span offsets and the declared units. Do not publish private text, offsets tied to identifiable records, or provider inputs. The helper verifies consistency with declared metadata, not actual source authenticity, language identity, journal currency, semantic validity or whether an annotation's subject is correct. It is not wired into the importer or annotation-count snapshot, so existing outputs and qualification flags are unchanged. Caller-side receipt selection and authorized retrieval remain explicit dependencies; no new content store.

## Candidate source and provider screen

| Candidate | Documented scope | Admission decision |
| --- | --- | --- |
| [ORCHID (EMNLP 2023)](https://aclanthology.org/2023.emnlp-main.582/) / [authors' repository](https://github.com/xiutian/orchid) | 1,218 Chinese debates, 476 topics, 14,133 stance-annotated utterances. | Candidate topic/stance benchmark only; stance or debate role is not an interpersonal insult, threat, or explicit disagreement with a particular proposal. No exact mapping to v1 labels and spans established. |
| [COLD (EMNLP 2022)](https://github.com/thu-coai/COLDataset) | 37,480 comments; binary offensiveness; fine-grained test categories include individual attack, group attack, anti-bias and other non-offensive. Authors link a RoBERTa detector. | Candidate separate text-classification benchmark; not a validated person/topic/offset or future-conflict target. Published benchmark and associated model cannot establish an independent held-out evaluation of that model without training-overlap evidence. |
| [ConvoKit Chinese politeness strategies](https://convokit.cornell.edu/documentation/politenessStrategies.html) | Chinese politeness marker features, not a social-action classifier. | Candidate upstream feature extractor; not selected or executed in this slice. |

Documentation-level screen only: source archives, weights, exact licenses/rights for intended use, sampling and split integrity were not audited. No real text or model weights acquired. No real source admitted to the full annotation contract. Do not merge these tasks into one accuracy figure or turn a person's debate stance or offensiveness label into a relationship or inferred motive.

## Next bounded stage

Freeze a topic-directed disagreement measurement protocol with one utterance and explicitly permitted preceding context. Keep speaker, addressee, semantic subject and topic separate. Use independent human labels with exact spans and uncertain decisions; split by conversation and topic/related duplicates before evaluation. Use one pinned upstream feature/model provider with a private verified-text input and explicit method identity. Compare against an abstention and simple lexical baseline; report joint label/subject/topic correctness and reference coverage. Do not promote a stance label to the existing disagreement label without independent semantic evidence. No future forecasting until separate future outcomes and coverage are admitted.

## Executed validation (2026-11-28)

Python 3.13.5, isolated local source slice; 16 unittest methods passed, zero failures/errors/skips. The original annotation_schema.py was reconstructed and its Git blob matched the parent commit (354d87ce525193e9e328332a668e237d6ece4551). The new source and test Git blobs are 9ce37226368d7a0a773bdab0f03667b9ea1dea55 and c9066e3d7b636d1ac2dbcaef1dea28047bdce46b. Tests cover all 28 nonempty codepoint intervals of the seven-codepoint mixed Unicode fixture in both units, every interior UTF-8 byte at either endpoint, invalid UTF-8 with matching hash, mismatch and schema rejection, exact revision identity, unchanged inputs and offset-only results.

Reproduction from the checkout: PYTHONPATH=src python -m unittest discover -s tests -p 'test_annotation_text.py' -v

Limitation: the execution environment could not resolve github.com for a complete clone. Only the new module/tests and byte-identical upstream schema were executed, not the repository's 564-test suite. No full-package integration or remote CI pass is claimed. No dependencies, installer/consumer tests or workflows changed.
