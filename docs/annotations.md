# Versioned annotations and descriptive agreement

**D4a is implemented:** SocioLab accepts human or externally supplied structured labels, checks their exact source bindings, builds explicitly derived annotation-count views, and compares a specified candidate method with a human reference. It does not fetch source text or execute a classifier.

**D4b remains open:** the accuracy, calibration and deployment qualification of a genuine automatic annotation provider are not established. Imported `kind: "model"` metadata does not prove that a model ran. D5 network–behavior coevolution is also separate and unimplemented. The [dynamic-analysis guide](dynamic-analysis.md) describes the underlying journal, coverage and graph-analysis contracts.

## Run the supplied example

Run from the repository root after `python -m pip install -e .`:

```bash
python -m sociolab events validate examples/annotations/events.json
python -m sociolab annotations inspect examples/annotations/events.json > annotation-inspection.json
python -m sociolab annotations inspect examples/annotations/events.json --method examples/annotations/human.method.json
python -m sociolab annotations evaluate examples/annotations/events.json --reference-method examples/annotations/human.method.json --candidate-method examples/annotations/model.method.json > annotation-evaluation.json

python -m sociolab snapshot examples/annotations/events.json examples/annotations/conflict-before.view.json > annotated-conflict-before.snapshot.json
python -m sociolab snapshot examples/annotations/events.json examples/annotations/conflict-after.view.json > annotated-conflict-after.snapshot.json
python -m sociolab changes annotated-conflict-before.snapshot.json annotated-conflict-after.snapshot.json > annotated-conflict-change.json

python -m sociolab snapshot examples/annotations/events.json examples/annotations/disagreement.view.json > annotated-disagreement.snapshot.json
python -m sociolab snapshot examples/annotations/events.json examples/annotations/model-disagreement.view.json > model-disagreement.snapshot.json
```

The [fixture](../examples/annotations/events.json) contains 36 records, four people, six invented utterances, six human-format labels, and five model-format labels. All labels are supplied fixtures; [the builder](../examples/annotations/build_example.py) does not call a model. Human labeling times are tick 50 and candidate labeling times tick 51; source utterance times are 5, 6, 7, 8, 15 and 16. Network windows use those **source event times**, together with the receipt cutoff that determines which labels were available.

The human conflict view has one `B→A` insult count in `[0,10)` and none in `[10,20)`. The human disagreement view has no interpersonal edge: the disagreement concerns topic `proposal-P`, and remains visible as a topic decision. These labels do not alter the separate observed cooperation layer.

The candidate disagreement view exposes one supplied `A→B` annotation-count edge, but is **incomplete**: the candidate's `m4` decision is `uncertain`. That unresolved source event blocks completeness even though the requested label filter is only `disagreement`. The snapshot remains inspectable; `communities analyze` and other analytical commands reject it. The fixture intentionally shows how a correct label with the wrong semantic subject can create a different derived graph.

Saved artifacts: [inspection](experiments/2026-11-27-annotations/inspection.json), [evaluation](experiments/2026-11-27-annotations/evaluation.json), [conflict changes](experiments/2026-11-27-annotations/conflict-change.json), [candidate snapshot](experiments/2026-11-27-annotations/model-disagreement.snapshot.json), and [execution record](experiments/2026-11-27-annotations/validation.json).

## Content and annotation records

Both new kinds use the existing `sociolab.events.v1` record envelope, revision chains and importer-owned receipts. Their `valid_interval` is `null`. Raw import batches still omit `ingest_seq` and `recorded_at`. No message body, quoted text, arbitrary extra field or unregistered taxonomy is admitted.

### `content.observed`

The payload has exactly these fields:

| Field | Contract |
| --- | --- |
| `interaction_record_id` | Exact earlier asserted `interaction.observed` record whose action is `utterance` or `reply` |
| `content_ref` | Nonempty source reference; SocioLab does not dereference it |
| `content_revision` | Nonempty declared revision identifier |
| `content_hash` | `sha256:` followed by 64 lowercase hexadecimal digits |
| `language` | Nonempty declared language label |
| `length` | Exactly `unicode_codepoint` and `utf8_byte`, both nonnegative integers |

Declared byte length must be between one and four times declared codepoint length. These checks validate metadata consistency; **the bytes, hash, language and lengths are not independently verified**. Current availability also requires the exact parent interaction to remain effective.

### `annotation.recorded`

| Field | Contract |
| --- | --- |
| `target_record_id` | Exact earlier asserted `content.observed` record ID |
| `target_content_revision`, `target_content_hash` | Must equal that record's declared revision and hash |
| `method` | Exactly `kind`, `id`, `version`; kind is `human`, `rule` or `model` |
| `taxonomy` | Exactly `{"id":"sociolab.social-actions","version":"1"}` |
| `label` | One of the eight registered labels below |
| `subject` | Exactly `kind` and `id`; kind is `person`, `topic` or `none` |
| `topic` | Nonempty text or `null` |
| `evidence` | Array of span objects, each exactly `unit`, `start`, `end` |
| `score` | `null` or `{"kind":"uncalibrated","value":<finite number>}` |

