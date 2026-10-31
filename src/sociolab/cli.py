"""Explicit command-line entry points for upstream reference experiments."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .dataset import load_network
from .diffusion import threshold_report
from .structure import structural_report
from .communities import karate_community_report
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
    structure = commands.add_parser("structure", help="run upstream NetworkX structure metrics")
    structure.add_argument("dataset")
    threshold = commands.add_parser("threshold", help="run upstream NDlib ThresholdModel")
    threshold.add_argument("dataset")
    threshold.add_argument("--seeds", nargs="+", required=True)
    threshold.add_argument("--threshold", type=float, required=True)
    threshold.add_argument("--steps", type=int, required=True)
    threshold.add_argument("--random-seed", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "communities":
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
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0
