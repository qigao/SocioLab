# R3s: Layer-specific multilayer structure and community evolution

Refs #23. [R3r native CI #1](https://github.com/qigao/SocioLab/actions/runs/46157512783) succeeded at `3f48da28`: all 86 native methods, including 13 aligned multilayer tests. Source-time windows, separate receipt prefixes, explicit activity associations and recorded attendance already have a common frame. This stage examines structural changes without treating different layers as interchangeable social relationships.

## Interface

```python
from sociolab.semantic_multilayer_structure import compare_multilayer_structure

report = compare_multilayer_structure(dataset, store,
    before=before_spec, after=after_spec,
    actors=["A", "B", "C"], actions=["support", "insult"],
    seed=0, resolution=1.0, max_nodes=200, max_edges=2000,
    expression_group_members=["B"], attendance_group_size=1)
```

Build both R3r frames once from the same journal/store lineage, then reuse its fixed-window/ordered-window comparison. Require a fixed explicitly selected cohort of canonical persons known at both journal prefixes, an explicit set of registered actions, nonnegative seed, finite positive resolution and computation budgets. Cohort is the expression graph's denominator, not a membership or complete coverage assertion. Report omitted out-of-cohort event IDs. Attendance retains its own native eligibility population, not silently restricted to that cohort.

## Independent structural measurements

For each action, construct a directed Person–Person selected expression graph and preserve event counts as positive weights for the original NetworkX Louvain community adapter. Use the existing structural report helper and community comparison for common cohort partition changes. All isolates and reachability values refer only to selected expression topology, not actual social isolation, influence or temporal transmission.

Compute in/out neighbors and weighted in/out expression counts separately; use original unweighted NetworkX betweenness (counts are not distances). Record per-person before/after values and deltas. When explicitly requested, score the supplied expression key group on a declared unweighted topology copy using the existing group-betweenness adapter. Do not automatically select groups in directed graphs: the existing upstream selection scope does not qualify that operation.

Person–Topic retains a typed bipartite profile, per-person topic and expression counts, per-topic actor and expression counts, selected and outside-cohort event IDs. Do not create interpersonal ties from shared topic support. No unified graph or signed community model is implied. Activity-context association changes remain available in the R3r comparison; they do not manufacture participation.

For actual recorded attendance, reconstruct the native NetworkSnapshot from each frame and use the existing `compare_snapshots` analysis. Both participation snapshots must have complete declared coverage; otherwise explicitly skip attendance structure while retaining expression and incidence views. The caller's original count/Newman/no-projection policy is retained. When requested, use the existing upstream `prominent_group` selection only under its connected, undirected, unit-weight and size/budget guards. Group positions describe structural potential, not social power.

If either expression graph exceeds node/edge budgets, retain its topic profile and selected evidence but skip the costly structure analysis. Likewise skip co-participation structure when projected graph exceeds the same budget. The existing affiliation pair budget still applies during frame materialization. No fallback estimator, automatic model scoring, combined centrality or comparison of unequal measurement units.

## Validation

Ten new test methods exercise topic counts without person projection; late attendance without an expression community change; source correction and selected expression topology change; separate cohorts; incomplete attendance coverage; computation budgets; no requested affiliation projection; invalid and noncanonical cohorts; explicit options; and upstream group selection on a synthetic A–B–C co-participation path. The path's expected unique one-person group is B, with normalized group betweenness 1. This is a synthetic test expectation, not a completed empirical result. Scoped CI reruns all preceding 86 tests, for 96 planned methods. It installs the already declared pandas dependency for the original NetworkX group routine. No new default dependencies, model download, installer/consumer test or source data mutation.

This remains descriptive synthetic research. No empirical qualification, real-data admission, identified causal effect, prediction or time-respecting transmission claim. Next: a fixed-roster, prospectively frozen repeated-frame study with explicit observation coverage and independent behavioral outcomes, before testing whether language-derived measures improve future prediction.
