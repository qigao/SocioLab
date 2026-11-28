# R3t: Frozen longitudinal semantic panel

Refs #23. [R3s CI #1](https://github.com/qigao/SocioLab/actions/runs/46158419431) failed one fixture because C→A identity mapping duplicated an active coverage actor. Correct the coverage assertion before merging identities, without changing journal production guards. [R3s CI #2](https://github.com/qigao/SocioLab/actions/runs/46158584345) succeeded at `53085075`: all 96 native methods, including upstream group selection.

## Scope

Compare multiple time points without silently replacing previously available features with corrected history. The existing expression sidecar, activity association, participation snapshot, affiliation and NetworkX routines remain authoritative. This new module is an immutable-by-replay, JSON-compatible **synthetic research** panel, not a new observation store, live subscription or predictor. No real-data qualification is implied.

## Interface

```python
from sociolab.semantic_panel import (
    freeze_semantic_panel, start_semantic_panel,
    append_semantic_wave, verify_semantic_panel,
)

settings = {
    "actors": ["A", "B", "C"], "actions": ["support", "insult"],
    "population": "team", "roles": [],
    "affiliation_projection": "count", "max_pairs": 100000,
    "seed": 0, "resolution": 1.0, "max_nodes": 200, "max_edges": 2000,
}
schedule = [
    {"wave_id": "w1", "start": 0, "end": 3, "as_of": first_utc},
    {"wave_id": "w2", "start": 3, "end": 6, "as_of": second_utc},
    {"wave_id": "w3", "start": 6, "end": 9, "as_of": third_utc},
]
plan = freeze_semantic_panel(dataset, store, registered_at=first_utc,
    schedule=schedule, settings=settings)
panel = start_semantic_panel(dataset, store, plan)
panel = append_semantic_wave(dataset, store, plan, panel,
    wave_id="w1", activity_links=None)

# At the next declared origin use the extended, actually selected inputs.
panel = append_semantic_wave(later_dataset, later_store, plan, panel,
    wave_id="w2", activity_links=explicit_link_plan_or_none)
verified = verify_semantic_panel(later_dataset, later_store, plan, panel)
```

Freeze 2–32 equal-duration nonoverlapping ordered source windows, unique wave IDs and strictly increasing UTC availability instants at/after registration. Gaps are allowed but not silently resampled. UTC source windows must end no later than their as_of; synthetic tick clocks have no automatic mapping to UTC. Freeze canonical fixed person cohort, registered action types, participation population/roles, projection and resource budgets. Registration includes the exact supplied journal and sidecar prefixes and fingerprints. The supplied sources must end at receipts available by registration.

Append only the next planned wave, selecting the entire supplied journal and sidecar at that wave's declared origin. Reject future receipts, backwards prefixes, unavailable activity associations and identities that cease to be canonical. A registration or issuance timestamp is a declared value, not external attestation. A prefix may omit records not supplied by the caller; this cannot independently prove observation completeness or that a study was genuinely registered before looking at later outcomes.

Each wave records its original two receipt cutoffs, link plan or explicit none, frame and prefix hashes, activity link status, fixed-cohort feature rows and wave hash. Replay verifies the registration and every saved wave against the original receipt prefixes, even if later corrections and observations extend the source. Rehashed changed features fail exact recomputation. A completed wave must not be replaced by a retrospective reconstruction. Persist the private plan and panel yourself; no durable writer, scheduler or online service is introduced.

## Feature units and coverage

Per fixed actor and selected action, retain distinct incoming/outgoing person neighbors and expression counts, unweighted betweenness, and person–topic distinct-topic and expression counts. Keep community partitions per wave, not global community identities; do not combine unrelated layers or create person ties from shared topics. Evidence and out-of-cohort IDs remain available. Zero expression counts mean no **selected** in-scope expression, not no expression or absence of social relationships.

Attendance retains the native eligible roster and coverage separately. Selected positive incidence counts remain descriptive when coverage is incomplete; complete-view incidence counts and co-participation features are null when their prerequisites are not met. Never fill missing measurements with zero. The existing affiliation projection operates on its own native population, not the fixed expression cohort. When requested and available, compute unweighted co-participation betweenness and weighted incidence-derived degree using the original graph/NetworkX routines. Preserve resource-bound structural skips as null features instead of discarding people. The participation count and expression count have different units and denominators.

This panel does not collect target labels, fit, score, select predictors, infer future behavior, infer causality, or qualify temporal transmission. Next stage: freeze an independent behavioral outcome stream and future target schedule, check raw target facts and revision ancestry for leakage, and compare an explicit non-network baseline with added historical language/network features on held-out origins. Separate prediction and scoring receipts.

## Validation

Ten new native tests exercise fixed schedules and cohort, incomplete and complete panel replay, late content correction and a later expression/attendance wave, missing coverage, future journal/sidecar/link receipts, explicit link binding, budgets, noncanonical identity, order and tamper checks. Rerun all 96 preceding methods, for 106 planned native methods. No new model downloads, installer/consumer tests, default dependencies, source mutations or real-data admission. Initial [native CI #1](https://github.com/qigao/SocioLab/actions/runs/46158873903) at `1b452340` passed 105 of 106 tests. The third window had complete participation coverage but no activity nodes; NetworkX 3.7 count projection rejects an empty opposite partition. The affiliation adapter now constructs the exact edgeless person graph using `networkx.empty_graph` after normal input validation, preserving all person isolates and the selected count/Newman policy. Nonempty activity partitions still use the original upstream projection algorithms. Five additional boundary test methods cover both policies, empty/one-sided inputs, invalid incidence, explicit no-projection mode, pair budgets and the original Davis reference. The original third-wave regression now asserts valid zero incidence and structural measurements, complete cohort preservation and exact replay. Total native validation plan: 111 methods. No relaxation of coverage rules or fabricated activity nodes; unknown coverage remains null. Corrected exact-head CI pending.
