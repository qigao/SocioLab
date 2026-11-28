# R3q: Versioned reviewed-expression store and temporal projection

Refs #23. [#44 admission CI #1](https://github.com/qigao/SocioLab/actions/runs/46154734959) succeeded on `2dd51f1d`: 60 native test methods, including 13 new admission methods and four replays of archived actual LLM outputs. The authored references are not independent empirical validation. R3p remains NOT_ADMITTED / NOT_ESTABLISHED.

## Scope and safety of measurement

This is a **synthetic-only research sidecar**, not a production observation-admission authority. It lets the existing reviewed candidate machinery be exercised end to end with versioned temporal network views without claiming validated facts about real people. Reject non-synthetic EventDatasets. Do not infer observed relationships, realized cooperation, private beliefs, causality, or a future behavior from expressed speech. Do not write to the original EventDataset, annotations, or existing network layers.

The source journal and this immutable sidecar have separate receipts. A source utterance may have multiple expression candidates; the append operation recomputes the R3p audit, requires exact declared human-format reference agreement and an explicit nonempty selection of eligible action hashes. A reviewed report/quotation, negation, condition, unresolved object or attribution cannot be selected as a direct expression. A declared authority ID and source reference accompany every sidecar revision. No reviewer or authority authentication is provided; neither declarations nor hashes establish real-world provenance. The review reference is supplied separately from the model. Recompute exact journal and evidence binding at append rather than accepting a caller-provided eligibility list.

## API

```python
from sociolab.semantic_observations import (
    SemanticObservationStore, append_reviewed_snapshot,
    withdraw_reviewed_snapshot, project_reviewed_expressions, expression_graph,
    load_semantic_observations,
)

store = SemanticObservationStore.empty(dataset)
store = append_reviewed_snapshot(store, dataset, context, frozen, model_report,
    original_bytes=authorized_bytes, people=people, topics=topics,
    model_key="qwen3-8b", reasoning_mode="off",
    admission_cutoff=K, reviews=review_records,
    selected_action_hashes=explicit_selection, revision_id="r1", supersedes=None,
    received_at=receipt_utc, authority={"id": operator_id, "source_ref": authority_ref})
projection = project_reviewed_expressions(dataset, store,
    journal_cutoff=K, observation_cutoff=1, start=source_start, end=source_end)
graph = expression_graph(projection, layer="PERSON_TOPIC", action="support")
```

The sidecar serializes using `store.to_dict()` and can be read using `load_semantic_observations(path)`. It is immutable, in-memory JSON with explicit serialization, not an SQL database, concurrent writer, or automatic live service. The caller owns durable atomic file writes. Revisions use a stable source-system / interaction-fact key, a unique revision ID, an explicit current predecessor, contiguous sidecar sequence, nondecreasing source-journal cutoff and UTC receipt, previous record hash, exact source journal prefix hash and explicit authority. A snapshot replaces the entire selected set for that interaction, not an incremental addition; a withdrawal suppresses its current head without claiming that no action occurred. Reassertions must supersede the current withdrawal. The source journal remains unchanged. Hashes are consistency checks, not signatures; only load trusted locally created stores.

Projection uses two explicit knowledge prefixes and a half-open source-time window [start,end). Reject unavailable future sidecar receipts and mismatched source prefixes rather than silently assuming compatibility. Retain receipt availability in each event. A later journal correction, ambiguity or noncanonical catalog identity withholds the affected snapshot; it does not silently reassign subjects or revive an older snapshot. Historical prefixes remain reproducible. The store also checks that the original context was current at its extraction and review cutoffs. Catalog descriptions and conversation membership remain externally declared. This is descriptive time-window analysis, not an authenticated as-of wall-clock feed or a causal estimator. Callers must choose cutoffs corresponding to what was actually available at a prediction origin.

## Typed projection

- PERSON_PERSON: direct expression directed to a person. An insult or threat is a language expression, not a verified hostile relation or executed threat. Self-targets are excluded by the audit.
- PERSON_TOPIC: direct expression toward a declared topic or proposal. Disagreement with a proposal is not automatically conflict with another person.
- PERSON_ACTIVITY: deliberately not implemented here. The current action schema admits person/topic subjects only. Existing explicit activity and participation records remain authoritative; add a reviewed activity-identity mapping and projection contract before connecting those layers.

Events include exact selected candidate hash, source/target record IDs, source occurrence time, sidecar availability time, revision/audit identity and original evidence coordinates. Edges aggregate **counts of selected reviewed expression candidates** by layer, typed source, typed target and action; counts are neither tie strengths nor calibrated probabilities. `expression_graph` uses the existing NetworkX library, creates a separate directed graph for one layer and action, and retains contributing event IDs. It neither mutates nor replaces a social relationship graph. The person/topic typed node keys cannot collide even when their string IDs are equal. Simultaneous events are ordered deterministically only for output, not causal ordering.

## Native validation

Thirteen new test methods exercise immutability, JSON roundtrip, source-time windows, dual receipt prefixes, explicit selection, reference mismatch, revision/retraction, source correction, temporal count evolution in two NetworkX layers, identity remapping, receipt order, forked prefixes and tampering. One of the thirteen replays the actual #43 reported-and-own model output against authored review fixtures, selecting only the sender's support and retaining no third-party disagreement edge. The workflow reruns all 60 semantic/context/study/admission test methods, then the new sidecar tests. No model download, new inference, default dependency, installer/consumer test, automatic real-data admission or independent accuracy claim. Exact-head CI pending at submission.

Next: a versioned activity association and multi-layer descriptive evolution contract; independent empirical reviews and an explicit production observation policy remain prerequisites for real-data qualification.
