# R3r: Aligned expression, topic, activity and attendance evolution

Refs #23. [#45 native CI #1](https://github.com/qigao/SocioLab/actions/runs/46155876746) succeeded at `d456e018`: all 73 semantic/context/study/admission/projection methods passed, including the 13 versioned-sidecar tests and replay of an actual archived LLM output. The sidecar remains synthetic-only; model semantic qualification has not been established.

## Reuse the existing engines

- `project_reviewed_expressions` materializes reviewed direct expression candidates by source time and journal/sidecar receipt prefixes.
- `materialize_snapshot` is the existing authoritative membership/coverage/participation view. It preserves activity-description and attendance record evidence; do not implement another attendance selector.
- `affiliation_report` runs the original NetworkX count or Newman co-participation projection only when the selected participation snapshot has complete declared coverage. Explicit pair budget is mandatory. Partial snapshots are retained without this analysis.

An utterance about a topic is not attendance at an activity. Never equate a topic ID with an activity ID, or infer participation because someone supported an agenda. Expression coverage is selected-candidate coverage, not a complete population survey. Attendance coverage and population eligibility do not automatically apply to all expression actors.

## Explicit expression/activity context links

```python
from sociolab.semantic_multilayer import (
    freeze_activity_links, build_multilayer_frame, compare_multilayer_frames,
)

links = freeze_activity_links(dataset, store,
    journal_cutoff=K, observation_cutoff=S, as_of=availability_utc,
    start=source_start, end=source_end,
    authority={"id": declared_operator, "source_ref": declaration_reference},
    links=[{"event_id": selected_expression_id,
            "activity_record_id": exact_activity_description_record_id,
            "evidence_ref": association_evidence_reference}])

spec = dict(journal_cutoff=K, observation_cutoff=S, as_of=availability_utc,
    start=source_start, end=source_end, population="team", roles=[],
    activity_links=links, affiliation_projection="count", max_pairs=100000)
frame = build_multilayer_frame(dataset, store, **spec)
change = compare_multilayer_frames(dataset, store, before=spec, after=later_spec)
```

A link is an explicitly declared association between one selected expression event and one exact current, uniquely described, canonical held activity at the expression's source time. It records source evidence reference and declared authority; it does not independently authenticate them or prove that the utterance was made at the activity. Freeze the entire selected link list and its original availability, source-window and source/observation prefix identities. Rebuild the original plan at its exact historical prefixes before applying it. A later source, expression or activity-description revision withholds the old link rather than silently rebinding; a new link plan can explicitly bind a new version. No link plan means association not requested; an empty declared list is different. This is immutable caller-selected plan versioning, not an append-only link-authority service or automatic discovery of the latest plan.

For each frame, require explicit UTC as_of and verify selected journal, expression and link receipts were available no later than it. These are selected prefixes, not a guarantee that every available input was included. Tick clocks and source-time windows remain distinct from receipt UTC. Preserve complete participation snapshot and expression projection and ensure they share the same source prefix and window. Linked actors get an independent attendance-in-window status with exact incidence evidence: selected, no selected incidence under complete declared coverage, or unknown/outside scope. Window incidence does not establish presence at the exact utterance instant.

Retain the following distinct layers and units:

| Layer | Unit |
| --- | --- |
| PERSON_PERSON | Selected reviewed expressions toward persons |
| PERSON_TOPIC | Selected reviewed expressions toward topics |
| PERSON_ACTIVITY_ATTENDANCE | Binary recorded attendance incidence in view |
| PERSON_ACTIVITY_EXPRESSION_CONTEXT | Selected expressions with explicitly declared activity context |
| TOPIC_ACTIVITY_EXPRESSION_CONTEXT | Selected topic-associated expressions with that declared activity context |

The last two are declared context associations, not new participation facts. Keep expression event IDs, exact activity-description ID, and per-link binding hash. Never add or multiply different units into a combined relationship weight.

## Temporal comparison

Recompute both frames using the same journal/store lineage, same population/roles/affiliation settings, nondecreasing receipt cutoffs and UTC availability. Compare either the identical source-time window (receipt or selection change) or ordered nonoverlapping windows (descriptive window change). Require explicit selection rather than interpreting an arbitrary overlapping-window comparison. For each typed edge/action, report before/after selected count and contributing evidence IDs, including evidence-only changes with zero count delta. Retain both affiliation reports and participation coverage flags. Removal from a selected view does not prove relationship dissolution, cessation of expression, attendance absence or causal effect. No combined community or influence score is inferred; later community analysis needs suitable layer-specific coverage and estimands.

## Validation

Thirteen new test methods cover existing native attendance and affiliation reuse, no automatic link, late attendance receipts, activity and content corrections, ordered windows, future receipt guards, explicit association validation, activity time/status, rehashed incorrect bindings, incomplete coverage, inconsistent comparison settings and evidence-only updates. Rerun all 73 previous semantic contract methods for 86 planned methods. No model download, new inference, default dependency, installer/consumer tests or real-data admission. Native CI pending at submission. Independent semantic review and real-source qualification remain open.
