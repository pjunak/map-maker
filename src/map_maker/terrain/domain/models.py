"""Core input models for deterministic terrain generation."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from map_maker.terrain.domain.seeds import validate_master_seed
from map_maker.terrain.domain.structure_profiles import (
    StructureProfileKnot,
    validate_structure_profile,
)

type Point2D = tuple[float, float]
type StructureKind = Literal["ridge", "valley"]
type ElevationMode = Literal["absolute", "relative"]


def _validate_count(value: object, minimum: int, maximum: int, label: str) -> None:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not minimum <= value <= maximum):
        raise ValueError(f"{label} must be an integer between {minimum:,} and {maximum:,}.")


def _validate_ring(points: tuple[Point2D, ...], label: str) -> None:
    if len(points) < 4:
        raise ValueError(f"{label} needs at least three vertices and a closing vertex.")
    if points[0] != points[-1]:
        raise ValueError(f"{label} must be closed.")
    if any(not isfinite(value) for point in points for value in point):
        raise ValueError(f"{label} coordinates must be finite.")


@dataclass(frozen=True, slots=True)
class LandComponent:
    """One connected land polygon with optional enclosed water holes."""

    exterior: tuple[Point2D, ...]
    holes: tuple[tuple[Point2D, ...], ...] = ()

    def __post_init__(self) -> None:
        _validate_ring(self.exterior, "Land-component exterior")
        for index, hole in enumerate(self.holes, start=1):
            _validate_ring(hole, f"Land-component hole {index}")


@dataclass(frozen=True, slots=True)
class Coastline:
    """Dissolved land geometry expressed as closed source-vector coastlines."""

    points: tuple[Point2D, ...]
    source_name: str
    holes: tuple[tuple[Point2D, ...], ...] = ()
    additional_components: tuple[LandComponent, ...] = ()

    def __post_init__(self) -> None:
        _validate_ring(self.points, "Primary land-component exterior")
        for index, hole in enumerate(self.holes, start=1):
            _validate_ring(hole, f"Primary land-component hole {index}")

    @property
    def components(self) -> tuple[LandComponent, ...]:
        """Return the primary landmass followed by disconnected land components."""

        return (LandComponent(self.points, self.holes), *self.additional_components)

    @property
    def component_count(self) -> int:
        return 1 + len(self.additional_components)

    @property
    def boundary_point_count(self) -> int:
        return sum(
            len(component.exterior) - 1
            + sum(len(hole) - 1 for hole in component.holes)
            for component in self.components
        )

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs = [point[0] for component in self.components for point in component.exterior]
        ys = [point[1] for component in self.components for point in component.exterior]
        return min(xs), min(ys), max(xs), max(ys)


def _validate_normalized_point(point: Point2D) -> None:
    if any(not isfinite(value) for value in point):
        raise ValueError("Constraint coordinates must be finite.")
    if any(not 0.0 <= value <= 1.0 for value in point):
        raise ValueError("Constraint coordinates must be between 0 and 1.")


def _validate_constraint_values(
    elevation_m: float,
    influence_radius_km: float,
    elevation_mode: ElevationMode,
    *,
    allow_signed_relative: bool,
) -> None:
    if elevation_mode not in ("absolute", "relative"):
        raise ValueError("Elevation mode must be 'absolute' or 'relative'.")
    if not isfinite(elevation_m):
        raise ValueError("Constraint elevation must be finite.")
    if elevation_mode == "absolute" and elevation_m < 0:
        raise ValueError("Absolute elevation must be at or above sea level.")
    if elevation_mode == "relative" and not allow_signed_relative and elevation_m < 0:
        raise ValueError("Relative ridge relief and valley depth must not be negative.")
    if not isfinite(influence_radius_km) or influence_radius_km <= 0:
        raise ValueError("Constraint influence radius must be positive and finite.")


@dataclass(frozen=True, slots=True)
class ElevationPoint:
    """An authored target height at a normalized position inside the coastline."""

    position: Point2D
    elevation_m: float
    influence_radius_km: float
    elevation_mode: ElevationMode = "absolute"

    def __post_init__(self) -> None:
        _validate_normalized_point(self.position)
        _validate_constraint_values(
            self.elevation_m,
            self.influence_radius_km,
            self.elevation_mode,
            allow_signed_relative=True,
        )


@dataclass(frozen=True, slots=True)
class TerrainStructure:
    """An authored ridge or upstream-to-downstream valley centreline."""

    kind: StructureKind
    points: tuple[Point2D, ...]
    elevation_m: float
    influence_radius_km: float
    elevation_mode: ElevationMode = "absolute"
    profile: tuple[StructureProfileKnot, ...] = ()

    def __post_init__(self) -> None:
        validate_structure_profile(
            self.profile,
            absolute_valley=self.kind == "valley" and self.elevation_mode == "absolute",
        )
        if self.kind not in ("ridge", "valley"):
            raise ValueError("Terrain structure kind must be 'ridge' or 'valley'.")
        if len(self.points) < 2:
            raise ValueError("A terrain structure needs at least two points.")
        for point in self.points:
            _validate_normalized_point(point)
        adjacent_pairs = zip(self.points, self.points[1:], strict=False)
        if any(first == second for first, second in adjacent_pairs):
            raise ValueError("Adjacent terrain structure points must be different.")
        _validate_constraint_values(
            self.elevation_m,
            self.influence_radius_km,
            self.elevation_mode,
            allow_signed_relative=False,
        )


@dataclass(frozen=True, slots=True)
class TerrainBrushStroke:
    """A soft target-elevation stroke painted in normalized map coordinates."""

    points: tuple[Point2D, ...]
    elevation_m: float
    influence_radius_km: float
    intensity: float
    elevation_mode: ElevationMode = "absolute"

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("A terrain brush stroke needs at least one point.")
        for point in self.points:
            _validate_normalized_point(point)
        adjacent_pairs = zip(self.points, self.points[1:], strict=False)
        if any(first == second for first, second in adjacent_pairs):
            raise ValueError("Adjacent terrain brush points must be different.")
        _validate_constraint_values(
            self.elevation_m,
            self.influence_radius_km,
            self.elevation_mode,
            allow_signed_relative=True,
        )
        if not isfinite(self.intensity) or not 0.0 < self.intensity <= 1.0:
            raise ValueError("Terrain brush intensity must be greater than 0 and at most 1.")


type LandformKind = Literal["plain", "hills", "plateau", "mountains"]


@dataclass(frozen=True, slots=True)
class LandformSettings:
    """Soft regional composition controls in physical units."""

    character: LandformKind = "plain"
    elevation_m: float = 250.0
    relief_m: float = 100.0
    feature_size_km: float = 150.0
    transition_km: float = 50.0
    orientation_deg: float = 0.0

    def __post_init__(self) -> None:
        if self.character not in ("plain", "hills", "plateau", "mountains"):
            raise ValueError("Unknown landform character.")
        for value in (self.elevation_m, self.relief_m):
            if not isfinite(value) or value < 0:
                raise ValueError("Regional elevation and relief must be finite and nonnegative.")
        for value in (self.feature_size_km, self.transition_km):
            if not isfinite(value) or value <= 0:
                raise ValueError("Regional size and transition must be positive and finite.")
        if not isfinite(self.orientation_deg) or not 0 <= self.orientation_deg < 180:
            raise ValueError("Regional orientation must be from 0 up to 180 degrees.")


def landform_preset(character: LandformKind) -> LandformSettings:
    """Starting points for editing, not biome or geological classifications."""
    values = {
        "plain": (250., 100., 150., 50.),
        "hills": (700., 900., 100., 70.),
        "plateau": (2200., 200., 200., 40.),
        "mountains": (1000., 3500., 120., 100.),
    }
    return LandformSettings(character, *values[character])


@dataclass(frozen=True, slots=True)
class TerrainRegion:
    """Closed normalized polygon selecting a soft regional terrain recipe."""

    points: tuple[Point2D, ...]
    settings: LandformSettings = LandformSettings()
    holes: tuple[tuple[Point2D, ...], ...] = ()

    def __post_init__(self) -> None:
        for ring in (self.points, *self.holes):
            _validate_ring(ring, "Terrain region")
            for point in ring:
                _validate_normalized_point(point)
            if len(set(ring[:-1])) < 3:
                raise ValueError("Terrain region rings need three distinct vertices.")


@dataclass(frozen=True, slots=True)
class TerrainBasin:
    """Authored retention footprint; lake water is separate from its ground DEM."""

    points: tuple[Point2D, ...]
    kind: Literal["lake", "dry_basin"]
    water_level_m: float | None = None
    outlet: Point2D | None = None

    def __post_init__(self) -> None:
        _validate_ring(self.points, "Basin footprint")
        for point in self.points:
            _validate_normalized_point(point)
        if len(set(self.points[:-1])) < 3:
            raise ValueError("Basin footprint needs three distinct vertices.")
        if self.kind not in ("lake", "dry_basin"):
            raise ValueError("Basin kind must be lake or dry_basin.")
        if self.kind == "lake":
            if (self.water_level_m is None or isinstance(self.water_level_m, bool)
                    or not isfinite(self.water_level_m) or self.water_level_m < 0):
                raise ValueError("Lake water level must be finite and non-negative.")
            if self.outlet is not None:
                _validate_normalized_point(self.outlet)
        elif self.water_level_m is not None or self.outlet is not None:
            raise ValueError("A dry basin cannot have a water level or an outlet.")


type TerrainConstraint = (
    ElevationPoint | TerrainStructure | TerrainBrushStroke | TerrainRegion | TerrainBasin
)


@dataclass(frozen=True, slots=True)
class TerrainSettings:
    """Effective settings for the first coastline-conditioned terrain model."""

    seed: int = 20_260_902
    object_scale_km: float = 4_000.0
    resolution_px: int = 768
    maximum_elevation_m: float = 4_500.0
    largest_feature_km: float = 450.0
    detail_levels: int = 6
    roughness: float = 0.55
    coastal_rise_km: float = 180.0
    variability: float = 0.75
    drainage_density: float = 1.0

    def __post_init__(self) -> None:
        validate_master_seed(self.seed)
        if not isfinite(self.object_scale_km) or self.object_scale_km <= 0:
            raise ValueError("Object scale must be finite and positive.")
        _validate_count(self.resolution_px, 64, 4_096, "Resolution")
        if not isfinite(self.maximum_elevation_m) or self.maximum_elevation_m <= 0:
            raise ValueError("Maximum elevation must be finite and positive.")
        if not isfinite(self.largest_feature_km) or self.largest_feature_km <= 0:
            raise ValueError("Largest feature size must be finite and positive.")
        _validate_count(self.detail_levels, 1, 12, "Detail levels")
        if not 0 < self.roughness < 1:
            raise ValueError("Roughness must be greater than 0 and less than 1.")
        if not isfinite(self.coastal_rise_km) or self.coastal_rise_km <= 0:
            raise ValueError("Coastal rise distance must be finite and positive.")
        if not 0 <= self.variability <= 1:
            raise ValueError("Variability must be between 0 and 1.")
        if not 0.25 <= self.drainage_density <= 2.0:
            raise ValueError("Drainage density must be between 0.25 and 2.")
