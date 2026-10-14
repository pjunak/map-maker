"""Portable current-format world projects; original SVG is embedded and fingerprinted."""

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import cast

from map_maker.terrain.adapters.world_svg import WORLD_IMPORTER, parse_world_svg
from map_maker.terrain.domain.world import (
    WORLD_PREPARATION,
    WorldAssignment,
    WorldContinent,
    WorldFrame,
    WorldProject,
)

WORLD_SCHEMA = "map-maker.world-project"
WORLD_VERSION = 1
WORLD_EXTENSION = ".world.json"
MAX_WORLD_PROJECT_BYTES = 32 * 1024 * 1024


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(cast("dict[str, object]", value)) != keys:
        raise ValueError(f"Expected exactly these world fields: {', '.join(sorted(keys))}.")
    return cast("dict[str, object]", value)


def _keys(value: object) -> set[str]:
    return set(cast("dict[str, object]", value)) if isinstance(value, dict) else set()


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("World names, IDs and source text must be non-empty strings.")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("World coordinates and radius must be numbers.")
    return float(value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("World collections must be JSON arrays.")
    return cast("list[object]", value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate world field: {key}.")
        result[key] = value
    return result


def world_project_document(project: WorldProject) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": WORLD_SCHEMA,
        "version": WORLD_VERSION,
        "importer": WORLD_IMPORTER,
        "preparation": WORLD_PREPARATION,
        "name": project.name,
        "source": {
            "name": project.source.name,
            "sha256": project.source.sha256,
            "svg": project.source.svg,
        },
        "frame": {
            "projection": "plate-carree",
            "bounds": [float(value) for value in project.frame.bounds],
            "radius_km": float(project.frame.radius_km),
            "central_meridian_deg": float(project.frame.central_meridian_deg),
        },
        "continents": [asdict(c) for c in sorted(project.continents, key=lambda c: c.id)],
        "assignments": [asdict(a) for a in sorted(project.assignments, key=lambda a: a.feature_id)],
    }
    # Written only when stated, so projects without it keep their bytes and identity.
    if project.coast_detail_km is not None:
        document["coast_detail_km"] = project.coast_detail_km
    return document


def read_world_project(path: Path) -> WorldProject:
    with path.open("rb") as stream:
        raw = stream.read(MAX_WORLD_PROJECT_BYTES + 1)
    return world_project_from_bytes(raw)


def world_project_from_bytes(raw: bytes) -> WorldProject:
    """Decode an already captured (and optionally hash-verified) source snapshot."""
    if len(raw) > MAX_WORLD_PROJECT_BYTES:
        raise ValueError("World project exceeds 32 MiB.")
    try:
        value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        fields = {
            "schema",
            "version",
            "importer",
            "preparation",
            "name",
            "source",
            "frame",
            "continents",
            "assignments",
        }
        document = _mapping(value, fields | (_keys(value) & {"coast_detail_km"}))
        version = document["version"]
        if (
            document["schema"] != WORLD_SCHEMA
            or type(version) is not int
            or version != WORLD_VERSION
            or document["importer"] != WORLD_IMPORTER
            or document["preparation"] != WORLD_PREPARATION
        ):
            raise ValueError(
                "Unsupported world format, importer or preparation version; import the SVG again."
            )
        source_record = _mapping(document["source"], {"name", "sha256", "svg"})
        source = parse_world_svg(_string(source_record["svg"]), _string(source_record["name"]))
        if source.sha256 != source_record["sha256"]:
            raise ValueError("Embedded world SVG fingerprint does not match its recorded source.")
        frame_record = _mapping(
            document["frame"], {"projection", "bounds", "radius_km", "central_meridian_deg"}
        )
        if frame_record["projection"] != "plate-carree":
            raise ValueError("Declare a full-world spherical Plate Carree frame.")
        bounds = tuple(_number(v) for v in _list(frame_record["bounds"]))
        if len(bounds) != 4:
            raise ValueError("World frame needs four source bounds.")
        frame = WorldFrame(
            (bounds[0], bounds[1], bounds[2], bounds[3]),
            _number(frame_record["radius_km"]),
            _number(frame_record["central_meridian_deg"]),
        )
        continents: list[WorldContinent] = []
        for item in _list(document["continents"]):
            record = _mapping(item, {"id", "name"})
            continents.append(WorldContinent(_string(record["id"]), _string(record["name"])))
        assignments: list[WorldAssignment] = []
        for item in _list(document["assignments"]):
            record = _mapping(item, {"feature_id", "continent_id", "role"})
            role = _string(record["role"])
            if role not in ("mainland", "island", "exclude"):
                raise ValueError("Unknown world shape role.")
            owner = None if record["continent_id"] is None else _string(record["continent_id"])
            assignments.append(WorldAssignment(_string(record["feature_id"]), owner, role))
        return WorldProject(
            _string(document["name"]), source, frame, tuple(continents), tuple(assignments),
            _number(document["coast_detail_km"]) if "coast_detail_km" in document else None,
        )
    except (UnicodeError, json.JSONDecodeError, OverflowError, RecursionError) as error:
        raise ValueError(f"Invalid world project: {error}") from error


def write_world_project(project: WorldProject, path: Path) -> None:
    """Atomic authored-input save. Spatial validation belongs to the application."""
    if not path.name.endswith(WORLD_EXTENSION):
        raise ValueError(f"Save world projects with the {WORLD_EXTENSION} extension.")
    data = (
        json.dumps(world_project_document(project), ensure_ascii=False, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    if len(data) > MAX_WORLD_PROJECT_BYTES:
        raise ValueError("World project exceeds 32 MiB.")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".world-", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
