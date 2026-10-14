"""Bounded finished-ground evidence between canonical water-review nodes."""

from collections.abc import Callable
from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import pairwise
from math import ceil, hypot, inf, isfinite, nextafter
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

if TYPE_CHECKING:
    from map_maker.terrain.pipeline.water import MetricBasin

type GroundSampler = Callable[[NDArray[np.float64], NDArray[np.float64]], NDArray[np.float32]]

WATER_SAMPLING_ALGORITHM_ID = "feature-guided-float32-water-checks@4"
MAX_PROFILE_SAMPLES = 65_536
SAMPLE_BATCH_SIZE = 4_096
FEATURE_RADIUS_DIVISOR = 4


type SamplingBounds = tuple[float, float, float, float]


def _expanded_bounds(geometry: BaseGeometry, radius_km: float = 0.) -> SamplingBounds:
    left, bottom, right, top = geometry.bounds
    # Round outward both before expansion and after subtraction/addition. Bounds
    # reject only impossible candidates; grazing contacts still reach GEOS.
    padding = nextafter(radius_km, inf) if radius_km else 0.
    return (nextafter(left - padding, -inf), nextafter(bottom - padding, -inf),
            nextafter(right + padding, inf), nextafter(top + padding, inf))


def _bounds_overlap(first: SamplingBounds, second: SamplingBounds) -> bool:
    return not (first[2] < second[0] or second[2] < first[0]
                or first[3] < second[1] or second[3] < first[1])


@dataclass(frozen=True, slots=True)
class SamplingFeature:
    """Prepared cores or regional boundaries with physical transition distances."""

    geometry: Point | LineString | Polygon
    influence_radius_km: float
    minimum_radius_km: float
    context_radius_km: float | None = None
    parts: tuple[Point | LineString, ...] = field(init=False, repr=False, compare=False)
    bounds_km: SamplingBounds = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (self.geometry.is_empty or not self.geometry.is_valid
                or not 0 < self.minimum_radius_km <= self.influence_radius_km
                or not isfinite(self.influence_radius_km)):
            raise ValueError("Water sampling features require finite geometry and positive radii.")
        if self.context_radius_km is not None and (
                isinstance(self.geometry, Polygon) or not isfinite(self.context_radius_km)
                or self.context_radius_km <= 0):
            raise ValueError("Context guidance requires a positive radius and point/line geometry.")
        # Every link sees the same canonical parts. Keep preparation local to the
        # immutable feature so edited/replaced geometry cannot reuse stale parts.
        normalized = self.geometry.normalize()
        rings = ((normalized.exterior, *normalized.interiors)
                 if isinstance(normalized, Polygon) else (normalized,))
        parts = ((normalized,) if isinstance(normalized, Point) else
                 tuple(LineString((a, b)) for ring in rings
                       for a, b in pairwise(ring.coords) if a != b))
        if not all(isfinite(v) for part in parts for point in part.coords for v in point):
            raise ValueError("Water sampling features require finite geometry and positive radii.")
        object.__setattr__(self, "geometry", normalized)
        object.__setattr__(self, "parts", parts)
        # Include polygon interiors, core corridors and the broadest context
        # shoulder. This bounds sampling guidance, not the field's Gaussian tail.
        object.__setattr__(self, "bounds_km", _expanded_bounds(
            normalized, 2 * max(self.influence_radius_km, self.context_radius_km or 0.)))


@dataclass(frozen=True, slots=True)
class SamplingDensity:
    """Physical spacing for an active procedural field; None geometry is global."""

    spacing_km: float
    geometry: Polygon | MultiPolygon | None = None
    bounds_km: SamplingBounds | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isfinite(self.spacing_km) or self.spacing_km <= 0:
            raise ValueError("Procedural sampling spacing must be finite and positive.")
        if self.geometry is not None:
            if self.geometry.is_empty or not self.geometry.is_valid:
                raise ValueError("Procedural sampling regions require valid nonempty geometry.")
            object.__setattr__(self, "geometry", self.geometry.normalize())
        object.__setattr__(self, "bounds_km",
                           None if self.geometry is None else _expanded_bounds(self.geometry))


