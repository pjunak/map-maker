"""Portable bounded context samples; decoding never allocates from untrusted shapes."""

import base64
import binascii
import io
from typing import Any, cast

import numpy as np

from map_maker.terrain.adapters.numeric import read_numeric_archive
from map_maker.terrain.domain.coordinates import EndpointGrid
from map_maker.terrain.domain.terrain_context import (
    CONTEXT_SAMPLE_FIELDS,
    MAX_CONTEXT_SAMPLES_PER_AXIS,
    TERRAIN_CONTEXT_MODEL,
    TerrainWorldContext,
)
from map_maker.terrain.domain.world_context import ConnectedWater
from map_maker.terrain.domain.world_terrain import WorldTerrainProjection, WorldTerrainSource
from map_maker.terrain.pipeline.terrain_context import (
    context_arrays,
    context_identity,
    context_metadata,
)

MAX_CONTEXT_ARCHIVE_BYTES = 4 * 1024 * 1024


def context_to_json(context: TerrainWorldContext | None) -> dict[str, object] | None:
    if context is None:
        return None
    stream = io.BytesIO()
    np.savez_compressed(stream, allow_pickle=False, **context_arrays(context))
    payload = stream.getvalue()
    if len(payload) > MAX_CONTEXT_ARCHIVE_BYTES:
        raise ValueError("Terrain context exceeds its 4 MiB portable payload budget.")
    return {**context_metadata(context), "binding_sha256": context_identity(context),
            "samples_npz_base64": base64.b64encode(payload).decode("ascii")}


def _record(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(cast(dict[str, Any], value)) != keys:
        raise ValueError("Terrain context fields do not match the current format.")
    return cast(dict[str, Any], value)


def context_from_json(value: object) -> TerrainWorldContext | None:
    if value is None:
        return None
    try:
        data = _record(value, {
            "model", "world_sha256", "context_input_sha256", "context_numeric_sha256",
            "producer_runtime_sha256", "context_latitude_cells", "source_bounds", "projection",
            "grid", "water_bodies", "fragmented_water_bodies", "source_shore_error_km",
            "geology_sha256", "binding_sha256", "samples_npz_base64",
        })
        if data["model"] != TERRAIN_CONTEXT_MODEL:
            raise ValueError("Unsupported world context transfer; prepare the terrain again.")
        grid_data = _record(data["grid"], {"extent_km", "width", "height"})
        grid = EndpointGrid(tuple(grid_data["extent_km"]), grid_data["width"], grid_data["height"])
        if max(grid.width, grid.height) > MAX_CONTEXT_SAMPLES_PER_AXIS:
            raise ValueError("Terrain context exceeds its sample budget.")
        encoded = data["samples_npz_base64"]
        if not isinstance(encoded, str) or len(encoded) > 4*((MAX_CONTEXT_ARCHIVE_BYTES+2)//3):
            raise ValueError("Terrain context payload is oversized.")
        payload = base64.b64decode(encoded, validate=True)
        if len(payload) > MAX_CONTEXT_ARCHIVE_BYTES:
            raise ValueError("Terrain context payload is oversized.")
        specs = {name: (grid.shape if channels == 1 else (channels, *grid.shape), dtype)
                 for name, dtype, channels in CONTEXT_SAMPLE_FIELDS}
        arrays = read_numeric_archive(payload, specs)
        projection = WorldTerrainProjection(**_record(data["projection"], {
            "radius_km", "longitude_deg", "latitude_deg", "maximum_angle_deg",
            "maximum_transverse_scale", "curve_tolerance_m", "source_step_deg",
        }))
        bodies = tuple(ConnectedWater(**_record(item, {
            "id", "area_km2", "crosses_seam", "displayed_cells",
        })) for item in data["water_bodies"])
        context = TerrainWorldContext(
            data["world_sha256"], data["context_input_sha256"], data["context_numeric_sha256"],
            data["producer_runtime_sha256"], data["context_latitude_cells"],
            tuple(data["source_bounds"]), projection, grid, bodies,
            tuple(data["fragmented_water_bodies"]), data["source_shore_error_km"],
            data["geology_sha256"], **{name: array.tobytes() for name, array in arrays.items()},
        )
        context_arrays(context)
        if context_identity(context) != data["binding_sha256"]:
            raise ValueError("Terrain context samples do not match their recorded identity.")
        return context
    except (KeyError, TypeError, OverflowError, binascii.Error) as error:
        raise ValueError(f"Invalid terrain context: {error}") from error


def validate_context_source(
    context: TerrainWorldContext | None, source: WorldTerrainSource | None,
) -> None:
    if context is None:
        return
    # These adapters depend on project persistence through build metadata. Import
    # only at the validation boundary, after module initialization.
    import json
    from hashlib import sha256

    from map_maker.terrain.adapters.world_geology import geology_document, world_fingerprint

    if (source is None or world_fingerprint(source.world) != context.world_sha256
            or source.projection != context.projection
            or source.coastline.bounds != context.source_bounds):
        raise ValueError("Terrain context does not match the retained world source and projection.")
    geology = None if source.geology is None else sha256(json.dumps(
        geology_document(source.geology), sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if geology != context.geology_sha256:
        raise ValueError("Terrain context and retained geology guidance do not match.")
