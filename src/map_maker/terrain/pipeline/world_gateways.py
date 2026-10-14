# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Finite shared-face openings measured from vectors, never inferred from water IDs."""

from math import pi

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, LineString, MultiLineString, box
from shapely.geometry.base import BaseGeometry

from map_maker.terrain.domain.world_context import SphericalContextGrid
from map_maker.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled


def _longest_line(geometry: BaseGeometry) -> float:
    # Point contacts carry no width; separate openings must not be added together.
    if geometry.geom_type in ("LineString", "LinearRing"):
        return float(geometry.length)
    if isinstance(geometry, (MultiLineString, GeometryCollection)):
        return max((_longest_line(g) for g in geometry.geoms), default=0.0)
    return 0.0


def measure_water_openings(
    land: BaseGeometry,
    grid: SphericalContextGrid,
    progress: ProgressCallback | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Longest continuous wet interval on each east/south shared cell edge, km.

    The last east column joins the first across the seam, using water present on
    BOTH sides. The last south row is zero: there is no finite polar gateway.
    This is face support, not a strait's minimum width, depth or transport graph.
    In particular, split water inside a cell cannot be merged through these edges.
    """
    frame = grid.frame
    rows, columns = grid.shape
    xs = np.linspace(frame.bounds[0], frame.bounds[2], columns + 1)
    ys = np.linspace(frame.bounds[1], frame.bounds[3], rows + 1)
    east = np.full(grid.shape, grid.north_south_spacing_km, dtype=np.float64)
    south = np.zeros(grid.shape, dtype=np.float64)
    for row in range(rows):
        check_cancelled(cancellation)
        if progress:
            progress(row / rows, f"Measuring shared water openings: row {row + 1}/{rows}")
        row_land = land.intersection(box(xs[0], ys[row], xs[-1], ys[row + 1]))
        shapely.prepare(row_land)
        faces = [LineString(((x, ys[row]), (x, ys[row + 1]))) for x in xs[1:]]
        touched = np.asarray(shapely.intersects(row_land, faces), dtype=np.bool_)
        full = np.asarray(shapely.covers(row_land, faces), dtype=np.bool_)
        east[row, full] = 0
        for col in np.flatnonzero(touched & ~full):
            east[row, col] = (
                _longest_line(faces[col].difference(row_land)) * pi * frame.radius_km / frame.height
            )
        left = LineString(((xs[0], ys[row]), (xs[0], ys[row + 1]))).difference(row_land)
        # Pin the comparison edge exactly: x1 - (x1 - x0) can differ from x0.
        # This identifies longitude edges; it never moves source land geometry.
        right = affine_transform(faces[-1].difference(row_land), (0, 0, 0, 1, xs[0], 0))
        east[row, -1] = (
            _longest_line(left.intersection(right)) * pi * frame.radius_km / frame.height
        )
        if row == rows - 1:
            continue
        maximum = grid.south_edge_length_km(row)
        south[row] = maximum
        faces = [
            LineString(((xs[c], ys[row + 1]), (xs[c + 1], ys[row + 1]))) for c in range(columns)
        ]
        touched = np.asarray(shapely.intersects(row_land, faces), dtype=np.bool_)
        full = np.asarray(shapely.covers(row_land, faces), dtype=np.bool_)
        south[row, full] = 0
        for col in np.flatnonzero(touched & ~full):
            south[row, col] = (
                _longest_line(faces[col].difference(row_land)) * maximum / (xs[col + 1] - xs[col])
            )
    check_cancelled(cancellation)
    # Differences of source coordinates may overshoot the exact edge by roundoff.
    np.clip(east, 0, grid.north_south_spacing_km, out=east)
    for row in range(rows):
        np.clip(south[row], 0, grid.south_edge_length_km(row), out=south[row])
    return east, south
