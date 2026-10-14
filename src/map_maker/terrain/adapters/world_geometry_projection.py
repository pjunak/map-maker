# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""One bounded source-linear projection for coastlines and landform footprints."""

from dataclasses import replace
from math import degrees

import numpy as np
from numpy.typing import NDArray
from rasterio.warp import transform
from shapely import make_valid, normalize
from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.ops import unary_union

from map_maker.terrain.domain.models import LandComponent
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_terrain import (
    MAX_PROJECTED_POINTS,
    MAX_PROJECTION_ANGLE_DEG,
    WorldTerrainProjection,
)
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.world import components_from_geometry


def project_components(
    parts: tuple[LandComponent, ...], frame: WorldFrame, initial: WorldTerrainProjection,
    *, cancellation: CancellationToken | None = None,
) -> tuple[tuple[LandComponent, ...], WorldTerrainProjection]:
    """Rejoin periodic parts and bound every projected ring by the same tolerances."""
    lon, lat = initial.longitude_deg, initial.latitude_deg
    centre_x, _ = frame.lonlat_to_source((lon, lat))
    # Rejoin source pieces across the map seam before projecting them. Shared
    # continent borders disappear here, while real coastline holes remain.
    unwrapped = []
    for part in parts:
        polygon = Polygon(part.exterior, part.holes)
        shift = round((centre_x - polygon.centroid.x) / frame.width) * frame.width
        unwrapped.append(translate(polygon, xoff=shift))
    merged = components_from_geometry(
        normalize(unary_union(unwrapped).simplify(0.0, preserve_topology=True))
    )
    maximum_angle = 0.0
    point_count = 0

    def project(xy: NDArray[np.float64]) -> NDArray[np.float64]:
        nonlocal maximum_angle
        longitude = (
            frame.central_meridian_deg + (xy[:, 0] - frame.bounds[0]) / frame.width * 360 - 180
        )
        longitude = (longitude + 180) % 360 - 180
        latitude = 90 - (xy[:, 1] - frame.bounds[1]) / frame.height * 180
        longitude[np.abs(latitude) == 90] = 0.0
        a, b = np.radians(longitude - lon), np.radians(latitude)
        centre_lat = np.radians(lat)
        angle = np.arccos(
            np.clip(
                np.sin(b) * np.sin(centre_lat) + np.cos(b) * np.cos(centre_lat) * np.cos(a), -1, 1
            )
        )
        maximum_angle = max(maximum_angle, float(np.max(angle, initial=0)))
        if maximum_angle > np.radians(MAX_PROJECTION_ANGLE_DEG):
            raise ValueError(
                "This land selection extends beyond the supported 80-degree projection radius. "
                "It needs separate regional domains; changing the planet scale is not a fix."
            )
        transformed = transform(
            initial.geographic_crs, initial.projected_crs, longitude.tolist(), latitude.tolist()
        )
        east, north = transformed[0], transformed[1]
        result = np.column_stack((east, -np.asarray(north, dtype=np.float64)))
        if not np.all(np.isfinite(result)):
            raise ValueError("World projection produced nonfinite coordinates.")
        return result

    def ring(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
        nonlocal point_count
        check_cancelled(cancellation)
        source = np.asarray(points, dtype=np.float64)
        span = np.abs(np.diff(source, axis=0)) * (360 / frame.width, 180 / frame.height)
        counts = np.maximum(1, np.ceil(span.max(axis=1) / initial.source_step_deg)).astype(int)
        if point_count + int(counts.sum()) + 1 > MAX_PROJECTED_POINTS:
            raise ValueError("Projected coastline exceeds 500,000 points; select a smaller domain.")
        pieces = [
            a + np.arange(n)[:, None] / n * (b - a)
            for a, b, n in zip(source[:-1], source[1:], counts, strict=True)
        ]
        source = np.vstack((*pieces, source[-1:]))
        for _ in range(16):
            check_cancelled(cancellation)
            projected = project(source)
            fractions = np.array([0.25, 0.5, 0.75])
            probes = (
                source[:-1, None, :] + fractions[None, :, None] * np.diff(source, axis=0)[:, None]
            )
            actual = project(probes.reshape(-1, 2)).reshape(-1, 3, 2)
            chords = (
                projected[:-1, None, :]
                + fractions[None, :, None] * np.diff(projected, axis=0)[:, None]
            )
            refine = np.any(
                np.linalg.norm(actual - chords, axis=2) > initial.curve_tolerance_m, axis=1
            )
            if not np.any(refine):
                break
            if point_count + len(source) + int(refine.sum()) > MAX_PROJECTED_POINTS:
                raise ValueError("Projection curve refinement exceeds 500,000 points.")
            source = np.vstack(
                [
                    p
                    for i, p in enumerate(source)
                    for p in (
                        [p, (p + source[i + 1]) / 2] if i < len(refine) and refine[i] else [p]
                    )
                ]
            )
        else:
            raise ValueError("Projection curves need more than the bounded refinement depth.")
        point_count += len(projected)
        # Every longitude at a pole is the same point. Remove only exact duplicate
        # consecutive coordinates, including the duplicate closing-pole case.
        keep = np.concatenate(([True], np.any(np.diff(projected, axis=0) != 0, axis=1)))
        values = [(float(p[0]), float(p[1])) for p in projected[keep]]
        if values[-1] != values[0]:
            values.append(values[0])
        return tuple(values)

    polygons = []
    for part in merged:
        candidate = Polygon(ring(part.exterior), [ring(h) for h in part.holes])
        if not candidate.is_valid:
            # Pole/seam collapse can leave a zero-area spike. Refuse any repair
            # that changes area materially instead of inventing new coastline.
            repaired = make_valid(candidate)
            if abs(repaired.area - candidate.area) > max(1.0, abs(candidate.area) * 1e-9):
                raise ValueError("Projected coastline folds over itself; use a smaller domain.")
            candidate = repaired
        polygons.append(candidate)
    components = components_from_geometry(unary_union(polygons))
    if not components:
        raise ValueError("Selected land has no usable projected area.")
    components = tuple(sorted(components, key=lambda p: -Polygon(p.exterior, p.holes).area))
    projection = replace(
        initial,
        maximum_angle_deg=degrees(maximum_angle),
        maximum_transverse_scale=(
            float(maximum_angle / np.sin(maximum_angle)) if maximum_angle > 1e-12 else 1.0
        ),
    )
    return components, projection
