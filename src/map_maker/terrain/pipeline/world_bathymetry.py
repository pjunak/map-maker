# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A bounded, coast-anchored ocean-depth scenario on the geographic cell grid."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from map_maker.terrain.domain.world_bathymetry import BathymetryInputs, BathymetrySettings
from map_maker.terrain.domain.world_context import SphericalContextGrid
from map_maker.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from map_maker.terrain.pipeline.world import WorldMap
from map_maker.terrain.pipeline.world_context import WorldContext, water_topology


@dataclass(frozen=True, slots=True)
class WorldBathymetry:
    inputs: BathymetryInputs
    context: WorldContext
    centre_water_body: NDArray[np.int32]
    bed_elevation_m: NDArray[np.float32]
    distance_depth_error_m: NDArray[np.float32]

    @property
    def unsampled_ocean_ids(self) -> tuple[int, ...]:
        sampled = set(np.unique(self.centre_water_body).tolist())
        return tuple(i for i in self.inputs.ocean_ids if i not in sampled)

    @property
    def sampled_cells(self) -> int:
        return int(np.count_nonzero(np.isfinite(self.bed_elevation_m)))


def sample_water_centres(
    world: WorldMap,
    grid: SphericalContextGrid,
    cancellation: CancellationToken | None = None,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> NDArray[np.int32]:
    """Actual point membership, not the largest-area water body of a mixed cell."""
    check_cancelled(cancellation)
    land = unary_union([Polygon(c.exterior, c.holes) for f in world.land for c in f.components])
    polygons, ids, _ = water_topology(land, grid.frame, cancellation)
    tree = STRtree(polygons)
    body_ids = np.asarray(ids, dtype=np.int32)
    rows, columns = grid.shape
    x0, y0, _, _ = grid.frame.bounds
    xs = x0 + (np.arange(columns) + 0.5) * grid.frame.width / columns
    result = np.zeros(grid.shape, dtype=np.int32)
    for row in range(rows):
        check_cancelled(cancellation)
        if checkpoint:
            checkpoint()
        y = y0 + (row + 0.5) * grid.frame.height / rows
        points = shapely.points(xs, np.full(columns, y))
        pairs = tree.query(points, predicate="within")
        if pairs.size:
            result[row, pairs[0]] = body_ids[pairs[1]]
    result.flags.writeable = False
    return result


def margin_depth_m(
    distance_km: NDArray[np.float64], settings: BathymetrySettings
) -> NDArray[np.float64]:
    """Positive depth; C1 smooth joins and exactly zero at the vector coast datum."""
    if not np.all(np.isfinite(distance_km)) or np.any(distance_km < 0):
        raise ValueError("Margin distances must be finite, nonnegative kilometres.")
    shelf = np.clip(distance_km / settings.shelf_width_km, 0, 1)
    slope = np.clip((distance_km - settings.shelf_width_km) / settings.slope_width_km, 0, 1)
    shelf = shelf * shelf * (3 - 2 * shelf)
    slope = slope * slope * (3 - 2 * slope)
    return (
        settings.shelf_depth_m * shelf + (settings.basin_depth_m - settings.shelf_depth_m) * slope
    )


def bathymetry_values(
    shore_upper_km: NDArray[np.float64],
    max_error_km: float,
    selected: NDArray[np.bool_],
    settings: BathymetrySettings,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Use a shore-distance lower bound; retain its depth envelope and float rounding.

    The lower bound deliberately creates a shallow/zero strip near the shore.
    Its envelope covers this distance approximation only, not geological uncertainty.
    """
    if not isfinite(max_error_km) or max_error_km < 0:
        raise ValueError("Shore-distance error bound must be finite and nonnegative.")
    upper = shore_upper_km[selected]
    lower = np.maximum(0, upper - max_error_km)
    depth = margin_depth_m(lower, settings)
    upper_depth = margin_depth_m(upper, settings)
    bed = np.full(shore_upper_km.shape, np.nan, dtype=np.float32)
    error = np.full(shore_upper_km.shape, np.nan, dtype=np.float32)
    bed[selected] = -depth.astype(np.float32)
    bound = np.maximum(0, upper_depth - depth) + np.abs(-bed[selected].astype(np.float64) - depth)
    rounded = bound.astype(np.float32)
    error[selected] = np.where(
        rounded.astype(np.float64) < bound, np.nextafter(rounded, np.float32(np.inf)), rounded
    )
    bed.flags.writeable = error.flags.writeable = False
    return bed, error


def generate_world_bathymetry(
    context: WorldContext,
    inputs: BathymetryInputs,
    progress: ProgressCallback | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> WorldBathymetry:
    check_cancelled(cancellation)
    if (
        context.world.project != inputs.world
        or context.grid.shape[0] != inputs.settings.latitude_cells
    ):
        raise ValueError("Bathymetry inputs must match the world and geographic resolution.")
    if not set(inputs.ocean_ids) <= {b.id for b in context.water_bodies}:
        raise ValueError("Selected ocean IDs are absent from this world's connected water.")
    if progress:
        progress(0.05, "Classifying selected ocean centres from retained water geometry")
    centres = sample_water_centres(context.world, context.grid, cancellation)
    selected = np.isin(centres, inputs.ocean_ids)
    if np.any(~np.isfinite(context.shore_distance_km[selected])):
        raise ValueError(
            "Selected ocean samples have no shoreline distance; margin model unavailable."
        )
    check_cancelled(cancellation)
    if progress:
        progress(0.8, "Evaluating the authored shelf, slope and basin depth scenario")
    bed, error = bathymetry_values(
        context.shore_distance_km, context.shore_sampling.max_error_km, selected, inputs.settings
    )
    result = WorldBathymetry(inputs, context, centres, bed, error)
    check_cancelled(cancellation)
    if progress:
        progress(1, "Ocean-depth hypothesis ready; unresolved cells remain flagged")
    check_cancelled(cancellation)
    return result
