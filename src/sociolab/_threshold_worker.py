"""Private JSON entry point that isolates NDlib's process-global RNG."""

import json
import sys

from .dataset import NetworkDataset
from .diffusion import _run_threshold


def main() -> None:
    request = json.load(sys.stdin)
    result = _run_threshold(
        NetworkDataset.from_mapping(request["dataset"]),
        seeds=tuple(request["seeds"]),
        threshold=request["threshold"],
        steps=request["steps"],
        random_seed=request["random_seed"],
    )
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
