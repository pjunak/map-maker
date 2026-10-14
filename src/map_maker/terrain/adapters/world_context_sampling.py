# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportUnknownVariableType=false
"""Transfer verified spherical context to fixed metric support, with distance intervals."""

import json
from hashlib import sha256
from typing import cast

import numpy as np
from numpy.typing import NDArray
from rasterio.warp import transform

from map_maker.terrain.adapters.world_context import context_document, context_input_sha256
from map_maker.terrain.adapters.world_geology import geology_document, world_fingerprint
from map_maker.terrain.domain.coordinates import EndpointGrid, LocalMetricFrame
from map_maker.terrain.domain.terrain_context import (
    MAX_CONTEXT_SAMPLES_PER_AXIS,
    TerrainWorldContext,
)
from map_maker.terrain.domain.world_terrain import WorldTerrainSource
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.terrain_context import context_arrays
from map_maker.terrain.pipeline.world_context import WorldContext


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")


def context_numeric_identity(context: WorldContext) -> str:
    """Identity of actual geographic numeric inputs, independent of previews/ZIP containers."""
    digest = sha256(_json(context_document(context, {}, {})))
    arrays = {name: getattr(context, name) for name in (
        "land_fraction", "water_body", "support_flags", "cell_area_km2", "east_opening_km",
        "south_opening_km", "shore_distance_km", "water_exposure", "exposure_mixed_support",
    )}
    arrays.update({f"connectivity.{name}": value
                   for name, value in context.connectivity.arrays().items()})
    for name, array in sorted(arrays.items()):
        digest.update(name.encode("ascii"))
        digest.update(array.astype(array.dtype.newbyteorder("<"), copy=False).tobytes())
    return digest.hexdigest()


def sample_geographic_context(
    context: WorldContext, longitude: NDArray[np.float64], latitude: NDArray[np.float64],
) -> dict[str, NDArray[np.float64] | NDArray[np.float32] | NDArray[np.int32] | NDArray[np.uint8]]:
    grid = context.grid
    rows, columns = grid.shape
    step = grid.angular_step_deg
    row_position = (90-latitude)/step - 0.5
    if (not np.all(np.isfinite(longitude)) or not np.all(np.isfinite(latitude))
            or np.any(row_position < 0) or np.any(row_position > rows-1)):
        raise ValueError("This context transfer needs polar support; choose a non-polar domain.")
    column_position = ((longitude-grid.frame.central_meridian_deg+180) % 360)/step-0.5
    row = np.minimum(np.floor(row_position).astype(np.int64), rows-2)
    column = np.floor(column_position).astype(np.int64)
    fy, fx = row_position-row, column_position-column
    lower = np.zeros(latitude.shape, dtype=np.float64)
    upper = np.zeros(latitude.shape, dtype=np.float64)
    fraction = np.zeros_like(latitude)
    exposure = np.zeros((8, *latitude.shape), dtype=np.float64)
    mixed = np.zeros_like(exposure)
    lat_radians = np.radians(latitude)
    for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        r, c = row+oy, (column+ox) % columns
        weight = (fx if ox else 1-fx) * (fy if oy else 1-fy)
        source_lon = grid.frame.central_meridian_deg+(c+0.5)*step-180
        source_lat = np.radians(90-(r+0.5)*step)
        hav = (np.sin((source_lat-lat_radians)/2)**2 + np.cos(source_lat)*np.cos(lat_radians)
               * np.sin(np.radians(source_lon-longitude)/2)**2)
        distance = 2*grid.frame.radius_km*np.arcsin(np.sqrt(np.clip(hav, 0, 1))) + 1e-8
        shore = context.shore_distance_km[r, c]
        if not np.all(np.isfinite(shore)):
            raise ValueError("Context has no finite shoreline support for this terrain domain.")
        # Convex combinations preserve bounds and remain continuous as vertices
        # enter/leave the bilinear stencil. Min/max of four cones would jump.
        lower += weight*(shore-context.shore_sampling.max_error_km-distance)
        upper += weight*(shore+distance)
        fraction += weight*context.land_fraction[r, c]
        exposure += weight*context.water_exposure[:, r, c]
        mixed += weight*context.exposure_mixed_support[:, r, c]
    lower = np.maximum(lower, 0)
    if np.any(lower > upper+1e-7):
        raise ValueError("Geographic context has inconsistent shoreline-distance intervals.")
    nr = np.floor(row_position+0.5).astype(np.int64)
    nc = np.floor(column_position+0.5).astype(np.int64) % columns
    return {
        "shore_lower_km": lower, "shore_upper_km": np.maximum(lower, upper),
        "latitude_deg": latitude, "longitude_deg": (longitude+180) % 360-180,
        "land_fraction": np.clip(fraction, 0, 1),
        "water_body": context.water_body[nr, nc], "support_flags": context.support_flags[nr, nc],
        "water_exposure": np.clip(exposure, 0, 1).astype(np.float32),
        "exposure_mixed_support": np.clip(mixed, 0, 1).astype(np.float32),
    }


def bind_world_context(
    source: WorldTerrainSource, context: WorldContext, runtime: dict[str, object], *,
    cancellation: CancellationToken | None = None,
) -> TerrainWorldContext:
    check_cancelled(cancellation)
    if world_fingerprint(source.world) != world_fingerprint(context.world.project):
        raise ValueError("Terrain and context must use the same world source, frame and ownership.")
    frame = LocalMetricFrame(source.coastline.bounds, source.object_scale_km)
    grid = EndpointGrid.for_extent(frame.extent_km, MAX_CONTEXT_SAMPLES_PER_AXIS)
    x, y = np.meshgrid(np.linspace(0, frame.width_km, grid.width),
                       np.linspace(0, frame.height_km, grid.height))
    east = x/frame.km_per_source_unit + source.coastline.bounds[0]
    north = -(y/frame.km_per_source_unit + source.coastline.bounds[1])
    longitude, latitude = cast(tuple[list[float], list[float]], transform(
        source.projection.projected_crs, source.projection.geographic_crs,
        east.ravel().tolist(), north.ravel().tolist(),
    ))
    check_cancelled(cancellation)
    arrays = sample_geographic_context(
        context, np.asarray(longitude, dtype=np.float64).reshape(grid.shape),
        np.asarray(latitude, dtype=np.float64).reshape(grid.shape),
    )
    bound = TerrainWorldContext(
        world_fingerprint(source.world), context_input_sha256(context),
        context_numeric_identity(context), sha256(_json(runtime)).hexdigest(),
        context.grid.settings.latitude_cells, source.coastline.bounds, source.projection,
        grid, context.water_bodies, context.connectivity.fragmented_bodies,
        context.shore_sampling.max_error_km,
        (None if source.geology is None
         else sha256(_json(geology_document(source.geology))).hexdigest()),
        **{name: array.astype(array.dtype.newbyteorder("<"), copy=False).tobytes()
           for name, array in arrays.items()},
    )
    context_arrays(bound)
    check_cancelled(cancellation)
    return bound
