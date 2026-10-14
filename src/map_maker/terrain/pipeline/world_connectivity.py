# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Separate water pieces per cell and finite shared-face incidence on a sphere."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy.sparse import csr_array
from scipy.sparse.csgraph import connected_components
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from map_maker.terrain.domain.world_context import SphericalContextGrid
from map_maker.terrain.pipeline.control import ProgressCallback
from map_maker.terrain.pipeline.world import component_area_km2, components_from_geometry

CONNECTIVITY_ALGORITHM = "cell-water-pieces-v1"
MAX_WATER_PIECES = 500_000
MAX_WATER_LINKS = 1_000_000
MAX_CELL_PIECES = 4096
MAX_CLIPPED_VERTICES = 2_000_000
MAX_FACE_INTERVALS = 8192

type Trace = list[tuple[float, float, int]]


@dataclass(frozen=True, slots=True)
class WaterConnectivity:
    cell_offsets: NDArray[np.int32]
    water_body: NDArray[np.int32]
    area_km2: NDArray[np.float64]
    sample_uv: NDArray[np.float64]
    link_nodes: NDArray[np.int32]
    link_axis: NDArray[np.uint8]
    link_interval: NDArray[np.float64]
    link_width_km: NDArray[np.float64]
    component: NDArray[np.int32]
    incident_links: NDArray[np.int32]
    fragmented_bodies: tuple[int, ...]

    @property
    def component_count(self) -> int:
        return int(self.component.max(initial=0))

    @property
    def split_cells(self) -> int:
        return int(np.count_nonzero(np.diff(self.cell_offsets) > 1))

    def arrays(self) -> dict[str, NDArray[np.int32] | NDArray[np.uint8] | NDArray[np.float64]]:
        return {
            name: getattr(self, name)
            for name in (
                "cell_offsets",
                "water_body",
                "area_km2",
                "sample_uv",
                "link_nodes",
                "link_axis",
                "link_interval",
                "link_width_km",
            )
        }


def connectivity_from_arrays(
    cell_offsets: NDArray[np.int32],
    water_body: NDArray[np.int32],
    area_km2: NDArray[np.float64],
    sample_uv: NDArray[np.float64],
    link_nodes: NDArray[np.int32],
    link_axis: NDArray[np.uint8],
    link_interval: NDArray[np.float64],
    link_width_km: NDArray[np.float64],
) -> WaterConnectivity:
    """Derive graph labels after source verification or trusted geometric generation."""
    count = len(water_body)
    matrix = csr_array(
        (np.ones(len(link_nodes), dtype=np.bool_), (link_nodes[:, 0], link_nodes[:, 1])),
        shape=(count, count),
    )
    _, labels = connected_components(matrix, directed=False)
    component = np.asarray(labels + 1, dtype=np.int32)
    degree = np.bincount(link_nodes.ravel(), minlength=count).astype(np.int32)
    memberships = np.unique(np.column_stack((water_body, component)), axis=0)
    ids, counts = np.unique(memberships[:, 0], return_counts=True)
    fragmented = tuple(int(body) for body in ids[counts > 1])
    result = WaterConnectivity(
        cell_offsets,
        water_body,
        area_km2,
        sample_uv,
        link_nodes,
        link_axis,
        link_interval,
        link_width_km,
        component,
        degree,
        fragmented,
    )
    for array in (*result.arrays().values(), component, degree):
        array.flags.writeable = False
    return result


