# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Resolve authored geology into disjoint, spherical-area land coverage."""

from dataclasses import dataclass
from math import fsum, isclose

from shapely.affinity import translate
from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import explain_validity

from map_maker.terrain.domain.models import LandComponent, Point2D
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.domain.world_geology import (
    GeologyProfile,
    GeologyProvince,
    WorldGeologyRecipe,
)
from map_maker.terrain.pipeline.control import CancellationToken, check_cancelled
from map_maker.terrain.pipeline.world import (
    WorldMap,
    component_area_km2,
    components_from_geometry,
)


@dataclass(frozen=True, slots=True)
class GeologyRegion:
    id: str
    name: str
    province: bool
    profile: GeologyProfile
    components: tuple[LandComponent, ...]
    area_km2: float
    geometry: BaseGeometry


@dataclass(frozen=True, slots=True)
class GeologyCoverage:
    recipe: WorldGeologyRecipe
    world: WorldMap
    regions: tuple[GeologyRegion, ...]

    def at(self, point: Point2D) -> GeologyRegion | None:
        """Province wins boundary ties; equal-priority shared edges use stable IDs."""
        x0, _, _, _ = self.recipe.world.frame.bounds
        width = self.recipe.world.frame.width
        position = Point(x0 + (point[0] - x0) % width, point[1])
        return next((r for r in self.regions if r.geometry.covers(position)), None)


def province_geometry(province: GeologyProvince, frame: WorldFrame) -> BaseGeometry:
    polygon = Polygon(province.vertices)
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        raise ValueError(f"{province.name}: invalid polygon ({explain_validity(polygon)}).")
    boundary = box(*frame.bounds)
    return unary_union(
        [
            translate(polygon, xoff=offset).intersection(boundary)
            for offset in (-frame.width, 0.0, frame.width)
        ]
    )


def resolve_geology(
    world: WorldMap,
    recipe: WorldGeologyRecipe,
    cancellation: CancellationToken | None = None,
) -> GeologyCoverage:
    """Highest priority replaces the entire default profile, including unknowns."""
    if recipe.world != world.project:
        raise ValueError("Geology recipe belongs to a different world source, frame or ownership.")
    check_cancelled(cancellation)
    continents: dict[str, BaseGeometry] = {}
    for continent in world.continents:
        check_cancelled(cancellation)
        continents[continent.id] = unary_union(
            [
                Polygon(c.exterior, c.holes)
                for land in world.land
                if land.continent_id == continent.id
                for c in land.components
            ]
        )
    remaining = unary_union(list(continents.values()))
    regions: list[GeologyRegion] = []

    def region(
        key: str, name: str, province: bool, profile: GeologyProfile, geometry: BaseGeometry
    ) -> None:
        components = components_from_geometry(geometry)
        area = fsum(component_area_km2(c, recipe.world.frame) for c in components)
        regions.append(GeologyRegion(key, name, province, profile, components, area, geometry))

    for priority in sorted({p.priority for p in recipe.provinces}, reverse=True):
        group: list[tuple[GeologyProvince, BaseGeometry]] = []
        for province in sorted(recipe.provinces, key=lambda p: p.id):
            if province.priority != priority:
                continue
            check_cancelled(cancellation)
            geometry = province_geometry(province, recipe.world.frame).intersection(remaining)
            for other, other_geometry in group:
                if geometry.intersection(other_geometry).area > 0:
                    raise ValueError(
                        f"{province.name} and {other.name} overlap on land at priority {priority}. "
                        "Give one a higher priority or redraw their boundaries."
                    )
            group.append((province, geometry))
            region(province.id, province.name, True, province.profile, geometry)
        remaining = remaining.difference(unary_union([geometry for _, geometry in group]))
    names = {c.id: c.name for c in world.continents}
    for default in sorted(recipe.defaults, key=lambda d: d.continent_id):
        check_cancelled(cancellation)
        region(
            "continent:" + default.continent_id,
            names[default.continent_id],
            False,
            default.profile,
            continents[default.continent_id].intersection(remaining),
        )
    if not isclose(
        fsum(r.area_km2 for r in regions),
        world.land_area_km2,
        rel_tol=1e-9,
        abs_tol=recipe.world.frame.surface_area_km2 * 1e-12,
    ):
        raise ValueError("Resolved geology does not conserve prepared world land area.")
    check_cancelled(cancellation)
    return GeologyCoverage(recipe, world, tuple(regions))
