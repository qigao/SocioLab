"""Fixed-roster directed observations with explicit present and absent dyads.

Every unlisted off-diagonal dyad is unknown. These declarations are separate
from the complete-data longitudinal v1 contract; they neither infer zeros nor
qualify a source, population boundary, or empirical model.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from ._json import unique_object


SCHEMA = "sociolab.partial-network.v1"
_FIELDS = frozenset({
    "schema", "dataset_id", "origin", "source_reference", "actors", "relation",
    "population_definition", "observation_definition", "waves",
})
_WAVE_FIELDS = frozenset({
    "time_index", "source_revision", "observed_present", "observed_absent",
})
_ORIGINS = frozenset({"synthetic", "external_observation"})
_MAX_ACTORS = 500
_MAX_WAVES = 20
_MAX_OBSERVED_DYADS = 1_000_000
_MAX_JSON_BYTES = 64 * 1024 * 1024


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonempty trimmed text")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"{name} must be valid UTF-8 text") from error


def _fields(value: object, expected: frozenset[str], name: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} requires exactly its declared fields")


def _pairs(value: object, name: str) -> None:
    if type(value) is not tuple:
        raise ValueError(f"{name} must be an immutable tuple of directed pairs")
    if len(value) > _MAX_OBSERVED_DYADS:
        raise ValueError("partial panel exceeds the observed dyad record limit")
    previous = None
    for pair in value:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError(f"{name} must contain immutable directed pairs")
        _text(pair[0], "dyad source")
        _text(pair[1], "dyad target")
        if pair[0] == pair[1]:
            raise ValueError("self dyads are outside the observation universe")
        if previous is not None and pair <= previous:
            raise ValueError(f"{name} must be unique and sorted")
        previous = pair


def _json_pairs(value: object, name: str) -> tuple[tuple[str, str], ...]:
    if type(value) is not list:
        raise ValueError(f"{name} must be a JSON list of directed pairs")
    if len(value) > _MAX_OBSERVED_DYADS:
        raise ValueError("partial panel exceeds the observed dyad record limit")
    pairs = []
    for pair in value:
        if type(pair) is not list or len(pair) != 2:
            raise ValueError(f"{name} must contain two-element JSON lists")
        pairs.append((pair[0], pair[1]))
    return tuple(pairs)


@dataclass(frozen=True, slots=True)
class PartialNetworkWave:
    """One observation time; absent and unknown have different meanings."""

    time_index: int
    source_revision: str
    observed_present: tuple[tuple[str, str], ...]
    observed_absent: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if type(self.time_index) is not int or self.time_index < 0:
            raise ValueError("wave time must be a nonnegative exact integer")
        _text(self.source_revision, "source_revision")
        _pairs(self.observed_present, "observed_present")
        _pairs(self.observed_absent, "observed_absent")
        if len(self.observed_present) + len(self.observed_absent) > _MAX_OBSERVED_DYADS:
            raise ValueError("partial panel exceeds the observed dyad record limit")
        if set(self.observed_present).intersection(self.observed_absent):
            raise ValueError("a dyad cannot be both observed present and observed absent")

    def to_dict(self) -> dict[str, object]:
        return {
            "time_index": self.time_index,
            "source_revision": self.source_revision,
            "observed_present": [list(pair) for pair in self.observed_present],
            "observed_absent": [list(pair) for pair in self.observed_absent],
        }


@dataclass(frozen=True, slots=True)
class PartialNetworkPanel:
    """Immutable declarations for one directed relation and a fixed roster.

    The same actor order applies to every wave. All off-diagonal pairs are in
    the declared observation universe; pairs in neither observation set are
    unknown. Empty observation sets and wholly unknown waves remain valid
    descriptions. Model readiness is a separate decision.
    """

    dataset_id: str
    origin: str
    source_reference: str | None
    actors: tuple[str, ...]
    relation: str
    population_definition: str
    observation_definition: str
    waves: tuple[PartialNetworkWave, ...]

    def __post_init__(self) -> None:
        _text(self.dataset_id, "dataset_id")
        _text(self.relation, "relation")
        _text(self.population_definition, "population_definition")
        _text(self.observation_definition, "observation_definition")
        if type(self.origin) is not str or self.origin not in _ORIGINS:
            raise ValueError("unsupported partial panel origin")
        if self.origin == "synthetic":
            if self.source_reference is not None:
                raise ValueError("synthetic panel cannot claim an external source")
        else:
            _text(self.source_reference, "source_reference")
            if not re.fullmatch(r"https://[^\s]+", self.source_reference):
                raise ValueError("external observation requires an HTTPS source reference")
        if type(self.actors) is not tuple or not 2 <= len(self.actors) <= _MAX_ACTORS:
            raise ValueError(f"partial panel requires an immutable tuple of 2..{_MAX_ACTORS} actors")
        for actor in self.actors:
            _text(actor, "actor")
        if self.actors != tuple(sorted(set(self.actors))):
            raise ValueError("actor identities must be unique and sorted")
        if type(self.waves) is not tuple or not 2 <= len(self.waves) <= _MAX_WAVES:
            raise ValueError(f"partial panel requires an immutable tuple of 2..{_MAX_WAVES} waves")
        actor_set = set(self.actors)
        previous_time = None
        revisions = set()
        observed_count = 0
        for wave in self.waves:
            if type(wave) is not PartialNetworkWave:
                raise ValueError("partial panel waves must be validated PartialNetworkWave objects")
            if previous_time is not None and wave.time_index <= previous_time:
                raise ValueError("wave time indices must strictly increase")
            previous_time = wave.time_index
            if wave.source_revision in revisions:
                raise ValueError("wave source revisions must be unique")
            revisions.add(wave.source_revision)
            observed_count += len(wave.observed_present) + len(wave.observed_absent)
            if observed_count > _MAX_OBSERVED_DYADS:
                raise ValueError("partial panel exceeds the observed dyad record limit")
            for pairs in (wave.observed_present, wave.observed_absent):
                if any(source not in actor_set or target not in actor_set for source, target in pairs):
                    raise ValueError("observed dyads must connect known actors")

    @classmethod
    def from_mapping(cls, value: object) -> PartialNetworkPanel:
        _fields(value, _FIELDS, "partial network panel")
        if type(value["schema"]) is not str or value["schema"] != SCHEMA:
            raise ValueError("unsupported partial network panel schema")
        actors = value["actors"]
        if type(actors) is not list or not 2 <= len(actors) <= _MAX_ACTORS:
            raise ValueError(f"partial panel requires a JSON list of 2..{_MAX_ACTORS} actors")
        raw_waves = value["waves"]
        if type(raw_waves) is not list or not 2 <= len(raw_waves) <= _MAX_WAVES:
            raise ValueError(f"partial panel requires a JSON list of 2..{_MAX_WAVES} waves")
        waves = []
        observed_count = 0
        for raw in raw_waves:
            _fields(raw, _WAVE_FIELDS, "partial network wave")
            for name in ("observed_present", "observed_absent"):
                if type(raw[name]) is not list:
                    raise ValueError(f"{name} must be a JSON list of directed pairs")
                observed_count += len(raw[name])
            if observed_count > _MAX_OBSERVED_DYADS:
                raise ValueError("partial panel exceeds the observed dyad record limit")
            waves.append(PartialNetworkWave(
                raw["time_index"], raw["source_revision"],
                _json_pairs(raw["observed_present"], "observed_present"),
                _json_pairs(raw["observed_absent"], "observed_absent"),
            ))
        return cls(
            value["dataset_id"], value["origin"], value["source_reference"], tuple(actors),
            value["relation"], value["population_definition"], value["observation_definition"],
            tuple(waves),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "dataset_id": self.dataset_id,
            "origin": self.origin,
            "source_reference": self.source_reference,
            "actors": list(self.actors),
            "relation": self.relation,
            "population_definition": self.population_definition,
            "observation_definition": self.observation_definition,
            "waves": [wave.to_dict() for wave in self.waves],
        }

    @property
    def content_hash(self) -> str:
        raw = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
        return "sha256:" + sha256(raw).hexdigest()


def _invalid_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON constant is not admitted: {value}")


def load_partial_panel(path: str | Path) -> PartialNetworkPanel:
    """Read bounded UTF-8 JSON without accepting duplicate object keys."""
    with Path(path).open("rb") as handle:
        raw = handle.read(_MAX_JSON_BYTES + 1)
    if len(raw) > _MAX_JSON_BYTES:
        raise ValueError("partial panel JSON exceeds the byte limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=_invalid_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("partial panel JSON must be valid, bounded UTF-8 data") from error
    return PartialNetworkPanel.from_mapping(value)