def _intervals(geometry: BaseGeometry, axis: int, origin: float, length: float, node: int) -> Trace:
    result: Trace = []
    pending = [geometry]
    while pending:
        item = pending.pop()
        if item.is_empty:
            continue
        if item.geom_type in ("GeometryCollection", "MultiLineString"):
            pending.extend(shapely.get_parts(item))
        elif item.geom_type in ("LineString", "LinearRing"):
            coordinates = np.asarray(item.coords)[:, axis]
            lo, hi = (
                (float(coordinates.min()) - origin) / length,
                (float(coordinates.max()) - origin) / length,
            )
            if not -1e-10 <= lo <= hi <= 1 + 1e-10:
                raise ValueError("Water face interval escaped its cell.")
            lo, hi = max(0.0, lo), min(1.0, hi)
            if hi > lo:
                result.append((lo, hi, node))
    # GEOS can split a continuous collinear boundary at source vertices.
    merged: Trace = []
    for lo, hi, _ in sorted(result):
        if merged and lo <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(hi, merged[-1][1]), node
        else:
            merged.append((lo, hi, node))
    if len(merged) > MAX_FACE_INTERVALS:
        raise ValueError("Too many intervals on one water-piece face; simplify source geometry.")
    return merged


def build_water_connectivity(
    land: BaseGeometry,
    polygons: list[Polygon],
    body_ids: list[int],
    grid: SphericalContextGrid,
    *,
    checkpoint: Callable[[], None],
    progress: ProgressCallback | None = None,
) -> WaterConnectivity:
    """Keep only two rows of boundary traces; never join by dominant cell IDs.

    Full water cells take an analytic fast path. Clipped pieces retain their
    physical areas and interior inspection sites, with exact source-derived face
    intervals. Sites/edge lengths are not travel paths or transport coefficients.
    """
    checkpoint()
    rows, columns = grid.shape
    frame = grid.frame
    x0, y0, x1, y1 = frame.bounds
    xs, ys = np.linspace(x0, x1, columns + 1), np.linspace(y0, y1, rows + 1)
    tree = STRtree(polygons)
    offsets = [0]
    bodies: list[int] = []
    areas: list[float] = []
    sites: list[tuple[float, float]] = []
    pairs: list[tuple[int, int]] = []
    axes: list[int] = []
    intervals: list[tuple[float, float]] = []
    widths: list[float] = []
    vertices = 0
    previous_south: list[Trace] = [[] for _ in range(columns)]

    def add(body: int, area: float, point: tuple[float, float]) -> int:
        if len(bodies) >= MAX_WATER_PIECES:
            raise ValueError(
                "Water connectivity exceeds the piece budget; reduce resolution or complexity."
            )
        if not isfinite(area) or area <= 0:
            raise ValueError("A clipped water piece is below supported spherical-area precision.")
        node = len(bodies)
        bodies.append(body)
        areas.append(area)
        sites.append(point)
        return node

    def connect(first: Trace, second: Trace, axis: int, scale: float) -> None:
        a, b = sorted(first), sorted(second)
        i = j = 0
        while i < len(a) and j < len(b):
            lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
            if hi > lo and scale > 0:
                left, right = a[i][2], b[j][2]
                if bodies[left] != bodies[right]:
                    raise ValueError("Shared water face disagrees with vector body identity.")
                if len(pairs) >= MAX_WATER_LINKS:
                    raise ValueError(
                        "Water connectivity exceeds the link budget; "
                        "reduce resolution or complexity."
                    )
                pairs.append((left, right))
                axes.append(axis)
                intervals.append((lo, hi))
                widths.append((hi - lo) * scale)
            if a[i][1] <= b[j][1]:
                i += 1
            else:
                j += 1

    for row in range(rows):
        checkpoint()
        if progress:
            progress(row / rows, f"Connecting water passages: row {row + 1}/{rows}")
        bottom, top = float(ys[row + 1]), float(ys[row])
        strip = box(x0, top, x1, bottom)
        row_land = land.intersection(strip)
        shapely.prepare(row_land)
        cells = shapely.box(xs[:-1], ys[row], xs[1:], ys[row + 1])
        full_land = np.asarray(shapely.covers(row_land, cells), dtype=np.bool_)
        full_water = ~np.asarray(shapely.intersects(row_land, cells), dtype=np.bool_)
        centres = shapely.points((xs[:-1] + xs[1:]) / 2, np.full(columns, (top + bottom) / 2))
        memberships = tree.query(centres, predicate="within")
        centre_bodies = np.zeros(columns, dtype=np.int32)
        if memberships.size:
            centre_bodies[memberships[0]] = np.asarray(body_ids, dtype=np.int32)[memberships[1]]
        row_polygons = [
            (int(i), polygons[int(i)].intersection(strip)) for i in sorted(tree.query(strip))
        ]
        current_south: list[Trace] = []
        east: Trace = []
        first_west: Trace = []
        for col in range(columns):
            if col % 32 == 0:
                checkpoint()
            left, right = float(xs[col]), float(xs[col + 1])
            west, next_east, north, south = [], [], [], []
            if full_water[col]:
                body = int(centre_bodies[col])
                if body <= 0:
                    raise ValueError("Full water cell has no source water identity.")
                node = add(
                    body, grid.cell_area_km2(row), ((col + 0.5) / columns, (row + 0.5) / rows)
                )
                west = next_east = north = south = [(0.0, 1.0, node)]
            elif not full_land[col]:
                pieces: list[tuple[Polygon, int]] = []
                for index, polygon in row_polygons:
                    for component in components_from_geometry(polygon.intersection(cells[col])):
                        pieces.append(
                            (Polygon(component.exterior, component.holes), body_ids[index])
                        )
                if len(pieces) > MAX_CELL_PIECES:
                    raise ValueError(
                        "Too many disconnected water pieces in one cell; simplify source geometry."
                    )
                pieces.sort(
                    key=lambda item: (item[0].bounds, item[1], shapely.normalize(item[0]).wkb)
                )
                faces = [
                    LineString(((left, top), (left, bottom))),
                    LineString(((right, top), (right, bottom))),
                    LineString(((left, top), (right, top))),
                    LineString(((left, bottom), (right, bottom))),
                ]
                wet_faces = [face.difference(row_land) for face in faces]
                for polygon, body in pieces:
                    component = components_from_geometry(polygon)[0]
                    vertices += len(component.exterior) + sum(map(len, component.holes))
                    if vertices > MAX_CLIPPED_VERTICES:
                        raise ValueError(
                            "Water connectivity exceeds the clipped-vertex budget; "
                            "simplify source geometry."
                        )
                    point = polygon.representative_point()
                    node = add(
                        body,
                        component_area_km2(component, frame),
                        ((point.x - x0) / frame.width, (point.y - y0) / frame.height),
                    )
                    for target, face, coordinate, origin, length in (
                        (west, wet_faces[0], 1, top, bottom - top),
                        (next_east, wet_faces[1], 1, top, bottom - top),
                        (north, wet_faces[2], 0, left, right - left),
                        (south, wet_faces[3], 0, left, right - left),
                    ):
                        target.extend(
                            _intervals(polygon.intersection(face), coordinate, origin, length, node)
                        )
            if col:
                connect(east, west, 0, grid.north_south_spacing_km)
            else:
                first_west = west
            if row:
                connect(previous_south[col], north, 1, grid.south_edge_length_km(row - 1))
            east = next_east
            current_south.append(south)
            offsets.append(len(bodies))
        connect(east, first_west, 0, grid.north_south_spacing_km)
        previous_south = current_south
    checkpoint()
    result = connectivity_from_arrays(
        np.asarray(offsets, dtype=np.int32),
        np.asarray(bodies, dtype=np.int32),
        np.asarray(areas, dtype=np.float64),
        np.asarray(sites, dtype=np.float64).reshape(-1, 2),
        np.asarray(pairs, dtype=np.int32).reshape(-1, 2),
        np.asarray(axes, dtype=np.uint8),
        np.asarray(intervals, dtype=np.float64).reshape(-1, 2),
        np.asarray(widths, dtype=np.float64),
    )
    checkpoint()
    return result
