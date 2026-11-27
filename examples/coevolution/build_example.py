"""Invented ordinal measurements on an original upstream synthetic network.

This fixture is a software example, not a recovered social mechanism or an
empirical population. Install the optional [saom] extra to rebuild it.
"""

import json
from pathlib import Path

import numpy as np
from cusna.saom.data import synthetic_panel

from sociolab.coevolution_input import CoevolutionSpec
from sociolab.panels import LongitudinalPanel


def build():
    original = synthetic_panel(20, mean_degree=4, change_frac=0.25, seed=17)
    actors = [f"actor-{i:03d}" for i in range(20)]
    first = 1 + np.arange(20) % 5
    second = np.clip(first + np.arange(20) % 3 - 1, 1, 5)
    behaviors = (first, second)
    panel = LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1", "dataset_id": "invented-coevolution-example",
        "origin": "synthetic", "source_reference": None, "actors": actors,
        "relation": "directed_observed_social_tie", "behavior_variable": "synthetic_ordinal_1_to_5",
        "waves": [{"time_index": m, "source_revision": f"invented-wave-{m}",
                   "network_complete": True,
                   "edges": [[actors[i], actors[j]] for i in range(20) for j in range(20) if wave[i, j]],
                   "behavior": {actor: int(behaviors[m][i]) for i, actor in enumerate(actors)}}
                  for m, wave in enumerate(original.waves)],
    })
    spec = CoevolutionSpec(
        "synthetic_ordinal_1_to_5", 1, 5, "synthetic:declared-five-state-scale",
        "Exercise the retrospective joint model on invented observations; no empirical inference.",
    )
    return panel, spec


if __name__ == "__main__":
    panel, spec = build()
    folder = Path(__file__).parent
    for name, value in (("synthetic.panel.json", panel.to_dict()), ("synthetic.model.json", spec.to_dict())):
        (folder / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
