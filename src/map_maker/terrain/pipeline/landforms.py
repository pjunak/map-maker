# pyright: reportUnknownMemberType=false
"""Regional macro composition before authored constraints and drainage planning."""

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain import LandformSettings, TerrainSettings
from map_maker.terrain.domain.seeds import LANDFORM_STAGE_ID, stage_seed
from map_maker.terrain.pipeline.landform_weights import (
    MetricRegion as MetricRegion,
)
from map_maker.terrain.pipeline.landform_weights import (
    prepare_regions as prepare_regions,
)
from map_maker.terrain.pipeline.landform_weights import (
    regional_transition_mask as regional_transition_mask,
)
from map_maker.terrain.pipeline.landform_weights import (
    regional_weights,
)
from map_maker.terrain.pipeline.noise import fractal_value_noise

LANDFORM_ALGORITHM_ID = "regional-landforms@4"


def _broad_noise(
    x: NDArray[np.float64], y: NDArray[np.float64], seed: int, feature_size_km: float,
) -> NDArray[np.float64]:
    # The fixed two-band shape carrier uses its full scale. It is not a growing
    # detail prefix: its weights stay 2/3 and 1/3 at every selected detail count.
    return fractal_value_noise(x, y, seed=seed, largest_feature_km=feature_size_km,
                               detail_levels=2, roughness=0.5) / 0.75


def regional_noise_basis(
    x: NDArray[np.float64], y: NDArray[np.float64], controls: LandformSettings, seed: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Shared coordinates/carrier for regional relief and mountain-crest detection."""
    angle = np.deg2rad(controls.orientation_deg)
    u = np.cos(angle) * x + np.sin(angle) * y
    v = -np.sin(angle) * x + np.cos(angle) * y
    if controls.character == "mountains":
        u = u / 3.0
    broad = _broad_noise(u, v, seed, controls.feature_size_km)
    return u, v, broad


def regional_elevation_fields(
    x: NDArray[np.float64], y: NDArray[np.float64], coast_distance: NDArray[np.float64],
    full: NDArray[np.float64], macro: NDArray[np.float64],
    settings: TerrainSettings, regions: tuple[MetricRegion, ...],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    if not regions:
        return full, macro
    total = np.zeros_like(full)
    target_macro = np.zeros_like(full)
    target_full = np.zeros_like(full)
    seed = stage_seed(settings.seed, LANDFORM_STAGE_ID)
    coastal_gate = -np.expm1(-coast_distance / settings.coastal_rise_km)
    for region, inside, weight in regional_weights(x, y, regions):
        controls = region.settings
        u, v, broad = regional_noise_basis(x[inside], y[inside], controls, seed)
        detail = fractal_value_noise(u, v, seed=seed,
            largest_feature_km=controls.feature_size_km,
            detail_levels=max(2, settings.detail_levels),
            roughness=settings.roughness, start_band=2)
        if controls.character == "mountains":
            # A second coordinate window varies summit heights along the belt;
            # a single ridged carrier would give every crest the same height.
            crest = _broad_noise(u + 5 * controls.feature_size_km, v - 7 * controls.feature_size_km,
                                 seed, 1.8 * controls.feature_size_km)
            shape = np.power(1 - np.abs(broad), 3) * (0.25 + 0.75 * (0.5 + 0.5 * crest))
            texture = 0.45 * detail * (0.3 + 0.7 * shape)
        elif controls.character == "plateau":
            shape, texture = 0.1 * broad, 0.03 * detail
        elif controls.character == "plain":
            shape, texture = 0.5 * broad, 0.05 * detail
        else:
            shape, texture = 0.5 * broad, 0.3 * detail
        local_macro = np.maximum(controls.elevation_m + controls.relief_m * shape, 0)
        local_full = np.maximum(local_macro + controls.relief_m * texture, 0)
        target_macro[inside] += weight * local_macro * coastal_gate[inside]
        target_full[inside] += weight * local_full * coastal_gate[inside]
        total[inside] += weight
    influence = np.minimum(total, 1)
    denominator = np.maximum(total, np.finfo(np.float64).tiny)
    return (
        full * (1 - influence) + target_full / denominator * influence,
        macro * (1 - influence) + target_macro / denominator * influence,
    )


def regional_incision_limit(background_budget_m: float, controls: LandformSettings) -> float:
    """Native full-influence automatic-cut limit for one landform recipe."""
    fraction = {"plain": 0.15, "hills": 0.40, "plateau": 0.25, "mountains": 0.25}
    return min(background_budget_m, fraction[controls.character] * controls.relief_m)


def regional_incision_budget(
    x: NDArray[np.float64], y: NDArray[np.float64], background_budget_m: float,
    regions: tuple[MetricRegion, ...],
) -> NDArray[np.float64]:
    """Blend heuristic automatic-cut limits; authored valleys are separate."""
    total = np.zeros_like(x)
    target = np.zeros_like(x)
    for region, inside, weight in regional_weights(x, y, regions):
        controls = region.settings
        local_budget = regional_incision_limit(background_budget_m, controls)
        target[inside] += weight * local_budget
        total[inside] += weight
    influence = np.minimum(total, 1)
    denominator = np.maximum(total, np.finfo(np.float64).tiny)
    return background_budget_m * (1 - influence) + target / denominator * influence
