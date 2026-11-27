"""Reproduce the retrospective CPU fit and published fixed-theta comparison.

Requires a caller-supplied original Oxford s50 ZIP and the pinned cusna source
checkout. No R runtime, data download, copied solver, or automatic fit retry.
Run each mode from the repository root; see docs/coevolution.md.
"""

from datetime import datetime, timezone
import csv
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
from statistics import NormalDist
import subprocess
import sys
import time
import argparse

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from sociolab.coevolution import _record_cpu_batch, coevolution_model_report
from sociolab.coevolution_input import load_coevolution_spec, validate_coevolution_input
from sociolab.s50 import load_s50_archive
from sociolab.saom import _assess_mom_diagnostics, saom_wave_matrices

PIN = "313c3d2623c99ed15c1eb6fe713593c6d3915d1d"
UPSTREAM = "https://github.com/artemmaltsev74-techcom/cusna/blob/" + PIN
MODEL = ROOT / "examples/coevolution/s50.model.json"


def digest(path):
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                              allow_nan=False) + "\n", encoding="utf-8")


def load_inputs(args):
    panel, provenance = load_s50_archive(args.archive)
    spec = load_coevolution_spec(MODEL)
    actual_pin = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip()
    if actual_pin != PIN:
        raise ValueError("qualification requires the documented pinned upstream checkout")
    from cusna.saom import data, mom, cpu, stats
    source_matches = {}
    for module in (data, mom, cpu, stats):
        installed = Path(module.__file__)
        original = args.upstream / "prototype/cusna/saom" / installed.name
        if installed.read_text() != original.read_text():
            raise ValueError("installed cusna differs from the pinned source: " + installed.name)
        source_matches[installed.name] = {"installed_sha256": digest(installed),
            "checkout_sha256": digest(original), "equal_after_newline_normalization": True}
    networks = saom_wave_matrices(panel)
    behavior = validate_coevolution_input(panel, spec)
    for i, network in enumerate(networks, 1):
        source = np.loadtxt(args.upstream / f"prototype/data/s50/s50-net{i}.txt")
        np.testing.assert_array_equal(network, source)
    np.testing.assert_array_equal(behavior, np.loadtxt(args.upstream / "prototype/data/s50/s50-alcohol.txt"))
    evidence = {"upstream_commit": PIN, "engine_version": version("cusna"),
                "dataset_hash": panel.content_hash, "specification_hash": spec.content_hash,
                "source_arrays_equal": True, "source_matches": source_matches, **provenance}
    return panel, spec, evidence


def published(args, model):
    folder = args.upstream / "prototype/bench"
    source_files = ("rsiena_coevol.R", "out/coevol_estimates.csv", "out/coevol_targets.csv", "out/coevol_sf.csv")
    files = {name: {"url": UPSTREAM + "/prototype/bench/" + name, "sha256": digest(folder / name)}
             for name in source_files}
    with (folder / "out/coevol_estimates.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    mapping = {"net.Rate.1": "rate net (p1)", "net.Rate.2": "rate net (p2)",
               "drink.Rate.1": "rate beh (p1)", "drink.Rate.2": "rate beh (p2)",
               **{"net." + name + ".NA": name for name in ("density", "recip", "transTrip", "altX", "egoX", "simX")},
               **{"drink." + name + ".NA": "beh " + name for name in ("linear", "quad", "avSim")}}
    names = model["parameter_names"]
    if len(rows) != 13 or {r["param"] for r in rows} != set(mapping) or len(set(names)) != 13:
        raise ValueError("unexpected published reference parameter set")
    permutation = [names.index(mapping[row["param"]]) for row in rows]
    records = [{"reference_name": row["param"], "parameter_index": index, "parameter_name": names[index],
                "estimate": float(row["est"]), "standard_error": float(row["se"]),
                "target": float(row["target"]), "adapter_target": model["targets"][index]}
               for row, index in zip(rows, permutation)]
    report = {
        "kind": "PUBLISHED_COEVOLUTION_REFERENCE", "files": files, "parameters": records,
        "model_matches": True, "conditional": False,
        "reference_settings": {"fit_seed": 321, "fit_n3": 2000, "simulation_seed": 654, "simulation_n3": 3000},
        "max_abs_target_difference": float(max(abs(r["target"] - r["adapter_target"]) for r in records)),
        "r_script_executed_here": False, "run_specific_rsiena_version_retained": False,
        "reference_full_convergence_diagnostics_retained": False,
        "independent_reference_validated": False,
        "scope": "published estimates, standard errors, deterministic targets and fixed-theta simulation export; not a newly qualified independent fit",
    }
    if report["max_abs_target_difference"] > 1e-10:
        raise ValueError("published deterministic targets do not match the selected model")
    return report, rows, permutation