type SamplingGuide = SamplingFeature | SamplingDensity


@dataclass(frozen=True, slots=True)
class _FeatureWindow:
    start: float
    end: float
    spacing_km: float
    anchors: tuple[float, ...]


def _feature_windows(
    segment: LineString, features: tuple[SamplingGuide, ...], spacing_km: float,
) -> list[_FeatureWindow]:
    """Clip conservative core corridors; split polylines to retain every crossing.

    Square end caps contain the round influence corridor. Their extra corner
    area can add probes, but cannot omit a nearby core through polygonal circle
    approximation. The corridor is a sampling choice, not a hydraulic boundary.
    """
    windows: list[_FeatureWindow] = []
    segment_bounds = segment.bounds
    for feature in features:
        if feature.bounds_km is not None and not _bounds_overlap(segment_bounds, feature.bounds_km):
            continue
        if isinstance(feature, SamplingDensity):
            if feature.spacing_km < spacing_km:
                intervals = ((0., 1.),) if feature.geometry is None else (
                    _contained_intervals(segment, feature.geometry))
                windows.extend(_FeatureWindow(start, end, feature.spacing_km, ())
                               for start, end in intervals)
            continue
        if feature.context_radius_km is not None:
            windows.extend(_context_windows(segment, feature, spacing_km))
        step = feature.minimum_radius_km / FEATURE_RADIUS_DIVISOR
        regional = isinstance(feature.geometry, Polygon)
        if step >= spacing_km:
            if not regional:
                continue
            # A broad transition can only add spacing inside a short contained
            # interval. Skip proven full-length/disjoint cases before building
            # boundary corridors, preserving the complete interval policy below.
            if (segment.length / FEATURE_RADIUS_DIVISOR >= spacing_km
                    and feature.geometry.covers(segment)) or feature.geometry.disjoint(segment):
                continue
        step = min(step, spacing_km)
        boundary_windows = _corridor_windows(
            segment, feature.parts, 2 * feature.influence_radius_km, step)
        if step < spacing_km:
            windows.extend(boundary_windows)
        if regional and boundary_windows:
            # A thin crossed region may never reach its nominal transition depth.
            # Refine its contained spans locally; vertex clearance is not width.
            for start, end in _contained_intervals(segment, cast(Polygon, feature.geometry)):
                local_step = min(step, (end - start) * segment.length / FEATURE_RADIUS_DIVISOR)
                if local_step >= spacing_km:
                    continue
                midpoint = (start + end) / 2
                for window in boundary_windows:
                    low, high = max(start, window.start), min(end, window.end)
                    if low < high:
                        anchors = (midpoint,) if low <= midpoint <= high else ()
                        windows.append(_FeatureWindow(low, high, local_step, anchors))
    return windows


def _corridor_windows(
    segment: LineString, parts: tuple[Point | LineString, ...], radius: float, step: float,
) -> list[_FeatureWindow]:
    windows: list[_FeatureWindow] = []
    for part in parts:
        if segment.distance(part) > radius:
            continue
        corridor = (box(part.x - radius, part.y - radius, part.x + radius, part.y + radius)
                    if isinstance(part, Point) else part.buffer(radius, cap_style="square"))
        intersection = segment.intersection(corridor)
        if intersection.is_empty:
            continue
        if not isinstance(intersection, (Point, LineString)):
            raise ValueError("Water sampling requires a single convex feature corridor.")
        bounds = tuple(float(segment.project(Point(p), normalized=True))
                       for p in intersection.coords)
        start, end = min(bounds), max(bounds)
        closest = float(segment.project(nearest_points(segment, part)[0], normalized=True))
        projected = (float(segment.project(Point(p), normalized=True)) for p in part.coords)
        anchors = tuple(t for t in (closest, *projected) if start <= t <= end)
        windows.append(_FeatureWindow(start, end, step, anchors))
    return windows


