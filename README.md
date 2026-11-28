# SocioLab

**Python-first social-network research built on existing open-source implementations.**

SocioLab reads versioned observations, builds typed temporal networks, and runs established network analysis and diffusion algorithms directly from their upstream Python packages. It does **not** fork network theory implementations, use Lean or R as a runtime, or simulate a second authoritative Agent world.

## Baseline and scope

- Repository: `qigao/SocioLab`. The dynamic D1–D3 implementation builds on [PR #4](https://github.com/qigao/SocioLab/pull/4) and follows the design in [PR #6](https://github.com/qigao/SocioLab/pull/6), tracked in [Issue #5](https://github.com/qigao/SocioLab/issues/5).
- Migration baseline: [`qigao/lean@master`](https://github.com/qigao/lean/tree/e5be0cf3fb0f57d4ea49093ecab429c5a862615e) at `e5be0cf3fb0f57d4ea49093ecab429c5a862615e` (contains only `LICENSE`). **No unmerged Lean PR files are copied.**
- Initial engines: **NetworkX 3.7** (directed graph and structural analysis) and **NDlib 6.0.1** (upstream threshold diffusion). Other Python packages are added only when a real study needs them.
- Existing reference commands retain their result labels. Dynamic commands produce validated journals, `sociolab.snapshot.v1` snapshots, upstream analysis results, and `DESCRIPTIVE_NETWORK_CHANGE` reports. Source assertions, derived graph properties, simulations and causal effects remain distinct.

## Install and run

Requires Python 3.12–3.13 and package installation from PyPI:

```bash
python -m pip install -e .
python -m sociolab karate  # observed, undirected Zachary 1977 social network
python -m sociolab keyplayers --size 2  # group betweenness, NOT causal power
python -m sociolab structure examples/synthetic_chain.json
python -m sociolab threshold examples/synthetic_chain.json --seeds alice --threshold 0.5 --steps 3
python -m unittest discover -s tests -v
```

All commands fail rather than substitute a locally written graph or diffusion engine if the required upstream package is unavailable.

SocioLab explicitly declares `six==1.17.0`, which NDlib 6.0.1 imports but
omits from its dependency metadata, and `pandas==2.2.3`, which NetworkX's
`prominent_group` requires for the supported group-selection commands.
Each `threshold_report` call runs the
original NDlib engine in a fresh Python subprocess, preserving the caller's
NumPy random state, including concurrent calls from notebooks or Python
programs. This adds interpreter/package startup time per report. Upstream
failures propagate with their error output.

The [2026-11-27 execution record](docs/validation-2026-11-27.md) documents
the tested versions, commands, original s50 archive fingerprint, and the
runtime review. The [SAOM numerical validation record](docs/saom-numerical-validation.md)
defines the convergence gate and preserves the full-budget experiment evidence.

## Dynamic observations and network changes: D1–D3

The implemented pipeline imports typed source records with immutable revisions
and importer-owned receipts, materializes state or time-window snapshots, and
compares their relations, population, connectivity, communities and key groups.
It preserves observation coverage and evidence IDs. Analytical commands reject
incomplete observations; missing data never become silently absent ties.

Run the checked-in synthetic example from the repository root:

```bash
python -m sociolab events validate examples/dynamic/events.json
python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/cooperation-before.view.json > cooperation-before.snapshot.json
python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/cooperation-after.view.json > cooperation-after.snapshot.json
python -m sociolab changes cooperation-before.snapshot.json cooperation-after.snapshot.json --algorithm greedy --group-size 2 > cooperation-change.json
```

An explicit cooperation update removes the C–D bridge: edges change **7→6**,
components **1→2**, and other people reachable from each person **5→2**.
The greedy communities remain ABC/DEF, while the original C/D group's
normalized betweenness changes **2/3→0**. The recorded conflict and actor
attribute do not automatically alter cooperation. These are descriptive
results, without causal attribution.

Additional commands analyze any qualified snapshot:

```bash
python -m sociolab communities analyze cooperation-before.snapshot.json --algorithm louvain --seed 0
python -m sociolab communities compare cooperation-before.snapshot.json cooperation-after.snapshot.json --algorithm greedy
python -m sociolab keyplayers select cooperation-before.snapshot.json --size 2
python -m sociolab keyplayers score cooperation-after.snapshot.json --members C D
python -m sociolab snapshot examples/dynamic/events.json examples/dynamic/participation.view.json > participation.snapshot.json
python -m sociolab affiliations analyze participation.snapshot.json --projection newman
```

The workshop's six attendance incidences produce **15 derived pairs** under
both count and Newman projection; their strengths are respectively 1 and 0.2.
Projection is explicit and bounded, and retains the original bipartite data.
It does not establish friendship, trust or actual conversation.

Group selection is bounded, connected, undirected and unit-strength, with
`k <= min(4,n-2)` and no nonempty exclusions. Scoring an explicitly supplied
group supports directed or disconnected unit-strength graphs. Missing original
members make its later score unavailable; surviving members are not silently
substituted. There is no implicit strength-to-distance conversion.

The [dynamic-analysis guide](docs/dynamic-analysis.md) provides the exact event,
receipt, view and snapshot contracts; CLI and Python APIs; communication and
conflict examples; temporal/coverage rules; and
[execution evidence](docs/experiments/2026-11-27-dynamic-runtime/validation.json).
CLI reports use JSON on stdout; the continuous tracker emits one JSON receipt
per input line. This release adds no database, hosted service or UI.
Existing reference commands retain their behavior.

## Continuous receipt tracking

`tracking init` freezes registered source-time views in a private local store.
`tracking run` consumes JSONL batches from stdin, commits immutable versions and
flushes a receipt before waiting for the next delivery. `tracking inspect`
replays the complete retained history before reporting the current version.

New receipts, graph changes, population changes, coverage changes and selected
evidence revisions remain distinct. Late corrections refresh fixed earlier
views; exact record retries create no checkpoint. Qualified comparisons reuse
the existing NetworkX analyses, with explicit skips for incomplete adjacent
snapshots and analysis budgets.

The [tracking guide](docs/network-tracking.md) documents the strict input,
record idempotence, POSIX single-writer store and crash/retry boundaries. The
[invented fixture](examples/network-tracking/README.md) includes late time and
endpoint correction, evidence-only updates, coverage loss/recovery and restart.
Views do not advance with wall time; source subscriptions and automatic forecast
triggers remain separate work.

## Versioned language annotations: D4a

SocioLab now imports human or externally supplied structured annotations bound
to exact content and interaction revisions. It reports current, stale and
ambiguous decisions, supports explicit annotation-count network layers, and
compares a selected candidate method with a human reference.

```bash
python -m sociolab annotations inspect examples/annotations/events.json
python -m sociolab annotations evaluate examples/annotations/events.json --reference-method examples/annotations/human.method.json --candidate-method examples/annotations/model.method.json
python -m sociolab snapshot examples/annotations/events.json examples/annotations/conflict-before.view.json > annotated-conflict-before.snapshot.json
python -m sociolab snapshot examples/annotations/events.json examples/annotations/conflict-after.view.json > annotated-conflict-after.snapshot.json
python -m sociolab changes annotated-conflict-before.snapshot.json annotated-conflict-after.snapshot.json
```

The example's model-format labels are supplied fixtures; **no classifier runs**.
Topic disagreement stays separate from a person-directed insult. A correct
label with the wrong subject does not count as joint agreement. Missing,
uncertain or ambiguous classifications block an annotation view's completeness
before label/topic filtering. Graph results retain `UNVALIDATED_SOURCE_LABELS`
and `automatic_annotation_qualified=false`; agreement reports remain
`qualification_status="NOT_ESTABLISHED"`.

The [annotation guide](docs/annotations.md) documents the exact payloads, span
units, version binding, view completeness and evaluation denominators, with
[execution artifacts](docs/experiments/2026-11-27-annotations/validation.json).
Source bodies are not fetched or stored, and source-coded conflict remains a
separate view. **D4b automatic-provider qualification remains open**, as do
classifier execution, calibration and deployment validation. The separate
joint model below requires observed ordinal measurements; annotation counts
and event attributes are not automatically converted into those measurements.

## Network and ordinal-behavior coevolution: D5 implementation

The `coevolution` command fits one directed binary network together with one
declared ordinal behavior on a fixed actor panel. It uses the original cusna
CPU estimator with an explicit unconditional profile: six network evaluation
effects, three behavior evaluation effects, and a network and behavior rate
for each observed transition. Two waves have 11 free parameters; three have 13.

```bash
python -m pip install -e '.[saom]'
python -m sociolab coevolution inspect examples/coevolution/synthetic.panel.json examples/coevolution/synthetic.model.json
NUMBA_NUM_THREADS=2 python -m sociolab coevolution fit examples/coevolution/synthetic.panel.json examples/coevolution/synthetic.model.json --seed 1234 --n1 64 --nd 64 --n3 128 --batch2 16 --n2 2 2 2 2
```

The sample is invented and its reduced budgets exercise integration. The
model specification declares the behavior variable, integer bounds,
measurement reference and research question. Complete observations and both
declared scale endpoints are required. Results retain all rates/effects,
preprocessing constants, full numerical diagnostics and an audit of every
original CPU period path. Exit 0 means the numerical convergence screen
passed; exit 2 with a report means a valid nonconverged fit.

This is a **retrospective fit** of the supplied panel. Independent model
qualification, population validity, forecasting and causal identification
remain open. See the [joint-model guide](docs/coevolution.md) and
[execution evidence](docs/experiments/2026-11-27-coevolution/validation.json).

## Past-only behavior forecasts

The separate `forecast` command creates point predictions from a historical
panel, then scores a saved prediction against a separate future-behavior file.
It compares persistence, own-lag OLS, and own-lag OLS with an outgoing-neighbor
behavior feature, using original NumPy and NetworkX. No future network is an
input, and scoring does not refit the models.

```bash
python -m sociolab forecast create examples/forecast/synthetic.history.json examples/forecast/synthetic.spec.json > /path/to/private-prediction.json
python -m sociolab forecast score /path/to/private-prediction.json examples/forecast/synthetic.target.json
```

The example is invented. Prediction artifacts contain per-actor values and
should stay with private inputs; score reports contain aggregate errors and
hashes. The s50 case uses two known waves to predict one later wave under a
fixed protocol. Its recorded MAE is 0.64010 with the network feature versus
0.64072 with own history alone: only a small improvement on this one split.
It is a numerical teaching example with one retrospective holdout, not a
qualified population forecast or causal result. See the
[forecast guide and case](docs/behavior-forecast.md).

`forecast plan` fixes multiple one-step target periods from the initial history;
`forecast evaluate` checks saved histories, predictions and targets for every
planned period without refitting. It verifies full historical-prefix continuity
and reports per-origin, pooled and macro errors, preserving non-estimable folds.
The [multi-origin guide](docs/forecast-evaluation.md) includes an invented
execution example and the remaining [real-source admission limits](docs/forecast-source-admission.md).

`forecast journal-history` rebuilds complete historical inputs at one explicit
event-receipt cutoff, with per-wave snapshot and behavior evidence.
`forecast journal-target` binds separately received target behavior to the
saved prediction. Later corrections can create new analysis or target versions
while old cutoffs replay unchanged. The [journal forecast guide](docs/journal-forecast.md)
documents exact source-time spacing, fixed identities and the distinction
between receipt-prefix enforcement and independently verified availability.

For several origins with corrected historical data, `forecast journal-plan`
fixes every history and target receipt cutoff; `forecast journal-evaluate`
reconstructs those versions, verifies saved predictions/targets and reports
historical revisions alongside pooled/macro errors without refitting.
The [receipt-version evaluation guide](docs/journal-evaluation.md) keeps this
policy separate from immutable-prefix evaluation and documents its mechanical
target-availability checks.

## Real-source admission: Mauldin MSW cohort

The source inspector reads a locally supplied official-format ZIP and reports
file fingerprints, the full published roster, relation-specific item coverage,
source anomalies and recorded nomination turnover. It exposes aggregate counts
without exporting participant IDs, relationship lists or personal attributes.

```bash
python -m sociolab source mauldin inspect /path/to/UTA_Social_Networks_Social_Good.zip
```

The original archive was obtained on 2026-11-27. Its 145-row roster includes
study nonparticipants, item nonresponse and explicit program departures.
Documented empty responses, literal `NA` and missing ego rows remain distinct;
known incoming nominations survive an actor's missing outgoing response.
Friendship, academic discussion, professional influence and wave-1 knowing-of
are separate measurements. Recorded nomination turnover does not establish
relationship creation or dissolution when observation coverage or target
eligibility differs.

The inspected source remains **`NOT_ESTIMABLE`**: roster scope, malformed
nominations and missingness/composition need resolution before an empirical
model can be admitted. Conflicting source licensing statements are recorded
separately. No longitudinal panel or fitted estimate is created.
A completed audit exits 0 even with admission
blockers; malformed input exits 2. See the [source-admission guide](docs/mauldin-source-admission.md)
and [reproducible aggregate audit](docs/experiments/2026-11-27-mauldin/source-audit.json).

## Partial network observations: present, absent and unknown

The separate `sociolab.partial-network.v1` format declares one fixed actor roster
and two explicit directed observation sets per wave: `observed_present` and
`observed_absent`. Every other nonself dyad remains unknown. Missing outgoing
responses preserve separately observed incoming ties.

```bash
python -m sociolab partial inspect examples/partial/coverage.panel.json
python -m pip install -e '.[saom]'
python -m sociolab partial model examples/partial/coverage.panel.json
# A qualified partial-network panel can use the original conditional CPU model:
NUMBA_NUM_THREADS=2 python -m sociolab partial fit /path/to/study.partial-panel.json --seed 1234
```

`inspect` reports all nine present/absent/unknown endpoint transitions. It
separates observed tie differences from gains and losses of observation
coverage, without constructing a graph from unknown ties. The small synthetic
example retains **3 positive observations at both waves**, while showing one
observed addition, one observed removal, two coverage gains and two coverage
losses. Its purpose is to demonstrate the counting contract.

`model` inspects the actual cusna 0.1.0 initialization, masks and targets;
`fit` runs its original conditional three-effect CPU estimator and audits every
simulated period path. Unknown source cells remain NaN at the boundary.
Upstream zero/carry-forward initialization and latent simulations never become
new source observations. Both model operations require positive common
observation coverage and positive observed distance in each period.

This experimental profile supports one directed binary network on a fixed cohort. The
[fixed-parameter reference comparison](docs/experiments/2026-11-27-partial-network/cpu-reference-simulation.json)
detects differences in density and reciprocity moment means; independent
reference qualification remains open. Numerical
convergence does not qualify a study population, missingness mechanism,
forecast or causal effect. The Mauldin source audit still requires its
study-specific admission decisions. See the [partial-network guide](docs/partial-networks.md)
for the complete contract, supported scope, and
[recorded CPU qualification](docs/experiments/2026-11-27-partial-network/validation.json).

## Real recorded-contact case: Hypertext 2009

The reviewed-source study command compares two equal ten-hour windows in the
official contact log, with fixed node and reference-group identities and two
declared sensitivity checks. It uses the existing community/key-group adapters
and original NetworkX algorithms.

```bash
python -m sociolab study hypertext2009 /path/to/ht2009_contact_list.dat.gz
```

In the primary comparison, recorded pairs increase **757→920**, while the same
retrospective two-person group's normalized betweenness decreases
**0.156812→0.078703**. Cross-group pairs among first-window recording nodes
increase **472→566** under the one-bin rule, but decrease **181→172** with a
three-bin threshold. Community counts also require separating zero-record
singletons from multi-node groups.

These are **published-record graph results**. The fixed 113-ID universe and
reference group use the full archive, including later records; complete sensor
coverage, attendance, social ties, causal effects and prediction are not
established. The source-specific result does not change general snapshot
completeness requirements. See the [case study and figure](docs/recorded-contact-case.md),
[aggregate output](docs/experiments/2026-11-28-recorded-contact/case-report.json),
and [validation evidence](docs/experiments/2026-11-28-recorded-contact/validation.json).
The raw dataset is obtained separately under its official terms.

## Data contract: `sociolab.network.v1`

Every input declares `origin`, `relation`, ordered `actors`, **directed** `edges`, `time_index` and `source_revision`. The program computes its own SHA-256 over the full canonical input. The provided example is explicitly synthetic.

JSON object keys must be unique at every nesting level. The file readers
reject duplicate fields before schema validation, so conflicting origin,
network-completeness, or actor-behavior declarations cannot overwrite one
another during parsing.

- `contact_opportunity`: an eligible interaction edge, **not** actual communication.
- `trust`: a directed relationship, **not** evidence that the observer received or believed a message.
- `realized_transmission`: an externally supplied observed transmission edge at the declared instant; diffusion results **must never** be interpreted as additional observed transmissions.

The current adapter does not claim it can read a V19 state: `qigao/lean@master` has no V19 Python implementation. The generic event importer validates supplied records and their history; it does not independently authenticate their source or establish that an asserted event occurred.

The output records the dataset content hash and upstream package version; graph algorithms respect edge direction. There is no private memory, TELL body, claim text, or world-state writer.

## Upstream ownership and citations

- [NetworkX](https://networkx.org/) — BSD-3-Clause. Use the original library for graph metrics, reachability and related algorithms.
- [NDlib](https://github.com/GiulioRossetti/ndlib) — BSD-2-Clause. Use the original `ThresholdModel`, not a duplicate implementation. See Rossetti et al., *NDlib: a Python Library to Model and Analyze Diffusion Processes Over Complex Networks* (2017).
- The optional [cusna](https://pypi.org/project/cusna/0.1.0/) adapter runs the network-only CPU model described below. Future studies may evaluate [DoWhy](https://github.com/py-why/dowhy), [Mesa](https://github.com/mesa/mesa), or [MossSpider](https://github.com/pzivich/MossSpider). These future packages are not silently installed or presented as causal validation.

Upstream licenses remain with their packages. SocioLab's own redistribution license has not yet been selected.

## Engineering boundaries

No R or Lean toolchain, no vendored third-party source, no independent threshold engine, no installer/consumer test projects, and no new GitHub Actions workflow. Add real native tests to this repository's existing test suite, keep parameters explicit, reject invalid datasets and source claims, and preserve experimental provenance.

## Published observational reference: Zachary Karate Club

`python -m sociolab karate` calls **NetworkX's own** `karate_club_graph()` and
`betweenness_centrality()`. It reports 34 people, 78 undirected interaction
links, positive interaction-context weights, and the two 17-member
post-fission clubs, together with a deterministic content hash of the
upstream data and its literature citation. **No dataset is copied into this
repository.** The club labels are observed *after* the split, so they must
not be treated as baseline covariates for causal estimation. These edges
are **not** V19 directed trust or witnessed transmissions; this single
network snapshot contains no longitudinal treatment assignment.

Reference: Wayne W. Zachary (1977), *An Information Flow Model for Conflict
and Fission in Small Groups*, Journal of Anthropological Research 33,
452–473. Dataset documentation: 
https://networkx.org/documentation/stable/reference/generated/networkx.generators.social.karate_club_graph.html

Local execution on 2026-11-27 covers actual reference import and structural
computation with **Python 3.12.14 / NetworkX 3.7**, together with actual NDlib
6.0.1 diffusion after declaring its missing `six` dependency. Python 3.13
and other platforms still require separate execution. See the
[execution record](docs/validation-2026-11-27.md).

## Group-key-player reference (NetworkX only)

`python -m sociolab keyplayers --size 2` directly executes
`networkx.prominent_group(greedy=True)` and then uses
`networkx.group_betweenness_centrality` on the original undirected Zachary
Karate Club network. It records the selected actors, actual upstream group
betweenness, the rounded search score, and the published dataset SHA-256.
The greedy search is **not guaranteed optimal** and group betweenness is
**not** a universal measure of leadership or a causal effect. This does **not**
claim equivalence with Borgatti's complete KPP-Pos/KPP-Neg family.

This reference command remains restricted to the published **connected,
undirected** source graph. NetworkX 3.6.1 had a group-betweenness defect
on directed non-strongly-connected graphs, tracked in
[networkx/networkx#8559](https://github.com/networkx/networkx/issues/8559).
Upstream merged fixes [#8879](https://github.com/networkx/networkx/pull/8879),
[#8880](https://github.com/networkx/networkx/pull/8880) and
[#8882](https://github.com/networkx/networkx/pull/8882) before the **3.7**
release. The pinned **3.7** implementation has executed this project's
undirected reference tests. The new generic **scoring** API separately supports
directed and disconnected simple unit-strength graphs; generic **selection**
remains connected and undirected because the pinned selection routine fails
on some directed inputs. Nonempty exclusions are also outside its qualified
scope after an observed upstream inconsistency. Tests compare selection and scores with
the actual installed upstream version, rather than freezing a result from
the previous NetworkX 3.6.1 environment.

## Two-mode observational research: Davis Southern Women

`python -m sociolab davis` calls **NetworkX's original**
`davis_southern_women_graph()` and `bipartite.weighted_projected_graph()`.
It reports 18 observed participants, 14 social events, 89 recorded attendance
links, and 139 *derived* co-attendance pairs between participants. The 139
projected links are **not observed direct relationships**; their weights count
shared events, not trust or message deliveries. The output records the source
SHA-256, package version and Davis, Gardner & Gardner (1941) citation.

This is a two-mode observational study, **not a multi-wave longitudinal network**
and not a causal intervention. Never treat event participation as a directed
trust edge or infer social influence from co-attendance alone.

No data files or algorithms are vendored. The research example runs only
against the original NetworkX package and fails closed on unexpected source
partition or topology. This path has executed against NetworkX 3.7; the
supported-platform follow-up remains tracked in Issue #1.

## Topological communities vs observed factions

`python -m sociolab communities` runs the **upstream**
`networkx.community.greedy_modularity_communities` on the original Zachary
Karate Club topology and scores both the inferred partition and the published
**post-fission** club labels using `networkx.community.modularity`.

This is descriptive: the later outcome labels are **not used in detection**,
and a high topology modularity is neither a prospective prediction nor a
causal explanation for why people changed groups. The graph is unweighted
and undirected; no invented V19 messages, source-private claims, diffusion
engine or inferential estimator is involved. Reported score/partition can
change with the installed NetworkX release, so tests compare against the
**same version's actual upstream implementation** rather than a frozen
3.6.1 result. The NetworkX 3.7 tests and the actual NDlib 6.0.1 diffusion
tests have executed on the Linux/Python 3.12 environment recorded above.


## Versioned multi-wave social network observations (Python-only)

`python -m sociolab panel examples/synthetic_longitudinal.json` uses the
versioned `sociolab.longitudinal.v1` JSON contract. It requires a stable
ordered actor roster, strictly increasing observation times, distinct
revision IDs, explicitly observed directed ties, an explicit network
completeness flag at *every* wave, and behavior values (integer or `null`)
for every actor. Missing behavior is counted and never imputed. Missing
**network ties** are not assumed absent unless `network_complete=true`;
the report refuses incomplete network waves.

The upstream **NetworkX** library calculates density and weak components
for each wave. Edge addition/removal counts describe the reported ties,
not tie formation mechanisms. Each result binds the input SHA-256 and
NetworkX version. The example is **synthetic**; declared external dataset
references are not independently verified by this parser. It does not run
RSiena/SAOM, identify peer influence, estimate causal effects or treat
behavior similarity as social contagion. Use qualified longitudinal field
data and fit an actual upstream SAOM package before scientific claims.

## s50: genuine longitudinal source archive, numerical-example adapter

The three-wave **s50** friendship/alcohol example is documented by Oxford's
[Teenage Friends and Lifestyle Study excerpt](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.htm).
**The source explicitly warns that this 50-person excerpt is not a properly
bounded social network and is suitable only for numerical illustration.**
Do not use it to infer population-level selection, influence, or causality.

Get the archive from the [original source](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.zip)
and run:

```bash
python -m sociolab s50 /path/to/s50_data.zip
```

`src/sociolab/s50.py` reads the supplied ZIP with standard-library `zipfile`
without extracting or vendoring any copyrighted data. It requires three 50×50
directed friendship matrices, 50×3 ordinal alcohol observations, and the
published 113/116/122 tie-count vector. Every matrix is checked for invalid
nodes, missingness codes, self-nominations and unsupported values. The output
calls the **existing NetworkX** multi-wave structural metrics and records the
actual ZIP and member SHA-256 fingerprints.

The repository **does not bundle or silently download** the dataset, and its
synthetic ZIP-shaped tests do not constitute official-source acceptance.
The original Oxford ZIP was retrieved and parsed on 2026-11-27; its exact
archive and member fingerprints are in the
[execution record](docs/validation-2026-11-27.md). The parser always reports
`source_claim_verified=false`: each supplied archive still requires source
verification. s50 remains a **teaching/numeric compatibility** sample.
The optional upstream `cusna==0.1.0` CPU adapter has also executed on that
archive. Reduced budgets failed the convergence screen; full-default results
and their exact scope are recorded in the
[numerical validation record](docs/saom-numerical-validation.md).


## Experimental upstream Python SAOM adapter (CPU only)

The optional `saom` feature uses [cusna 0.1.0](https://pypi.org/project/cusna/0.1.0/) directly, under its MIT license. It does **not** translate RSiena's GPL code, reimplement an SAOM optimizer, or require R/Lean/CUDA:

```bash
python -m pip install -e '.[saom]'
python -m unittest discover -s tests/saom_runtime -v
python -m sociolab saom /path/to/s50_data.zip --format s50 --seed 4321 > fit.json
# For the versioned JSON contract, use: saom /path/to/panel.json --format panel
```

The first supported model is **network-only conditional method of moments** with `density`, `recip`, and `transTrip` effects, and `backend="cpu"`. The source actor order and directed edges are preserved in NumPy `(n,n)` matrices. Incompletely observed tie waves are **rejected**, never silently filled as absent edges.

cusna 0.1.0 automatically chooses a symmetric model when all observed
matrices are symmetric and exposes no documented constructor override.
SocioLab therefore rejects that case before estimation: reciprocal
observations of a directed relationship must not implicitly select paired
edge updates. Supporting those panels requires an explicit upstream
directed-mode API. Accepted panels retain directed-model semantics.

The base suite in `tests/` checks the input contract without requiring the
optional extra, including strict diagnostic boundaries and unusable matrices.
The separately invoked `tests/saom_runtime` suite requires the real installed
cusna package, checks the symmetric-mode rejection, compares an actual CPU
fit through SocioLab with the same direct upstream fit, and exercises CLI
nonconvergence. Missing optional dependencies fail that explicit suite;
no tests are conditionally skipped and no estimator is substituted.

The result preserves estimates, standard errors, individual and overall
convergence ratios, targets, simulated means, derivative matrix `D`, statistic
covariance `msf`, matrix ranks/condition numbers, conditional durations, and
the parameter trace. It also records package versions, dataset hash, effective
algorithm settings, seed, and simulation budgets. `n_simulations` counts
**full-panel replicates**. `rate_sd` is a standard deviation of simulated
durations, not a rate standard error or a rate per calendar day.

Numerical convergence requires `max(abs(tconv)) < 0.1` and
`0 <= tconv_max < 0.25`, following the
[RSiena manual's diagnostic guidance](https://www.stats.ox.ac.uk/~snijders/siena/RSiena_Manual.pdf#page=76).
SocioLab adopts strict boundaries for its screen; these are practical
guidelines, not a mathematical guarantee. Before classification it rejects
nonfinite/malformed diagnostics, nonpositive standard errors, rank-deficient
`D` or `msf`, and a nonsymmetric/non-positive-definite `msf`. `D` itself need
not be symmetric. No local optimizer, regularization, or retry is added.

The `saom` command writes the report as strict JSON and returns **0** for
`CONVERGED`, **2** for a valid `NOT_CONVERGED` result. Invalid inputs, unusable
diagnostics, and upstream failures raise errors. The Python functions return
valid nonconverged reports, so callers must inspect `convergence_status`.
Defaults are `n1=1000`, `nD=1000`, `n3=4000`, `batch2=256`, and
`n2=(40,40,60,80)`; CLI overrides are `--n1`, `--nd`, `--n3`, `--batch2`, and
`--n2`. Phase-3 sample size `n3` must exceed the three free effects to allow a
full-rank sample covariance.

`convergence_is_validated=true` means **numerical moment matching only**.
For this network-only command, `independent_reference_validated`, `behavior_coevolution_fitted`,
`causal_effect_identified`, and `population_boundary_qualified` remain false.
Reduced simulation budgets are numerical smoke checks. s50 remains an
**incompletely bounded teaching subset**, unsuitable for empirical social
influence claims.

**Runtime execution is verified on Linux/Python 3.12.14** with cusna 0.1.0:
the CPU engine compiles and the estimator returns through the adapter.
The [numerical validation record](docs/saom-numerical-validation.md) separates
full-budget convergence evidence from an informational comparison with
upstream-published RSiena coefficients. The separately implemented
[joint network/behavior profile](docs/coevolution.md) has its own input,
parameter and rate contracts. Independent reference acceptance, a qualified
empirical population, and Python 3.13/platform coverage remain open.
See the [execution record](docs/validation-2026-11-27.md) and
SocioLab [Issue #2](https://github.com/qigao/SocioLab/issues/2).
