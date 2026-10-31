"""Call NDlib's original threshold engine, never implement one here."""

from __future__ import annotations

from importlib.metadata import version
import math

from .dataset import NetworkDataset


def threshold_report(
    dataset: NetworkDataset,
    *,
    seeds: tuple[str, ...],
    threshold: float,
    steps: int,
    random_seed: int = 0,
) -> dict[str, object]:
    if not isinstance(dataset, NetworkDataset):
        raise TypeError("threshold analysis requires NetworkDataset")
    if type(seeds) is not tuple or not seeds or any(type(x) is not str for x in seeds):
        raise ValueError("one or more explicitly supplied seed actors are required")
    if tuple(sorted(set(seeds))) != seeds or any(x not in dataset.actors for x in seeds):
        raise ValueError("seed actors must be unique, sorted and present in the dataset")
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be a finite number in [0,1]")
    if type(steps) is not int or steps <= 0:
        raise ValueError("steps must be a positive integer")
    if type(random_seed) is not int or random_seed < 0:
        raise ValueError("random_seed must be a nonnegative integer")

    # Required upstream dependency. Missing package is an error, not a
    # reason to run a local fallback diffusion engine.
    from ndlib.models.epidemics import ThresholdModel
    from ndlib.models.ModelConfig import Configuration

    engine = ThresholdModel(dataset.to_graph(), seed=random_seed)
    settings = Configuration()
    settings.add_model_initial_configuration("Infected", list(seeds))
    settings.add_node_set_configuration(
        "threshold", {actor: float(threshold) for actor in dataset.actors}
    )
    engine.set_initial_status(settings)
    # NDlib iteration 0 is its initial status; subsequent iterations hold
    # only changed node statuses. This is report reconstruction, NOT diffusion.
    iterations = engine.iteration_bunch(steps + 1)
    status: dict[str, int] = {}
    adopted_by_step: list[list[str]] = []
    for index, record in enumerate(iterations):
        if record["iteration"] != index:
            raise RuntimeError("unexpected NDlib iteration order")
        status.update(record["status"])
        if set(status) != set(dataset.actors):
            raise RuntimeError("NDlib did not report all graph actors")
        if any(value not in (0, 1) for value in status.values()):
            raise RuntimeError("unexpected NDlib threshold status")
        adopted_by_step.append(sorted(actor for actor, value in status.items() if value == 1))
    if adopted_by_step[0] != list(seeds):
        raise RuntimeError("NDlib initial status differs from explicit seed actors")
    return {
        "kind": "REFERENCE_MODEL_RESULT",
        "engine": "ndlib",
        "engine_version": version("ndlib"),
        "model": "ThresholdModel",
        "dataset_id": dataset.dataset_id,
        "dataset_hash": dataset.content_hash,
        "source_origin": dataset.origin,
        "relation": dataset.relation,
        "directed": True,
        "seed_actors": list(seeds),
        "threshold": float(threshold),
        "random_seed": random_seed,
        "steps": steps,
        "adopted_by_step": adopted_by_step,
        "meaning": "reference diffusion simulation; not actual observed transmissions",
    }
