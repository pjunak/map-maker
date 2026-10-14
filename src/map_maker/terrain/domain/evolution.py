"""Units and bounded history inputs for the experimental evolution comparison.

These values are not yet terrain-project settings or a saved-project contract.
"""

import re
from dataclasses import dataclass
from math import isclose, isfinite

EVOLUTION_MODEL_ID = "uplift-stream-power-diffusion-reference@1"
EVOLUTION_INITIAL_STAGE_ID = "terrain.evolution.initial"


def _number(value: float, label: str, *, zero: bool = False) -> None:
    if (isinstance(value, bool) or not isfinite(value)
            or value < 0 or (not zero and value == 0)):
        raise ValueError(f"{label} must be finite and {'nonnegative' if zero else 'positive'}.")


@dataclass(frozen=True, slots=True)
class EvolutionGrid:
    """Square endpoint spacing; fixed perimeter nodes own no control area."""

    width_m: float = 80_000.
    height_m: float = 60_000.
    spacing_m: float = 625.

    def __post_init__(self) -> None:
        for name in ("width_m", "height_m", "spacing_m"):
            _number(getattr(self, name), name)
        for length in (self.width_m, self.height_m):
            intervals = length / self.spacing_m
            if (not isfinite(intervals) or not 4 <= intervals <= 4096
                    or not isclose(intervals, round(intervals), rel_tol=0., abs_tol=1.e-8)):
                raise ValueError("Evolution extents need 4-4096 whole square-cell intervals.")
        if self.shape[0] * self.shape[1] > 262_144:
            raise ValueError("Evolution research grids are limited to 262,144 nodes.")

    @property
    def shape(self) -> tuple[int, int]:
        return round(self.height_m / self.spacing_m) + 1, round(self.width_m / self.spacing_m) + 1

    @property
    def contributing_area_m2(self) -> float:
        rows, columns = self.shape
        return (rows - 2) * (columns - 2) * self.spacing_m**2


@dataclass(frozen=True, slots=True)
class EvolutionEpoch:
    """An authored forcing interval, not a final elevation requirement."""

    name: str
    duration_years: float
    uplift_m_per_year: float
    runoff_m_per_year: float = .4
    erodibility_m_per_year: float = .001
    diffusivity_m2_per_year: float = .05

    def __post_init__(self) -> None:
        if (type(self.name) is not str
                or re.fullmatch(r"[a-z][a-z0-9-]{0,47}", self.name) is None):
            raise ValueError("Epoch name must be a short lowercase identifier.")
        _number(self.duration_years, "Epoch duration")
        for name in ("uplift_m_per_year", "runoff_m_per_year", "erodibility_m_per_year",
                     "diffusivity_m2_per_year"):
            _number(getattr(self, name), name, zero=True)
            if not isfinite(getattr(self, name) * self.duration_years):
                raise ValueError("Integrated epoch forcing must be finite.")


@dataclass(frozen=True, slots=True)
class EvolutionHistory:
    epochs: tuple[EvolutionEpoch, ...]
    reference_discharge_m3_per_year: float = 1_000_000.
    discharge_exponent: float = .5

    def __post_init__(self) -> None:
        if type(self.epochs) is not tuple or not 1 <= len(self.epochs) <= 16:
            raise ValueError("History requires an immutable tuple of 1-16 epochs.")
        if any(type(epoch) is not EvolutionEpoch for epoch in self.epochs):
            raise ValueError("History contains an invalid epoch.")
        if len({epoch.name for epoch in self.epochs}) != len(self.epochs):
            raise ValueError("Epoch names must be unique within a history.")
        if not isfinite(self.duration_years):
            raise ValueError("Total history duration must be finite.")
        _number(self.reference_discharge_m3_per_year, "Reference discharge")
        _number(self.discharge_exponent, "Discharge exponent", zero=True)
        if self.discharge_exponent > 1:
            raise ValueError("The reference comparison supports discharge exponents from 0 to 1.")

    @property
    def duration_years(self) -> float:
        return sum(epoch.duration_years for epoch in self.epochs)


@dataclass(frozen=True, slots=True)
class EvolutionBudget:
    maximum_step_years: float = 25_000.
    minimum_step_years: float = .01
    step_error_m: float = .5
    maximum_steps: int = 4096
    maximum_trials: int = 8192
    maximum_seconds: float = 60.

    def __post_init__(self) -> None:
        for name in ("maximum_step_years", "minimum_step_years", "step_error_m",
                     "maximum_seconds"):
            _number(getattr(self, name), name)
        if self.minimum_step_years > self.maximum_step_years:
            raise ValueError("Minimum step exceeds maximum step.")
        for name in ("maximum_steps", "maximum_trials"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 100_000:
                raise ValueError("Step and trial budgets must be integers from 1 to 100,000.")
        if self.maximum_trials < self.maximum_steps:
            raise ValueError("Trial budget must cover the accepted-step budget.")
