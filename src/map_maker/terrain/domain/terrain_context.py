"""Immutable metric samples of a specific geographic context, not a climate model."""

from dataclasses import dataclass, field
from math import isfinite

from map_maker.terrain.domain.coordinates import Bounds, EndpointGrid, LocalMetricFrame
from map_maker.terrain.domain.world_context import ConnectedWater, WorldContextSettings
from map_maker.terrain.domain.world_terrain import WorldTerrainProjection

TERRAIN_CONTEXT_MODEL = "spherical-context-coastal-support@1"
MAX_CONTEXT_SAMPLES_PER_AXIS = 129
# Buffers are immutable, C-order, little-endian values. Exposure is bearing-first.
CONTEXT_SAMPLE_FIELDS = (
    ("shore_lower_km", "<f8", 1), ("shore_upper_km", "<f8", 1),
    ("latitude_deg", "<f8", 1), ("longitude_deg", "<f8", 1),
    ("land_fraction", "<f8", 1), ("water_body", "<i4", 1),
    ("support_flags", "|u1", 1), ("water_exposure", "<f4", 8),
    ("exposure_mixed_support", "<f4", 8),
)


def _digest(value: object) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        c not in "0123456789abcdef" for c in value
    ):
        raise ValueError("Terrain context identity must be a lowercase SHA-256 digest.")


@dataclass(frozen=True, slots=True)
class TerrainWorldContext:
    """Bounded support grid; its fractions and water labels never define terrain land."""

    world_sha256: str
    context_input_sha256: str
    context_numeric_sha256: str
    producer_runtime_sha256: str
    context_latitude_cells: int
    source_bounds: Bounds
    projection: WorldTerrainProjection
    grid: EndpointGrid
    water_bodies: tuple[ConnectedWater, ...]
    fragmented_water_bodies: tuple[int, ...]
    source_shore_error_km: float
    geology_sha256: str | None = None
    shore_lower_km: bytes = field(default=b"", repr=False)
    shore_upper_km: bytes = field(default=b"", repr=False)
    latitude_deg: bytes = field(default=b"", repr=False)
    longitude_deg: bytes = field(default=b"", repr=False)
    land_fraction: bytes = field(default=b"", repr=False)
    water_body: bytes = field(default=b"", repr=False)
    support_flags: bytes = field(default=b"", repr=False)
    water_exposure: bytes = field(default=b"", repr=False)
    exposure_mixed_support: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        for digest in (self.world_sha256, self.context_input_sha256,
                       self.context_numeric_sha256, self.producer_runtime_sha256):
            _digest(digest)
        if self.geology_sha256 is not None:
            _digest(self.geology_sha256)
        WorldContextSettings(self.context_latitude_cells)
        if (not isfinite(self.source_shore_error_km) or self.source_shore_error_km < 0
                or isinstance(self.source_shore_error_km, bool)):
            raise ValueError("Terrain context shore error must be finite and non-negative.")
        x0, y0, x1, y1 = self.source_bounds
        frame = LocalMetricFrame(self.source_bounds, max(x1-x0, y1-y0)/1000)
        if (self.grid.extent_km != frame.extent_km
                or max(self.grid.width, self.grid.height) > MAX_CONTEXT_SAMPLES_PER_AXIS):
            raise ValueError("Terrain context grid must cover its bounded metric source.")
        ids = tuple(body.id for body in self.water_bodies)
        if (ids != tuple(sorted(set(ids))) or any(type(i) is not int or i <= 0 for i in ids)
                or any(isinstance(body.area_km2, bool) or not isfinite(body.area_km2)
                       or body.area_km2 <= 0 or type(body.crosses_seam) is not bool
                       or type(body.displayed_cells) is not int or body.displayed_cells < 0
                       for body in self.water_bodies)
                or any(type(i) is not int for i in self.fragmented_water_bodies)
                or self.fragmented_water_bodies != tuple(sorted(set(self.fragmented_water_bodies)))
                or not set(self.fragmented_water_bodies) <= set(ids)):
            raise ValueError("Terrain context water-body records are inconsistent.")
        for name, dtype, channels in CONTEXT_SAMPLE_FIELDS:
            data = getattr(self, name)
            size = self.grid.width * self.grid.height * channels * int(dtype[-1])
            if not isinstance(data, bytes) or len(data) != size:
                raise ValueError(f"Invalid terrain context buffer: {name}.")

    def validate_frame(self, bounds: Bounds, scale_km: float) -> None:
        if bounds != self.source_bounds or LocalMetricFrame(bounds, scale_km).extent_km != (
            self.grid.extent_km
        ):
            raise ValueError("Terrain context belongs to a different coastline frame or scale.")
