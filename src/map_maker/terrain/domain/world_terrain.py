"""World-derived terrain source values, distinct from a generated world parent."""

from dataclasses import dataclass
from math import isfinite

from map_maker.terrain.domain.models import Coastline
from map_maker.terrain.domain.world import WorldProject
from map_maker.terrain.domain.world_geology import WorldGeologyRecipe

WORLD_TERRAIN_MODEL = "world-landmass-aeqd@2"
GEOLOGY_LANDFORM_MODEL = "explicit-geology-landforms@1"
MAX_PROJECTION_ANGLE_DEG = 80.0
MAX_PROJECTED_POINTS = 500_000


@dataclass(frozen=True, slots=True)
class WorldTerrainProjection:
    radius_km: float
    longitude_deg: float
    latitude_deg: float
    maximum_angle_deg: float
    maximum_transverse_scale: float
    curve_tolerance_m: float = 25.0
    source_step_deg: float = 0.25

    def __post_init__(self) -> None:
        if any(
            isinstance(v, bool) or not isfinite(v)
            for v in (
                self.radius_km,
                self.longitude_deg,
                self.latitude_deg,
                self.maximum_angle_deg,
                self.maximum_transverse_scale,
                self.curve_tolerance_m,
                self.source_step_deg,
            )
        ):
            raise ValueError("World terrain projection values must be finite numbers.")
        if (
            self.radius_km <= 0
            or not -180 <= self.longitude_deg < 180
            or not -90 <= self.latitude_deg <= 90
            or not 0 <= self.maximum_angle_deg <= MAX_PROJECTION_ANGLE_DEG
            or not 1 <= self.maximum_transverse_scale <= 1.5
            or self.curve_tolerance_m != 25.0
            or self.source_step_deg != 0.25
        ):
            raise ValueError("World terrain projection is outside the supported local domain.")

    @property
    def geographic_crs(self) -> str:
        return f"+proj=longlat +R={self.radius_km * 1000:.17g} +no_defs"

    @property
    def projected_crs(self) -> str:
        return (
            f"+proj=aeqd +lat_0={self.latitude_deg:.17g} "
            f"+lon_0={self.longitude_deg:.17g} +R={self.radius_km * 1000:.17g} "
            "+units=m +no_defs"
        )


@dataclass(frozen=True, slots=True)
class WorldTerrainSource:
    world: WorldProject
    requested_continent_id: str
    included_continent_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]
    coastline: Coastline
    projection: WorldTerrainProjection
    geology: WorldGeologyRecipe | None = None

    @property
    def object_scale_km(self) -> float:
        x0, y0, x1, y1 = self.coastline.bounds
        return max(x1 - x0, y1 - y0) / 1000.0
