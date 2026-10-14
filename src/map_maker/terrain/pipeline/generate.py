# pyright: reportUnknownMemberType=false
"""First deterministic coastline-conditioned terrain pipeline."""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any, cast

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from map_maker.terrain.domain import (
    Coastline,
    ElevationMode,
    ElevationPoint,
    EndpointGrid,
    LocalMetricFrame,
    TerrainBasin,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainRegion,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.domain.seeds import RELIEF_STAGE_ID, stage_seed
from map_maker.terrain.domain.terrain_context import TerrainWorldContext
from map_maker.terrain.pipeline.basin_flow import BasinOutflow, resolve_basin_outflow
from map_maker.terrain.pipeline.channel_floor import ChannelFloorReconstruction
from map_maker.terrain.pipeline.channel_reconstruction import ChannelReconstruction
from map_maker.terrain.pipeline.control import (
    CancellationToken,
    cancellable_progress,
    check_cancelled,
)
from map_maker.terrain.pipeline.control import ProgressCallback as ProgressCallback
from map_maker.terrain.pipeline.diagnostics import (
    ChannelConflicts,
    DrainageAnalysis,
    RoutingAgreement,
    review_drainage_routing,
)
from map_maker.terrain.pipeline.grid import grid_coordinates
from map_maker.terrain.pipeline.hydrology import (
    DrainageIncision,
    automatic_incision_budget,
    drainage_incision,
)
from map_maker.terrain.pipeline.landforms import (
    MetricRegion,
    prepare_regions,
    regional_elevation_fields,
    regional_incision_budget,
    regional_transition_mask,
)
from map_maker.terrain.pipeline.noise import fractal_value_noise
from map_maker.terrain.pipeline.profile import shape_preserving_profile
from map_maker.terrain.pipeline.ridge_crests import (
    CrestBlend,
    ProfileRidge,
    smooth_connected_ridges,
    validate_ridge_contacts,
)
from map_maker.terrain.pipeline.routing_edges import sample_mountain_barriers
from map_maker.terrain.pipeline.terrain_context import PreparedWorldContext
from map_maker.terrain.pipeline.water import (
    MetricBasin,
    WaterProducts,
    basin_intent_ids,
    prepare_basins,
    water_products,
)
from map_maker.terrain.pipeline.water_budget import WaterSamplingBudget, plan_water_sampling_budget
from map_maker.terrain.pipeline.water_sampling import (
    SamplingDensity,
    SamplingFeature,
    SamplingGuide,
)

GENERATOR_ALGORITHM_ID = "coastline-constraint-terrain@21"
AUTOMATIC_VALLEY_ALGORITHM_ID = "regional-budget-mfd-d8-valleys@15"
NOISE_ALGORITHM_ID = "coordinate-value-noise-fixed-budget@2"


@dataclass(frozen=True, slots=True)
class GeneratedTerrain:
    """Authoritative numeric result of one in-memory terrain generation."""

    elevation_m: NDArray[np.float32]
    land_mask: NDArray[np.bool_]
    x_km: NDArray[np.float64]
    y_km: NDArray[np.float64]
    settings: TerrainSettings
    constraints: tuple[TerrainConstraint, ...]
    source_name: str
    drainage: DrainageAnalysis
    routing_grid_shape: tuple[int, int]
    routing: DrainageIncision
    routing_land_mask: NDArray[np.bool_]
    routing_final_elevation_m: NDArray[np.float64]
    routing_agreement: RoutingAgreement
    routing_conflicts: ChannelConflicts
    water: WaterProducts
    basin_outflow: BasinOutflow
    world_context: TerrainWorldContext | None = None

    @property
    def grid(self) -> EndpointGrid:
        return EndpointGrid(
            (float(self.x_km[0]), float(self.y_km[0]),
             float(self.x_km[-1]), float(self.y_km[-1])),
            self.width, self.height,
        )

    @property
    def routing_grid(self) -> EndpointGrid:
        height, width = self.routing_grid_shape
        return EndpointGrid(self.grid.extent_km, width, height)

    @property
    def width(self) -> int:
        return int(self.elevation_m.shape[1])

    @property
    def height(self) -> int:
        return int(self.elevation_m.shape[0])


@dataclass(frozen=True, slots=True)
class _AutomaticValleyField:
    """Resolution-independent broad incision sampled from a canonical grid."""

    x_km: NDArray[np.float64]
    y_km: NDArray[np.float64]
    drainage: DrainageIncision
    land_mask: NDArray[np.bool_]
    floor: ChannelFloorReconstruction
    _reconstruction: ChannelReconstruction = field(repr=False)
    basins: tuple[MetricBasin, ...] = ()

    def sample_shaping(
        self,
        x_km: NDArray[np.float64],
        y_km: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return self._reconstruction.sample(x_km, y_km)


def _report(callback: ProgressCallback | None, fraction: float, message: str) -> None:
    if callback is not None:
        callback(fraction, message)


type LandGeometry = Polygon | MultiPolygon


def _metric_polygon(
    coastline: Coastline, object_scale_km: float
) -> tuple[LandGeometry, float, float]:
    frame = LocalMetricFrame(coastline.bounds, object_scale_km)
    def metric_ring(
        ring: tuple[tuple[float, float], ...],
    ) -> list[tuple[float, float]]:
        return [frame.source_to_local(point) for point in ring]

    polygons = [
        Polygon(
            metric_ring(component.exterior),
            holes=[metric_ring(hole) for hole in component.holes],
        )
        for component in coastline.components
    ]
    polygon = unary_union(polygons)
    if not isinstance(polygon, (Polygon, MultiPolygon)):
        raise ValueError("The coastlines do not form polygonal land geometry.")
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError("The coastline does not form a valid land polygon.")
    return polygon, frame.width_km, frame.height_km


STRUCTURE_MIN_TAPER = .35
STRUCTURE_MIN_WIDTH_VARIATION = .82
ATTACHED_POINT_RADIUS_FACTOR = .45


@dataclass(frozen=True, slots=True)
class _MetricConstraint:
    kind: str
    geometry: Point | LineString
    elevation_m: float
    influence_radius_km: float
    elevation_mode: ElevationMode
    intensity: float = 1.0
    profile_anchors: tuple[tuple[float, float, float], ...] = ()
    explicit_profile: bool = False
    source_instruction: int = 0
    attached_to_structure: bool = False
    taper_start: bool = True
    taper_end: bool = True
    downstream_positions_km: tuple[float, ...] = ()
    downstream_floor_m: tuple[float, ...] = ()


def _smooth_structure_points(
    points: list[tuple[float, float]], iterations: int = 3
) -> list[tuple[float, float]]:
    """Round authored polyline corners while preserving its two endpoints."""

    if len(points) <= 2:
        return points
    smoothed = points
    for _ in range(iterations):
        refined = [smoothed[0]]
        for first, second in pairwise(smoothed):
            refined.append(
                (
                    0.75 * first[0] + 0.25 * second[0],
                    0.75 * first[1] + 0.25 * second[1],
                )
            )
            refined.append(
                (
                    0.25 * first[0] + 0.75 * second[0],
                    0.25 * first[1] + 0.75 * second[1],
                )
            )
        refined.append(smoothed[-1])
        smoothed = refined
    return smoothed


def _preserve_structure_junction_widths(
    constraints: list[_MetricConstraint],
) -> None:
    """Disable endpoint narrowing where compatible authored structures meet."""

    for index, constraint in enumerate(constraints):
        if constraint.kind not in ("ridge", "valley"):
            continue
        line = cast(LineString, constraint.geometry)
        endpoints = (Point(line.coords[0]), Point(line.coords[-1]))
        connected = [False, False]
        for other_index, other in enumerate(constraints):
            if (
                other_index == index
                or other.kind != constraint.kind
                or other.elevation_mode != constraint.elevation_mode
            ):
                continue
            tolerance_km = min(
                2.0,
                0.02
                * min(
                    constraint.influence_radius_km,
                    other.influence_radius_km,
                ),
            )
            for endpoint_index, endpoint in enumerate(endpoints):
                if float(other.geometry.distance(endpoint)) <= tolerance_km:
                    connected[endpoint_index] = True
        constraints[index] = replace(
            constraint,
            taper_start=not connected[0],
            taper_end=not connected[1],
        )


def _metric_constraints(
    constraints: Sequence[TerrainConstraint],
    polygon: LandGeometry,
    width_km: float,
    height_km: float,
    maximum_elevation_m: float,
) -> tuple[_MetricConstraint, ...]:
    converted: list[_MetricConstraint] = []
    connected_ridges = smooth_connected_ridges({
        number: LineString([(x*width_km, y*height_km) for x, y in c.points])
        for number, c in enumerate(constraints, start=1)
        if isinstance(c, TerrainStructure) and c.kind == "ridge"
        and c.elevation_mode == "absolute" and c.profile
    }, _smooth_structure_points)
    absolute_points: dict[tuple[float, float], float] = {}
    for instruction, constraint in enumerate(constraints, start=1):
        if isinstance(constraint, (TerrainRegion, TerrainBasin)):
            continue
        if (
            constraint.elevation_mode == "absolute"
            and constraint.elevation_m > maximum_elevation_m
        ):
            raise ValueError(
                f"Authored elevation {constraint.elevation_m:,.0f} m exceeds the "
                f"{maximum_elevation_m:,.0f} m elevation ceiling."
            )
        if isinstance(constraint, ElevationPoint):
            x, y = constraint.position
            geometry: Point | LineString = Point(x * width_km, y * height_km)
            if constraint.elevation_mode == "absolute":
                position = (geometry.x, geometry.y)
                existing = absolute_points.get(position)
                if existing is not None and existing != constraint.elevation_m:
                    raise ValueError(
                        "Conflicting height points: absolute targets differ at the same location.")
                absolute_points[position] = constraint.elevation_m
                if constraint.elevation_m != 0. and polygon.boundary.intersects(geometry):
                    raise ValueError(
                        "An absolute height point on the sea-level boundary must be 0 m.")
            kind = "point"
            intensity = 1.0
        elif isinstance(constraint, TerrainBrushStroke):
            metric_points = [(x * width_km, y * height_km) for x, y in constraint.points]
            geometry = (
                Point(metric_points[0])
                if len(metric_points) == 1
                else LineString(metric_points)
            )
            kind = "brush"
            intensity = constraint.intensity
        else:
            metric_points = [(x * width_km, y * height_km) for x, y in constraint.points]
            geometry = (connected_ridges[instruction] if instruction in connected_ridges
                        else LineString(_smooth_structure_points(metric_points)))
            kind = constraint.kind
            intensity = 1.0
        if not polygon.covers(geometry):
            if kind == "point":
                label = "Elevation point"
            elif kind == "brush":
                label = "Terrain brush stroke"
            else:
                label = kind.capitalize()
            raise ValueError(f"{label} constraint extends outside the coastline.")
        profile_anchors: tuple[tuple[float, float, float], ...] = ()
        if isinstance(constraint, TerrainStructure) and constraint.profile:
            if (constraint.elevation_mode == "absolute"
                    and any(k.elevation_m > maximum_elevation_m for k in constraint.profile)):
                raise ValueError("A structure profile height exceeds the elevation ceiling.")
            profile_anchors = tuple(
                (k.position * geometry.length, k.elevation_m, constraint.influence_radius_km)
                for k in constraint.profile
            )
        converted.append(
            _MetricConstraint(
                kind=kind,
                geometry=geometry,
                elevation_m=constraint.elevation_m,
                influence_radius_km=constraint.influence_radius_km,
                elevation_mode=constraint.elevation_mode,
                intensity=intensity,
                profile_anchors=profile_anchors,
                source_instruction=instruction,
                explicit_profile=(isinstance(constraint, TerrainStructure)
                                  and bool(constraint.profile)),
            )
        )
    _preserve_structure_junction_widths(converted)
    structure_indices = [
        index
        for index, constraint in enumerate(converted)
        if constraint.kind in ("ridge", "valley")
    ]
    anchors: dict[int, list[tuple[float, float, float]]] = {
        index: [] for index in structure_indices
    }
    for point_index, point_constraint in enumerate(converted):
        if point_constraint.kind != "point":
            continue
        compatible: list[tuple[float, int]] = []
        for structure_index in structure_indices:
            structure = converted[structure_index]
            # An explicit profile owns this line. Nearby points remain independent
            # hard controls; they cannot silently acquire or reshape its crest/floor.
            if (structure.explicit_profile
                    or structure.elevation_mode != point_constraint.elevation_mode):
                continue
            attachment_distance = max(
                point_constraint.influence_radius_km,
                structure.influence_radius_km,
            )
            distance = float(structure.geometry.distance(point_constraint.geometry))
            if distance > attachment_distance:
                continue
            compatible.append((distance, structure_index))

        if point_constraint.elevation_mode == "relative" and compatible:
            compatible.sort()
            if len(compatible) > 1 and abs(compatible[0][0] - compatible[1][0]) <= 1e-6:
                compatible = []
            else:
                compatible = compatible[:1]

        attached = False
        for _distance, structure_index in compatible:
            structure = converted[structure_index]
            project_line = cast(Any, structure.geometry)
            along_km = float(project_line.project(point_constraint.geometry))
            along_radius_km = max(
                2.0 * point_constraint.influence_radius_km,
                structure.influence_radius_km,
            )
            if point_constraint.elevation_mode == "absolute":
                profile_target_m = point_constraint.elevation_m
            elif structure.kind == "ridge":
                profile_target_m = structure.elevation_m + point_constraint.elevation_m
            else:
                profile_target_m = structure.elevation_m - point_constraint.elevation_m
            if profile_target_m < 0.0:
                raise ValueError(
                    f"Relative point would reverse the {structure.kind} at its profile anchor."
                )
            anchors[structure_index].append(
                (along_km, profile_target_m, along_radius_km)
            )
            attached = True
        if attached:
            converted[point_index] = replace(point_constraint, attached_to_structure=True)
    for structure_index, structure_anchors in anchors.items():
        if structure_anchors:
            converted[structure_index] = replace(
                converted[structure_index],
                profile_anchors=tuple(sorted(structure_anchors)),
            )
    validate_ridge_contacts(tuple(
        ProfileRidge(c.source_instruction, cast(LineString, c.geometry),
                     tuple(a[0] for a in c.profile_anchors),
                     tuple(a[1] for a in c.profile_anchors))
        for c in converted
        if c.kind == "ridge" and c.elevation_mode == "absolute" and c.explicit_profile
    ))
    return tuple(converted)


def _context_factors(
    *, is_structure: bool, is_brush: bool = False, attached_point: bool = False,
) -> tuple[float, float, float]:
    """Shared radius/feature-scale multipliers and amplitude for sampling and ground."""
    if is_structure:
        return 3.0, 0.8, 0.32
    if is_brush:
        return 1.75, 0.3, 0.18
    if attached_point:
        return 1.25, 0.15, 0.04
    return 2.0, 0.35, 0.12


def _constraint_weight(
    distance_km: NDArray[np.float64],
    radius_km: float | NDArray[np.float64],
    largest_feature_km: float,
    *,
    is_structure: bool,
    is_brush: bool = False,
    attached_point: bool = False,
) -> NDArray[np.float64]:
    """Blend a defined landform core into a broader geological context."""

    radius_factor, feature_factor, context_share = _context_factors(
        is_structure=is_structure, is_brush=is_brush, attached_point=attached_point)
    context_radius_km = np.maximum(radius_factor * radius_km, feature_factor * largest_feature_km)
    core = np.exp(-np.log(2.0) * np.square(distance_km / radius_km))
    context = np.exp(-np.log(2.0) * np.square(distance_km / context_radius_km))
    return (1.0 - context_share) * core + context_share * context


def _coast_conditioned_weight(
    weight: NDArray[np.float64],
    distance_to_constraint_km: NDArray[np.float64],
    distance_to_coast_km: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Keep sea level hard while allowing an inland feature to reach its target."""

    denominator = distance_to_coast_km + distance_to_constraint_km
    coast_gate = np.divide(
        distance_to_coast_km,
        denominator,
        out=np.zeros_like(distance_to_coast_km),
        where=denominator > 0.0,
    )
    return weight * coast_gate


def _line_positions_km(
    line: LineString, sample_points: Any
) -> NDArray[np.float64]:
    raw_positions = cast(Any, shapely.line_locate_point(line, sample_points))
    return cast(NDArray[np.float64], np.asarray(raw_positions, dtype=np.float64))


def _coalesced_profile_anchors(
    constraint: _MetricConstraint,
) -> list[tuple[float, float, float]]:
    coalesced: list[tuple[float, float, float]] = []
    for anchor in constraint.profile_anchors:
        if coalesced and abs(anchor[0] - coalesced[-1][0]) <= 1e-6:
            previous = coalesced[-1]
            if abs(anchor[1] - previous[1]) > 1e-6:
                raise ValueError(
                    "Conflicting height points project to the same structure position."
                )
            coalesced[-1] = (previous[0], previous[1], max(previous[2], anchor[2]))
        else:
            coalesced.append(anchor)
    return coalesced


def _structure_profile(
    constraint: _MetricConstraint,
    line_positions_km: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return a shape-preserving target and its authored longitudinal control."""

    target = np.full_like(line_positions_km, constraint.elevation_m)
    if not constraint.profile_anchors:
        return target, np.zeros_like(line_positions_km)

    coalesced = _coalesced_profile_anchors(constraint)

    line = cast(LineString, constraint.geometry)
    line_length = float(line.length)
    first_position, _first_elevation, first_radius = coalesced[0]
    last_position, _last_elevation, last_radius = coalesced[-1]
    first_shoulder = max(0.0, first_position - 2.0 * first_radius)
    last_shoulder = min(line_length, last_position + 2.0 * last_radius)
    knot_positions: list[float] = []
    knot_elevations: list[float] = []

    if first_position > 1e-6:
        knot_positions.append(0.0)
        knot_elevations.append(constraint.elevation_m)
        if first_shoulder > 1e-6:
            knot_positions.append(first_shoulder)
            knot_elevations.append(constraint.elevation_m)
    for along_km, elevation_m, _radius_km in coalesced:
        knot_positions.append(along_km)
        knot_elevations.append(elevation_m)
    if last_position < line_length - 1e-6:
        if last_shoulder < line_length - 1e-6:
            knot_positions.append(last_shoulder)
            knot_elevations.append(constraint.elevation_m)
        knot_positions.append(line_length)
        knot_elevations.append(constraint.elevation_m)

    target = shape_preserving_profile(
        np.asarray(knot_positions, dtype=np.float64),
        np.asarray(knot_elevations, dtype=np.float64),
        line_positions_km,
    )
    authored_control = np.ones_like(line_positions_km)
    if first_position > first_shoulder:
        left_progress = np.clip(
            (line_positions_km - first_shoulder) / (first_position - first_shoulder),
            0.0,
            1.0,
        )
        authored_control = left_progress * left_progress * (3.0 - 2.0 * left_progress)
    if last_position < last_shoulder:
        right_progress = np.clip(
            (last_shoulder - line_positions_km) / (last_shoulder - last_position),
            0.0,
            1.0,
        )
        right_control = right_progress * right_progress * (3.0 - 2.0 * right_progress)
        authored_control = np.minimum(authored_control, right_control)
    between_anchors = (line_positions_km >= first_position) & (
        line_positions_km <= last_position
    )
    authored_control = np.where(between_anchors, 1.0, authored_control)
    return target, np.clip(authored_control, 0.0, 1.0)


def _structure_response(
    constraint: _MetricConstraint,
    sample_points: Any,
    distance_to_coast_km: NDArray[np.float64],
    largest_feature_km: float,
    detail_driver: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return a tapered structure weight and distance along its centreline."""

    raw_distance = cast(Any, shapely.distance(sample_points, constraint.geometry))
    distance = cast(NDArray[np.float64], np.asarray(raw_distance, dtype=np.float64))
    line = cast(LineString, constraint.geometry)
    line_positions = _line_positions_km(line, sample_points)
    distance_to_tapered_end = np.full_like(line_positions, np.inf)
    if constraint.taper_start:
        distance_to_tapered_end = np.minimum(distance_to_tapered_end, line_positions)
    if constraint.taper_end:
        distance_to_tapered_end = np.minimum(
            distance_to_tapered_end,
            line.length - line_positions,
        )
    taper_length = max(2.0 * constraint.influence_radius_km, 0.12 * line.length)
    taper_progress = np.clip(distance_to_tapered_end / taper_length, 0.0, 1.0)
    taper = taper_progress * taper_progress * (3.0 - 2.0 * taper_progress)
    width_variation = STRUCTURE_MIN_WIDTH_VARIATION + 0.36 * (0.5 + 0.5 * detail_driver)
    effective_radius = constraint.influence_radius_km * (STRUCTURE_MIN_TAPER + 0.65 * taper)
    effective_radius *= width_variation
    weight = _constraint_weight(
        distance,
        effective_radius,
        largest_feature_km,
        is_structure=True,
    )
    return (
        _coast_conditioned_weight(weight, distance, distance_to_coast_km),
        line_positions,
    )


def _base_elevation_fields(
    x_km: NDArray[np.float64],
    y_km: NDArray[np.float64],
    distance_to_coast_km: NDArray[np.float64],
    settings: TerrainSettings,
    regions: tuple[MetricRegion, ...] = (),
    world_context: PreparedWorldContext | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return full detail, stable macro elevation, and the shared detail driver."""

    # Macro and full detail are correlated views of one relief stage.
    relief_seed = stage_seed(settings.seed, RELIEF_STAGE_ID)
    relief_noise = fractal_value_noise(
        x_km,
        y_km,
        seed=relief_seed,
        largest_feature_km=settings.largest_feature_km,
        detail_levels=settings.detail_levels,
        roughness=settings.roughness,
    )
    if world_context is not None:
        distance_to_coast_km = world_context.coastal_distance(
            x_km, y_km, distance_to_coast_km,
        )
    coastal_envelope = 1.0 - np.exp(-distance_to_coast_km / settings.coastal_rise_km)
    shaped_noise = np.power(np.clip(0.5 + 0.5 * relief_noise, 0.0, 1.0), 1.35)
    relief = (1.0 - settings.variability) * 0.72 + settings.variability * shaped_noise
    unconditioned_elevation = settings.maximum_elevation_m * coastal_envelope * relief

    macro_noise = fractal_value_noise(
        x_km,
        y_km,
        seed=relief_seed,
        largest_feature_km=settings.largest_feature_km,
        detail_levels=min(2, settings.detail_levels),
        roughness=settings.roughness,
    )
    shaped_macro = np.power(np.clip(0.5 + 0.5 * macro_noise, 0.0, 1.0), 1.35)
    macro_relief = (
        (1.0 - settings.variability) * 0.72
        + settings.variability * shaped_macro
    )
    macro_elevation = settings.maximum_elevation_m * coastal_envelope * macro_relief
    unconditioned_elevation, macro_elevation = regional_elevation_fields(
        x_km, y_km, distance_to_coast_km, unconditioned_elevation, macro_elevation,
        settings, regions,
    )
    return unconditioned_elevation, macro_elevation, relief_noise


def _downstream_valley_floor(
    constraint: _MetricConstraint,
    line_positions_km: NDArray[np.float64],
) -> NDArray[np.float64]:
    if not constraint.downstream_positions_km or not constraint.downstream_floor_m:
        raise RuntimeError("Valley constraint has no prepared downstream floor profile.")
    return np.interp(
        line_positions_km,
        np.asarray(constraint.downstream_positions_km, dtype=np.float64),
        np.asarray(constraint.downstream_floor_m, dtype=np.float64),
    )


def _apply_constraints(
    base_elevation: NDArray[np.float64],
    sample_points: Any,
    distance_to_coast_km: NDArray[np.float64],
    constraints: tuple[_MetricConstraint, ...],
    largest_feature_km: float,
    maximum_elevation_m: float,
    detail_driver: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Condition a broad base surface and report where fine detail should fade."""

    elevation = base_elevation.copy()
    detail_suppression = np.zeros_like(elevation)

    brush_weight = np.zeros_like(elevation)
    brush_targets = np.zeros_like(elevation)
    for constraint in constraints:
        if constraint.kind != "brush" or constraint.elevation_mode != "absolute":
            continue
        raw_distance = cast(Any, shapely.distance(sample_points, constraint.geometry))
        distance = cast(NDArray[np.float64], np.asarray(raw_distance, dtype=np.float64))
        weight = constraint.intensity * _constraint_weight(
            distance,
            constraint.influence_radius_km,
            largest_feature_km,
            is_structure=False,
            is_brush=True,
        )
        weight = _coast_conditioned_weight(weight, distance, distance_to_coast_km)
        brush_weight += weight
        brush_targets += weight * constraint.elevation_m
    brush_affected = brush_weight > 0.0
    if np.any(brush_affected):
        brush_target = np.divide(
            brush_targets,
            brush_weight,
            out=np.zeros_like(brush_targets),
            where=brush_affected,
        )
        brush_blend = np.clip(brush_weight, 0.0, 1.0)
        elevation = elevation * (1.0 - brush_blend) + brush_target * brush_blend
        detail_suppression = np.maximum(detail_suppression, brush_blend)

    relative_brush_delta = np.zeros_like(elevation)
    for constraint in constraints:
        if constraint.kind != "brush" or constraint.elevation_mode != "relative":
            continue
        raw_distance = cast(Any, shapely.distance(sample_points, constraint.geometry))
        distance = cast(NDArray[np.float64], np.asarray(raw_distance, dtype=np.float64))
        weight = constraint.intensity * _constraint_weight(
            distance,
            constraint.influence_radius_km,
            largest_feature_km,
            is_structure=False,
            is_brush=True,
        )
        weight = _coast_conditioned_weight(weight, distance, distance_to_coast_km)
        relative_brush_delta += weight * constraint.elevation_m
    elevation += relative_brush_delta

    ridge_raise = np.zeros_like(elevation)
    ridge_profile_weight = np.zeros_like(elevation)
    ridge_profile_targets = np.zeros_like(elevation)
    for constraint in constraints:
        if (constraint.kind != "ridge" or constraint.elevation_mode != "absolute"
                or constraint.explicit_profile):
            continue
        weight, line_positions = _structure_response(
            constraint,
            sample_points,
            distance_to_coast_km,
            largest_feature_km,
            detail_driver,
        )
        detail_suppression = np.maximum(detail_suppression, weight)
        target, authored_control = _structure_profile(constraint, line_positions)
        generated_relief = np.minimum(
            0.10 * target,
            0.22 * np.maximum(maximum_elevation_m - target, 0.0),
        )
        target += (
            generated_relief
            * np.clip(0.5 + 0.5 * detail_driver, 0.0, 1.0)
            * (1.0 - authored_control)
        )
        ridge_raise = np.maximum(
            ridge_raise,
            weight * (1.0 - authored_control) * np.maximum(target - elevation, 0.0),
        )
        profile_weight = weight * authored_control
        ridge_profile_weight += profile_weight
        ridge_profile_targets += profile_weight * target
    elevation += ridge_raise
    ridge_profile_affected = ridge_profile_weight > 0.0
    if np.any(ridge_profile_affected):
        ridge_profile_target = np.divide(
            ridge_profile_targets,
            ridge_profile_weight,
            out=np.zeros_like(ridge_profile_targets),
            where=ridge_profile_affected,
        )
        ridge_profile_blend = np.clip(ridge_profile_weight, 0.0, 1.0)
        elevation = elevation * (1.0 - ridge_profile_blend) + (
            ridge_profile_target * ridge_profile_blend
        )

    relative_ridge_raise = np.zeros_like(elevation)
    for constraint in constraints:
        if constraint.kind != "ridge" or constraint.elevation_mode != "relative":
            continue
        weight, line_positions = _structure_response(
            constraint,
            sample_points,
            distance_to_coast_km,
            largest_feature_km,
            detail_driver,
        )
        profile_target, authored_control = _structure_profile(
            constraint, line_positions
        )
        profiled_relief = (
            constraint.elevation_m * (1.0 - authored_control)
            + profile_target * authored_control
        )
        relative_ridge_raise = np.maximum(
            relative_ridge_raise,
            weight * profiled_relief,
        )
    elevation += relative_ridge_raise

    # Explicit absolute crests own their axis after other ridge guidance.
    # Stable order also keeps Float32 results independent of instruction order.
    profiled_ridges = sorted(
        (c for c in constraints if c.kind == "ridge" and c.elevation_mode == "absolute"
         and c.explicit_profile),
        key=lambda c: (tuple(cast(LineString, c.geometry).coords), c.profile_anchors,
                       c.influence_radius_km),
    )
    if profiled_ridges:
        blend = CrestBlend(elevation)
        for constraint in profiled_ridges:
            weight, positions = _structure_response(
                constraint, sample_points, distance_to_coast_km, largest_feature_km, detail_driver)
            target, _control = _structure_profile(constraint, positions)
            raw_distance = cast(Any, shapely.distance(sample_points, constraint.geometry))
            distance = cast(NDArray[np.float64], np.asarray(raw_distance, dtype=np.float64))
            blend.add(weight, target, distance)
            detail_suppression = np.maximum(detail_suppression, weight)
        elevation = blend.apply(elevation)

    valley_cut = np.zeros_like(elevation)
    for constraint in constraints:
        if constraint.kind != "valley" or constraint.elevation_mode != "absolute":
            continue
        weight, line_positions = _structure_response(
            constraint,
            sample_points,
            distance_to_coast_km,
            largest_feature_km,
            detail_driver,
        )
        detail_suppression = np.maximum(detail_suppression, weight)
        target = _downstream_valley_floor(constraint, line_positions)
        valley_cut = np.maximum(
            valley_cut,
            weight * np.maximum(elevation - target, 0.0),
        )
    elevation -= valley_cut

    relative_valley_cut = np.zeros_like(elevation)
    for constraint in constraints:
        if constraint.kind != "valley" or constraint.elevation_mode != "relative":
            continue
        weight, line_positions = _structure_response(
            constraint,
            sample_points,
            distance_to_coast_km,
            largest_feature_km,
            detail_driver,
        )
        detail_suppression = np.maximum(detail_suppression, weight)
        floor_target = _downstream_valley_floor(constraint, line_positions)
        relative_valley_cut = np.maximum(
            relative_valley_cut,
            weight * np.maximum(elevation - floor_target, 0.0),
        )
    elevation -= relative_valley_cut

    relative_point_delta = np.zeros_like(elevation)
    for constraint in constraints:
        if (
            constraint.kind != "point"
            or constraint.elevation_mode != "relative"
            or constraint.attached_to_structure
        ):
            continue
        raw_distance = cast(Any, shapely.distance(sample_points, constraint.geometry))
        distance = cast(NDArray[np.float64], np.asarray(raw_distance, dtype=np.float64))
        weight = _constraint_weight(
            distance,
            constraint.influence_radius_km,
            largest_feature_km,
            is_structure=False,
        )
        weight = _coast_conditioned_weight(weight, distance, distance_to_coast_km)
        relative_point_delta += weight * constraint.elevation_m
    elevation += relative_point_delta

    absolute_points = sorted(
        (c for c in constraints if c.kind == "point" and c.elevation_mode == "absolute"),
        key=lambda c: (cast(Point, c.geometry).x, cast(Point, c.geometry).y,
                       c.elevation_m, c.influence_radius_km),
    )
    if not absolute_points:
        return elevation, np.clip(detail_suppression, 0.0, 1.0)
    point_weight = np.zeros_like(elevation)
    point_targets = np.zeros_like(elevation)
    target_weight = np.zeros_like(elevation)
    target_scale = np.ones_like(elevation)
    exact_targets = np.full_like(elevation, np.nan)
    for constraint in absolute_points:
        raw_distance = cast(Any, shapely.distance(sample_points, constraint.geometry))
        distance = cast(NDArray[np.float64], np.asarray(raw_distance, dtype=np.float64))
        weight = _constraint_weight(
            distance,
            (
                ATTACHED_POINT_RADIUS_FACTOR * constraint.influence_radius_km
                if constraint.attached_to_structure
                else constraint.influence_radius_km
            ),
            largest_feature_km,
            is_structure=False,
            attached_point=constraint.attached_to_structure,
        )
        weight = _coast_conditioned_weight(weight, distance, distance_to_coast_km)
        detail_suppression = np.maximum(detail_suppression, weight)
        point_weight += weight
        # Target shares w/(1-w) interpolate each hard point, instead of
        # averaging its height with neighboring targets at its own centre.
        # Rescale all shares by the smallest (1-w) seen so far. This keeps
        # every contribution <= 1 without a singular divide or an epsilon cap.
        gap = 1. - weight
        scale = np.minimum(target_scale, gap)
        previous_share = np.divide(scale, target_scale, out=np.ones_like(scale),
                                   where=target_scale > 0.)
        share = np.divide(weight*scale, gap, out=weight.copy(), where=gap > 0.)
        target_weight = target_weight*previous_share + share
        point_targets = point_targets*previous_share + share*constraint.elevation_m
        target_scale = scale
        np.copyto(exact_targets, constraint.elevation_m, where=distance == 0.)
    affected = target_weight > 0.0
    if np.any(affected):
        target = np.divide(
            point_targets,
            target_weight,
            out=np.zeros_like(point_targets),
            where=affected,
        )
        blend = np.clip(point_weight, 0.0, 1.0)
        elevation = elevation * (1.0 - blend) + target * blend
    # Distinct extremely close points can both round to w=1. Resolve the
    # actual authored coordinate exactly, including a zero-height target.
    exact = np.isfinite(exact_targets)
    elevation = np.where(exact, exact_targets, elevation)
    detail_suppression = np.where(exact, 1., detail_suppression)

    return elevation, np.clip(detail_suppression, 0.0, 1.0)


def _prepare_automatic_valley_field(
    polygon: LandGeometry,
    boundary: Any,
    width_km: float,
    height_km: float,
    settings: TerrainSettings,
    constraints: tuple[_MetricConstraint, ...],
    regions: tuple[MetricRegion, ...] = (),
    world_context: PreparedWorldContext | None = None,
    basins: tuple[MetricBasin, ...] = (),
    progress: ProgressCallback | None = None,
) -> _AutomaticValleyField:
    """Route broad drainage once on a canonical, output-resolution-free grid."""

    grid = EndpointGrid.for_extent((0.0, 0.0, width_km, height_km), 257, minimum_samples=3)
    x_km, y_km = grid_coordinates(grid)
    x_grid, y_grid = np.meshgrid(x_km, y_km)
    land_mask = np.asarray(
        shapely.intersects_xy(polygon, x_grid, y_grid),
        dtype=np.bool_,
    )
    sample_points: Any = shapely.points(x_grid, y_grid)
    raw_distance_to_coast = cast(Any, shapely.distance(sample_points, boundary))
    distance_to_coast_km = cast(
        NDArray[np.float64],
        np.asarray(raw_distance_to_coast, dtype=np.float64),
    )
    full_elevation, macro_elevation, detail_driver = _base_elevation_fields(
        x_grid,
        y_grid,
        distance_to_coast_km,
        settings,
        regions=regions, world_context=world_context,
    )
    conditioned_macro, constraint_influence = _apply_constraints(
        macro_elevation, sample_points, distance_to_coast_km, constraints,
        settings.largest_feature_km, settings.maximum_elevation_m, detail_driver,
    )
    routing_elevation = np.where(
        land_mask, np.clip(conditioned_macro, 0.0, settings.maximum_elevation_m), 0.0,
    )
    budget = regional_incision_budget(
        x_grid, y_grid,
        automatic_incision_budget(settings.maximum_elevation_m, settings.variability), regions,
    )
    retention_terminals = basin_intent_ids(x_grid, y_grid, basins) > 0
    budget[retention_terminals] = 0
    def sample_routing_macro(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float64]:
        _report(progress, 0.062, "Reviewing mountain passes")
        points = shapely.points(x, y)
        coast_distance = np.asarray(shapely.distance(points, boundary), dtype=np.float64)
        _full, macro, driver = _base_elevation_fields(
            x, y, coast_distance, settings, regions, world_context,
        )
        conditioned, _influence = _apply_constraints(
            macro, points, coast_distance, constraints, settings.largest_feature_km,
            settings.maximum_elevation_m, driver,
        )
        # Retain the existing node/coast topology. Non-land interiors are sea
        # level observations, not newly invented land receivers or coast exits.
        return np.where(shapely.intersects_xy(polygon, x, y),
                        np.clip(conditioned, 0., settings.maximum_elevation_m), 0.)

    _report(progress, 0.062, "Reviewing mountain passes")
    edge_barriers = sample_mountain_barriers(
        x_km, y_km, routing_elevation, land_mask, regions, settings.seed, sample_routing_macro,
    )
    _report(progress, 0.068, "Routing canonical drainage")
    drainage = drainage_incision(
        routing_elevation,
        land_mask,
        distance_to_coast_km,
        x_spacing_km=grid.x_spacing_km,
        y_spacing_km=grid.y_spacing_km,
        maximum_elevation_m=settings.maximum_elevation_m,
        variability=settings.variability,
        drainage_density=settings.drainage_density,
        residual_detail_m=(full_elevation - macro_elevation) * (1.0 - constraint_influence),
        incision_budget_m=budget,
        retention_terminal_mask=retention_terminals,
        edge_barriers_m=edge_barriers,
    )
    _report(progress, 0.072, "Preparing connected valley shapes")
    reconstruction = ChannelReconstruction.prepare(x_km, y_km, drainage)
    nodal_floor = np.maximum(
        np.maximum(macro_elevation - drainage.incision_m, 0.)
        + (full_elevation - macro_elevation) * (1. - drainage.detail_suppression), 0.,
    )
    def sample_channel_source(
        x: NDArray[np.float64], y: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
        _report(progress, 0.076, "Preparing channel floor profiles")
        points = shapely.points(x, y)
        coast_distance = np.asarray(shapely.distance(points, boundary), dtype=np.float64)
        full, macro, _driver = _base_elevation_fields(
            x, y, coast_distance, settings, regions, world_context,
        )
        _incision, suppression = reconstruction.sample(x, y)
        available = np.asarray(shapely.intersects_xy(polygon, x, y), dtype=np.bool_)
        if basins:
            available &= basin_intent_ids(x, y, basins) == 0
        return macro, (full-macro)*(1-suppression), available

    _report(progress, 0.076, "Preparing channel floor profiles")
    floor = ChannelFloorReconstruction.prepare(
        reconstruction.incision, nodal_floor, drainage.receivers, drainage.channel_mask, land_mask,
        sample_source=sample_channel_source,
    )
    return _AutomaticValleyField(
        x_km=x_km,
        y_km=y_km,
        drainage=drainage,
        land_mask=land_mask,
        floor=floor,
        _reconstruction=reconstruction,
        basins=basins,
    )


def _absolute_valley_profile(
    constraint: _MetricConstraint,
    positions_km: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Build an upstream-to-outlet floor through exact absolute anchors."""

    anchors = _coalesced_profile_anchors(constraint)
    if not anchors:
        return np.full_like(positions_km, constraint.elevation_m)

    line = cast(LineString, constraint.geometry)
    augmented = list(anchors)
    first_position, first_elevation, first_radius = augmented[0]
    if first_position > 1e-6:
        augmented.insert(0, (0.0, first_elevation, first_radius))
    last_position, _last_elevation, last_radius = augmented[-1]
    if last_position < line.length - 1e-6:
        augmented.append((float(line.length), constraint.elevation_m, last_radius))

    elevations = np.asarray([anchor[1] for anchor in augmented], dtype=np.float64)
    if np.any(np.diff(elevations) > 1e-6):
        raise ValueError(
            "Absolute valley floor anchors must not rise downstream; "
            "draw the valley from its head toward its outlet."
        )
    profiled_constraint = replace(constraint, profile_anchors=tuple(augmented))
    target, _authored_control = _structure_profile(
        profiled_constraint,
        positions_km,
    )
    return target


def _relative_valley_depth_profile(
    constraint: _MetricConstraint,
    positions_km: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Extend the first authored incision upstream before shaping the outlet reach."""

    anchors = _coalesced_profile_anchors(constraint)
    if not anchors:
        return np.full_like(positions_km, constraint.elevation_m)

    line = cast(LineString, constraint.geometry)
    augmented = list(anchors)
    first_position, first_depth, first_radius = augmented[0]
    if first_position > 1e-6:
        augmented.insert(0, (0.0, first_depth, first_radius))
    last_position, _last_depth, last_radius = augmented[-1]
    if last_position < line.length - 1e-6:
        augmented.append((float(line.length), constraint.elevation_m, last_radius))
    profiled_constraint = replace(constraint, profile_anchors=tuple(augmented))
    depth, _authored_control = _structure_profile(
        profiled_constraint,
        positions_km,
    )
    return depth


def _prepare_downstream_valley_profiles(
    constraints: tuple[_MetricConstraint, ...],
    boundary: Any,
    settings: TerrainSettings,
    regions: tuple[MetricRegion, ...] = (),
    world_context: PreparedWorldContext | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[_MetricConstraint, ...]:
    """Prepare resolution-independent non-rising floors for authored valleys."""

    if not any(constraint.kind == "valley" for constraint in constraints):
        return constraints
    reference_constraints = tuple(
        constraint
        for constraint in constraints
        if constraint.kind in ("brush", "ridge")
    )
    prepared: list[_MetricConstraint] = []
    for constraint in constraints:
        _report(progress, 0.04, "Preparing authored valley profiles")
        if constraint.kind != "valley":
            prepared.append(constraint)
            continue

        line = cast(LineString, constraint.geometry)
        sample_spacing_km = min(
            2.0,
            max(0.25, 0.25 * constraint.influence_radius_km),
        )
        sample_count = max(2, int(np.ceil(line.length / sample_spacing_km)) + 1)
        positions_km = np.linspace(0.0, line.length, sample_count, dtype=np.float64)
        if constraint.profile_anchors:
            positions_km = np.unique(
                np.concatenate(
                    (
                        positions_km,
                        np.asarray(
                            [anchor[0] for anchor in constraint.profile_anchors],
                            dtype=np.float64,
                        ),
                    )
                )
            )
        if constraint.elevation_mode == "absolute":
            preferred_floor = _absolute_valley_profile(constraint, positions_km)
        else:
            coordinates = np.asarray(
                [line.interpolate(float(position)).coords[0] for position in positions_km],
                dtype=np.float64,
            )
            x_km = coordinates[:, 0]
            y_km = coordinates[:, 1]
            sample_points: Any = shapely.points(x_km, y_km)
            raw_distance_to_coast = cast(
                Any,
                shapely.distance(sample_points, boundary),
            )
            distance_to_coast_km = cast(
                NDArray[np.float64],
                np.asarray(raw_distance_to_coast, dtype=np.float64),
            )
            full_elevation, macro_elevation, detail_driver = _base_elevation_fields(
                x_km,
                y_km,
                distance_to_coast_km,
                settings,
                regions=regions, world_context=world_context,
            )
            conditioned_macro, reference_influence = _apply_constraints(
                macro_elevation,
                sample_points,
                distance_to_coast_km,
                reference_constraints,
                settings.largest_feature_km,
                settings.maximum_elevation_m,
                detail_driver,
            )
            # Relative depth is measured before generated incision. This fixed
            # reference breaks the valley-profile / drainage routing cycle.
            reference_elevation = conditioned_macro + (
                (full_elevation - macro_elevation) * (1.0 - reference_influence)
            )
            depth = _relative_valley_depth_profile(constraint, positions_km)
            preferred_floor = reference_elevation - depth
        preferred_floor = np.clip(
            preferred_floor,
            0.0,
            settings.maximum_elevation_m,
        )
        downstream_floor = np.minimum.accumulate(preferred_floor)
        prepared.append(
            replace(
                constraint,
                downstream_positions_km=tuple(float(value) for value in positions_km),
                downstream_floor_m=tuple(float(value) for value in downstream_floor),
            )
        )
    return tuple(prepared)


def _evaluate_elevation_samples(
    x_grid: NDArray[np.float64],
    y_grid: NDArray[np.float64],
    polygon: LandGeometry,
    boundary: Any,
    settings: TerrainSettings,
    constraints: tuple[_MetricConstraint, ...],
    automatic_valleys: _AutomaticValleyField,
    regions: tuple[MetricRegion, ...] = (),
    world_context: PreparedWorldContext | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Evaluate the complete terrain pipeline at arbitrary metric coordinates."""

    land_mask = np.asarray(
        shapely.intersects_xy(polygon, x_grid, y_grid),
        dtype=np.bool_,
    )
    if np.all(land_mask):
        return _evaluate_land_samples(
            x_grid, y_grid, boundary, settings, constraints, automatic_valleys,
            regions=regions, world_context=world_context,
        ), land_mask
    elevation = np.zeros(land_mask.shape, dtype=np.float64)
    if np.any(land_mask):
        elevation[land_mask] = _evaluate_land_samples(
            x_grid[land_mask], y_grid[land_mask], boundary, settings, constraints,
            automatic_valleys,
            regions=regions, world_context=world_context,
        )
    return elevation, land_mask


def _evaluate_land_samples(
    x_grid: NDArray[np.float64],
    y_grid: NDArray[np.float64],
    boundary: Any,
    settings: TerrainSettings,
    constraints: tuple[_MetricConstraint, ...],
    automatic_valleys: _AutomaticValleyField,
    regions: tuple[MetricRegion, ...] = (),
    world_context: PreparedWorldContext | None = None,
) -> NDArray[np.float64]:
    """Evaluate independent points after canonical routing and profiles are prepared.

    No operation here may reduce across neighboring samples: callers can omit
    ocean points or split land points into different chunks without changing
    the field. Neighborhood-dependent hydrology remains on its complete grid.
    """

    points: Any = shapely.points(x_grid, y_grid)
    raw_distance_to_coast = cast(Any, shapely.distance(points, boundary))
    distance_to_coast = cast(
        NDArray[np.float64],
        np.asarray(raw_distance_to_coast, dtype=np.float64),
    )
    unconditioned_elevation, macro_elevation, relief_noise = _base_elevation_fields(
        x_grid,
        y_grid,
        distance_to_coast,
        settings,
        regions=regions, world_context=world_context,
    )
    automatic_incision, automatic_detail_suppression = automatic_valleys.sample_shaping(
        x_grid, y_grid,
    )
    residual_detail = unconditioned_elevation - macro_elevation
    automatic_incision = automatic_valleys.floor.refine(
        x_grid, y_grid, automatic_incision, macro_elevation,
        residual_detail * (1. - automatic_detail_suppression),
    )
    if automatic_valleys.basins:
        retained = basin_intent_ids(x_grid, y_grid, automatic_valleys.basins) > 0
        automatic_incision[retained] = 0
        automatic_detail_suppression[retained] = 0
    macro_elevation = np.maximum(macro_elevation - automatic_incision, 0.0)
    unconditioned_elevation = np.maximum(
        macro_elevation + residual_detail * (1.0 - automatic_detail_suppression),
        0.0,
    )
    if constraints:
        conditioned_elevation, constraint_influence = _apply_constraints(
            macro_elevation,
            points,
            distance_to_coast,
            constraints,
            settings.largest_feature_km,
            settings.maximum_elevation_m,
            relief_noise,
        )
        residual_detail = unconditioned_elevation - macro_elevation
        elevation = conditioned_elevation + residual_detail * (1.0 - constraint_influence)
    else:
        elevation = unconditioned_elevation
    return np.clip(elevation, 0.0, settings.maximum_elevation_m)


def _water_sampling_guides(
    constraints: tuple[_MetricConstraint, ...], regions: tuple[MetricRegion, ...],
    settings: TerrainSettings,
) -> tuple[SamplingGuide, ...]:
    features: list[SamplingGuide] = []
    # Global detail also drives structure width even when base variability is zero.
    if settings.variability > 0 or any(c.kind in ("ridge", "valley") for c in constraints):
        features.append(SamplingDensity(
            settings.largest_feature_km / (2 ** settings.detail_levels)))
    for region in regions:
        controls = region.settings
        features.append(SamplingFeature(region.geometry, controls.transition_km,
                                        controls.transition_km))
        if controls.relief_m > 0:
            # Regional recipes always include two macro octaves. Belt stretching
            # lengthens one axis; the unstretched axis keeps this conservative scale.
            features.append(SamplingDensity(
                controls.feature_size_km / (2 ** max(2, settings.detail_levels)),
                region.sampling_support()))
    for constraint in constraints:
        if (constraint.kind == "point" and constraint.attached_to_structure
                and constraint.elevation_mode == "relative"):
            continue
        structure = constraint.kind in ("ridge", "valley")
        attached = constraint.kind == "point" and constraint.attached_to_structure
        radius = constraint.influence_radius_km
        minimum = radius * (STRUCTURE_MIN_TAPER * STRUCTURE_MIN_WIDTH_VARIATION if structure else
                            ATTACHED_POINT_RADIUS_FACTOR if attached else 1.)
        maximum = radius * (STRUCTURE_MIN_WIDTH_VARIATION + .36 if structure else
                            ATTACHED_POINT_RADIUS_FACTOR if attached else 1.)
        radius_factor, feature_factor, _share = _context_factors(
            is_structure=structure, is_brush=constraint.kind == "brush", attached_point=attached)
        context = max(radius_factor * maximum, feature_factor * settings.largest_feature_km)
        features.append(SamplingFeature(constraint.geometry, radius, minimum, context))
        if constraint.explicit_profile:
            # A narrow pass can be much shorter than the line's crosswise width.
            # Keep its longitudinal scale visible to bounded water-review sampling.
            spacing = min(b[0]-a[0] for a, b in pairwise(constraint.profile_anchors)) / 4.
            features.append(SamplingDensity(
                spacing, constraint.geometry.buffer(2*max(radius, context))))
    return tuple(features)


@dataclass(frozen=True, slots=True)
class PreparedTerrainField:
    """One prepared pointwise field shared by raster generation and budget planning."""

    polygon: LandGeometry
    boundary: Any
    width_km: float
    height_km: float
    settings: TerrainSettings
    constraints: tuple[_MetricConstraint, ...]
    regions: tuple[MetricRegion, ...]
    basins: tuple[MetricBasin, ...]
    automatic_valleys: _AutomaticValleyField
    world_context: PreparedWorldContext | None = None

    def evaluate(
        self, x: NDArray[np.float64], y: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
        return _evaluate_elevation_samples(
            x, y, self.polygon, self.boundary, self.settings, self.constraints,
            self.automatic_valleys, regions=self.regions, world_context=self.world_context,
        )

    def sample_ground(
        self, x: NDArray[np.float64], y: NDArray[np.float64],
    ) -> NDArray[np.float32]:
        values, on_land = self.evaluate(x, y)
        return np.where(on_land, values, np.nan).astype(np.float32)


def prepare_terrain_field(
    coastline: Coastline, settings: TerrainSettings, constraints: Sequence[TerrainConstraint],
    progress: ProgressCallback | None, *, world_context: TerrainWorldContext | None = None,
) -> PreparedTerrainField:
    _report(progress, 0.02, "Preparing metric grid")
    polygon, width_km, height_km = _metric_polygon(coastline, settings.object_scale_km)
    if world_context is not None:
        world_context.validate_frame(coastline.bounds, settings.object_scale_km)
    context = None if world_context is None else PreparedWorldContext(world_context)
    authored_constraints = tuple(constraints)
    basins = prepare_basins(
        authored_constraints, width_km, height_km, polygon, settings.maximum_elevation_m,
    )
    regions = prepare_regions(
        tuple(item for item in authored_constraints if isinstance(item, TerrainRegion)),
        width_km, height_km, polygon, settings.maximum_elevation_m,
    )
    metric_constraints = _metric_constraints(
        authored_constraints,
        polygon,
        width_km,
        height_km,
        settings.maximum_elevation_m,
    )
    boundary = polygon.boundary
    _report(progress, 0.04, "Preparing authored valley profiles")
    metric_constraints = _prepare_downstream_valley_profiles(
        metric_constraints, boundary, settings,
        regions=regions, world_context=context, progress=progress,
    )
    _report(progress, 0.06, "Routing drainage over authored terrain")
    automatic_valleys = _prepare_automatic_valley_field(
        polygon, boundary, width_km, height_km, settings, metric_constraints,
        regions=regions, world_context=context, basins=basins, progress=progress,
    )
    _report(progress, 0.08, "Terrain field prepared")

    return PreparedTerrainField(polygon, boundary, width_km, height_km, settings,
                                 metric_constraints, regions, basins, automatic_valleys, context)


def forecast_water_sampling(
    coastline: Coastline, settings: TerrainSettings, *,
    constraints: Sequence[TerrainConstraint] = (),
    world_context: TerrainWorldContext | None = None,
) -> WaterSamplingBudget:
    """Plan shoreline and potential internal-network demand without fine water evaluation."""
    field = prepare_terrain_field(
        coastline, settings, constraints, None, world_context=world_context,
    )
    automatic = field.automatic_valleys
    x, y = np.meshgrid(automatic.x_km, automatic.y_km)
    ground, _mask = field.evaluate(x, y)
    return plan_water_sampling_budget(
        field.basins, ground.astype(np.float32).astype(np.float64),
        automatic.x_km, automatic.y_km,
        _water_sampling_guides(field.constraints, field.regions, settings),
    )


def generate_terrain(
    coastline: Coastline,
    settings: TerrainSettings,
    progress: ProgressCallback | None = None,
    *,
    constraints: Sequence[TerrainConstraint] = (),
    world_context: TerrainWorldContext | None = None,
    cancellation: CancellationToken | None = None,
) -> GeneratedTerrain:
    """Generate a deterministic Float32 elevation grid inside a coastline."""

    check_cancelled(cancellation)
    progress = cancellable_progress(progress, cancellation)
    authored_constraints = tuple(constraints)
    field = prepare_terrain_field(
        coastline, settings, authored_constraints, progress, world_context=world_context,
    )
    polygon, width_km, height_km = field.polygon, field.width_km, field.height_km
    metric_constraints, regions, basins = field.constraints, field.regions, field.basins
    automatic_valleys = field.automatic_valleys
    grid = EndpointGrid.for_extent((0.0, 0.0, width_km, height_km), settings.resolution_px)
    width, height = grid.width, grid.height
    x_km, y_km = grid_coordinates(grid)
    elevation = np.full((height, width), np.nan, dtype=np.float32)
    mask = np.zeros((height, width), dtype=np.bool_)

    _report(progress, 0.08, "Building elevation field")
    chunk_rows = 128
    for start in range(0, height, chunk_rows):
        stop = min(start + chunk_rows, height)
        x_grid, y_grid = np.meshgrid(x_km, y_km[start:stop])
        chunk_elevation, chunk_mask = field.evaluate(x_grid, y_grid)
        chunk_elevation = np.where(chunk_mask, chunk_elevation, np.nan)

        elevation[start:stop] = chunk_elevation.astype(np.float32)
        mask[start:stop] = chunk_mask
        completed = stop / height
        _report(progress, 0.08 + 0.82 * completed, "Building elevation field")

    _report(progress, 0.92, "Checking drainage connectivity")
    routing_x, routing_y = np.meshgrid(automatic_valleys.x_km, automatic_valleys.y_km)
    routing_final, _routing_mask = field.evaluate(routing_x, routing_y)
    # Match the authoritative Float32 field, sampled at canonical routing nodes.
    routing_final = routing_final.astype(np.float32).astype(np.float64)
    review = review_drainage_routing(
        automatic_valleys.drainage, routing_final, automatic_valleys.land_mask,
        x_spacing_km=float(automatic_valleys.x_km[1] - automatic_valleys.x_km[0]),
        y_spacing_km=float(automatic_valleys.y_km[1] - automatic_valleys.y_km[0]),
        region_transition_mask=regional_transition_mask(routing_x, routing_y, regions),
    )

    routing_basin_ids = basin_intent_ids(routing_x, routing_y, basins)
    outlet_heights: list[float | None] = []
    for basin in basins:
        check_cancelled(cancellation)
        if basin.outlet_km is None:
            outlet_heights.append(None)
        else:
            outlet_x, outlet_y = basin.outlet_km
            values = field.sample_ground(np.asarray([outlet_x]), np.asarray([outlet_y]))
            outlet_heights.append(float(values[0]))
    water_features = _water_sampling_guides(metric_constraints, regions, settings)
    _report(progress, 0.93, "Reviewing basin water and outlets")

    def sample_water_ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        check_cancelled(cancellation)
        values = field.sample_ground(x, y)
        check_cancelled(cancellation)
        return values

    water_review, basin_outflow = resolve_basin_outflow(
        basins, routing_basin_ids, routing_final, automatic_valleys.drainage,
        automatic_valleys.land_mask, review.drainage.receivers, review.drainage.boundary_flags,
        automatic_valleys.x_km, automatic_valleys.y_km, polygon, authored_constraints,
        tuple(outlet_heights), sample_water_ground, water_features,
    )
    water = water_products(elevation, x_km, y_km, basins, routing_basin_ids, water_review)

    _report(progress, 0.94, "Validating terrain")
    if not np.any(mask):
        raise ValueError("The coastline does not cover any output pixels.")
    if not np.all(np.isfinite(elevation[mask])):
        raise RuntimeError("Terrain generation produced non-finite land elevations.")
    if np.any(elevation[mask] < 0):
        raise RuntimeError("Terrain generation produced land below sea level.")

    _report(progress, 1.0, "Terrain ready")
    return GeneratedTerrain(
        elevation_m=elevation,
        land_mask=mask,
        x_km=x_km,
        y_km=y_km,
        settings=settings,
        constraints=authored_constraints,
        source_name=coastline.source_name,
        drainage=review.drainage,
        routing_grid_shape=(automatic_valleys.y_km.size, automatic_valleys.x_km.size),
        routing=automatic_valleys.drainage,
        routing_land_mask=automatic_valleys.land_mask,
        routing_final_elevation_m=routing_final,
        routing_agreement=review.agreement,
        routing_conflicts=review.conflicts,
        water=water,
        basin_outflow=basin_outflow,
        world_context=world_context,
    )
