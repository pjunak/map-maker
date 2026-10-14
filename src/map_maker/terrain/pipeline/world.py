# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Read-only spherical world inspection; no terrain or climate is generated here."""

from dataclasses import dataclass
from itertools import pairwise
from math import cos, fsum, pi, sin
from typing import Literal

from shapely.affinity import translate
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from map_maker.terrain.domain.models import LandComponent, Point2D
from map_maker.terrain.domain.world import (
    WORLD_BORDER_OVERLAP_FRACTION,
    WorldFeature,
    WorldFrame,
    WorldGeometryError,
    WorldProject,
    WorldRole,
)


@dataclass(frozen=True, slots=True)
class WorldLandView:
    feature_id: str
    continent_id: str
    role: WorldRole
    components: tuple[LandComponent, ...]


@dataclass(frozen=True, slots=True)
class ContinentSummary:
    id: str
    name: str
    area_km2: float
    land_shapes: int
    island_shapes: int


@dataclass(frozen=True, slots=True)
class WorldAdjustment:
    kind: Literal["edge_clip", "shared_land", "border_overlap", "pole_cover"]
    feature_ids: tuple[str, ...]
    area_source_units2: float
    message: str


@dataclass(frozen=True, slots=True)
class WorldMap:
    project: WorldProject
    land: tuple[WorldLandView, ...]
    continents: tuple[ContinentSummary, ...]
    land_area_km2: float
    adjustments: tuple[WorldAdjustment, ...] = ()

    @property
    def land_fraction(self) -> float:
        return self.land_area_km2 / self.project.frame.surface_area_km2


