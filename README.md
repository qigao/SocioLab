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
undirected** source graph: NetworkX 3.6.1 / development 3.7 has a documented
group-betweenness defect on directed non-strongly-connected graphs; see
[networkx/networkx#8559](https://github.com/networkx/networkx/issues/8559).
There is no silent conversion of a directed trust network to an undirected
social network.