def reference(args):
    panel, spec, evidence = load_inputs(args)
    model = coevolution_model_report(panel, spec)
    model.update(evidence)
    write(args.output / "s50-model.json", model)
    reference, rows, permutation = published(args, model)
    reference["input_evidence"] = evidence
    write(args.output / "published-reference.json", reference)

    from cusna.saom.data import SaomData
    from cusna.saom.mom import MomEstimator
    from cusna.saom.stats import BehEffectSpec, EffectSpec
    data = SaomData(saom_wave_matrices(panel), behavior=validate_coevolution_input(panel, spec))
    estimator = MomEstimator(data, effects=[EffectSpec(n, dyn=n in {"altX", "egoX", "simX"})
        for n in ("density", "recip", "transTrip", "altX", "egoX", "simX")],
        beh_effects=[BehEffectSpec(n) for n in ("linear", "quad", "avSim")],
        conditional=False, backend="cpu", seed=2024)
    if estimator.param_names != model["parameter_names"]:
        raise ValueError("independent direct call uses a different parameter layout")
    theta = np.empty(13)
    theta[permutation] = [float(r["est"]) for r in rows]
    export = args.upstream / "prototype/bench/out/coevol_sf.csv"
    with export.open(newline="") as stream:
        reader = csv.reader(stream)
        columns = next(reader)
        observed = np.asarray([[float(value) for value in row] for row in reader])
    if columns != [r["param"] for r in rows] or observed.shape != (3000, 13) or not np.isfinite(observed).all():
        raise ValueError("unexpected published simulation export")
    audit = {"batch_calls": 0, "period_paths_checked": 0, "max_steps_per_path": 0, "max_steps_by_period": [0, 0]}
    from cusna.saom.cpu import MAX_STEPS
    original = estimator._cpu

    def audited(*positional, **keywords):
        result = original(*positional, **keywords)
        _record_cpu_batch(result, n_sims=positional[3], period=keywords["period"],
                          step_limit=int(MAX_STEPS), audit=audit)
        return result

    estimator._cpu = audited
    start = time.monotonic()
    simulations, _, _, _ = estimator.simulate(theta, 3000)
    elapsed = time.monotonic() - start
    deviations = simulations[:, permutation] - estimator.targets[permutation]
    comparisons = []
    critical = NormalDist().inv_cdf(1 - 0.05 / (2 * 13))
    for column, row in enumerate(rows):
        candidate = deviations[:, column]
        baseline = observed[:, column]
        standard_error = float(np.sqrt(candidate.var(ddof=1) / 3000 + baseline.var(ddof=1) / 3000))
        if not standard_error > 0:
            raise ValueError("degenerate Monte Carlo mean comparison")
        difference = float(candidate.mean() - baseline.mean())
        comparisons.append({"reference_name": row["param"], "parameter_index": permutation[column],
            "cpu_mean_deviation": float(candidate.mean()), "reference_mean_deviation": float(baseline.mean()),
            "cpu_sd": float(candidate.std(ddof=1)), "reference_sd": float(baseline.std(ddof=1)),
            "difference": difference, "monte_carlo_standard_error": standard_error,
            "standardized_mean_difference": difference / standard_error,
            "simultaneous_interval": [difference - critical * standard_error, difference + critical * standard_error]})
    maximum = max(abs(r["standardized_mean_difference"]) for r in comparisons)
    result = {"kind": "FIXED_PARAMETER_CPU_REFERENCE_COMPARISON", "input_evidence": evidence,
        "cpu_seed": 2024, "full_panel_replicates_each": 3000, "reference_seed": 654,
        "theta_source": reference["files"]["out/coevol_estimates.csv"], "theta_in_cusna_order": theta.tolist(),
        "reference_export": reference["files"]["out/coevol_sf.csv"],
        "comparisons": comparisons, "max_abs_standardized_mean_difference": maximum,
        "mean_comparison_screen": {"family_alpha": 0.05, "comparison_count": 13,
            "normal_approximation_bonferroni_critical_value": critical,
            "all_intervals_include_zero": bool(maximum <= critical),
            "scope": "simultaneous approximate Monte Carlo intervals for these 13 statistic means at one fixed parameter vector; not full distribution equivalence"},
        "simulation_diagnostics": {**audit, "kernel_step_limit": int(MAX_STEPS)},
        "cpu_wall_seconds": round(elapsed, 6), "fit_performed": False,
        "independent_reference_validated": False, "forecast_validated": False,
        "causal_effect_identified": False}
    write(args.output / "cpu-reference-simulation.json", result)
    print(json.dumps({"mode": "reference", "max_abs_target_difference": reference["max_abs_target_difference"],
        "max_abs_standardized_mean_difference": maximum, "critical_value": critical,
        "all_intervals_include_zero": maximum <= critical, "seconds": elapsed}), flush=True)