def _polygons(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty or geometry.area <= 0 else [geometry]
    if not isinstance(geometry, (MultiPolygon, GeometryCollection)):
        return []
    return [
        p
        for g in geometry.geoms
        if isinstance(g, (Polygon, MultiPolygon, GeometryCollection))
        for p in _polygons(g)
    ]


def _ring_area(ring: tuple[Point2D, ...], frame: WorldFrame) -> float:
    # Integrate sin(latitude) d(longitude) along source-linear segments. Remove
    # a constant reference sine (whose closed-ring integral is zero) before
    # summing, so tiny pockets do not cancel large nearly equal contributions.
    reference_y = ring[0][1]
    reference = pi / 2 - (reference_y - frame.bounds[1]) / frame.height * pi
    terms: list[float] = []
    for (x0, y0), (x1, y1) in pairwise(ring):
        a = -(y0 - reference_y) / frame.height * pi
        b = -(y1 - reference_y) / frame.height * pi
        middle, half_delta = (a + b) / 2, (b - a) / 2
        squared = half_delta * half_delta
        # Evaluate sinc(h)-1 directly near zero instead of subtracting two
        # rounded ones; through h^6 the omitted term is below 3e-22 at |h|=.01.
        sinc_delta = (
            squared * (-1 / 6 + squared * (1 / 120 - squared / 5040))
            if abs(half_delta) < 0.01
            else sin(half_delta) / half_delta - 1
        )
        mean_sine_offset = (
            2 * cos(reference + middle / 2) * sin(middle / 2) + sin(reference + middle) * sinc_delta
        )
        terms.append((x1 - x0) / frame.width * 2 * pi * mean_sine_offset)
    return abs(fsum(terms)) * frame.radius_km**2


def component_area_km2(component: LandComponent, frame: WorldFrame) -> float:
    return max(
        0.0,
        _ring_area(component.exterior, frame)
        - sum(_ring_area(hole, frame) for hole in component.holes),
    )


type _Geometry = Polygon | MultiPolygon


@dataclass(frozen=True, slots=True)
class _PreparedShape:
    feature: WorldFeature
    continent_id: str
    role: WorldRole
    geometry: _Geometry


def components_from_geometry(geometry: BaseGeometry) -> tuple[LandComponent, ...]:
    return tuple(
        LandComponent(
            tuple((float(x), float(y)) for x, y in polygon.exterior.coords),
            tuple(
                tuple((float(x), float(y)) for x, y in hole.coords) for hole in polygon.interiors
            ),
        )
        for polygon in sorted(_polygons(geometry), key=lambda p: (*p.bounds, p.area))
    )


def _reconcile_land(
    shapes: list[_PreparedShape],
    tolerance: float,
) -> tuple[tuple[WorldLandView, ...], list[WorldAdjustment]]:
    geometries = [s.geometry for s in shapes]
    tree = STRtree(geometries)
    neighbours: list[list[int]] = [[] for _ in shapes]
    foreign_overlaps: dict[int, list[BaseGeometry]] = {}
    bands: dict[int, BaseGeometry] = {}
    adjustments: list[WorldAdjustment] = []
    conflicts: list[str] = []
    affected: set[str] = set()
    for index, shape in enumerate(shapes):
        for other in sorted(int(i) for i in tree.query(shape.geometry) if int(i) > index):
            second = shapes[other]
            overlap = shape.geometry.intersection(second.geometry)
            if overlap.area <= 0:
                continue
            neighbours[index].append(other)
            neighbours[other].append(index)
            ids = (shape.feature.id, second.feature.id)
            descriptions = f"{shape.feature.description} / {second.feature.description}"
            if shape.continent_id == second.continent_id:
                adjustments.append(
                    WorldAdjustment(
                        "shared_land",
                        ids,
                        float(overlap.area),
                        f"Overlapping land within one continent is counted once: {descriptions}.",
                    )
                )
                continue
            for key in (index, other):
                foreign_overlaps.setdefault(key, []).append(overlap)
                if key not in bands:
                    boundary = shapes[key].geometry.boundary
                    assert boundary is not None  # Prepared shapes contain polygonal land.
                    bands[key] = boundary.buffer(tolerance)
            small = overlap.area <= min(shape.geometry.area, second.geometry.area) * (
                WORLD_BORDER_OVERLAP_FRACTION
            )
            if not small or not all(bands[k].covers(overlap) for k in (index, other)):
                affected.update(ids)
                if len(conflicts) < 6:
                    conflicts.append(
                        f"{shape.feature.description} overlaps {second.feature.description} "
                        f"by {overlap.area:.6g} square source units."
                    )
            else:
                adjustments.append(
                    WorldAdjustment(
                        "border_overlap",
                        ids,
                        float(overlap.area),
                        f"A narrow continent-border overlap is counted once: {descriptions}.",
                    )
                )
    # Fragmenting a border into many small shapes must not evade the per-feature
    # area budget. Check the union of all foreign overlaps, not only each pair.
    for index, overlaps in foreign_overlaps.items():
        shape = shapes[index]
        if unary_union(overlaps).area > shape.geometry.area * WORLD_BORDER_OVERLAP_FRACTION:
            if len(conflicts) < 6:
                conflicts.append(
                    f"{shape.feature.description}: combined border overlaps exceed "
                    f"{WORLD_BORDER_OVERLAP_FRACTION:.2%} of this shape's area."
                )
            affected.add(shape.feature.id)
            affected.update(
                shapes[j].feature.id
                for j in neighbours[index]
                if shapes[j].continent_id != shape.continent_id
            )
    if affected:
        raise WorldGeometryError(
            "Different continents overlap beyond the export tolerance.\n"
            + "\n".join(conflicts)
            + "\nResolve these ownership conflicts or outlines. Large overlaps cannot "
            "be inferred from export rounding; source geometry is unchanged.",
            tuple(sorted(affected)),
        )
    # Assign shared coverage once: mainland first, then larger footprint, then ID.
    # Subtraction preserves the union and every source ID/assignment. A contained
    # redundant shape legitimately contributes no additional prepared coverage.
    order = sorted(
        range(len(shapes)),
        key=lambda i: (
            shapes[i].role != "mainland",
            -geometries[i].area,
            shapes[i].feature.id,
        ),
    )
    accepted: set[int] = set()
    land: list[WorldLandView] = []
    for index in order:
        shape = shapes[index]
        prior = [geometries[j] for j in sorted(neighbours[index]) if j in accepted]
        geometry = shape.geometry.difference(unary_union(prior)) if prior else shape.geometry
        land.append(
            WorldLandView(
                shape.feature.id,
                shape.continent_id,
                shape.role,
                components_from_geometry(geometry),
            )
        )
        accepted.add(index)
    return tuple(sorted(land, key=lambda f: f.feature_id)), adjustments


def prepare_world_map(project: WorldProject) -> WorldMap:
    """Prepare bounded, non-overlapping coverage while retaining the authored source."""
    frame = project.frame
    frame_polygon = box(*frame.bounds)
    tolerance = frame.geometry_tolerance
    features = {f.id: f for f in project.source.features}
    shapes: list[_PreparedShape] = []
    adjustments: list[WorldAdjustment] = []
    for assignment in sorted(project.assignments, key=lambda a: a.feature_id):
        if assignment.continent_id is None:
            continue
        feature = features[assignment.feature_id]
        parts: list[Polygon] = []
        clipped_area = 0.0
        overflow = 0.0
        for component in feature.components:
            polygon = Polygon(component.exterior, component.holes)
            x0, y0, x1, y1 = polygon.bounds
            outside = max(frame.bounds[1] - y0, y1 - frame.bounds[3], 0.0)
            if (
                outside > tolerance
                or x1 - x0 > frame.width
                or x0 < frame.bounds[0] - frame.width
                or x1 > frame.bounds[2] + frame.width
            ):
                raise WorldGeometryError(
                    f"{feature.description}: land is outside the full-world frame. "
                    f"Shape bounds: ({x0:.9g}, {y0:.9g}) to ({x1:.9g}, {y1:.9g}); "
                    f"frame: {frame.bounds}. Allowed edge rounding: {tolerance:.6g} source units. "
                    "Check the declared frame and source geography.",
                    (feature.id,),
                )
            component_parts: list[Polygon] = []
            for offset in (-frame.width, 0.0, frame.width):
                clipped = translate(polygon, xoff=offset).intersection(frame_polygon)
                if isinstance(clipped, (Polygon, MultiPolygon, GeometryCollection)):
                    component_parts.extend(_polygons(clipped))
            parts.extend(component_parts)
            if outside > 0:
                overflow = max(overflow, outside)
                clipped_area += max(0.0, polygon.area - sum(p.area for p in component_parts))
        if not parts:
            raise WorldGeometryError(
                f"{feature.description}: no land lies inside the world frame.",
                (feature.id,),
            )
        if overflow > 0:
            adjustments.append(
                WorldAdjustment(
                    "edge_clip",
                    (feature.id,),
                    clipped_area,
                    f"Trimmed {overflow:.6g} source units of export overflow at the world edge: "
                    f"{feature.description}.",
                )
            )
        geometry = unary_union(parts)
        assert isinstance(geometry, (Polygon, MultiPolygon))
        shapes.append(_PreparedShape(feature, assignment.continent_id, assignment.role, geometry))
    land, overlaps = _reconcile_land(shapes, tolerance)
    adjustments.extend(overlaps)
    return world_from_land(project, land, tuple(adjustments))


def world_from_land(
    project: WorldProject,
    land: tuple[WorldLandView, ...],
    adjustments: tuple[WorldAdjustment, ...],
) -> WorldMap:
    """A world map over prepared ``land``, with each continent's area summarised."""
    frame = project.frame
    summaries = tuple(
        ContinentSummary(
            continent.id,
            continent.name,
            sum(
                component_area_km2(c, frame)
                for f in land
                if f.continent_id == continent.id
                for c in f.components
            ),
            sum(f.continent_id == continent.id for f in land),
            sum(f.continent_id == continent.id and f.role == "island" for f in land),
        )
        for continent in sorted(project.continents, key=lambda c: (c.name.casefold(), c.id))
    )
    for summary in summaries:
        if not any(f.components for f in land if f.continent_id == summary.id):
            raise WorldGeometryError(
                f"{summary.name}: no independent land remains after resolving overlaps.",
                tuple(f.feature_id for f in land if f.continent_id == summary.id),
            )
    return WorldMap(project, land, summaries, sum(s.area_km2 for s in summaries), adjustments)
