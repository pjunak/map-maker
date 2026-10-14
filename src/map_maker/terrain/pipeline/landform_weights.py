# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
"""Compact regional weights with separate recipe and background transitions."""

from collections.abc import Iterator
from dataclasses import astuple, dataclass
from math import sqrt
from typing import Any, cast

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from map_maker.terrain.domain import LandformSettings, TerrainRegion

type FloatArray = NDArray[np.float64]
type Mask = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class MetricRegion:
    geometry: Polygon
    settings: LandformSettings
    coverage: Polygon

    def sampling_support(self) -> Polygon | MultiPolygon:
        """Conservative support for probes, never the authoritative weight."""
        # A diamond with circumradius sqrt(2)*r encloses the exact r-circle.
        # Avoid missing a thin arc because ordinary polygonal buffers are inscribed.
        support = self.geometry.buffer(
            sqrt(2.) * self.settings.transition_km, quad_segs=1,
        ).intersection(self.coverage)
        # Boundary-only intersections must not turn density geometry into a
        # GeometryCollection; they have no positive regional influence.
        return cast(Polygon | MultiPolygon, unary_union([
            part for part in shapely.get_parts(support) if isinstance(part, Polygon)
        ]))


def prepare_regions(
    regions: tuple[TerrainRegion, ...], width_km: float, height_km: float,
    land: Polygon | MultiPolygon, maximum_elevation_m: float,
) -> tuple[MetricRegion, ...]:
    groups: dict[LandformSettings, list[Polygon]] = {}
    for region in sorted(
        regions, key=lambda item: (astuple(item.settings), item.points, item.holes),
    ):
        geometry = Polygon(
            [(x * width_km, y * height_km) for x, y in region.points],
            [[(x * width_km, y * height_km) for x, y in ring] for ring in region.holes],
        )
        if not geometry.is_valid or geometry.area <= 0:
            raise ValueError("Terrain region must be a simple polygon with positive area.")
        if not geometry.intersects(land) or geometry.intersection(land).area <= 0:
            raise ValueError("Terrain region must cover some land.")
        if region.settings.elevation_m > maximum_elevation_m:
            raise ValueError("Regional elevation exceeds the elevation ceiling.")
        groups.setdefault(region.settings, []).append(geometry)
    if not groups:
        return ()
    merged: list[tuple[LandformSettings, Polygon]] = []
    for controls, polygons in sorted(groups.items(), key=lambda item: astuple(item[0])):
        geometry = shapely.normalize(unary_union(polygons).simplify(0., preserve_topology=True))
        for part in shapely.get_parts(geometry):
            merged.append((controls, cast(Polygon, part)))
    coverage = shapely.normalize(unary_union([geometry for _, geometry in merged]))
    prepared: list[MetricRegion] = []
    for part in shapely.get_parts(coverage):
        domain = cast(Polygon, part)
        for controls, geometry in merged:
            if domain.covers(geometry.representative_point()):
                prepared.append(MetricRegion(geometry, controls, domain))
    return tuple(prepared)


def _smoothstep(values: FloatArray) -> FloatArray:
    t = np.clip(values, 0., 1.)
    return t * t * (3. - 2. * t)


def _signed_distance(region: MetricRegion, points: Any, x: FloatArray, y: FloatArray) -> FloatArray:
    distance = np.asarray(shapely.distance(points, region.geometry.boundary), dtype=np.float64)
    inside = shapely.intersects_xy(region.geometry, x, y)
    return np.where(inside, distance, -distance)


def _domains(regions: tuple[MetricRegion, ...]) -> Iterator[tuple[Polygon, list[MetricRegion]]]:
    groups: dict[Polygon, list[MetricRegion]] = {}
    for region in regions:
        groups.setdefault(region.coverage, []).append(region)
    yield from groups.items()


def regional_weights(
    x: FloatArray, y: FloatArray, regions: tuple[MetricRegion, ...],
) -> Iterator[tuple[MetricRegion, Mask, FloatArray]]:
    """Convex, compact weights; the remainder belongs to background terrain.

    Core strength protects established interiors. Residual signed-distance
    support fills shared seams. Only the union's exposed boundary fades toward
    background, including unassigned holes. Separate components never interact.
    Two passes bound temporary storage by query size rather than region count.
    """
    for domain, members in _domains(regions):
        covered = np.asarray(shapely.intersects_xy(domain, x, y), dtype=np.bool_)
        if not covered.any():
            continue
        qx, qy = x[covered], y[covered]
        points: Any = shapely.points(qx, qy)
        edge_distance = np.asarray(shapely.distance(points, domain.boundary), dtype=np.float64)
        if len(members) == 1 and members[0].geometry.equals(domain):
            # The normalized recipe weight is exactly one for an isolated region.
            weight = _smoothstep(edge_distance / members[0].settings.transition_km)
            yield members[0], covered, weight
            continue
        core_sum, core_max, halo_sum = (np.zeros_like(qx) for _ in range(3))
        for region in members:
            signed = _signed_distance(region, points, qx, qy) / region.settings.transition_km
            core = _smoothstep(signed)
            core_sum += core
            core_max = np.maximum(core_max, core)
            halo_sum += _smoothstep(.5 + .5 * signed)
        residual = 1. - core_max
        denominator = core_sum + residual * halo_sum
        for region in members:
            signed = _signed_distance(region, points, qx, qy) / region.settings.transition_km
            raw = _smoothstep(signed) + residual * _smoothstep(.5 + .5 * signed)
            weight = raw / denominator * _smoothstep(edge_distance / region.settings.transition_km)
            active = weight > 0.
            if not active.any():
                continue
            selected = covered.copy()
            selected[covered] = active
            yield region, selected, weight[active]


def regional_transition_mask(
    x: FloatArray, y: FloatArray, regions: tuple[MetricRegion, ...],
) -> Mask:
    """Review both sides of recipe transitions, bounded by connected coverage."""
    transition = np.zeros(x.shape, dtype=np.bool_)
    for domain, members in _domains(regions):
        covered = np.asarray(shapely.intersects_xy(domain, x, y), dtype=np.bool_)
        if not covered.any():
            continue
        points: Any = shapely.points(x[covered], y[covered])
        local = np.zeros(np.count_nonzero(covered), dtype=np.bool_)
        for region in members:
            distance = np.asarray(
                shapely.distance(points, region.geometry.boundary), dtype=np.float64,
            )
            local |= distance < region.settings.transition_km
        transition[covered] |= local
    return transition
