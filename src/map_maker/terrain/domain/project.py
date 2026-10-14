"""Version-independent domain state for an authored terrain project."""

from dataclasses import dataclass, field
from math import isfinite
from typing import Literal

from map_maker.terrain.domain.models import (
    Coastline,
    ElevationMode,
    LandformSettings,
    TerrainConstraint,
    TerrainSettings,
)
from map_maker.terrain.domain.terrain_context import TerrainWorldContext

type AuthoringTool = Literal["brush", "height", "ridge", "valley", "region", "lake", "dry_basin"]


def _validate_tool_value(
    elevation_mode: ElevationMode,
    elevation_m: float,
    size_km: float,
) -> None:
    if elevation_mode not in ("absolute", "relative"):
        raise ValueError("Elevation mode must be 'absolute' or 'relative'.")
    if not isfinite(elevation_m):
        raise ValueError("Tool elevation must be finite.")
    if elevation_mode == "absolute" and elevation_m < 0:
        raise ValueError("Absolute tool elevation must be at or above sea level.")
    if not isfinite(size_km) or size_km <= 0:
        raise ValueError("Tool size must be positive and finite.")


@dataclass(frozen=True, slots=True)
class BrushToolSettings:
    """Remembered controls for the soft terrain brush."""

    elevation_mode: ElevationMode = "relative"
    elevation_m: float = 500.0
    width_km: float = 280.0
    intensity: float = 0.55

    def __post_init__(self) -> None:
        _validate_tool_value(self.elevation_mode, self.elevation_m, self.width_km)
        if not isfinite(self.intensity) or not 0.0 < self.intensity <= 1.0:
            raise ValueError("Brush intensity must be greater than 0 and at most 1.")


@dataclass(frozen=True, slots=True)
class FeatureToolSettings:
    """Remembered controls for a point, ridge, or valley authoring tool."""

    elevation_mode: ElevationMode
    elevation_m: float
    radius_km: float

    def __post_init__(self) -> None:
        _validate_tool_value(self.elevation_mode, self.elevation_m, self.radius_km)


def _default_height_tool() -> FeatureToolSettings:
    return FeatureToolSettings("absolute", 2_500.0, 120.0)


def _default_ridge_tool() -> FeatureToolSettings:
    return FeatureToolSettings("relative", 1_200.0, 120.0)


def _default_valley_tool() -> FeatureToolSettings:
    return FeatureToolSettings("relative", 700.0, 90.0)


@dataclass(frozen=True, slots=True)
class LakeToolSettings:
    water_level_m: float = 500.0
    outlet_at_first_vertex: bool = False

    def __post_init__(self) -> None:
        if (isinstance(self.water_level_m, bool) or not isfinite(self.water_level_m)
                or self.water_level_m < 0):
            raise ValueError("Lake water level must be finite and non-negative.")
        if type(self.outlet_at_first_vertex) is not bool:
            raise ValueError("Lake outlet selection must be boolean.")


@dataclass(frozen=True, slots=True)
class TerrainAuthoringState:
    """User-facing tool defaults that should survive closing the workbench."""

    region: LandformSettings = field(default_factory=LandformSettings)
    lake: LakeToolSettings = field(default_factory=LakeToolSettings)
    active_tool: AuthoringTool = "brush"
    brush: BrushToolSettings = field(default_factory=BrushToolSettings)
    height: FeatureToolSettings = field(default_factory=_default_height_tool)
    ridge: FeatureToolSettings = field(default_factory=_default_ridge_tool)
    valley: FeatureToolSettings = field(default_factory=_default_valley_tool)

    def __post_init__(self) -> None:
        if self.active_tool not in (
            "brush", "height", "ridge", "valley", "region", "lake", "dry_basin",
        ):
            raise ValueError("Active authoring tool is not supported.")
        for name, settings in (("ridge", self.ridge), ("valley", self.valley)):
            if settings.elevation_mode == "relative" and settings.elevation_m < 0:
                raise ValueError(f"Relative {name} magnitude must not be negative.")


@dataclass(frozen=True, slots=True)
class TerrainProject:
    """All authored state needed to reopen and regenerate one terrain project."""

    coastline: Coastline
    settings: TerrainSettings
    constraints: tuple[TerrainConstraint, ...] = ()
    authoring: TerrainAuthoringState = field(default_factory=TerrainAuthoringState)
    world_context: TerrainWorldContext | None = None

    def __post_init__(self) -> None:
        if self.world_context is not None:
            self.world_context.validate_frame(self.coastline.bounds, self.settings.object_scale_km)
