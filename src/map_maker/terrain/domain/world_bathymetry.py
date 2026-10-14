"""Explicit ocean-margin hypotheses; separate from land terrain and heat capacity."""

from dataclasses import dataclass
from math import isfinite

from map_maker.terrain.domain.world import WorldProject
from map_maker.terrain.domain.world_context import WorldContextSettings

BATHYMETRY_ALGORITHM = "conservative-distance-margin-v1"
MAX_OCEAN_SELECTION = 4096


def _positive(value: object, label: str, lower: float, upper: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or not lower <= value <= upper
    ):
        raise ValueError(f"{label} must be finite and between {lower:g} and {upper:g}.")


@dataclass(frozen=True, slots=True)
class BathymetrySettings:
    """Illustrative editable starting values, never inferred from ocean width/age."""

    latitude_cells: int = 180
    shelf_width_km: float = 100.0
    shelf_depth_m: float = 200.0
    slope_width_km: float = 200.0
    basin_depth_m: float = 4000.0

    def __post_init__(self) -> None:
        WorldContextSettings(self.latitude_cells)
        _positive(self.shelf_width_km, "Shelf width (km)", 1, 100_000)
        _positive(self.slope_width_km, "Slope width (km)", 1, 100_000)
        _positive(self.shelf_depth_m, "Shelf-break depth (m)", 1, 100_000)
        _positive(self.basin_depth_m, "Basin depth (m)", 1, 100_000)
        if self.basin_depth_m < self.shelf_depth_m:
            raise ValueError("Basin depth must be at least the shelf-break depth.")


@dataclass(frozen=True, slots=True)
class BathymetryInputs:
    world: WorldProject
    ocean_ids: tuple[int, ...]
    settings: BathymetrySettings = BathymetrySettings()

    def __post_init__(self) -> None:
        if (
            not 1 <= len(self.ocean_ids) <= MAX_OCEAN_SELECTION
            or any(type(i) is not int or not 1 <= i <= 2**31 - 1 for i in self.ocean_ids)
            or tuple(sorted(set(self.ocean_ids))) != self.ocean_ids
        ):
            raise ValueError(
                f"Select 1-{MAX_OCEAN_SELECTION} distinct positive water IDs in sorted order. "
                "Ocean membership must be explicit."
            )
