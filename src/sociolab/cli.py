"""Explicit command-line entry points for upstream reference experiments."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .dataset import load_network
from .diffusion import threshold_report
from .structure import structural_report
from .communities import karate_community_report
from .panels import load_panel, longitudinal_structure_report
from .s50 import s50_reference_report
from .references import karate_club_report
from .keyplayers import karate_keyplayers_report
from .affiliations import davis_affiliation_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sociolab")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("davis", help="analyze Davis 1941 person-event affiliation reference")
    commands.add_parser("communities", help="upstream NetworkX Karate community detection and post-fission comparison")
    commands.add_parser("karate", help="analyze published Zachary network using upstream NetworkX")
    keyplayers = commands.add_parser("keyplayers", help="upstream NetworkX prominent-group search on the published Karate graph")
    keyplayers.add_argument("--size", type=int, default=2)
    panel = commands.add_parser("panel", help="descriptive multi-wave NetworkX metrics; no influence or causal estimation")
    panel.add_argument("dataset")
    s50 = commands.add_parser("s50", help="read official s50-format ZIP as a numerical example; not causal evidence")
    s50.add_argument("archive", help="locally supplied s50_data.zip from the original research site")
    saom = commands.add_parser("saom", help="fit the upstream CPU model and report numerical convergence")
    saom.add_argument("dataset", help="longitudinal panel JSON or s50 archive")
    saom.add_argument("--format", choices=("panel", "s50"), default="panel")
    saom.add_argument("--seed", type=int, default=1234)
    saom.add_argument("--n1", type=int, default=1000)
    saom.add_argument("--nd", type=int, default=1000, help="simulations for each derivative batch")
    saom.add_argument("--n3", type=int, default=4000)
    saom.add_argument("--batch2", type=int, default=256)
    saom.add_argument("--n2", type=int, nargs=4, default=(40, 40, 60, 80),
                      help="iteration counts for the four phase-2 subphases")
    structure = commands.add_parser("structure", help="run upstream NetworkX structure metrics")
    structure.add_argument("dataset")
    threshold = commands.add_parser("threshold", help="run upstream NDlib ThresholdModel")
    threshold.add_argument("dataset")
    threshold.add_argument("--seeds", nargs="+", required=True)
    threshold.add_argument("--threshold", type=float, required=True)
    threshold.add_argument("--steps", type=int, required=True)
    threshold.add_argument("--random-seed", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "saom":
        from .saom import fit_network_saom, fit_s50_network_reference

        settings = {
            "seed": args.seed, "n1": args.n1, "nD": args.nd,
            "n3": args.n3, "batch2": args.batch2, "n2": tuple(args.n2),
        }
        if args.format == "s50":
            report = fit_s50_network_reference(args.dataset, **settings)
        else:
            report = fit_network_saom(load_panel(args.dataset), **settings)
    elif args.command == "s50":
        report = s50_reference_report(args.archive)
    elif args.command == "panel":
        report = longitudinal_structure_report(load_panel(args.dataset))
    elif args.command == "communities":
        report = karate_community_report()
    elif args.command == "davis":
        report = davis_affiliation_report()
    elif args.command == "karate":
        report = karate_club_report()
    elif args.command == "keyplayers":
        report = karate_keyplayers_report(group_size=args.size)
    elif args.command == "structure":
        report = structural_report(load_network(args.dataset))
    else:
        dataset = load_network(args.dataset)
        report = threshold_report(
            dataset, seeds=tuple(sorted(args.seeds)), threshold=args.threshold,
            steps=args.steps, random_seed=args.random_seed,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    if args.command == "saom" and not report["convergence_is_validated"]:
        return 2
    return 0
