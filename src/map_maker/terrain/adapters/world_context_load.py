"""Verify completed context bundles and decode bounded, immutable numeric snapshots."""

import io
import json
from collections.abc import Callable
from hashlib import sha256
from itertools import pairwise
from math import isfinite, pi
from pathlib import Path
from typing import Any, cast

import numpy as np
from PIL import Image

from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.adapters.numeric import read_numeric_archive
from map_maker.terrain.adapters.world_connectivity import read_water_connectivity
from map_maker.terrain.adapters.world_context import (
    CONTEXT_OUTPUTS,
    CONTEXT_PREVIEWS,
    CONTEXT_SCHEMA,
    CONTEXT_VERSION,
    MAX_CONTEXT_MANIFEST_BYTES,
    context_document,
)
from map_maker.terrain.adapters.world_project import (
    MAX_WORLD_PROJECT_BYTES,
    world_project_from_bytes,
)
from map_maker.terrain.adapters.world_svg import WORLD_IMPORTER
from map_maker.terrain.domain.world import WORLD_PREPARATION
from map_maker.terrain.domain.world_context import (
    MAX_SHORE_SAMPLES,
    MIXED_COAST,
    SPLIT_WATER,
    SUBCELL_LAND,
    SUBCELL_WATER,
    WORLD_CONTEXT_ALGORITHM,
    ConnectedWater,
    ShoreSampling,
    SphericalContextGrid,
    WorldContextSettings,
    shore_spacing_km,
)
from map_maker.terrain.pipeline.world import prepare_world_map
from map_maker.terrain.pipeline.world_context import WorldContext, validate_water_partition


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Context records must be JSON objects.")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate context field: {key}.")
        result[key] = value
    return result