The labels are `disagreement`, `insult`, `threat`, `cooperation_commitment`, `mediation`, `support`, `neutral`, and `uncertain`.

A person subject must reference a known person and cannot resolve to the speaker. It can differ from the message addressee: the addressee and the person being discussed are separate roles. A topic subject's ID must equal `topic`. A `none` subject has a null ID and is allowed only with `neutral` or `uncertain`.

Evidence spans are half-open `[start,end)` with integer bounds and positive length. The unit is `unicode_codepoint` or `utf8_byte`; offsets must fit the corresponding declared content length. Duplicate or overlapping spans within the same unit fail. Non-neutral, non-uncertain labels require at least one span. The units are not interchangeable, and the importer cannot verify actual substrings or byte boundaries without the source bytes. No offset conversion is inferred.

Scores remain uncalibrated metadata, even if a value happens to fall between zero and one. They are not probabilities or qualification thresholds and are not used in agreement calculations.

Example method file:

```json
{"kind":"human","id":"example-reviewer","version":"1"}
```

All three fields define method identity. A new version is a different method. Importing two independent effective decisions for the same exact content/method/taxonomy creates ambiguity, even if their labels agree. Correct a decision through its revision chain instead of letting the newest unrelated record win.

## Current, stale, and ambiguous bindings

`annotations inspect DATASET` reports all effective annotation assertions. `--method METHOD.json` filters the exact method identity; `--knowledge-cutoff K` selects the existing receipt prefix. The Python function also supports an exact taxonomy filter. Ambiguity is assessed before filters are applied.

| Status | Meaning |
| --- | --- |
| `CURRENT` | Exact content and interaction remain effective, with one applicable content record and one decision for this method/taxonomy |
| `STALE_CONTENT` | The exact target content was superseded or retracted |
| `STALE_INTERACTION` | The exact parent interaction was superseded or retracted |
| `AMBIGUOUS_CONTENT` | Multiple effective content records describe the same active interaction |
| `AMBIGUOUS_ANNOTATION` | Multiple effective decisions share this exact content/method/taxonomy |

Rows retain reasons, conflicting or invalidating IDs, source and canonical subject identities, content metadata, spans and evidence record IDs. `current_contents` includes unambiguous active content even when it has no label; `content_issues` retains excluded or historical bindings still referenced by effective annotations. If several problems apply, status precedence is stale content, stale interaction, ambiguous content, then ambiguous annotation; `issues` retains the applicable detail.

A new content record ID invalidates the old binding **even when its text hash is unchanged**. Updating the interaction likewise does not automatically reattach its old content or labels. Historical parent assertions remain legal references so stale records can be inspected. Earlier as-known cutoffs retain the earlier valid interpretation. Input hashes cover the selected receipt prefix, so appending later records does not rewrite an earlier result.

## Annotation-count network views

An annotation view adds `source_layer`, `method`, `taxonomy` and `labels` to the window-view contract:

```json
{
  "schema": "sociolab.view.v1",
  "population": "team",
  "layer": "annotated_conflict",
  "mode": "annotations",
  "directed": true,
  "start": 0,
  "end": 10,
  "actions": ["reply", "utterance"],
  "roles": [],
  "topics": [],
  "source_layer": "communication",
  "method": {"kind":"human","id":"example-reviewer","version":"1"},
  "taxonomy": {"id":"sociolab.social-actions","version":"1"},
  "labels": ["insult", "threat"]
}
```

`source_layer` must be `communication`; direction must be true; roles must be empty; actions must explicitly select `utterance` and/or `reply`. Labels must be a nonempty subset of the selected layer's registered labels:

| Derived layer | Admitted labels |
| --- | --- |
| `annotated_disagreement` | `disagreement` |
| `annotated_conflict` | `insult`, `threat` |
| `annotated_cooperation_commitment` | `cooperation_commitment` |
| `annotated_mediation` | `mediation` |
| `annotated_support` | `support` |

Completeness has two requirements: complete source communication coverage and a resolved annotation decision for **every eligible source interaction**, selected by population, window and actions. Each needs one current content record and one `CURRENT` decision for the exact selected method/taxonomy. Missing, stale, ambiguous or uncertain decisions remain unresolved. This check runs **before label and topic filtering**, so a narrower filter cannot hide missing classifications.

A `neutral` decision resolves its source event and creates no edge. A nonmatching label/topic also creates no edge after its decision is recorded. A topic subject is retained as a topic decision, never converted into an edge to the addressee or proposal author. An eligible person subject produces `speaker→subject`, with positive integer `annotation_count` strength. A person outside the population at source event time is explicitly recorded as outside-population, without an edge.

