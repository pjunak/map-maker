# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Bounded spherical shore queries and directional geographic water exposure."""

from collections.abc import Iterator
from math import pi

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy.spatial import KDTree
from shapely.affinity import affine_transform
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry, BaseMultipartGeometry
from shapely.ops import unary_union

from map_maker.terrain.domain.world_context import (
    EXPOSURE_BEARINGS,
    MAX_SHORE_SAMPLES,
    MIXED_COAST,
    ShoreSampling,
    SphericalContextGrid,
    exposure_range_km,
    exposure_steps,
    shore_spacing_km,
)
from map_maker.terrain.pipeline.control import CancellationToken, ProgressCallback, check_cancelled


def _lines(geometry: BaseGeometry) -> Iterator[NDArray[np.float64]]:
    if geometry.is_empty:
        return
    if geometry.geom_type in ("LineString", "LinearRing"):
        yield np.asarray(geometry.coords, dtype=np.float64)
    elif isinstance(geometry, BaseMultipartGeometry):
        for part in geometry.geoms:
            yield from _lines(part)


def _vectors(longitude: NDArray[np.float64], latitude: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.stack(
        (
            np.cos(latitude) * np.cos(longitude),
            np.cos(latitude) * np.sin(longitude),
            np.sin(latitude),
        ),
        axis=-1,
    )


def _shore_samples(
    land: BaseGeometry,
    grid: SphericalContextGrid,
    cancellation: CancellationToken | None,
) -> tuple[NDArray[np.float64], ShoreSampling]:
    if land.is_empty:
        return np.empty((0, 3), dtype=np.float64), ShoreSampling(0, 0.0)
    # Ownership splits can add collinear vertices without changing physical land.
    # Canonicalize those zero-area edits before placing distance samples.
    land = shapely.normalize(land.simplify(0, preserve_topology=True))
    frame = grid.frame
    x0, y0, x1, y1 = frame.bounds
    # Artificial map cuts and collapsed polar edges are not shores. A mismatch
    # between the two seam sides IS a shore, represented once at the left edge.
    left = land.intersection(LineString(((x0, y0), (x0, y1))))
    right = affine_transform(
        land.intersection(LineString(((x1, y0), (x1, y1)))), (0, 0, 0, 1, x0, 0)
    )
    shore = unary_union(
        (land.boundary.difference(box(*frame.bounds).boundary), left.symmetric_difference(right))
    )
    chunks: list[NDArray[np.float64]] = []
    count, max_gap = 0, 0.0
    for coords in _lines(shore):
        check_cancelled(cancellation)
        angles = (coords - (x0, y0)) * (2 * pi / frame.width, -pi / frame.height)
        angles += (np.deg2rad(frame.central_meridian_deg) - pi, pi / 2)
        differences = np.diff(angles, axis=0)
        # Along a source-linear lon/lat segment ds <= R*hypot(dlat, dlon).
        # Every curve point is within half this sample gap of an endpoint.
        lengths = np.linalg.norm(differences, axis=1) * frame.radius_km
        requested = np.maximum(1, np.ceil(lengths / shore_spacing_km(grid)))
        # Admit while counts are floating point: valid large-radius worlds can
        # exceed Int64 before conversion or overflow an integer sum.
        required = float(np.sum(requested)) + count + 1
        if not np.isfinite(required) or required > MAX_SHORE_SAMPLES:
            raise ValueError(
                f"Shoreline needs over {MAX_SHORE_SAMPLES:,} samples; simplify source detail "
                "or use a coarser context grid. No approximate result was accepted."
            )
        subdivisions = requested.astype(np.int64)
        added = int(np.sum(subdivisions)) + 1
        count += added
        if len(lengths):
            max_gap = max(max_gap, float(np.max(lengths / subdivisions)))
        segment = np.repeat(np.arange(len(differences)), subdivisions)
        starts = np.repeat(np.cumsum(subdivisions) - subdivisions, subdivisions)
        t = (np.arange(added - 1) - starts) / subdivisions[segment]
        samples = angles[segment] + differences[segment] * t[:, None]
        samples = np.concatenate((samples, angles[-1:]), axis=0)
        chunks.append(_vectors(samples[:, 0], samples[:, 1]))
    points = np.concatenate(chunks) if chunks else np.empty((0, 3), dtype=np.float64)
    return points, ShoreSampling(count, max_gap / 2)


def _centres(grid: SphericalContextGrid) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    rows, columns = grid.shape
    longitude, latitude = np.meshgrid(
        np.deg2rad([grid.longitude_deg(c) for c in range(columns)]),
        np.deg2rad([grid.latitude_deg(r) for r in range(rows)]),
    )
    return longitude.ravel(), latitude.ravel()


def measure_shore_distance(
    land: BaseGeometry,
    grid: SphericalContextGrid,
    *,
    cancellation: CancellationToken | None = None,
) -> tuple[NDArray[np.float64], ShoreSampling]:
    """Nearest sampled shoreline: true distance <= result <= true + max_error_km.

    Includes inland water shores. NaN means no shoreline exists, not zero distance.
    Bounds refer to retained prepared source curves, not the original Bezier curves.
    """
    check_cancelled(cancellation)
    samples, support = _shore_samples(land, grid, cancellation)
    distances = np.full(grid.shape, np.nan, dtype=np.float64)
    if len(samples):
        tree = KDTree(samples)
        longitude, latitude = _centres(grid)
        positions = _vectors(longitude, latitude)
        flat = distances.ravel()
        for start in range(0, len(positions), 4096):
            check_cancelled(cancellation)
            points = positions[start : start + 4096]
            _, nearest = tree.query(points, eps=0, p=2, workers=1)
            target = samples[nearest]
            # atan2 remains stable near zero and antipodal distances.
            flat[start : start + len(points)] = grid.frame.radius_km * np.arctan2(
                np.linalg.norm(np.cross(points, target), axis=1),
                np.sum(points * target, axis=1),
            )
    distances.flags.writeable = False
    check_cancelled(cancellation)
    return distances, support


def measure_water_exposure(
    grid: SphericalContextGrid,
    land_fraction: NDArray[np.float64],
    support_flags: NDArray[np.uint8],
    progress: ProgressCallback | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Weighted water fraction along eight great-circle rays from each cell centre.

    Bearings are initial look directions, clockwise from true north. Land does
    not stop rays; this is geographic exposure, not moisture or water transport.
    Mixed support measures quadrature weight on mixed cells, not an error bound.
    """
    check_cancelled(cancellation)
    steps = exposure_steps(grid)
    horizon = exposure_range_km(grid)
    distance = (np.arange(steps, dtype=np.float64) + 0.5) * horizon / steps
    weights = np.exp(-3 * distance / horizon)
    weights /= weights.sum()
    cosine = np.cos(distance / grid.frame.radius_km)[None, :]
    sine = np.sin(distance / grid.frame.radius_km)[None, :]
    lon, lat = _centres(grid)
    positions = _vectors(lon, lat)
    north = np.stack((-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)), axis=-1)
    east = np.stack((-np.sin(lon), np.cos(lon), np.zeros_like(lon)), axis=-1)
    result = np.empty((8, *grid.shape), dtype=np.float32)
    support = np.empty_like(result)
    wet = 1 - land_fraction
    mixed = (support_flags & MIXED_COAST) != 0
    rows, columns = grid.shape
    offset = np.deg2rad(grid.frame.central_meridian_deg) - pi
    for direction, name in enumerate(EXPOSURE_BEARINGS):
        bearing = direction * pi / 4
        tangent = north * np.cos(bearing) + east * np.sin(bearing)
        values = result[direction].ravel()
        uncertain = support[direction].ravel()
        for start in range(0, len(lon), 1024):
            check_cancelled(cancellation)
            end = min(start + 1024, len(lon))
            points = positions[start:end, None, :] * cosine[..., None]
            points += tangent[start:end, None, :] * sine[..., None]
            longitude = np.arctan2(points[..., 1], points[..., 0])
            latitude = np.arctan2(points[..., 2], np.hypot(points[..., 0], points[..., 1]))
            x = np.floor(((longitude - offset) % (2 * pi)) * columns / (2 * pi))
            y = np.floor((pi / 2 - latitude) * rows / pi)
            column = np.clip(x.astype(np.int64), 0, columns - 1)
            row = np.clip(y.astype(np.int64), 0, rows - 1)
            values[start:end] = np.clip(np.sum(wet[row, column] * weights, axis=1), 0, 1)
            uncertain[start:end] = np.clip(np.sum(mixed[row, column] * weights, axis=1), 0, 1)
            if progress:
                progress((direction + end / len(lon)) / 8, f"Measuring {name} water exposure")
            check_cancelled(cancellation)
    result.flags.writeable = support.flags.writeable = False
    return result, support
