"""Finer dry collection links and cumulative head checks on the chosen paths."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.flat_routing import FlatRouting, route_flats
from map_maker.terrain.pipeline.link_planning import plan_water_links, water_link_candidates
from map_maker.terrain.pipeline.water_sampling import (
    GroundSampler,
    SamplingGuide,
    plan_ground_profile,
    profile_positions,
    sample_ground_positions,
)

MAX_DRY_LINK_SAMPLES = 262_144
HEAD_TOLERANCE_M = .01


@dataclass(frozen=True, slots=True)
class DryLinkEvidence:
    source_flat_index: int
    target_flat_index: int
    sample_count: int
    feature_sample_count: int
    feature_spacing_limit_km: float | None
    maximum_uphill_excursion_m: float
    low_position_km: tuple[float, float]
    crest_position_km: tuple[float, float]
    blocked: bool


@dataclass(frozen=True, slots=True)
class DryPathBarrier:
    source_flat_index: int
    maximum_uphill_excursion_m: float
    low_position_km: tuple[float, float]
    crest_position_km: tuple[float, float]


@dataclass(frozen=True, slots=True)
class DryLinkReview:
    status: Literal["sampled", "budget_exceeded"]
    spacing_limit_km: float
    candidate_link_count: int
    requested_sample_count: int
    blocked_link_count: int | None
    cumulative_uphill_cell_count: int | None
    links: tuple[DryLinkEvidence, ...]
    path_barriers: tuple[DryPathBarrier, ...]


@dataclass(frozen=True, slots=True)
class DryCollectionRouting:
    routing: FlatRouting
    path_uphill_m: NDArray[np.float64]
    review: DryLinkReview


def _uphill(heights: NDArray[np.float64]) -> tuple[float, int, int]:
    rise = heights - np.minimum.accumulate(heights)
    crest = int(np.argmax(rise))
    low = int(np.argmin(heights[:crest + 1]))
    return float(rise[crest]), low, crest


def _position(positions: NDArray[np.float64], index: int) -> tuple[float, float]:
    return float(positions[index, 0]), float(positions[index, 1])


def route_dry_links(
    nodes: NDArray[np.int64], neighbours: NDArray[np.int64], wet: NDArray[np.bool_],
    elevation_m: NDArray[np.float64], x_km: NDArray[np.float64],
    y_km: NDArray[np.float64], water_level_m: float, sample_ground: GroundSampler,
    features: tuple[SamplingGuide, ...] = (),
) -> DryCollectionRouting:
    """Screen all potential descents/flats, then review complete chosen paths.

    Unequal-head links are checked downhill; exact dry flats must pass in both
    directions to retain a symmetric flat graph. Links ending at wet terminals
    use max(ground, water level), so submerged bed rises do not invent barriers.
    All other dry profiles use ground. Excessive plans retain every dry donor
    without evaluating or accepting a partial network; reviewed wet flow survives.
    """
    count = nodes.size
    if neighbours.shape != (count, 8) or wet.shape != (count,):
        raise ValueError("Dry-link review needs matching node and edge arrays.")
    head = np.where(wet, water_level_m, elevation_m.ravel()[nodes])
    dx, dy = float(x_km[1] - x_km[0]), float(y_km[1] - y_km[0])
    candidates = water_link_candidates(nodes, neighbours, wet, elevation_m, x_km, y_km,
                                        water_level_m, kind="dry")
    sources, targets, directions = candidates.sources, candidates.targets, candidates.directions
    spacing = candidates.spacing_km
    width = elevation_m.shape[1]
    coordinates = np.column_stack((x_km[nodes % width], y_km[nodes // width]))
    planned = plan_water_links(candidates, features, sample_budget=MAX_DRY_LINK_SAMPLES,
                               planner=plan_ground_profile)
    requested = planned.requested_sample_count
    if planned.status != "sampled":
        return DryCollectionRouting(
            FlatRouting(np.full(count, -1, dtype=np.int64), np.zeros(count, dtype=np.uint32)),
            np.zeros(count, dtype=np.float64),
            DryLinkReview("budget_exceeded", spacing, len(sources), requested, None, None, (), ()))
    plans = planned.plans
    offsets = np.concatenate((np.zeros(1, dtype=np.int64), np.cumsum(
        np.asarray([p.requested_sample_count for p in plans], dtype=np.int64))))
    positions = (np.concatenate([profile_positions(p) for p in plans]) if plans else
                 np.empty((0, 2), dtype=np.float64))
    ground = sample_ground_positions(positions, sample_ground)
    graph = neighbours.copy()
    link_ids = np.full(neighbours.shape, -1, dtype=np.int64)
    evidence: list[DryLinkEvidence] = []
    for i, (source, target, direction, plan) in enumerate(
        zip(sources, targets, directions, plans, strict=True)
    ):
        start, end = int(offsets[i]), int(offsets[i + 1])
        raw = ground[start:end]
        canonical = elevation_m.ravel()[nodes[[source, target]]].astype(np.float32)
        if not np.array_equal(raw[[0, -1]], canonical):
            raise ValueError("Dry-link samples must match canonical Float32 ground.")
        heights = raw.astype(np.float64)
        if wet[target]:
            heights = np.maximum(heights, water_level_m)
        uphill, low, crest = _uphill(heights)
        if not wet[target] and head[source] == head[target]:
            backward, back_low, back_crest = _uphill(heights[::-1])
            if backward > uphill:
                uphill, low, crest = backward, len(raw)-1-back_low, len(raw)-1-back_crest
        blocked = uphill > HEAD_TOLERANCE_M
        if blocked:
            graph[source, direction] = graph[target, 7-int(direction)] = -1
        link_ids[source, direction] = link_ids[target, 7-int(direction)] = i
        evidence.append(DryLinkEvidence(int(nodes[source]), int(nodes[target]), len(raw),
            len(raw) - plan.baseline_sample_count, plan.feature_spacing_limit_km,
            uphill, _position(positions, start+low), _position(positions, start+crest), blocked))
    routing = route_flats(head, graph, wet, x_spacing_km=dx, y_spacing_km=dy)
    # Compose profile summaries in reverse flow order. A link's minimum can be
    # followed by a crest several links later, even when each link passes alone.
    path_uphill = np.zeros(count, dtype=np.float64)
    path_maximum = head.copy()
    maximum_position, low_position, crest_position = (coordinates.copy() for _ in range(3))
    for node in np.lexsort((nodes, routing.flat_rank, head)):
        target = int(routing.receivers[node])
        if target < 0:
            continue
        direction = int(np.flatnonzero(graph[node] == target)[0])
        link = int(link_ids[node, direction])
        if link < 0:
            raise RuntimeError("Every selected dry link must have a sampled profile.")
        start, end = int(offsets[link]), int(offsets[link + 1])
        heights, points = ground[start:end].astype(np.float64), positions[start:end]
        if node != sources[link]:
            heights, points = heights[::-1], points[::-1]
        if wet[target]:
            heights = np.maximum(heights, water_level_m)
        uphill, low, crest = _uphill(heights)
        path_uphill[node] = uphill
        low_position[node], crest_position[node] = points[low], points[crest]
        minimum = int(np.argmin(heights))
        cross = path_maximum[target] - heights[minimum]
        if cross > path_uphill[node]:
            path_uphill[node] = cross
            low_position[node], crest_position[node] = points[minimum], maximum_position[target]
        if path_uphill[target] > path_uphill[node]:
            path_uphill[node] = path_uphill[target]
            low_position[node], crest_position[node] = low_position[target], crest_position[target]
        maximum = int(np.argmax(heights))
        if heights[maximum] >= path_maximum[target]:
            path_maximum[node], maximum_position[node] = heights[maximum], points[maximum]
        else:
            path_maximum[node] = path_maximum[target]
            maximum_position[node] = maximum_position[target]
    excessive = path_uphill > HEAD_TOLERANCE_M
    origins = excessive & ~excessive[np.maximum(routing.receivers, 0)] & (routing.receivers >= 0)
    barriers = tuple(DryPathBarrier(int(nodes[n]), float(path_uphill[n]),
        _position(low_position, int(n)), _position(crest_position, int(n)))
        for n in np.flatnonzero(origins))
    return DryCollectionRouting(routing, path_uphill,
        DryLinkReview("sampled", spacing, len(sources), requested,
            sum(e.blocked for e in evidence), int(np.count_nonzero(excessive)),
            tuple(evidence), barriers))
