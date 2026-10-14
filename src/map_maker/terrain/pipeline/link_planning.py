"""Shared candidate geometry and bounded sample planning for internal water review."""

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, hypot
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray
from shapely import covers, linestrings

from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS
from map_maker.terrain.pipeline.water_sampling import (
    GroundSamplingPlan,
    SamplingGuide,
)

if TYPE_CHECKING:
    from map_maker.terrain.pipeline.water import MetricBasin

type ProfileVertices = tuple[tuple[float, float], ...]
type ProfilePlanner = Callable[
    [ProfileVertices, float, tuple[SamplingGuide, ...]], GroundSamplingPlan]


@dataclass(frozen=True, slots=True)
class LinkCandidates:
    sources: NDArray[np.int64]
    targets: NDArray[np.int64]
    directions: NDArray[np.int64]
    vertices_km: tuple[ProfileVertices, ...]
    spacing_km: float


@dataclass(frozen=True, slots=True)
class LinkSamplingPlan:
    status: Literal["sampled", "budget_exceeded"]
    baseline_sample_count: int
    requested_sample_count: int
    planned_link_count: int
    limiting_budget: Literal["network", "profile"] | None
    plans: tuple[GroundSamplingPlan, ...]


def basin_neighbours(
    basin: MetricBasin, inside: NDArray[np.bool_],
    x_km: NDArray[np.float64], y_km: NDArray[np.float64],
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Build each undirected vector-contained link once, in bulk."""
    nodes = np.flatnonzero(inside).astype(np.int64)
    height, width = inside.shape
    rows, columns = nodes // width, nodes % width
    local = np.full(inside.size, -1, dtype=np.int64)
    local[nodes] = np.arange(nodes.size, dtype=np.int64)
    neighbours = np.full((nodes.size, 8), -1, dtype=np.int64)
    for direction, (dr, dc) in enumerate(D8_NEIGHBOURS):
        if dr < 0 or (dr == 0 and dc < 0):
            continue
        target_rows, target_columns = rows + dr, columns + dc
        valid = ((target_rows >= 0) & (target_rows < height)
                 & (target_columns >= 0) & (target_columns < width))
        sources = np.flatnonzero(valid)
        targets = local[target_rows[valid] * width + target_columns[valid]]
        present = targets >= 0
        sources, targets = sources[present], targets[present]
        if not sources.size:
            continue
        first = np.column_stack((x_km[columns[sources]], y_km[rows[sources]]))
        second = np.column_stack((x_km[columns[targets]], y_km[rows[targets]]))
        segments = linestrings(np.stack((first, second), axis=1))
        allowed = np.asarray(covers(basin.geometry, segments), dtype=np.bool_)
        sources, targets = sources[allowed], targets[allowed]
        neighbours[sources, direction] = targets
        neighbours[targets, 7 - direction] = sources
    return nodes, neighbours


def water_link_candidates(
    nodes: NDArray[np.int64], neighbours: NDArray[np.int64], wet: NDArray[np.bool_],
    elevation_m: NDArray[np.float64], x_km: NDArray[np.float64],
    y_km: NDArray[np.float64], water_level_m: float, *, kind: Literal["wet", "dry"],
) -> LinkCandidates:
    """Choose the same wet links or eligible dry descents/flats for review and forecasting."""
    count = nodes.size
    if neighbours.shape != (count, 8) or wet.shape != (count,):
        raise ValueError("Water-link planning needs matching node and edge arrays.")
    unique = neighbours > np.arange(count)[:, None]
    both_wet = wet[:, None] & wet[np.maximum(neighbours, 0)]
    sources, directions = np.nonzero(unique & (both_wet if kind == "wet" else ~both_wet))
    targets = neighbours[sources, directions]
    if kind == "dry":
        head = np.where(wet, water_level_m, elevation_m.ravel()[nodes])
        reverse = (head[targets] > head[sources]) | wet[sources]
        sources, targets = np.where(reverse, targets, sources), np.where(reverse, sources, targets)
        directions = np.where(reverse, 7 - directions, directions)
        possible = ~wet[sources] & (head[sources] >= head[targets])
        sources, targets, directions = sources[possible], targets[possible], directions[possible]
    width = elevation_m.shape[1]
    coordinates = np.column_stack((x_km[nodes % width], y_km[nodes // width]))
    vertices = tuple(((float(coordinates[a, 0]), float(coordinates[a, 1])),
                      (float(coordinates[b, 0]), float(coordinates[b, 1])))
                     for a, b in zip(sources, targets, strict=True))
    spacing = min(float(x_km[1] - x_km[0]), float(y_km[1] - y_km[0])) / 4
    return LinkCandidates(sources.astype(np.int64), targets.astype(np.int64),
                          directions.astype(np.int64), vertices, spacing)


def plan_water_links(
    candidates: LinkCandidates, features: tuple[SamplingGuide, ...], *,
    sample_budget: int, planner: ProfilePlanner,
) -> LinkSamplingPlan:
    """Count a complete network before evaluation; failed totals remain lower bounds."""
    baseline = tuple(1 + max(2, ceil(hypot(b[0]-a[0], b[1]-a[1]) / candidates.spacing_km))
                     for a, b in candidates.vertices_km)
    baseline_count = requested = sum(baseline)
    if requested > sample_budget:
        return LinkSamplingPlan("budget_exceeded", baseline_count, requested, 0, "network", ())
    plans: list[GroundSamplingPlan] = []
    for index, (pair, base) in enumerate(zip(candidates.vertices_km, baseline, strict=True), 1):
        plan = planner(pair, candidates.spacing_km, features)
        requested += plan.requested_sample_count - base
        if plan.status != "sampled" or requested > sample_budget:
            limit = "profile" if plan.status != "sampled" else "network"
            return LinkSamplingPlan("budget_exceeded", baseline_count, requested, index, limit, ())
        plans.append(plan)
    return LinkSamplingPlan("sampled", baseline_count, requested, len(plans), None, tuple(plans))
