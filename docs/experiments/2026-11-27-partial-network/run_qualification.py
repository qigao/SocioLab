"""Reproduce a bounded missing-network CPU qualification against retained assets.

Supply the 17 pinned upstream files listed in source-review.json beneath
--reference-root. No download, R runtime, source-data vendoring, solver copy,
automatic retry, seed search, or empirical-population admission is performed.
See docs/partial-networks.md for commands and the limits of this reference.
"""

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
from statistics import NormalDist
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from sociolab.partial_panels import PartialNetworkPanel, PartialNetworkWave
from sociolab.partial_saom import (
    _record_conditional_batch, partial_network_model_report,
    partial_saom_wave_matrices,
)

PIN = "313c3d2623c99ed15c1eb6fe713593c6d3915d1d"
UPSTREAM = "https://github.com/artemmaltsev74-techcom/cusna/blob/" + PIN
EFFECTS = ["density", "recip", "transTrip"]
HERE = Path(__file__).resolve().parent


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                              allow_nan=False) + "\n", encoding="utf-8")


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def source_hashes():
    paths = ["src/sociolab/partial_panels.py", "src/sociolab/partial_changes.py",
             "src/sociolab/partial_saom.py", "src/sociolab/saom.py",
             "src/sociolab/cli.py", str(Path(__file__).relative_to(ROOT))]
    return {path: digest(ROOT / path) for path in paths}


def load_inputs(reference_root):
    manifest = json.loads((HERE / "source-review.json").read_text(encoding="utf-8"))
    if manifest["source_commit"] != PIN or version("cusna") != "0.1.0":
        raise ValueError("qualification requires the pinned cusna 0.1.0 reference")
    for item in manifest["files"]:
        path = reference_root / item["repository_path"]
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError("reference fingerprint mismatch: " + item["repository_path"])

    from cusna.saom import data, mom, cpu, stats
    installed = {}
    for module in (data, mom, cpu, stats):
        path = Path(module.__file__)
        original = reference_root / "prototype/cusna/saom" / path.name
        if path.read_bytes().replace(b"\r\n", b"\n") != original.read_bytes().replace(b"\r\n", b"\n"):
            raise ValueError("installed source differs from reference: " + path.name)
        installed[path.name] = {"installed_sha256": digest(path),
                                "pinned_sha256": digest(original),
                                "equal_after_newline_normalization": True}

    out = reference_root / "prototype/bench/out"
    actors = tuple(f"actor-{index:03d}" for index in range(1, 51))
    waves = []
    for number in (1, 2, 3):
        path = out / f"s50miss-net{number}.txt"
        raw = np.loadtxt(path)
        if raw.shape != (50, 50) or not np.isin(raw, [0, 1, 9]).all() or np.any(np.diag(raw) != 0):
            raise ValueError("reference must contain 50x50 0/1/9 matrices with zero diagonal")
        pairs = {state: tuple((actors[i], actors[j]) for i in range(50)
                             for j in range(50) if i != j and raw[i, j] == state)
                 for state in (0, 1)}
        waves.append(PartialNetworkWave(number - 1, "sha256:" + digest(path), pairs[1], pairs[0]))
    panel = PartialNetworkPanel(
        dataset_id="s50-artificial-missing-network-reference", origin="external_observation",
        source_reference=UPSTREAM + "/prototype/bench/rsiena_missing.R", actors=actors,
        relation="friendship_nomination",
        population_definition="Fixed 50 matrix indices in the published s50 teaching excerpt; numerical reference only, not a qualified empirical population.",
        observation_definition="Retain original 0/1 cells as explicit observations and artificial code 9 as unknown; exclude the diagonal; do not infer response or membership from missingness.",
        waves=tuple(waves),
    )
    model = partial_network_model_report(panel)
    targets = rows(out / "miss_targets.csv")
    estimates = rows(out / "miss_estimates.csv")
    distances = rows(out / "miss_distances.csv")
    if ([row["param"] for row in targets] != EFFECTS
            or [row["param"] for row in estimates] != EFFECTS
            or [int(row["period"]) for row in distances] != [1, 2]):
        raise ValueError("reference names or period order differ from the documented profile")
    np.testing.assert_array_equal(model["targets"], [float(row["target"]) for row in targets])
    np.testing.assert_array_equal([p["conditional_target_distance"] for p in model["periods"]],
                                  [int(row["distance"]) for row in distances])
    provenance = {
        "kind": "PARTIAL_REFERENCE_INPUT_VERIFICATION", "upstream_commit": PIN,
        "dataset_hash": panel.content_hash, "source_reference": panel.source_reference,
        "source_manifest_sha256": digest(HERE / "source-review.json"),
        "reference_file_count_verified": len(manifest["files"]),
        "installed_source": installed, "source_sha256": source_hashes(),
        "transformation": "row/column order becomes actor-001..actor-050; offdiagonal 1 -> observed_present, 0 -> observed_absent, 9 -> unknown; original matrix SHA256 becomes wave source_revision",
        "input_matrix_sha256": [wave.source_revision for wave in panel.waves],
        "targets_match_retained_reference_exactly": True,
        "distances_match_retained_reference_exactly": True,
        "raw_reference_data_committed": False, "population_boundary_qualified": False,
        "empirical_admitted": False, "independent_reference_validated": False,
        "runtime_versions": {name: version(name) for name in ("cusna", "numpy", "numba")},
        "python": sys.version.split()[0], "numba_num_threads": os.environ.get("NUMBA_NUM_THREADS"),
    }
    return panel, model, provenance, out