The snapshot preserves `annotation_summary`: source events, decisions, unresolved items, counts, method/taxonomy and `source_coverage_complete`. It marks `UNVALIDATED_SOURCE_LABELS` and `automatic_annotation_qualified=false`. Standalone analysis and `changes` retain that measurement basis and summary. Complete coverage means all required decisions are present; it does not certify that the decisions are accurate.

Method, taxonomy and label choices belong to the policy hash. Changing a human method to a model method cannot be presented as a time change under the same policy. Annotation views do not overwrite observed cooperation, trust, attendance, source-coded conflict or communication.

## Reading an evaluation report

`annotations evaluate` requires an exact **human** reference method and a different exact candidate method. Candidate methods may be human, rule or model metadata. A human reference is supplied comparison material, not certified truth. The evaluator uses all current unambiguous content revisions in the journal at the cutoff; it has no snapshot-window or label filter.

Pairing requires the **same content record ID**. Matching hashes, similar text, shared interactions or another method version cannot substitute. Both decisions must be unambiguous and current. Human `uncertain` is unresolved and excluded from eligible reference count; candidate `uncertain` is an abstention, not a neutral or negative prediction.

| Report quantity | Denominator or scope |
| --- | --- |
| `current_content_count` | All current unambiguous content revisions with an active exact parent |
| `reference_count` | Revisions with one current, unambiguous, non-uncertain reference decision |
| `matched_count` | Eligible reference revisions with one current, unambiguous, non-abstaining candidate |
| `agreement.label_accuracy` | Equal labels among matched pairs |
| `agreement.subject_accuracy`, `topic_accuracy` | Exact canonical subject or topic equality among matched pairs |
| `agreement.semantic_target_topic_accuracy` | Both subject and topic equal among matched pairs |
| `agreement.joint_accuracy` | Label, subject and topic all equal among matched pairs |
| `coverage.matched_over_reference` | Matched count / eligible reference count |
| `coverage.joint_correct_over_reference` | Jointly correct matched count / eligible reference count; unscored items remain unresolved |

Every fraction contains `numerator`, `denominator` and `value`; an empty denominator gives `null`. Missing-reference/candidate IDs, per-target statuses and unresolved reasons remain visible. `annotation_audit` preserves selected methods' uncertain, ambiguous and stale records, including annotations whose targets are outside current content. Other method versions are listed separately rather than pooled.

Confusion counts and per-label metrics use **matched non-abstaining pairs only**. Per-label `support` sums to `matched_count`; `eligible_reference_support` and `unscored_reference_count` reveal reference items excluded by missing or unusable candidates. Precision is null with no predictions of that label, recall is null with no matched reference support, and F1 uses `2*TP/(support+predicted_count)`, null when that denominator is zero. These conditional metrics must be read with coverage.

For the supplied fixture, the six eligible human references yield four matched pairs: `m4` abstains and `m6` lacks a candidate. Label agreement is **3/4**, combined subject/topic agreement **2/4**, and joint agreement **2/4**. Matched/reference coverage is **4/6**; jointly correct/reference is **2/6**. In particular, candidate `m1` has the right disagreement label but targets person B instead of topic `proposal-P`, so it is not jointly correct. These are illustrative fixture results, not measured performance of an executed model.

`qualification_status` remains `NOT_ESTABLISHED`. Perfect agreement would not establish independent labeling, a held-out evaluation, source authenticity, representative data, calibrated probabilities, deployment quality or causal validity. The report does not infer training/test independence from caller-supplied method names and applies no automatic qualification threshold.

## Python entry points and evidence

```python
from sociolab.events import load_event_dataset
from sociolab.annotations import annotation_report
from sociolab.annotation_evaluation import evaluate_annotations

dataset = load_event_dataset("examples/annotations/events.json")
human = {"kind": "human", "id": "example-reviewer", "version": "1"}
candidate = {"kind": "model", "id": "provided-demo-labels", "version": "1"}
inspection = annotation_report(dataset, method=human, knowledge_cutoff=None)
evaluation = evaluate_annotations(
    dataset, reference_method=human, candidate_method=candidate,
    knowledge_cutoff=None,
)
```

The existing `materialize_snapshot`, `load_view` and `compare_snapshots` APIs handle annotation views under the same receipt, membership and coverage rules. Graph-only API callers must still check `snapshot.require_complete()` and retain the annotation measurement metadata in their own outputs.

Contract sources: [annotation_schema.py](../src/sociolab/annotation_schema.py), [events.py](../src/sociolab/events.py), [annotations.py](../src/sociolab/annotations.py), [annotation_evaluation.py](../src/sociolab/annotation_evaluation.py), [snapshots.py](../src/sociolab/snapshots.py), and [cli.py](../src/sociolab/cli.py). No source content is fetched, no classifier is trained or called, and this addition changes neither the reference commands nor the existing network-only SAOM model.
