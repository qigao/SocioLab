"""Separate an s50 teaching prefix from its later behavior target.

The archive is caller supplied.  History never opens the third network and
never parses, validates or hashes the third behavior column.  The shared
behavior member must be decompressed to obtain its earlier columns; reading
those bounded bytes does not make the unused tokens observations available
to the returned history.  Only the separate target function consumes them.

s50 is not a properly delineated social network.  These readers establish
neither population validity, forecast performance nor causal influence.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from .panels import LongitudinalPanel
from .s50 import (
    S50_DOWNLOAD, S50_SOURCE, _ARCHIVE_MAX_BYTES, _MEMBER_MAX_BYTES,
    _integer_matrix,
)

_DATASET_ID = "teenage-friends-s50-numerical-example"
_BEHAVIOR_VARIABLE = "alcohol_consumption_ordinal_1_to_5"
_NETWORK_MEMBERS = ("s50-network1.dat", "s50-network2.dat")
_BEHAVIOR_MEMBER = "s50-alcohol.dat"
_EXPECTED_TIES = (113, 116)
_ACTORS = tuple(f"p{index:03d}" for index in range(1, 51))


def _value_hash(value: object) -> str:
    """Fingerprint consumed values, without unused source bytes or tokens."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + sha256(raw.encode("ascii")).hexdigest()


def _selected_members(path: str | Path, required: tuple[str, ...]) -> dict[str, bytes]:
    """Read bounded, safely named required ZIP members; ignore other contents."""
    with Path(path).open("rb") as stream:
        source = stream.read(_ARCHIVE_MAX_BYTES + 1)
    if not source or len(source) > _ARCHIVE_MAX_BYTES:
        raise ValueError("s50 archive must be nonempty and within byte limit")
    selected: dict[str, bytes] = {}
    try:
        with ZipFile(BytesIO(source)) as archive:
            for item in archive.infolist():
                normalized = PurePosixPath(item.filename)
                if (normalized.is_absolute() or ".." in normalized.parts
                        or "\\" in item.filename):
                    raise ValueError("s50 archive has an unsafe member path")
                if item.is_dir() or normalized.name not in required:
                    continue
                name = normalized.name
                if name in selected:
                    raise ValueError("s50 archive contains duplicate required files")
                if item.file_size > _MEMBER_MAX_BYTES:
                    raise ValueError("s50 member exceeds bounded input size")
                with archive.open(item) as member:
                    data = member.read(_MEMBER_MAX_BYTES + 1)
                if len(data) > _MEMBER_MAX_BYTES:
                    raise ValueError("s50 member exceeds bounded input size")
                selected[name] = data
    except BadZipFile as exc:
        raise ValueError("s50 source is not a valid ZIP archive") from exc
    except (NotImplementedError, RuntimeError) as exc:
        raise ValueError("s50 required member cannot be read from this ZIP archive") from exc
    if set(selected) != set(required):
        raise ValueError("s50 archive lacks required prefix/target observations")
    return selected


def _behavior_columns(data: bytes, columns: tuple[int, ...], *, target: bool = False
                      ) -> list[list[int]]:
    """Parse selected columns only, leaving all other tokens opaque bytes."""
    lines = data.splitlines()
    if len(lines) != 50:
        raise ValueError("s50-alcohol.dat must have exactly 50 rows")
    result = []
    minimum_columns = max(columns) + 1
    for line in lines:
        # In the prefix reader the third element is an opaque remainder, not
        # a third parsed column.  Its presence and contents are immaterial.
        parts = line.split(maxsplit=minimum_columns)
        if len(parts) < minimum_columns:
            raise ValueError(
                f"s50-alcohol.dat must supply at least {minimum_columns} columns"
            )
        if target and len(parts) != 3:
            raise ValueError("s50-alcohol.dat target rows must have exactly 3 columns")
        values = []
        for column in columns:
            token = parts[column]
            if not token.isdigit():
                raise ValueError("consumed s50 behavior must contain ASCII integer codes")
            value = int(token)
            if value not in range(1, 6):
                raise ValueError("consumed s50 behavior contains missing or unsupported observations")
            values.append(value)
        result.append(values)
    return result


