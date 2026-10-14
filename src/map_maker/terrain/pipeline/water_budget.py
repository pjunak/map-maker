"""Read-only demand planning for shorelines and potential internal water networks."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline import dry_links, water_sampling, wet_links
from map_maker.terrain.pipeline.link_planning import (
    LinkCandidates,
    basin_neighbours,
    plan_water_links,
    water_link_candidates,
)
from map_maker.terrain.pipeline.water import (
    WATER_ELEVATION_TOLERANCE_M,
    MetricBasin,
    basin_intent_ids,
)
from map_maker.terrain.pipeline.water_sampling import SamplingGuide


@dataclass(frozen=True, slots=True)
class SamplingDemand:
    status: Literal["within_budget", "budget_exceeded"]
    baseline_sample_count: int
    requested_sample_count: int
    sample_limit: int
    candidate_profile_count: int
    visited_profile_count: int
    limiting_budget: Literal["network", "profile"] | None

    @property
    def count_is_exact(self) -> bool:
        # Early failure need not visit every guide/profile. Never advertise the
        # remaining coarse baseline as the final feature-guided network total.
        return self.status == "within_budget"


@dataclass(frozen=True, slots=True)
class BasinSamplingBudget:
    intent_id: int
    kind: Literal["lake", "dry_basin"]
    has_outlet: bool
    footprint_cell_count: int
    wet_cell_count: int
    shoreline: SamplingDemand | None
    wet_links: SamplingDemand | None
    dry_links: SamplingDemand | None


@dataclass(frozen=True, slots=True)
class WaterSamplingBudget:
    sampling_algorithm_id: str
    grid_width: int
    grid_height: int
    profile_sample_limit: int
    wet_network_sample_limit: int
    dry_network_sample_limit: int
    basins: tuple[BasinSamplingBudget, ...]


def _network_demand(
    candidates: LinkCandidates, features: tuple[SamplingGuide, ...], limit: int,
) -> SamplingDemand:
    plan = plan_water_links(candidates, features, sample_budget=limit,
                            planner=water_sampling.plan_ground_profile)
    return SamplingDemand(
        "within_budget" if plan.status == "sampled" else "budget_exceeded",
        plan.baseline_sample_count, plan.requested_sample_count, limit,
        len(candidates.sources), plan.planned_link_count, plan.limiting_budget,
    )


def plan_water_sampling_budget(
    basins: tuple[MetricBasin, ...], elevation_m: NDArray[np.float64],
    x_km: NDArray[np.float64], y_km: NDArray[np.float64],
    features: tuple[SamplingGuide, ...] = (),
) -> WaterSamplingBudget:
    """Plan current candidate profiles; do not infer eligibility or allocate stations.

    Shorelines are always reviewed for lakes. Internal networks are potential
    demand for outlet lakes: a full review can skip them after outlet, shoreline
    or wet-connectivity failure. External routes and contacts are not forecast.
    Counts include repeated stations, exactly as the review budgets do.
    """
    x, y = np.meshgrid(x_km, y_km)
    intent_ids = basin_intent_ids(x, y, basins)
    spacing = min(float(x_km[1] - x_km[0]), float(y_km[1] - y_km[0])) / 4
    records: list[BasinSamplingBudget] = []
    for intent_id, basin in enumerate(basins, 1):
        inside = intent_ids == intent_id
        level = basin.source.water_level_m
        shoreline = wet_links_demand = dry_links_demand = None
        wet_count = 0
        if level is not None:
            profile = water_sampling.plan_ground_profile(
                water_sampling.shoreline_vertices(basin), spacing, features)
            shoreline = SamplingDemand(
                "within_budget" if profile.status == "sampled" else "budget_exceeded",
                profile.baseline_sample_count, profile.requested_sample_count,
                water_sampling.MAX_PROFILE_SAMPLES, 1, 1,
                None if profile.status == "sampled" else "profile",
            )
            wet = inside & (elevation_m < level - WATER_ELEVATION_TOLERANCE_M)
            wet_count = int(np.count_nonzero(wet))
            if basin.outlet_km is not None:
                nodes, neighbours = basin_neighbours(basin, inside, x_km, y_km)
                local_wet = wet.ravel()[nodes]
                wet_links_demand = _network_demand(
                    water_link_candidates(nodes, neighbours, local_wet, elevation_m,
                                          x_km, y_km, level, kind="wet"),
                    features, wet_links.MAX_WET_LINK_SAMPLES,
                )
                dry_links_demand = _network_demand(
                    water_link_candidates(nodes, neighbours, local_wet, elevation_m,
                                          x_km, y_km, level, kind="dry"),
                    features, dry_links.MAX_DRY_LINK_SAMPLES,
                )
        records.append(BasinSamplingBudget(
            intent_id, basin.source.kind, basin.outlet_km is not None,
            int(np.count_nonzero(inside)), wet_count, shoreline, wet_links_demand, dry_links_demand,
        ))
    return WaterSamplingBudget(
        water_sampling.WATER_SAMPLING_ALGORITHM_ID, len(x_km), len(y_km),
        water_sampling.MAX_PROFILE_SAMPLES, wet_links.MAX_WET_LINK_SAMPLES,
        dry_links.MAX_DRY_LINK_SAMPLES, tuple(records),
    )