def _context_windows(
    segment: LineString, feature: SamplingFeature, spacing_km: float,
) -> list[_FeatureWindow]:
    radius = feature.context_radius_km
    assert radius is not None
    step = radius / FEATURE_RADIUS_DIVISOR
    if step < spacing_km:
        return _corridor_windows(segment, feature.parts, 2 * radius, step)
    # Broad shoulders already fit the baseline spacing. Anchor the closest
    # approach to the complete geometry without buffering/splitting every part.
    # Narrow corridors above still retain every crossing. Neither policy bounds
    # the extrema of interacting or longitudinally varying features.
    if segment.distance(feature.geometry) > 2 * radius:
        return []
    closest = float(segment.project(nearest_points(segment, feature.geometry)[0], normalized=True))
    return ([_FeatureWindow(closest, closest, spacing_km, (closest,))]
            if 0 < closest < 1 else [])


def _contained_intervals(
    segment: LineString, geometry: Polygon | MultiPolygon,
) -> tuple[tuple[float, float], ...]:
    # Strict interior avoids clipping unchanged links. Merely covered paths
    # can touch re-entrant/hole corners and require those split-interval anchors.
    if geometry.contains_properly(segment):
        return ((0., 1.),)
    if geometry.disjoint(segment):
        return ()
    intervals: list[tuple[float, float]] = []
    for piece in _linear_parts(segment.intersection(geometry)):
        bounds = tuple(float(segment.project(Point(p), normalized=True)) for p in piece.coords)
        start, end = min(bounds), max(bounds)
        if start < end:
            intervals.append((start, end))
    return tuple(intervals)


