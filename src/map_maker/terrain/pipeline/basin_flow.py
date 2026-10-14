"""Conservative transfer of captured contributing area through authored lake outlets."""

from dataclasses import dataclass, replace
from enum import IntEnum
from math import hypot

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import MultiPolygon, Polygon

from map_maker.terrain.domain import TerrainConstraint
from map_maker.terrain.pipeline.dry_links import HEAD_TOLERANCE_M, DryLinkReview, route_dry_links
from map_maker.terrain.pipeline.flat_routing import (
    FLAT_ROUTING_ALGORITHM_ID,
    FlatRouting,
)
from map_maker.terrain.pipeline.hydrology import DrainageIncision
from map_maker.terrain.pipeline.link_planning import basin_neighbours
from map_maker.terrain.pipeline.outlets import review_outlet_routes
from map_maker.terrain.pipeline.water import (
    MetricBasin,
    WaterReview,
    low_boundary_cells,
    review_water,
)
from map_maker.terrain.pipeline.water_sampling import (
    GroundSampler,
    SamplingGuide,
    review_shorelines,
)
from map_maker.terrain.pipeline.wet_links import WetLinkReview, review_wet_links


class BasinCatchmentClass(IntEnum):
    """Canonical footprint-node outcome, not an upstream watershed delineation."""

    OUTSIDE = 0
    RETAINED = 1
    COLLECTED_WATER = 2
    COLLECTED_DRY = 3


@dataclass(frozen=True, slots=True)
class BasinOutflowSummary:
    algorithm_id: str
    flat_routing_algorithm_id: str
    connected_outlet_count: int
    source_area_km2: float
    retained_area_km2: float
    direct_boundary_area_km2: float
    outlet_boundary_area_km2: float
    area_balance_error_km2: float


@dataclass(frozen=True, slots=True)
class BasinOutflow:
    internal_receivers: NDArray[np.int64]
    flat_rank: NDArray[np.uint32]
    internal_path_uphill_m: NDArray[np.float64]
    catchment_class: NDArray[np.uint8]
    retained_km2: NDArray[np.float64]
    source_km2: NDArray[np.float64]
    throughput_km2: NDArray[np.float64]
    terminal_km2: NDArray[np.float64]
    summary: BasinOutflowSummary



@dataclass(frozen=True, slots=True)
class _BasinCollection:
    nodes: NDArray[np.int64]
    connected: NDArray[np.bool_]
    routing: FlatRouting | None
    wet_links: WetLinkReview
    dry_links: DryLinkReview | None
    path_uphill_m: NDArray[np.float64]


def _collect_basin(
    basin: MetricBasin, inside: NDArray[np.bool_], wet: NDArray[np.bool_], contact: int,
    elevation_m: NDArray[np.float64], x_km: NDArray[np.float64], y_km: NDArray[np.float64],
    sample_ground: GroundSampler, features: tuple[SamplingGuide, ...],
) -> _BasinCollection:
    nodes, neighbours = basin_neighbours(basin, inside, x_km, y_km)
    local_wet = wet.ravel()[nodes]
    assert basin.source.water_level_m is not None
    wet_links, connected = review_wet_links(nodes, neighbours, local_wet, contact,
        elevation_m, x_km, y_km, basin.source.water_level_m, sample_ground, features)
    if wet_links.status != "sampled" or np.any(local_wet & ~connected):
        return _BasinCollection(nodes, connected, None, wet_links, None,
                                np.zeros(nodes.size, dtype=np.float64))
    head = np.where(local_wet, basin.source.water_level_m, elevation_m.ravel()[nodes])
    dry = route_dry_links(nodes, neighbours, local_wet, elevation_m, x_km, y_km,
                          basin.source.water_level_m, sample_ground, features)
    routing = dry.routing
    # Real drops sort by height; equal-head steps sort by their decreasing integer rank.
    order = np.lexsort((nodes, routing.flat_rank, head))
    for node in order:
        target = int(routing.receivers[node])
        if target >= 0:
            connected[node] = connected[target] and dry.path_uphill_m[node] <= HEAD_TOLERANCE_M
    return _BasinCollection(nodes, connected, routing, wet_links, dry.review, dry.path_uphill_m)


