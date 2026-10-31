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