def _digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("Context identity must be a lowercase SHA-256 digest.")
    return value


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Context file missing or linked: {path.name}")
    size = path.stat().st_size
    if not 0 < size <= limit:
        raise ValueError(f"Context file is empty or oversized: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(size + 1)
    if len(data) != size:
        raise ValueError(f"Context file changed size while reading: {path.name}")
    return data


def _runtime(value: object) -> dict[str, object]:
    record = _object(value)
    strings = {
        "map_maker_version",
        "package_source_sha256",
        "python",
        "implementation",
        "platform",
        "machine",
        "byteorder",
        "geos",
        "gdal",
        "proj",
    }
    if set(record) != strings | {"dependencies"} or any(
        not isinstance(record[key], str) or not record[key] for key in strings
    ):
        raise ValueError("Context producer runtime is incomplete.")
    _digest(record["package_source_sha256"])
    dependencies = _object(record["dependencies"])
    if (
        set(dependencies)
        != {"numpy", "scipy", "Pillow", "shapely", "svgelements", "rasterio", "affine"}
        or any(not isinstance(v, str) or not v for v in dependencies.values())
        or record["byteorder"] not in ("little", "big")
    ):
        raise ValueError("Context producer dependencies or byte order are invalid.")
    return record


def read_world_context(
    source: Path,
    *,
    checkpoint: Callable[[], None],
) -> tuple[WorldContext, dict[str, object]]:
    """Inspect a supported format without requiring the producer's exact runtime.

    Hashes certify internal integrity, not origin/authenticity. This validates
    numeric invariants and rebuilds source water incidence, but does not rerun
    shoreline distances or exposure fields.
    """
    checkpoint()
    manifest_path = source / "context.json" if source.is_dir() else source
    if manifest_path.name != "context.json":
        raise ValueError("Select a completed context.json or its result directory.")
    root = manifest_path.parent
    raw = _read(manifest_path, MAX_CONTEXT_MANIFEST_BYTES)
    try:
        doc = _object(json.loads(raw, object_pairs_hook=_unique_object))
        if (
            doc.get("schema") != CONTEXT_SCHEMA
            or type(doc.get("version")) is not int
            or doc["version"] != CONTEXT_VERSION
            or doc.get("algorithm") != WORLD_CONTEXT_ALGORITHM
            or doc.get("importer") != WORLD_IMPORTER
            or doc.get("preparation") != WORLD_PREPARATION
        ):
            raise ValueError("Unsupported context format or algorithm; generate context again.")
        fingerprint = _digest(doc.get("context_sha256"))
        if (
            sha256(
                canonical_json({k: v for k, v in doc.items() if k != "context_sha256"})
            ).hexdigest()
            != fingerprint
        ):
            raise ValueError("Context manifest fingerprint does not match its contents.")
        runtime = _runtime(doc["runtime"])
        settings = _object(doc["settings"])
        if set(settings) != {"latitude_cells"}:
            raise ValueError("Unknown context settings.")
        config = WorldContextSettings(settings["latitude_cells"])
        outputs = _object(doc["outputs"])
        if set(outputs) != set(CONTEXT_OUTPUTS):
            raise ValueError("Context products do not match the current contract.")
        products: dict[str, bytes] = {}
        for name in CONTEXT_OUTPUTS:
            checkpoint()
            record = _object(outputs[name])
            limit = MAX_WORLD_PROJECT_BYTES if name == "input.world.json" else 24 * 1024 * 1024
            if name == "connectivity.npz":
                limit = 64 * 1024 * 1024
            if (
                set(record) != {"bytes", "sha256"}
                or type(record["bytes"]) is not int
                or not 0 < record["bytes"] <= limit
            ):
                raise ValueError(f"Invalid context product record: {name}")
            data = _read(root / name, record["bytes"])
            if len(data) != record["bytes"] or sha256(data).hexdigest() != _digest(
                record["sha256"]
            ):
                raise ValueError(f"Context product failed hash verification: {name}")
            products[name] = data
        world = prepare_world_map(world_project_from_bytes(products["input.world.json"]))
        grid = SphericalContextGrid(world.project.frame, config)
        rows, columns = grid.shape
        arrays = read_numeric_archive(
            products["geography.npz"],
            {
                "land_fraction": (grid.shape, "<f8"),
                "water_body": (grid.shape, "<i4"),
                "support_flags": (grid.shape, "u1"),
                "east_opening_km": (grid.shape, "<f8"),
                "south_opening_km": (grid.shape, "<f8"),
                "cell_area_km2": ((rows,), "<f8"),
                "latitude_deg": ((rows,), "<f8"),
                "longitude_deg": ((columns,), "<f8"),
            },
        )
        if any(not np.isfinite(a).all() for a in arrays.values()):
            raise ValueError("Context arrays must contain finite numbers.")
        for key, expected in (
            ("cell_area_km2", [grid.cell_area_km2(r) for r in range(rows)]),
            ("latitude_deg", [grid.latitude_deg(r) for r in range(rows)]),
            ("longitude_deg", [grid.longitude_deg(c) for c in range(columns)]),
        ):
            if not np.allclose(arrays[key], expected, rtol=1e-12, atol=0):
                raise ValueError(f"Context coordinates disagree with the source frame: {key}")
        fraction, flags = arrays["land_fraction"], arrays["support_flags"]
        water = arrays["water_body"]
        if np.any((fraction < 0) | (fraction > 1)) or np.any(flags > 15):
            raise ValueError("Context land fractions or support flags are out of range.")
        mixed = (fraction > 0) & (fraction < 1)
        subcell = flags & (SUBCELL_LAND | SUBCELL_WATER)
        if (
            not np.array_equal((flags & MIXED_COAST) != 0, mixed)
            or np.any((subcell != 0) != mixed)
            or np.any(subcell == (SUBCELL_LAND | SUBCELL_WATER))
            or np.any(((flags & SPLIT_WATER) != 0) & (water == 0))
        ):
            raise ValueError("Context support flags disagree with surface coverage.")
        bodies: list[ConnectedWater] = []
        records: object = doc["water_bodies"]
        if not isinstance(records, list):
            raise ValueError("Context water bodies must be an array.")
        for index, item in enumerate(cast(list[object], records), start=1):
            record = _object(item)
            if (
                set(record) != {"id", "area_km2", "crosses_seam", "displayed_cells"}
                or type(record["id"]) is not int
                or record["id"] != index
                or type(record["crosses_seam"]) is not bool
                or type(record["displayed_cells"]) is not int
                or record["displayed_cells"] != int(np.count_nonzero(water == index))
                or type(record["area_km2"]) not in (float, int)
                or not isfinite(record["area_km2"])
                or record["area_km2"] <= 0
            ):
                raise ValueError("Invalid context water body record.")
            bodies.append(ConnectedWater(**record))
        if (
            np.any((water < 0) | (water > len(bodies)))
            or np.any((fraction < 1) & (water == 0))
            or any(a.area_km2 < b.area_km2 for a, b in pairwise(bodies))
        ):
            raise ValueError("Context water IDs or area ranking are inconsistent.")
        for name, maximum in (
            ("east_opening_km", grid.north_south_spacing_km),
            (
                "south_opening_km",
                np.array([grid.south_edge_length_km(r) for r in range(rows)])[:, None],
            ),
        ):
            if np.any(arrays[name] < 0) or np.any(arrays[name] > maximum * (1 + 1e-12)):
                raise ValueError(f"Context water opening exceeds its shared edge: {name}")
        measured = float(np.sum(fraction * arrays["cell_area_km2"][:, None]))
        tolerance = max(grid.frame.surface_area_km2 * 1e-9, 1e-8)
        areas = _object(doc["areas_km2"])
        error = areas["land_conservation_error"]
        if (
            type(error) not in (float, int)
            or not isfinite(error)
            or abs(error) > tolerance
            or abs(measured - world.land_area_km2) > tolerance
            or abs(measured + sum(b.area_km2 for b in bodies) - grid.frame.surface_area_km2)
            > tolerance
        ):
            raise ValueError("Context does not conserve prepared source or sphere area.")
        exposure = read_numeric_archive(
            products["exposure.npz"],
            {
                "shore_distance_km": (grid.shape, "<f8"),
                "water_exposure": ((8, rows, columns), "<f4"),
                "exposure_mixed_support": ((8, rows, columns), "<f4"),
            },
        )
        shore_record = _object(doc["shore_distance"])
        samples, bound = shore_record["sample_count"], shore_record["max_error_km"]
        if (
            type(samples) is not int
            or not 0 <= samples <= MAX_SHORE_SAMPLES
            or type(bound) not in (int, float)
            or not isfinite(bound)
            or not 0 <= bound <= shore_spacing_km(grid) / 2 * (1 + 1e-12)
        ):
            raise ValueError("Invalid shoreline sampling support.")
        shore = exposure["shore_distance_km"]
        if samples == 0:
            if (
                bound != 0
                or not np.isnan(shore).all()
                or not (np.all(fraction == 0) or np.all(fraction == 1))
            ):
                raise ValueError("Missing shoreline distances require a shore-free world.")
        elif not np.isfinite(shore).all() or np.any(
            (shore < 0) | (shore > pi * grid.frame.radius_km)
        ):
            raise ValueError("Shore distance must be finite and within half the circumference.")
        for key in ("water_exposure", "exposure_mixed_support"):
            value = exposure[key]
            if not np.isfinite(value).all() or np.any((value < 0) | (value > 1)):
                raise ValueError("Geographic exposure fractions must be finite and within 0-1.")
        connectivity = read_water_connectivity(
            products["connectivity.npz"],
            _object(doc["connectivity"]),
            world,
            grid,
            checkpoint=checkpoint,
        )
        validate_water_partition(connectivity, grid, fraction, tuple(bodies))
        context = WorldContext(
            world,
            grid,
            fraction,
            water,
            flags,
            arrays["cell_area_km2"],
            arrays["east_opening_km"],
            arrays["south_opening_km"],
            shore,
            exposure["water_exposure"],
            exposure["exposure_mixed_support"],
            ShoreSampling(samples, bound),
            tuple(bodies),
            measured,
            error,
            connectivity,
        )
        if canonical_json(doc) != canonical_json(context_document(context, runtime, outputs)):
            raise ValueError("Context metadata disagrees with its source or numeric products.")
        for name in CONTEXT_PREVIEWS:
            checkpoint()
            factor = 3 if name == "gateways.png" else 1
            with Image.open(io.BytesIO(products[name])) as preview:
                if (
                    preview.format != "PNG"
                    or preview.mode != "RGB"
                    or preview.size != (columns * factor, rows * factor)
                ):
                    raise ValueError(f"Invalid context preview dimensions or format: {name}")
                preview.verify()
        # Check every captured input again before accepting a possibly copied bundle.
        for name, captured in {"context.json": raw, **products}.items():
            checkpoint()
            if sha256(_read(root / name, len(captured))).digest() != sha256(captured).digest():
                raise ValueError(f"Context changed while opening: {name}")
        return context, runtime
    except (
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        OverflowError,
        RecursionError,
    ) as error:
        raise ValueError(f"Invalid context bundle: {error}") from error
