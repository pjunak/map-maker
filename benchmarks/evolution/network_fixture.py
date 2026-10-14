"""Public range-to-lowland fixture with physical paths and native regional limits."""

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon, box

from benchmarks.evolution.constrained import FittedSurface, HardHeights
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.paths import FloatArray
from map_maker.terrain.domain import LandformSettings
from map_maker.terrain.domain.evolution import EvolutionGrid
from map_maker.terrain.domain.models import LandformKind
from map_maker.terrain.pipeline.hydrology import automatic_incision_budget
from map_maker.terrain.pipeline.landforms import MetricRegion, regional_incision_limit

FIXTURE_ID = "two-catchment-range-lowland@2"


@dataclass(frozen=True, slots=True)
class NetworkFixture:
    source: FittedSurface
    network: RiverNetwork
    regions: tuple[MetricRegion, ...]
    protected_divide_km: Polygon
    limits_m: FloatArray
    target_m: FloatArray
    hard: HardHeights
    global_limit_m: float


def conservative_limits(
    grid: EvolutionGrid, background: float, regions: tuple[MetricRegion, ...], protected_km: Polygon
) -> FloatArray:
    """Cell-wide lower envelope of native blended caps, including transitions.

    The smallest full-influence limit among all potentially intersecting regions
    is no greater than their native convex blend at any point in the cell. Give
    each node the minimum of its incident cells. Bounding boxes may overprotect;
    they never authorize a larger cut. Protect the whole divide footprint likewise.
    """
    cell_y, cell_x = np.indices((grid.shape[0] - 1, grid.shape[1] - 1), dtype=np.float64)
    step = grid.spacing_m / 1000.0
    cell_x, cell_y = cell_x * step, cell_y * step
    cells = np.full(cell_x.shape, background)
    for geometry, limit in (
        *((r.sampling_support(), regional_incision_limit(background, r.settings)) for r in regions),
        (protected_km, 0.0),
    ):
        x0, y0, x1, y1 = geometry.bounds
        selected = (cell_x <= x1) & (cell_x + step >= x0) & (cell_y <= y1) & (cell_y + step >= y0)
        cells[selected] = np.minimum(cells[selected], limit)
    result = np.full(grid.shape, background)
    for rows, cols in (
        (slice(None, -1), slice(None, -1)),
        (slice(1, None), slice(None, -1)),
        (slice(None, -1), slice(1, None)),
        (slice(1, None), slice(1, None)),
    ):
        result[rows, cols] = np.minimum(result[rows, cols], cells)
    return result


def valley_target(
    source: FittedSurface, network: RiverNetwork, limits: FloatArray, width_m: float = 2400.0
) -> FloatArray:
    grid = source.grid
    y, x = np.indices(grid.shape, dtype=np.float64) * grid.spacing_m
    xy = np.stack((x.ravel(), y.ravel()), axis=-1)
    target = source.ground_m.astype(np.float64).ravel().copy()
    limit_field = FittedSurface(grid, limits.astype(np.float32), {})
    bed = source.sample(network.coordinates_m[:, 0], network.coordinates_m[:, 1]).astype(np.float64)
    depth = 0.65 * limit_field.sample(network.coordinates_m[:, 0], network.coordinates_m[:, 1])
    bed -= depth
    for a in np.flatnonzero(network.required):
        b = int(network.receivers[a])
        origin = network.coordinates_m[a]
        direction = network.coordinates_m[b] - origin
        t = np.clip(((xy - origin) @ direction) / np.dot(direction, direction), 0, 1)
        offset: FloatArray = xy - origin - t[:, None] * direction
        distance = np.sqrt(np.sum(offset**2, axis=-1))
        local_depth = (1 - t) * depth[a] + t * depth[b]
        cross_section = (1 - t) * bed[a] + t * bed[b] + local_depth * (distance / width_m) ** 1.5
        # The endpoint of a coastal reach has zero bed/depth; it must not
        # flatten an entire downstream half-plane. Compact C1 support also
        # avoids a step where the valley meets its surrounding hillslope.
        q = np.minimum(distance / width_m, 1.0)
        influence = (1.0 - q * q) ** 2
        cut = np.maximum(source.ground_m.ravel() - cross_section, 0.0) * influence
        target = np.minimum(target, source.ground_m.ravel() - cut)
    return np.clip(target.reshape(grid.shape), source.ground_m - limits, source.ground_m)