def fit(args):
    _, _, evidence = load_inputs(args)
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in (
        ROOT / "src/sociolab/coevolution.py", ROOT / "src/sociolab/coevolution_input.py",
        ROOT / "src/sociolab/saom.py", ROOT / "src/sociolab/cli.py", MODEL)}
    command = [sys.executable, "-m", "sociolab", "coevolution", "fit", str(args.archive),
               str(MODEL), "--format", "s50", "--seed", "1234"]
    started = datetime.now(timezone.utc).isoformat()
    print(json.dumps({"mode": "fit", "started_at_utc": started, "budgets": "unchanged defaults", "seed": 1234}), flush=True)
    start = time.monotonic()
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NUMBA_NUM_THREADS="2")
    result = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
    elapsed = time.monotonic() - start
    report_path = args.output / "s50-seed1234-fit.json"
    report_path.write_text(result.stdout, encoding="utf-8")
    (args.output / "s50-seed1234-stderr.log").write_text(result.stderr, encoding="utf-8")
    execution = {"kind": "COEVOLUTION_FIT_EXECUTION", "command": command, "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(), "exit_code": result.returncode,
        "wall_seconds": round(elapsed, 6), "source_hashes_at_start": source_hashes,
        "input_evidence": evidence, "environment": {"NUMBA_NUM_THREADS": "2"},
        "report_sha256": digest(report_path), "stderr": result.stderr,
        "automatic_retry": False, "retuned_budgets": False}
    write(args.output / "s50-seed1234-execution.json", execution)
    if result.returncode not in (0, 2) or not result.stdout.strip():
        raise RuntimeError("joint fit did not emit a valid diagnostic report: " + result.stderr)
    report = json.loads(result.stdout)
    expected = 0 if report["convergence_is_validated"] else 2
    if result.returncode != expected:
        raise ValueError("CLI exit status disagrees with diagnostic report")
    print(json.dumps({"mode": "fit", "exit_code": result.returncode, "status": report["convergence_status"],
        "max_abs_tconv": report["max_abs_tconv"], "tconv_max": report["tconv_max"],
        "full_panel_replicates": report["n_simulations"], "seconds": elapsed}), flush=True)


