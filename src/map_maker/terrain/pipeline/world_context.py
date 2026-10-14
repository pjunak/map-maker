# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Area-conserving geographic context with vector-derived periodic water topology."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_context import (
    MIXED_COAST,
    SPLIT_WATER,
    SUBCELL_LAND,
    SUBCELL_WATER,
    ConnectedWater,
    ShoreSampling,
    SphericalContextGrid,
    WorldContextSettings,
)
from map_maker.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled
from map_maker.terrain.pipeline.world import WorldMap, component_area_km2, components_from_geometry
from map_maker.terrain.pipeline.world_connectivity import (
    WaterConnectivity,
    build_water_connectivity,
)
from map_maker.terrain.pipeline.world_exposure import measure_shore_distance, measure_water_exposure
from map_maker.terrain.pipeline.world_gateways import measure_water_openings


@dataclass(frozen=True, slots=True)
class WorldContext:
    world: WorldMap
    grid: SphericalContextGrid
    land_fraction: NDArray[np.float64]
    water_body: NDArray[np.int32]
    support_flags: NDArray[np.uint8]
    cell_area_km2: NDArray[np.float64]
    east_opening_km: NDArray[np.float64]
    south_opening_km: NDArray[np.float64]
    shore_distance_km: NDArray[np.float64]
    water_exposure: NDArray[np.float32]
    exposure_mixed_support: NDArray[np.float32]
    shore_sampling: ShoreSampling
    water_bodies: tuple[ConnectedWater, ...]
    land_area_km2: float
    area_error_km2: float
    connectivity: WaterConnectivity

    @property
    def mixed_cells(self) -> int:
        return int(np.count_nonzero(self.support_flags & MIXED_COAST))

    @property
    def subcell_land_cells(self) -> int:
        return int(np.count_nonzero(self.support_flags & SUBCELL_LAND))

    @property
    def subcell_water_cells(self) -> int:
        return int(np.count_nonzero(self.support_flags & SUBCELL_WATER))

    @property
    def split_water_cells(self) -> int:
        return int(np.count_nonzero(self.support_flags & SPLIT_WATER))


def _area(geometry: BaseGeometry, frame: WorldFrame) -> float:
    return sum(component_area_km2(c, frame) for c in components_from_geometry(geometry))