def load_s50_forecast_history(path: str | Path
                              ) -> tuple[LongitudinalPanel, dict[str, object]]:
    """Return only waves 1/2 and aggregate provenance of their consumed values.

    Source-format safety limits apply to the archive and selected members.
    Within those limits, unused future values and the presence or contents of
    network3 cannot change the returned panel or provenance.  Two-column
    behavior rows are accepted so a target-free input can also be supplied.
    """
    members = _selected_members(path, (*_NETWORK_MEMBERS, _BEHAVIOR_MEMBER))
    networks = [
        _integer_matrix(members[name], name=name, rows=50, columns=50,
                        allowed=frozenset({0, 1}))
        for name in _NETWORK_MEMBERS
    ]
    behavior = _behavior_columns(members[_BEHAVIOR_MEMBER], (0, 1))
    waves = []
    for index, matrix in enumerate(networks):
        edges = []
        for row, values in enumerate(matrix):
            if values[row] != 0 or sum(values) > 12:
                raise ValueError("s50 self-nominations/overlimit nominations are invalid")
            edges.extend([_ACTORS[row], _ACTORS[column]]
                         for column, value in enumerate(values) if value)
        if len(edges) != _EXPECTED_TIES[index]:
            raise ValueError("s50 friendship ties differ from the documented reference")
        wave_behavior = [values[index] for values in behavior]
        waves.append({
            "time_index": index,
            "source_revision": _value_hash({"network": matrix, "behavior": wave_behavior}),
            "network_complete": True,
            "edges": sorted(edges),
            "behavior": dict(zip(_ACTORS, wave_behavior, strict=True)),
        })
    panel = LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1",
        "dataset_id": _DATASET_ID,
        "origin": "external_observation",
        "source_reference": S50_SOURCE,
        "actors": list(_ACTORS),
        "relation": "directed_observed_social_tie",
        "behavior_variable": _BEHAVIOR_VARIABLE,
        "waves": waves,
    })
    provenance = {
        "source_archive_url": S50_DOWNLOAD,
        "source_prefix_sha256": _value_hash({"networks": networks, "behavior": behavior}),
        "hash_scope": "canonical network1/2 values and first two behavior columns only",
        "consumed_network_members": list(_NETWORK_MEMBERS),
        "consumed_behavior_member": _BEHAVIOR_MEMBER,
        "consumed_behavior_columns_1based": [1, 2],
        "actor_count": 50,
        "wave_count": 2,
        "last_history_time_index": 1,
        "published_illustrative_tie_counts": list(_EXPECTED_TIES),
        "future_network_members_read": False,
        "future_behavior_columns_parsed": False,
        "source_claim_verified": False,
        "sample_has_valid_population_boundary": False,
        "suitable_for_empirical_influence_estimation": False,
        "causal_effect_identified": False,
        "forecast_accuracy_established": False,
        "usage_limit": "numerical illustration only: s50 is not a properly delineated network",
    }
    return panel, provenance


def load_s50_forecast_target(path: str | Path) -> dict[str, object]:
    """Read the later behavior column for separate evaluation, without a graph.

    The earlier two tokens locate column 3 but are not parsed or validated.
    Source revision binds only the ordered target values.  The format and
    source reference do not qualify this teaching sample as a population.
    """
    members = _selected_members(path, (_BEHAVIOR_MEMBER,))
    values = [row[0] for row in _behavior_columns(members[_BEHAVIOR_MEMBER], (2,), target=True)]
    return {
        "schema": "sociolab.behavior-target.v1",
        "dataset_id": _DATASET_ID,
        "origin": "external_observation",
        "source_reference": S50_SOURCE,
        "behavior_variable": _BEHAVIOR_VARIABLE,
        "time_index": 2,
        "source_revision": _value_hash(values),
        "behavior": dict(zip(_ACTORS, values, strict=True)),
    }