def verify(args):
    report = json.loads((args.output / "s50-seed1234-fit.json").read_text())
    execution = json.loads((args.output / "s50-seed1234-execution.json").read_text())
    reference = json.loads((args.output / "published-reference.json").read_text())
    source_checks = []
    for relative, original_hash in execution["source_hashes_at_start"].items():
        current = ROOT / relative
        current_hash = digest(current)
        if current_hash == original_hash:
            source_checks.append({"path": relative, "source_unchanged": True})
        elif relative == "src/sociolab/coevolution.py":
            previous_wording = current.read_text().replace(
                "ego's outgoing network ties", "ego's outgoing observed network ties", 1)
            if "sha256:" + sha256(previous_wording.encode()).hexdigest() != original_hash:
                raise ValueError("fit source changed beyond the documented metadata clarification")
            source_checks.append({"path": relative, "source_unchanged": False,
                "only_change": "neighbor_direction wording removes observed; target conventions and all numerical code are unchanged",
                "current_sha256": current_hash, "executed_sha256": original_hash})
        else:
            raise ValueError("fit source changed without an execution-equivalence check: " + relative)
    diagnostic = report["diagnostics"]
    assessment = _assess_mom_diagnostics(theta=report["estimates"], se=report["standard_errors"],
        tconv=report["tconv"], tconv_max=report["tconv_max"], targets=diagnostic["targets"],
        sim_means=diagnostic["sim_means"], D=diagnostic["D"], msf=diagnostic["msf"],
        parameter_count=report["model_descriptor"]["parameter_count"])
    D = np.asarray(diagnostic["D"])
    covariance = np.asarray(diagnostic["msf"])
    deviation = np.asarray(diagnostic["sim_means"]) - diagnostic["targets"]
    ratios = deviation / np.sqrt(np.diag(covariance))
    overall = float(np.sqrt(deviation @ np.linalg.solve(covariance, deviation)))
    inverse = np.linalg.inv(D)
    standard_errors = np.sqrt(np.diag(inverse @ covariance @ inverse.T))
    np.testing.assert_allclose(ratios, report["tconv"], rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(overall, report["tconv_max"], rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(standard_errors, report["standard_errors"], rtol=1e-11, atol=1e-12)
    coefficients = []
    for row in reference["parameters"]:
        i = row["parameter_index"]
        difference = report["estimates"][i] - row["estimate"]
        coefficients.append({"parameter_name": row["parameter_name"], "reference_name": row["reference_name"],
            "cpu_estimate": report["estimates"][i], "cpu_standard_error": report["standard_errors"][i],
            "reference_estimate": row["estimate"], "reference_standard_error": row["standard_error"],
            "difference": difference, "difference_over_reference_se": difference / row["standard_error"]})
    result = {"kind": "COEVOLUTION_RECORDED_DIAGNOSTIC_VERIFICATION",
        "convergence_status": assessment["convergence_status"], "convergence_scope": assessment["convergence_scope"],
        "parameter_count": len(report["parameter_names"]), "max_abs_tconv": float(np.max(np.abs(ratios))),
        "tconv_max": overall, "derivative_rank": int(np.linalg.matrix_rank(D)),
        "statistic_covariance_rank": int(np.linalg.matrix_rank(covariance)),
        "statistic_covariance_eigenvalues": np.linalg.eigvalsh(covariance).tolist(),
        "standard_error_max_abs_reconstruction_difference": float(np.max(np.abs(standard_errors - report["standard_errors"]))),
        "coefficients": coefficients,
        "coefficient_comparison_scope": "informational differences on the same data; reference fit diagnostics/version are incomplete, and standardized differences are not independent-estimator tests",
        "independent_reference_validated": False, "causal_effect_identified": False,
        "final_source_checks": source_checks,
        "raw_cli_report_preserved": True,
        "source_report_sha256": digest(args.output / "s50-seed1234-fit.json")}
    write(args.output / "s50-seed1234-verification.json", result)
    print(json.dumps({"mode": "verify", "convergence_status": result["convergence_status"],
                      "parameter_count": result["parameter_count"], "rank": result["derivative_rank"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("reference", "fit", "verify"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    args.archive = args.archive.resolve()
    args.upstream = args.upstream.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    {"reference": reference, "fit": fit, "verify": verify}[args.mode](args)