def run_cli(panel, action, extra=()):
    with TemporaryDirectory(prefix="sociolab-partial-reference-") as temporary:
        path = Path(temporary) / "reference.panel.json"
        write(path, panel.to_dict())
        command = [sys.executable, "-m", "sociolab", "partial", action, str(path), *extra]
        started = datetime.now(timezone.utc).isoformat()
        begin = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, capture_output=True)
        elapsed = time.perf_counter() - begin
    execution = {"action": action, "command": ["python", "-m", "sociolab", "partial", action,
                                              "<temporary-reference.panel.json>", *extra],
                 "started_utc": started, "wall_time_seconds": elapsed, "exit_code": result.returncode,
                 "stdout_sha256": sha256(result.stdout).hexdigest(),
                 "stderr_sha256": sha256(result.stderr).hexdigest(),
                 "source_sha256": source_hashes(), "dataset_hash": panel.content_hash,
                 "numba_num_threads": os.environ.get("NUMBA_NUM_THREADS")}
    return result, execution


def inspect(panel, model, provenance, output):
    write(output / "reference-provenance.json", provenance)
    for action, expected, filename in (("inspect", model["input"], "reference-observations.json"),
                                       ("model", model, "reference-model.json")):
        result, execution = run_cli(panel, action)
        if result.returncode != 0 or result.stderr or json.loads(result.stdout) != expected:
            raise ValueError("actual CLI inspection differs from API report")
        (output / filename).write_bytes(result.stdout)
        write(output / ("reference-" + action + "-execution.json"), execution)
    print(json.dumps({"mode": "inspect", "targets": model["targets"],
                      "dataset_hash": panel.content_hash}), flush=True)


