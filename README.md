# SocioLab

**Python-first social-network research built on existing open-source implementations.**

SocioLab runs established network analysis and diffusion algorithms directly from their upstream Python packages. It does **not** fork network theory implementations, use Lean or R as a runtime, or simulate a second authoritative Agent world.

## Baseline and scope

- New, independently initialized repository: `qigao/SocioLab` (`master`).
- Migration baseline: [`qigao/lean@master`](https://github.com/qigao/lean/tree/e5be0cf3fb0f57d4ea49093ecab429c5a862615e) at `e5be0cf3fb0f57d4ea49093ecab429c5a862615e` (contains only `LICENSE`). **No unmerged Lean PR files are copied.**
- Initial engines: **NetworkX 3.7** (directed graph and structural analysis) and **NDlib 6.0.1** (upstream threshold diffusion). Other Python packages are added only when a real study needs them.
- Outputs are labeled `REFERENCE_MODEL_RESULT`, **not** observations of genuine message delivery, estimated causal effects, or verified sociological laws.

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

## Data contract: `sociolab.network.v1`

Every input declares `origin`, `relation`, ordered `actors`, **directed** `edges`, `time_index` and `source_revision`. The program computes its own SHA-256 over the full canonical input. The provided example is explicitly synthetic.

- `contact_opportunity`: an eligible interaction edge, **not** actual communication.
- `trust`: a directed relationship, **not** evidence that the observer received or believed a message.
- `realized_transmission`: an externally supplied observed transmission edge at the declared instant; diffusion results **must never** be interpreted as additional observed transmissions.

The current adapter does not claim it can read a V19 state: `qigao/lean@master` has no V19 Python implementation. A future external dataset importer must prove identity, revision, event semantics, and privacy independently before claiming to be source-backed.

The output records the dataset content hash and upstream package version; graph algorithms respect edge direction. There is no private memory, TELL body, claim text, or world-state writer.

## Upstream ownership and citations

- [NetworkX](https://networkx.org/) — BSD-3-Clause. Use the original library for graph metrics, reachability and related algorithms.
- [NDlib](https://github.com/GiulioRossetti/ndlib) — BSD-2-Clause. Use the original `ThresholdModel`, not a duplicate implementation. See Rossetti et al., *NDlib: a Python Library to Model and Analyze Diffusion Processes Over Complex Networks* (2017).
- Future studies may evaluate [DoWhy](https://github.com/py-why/dowhy), [Mesa](https://github.com/mesa/mesa), [MossSpider](https://github.com/pzivich/MossSpider), and Python longitudinal SAOM implementations. None are silently installed, treated as equivalent to RSiena/tmlenet, or presented as causal validation.

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

Local acceptance (Python 3.13.5 / installed NetworkX 3.6.1) covers actual
reference import and structural computation. The **pinned** NetworkX 3.7
and NDlib 6.0.1 environment still requires independent execution; the two
NDlib-dependent tests currently fail with `ModuleNotFoundError` in this
offline environment. They are not skipped or counted as passes.

## Group-key-player reference (NetworkX only)

`python -m sociolab keyplayers --size 2` directly executes
`networkx.prominent_group(greedy=True)` and then uses
`networkx.group_betweenness_centrality` on the original undirected Zachary
Karate Club network. It records the selected actors, actual upstream group
betweenness, the rounded search score, and the published dataset SHA-256.
The greedy search is **not guaranteed optimal** and group betweenness is
**not** a universal measure of leadership or a causal effect. This does **not**
claim equivalence with Borgatti's complete KPP-Pos/KPP-Neg family.

The experiment is intentionally restricted to the published **connected,
undirected** source graph. NetworkX 3.6.1 had a group-betweenness defect
on directed non-strongly-connected graphs, tracked in
[networkx/networkx#8559](https://github.com/networkx/networkx/issues/8559).
Upstream merged fixes [#8879](https://github.com/networkx/networkx/pull/8879),
[#8880](https://github.com/networkx/networkx/pull/8880) and
[#8882](https://github.com/networkx/networkx/pull/8882) before the **3.7**
release. This project's **pinned 3.7 combination has not yet been executed**;
we do not infer directed-algorithm support from the older local tests, and
never silently convert a directed trust graph to an undirected one. Any
published key-player pair/score from the local NetworkX 3.6.1 environment is
version-specific until 3.7 is independently qualified.

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
partition or topology. This independently tested path does not lift the
separate NDlib 6.0.1 / NetworkX 3.7 admission blocker in Issue #1.

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
3.6.1 result. The pinned NetworkX 3.7/NDlib 6.0.1 combination still needs
independent real installation/acceptance.


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
synthetic ZIP-shaped tests do not constitute official-source acceptance. Until
an original-source archive is actually supplied, the source authenticity
remains unverified; even with such an archive, s50 is only a **teaching/numeric
compatibility** sample. SocioLab has no local SAOM algorithm. An optional adapter for upstream `cusna==0.1.0` is available as experimental code, but its real model fitting has **not** been run/accepted on this environment.


## Experimental upstream Python SAOM adapter (CPU only)

The optional `saom` feature uses [cusna 0.1.0](https://pypi.org/project/cusna/0.1.0/) directly, under its MIT license. It does **not** translate RSiena's GPL code, reimplement an SAOM optimizer, or require R/Lean/CUDA:

```bash
python -m pip install -e '.[saom]'
python - <<'PY'
from sociolab.saom import fit_s50_network_reference
print(fit_s50_network_reference('/path/to/s50_data.zip'))
PY
```

The first supported model is **network-only conditional method of moments** with `density`, `recip`, and `transTrip` effects, and `backend="cpu"`. The source actor order and directed edges are preserved in NumPy `(n,n)` matrices. Incompletely observed tie waves are **rejected**, never silently filled as absent edges.

The result identifies upstream package version, dataset hash, simulation budgets, estimates and convergence diagnostics, but always reports `behavior_coevolution_fitted=false`, `causal_effect_identified=false`, `population_boundary_qualified=false`. Reduced simulation budgets are numerical smoke checks, not inferential acceptance. s50 remains an **incompletely bounded teaching subset**, unsuitable for empirical social influence claims.

**Admission is blocked**: `cusna` is not installed here and package network access is unavailable. Only the input contract / matrix adapter has passed local tests; the actual `MomEstimator` run, CPU compilation and fitting are **NOT** qualified. The optional SAOM package itself is early-stage and published Python 3.13 compatibility also requires real testing. See SocioLab [Issue #2](https://github.com/qigao/SocioLab/issues/2).
