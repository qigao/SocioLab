"""Read the published s50 teaching archive; never implement an SAOM solver.

The Oxford s50 subset is NOT a properly delineated social network.  Its
50-person, three-wave matrices are suitable only for numerical/software
compatibility tests, not empirical population causal inference.  The source
ZIP is supplied by the caller; no data are vendored or fetched implicitly.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from .panels import LongitudinalPanel, longitudinal_structure_report

S50_SOURCE = "https://www.stats.ox.ac.uk/~snijders/siena/s50_data.htm"
S50_DOWNLOAD = "https://www.stats.ox.ac.uk/~snijders/siena/s50_data.zip"
_FILENAMES = (
    "s50-network1.dat", "s50-network2.dat", "s50-network3.dat",
    "s50-alcohol.dat",
)
_EXPECTED_TIES = (113, 116, 122)  # Published s50 / Glasgow numerical example
_ARCHIVE_MAX_BYTES = 2_000_000
_MEMBER_MAX_BYTES = 160_000


def _digest(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()


def _source_members(archive_bytes: bytes) -> dict[str, bytes]:
    if not archive_bytes or len(archive_bytes) > _ARCHIVE_MAX_BYTES:
        raise ValueError("s50 archive must be nonempty and within byte limit")
    try:
        with ZipFile(BytesIO(archive_bytes)) as archive:
            selected: dict[str, bytes] = {}
            for item in archive.infolist():
                if item.is_dir():
                    continue
                normalized = PurePosixPath(item.filename)
                if (normalized.is_absolute() or ".." in normalized.parts
                        or "\\" in item.filename):
                    raise ValueError("s50 archive has an unsafe member path")
                name = normalized.name
                if name not in _FILENAMES:
                    continue
                if name in selected:
                    raise ValueError("s50 archive contains duplicate required files")
                if item.file_size > _MEMBER_MAX_BYTES:
                    raise ValueError("s50 member exceeds bounded input size")
                selected[name] = archive.read(item)
    except BadZipFile as exc:
        raise ValueError("s50 source is not a valid ZIP archive") from exc
    if set(selected) != set(_FILENAMES):
        raise ValueError("s50 archive lacks required friendship/alcohol observations")
    return selected


def _integer_matrix(data: bytes, *, name: str, rows: int, columns: int,
                    allowed: frozenset[int]) -> list[list[int]]:
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name} must contain plain ASCII integer data") from exc
    if len(lines) != rows:
        raise ValueError(f"{name} must have exactly {rows} rows")
    result: list[list[int]] = []
    for line in lines:
        parts = line.split()
        if len(parts) != columns:
            raise ValueError(f"{name} must have exactly {columns} columns")
        if any(not item.isdecimal() for item in parts):
            raise ValueError(f"{name} must contain nonnegative integer codes")
        values = [int(item) for item in parts]
        if not set(values).issubset(allowed):
            raise ValueError(f"{name} contains missing or unsupported observations")
        result.append(values)
    return result


def load_s50_archive(path: str | Path) -> tuple[LongitudinalPanel, dict[str, object]]:
    """Read official-format ZIP for a descriptive *numerical illustration*.

    No implied certificate of authorship is created by a valid filename or
    matrix shape.  Preserve archive digest so a reviewer can compare source.
    """
    source = Path(path).read_bytes()
    members = _source_members(source)
    networks = [
        _integer_matrix(members[name], name=name, rows=50, columns=50,
                        allowed=frozenset({0, 1}))
        for name in _FILENAMES[:3]
    ]
    alcohol = _integer_matrix(
        members["s50-alcohol.dat"], name="s50-alcohol.dat",
        rows=50, columns=3, allowed=frozenset(range(1, 6)),
    )
    actors = [f"p{idx:03d}" for idx in range(1, 51)]
    waves = []
    for index, matrix in enumerate(networks):
        edges = []
        for row, values in enumerate(matrix):
            if values[row] != 0 or sum(values) > 12:
                raise ValueError("s50 self-nominations/overlimit nominations are invalid")
            for column, value in enumerate(values):
                if value:
                    edges.append([actors[row], actors[column]])
        if len(edges) != _EXPECTED_TIES[index]:
            raise ValueError("s50 friendship ties differ from the documented reference")
        waves.append({
            "time_index": index,
            "source_revision": _digest(members[_FILENAMES[index]]),
            "network_complete": True,
            "edges": sorted(edges),
            "behavior": {actor: alcohol[i][index]
                         for i, actor in enumerate(actors)},
        })
    panel = LongitudinalPanel.from_mapping({
        "schema": "sociolab.longitudinal.v1",
        "dataset_id": "teenage-friends-s50-numerical-example",
        "origin": "external_observation",
        "source_reference": S50_SOURCE,
        "actors": actors,
        "relation": "directed_observed_social_tie",
        "behavior_variable": "alcohol_consumption_ordinal_1_to_5",
        "waves": waves,
    })
    provenance = {
        "source_archive_url": S50_DOWNLOAD,
        "source_archive_sha256": _digest(source),
        "source_member_sha256": {
            name: _digest(members[name]) for name in _FILENAMES
        },
        "published_illustrative_tie_counts": list(_EXPECTED_TIES),
    }
    return panel, provenance


def s50_reference_report(path: str | Path) -> dict[str, object]:
    panel, provenance = load_s50_archive(path)
    report = longitudinal_structure_report(panel)
    return {
        **report,
        **provenance,
        "source_claim_verified": False,
        "sample_has_valid_population_boundary": False,
        "suitable_for_empirical_influence_estimation": False,
        "saom_model_fitted": False,
        "causal_effect_identified": False,
        "usage_limit": "numerical illustration only: s50 is not a properly delineated network",
    }
