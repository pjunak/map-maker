"""Public, coordinate-addressed controls for geological-history experiments."""

from dataclasses import dataclass, replace
from hashlib import sha256
from math import isfinite
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.domain.evolution import (
    EVOLUTION_INITIAL_STAGE_ID,
    EvolutionEpoch,
    EvolutionGrid,
    EvolutionHistory,
)
from map_maker.terrain.domain.seeds import stage_seed, validate_master_seed
from map_maker.terrain.pipeline.noise import fractal_value_noise

FloatArray = NDArray[np.float64]
HistoryCase = Literal[
    "two-epoch", "constant", "reversed", "uplift-only", "uniform-rock",
    "diffusion-only", "incision-only",
]
CASES: tuple[HistoryCase, ...] = (
    "two-epoch", "constant", "reversed", "uplift-only", "uniform-rock",
    "diffusion-only", "incision-only",
)


def frozen(values: FloatArray) -> FloatArray:
    result = np.array(values, dtype=np.float64, copy=True)
    result.flags.writeable = False
    return result


@dataclass(frozen=True, slots=True)
class EvolutionFields:
    grid: EvolutionGrid
    initial_m: FloatArray
    uplift_weight: FloatArray
    resistance: FloatArray
    runoff_weight: FloatArray

    def __post_init__(self) -> None:
        for name in ("initial_m", "uplift_weight", "resistance", "runoff_weight"):
            values = np.asarray(getattr(self, name), dtype=np.float64)
            if values.shape != self.grid.shape or not np.all(np.isfinite(values)):
                raise ValueError("Evolution fields must be finite and match the process grid.")
            if np.any(values < 0) or (name == "resistance" and np.any(values <= 0)):
                raise ValueError("Fields must be nonnegative and rock resistance positive.")
            if name == "uplift_weight" and np.any(values > 1):
                raise ValueError("Uplift weights must be between zero and one.")
            object.__setattr__(self, name, frozen(values))

    @property
    def core(self) -> NDArray[np.bool_]:
        mask = np.zeros(self.grid.shape, dtype=np.bool_)
        mask[1:-1, 1:-1] = True
        return mask

    def hashes(self) -> dict[str, str]:
        return {name: sha256(getattr(self, name).astype('<f8').tobytes()).hexdigest()
                for name in ("initial_m", "uplift_weight", "resistance", "runoff_weight")}


def scenario(grid: EvolutionGrid, seed: int, angle_deg: float = 25.) -> EvolutionFields:
    validate_master_seed(seed)
    if isinstance(angle_deg, bool) or not isfinite(angle_deg) or not 0 <= angle_deg < 180:
        raise ValueError("Uplift orientation must be from 0 up to 180 degrees.")
    y, x = np.meshgrid(np.arange(grid.shape[0], dtype=np.float64) * grid.spacing_m,
                       np.arange(grid.shape[1], dtype=np.float64) * grid.spacing_m, indexing="ij")
    # These fields depend on metric coordinates, never node count or iteration order.
    edge = np.minimum.reduce((x, y, grid.width_m-x, grid.height_m-y))
    taper = np.minimum(edge / 8_000., 1.)
    taper = taper * taper * (3.-2.*taper)
    theta = np.deg2rad(angle_deg)
    across = (x-.48*grid.width_m)*np.sin(theta) + (y-.48*grid.height_m)*np.cos(theta)
    along = (x-.48*grid.width_m)*np.cos(theta) - (y-.48*grid.height_m)*np.sin(theta)
    uplift = np.exp(-(across/10_000.)**2 - (along/32_000.)**4) * taper
    noise = fractal_value_noise(x/1000., y/1000., seed=stage_seed(seed, EVOLUTION_INITIAL_STAGE_ID),
                                largest_feature_km=8., detail_levels=3, roughness=.5)
    initial = taper * (60. + 110.*uplift + 10.*noise)
    resistance = 1. + 3.*np.exp(-((across-2500.)/2500.)**4)
    return EvolutionFields(grid, initial, uplift, resistance, np.ones_like(x))


def history(case: HistoryCase) -> EvolutionHistory:
    active = EvolutionEpoch("active-uplift", 2_000_000., .0005)
    old = EvolutionEpoch("waning-uplift", 4_000_000., .00005)
    if case in ("two-epoch", "uniform-rock"):
        epochs = (active, old)
    elif case == "reversed":
        epochs = (old, active)
    elif case == "constant":
        epochs = (replace(active, name="matched-total-forcing", duration_years=6_000_000.,
                          uplift_m_per_year=.0002),)
    elif case in ("uplift-only", "diffusion-only", "incision-only"):
        epochs = tuple(replace(
            e, erodibility_m_per_year=e.erodibility_m_per_year if case == "incision-only" else 0.,
            diffusivity_m2_per_year=e.diffusivity_m2_per_year if case == "diffusion-only" else 0.,
        ) for e in (active, old))
    else:
        raise ValueError(f"Unknown evolution scenario: {case}")
    return EvolutionHistory(epochs)


def scenario_identity(fields: EvolutionFields, seed: int, angle_deg: float) -> str:
    from dataclasses import asdict

    return sha256(canonical_json({"grid": asdict(fields.grid), "seed": seed,
                                  "angle_deg": angle_deg, "fields": fields.hashes()})).hexdigest()