def fixture(spacing_m: float = 500.0, *, rotate: bool = False) -> NetworkFixture:
    # A fixed broad parent at 2 km. Quantized dyadic interpolation makes all
    # three nested process grids sample exactly the same physical source field.
    parent_grid = EvolutionGrid(32000.0, 24000.0, 2000.0)
    y, x = np.indices(parent_grid.shape, dtype=np.float64) * 2.0
    shape = 140 + 760 * np.exp(-(((x - 16) / 8) ** 2))
    shape += 180 * np.exp(-(((x - 11) / 3) ** 2) - ((y - 5) / 3) ** 2)
    shape += 150 * np.exp(-(((x - 22) / 3) ** 2) - ((y - 7) / 3) ** 2)
    parent = np.rint((1 - y / 24) ** 1.3 * shape * 16) / 16
    coarse = FittedSurface(parent_grid, parent.astype(np.float32), {})
    grid = EvolutionGrid(32000.0, 24000.0, spacing_m)
    qy, qx = np.indices(grid.shape, dtype=np.float64) * spacing_m
    ground = coarse.sample(qx, qy)
    xy = (
        np.array(
            [
                (13, 2),
                (11.5, 5.5),
                (10, 8),
                (9, 11.5),
                (7.5, 15),
                (8, 19),
                (6.5, 24),
                (9, 2),
                (8, 5),
                (19, 3),
                (21, 7),
                (23, 11.5),
                (24.5, 16),
                (25, 20),
                (26, 24),
                (25, 4),
                (24.5, 8),
            ],
            dtype=np.float64,
        )
        * 1000
    )
    receivers = np.array(
        [1, 2, 3, 4, 5, 6, -1, 8, 2, 10, 11, 12, 13, 14, -1, 16, 11], dtype=np.int64
    )
    regions: list[MetricRegion] = []
    recipes: tuple[tuple[float, float, LandformKind, float], ...] = (
        (0, 9, "mountains", 600.0),
        (9, 17, "hills", 300.0),
        (17, 24, "plain", 100.0),
    )
    for y0, y1, kind, relief in recipes:
        controls = LandformSettings(character=kind, relief_m=relief, transition_km=1.0)
        regions.append(MetricRegion(box(0, y0, 32, y1), controls, box(0, 0, 32, 24)))
    divide = box(15, 0, 17, 24)
    anchors = np.array([[12375.0, 4625.0], [16000.0, 8375.0]])
    heights = coarse.sample(anchors[:, 0], anchors[:, 1]).astype(np.float64)
    heights[0] -= 10.0
    if rotate:
        grid = EvolutionGrid(24000.0, 32000.0, spacing_m)
        ground = np.rot90(ground, -1).copy()
        xy = np.stack((24000 - xy[:, 1], xy[:, 0]), axis=-1)
        anchors = np.stack((24000 - anchors[:, 1], anchors[:, 0]), axis=-1)
        rotated: list[MetricRegion] = []
        for r in regions:
            x0, y0, x1, y1 = r.geometry.bounds
            rotated.append(MetricRegion(box(24 - y1, x0, 24 - y0, x1), r.settings,
                                        box(0, 0, 24, 32)))
        regions = rotated
        divide = box(0, 15, 24, 17)
    source = FittedSurface(grid, ground, {"role": "fixed physical broad source"})
    network = RiverNetwork(xy, receivers)
    global_limit = automatic_incision_budget(1600.0, 0.5)
    limits = conservative_limits(grid, global_limit, tuple(regions), divide)
    limits[ground == 0] = 0.0
    target = valley_target(source, network, limits)
    return NetworkFixture(
        source,
        network,
        tuple(regions),
        divide,
        limits,
        target,
        HardHeights(anchors, heights),
        global_limit,
    )