def resolve_basin_outflow(
    basins: tuple[MetricBasin, ...], intent_ids: NDArray[np.uint32],
    elevation_m: NDArray[np.float64], routing: DrainageIncision, land_mask: NDArray[np.bool_],
    final_receivers: NDArray[np.int64], boundary_flags: NDArray[np.uint8],
    x_km: NDArray[np.float64], y_km: NDArray[np.float64], land: Polygon | MultiPolygon,
    constraints: tuple[TerrainConstraint, ...], outlet_heights: tuple[float | None, ...],
    sample_ground: GroundSampler, features: tuple[SamplingGuide, ...] = (),
) -> tuple[WaterReview, BasinOutflow]:
    """Review current ground, connect eligible outlets, and account for every source once.

    The original MFD graph captures incoming area at footprint nodes. This
    post-terrain layer transfers the eligible portion along reviewed D8 paths;
    it neither adds local rainfall again nor feeds unvalidated cuts into ground.
    Paths must avoid every basin, so no connection can feed its own source.
    """
    routes = review_outlet_routes(basins, intent_ids, elevation_m, land_mask,
                                  final_receivers, boundary_flags, x_km, y_km, land,
                                  outlet_heights, sample_ground, features)
    dx, dy = float(x_km[1] - x_km[0]), float(y_km[1] - y_km[0])
    shorelines = review_shorelines(basins, min(dx, dy) / 4, hypot(dx, dy), sample_ground, features)
    review = review_water(
        basins, intent_ids, elevation_m, routing, constraints, outlet_heights, routes, shorelines)
    catchment_class = np.where(intent_ids > 0, BasinCatchmentClass.RETAINED,
                                BasinCatchmentClass.OUTSIDE).astype(np.uint8)
    retained = np.where((intent_ids > 0) & routing.retention_terminal_mask,
                        routing.accumulation_km2, 0.)
    internal_receivers = np.full(elevation_m.shape, -1, dtype=np.int64)
    flat_rank = np.zeros(elevation_m.shape, dtype=np.uint32)
    internal_path_uphill = np.zeros_like(elevation_m)
    source = np.zeros_like(elevation_m)
    throughput = np.zeros_like(elevation_m)
    terminal = np.zeros_like(elevation_m)
    records = list(review.basins)
    x, y = np.meshgrid(x_km, y_km)
    for index, (basin, record) in enumerate(zip(basins, records, strict=True)):
        route = record.outlet_route
        if basin.outlet_km is None:
            continue
        inside = intent_ids == record.intent_id
        assert basin.source.water_level_m is not None
        below = elevation_m < basin.source.water_level_m - review.elevation_tolerance_m
        wet = inside & below
        opening = np.hypot(x - basin.outlet_km[0], y - basin.outlet_km[1]) <= hypot(dx, dy)
        uncontrolled = int(np.count_nonzero(low_boundary_cells(inside, wet, below, opening)))
        issues = list(record.issues)
        if uncontrolled:
            issues.append("outlet_shoreline_uncontained")
        elif "low_boundary" in issues:
            issues.remove("low_boundary")
        records[index] = replace(record, uncontrolled_low_boundary_cell_count=uncontrolled,
                                  issues=tuple(issues))
        if (route is None or route.status != "sampled_clear" or uncontrolled
                or record.shoreline is None or record.shoreline.profile.status != "sampled"
                or record.shoreline.uncontrolled_low_sample_count
                or record.wet_component_count != 1 or not record.footprint_cell_count):
            continue
        assert route.water_contact_flat_index is not None
        assert route.terminal_flat_index is not None
        collection = _collect_basin(basin, inside, wet, route.water_contact_flat_index,
                                    elevation_m, x_km, y_km, sample_ground, features)
        links = collection.wet_links
        if links.status != "sampled":
            issues.append("wet_link_sampling_unresolved")
        elif links.blocked_link_count:
            issues.append("wet_link_barrier")
        dry = collection.dry_links
        if dry is not None:
            if dry.status != "sampled":
                issues.append("dry_link_sampling_unresolved")
            elif dry.blocked_link_count:
                issues.append("dry_link_barrier")
            if dry.cumulative_uphill_cell_count:
                issues.append("dry_path_uphill")
        records[index] = replace(records[index], wet_links=links, dry_links=dry,
                                  issues=tuple(issues))
        if collection.routing is None:
            if links.status == "sampled":
                records[index] = replace(records[index],
                                         issues=(*issues, "outlet_water_disconnected"))
            continue
        nodes, internal = collection.nodes, collection.routing
        has_receiver = internal.receivers >= 0
        internal_receivers.ravel()[nodes[has_receiver]] = nodes[internal.receivers[has_receiver]]
        flat_rank.ravel()[nodes] = internal.flat_rank
        internal_path_uphill.ravel()[nodes] = collection.path_uphill_m
        connected = np.zeros_like(inside)
        connected.ravel()[nodes] = collection.connected
        captured = np.where(connected & routing.retention_terminal_mask,
                            routing.accumulation_km2, 0.)
        amount = float(np.sum(captured))
        remaining = max(0., record.captured_contributing_area_km2 - amount)
        source += captured
        retained[connected] = 0.
        catchment_class[connected & wet] = BasinCatchmentClass.COLLECTED_WATER
        catchment_class[connected & ~wet] = BasinCatchmentClass.COLLECTED_DRY
        throughput.ravel()[np.asarray(route.path_flat_indices, dtype=np.int64)] += amount
        terminal.ravel()[route.terminal_flat_index] += amount
        if remaining > 1e-8:
            issues.append("outlet_partial_catchment")
        records[index] = replace(records[index], outlet_connection="connected",
            retained_contributing_area_km2=remaining, outlet_contributing_area_km2=amount,
            flat_routed_cell_count=int(np.count_nonzero(internal.flat_rank)),
            collected_flat_cell_count=int(np.count_nonzero(
                (internal.flat_rank > 0) & collection.connected)),
            collected_wet_cell_count=int(np.count_nonzero(connected & wet)),
            collected_dry_cell_count=int(np.count_nonzero(connected & ~wet)),
            retained_cell_count=int(np.count_nonzero(inside & ~connected)),
            issues=tuple(issues))
    source_area = float(np.count_nonzero(land_mask)) * dx * dy
    retained_area = sum(record.retained_contributing_area_km2 for record in records)
    direct_area = float(np.sum(routing.accumulation_km2[routing.outlet_mask & (intent_ids == 0)]))
    delivered_area = float(np.sum(terminal))
    error = source_area - (retained_area + direct_area + delivered_area)
    if not np.isclose(error, 0., rtol=0., atol=max(1e-8, source_area * 1e-10)):
        raise RuntimeError("Basin outlet transfer did not conserve contributing area.")
    summary = BasinOutflowSummary("captured-mfd-reviewed-d8-outlets@8",
        FLAT_ROUTING_ALGORITHM_ID,
        sum(record.outlet_connection == "connected" for record in records),
        source_area, retained_area, direct_area, delivered_area, error)
    return (replace(review, basins=tuple(records)),
            BasinOutflow(internal_receivers, flat_rank, internal_path_uphill, catchment_class,
                         retained, source, throughput, terminal, summary))
