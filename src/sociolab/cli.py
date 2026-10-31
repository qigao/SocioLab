"""Explicit command-line entry points for upstream reference experiments."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .dataset import load_network
from .diffusion import threshold_report
from .structure import structural_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sociolab")
    commands = parser.add_subparsers(dest="command", required=True)
    structure = commands.add_parser("structure", help="run upstream NetworkX structure metrics")
    structure.add_argument("dataset")
    threshold = commands.add_parser("threshold", help="run upstream NDlib ThresholdModel")
    threshold.add_argument("dataset")
    threshold.add_argument("--seeds", nargs="+", required=True)
    threshold.add_argument("--threshold", type=float, required=True)
    threshold.add_argument("--steps", type=int, required=True)
    threshold.add_argument("--random-seed", type=int, default=0)
    args = parser.parse_args(argv)
    dataset = load_network(args.dataset)
    if args.command == "structure":
        report = structural_report(dataset)
    else:
        report = threshold_report(
            dataset, seeds=tuple(sorted(args.seeds)), threshold=args.threshold,
            steps=args.steps, random_seed=args.random_seed,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0