def _linear_parts(geometry: BaseGeometry) -> tuple[LineString, ...]:
    if isinstance(geometry, LineString):
        return () if geometry.is_empty else (geometry,)
    if isinstance(geometry, MultiLineString):
        return tuple(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        collection = cast("GeometryCollection[BaseGeometry]", geometry)
        return tuple(part for item in collection.geoms for part in _linear_parts(item))
    return ()


def _refined_spans(
    steps: int, length_km: float, windows: list[_FeatureWindow], spacing_km: float,
) -> list[tuple[float, float, int]]:
    """Merge overlapping corridors before counting samples; preserve baseline stations."""
    knots = {i / steps for i in range(steps + 1)}
    for window in windows:
        knots.update((window.start, window.end, *window.anchors))
    pending = sorted(windows, key=lambda window: (window.start, window.end, window.spacing_km))
    active: list[tuple[float, float]] = []
    index = 0
    spans: list[tuple[float, float, int]] = []
    for start, end in pairwise(sorted(knots)):
        while index < len(pending) and pending[index].start <= start:
            window = pending[index]
            heappush(active, (window.spacing_km, window.end))
            index += 1
        while active and active[0][1] <= start:
            heappop(active)
        step = active[0][0] if active else spacing_km
        # Keep round-off at a nominal spacing from doubling a baseline interval.
        count = max(1, ceil((end - start) * length_km / step - 1e-12))
        spans.append((start, end, count))
    return spans


@dataclass(frozen=True, slots=True)
class GroundProfile:
    status: Literal["sampled", "budget_exceeded"]
    spacing_limit_km: float
    requested_sample_count: int
    feature_sample_count: int | None
    feature_spacing_limit_km: float | None
    positions_km: tuple[tuple[float, float], ...]
    ground_m: tuple[float, ...]
    minimum_ground_m: float | None
    maximum_ground_m: float | None
    maximum_position_km: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class GroundSamplingPlan:
    vertices_km: tuple[tuple[float, float], ...]
    spacing_limit_km: float
    baseline_sample_count: int
    requested_sample_count: int
    feature_spacing_limit_km: float | None
    spans: tuple[tuple[tuple[float, float, int], ...], ...]
    status: Literal["sampled", "budget_exceeded"]


def plan_ground_profile(
    vertices_km: tuple[tuple[float, float], ...], spacing_limit_km: float,
    features: tuple[SamplingGuide, ...] = (),
) -> GroundSamplingPlan:
    """Include every vertex and bounded intervening samples; never silently coarsen.

    A closed polyline repeats its first point at the end. Duplicate consecutive
    vertices add no samples. Failed budgets retain the requested count but no
    partial evidence, so callers cannot mistake an inspected prefix for clearance.
    """
    if (not vertices_km or not isfinite(spacing_limit_km) or spacing_limit_km <= 0
            or not all(isfinite(v) for point in vertices_km for v in point)):
        raise ValueError("Water sampling requires finite vertices and positive spacing.")
    lengths = tuple(hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(vertices_km))
    spans = tuple(max(2, ceil(length / spacing_limit_km)) if length else 0 for length in lengths)
    baseline_count = 1 + sum(spans)
    if baseline_count > MAX_PROFILE_SAMPLES:
        return GroundSamplingPlan(vertices_km, spacing_limit_km, baseline_count,
                                  baseline_count, None, (), "budget_exceeded")
    plans: list[list[tuple[float, float, int]]] = []
    feature_spacing: float | None = None
    for (a, b), steps, length in zip(pairwise(vertices_km), spans, lengths, strict=True):
        if not steps:
            plans.append([])
            continue
        windows = _feature_windows(LineString((a, b)), features, spacing_limit_km)
        if windows:
            minimum = min(window.spacing_km for window in windows)
            feature_spacing = minimum if feature_spacing is None else min(feature_spacing, minimum)
        plans.append(_refined_spans(steps, length, windows, spacing_limit_km) if windows else
                     [(0., 1., steps)])
    count = 1 + sum(steps for plan in plans for _, _, steps in plan)
    if count > MAX_PROFILE_SAMPLES:
        return GroundSamplingPlan(vertices_km, spacing_limit_km, baseline_count, count,
                                  feature_spacing, (), "budget_exceeded")
    return GroundSamplingPlan(vertices_km, spacing_limit_km, baseline_count, count,
                              feature_spacing, tuple(tuple(p) for p in plans), "sampled")


def profile_positions(plan: GroundSamplingPlan) -> NDArray[np.float64]:
    """Allocate stations only after the caller has accepted the complete budget."""
    if plan.status != "sampled":
        raise ValueError("Unresolved profiles have no sample positions.")
    vertices_km, plans = plan.vertices_km, plan.spans
    count = plan.requested_sample_count
    positions = np.empty((count, 2), dtype=np.float64)
    positions[0] = vertices_km[0]
    offset = 1
    for (a, b), segment_plan in zip(pairwise(vertices_km), plans, strict=True):
        # Generate each segment as one vectorized block, including every original station.
        fractions = [np.asarray([end]) if steps == 1 else
                     start + (end - start) * np.arange(1, steps + 1, dtype=np.float64) / steps
                     for start, end, steps in segment_plan]
        if not fractions:
            continue
        for fraction, (_, end, _) in zip(fractions, segment_plan, strict=True):
            fraction[-1] = end
        combined = np.concatenate(fractions)
        positions[offset:offset + combined.size] = (np.asarray(a) + combined[:, None]
                                                   * (np.asarray(b) - a))
        positions[offset + combined.size - 1] = b
        offset += combined.size
    return positions


def sample_ground_positions(
    positions: NDArray[np.float64], sample_ground: GroundSampler,
) -> NDArray[np.float32]:
    """Evaluate a pointwise field once per exact position within this call.

    Requested stations and budget counts are unchanged. Compare coordinate bytes
    so signed zero and neighbouring Float64 positions are never merged; restore
    every occurrence in its original order. No cache survives this evaluation.
    """
    keys = np.ascontiguousarray(positions).view(np.dtype((np.void, 16))).ravel()
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    repeated = len(first) < len(positions)
    if repeated:
        positions = positions[first]
    count = len(positions)
    ground = np.empty(count, dtype=np.float32)
    for start in range(0, count, SAMPLE_BATCH_SIZE):
        part = positions[start:start + SAMPLE_BATCH_SIZE]
        values = sample_ground(part[:, 0], part[:, 1])
        if values.shape != (len(part),) or not np.all(np.isfinite(values)):
            raise ValueError("Water sampling requires finite ground at every requested point.")
        ground[start:start + len(part)] = values
    if not np.all(np.isfinite(ground)):
        raise ValueError("Water sampling requires finite Float32 ground.")
    return ground[inverse] if repeated else ground


def sample_ground_profile(
    vertices_km: tuple[tuple[float, float], ...], spacing_limit_km: float,
    sample_ground: GroundSampler, features: tuple[SamplingGuide, ...] = (),
) -> GroundProfile:
    """Evaluate a complete planned profile; excessive budgets retain no prefix."""
    plan = plan_ground_profile(vertices_km, spacing_limit_km, features)
    count = plan.requested_sample_count
    if plan.status != "sampled":
        return GroundProfile("budget_exceeded", spacing_limit_km, count,
                             None, plan.feature_spacing_limit_km, (), (), None, None, None)
    positions = profile_positions(plan)
    ground = sample_ground_positions(positions, sample_ground)
    maximum = int(np.argmax(ground))
    return GroundProfile(
        "sampled", spacing_limit_km, count, count - plan.baseline_sample_count,
        plan.feature_spacing_limit_km,
        tuple((float(x), float(y)) for x, y in positions), tuple(float(v) for v in ground),
        float(np.min(ground)), float(ground[maximum]),
        (float(positions[maximum, 0]), float(positions[maximum, 1])))


@dataclass(frozen=True, slots=True)
class ShorelineReview:
    profile: GroundProfile
    opening_radius_km: float
    low_sample_count: int
    uncontrolled_low_sample_count: int
    uncontrolled_low_sample_indices: tuple[int, ...]


def shoreline_vertices(basin: MetricBasin) -> tuple[tuple[float, float], ...]:
    """Canonical ring orientation/start keep review and forecast stations identical."""
    normalized = cast(Polygon, basin.geometry.normalize())
    return tuple((float(x), float(y)) for x, y in normalized.exterior.coords)


def review_shorelines(
    basins: tuple[MetricBasin, ...], spacing_limit_km: float, opening_radius_km: float,
    sample_ground: GroundSampler, features: tuple[SamplingGuide, ...] = (),
) -> tuple[ShorelineReview | None, ...]:
    """Review lake polygon boundaries, including low ground missed by coarse wet nodes."""
    reviews: list[ShorelineReview | None] = []
    for basin in basins:
        level = basin.source.water_level_m
        if level is None:
            reviews.append(None)
            continue
        profile = sample_ground_profile(
            shoreline_vertices(basin), spacing_limit_km, sample_ground, features)
        low = np.asarray(profile.ground_m, dtype=np.float64) < level - .01
        allowed = np.zeros(low.size, dtype=np.bool_)
        radius = 0. if basin.outlet_km is None else opening_radius_km
        if basin.outlet_km is not None and low.size:
            points = np.asarray(profile.positions_km)
            # Round-off at the declared radius must not turn an endpoint into a new opening.
            allowed = np.hypot(points[:, 0] - basin.outlet_km[0],
                               points[:, 1] - basin.outlet_km[1]) <= radius + 1e-9 * radius
        uncontrolled = tuple(int(index) for index in np.flatnonzero(low & ~allowed))
        reviews.append(ShorelineReview(profile, radius, int(np.count_nonzero(low)),
                                       len(uncontrolled), uncontrolled))
    return tuple(reviews)
