"""Sample bounded windows of the unchanged global terrain field."""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from hashlib import sha256

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain import Coastline, EndpointGrid, LocalMetricFrame, TerrainSettings
from map_maker.terrain.domain.models import TerrainConstraint
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.domain.seeds import SEED_POLICY_ID
from map_maker.terrain.domain.terrain_context import TerrainWorldContext
from map_maker.terrain.pipeline.generate import (
    AUTOMATIC_VALLEY_ALGORITHM_ID,
    GENERATOR_ALGORITHM_ID,
    NOISE_ALGORITHM_ID,
    PreparedTerrainField,
    ProgressCallback,
    prepare_terrain_field,
)
from map_maker.terrain.pipeline.landforms import LANDFORM_ALGORITHM_ID
from map_maker.terrain.pipeline.terrain_context import context_identity
from map_maker.terrain.pipeline.water import sampled_basin_water

REGIONAL_SAMPLING_ALGORITHM_ID = "regional-unchanged-field-sampling@1"
REGIONAL_CHUNK_SAMPLES = 65_536


def sampling_source_id(
    coastline: Coastline, settings: TerrainSettings, constraints: Sequence[TerrainConstraint] = (),
    *, world_context: TerrainWorldContext | None = None,
) -> str:
    """Bind input geometry/settings and algorithms; applications also bind the runtime."""
    payload = {
        "coastline": asdict(coastline), "settings": asdict(settings),
        "world_context": None if world_context is None else context_identity(world_context),
        "constraints": [{"type": type(c).__name__, **asdict(c)} for c in constraints],
        "algorithms": [GENERATOR_ALGORITHM_ID, AUTOMATIC_VALLEY_ALGORITHM_ID,
                       NOISE_ALGORITHM_ID, LANDFORM_ALGORITHM_ID, SEED_POLICY_ID],
    }
    return sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def regional_coordinates(
    request: RegionalSamplingRequest,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Subdivide each original interval, reusing exact parent nodes at every level."""
    left, top, right, bottom = request.sample_window
    grid = request.reference_grid
    a, b, c, d = grid.extent_km

    def subdivide(
        first: float, last: float, count: int, start: int, stop: int,
    ) -> NDArray[np.float64]:
        indices = np.arange(start, stop + 1, dtype=np.int64)
        lower, remainder = np.divmod(indices, request.refinement)
        step = (last - first) / (count - 1)
        # Match np.linspace's original nodes without allocating the full axes.
        lo = lower.astype(np.float64) * step + first
        hi = np.minimum(lower + 1, count - 1).astype(np.float64) * step + first
        lo[lower == count - 1] = last
        hi[lower + 1 >= count - 1] = last
        fraction = remainder.astype(np.float64) / request.refinement
        result = lo + (hi - lo) * fraction
        result[remainder == 0] = lo[remainder == 0]
        if not np.all(np.diff(result) > 0):
            raise ValueError("Regional coordinates are not distinct at this precision.")
        return result

    return (subdivide(a, c, grid.width, left, right),
            subdivide(b, d, grid.height, top, bottom))


@dataclass(frozen=True, slots=True)
class RegionalTerrainSamples:
    """Read-only samples including halo; no local drainage review is implied."""

    request: RegionalSamplingRequest
    x_km: NDArray[np.float64]
    y_km: NDArray[np.float64]
    elevation_m: NDArray[np.float32]
    land_mask: NDArray[np.bool_]
    water_surface_m: NDArray[np.float32]
    basin_intent_ids: NDArray[np.uint32]
    canonical_grid: EndpointGrid
    maximum_elevation_m: float


@dataclass(frozen=True, slots=True)
class TerrainRegionSampler:
    """Reuse global constraints/profiles/drainage across independent windows."""

    source_id: str
    reference_grid: EndpointGrid
    _field: PreparedTerrainField = field(repr=False)

    @property
    def prepared_field(self) -> PreparedTerrainField:
        """Complete-source context for verified replay and separately generated detail."""
        return self._field

    def sample(
        self, request: RegionalSamplingRequest, progress: ProgressCallback | None = None,
    ) -> RegionalTerrainSamples:
        if request.source_id != self.source_id or request.reference_grid != self.reference_grid:
            raise ValueError("Regional request belongs to a different terrain source or grid.")
        x, y = regional_coordinates(request)
        height, width = request.sample_shape
        elevation = np.full((height, width), np.nan, dtype=np.float32)
        land = np.zeros((height, width), dtype=np.bool_)
        surface = np.full_like(elevation, np.nan)
        labels = np.zeros((height, width), dtype=np.uint32)
        count = height * width
        for start in range(0, count, REGIONAL_CHUNK_SAMPLES):
            stop = min(start + REGIONAL_CHUNK_SAMPLES, count)
            indices = np.arange(start, stop, dtype=np.int64)
            px, py = x[indices % width], y[indices // width]
            values, mask = self._field.evaluate(px, py)
            ground = np.where(mask, values, np.nan).astype(np.float32)
            if not np.isfinite(ground[mask]).all() or np.any(ground[mask] < 0):
                raise RuntimeError("Regional sampling produced invalid land elevations.")
            water, intent = sampled_basin_water(ground, px, py, self._field.basins)
            elevation.ravel()[start:stop], land.ravel()[start:stop] = ground, mask
            surface.ravel()[start:stop], labels.ravel()[start:stop] = water, intent
            if progress is not None:
                progress(stop / count, "Sampling the regional terrain field")
        for array in (x, y, elevation, land, surface, labels):
            array.setflags(write=False)
        automatic = self._field.automatic_valleys
        canonical = EndpointGrid(self.reference_grid.extent_km,
                                 automatic.x_km.size, automatic.y_km.size)
        return RegionalTerrainSamples(request, x, y, elevation, land, surface, labels,
                                      canonical, self._field.settings.maximum_elevation_m)


def prepare_regional_sampler(
    coastline: Coastline, settings: TerrainSettings, *,
    constraints: Sequence[TerrainConstraint] = (), progress: ProgressCallback | None = None,
    world_context: TerrainWorldContext | None = None,
) -> TerrainRegionSampler:
    authored = tuple(constraints)
    frame = LocalMetricFrame(coastline.bounds, settings.object_scale_km)
    grid = EndpointGrid.for_extent(frame.extent_km, settings.resolution_px)
    identity = sampling_source_id(coastline, settings, authored, world_context=world_context)
    prepared = prepare_terrain_field(
        coastline, settings, authored, progress, world_context=world_context,
    )
    return TerrainRegionSampler(identity, grid, prepared)
