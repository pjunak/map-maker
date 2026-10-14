"""Bounded, portable current bathymetry inputs with retained world identity."""

import json
import os
import tempfile
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import cast

from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.adapters.world_geology import world_fingerprint
from map_maker.terrain.adapters.world_project import (
    world_project_document,
    world_project_from_bytes,
)
from map_maker.terrain.domain.world_bathymetry import BathymetryInputs, BathymetrySettings
from map_maker.terrain.domain.world_context import WORLD_CONTEXT_ALGORITHM

BATHYMETRY_INPUT_SCHEMA = "map-maker.world-bathymetry-inputs"
BATHYMETRY_INPUT_VERSION = 1
BATHYMETRY_EXTENSION = ".bathy.json"
MAX_BATHYMETRY_INPUT_BYTES = 40 * 1024 * 1024


def inputs_document(inputs: BathymetryInputs) -> dict[str, object]:
    settings = asdict(inputs.settings)
    for key in ("shelf_width_km", "shelf_depth_m", "slope_width_km", "basin_depth_m"):
        settings[key] = float(settings[key])
    return {
        "schema": BATHYMETRY_INPUT_SCHEMA,
        "version": BATHYMETRY_INPUT_VERSION,
        "geography_algorithm": WORLD_CONTEXT_ALGORITHM,
        "world_sha256": world_fingerprint(inputs.world),
        "world": world_project_document(inputs.world),
        "ocean_ids": list(inputs.ocean_ids),
        "settings": settings,
    }


def _record(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(cast(dict[str, object], value)) != fields:
        raise ValueError(f"Expected exactly these bathymetry fields: {', '.join(sorted(fields))}.")
    return cast(dict[str, object], value)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate bathymetry field: {key}.")
        result[key] = value
    return result


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Bathymetry widths and depths must be numbers.")
    return float(value)


def inputs_from_bytes(raw: bytes) -> BathymetryInputs:
    if len(raw) > MAX_BATHYMETRY_INPUT_BYTES:
        raise ValueError("Bathymetry inputs exceed 40 MiB.")
    try:
        value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        record = _record(
            value,
            {
                "schema",
                "version",
                "geography_algorithm",
                "world_sha256",
                "world",
                "ocean_ids",
                "settings",
            },
        )
        if (
            record["schema"] != BATHYMETRY_INPUT_SCHEMA
            or type(record["version"]) is not int
            or record["version"] != BATHYMETRY_INPUT_VERSION
            or record["geography_algorithm"] != WORLD_CONTEXT_ALGORITHM
        ):
            raise ValueError("Unsupported bathymetry input format or geographic water identity.")
        world = world_project_from_bytes(canonical_json(record["world"]))
        if world_fingerprint(world) != record["world_sha256"]:
            raise ValueError("Bathymetry world fingerprint does not match the retained world.")
        settings = _record(
            record["settings"],
            {
                "latitude_cells",
                "shelf_width_km",
                "shelf_depth_m",
                "slope_width_km",
                "basin_depth_m",
            },
        )
        rows = settings["latitude_cells"]
        if type(rows) is not int:
            raise ValueError("Bathymetry latitude cells must be an integer.")
        ids = record["ocean_ids"]
        if not isinstance(ids, list):
            raise ValueError("Ocean IDs must be an array of integers.")
        selected = cast(list[object], ids)
        if any(type(i) is not int for i in selected):
            raise ValueError("Ocean IDs must be integers.")
        return BathymetryInputs(
            world,
            tuple(cast(list[int], selected)),
            BathymetrySettings(
                rows,
                *(
                    _number(settings[k])
                    for k in ("shelf_width_km", "shelf_depth_m", "slope_width_km", "basin_depth_m")
                ),
            ),
        )
    except (UnicodeError, json.JSONDecodeError, OverflowError, RecursionError) as error:
        raise ValueError(f"Invalid bathymetry inputs: {error}") from error


def read_bathymetry_inputs(path: Path) -> tuple[BathymetryInputs, str]:
    with path.open("rb") as stream:
        data = stream.read(MAX_BATHYMETRY_INPUT_BYTES + 1)
    return inputs_from_bytes(data), sha256(data).hexdigest()


def bathymetry_file_hash(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BATHYMETRY_INPUT_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(data) > MAX_BATHYMETRY_INPUT_BYTES:
        raise ValueError("Existing bathymetry input exceeds 40 MiB; choose another path.")
    return sha256(data).hexdigest()


def write_bathymetry_inputs(inputs: BathymetryInputs, path: Path, expected_hash: str | None) -> str:
    if not path.name.endswith(BATHYMETRY_EXTENSION):
        raise ValueError(f"Save bathymetry inputs with the {BATHYMETRY_EXTENSION} extension.")
    data = canonical_json(inputs_document(inputs))
    if len(data) > MAX_BATHYMETRY_INPUT_BYTES:
        raise ValueError("Bathymetry inputs exceed 40 MiB.")
    pending: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".bathy-", delete=False
        ) as stream:
            pending = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if bathymetry_file_hash(path) != expected_hash:
            raise ValueError("Bathymetry file changed outside the editor; reopen or use Save As.")
        os.replace(pending, path)
        pending = None
    finally:
        if pending is not None:
            Path(pending).unlink(missing_ok=True)
    return sha256(data).hexdigest()
