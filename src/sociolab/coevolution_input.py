"""Declared ordinal measurements for the fixed directed coevolution profile.

This module prepares complete observations; it performs no imputation,
annotation inference, or estimation. Measurement references are declarations,
not authentication of a source or qualification of a research design.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from ._json import unique_object
from .panels import LongitudinalPanel


SCHEMA = "sociolab.coevolution.v1"
PROFILE = "directed-selection-similarity-v1"
_FIELDS = frozenset({"schema", "profile", "behavior", "research_question"})
_BEHAVIOR_FIELDS = frozenset({"variable", "minimum", "maximum", "measurement_reference"})
_INT32_MAX = int(np.iinfo(np.int32).max)


def _fields(value: object, expected: frozenset[str], name: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} requires exactly its declared fields")


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonempty trimmed text")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"{name} must be valid UTF-8 text") from error


@dataclass(frozen=True)
class CoevolutionSpec:
    """Immutable measurement declaration and one registered model profile.

    Every integer between minimum and maximum is an admissible ordinal state;
    the modeled step is one. Values are not recoded or rounded. The current
    upstream constructor derives its bounds from the supplied fit sample, so
    admission additionally requires that sample to observe both endpoints.
    """

    behavior_variable: str
    minimum: int
    maximum: int
    measurement_reference: str
    research_question: str
    profile: str = PROFILE

    def __post_init__(self) -> None:
        _text(self.behavior_variable, "behavior variable")
        _text(self.measurement_reference, "measurement reference")
        _text(self.research_question, "research question")
        if type(self.profile) is not str or self.profile != PROFILE:
            raise ValueError("unsupported coevolution profile")
        if (type(self.minimum) is not int or type(self.maximum) is not int
                or not 0 <= self.minimum < self.maximum <= _INT32_MAX):
            raise ValueError("ordinal bounds require exact integers 0 <= minimum < maximum <= int32 maximum")

    @classmethod
    def from_mapping(cls, value: object) -> CoevolutionSpec:
        _fields(value, _FIELDS, "coevolution specification")
        if type(value["schema"]) is not str or value["schema"] != SCHEMA:
            raise ValueError("unsupported coevolution specification schema")
        behavior = value["behavior"]
        _fields(behavior, _BEHAVIOR_FIELDS, "coevolution behavior declaration")
        return cls(
            behavior_variable=behavior["variable"],
            minimum=behavior["minimum"],
            maximum=behavior["maximum"],
            measurement_reference=behavior["measurement_reference"],
            research_question=value["research_question"],
            profile=value["profile"],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "profile": self.profile,
            "behavior": {
                "variable": self.behavior_variable,
                "minimum": self.minimum,
                "maximum": self.maximum,
                "measurement_reference": self.measurement_reference,
            },
            "research_question": self.research_question,
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        return "sha256:" + sha256(encoded).hexdigest()


def load_coevolution_spec(path: str | Path) -> CoevolutionSpec:
    with Path(path).open("r", encoding="utf-8") as handle:
        return CoevolutionSpec.from_mapping(json.load(handle, object_pairs_hook=unique_object))


def validate_coevolution_input(panel: LongitudinalPanel, spec: CoevolutionSpec) -> np.ndarray:
    """Return complete behavior values with rows=actors and columns=waves.

    Row order is exactly ``panel.actors`` and columns follow the panel's
    strictly increasing wave order. No observation or actor is dropped.
    Wave time indices are preserved by the panel; this function does not
    reinterpret index gaps as model durations.
    """
    if not isinstance(panel, LongitudinalPanel):
        raise ValueError("coevolution requires a versioned LongitudinalPanel")
    if not isinstance(spec, CoevolutionSpec):
        raise ValueError("coevolution requires a validated CoevolutionSpec")
    if panel.behavior_variable != spec.behavior_variable:
        raise ValueError("declared behavior variable must match the panel")
    if any(not wave.network_complete for wave in panel.waves):
        raise ValueError("coevolution requires complete network observations")

    # cusna consumes float64 observations and later stores simulated ordinal
    # states as int32. Validate before conversion, avoiding coercion/overflow.
    behavior = np.empty((len(panel.actors), len(panel.waves)), dtype=np.float64)
    for wave_index, wave in enumerate(panel.waves):
        for actor_index, (actor, value) in enumerate(wave.behavior):
            if value is None:
                raise ValueError(f"coevolution requires complete behavior observations: {actor} at wave {wave.time_index}")
            if type(value) is not int or not spec.minimum <= value <= spec.maximum:
                raise ValueError(f"behavior observation is outside declared ordinal bounds: {actor} at wave {wave.time_index}")
            behavior[actor_index, wave_index] = value

    if int(behavior.min()) != spec.minimum or int(behavior.max()) != spec.maximum:
        raise ValueError("observed behavior extrema must equal the declared ordinal bounds; upstream cannot preserve unobserved endpoints")
    return behavior
