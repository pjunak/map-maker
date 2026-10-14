"""Finished-ground evidence along the inspected downstream outlet path."""

from dataclasses import dataclass

import numpy as np

from map_maker.terrain.pipeline.water_sampling import (
    GroundProfile,
    GroundSampler,
    SamplingGuide,
    sample_ground_profile,
)


@dataclass(frozen=True, slots=True)
class DownstreamProfile:
    profile: GroundProfile
    reaches_terminal: bool
    path_vertex_sample_indices: tuple[int, ...]
    maximum_uphill_excursion_m: float | None
    rise_from_sample_index: int | None
    rise_to_sample_index: int | None


def sample_downstream_profile(
    vertices_km: tuple[tuple[float, float], ...], canonical_ground_m: tuple[float, ...],
    reaches_terminal: bool, spacing_limit_km: float, sample_ground: GroundSampler,
    features: tuple[SamplingGuide, ...] = (),
) -> DownstreamProfile:
    """Keep a complete profile or no ground evidence; never reset its budget per edge.

    This is a conservative non-rising-ground test. Real flow over adverse bed
    slopes needs water-surface/energy and storage assumptions that this review
    does not model. The cumulative minimum avoids hiding a climb in tiny steps.
    """
    if (len(vertices_km) != len(canonical_ground_m)
            or len(set(vertices_km)) != len(vertices_km)):
        raise ValueError("Downstream profiles need distinct path vertices and matching heights.")
    profile = sample_ground_profile(vertices_km, spacing_limit_km, sample_ground, features)
    if profile.status != "sampled":
        return DownstreamProfile(profile, reaches_terminal, (), None, None, None)
    position_indices = {point: index for index, point in enumerate(profile.positions_km)}
    vertex_indices = tuple(position_indices[point] for point in vertices_km)
    heights = np.asarray(profile.ground_m, dtype=np.float64)
    if not np.array_equal(heights[np.asarray(vertex_indices)],
                          np.asarray(canonical_ground_m, dtype=np.float32)):
        raise ValueError("Downstream samples must match canonical Float32 ground.")
    excursions = heights - np.minimum.accumulate(heights)
    crest = int(np.argmax(excursions))
    maximum = float(excursions[crest])
    low = int(np.argmin(heights[:crest + 1])) if maximum > 0 else None
    return DownstreamProfile(profile, reaches_terminal, vertex_indices, maximum,
                             low, crest if maximum > 0 else None)
