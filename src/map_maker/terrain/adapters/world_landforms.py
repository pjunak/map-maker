# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
"""Compile resolved world guidance into ordinary editable terrain regions."""

from dataclasses import astuple

from shapely import normalize
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from map_maker.terrain.adapters.world_geometry_projection import project_components
from map_maker.terrain.domain.models import LandformSettings, TerrainRegion
from map_maker.terrain.domain.world_terrain import MAX_PROJECTED_POINTS, WorldTerrainSource
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.world import components_from_geometry
from map_maker.terrain.pipeline.world_geology import GeologyCoverage
from map_maker.terrain.pipeline.world_landmass import WorldLandmass


def compile_landforms(
    coverage: GeologyCoverage, land: WorldLandmass, source: WorldTerrainSource,
    *, maximum_elevation_m: float, cancellation: CancellationToken | None = None,
) -> tuple[TerrainRegion, ...]:
    """Preserve priority holes; dissolve identical guidance across ownership borders."""
    if coverage.recipe.world != source.world:
        raise ValueError("Geology must belong to the current world.")
    selected = unary_union([Polygon(p.exterior, p.holes) for p in land.components])
    groups: dict[LandformSettings, list[BaseGeometry]] = {}
    for region in coverage.regions:
        check_cancelled(cancellation)
        controls = region.profile.landform
        if controls is None:
            continue
        footprint = region.geometry.intersection(selected)
        if footprint.area <= 0:
            continue
        if controls.elevation_m > maximum_elevation_m:
            raise ValueError(f"{region.name}: regional elevation exceeds the terrain ceiling.")
        groups.setdefault(controls, []).append(footprint)

    coast = unary_union([Polygon(p.exterior, p.holes) for p in source.coastline.components])
    x0, y0, x1, y1 = source.coastline.bounds
    regions: list[TerrainRegion] = []
    count = 0

    def normalized(ring: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
        return tuple((min(1., max(0., (x-x0)/(x1-x0))),
                      min(1., max(0., (y-y0)/(y1-y0)))) for x, y in ring)

    for controls, shapes in sorted(groups.items(), key=lambda pair: astuple(pair[0])):
        check_cancelled(cancellation)
        # A semantic split or a distinct age with identical landform controls must
        # not introduce another inward transition or alter the noise carrier.
        parts = components_from_geometry(
            normalize(unary_union(shapes).simplify(0., preserve_topology=True))
        )
        projected, _ = project_components(
            parts, source.world.frame, source.projection, cancellation=cancellation,
        )
        geometry = normalize(unary_union(
            [Polygon(p.exterior, p.holes) for p in projected]
        ).intersection(coast))
        for part in components_from_geometry(geometry):
            count += len(part.exterior) + sum(len(ring) for ring in part.holes)
            if count > MAX_PROJECTED_POINTS:
                raise ValueError("Projected landforms exceed 500,000 points; use a smaller domain.")
            regions.append(TerrainRegion(
                normalized(part.exterior), controls, tuple(normalized(h) for h in part.holes),
            ))
    return tuple(sorted(regions, key=lambda r: (astuple(r.settings), r.points, r.holes)))
