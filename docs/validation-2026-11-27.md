# Upstream runtime and input-contract validation — 2026-11-27

## Scope and revisions

The review baseline was `b54dad8b3f8db45ab5d4f6ce987adaacdd898ee8` on
`master`. This record accompanies the `fix/upstream-runtime-contracts`
changes; the pull request records the exact submitted HEAD and verification.
All results below are local execution results. The repository has no Actions
workflow or CI run for this change.

This work fixes dependency declaration, directed-model admission, ambiguous
JSON input, and NDlib random-state isolation. It introduces no replacement
network algorithm, estimator, installer/consumer project, or workflow.

## Executed environment

| Component | Version |
| --- | --- |
| OS / architecture | Linux / x86_64 |
| Python | 3.12.14 |
| NetworkX | 3.7 |
| NDlib | 6.0.1 |
| six | 1.17.0 |
| NumPy | 2.3.5 |
| cusna | 0.1.0 |
| Numba / llvmlite | 0.68.1 / 0.50.0 |
| SciPy | 1.17.0 |
| igraph | 1.0.0 |
| dynetx / netdispatch | 0.3.2 / 0.1.0 |
| Bokeh / future / tqdm | 3.10.2 / 1.0.0 / 4.70.1 |

Dependencies were resolved into an isolated review virtual environment using
the existing runtime's NumPy/SciPy packages. The source was executed with
`PYTHONPATH=src`; these are source-runtime tests, not distribution-installation
acceptance. Python 3.13, Windows, and macOS have not been qualified by this run.

## Tests and reproduced defects

From the repository root, with the dependencies above available:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src NUMBA_NUM_THREADS=2 python -m unittest discover -s tests/saom_runtime -v
```

The optional CPU test used a writable scratch `NUMBA_CACHE_DIR`. The recorded
final runs reused compiled kernels; cold compilation takes additional time.

| Check | Result |
| --- | --- |
| Base suite after fixes | **49/49 PASS**, no skips |
| Explicit optional SAOM runtime suite | **2/2 PASS**, no skips |
| Original s50 ZIP → structural report | Success |
| Original s50 ZIP → actual cusna CPU fit | Call succeeds; convergence unvalidated |
| `git diff --check` | Pass |

### NDlib runtime dependency

Installing the baseline's declared dependencies and the SAOM extra gave
**42 PASS / 2 ERROR**: NDlib 6.0.1 imports `six` from its core
`DiffusionModel`, but its package metadata omits that requirement.
After adding `six==1.17.0`, the original **44/44** tests passed. The manifest
now declares this dependency; the five added base regressions bring the
suite to 49 tests.

### Directed SAOM admission

The pinned upstream
[SaomData implementation](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/data.py#L194-L199)
infers a symmetric model when all observed waves are symmetric. That selects
[paired edge changes](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/cpu.py#L512-L527),
which conflicts with SocioLab's directed-relation contract even when all
observed nominations happen to be reciprocal.

The adapter now rejects that actual upstream mode before constructing the
estimator. cusna 0.1.0 has no documented constructor override; SocioLab does
not alter its inferred state. This is an explicit unsupported-input boundary,
not support for fitting reciprocal directed panels.

The optional suite verifies this rejection and runs a genuine seeded CPU
fit on upstream `synthetic_panel(20, mean_degree=4, change_frac=0.25, seed=17)`.
It compares the adapter's coefficients, standard errors, convergence
diagnostics, and simulation count against a separate direct upstream fit
using the same data and settings. No fixed scientific coefficient oracle,
stubbed estimator, or conditional dependency skip is used.

### JSON and diffusion execution

Duplicate JSON keys now fail during decoding, before field validation or
hashing. Regressions cover conflicting `origin`, conflicting
`network_complete`, and duplicate actor behavior overwriting `null`.

NDlib seeds NumPy's process-global generator. Each public threshold report
now executes in a fresh Python subprocess using the same interpreter and
the original upstream model. Serial and concurrent real-model tests verify
unchanged caller RNG state and directed results. A genuine upstream seed
error verifies that child failure and stderr reach the caller. The caller's
working directory is preserved. Each report pays the interpreter/import
startup cost; there is no shared process pool or global-RNG save/restore.

## Original Oxford s50 archive

The original archive was downloaded directly from
[Oxford](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.zip) on
2026-11-27. Its size was **7,358 bytes**, and the unmodified archive was read
by the existing s50 adapter. It is not bundled in this repository.

Archive SHA-256:

```text
57dfd0d2a5f924f36cb1ff0c70d2e3a83370e142400af4edc28f4c5c29fea955
```

| Required member | SHA-256 |
| --- | --- |
| `s50-network1.dat` | `7c20670c39b9ca25cf7b0bbc00c81621ababfaa6f97b2344533528d2fb9d7a94` |
| `s50-network2.dat` | `d0ed7908e695445069162dccddb483dddb98a34f2b3085fe19e34af8028b9aa2` |
| `s50-network3.dat` | `6f0f230734ce432d5b229cade3bbcfe8a0ba925b63dfdf89ab79e9d544db7fd8` |
| `s50-alcohol.dat` | `84eb97edab4de88c8ab9185db3aa1dc329548e04be11fc73f7bb74a531bf1966` |

Normalized panel SHA-256:

```text
dd71009fe43cf7a32538c740d3b67f73bb1e601bb18146677b384d7d7213b001
```

| Wave | Directed ties | Added since prior wave | Removed since prior wave |
| --- | ---: | ---: | ---: |
| 1 | 113 | — | — |
| 2 | 116 | 59 | 56 |
| 3 | 122 | 56 | 50 |

This supersedes the earlier inability to retrieve the original archive.
It does not turn arbitrary caller-supplied ZIP files into authenticated
sources: the parser continues to report `source_claim_verified=false`.
The source itself [restricts this excerpt to numerical illustration](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.htm)
because its network population is not properly delineated.

## Actual CPU fit on s50

With `NUMBA_NUM_THREADS=2`, the following call executes the upstream engine
through the updated adapter:

```python
from sociolab.saom import fit_s50_network_reference

report = fit_s50_network_reference(
    "/path/to/s50_data.zip",
    seed=1234,
    n1=64,
    nD=64,
    n3=128,
    batch2=16,
    n2=(2, 2, 2, 2),
)
```

The report returned **576 simulations**, effects `density`, `recip`, and
`transTrip`, and `tconv_max=5.259294932616379`. These deliberately small
budgets did not establish convergence. The call demonstrates runtime
integration; its coefficients are not accepted estimates for interpretation.
`convergence_is_validated`, `behavior_coevolution_fitted`,
`population_boundary_qualified`, and `causal_effect_identified` remain false.

## Remaining work

- [Issue #1](https://github.com/qigao/SocioLab/issues/1): qualify the remaining
  declared Python runtime and platforms. The actual Linux/Python 3.12
  NetworkX/NDlib execution blocker is resolved by this change.
- [Issue #2](https://github.com/qigao/SocioLab/issues/2): define numerical
  reference and convergence acceptance, preserve full experiment evidence,
  and obtain an explicit upstream directed-mode API for reciprocal panels.
  Behavior coevolution and scientific influence inference remain outside
  the current network-only adapter.
- [Issue #3](https://github.com/qigao/SocioLab/issues/3): qualify a real cohort's
  actor roster, relationship layers, dyad missingness, and membership changes
  before empirical estimation. The Mauldin source has not been admitted by
  this work.