def water_topology(
    land: BaseGeometry,
    frame: WorldFrame,
    cancellation: CancellationToken | None,
    *,
    checkpoint: Callable[[], None] = lambda: None,
) -> tuple[list[Polygon], list[int], tuple[ConnectedWater, ...]]:
    checkpoint()
    water = box(*frame.bounds).difference(land)
    polygons = [Polygon(c.exterior, c.holes) for c in components_from_geometry(water)]
    parent = list(range(len(polygons)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    x0, y0, x1, y1 = frame.bounds
    left = LineString(((x0, y0), (x0, y1)))
    right = LineString(((x1, y0), (x1, y1)))
    left_edges = [(i, p.intersection(left)) for i, p in enumerate(polygons) if p.bounds[0] == x0]
    right_edges = [
        (i, affine_transform(p.intersection(right), (0, 0, 0, 1, x0, 0)))
        for i, p in enumerate(polygons)
        if p.bounds[2] == x1
    ]
    crossing: set[int] = set()
    # A positive-length seam opening connects water. Point contacts, including
    # polar contacts, are not finite gateways and must not bypass a land barrier.
    for i, a in left_edges:
        check_cancelled(cancellation)
        checkpoint()
        for j, b in right_edges:
            if a.intersection(b).length > 0:
                parent[root(j)] = root(i)
                crossing.update((i, j))
    groups: dict[int, list[int]] = {}
    for i in range(len(polygons)):
        groups.setdefault(root(i), []).append(i)
    areas = {key: sum(_area(polygons[i], frame) for i in group) for key, group in groups.items()}
    if any(not np.isfinite(area) or area <= 0 for area in areas.values()):
        raise ValueError("A water region is below supported spherical-area precision.")
    ordered = sorted(groups, key=lambda key: (-areas[key], min(groups[key])))
    ids = {key: i + 1 for i, key in enumerate(ordered)}
    bodies = tuple(
        ConnectedWater(ids[key], areas[key], bool(crossing.intersection(groups[key])), 0)
        for key in ordered
    )
    return polygons, [ids[root(i)] for i in range(len(polygons))], bodies


def source_water_connectivity(
    world: WorldMap,
    grid: SphericalContextGrid,
    *,
    checkpoint: Callable[[], None],
) -> WaterConnectivity:
    """Rebuild source incidence when accepting stored graph data."""
    checkpoint()
    land = unary_union(
        [Polygon(c.exterior, c.holes) for feature in world.land for c in feature.components]
    )
    polygons, ids, _bodies = water_topology(land, grid.frame, None, checkpoint=checkpoint)
    checkpoint()
    return build_water_connectivity(land, polygons, ids, grid, checkpoint=checkpoint)


def validate_water_partition(
    graph: WaterConnectivity,
    grid: SphericalContextGrid,
    fraction: NDArray[np.float64],
    bodies: tuple[ConnectedWater, ...],
) -> None:
    """Reject lost area or crossed barriers; retain unresolved finite-face support."""
    node_cells = np.repeat(np.arange(fraction.size), np.diff(graph.cell_offsets))
    wet_area = np.bincount(node_cells, weights=graph.area_km2, minlength=fraction.size)
    row_area = np.array([grid.cell_area_km2(r) for r in range(grid.shape[0])])[:, None]
    expected = (1 - fraction) * row_area
    if np.any(np.abs(wet_area.reshape(grid.shape) - expected) > np.maximum(row_area * 1e-9, 1e-8)):
        raise ValueError("Water pieces do not conserve geographic cell areas.")
    body_area = np.bincount(graph.water_body, weights=graph.area_km2, minlength=len(bodies) + 1)
    if not np.allclose(body_area[1:], [b.area_km2 for b in bodies], rtol=1e-9, atol=1e-8):
        raise ValueError("Water pieces do not conserve source water-body areas.")
    identities = np.unique(np.column_stack((graph.component, graph.water_body)), axis=0)
    if len(identities) != graph.component_count or not np.array_equal(
        np.unique(graph.water_body), [b.id for b in bodies]
    ):
        raise ValueError("Water-piece components cross or omit source water regions.")
    # Floating-point clipping can close an unrepresentably thin source sliver.
    # Retain its area and isolated pieces, expose fragmented_bodies, and require
    # future transport consumers to reject them. Never invent an epsilon bridge.


def generate_world_context(
    world: WorldMap,
    settings: WorldContextSettings | None = None,
    progress: ProgressCallback | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> WorldContext:
    """Partition the prepared source into cells without changing its coastline.

    Water IDs come from continuous prepared vectors, not thresholded pixels.
    A cell may contain disconnected water pieces: its largest aggregated body supplies the
    display ID, while support flags prevent treating that ID as a solver gateway.
    """

    def report(fraction: float, message: str) -> None:
        check_cancelled(cancellation)
        if progress:
            progress(fraction, message)
        check_cancelled(cancellation)

    report(0, "Preparing spherical geography and connected water")
    grid = SphericalContextGrid(world.project.frame, settings or WorldContextSettings())
    frame = grid.frame
    land = unary_union(
        [Polygon(c.exterior, c.holes) for feature in world.land for c in feature.components]
    )
    polygons, body_ids, bodies = water_topology(land, frame, cancellation)
    tree = STRtree(polygons)
    shapely.prepare(polygons)
    rows, columns = grid.shape
    fraction = np.zeros(grid.shape, dtype=np.float64)
    water_id = np.zeros(grid.shape, dtype=np.int32)
    flags = np.zeros(grid.shape, dtype=np.uint8)
    row_area = np.array([grid.cell_area_km2(r) for r in range(rows)], dtype=np.float64)
    xs = np.linspace(frame.bounds[0], frame.bounds[2], columns + 1)
    ys = np.linspace(frame.bounds[1], frame.bounds[3], rows + 1)
    centres = (xs[:-1] + xs[1:]) / 2
    # Work one row at a time; coastline intersection scratch does not scale with
    # all cells times all vector vertices. Grid admission is bounded in settings.
    for row in range(rows):
        report(0.05 + 0.4 * row / rows, f"Measuring geographic cells: row {row + 1}/{rows}")
        strip = box(xs[0], ys[row], xs[-1], ys[row + 1])
        row_land = land.intersection(strip)
        shapely.prepare(row_land)
        cells = shapely.box(xs[:-1], ys[row], xs[1:], ys[row + 1])
        full = np.asarray(shapely.covers(row_land, cells), dtype=np.bool_)
        touched = np.asarray(shapely.intersects(row_land, cells), dtype=np.bool_)
        centres_land = np.asarray(
            shapely.intersects_xy(row_land, centres, (ys[row] + ys[row + 1]) / 2), dtype=np.bool_
        )
        fraction[row, full] = 1
        for index in sorted(int(i) for i in tree.query(strip)):
            wet_centres = np.asarray(
                shapely.intersects_xy(polygons[index], centres, (ys[row] + ys[row + 1]) / 2),
                dtype=np.bool_,
            )
            water_id[row, wet_centres & ~full] = body_ids[index]
        for column in np.flatnonzero(touched & ~full):
            col = int(column)
            cell = cells[col]
            wet = cell
            if touched[col]:
                dry = row_land.intersection(cell)
                value = _area(dry, frame) / row_area[row]
                if not -1e-9 <= value <= 1 + 1e-9:
                    raise ValueError("Spherical cell coverage escaped its area bounds.")
                fraction[row, col] = float(np.clip(value, 0, 1))
                wet = cell.difference(dry)
                if 0 < fraction[row, col] < 1:
                    flags[row, col] |= MIXED_COAST
                    flags[row, col] |= SUBCELL_WATER if centres_land[col] else SUBCELL_LAND
            if wet.area <= 0:
                # A boundary-only GEOS remainder has no water area. Spherical
                # integration can round a full dry cell just below one; use
                # empty wet geometry, never an epsilon that could erase islands.
                fraction[row, col] = 1
                water_id[row, col] = 0
                flags[row, col] = 0
                continue
            pieces = components_from_geometry(wet)
            if len(pieces) > 1:
                flags[row, col] |= SPLIT_WATER
            candidates: dict[int, float] = {}
            for index in tree.query(wet):
                piece = wet.intersection(polygons[int(index)])
                area = _area(piece, frame)
                if area > 0:
                    key = body_ids[int(index)]
                    candidates[key] = candidates.get(key, 0) + area
            if candidates:
                water_id[row, col] = min(candidates, key=lambda key: (-candidates[key], key))
                if len(candidates) > 1:
                    flags[row, col] |= SPLIT_WATER
    measured = float(np.sum(fraction * row_area[:, None]))
    error = measured - world.land_area_km2
    tolerance = max(frame.surface_area_km2 * 1e-9, 1e-8)
    if abs(error) > tolerance:
        raise ValueError(f"Context coverage failed spherical area conservation ({error:g} km²).")
    if abs(sum(b.area_km2 for b in bodies) + measured - frame.surface_area_km2) > tolerance:
        raise ValueError("Connected water and land do not conserve the sphere area.")
    bodies = tuple(
        ConnectedWater(b.id, b.area_km2, b.crosses_seam, int(np.count_nonzero(water_id == b.id)))
        for b in bodies
    )
    east, south = measure_water_openings(
        land,
        grid,
        lambda f, message: report(0.45 + 0.15 * f, message),
        cancellation=cancellation,
    )
    connectivity = build_water_connectivity(
        land,
        polygons,
        body_ids,
        grid,
        checkpoint=lambda: check_cancelled(cancellation),
        progress=lambda f, message: report(0.60 + 0.15 * f, message),
    )
    validate_water_partition(connectivity, grid, fraction, bodies)
    report(0.75, "Measuring geodesic shoreline distance")
    shore, sampling = measure_shore_distance(land, grid, cancellation=cancellation)
    exposure, mixed_support = measure_water_exposure(
        grid,
        fraction,
        flags,
        lambda f, message: report(0.80 + 0.19 * f, message),
        cancellation=cancellation,
    )
    for array in (fraction, water_id, flags, row_area, east, south):
        array.flags.writeable = False
    report(1, "Geographic context ready; mixed cells retain unresolved local detail")
    return WorldContext(
        world,
        grid,
        fraction,
        water_id,
        flags,
        row_area,
        east,
        south,
        shore,
        exposure,
        mixed_support,
        sampling,
        bodies,
        measured,
        error,
        connectivity,
    )