def simulate(panel, model, provenance, reference, output):
    from cusna.saom.data import SaomData
    from cusna.saom.cpu import MAX_STEPS
    from cusna.saom.mom import MomEstimator
    from cusna.saom.stats import EffectSpec

    estimates = rows(reference / "miss_estimates.csv")
    theta = np.array([float(row["est"]) for row in estimates])
    with (reference / "miss_sf.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader) != ["V1", "V2", "V3"]:
            raise ValueError("unexpected retained simulation columns")
        reference_dev = np.array([[float(value) for value in row] for row in reader])
    if reference_dev.shape != (3000, 3) or not np.isfinite(reference_dev).all():
        raise ValueError("expected exactly 3000 finite retained centered statistic rows")
    duration_rows = rows(reference / "miss_ntim.csv")
    if [int(row["period"]) for row in duration_rows] != [1, 2]:
        raise ValueError("unexpected reference duration periods")
    estimator = MomEstimator(SaomData(partial_saom_wave_matrices(panel)),
                             effects=[EffectSpec(name) for name in EFFECTS],
                             conditional=True, backend="cpu", seed=2024, n3=3000)
    if estimator.param_names != EFFECTS:
        raise ValueError("unexpected CPU effect order")
    np.testing.assert_array_equal(estimator.targets, model["targets"])
    paths = [{"period_index": i, "target_distance": period["conditional_target_distance"],
              "path_count": 0, "batch_calls": 0, "max_steps": 0,
              "min_duration": float("inf"), "max_duration": 0.0}
             for i, period in enumerate(model["periods"])]
    original = estimator._cpu

    def observe(*args, **kwargs):
        period = kwargs["period"]
        if kwargs["conditional"] is not True or kwargs["target_dist"] != paths[period]["target_distance"]:
            raise ValueError("upstream changed conditional simulation scope")
        result = original(*args, **kwargs)
        _record_conditional_batch(paths, result, n_sims=args[3], period=period,
                                  target=paths[period]["target_distance"], max_steps=MAX_STEPS)
        return result

    estimator._cpu = observe
    started = datetime.now(timezone.utc).isoformat()
    begin = time.perf_counter()
    statistics, _, _, durations = estimator.simulate(theta, 3000)
    elapsed = time.perf_counter() - begin
    if (statistics.shape != (3000, 3) or durations.shape != (3000, 2)
            or not np.isfinite(statistics).all() or not np.isfinite(durations).all()
            or estimator.n_sims != 3000 or any(item["path_count"] != 3000 for item in paths)):
        raise ValueError("invalid CPU reference simulation output")
    cpu_dev = statistics - estimator.targets
    cpu_var, reference_var = cpu_dev.var(axis=0, ddof=1), reference_dev.var(axis=0, ddof=1)
    mcse = np.sqrt(cpu_var / 3000 + reference_var / 3000)
    if np.any(mcse <= 0):
        raise ValueError("reference comparison has zero Monte Carlo uncertainty")
    difference = cpu_dev.mean(axis=0) - reference_dev.mean(axis=0)
    critical = NormalDist().inv_cdf(1 - 0.05 / (2 * len(EFFECTS)))
    comparisons = [{"effect": name, "cpu_mean_deviation": float(cpu_dev[:, i].mean()),
                    "reference_mean_deviation": float(reference_dev[:, i].mean()),
                    "cpu_sample_variance": float(cpu_var[i]),
                    "reference_sample_variance": float(reference_var[i]),
                    "mean_difference": float(difference[i]), "difference_mcse": float(mcse[i]),
                    "standardized_difference": float(difference[i] / mcse[i]),
                    "simultaneous_ci": [float(difference[i] - critical * mcse[i]),
                                        float(difference[i] + critical * mcse[i])],
                    "interval_includes_zero": bool(abs(difference[i]) <= critical * mcse[i])}
                   for i, name in enumerate(EFFECTS)]
    result = {
        "kind": "PARTIAL_FIXED_PARAMETER_CPU_REFERENCE_COMPARISON", "provenance": provenance,
        "seed": 2024, "reference_simulation_seed": 654, "theta": theta.tolist(),
        "effect_names": EFFECTS, "targets": estimator.targets.tolist(),
        "cpu_replicates": 3000, "retained_reference_replicates": 3000,
        "reference_sf_column_binding": dict(zip(["V1", "V2", "V3"], EFFECTS)),
        "comparison": comparisons, "family_alpha": 0.05, "normal_critical_value": critical,
        "uncertainty_method": "independent sample mean difference; sqrt(var_cpu/3000+var_reference/3000), sample variances ddof=1; Bonferroni normal approximation for three means",
        "all_intervals_include_zero": all(row["interval_includes_zero"] for row in comparisons),
        "cpu_deviation_covariance": np.cov(cpu_dev.T).tolist(),
        "reference_deviation_covariance": np.cov(reference_dev.T).tolist(),
        "durations": [{"period": i + 1, "cpu_mean": float(durations[:, i].mean()),
                       "reference_mean": float(row["mean_ntim"]),
                       "difference": float(durations[:, i].mean() - float(row["mean_ntim"]))}
                      for i, row in enumerate(duration_rows)],
        "duration_uncertainty_test_performed": False,
        "cpu_path_audit": {"all_paths_reached_target": True, "step_cap": int(MAX_STEPS),
                           "total_period_paths": 6000, "periods": paths},
        "started_utc": started, "wall_time_seconds": elapsed,
        "model_fitted": False, "equivalence_test": False,
        "independent_reference_validated": False, "empirical_admitted": False,
        "limits": ["One retained theta and three moment means; no equivalence margin or full distribution/estimator validation.",
                   "Monte Carlo intervals use an independent-replicate normal approximation, not observational or parameter uncertainty.",
                   "Reference RSiena version, full session, overall convergence and full fitted covariance are not retained.",
                   "Reference duration samples/variances are unavailable; duration comparisons are descriptive only.",
                   "Artificially missing s50 excerpt is not an admitted empirical population or a validation of arbitrary missingness."],
    }
    write(output / "cpu-reference-simulation.json", result)
    print(json.dumps({"mode": "simulate", "all_intervals_include_zero": result["all_intervals_include_zero"],
                      "standardized_differences": [row["standardized_difference"] for row in comparisons],
                      "wall_time_seconds": elapsed}), flush=True)


def fit(panel, output):
    extra = ("--seed", "1234", "--n1", "1000", "--nd", "1000", "--n3", "4000",
             "--batch2", "256", "--n2", "40", "40", "60", "80")
    result, execution = run_cli(panel, "fit", extra)
    (output / "s50-missing-seed1234-fit.json").write_bytes(result.stdout)
    (output / "s50-missing-seed1234-stderr.log").write_bytes(result.stderr)
    write(output / "s50-missing-seed1234-execution.json", execution)
    if result.returncode not in (0, 2) or result.stderr:
        raise ValueError("CLI fit failed; inspect preserved stdout/stderr and execution record")
    report = json.loads(result.stdout)
    if report.get("kind") != "PARTIAL_NETWORK_SAOM_FIT":
        raise ValueError("CLI did not produce a genuine partial-network fit")
    print(json.dumps({"mode": "fit", "exit_code": result.returncode,
                      "convergence_status": report["convergence_status"],
                      "max_abs_tconv": report["max_abs_tconv"], "tconv_max": report["tconv_max"],
                      "wall_time_seconds": execution["wall_time_seconds"]}), flush=True)


def verify(output):
    report = json.loads((output / "s50-missing-seed1234-fit.json").read_text())
    execution = json.loads((output / "s50-missing-seed1234-execution.json").read_text())
    model = json.loads((output / "reference-model.json").read_text())
    diagnostics = report["diagnostics"]
    derivative, covariance = np.array(diagnostics["D"]), np.array(diagnostics["msf"])
    deviation = np.array(diagnostics["sim_means"]) - diagnostics["targets"]
    np.linalg.cholesky(covariance)
    inverse = np.linalg.inv(derivative)
    parameter_covariance = inverse @ covariance @ inverse.T
    if np.any(np.diag(parameter_covariance) <= 0):
        raise ValueError("nonpositive parameter variance")
    se = np.sqrt(np.diag(parameter_covariance))
    ratios = deviation / np.sqrt(np.diag(covariance))
    overall = float(np.sqrt(deviation @ np.linalg.solve(covariance, deviation)))
    np.testing.assert_allclose(se, report["standard_errors"], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(ratios, report["tconv"], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(overall, report["tconv_max"], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(max(abs(ratios)), report["max_abs_tconv"], rtol=1e-12, atol=1e-12)
    converged = max(abs(ratios)) < .1 and 0 <= overall < .25
    if report["convergence_status"] != ("CONVERGED" if converged else "NOT_CONVERGED"):
        raise ValueError("inconsistent convergence label")
    if execution["exit_code"] != (0 if converged else 2):
        raise ValueError("inconsistent CLI convergence exit status")
    if execution["stdout_sha256"] != digest(output / "s50-missing-seed1234-fit.json"):
        raise ValueError("saved fit bytes differ from CLI output")
    for key in ("dataset_hash", "input", "periods", "targets", "initialization", "missingness_policy"):
        if report[key] != model[key]:
            raise ValueError("fit modified inspected input/model: " + key)
    expected_sims = report["n1"] + len(report["n2"]) * report["nD"] + sum(report["n2"]) * report["batch2"] + report["n3"]
    audit = report["cpu_path_audit"]
    if (report["n_simulations"] != expected_sims
            or audit["total_period_paths"] != expected_sims * len(report["periods"])
            or any(item["path_count"] != expected_sims or not 0 < item["max_steps"] < audit["step_cap"]
                   or not 0 < item["min_duration"] <= item["max_duration"] for item in audit["periods"])):
        raise ValueError("inconsistent path budget or duration summary")
    for key in ("empirical_admitted", "population_boundary_qualified", "source_claim_verified",
                "independent_reference_validated", "causal_effect_identified", "behavior_coevolution_fitted"):
        if report[key] is not False:
            raise ValueError("qualification was improperly elevated: " + key)
    result = {"kind": "PARTIAL_FIT_ARITHMETIC_VERIFICATION", "status": "PASSED",
              "fit_sha256": digest(output / "s50-missing-seed1234-fit.json"),
              "standard_errors_recomputed": se.tolist(), "tconv_recomputed": ratios.tolist(),
              "overall_tconv_recomputed": overall, "parameter_covariance": parameter_covariance.tolist(),
              "fit_matches_inspected_model": True, "expected_full_panel_replicates": expected_sims,
              "expected_period_paths": expected_sims * len(report["periods"]),
              "numerical_convergence_screen_passed": bool(converged),
              "conditional_duration_sd_recomputed": False,
              "scope": "arithmetic recomputation from saved diagnostics and consistency of saved path audit; no simulation replay or independent empirical qualification"}
    write(output / "s50-missing-seed1234-verification.json", result)
    print(json.dumps({"mode": "verify", "status": "PASSED", "converged": bool(converged)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "simulate", "fit", "verify"))
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "verify":
        verify(args.output)
        return
    if args.reference_root is None:
        parser.error("--reference-root is required for inspect, simulate and fit")
    panel, model, provenance, reference = load_inputs(args.reference_root)
    if args.mode == "inspect":
        inspect(panel, model, provenance, args.output)
    elif args.mode == "simulate":
        simulate(panel, model, provenance, reference, args.output)
    else:
        fit(panel, args.output)


if __name__ == "__main__":
    main()
