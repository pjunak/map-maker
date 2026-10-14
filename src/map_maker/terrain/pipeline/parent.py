"""Replay a completed parent's effective inputs before permitting regional reuse."""

from dataclasses import dataclass, fields, is_dataclass
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain import EndpointGrid, LocalMetricFrame, TerrainProject
from map_maker.terrain.pipeline.generate import ProgressCallback, prepare_terrain_field
from map_maker.terrain.pipeline.regional import REGIONAL_CHUNK_SAMPLES, TerrainRegionSampler
from map_maker.terrain.pipeline.water import sampled_basin_water

PARENT_REPLAY_ALGORITHM_ID = "verified-parent-field-replay@1"


@dataclass(frozen=True, slots=True)
class ParentRouting:
    x_km: NDArray[np.float64]
    y_km: NDArray[np.float64]
    land_mask: NDArray[np.bool_]
    final_elevation_m: NDArray[np.float64]
    source_elevation_m: NDArray[np.float64]
    receivers: NDArray[np.int64]
    channel_mask: NDArray[np.bool_]
    accumulation_km2: NDArray[np.float64]
    incision_m: NDArray[np.float64]
    incision_limit_m: NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ParentTerrainData:
    """Decoded artifacts; these become a reference only after numerical replay."""

    build_id: str
    project: TerrainProject
    x_km: NDArray[np.float64]
    y_km: NDArray[np.float64]
    elevation_m: NDArray[np.float32]
    land_mask: NDArray[np.bool_]
    water_surface_m: NDArray[np.float32]
    basin_intent_ids: NDArray[np.uint32]
    routing: ParentRouting

    @property
    def grid(self) -> EndpointGrid:
        frame = LocalMetricFrame(
            self.project.coastline.bounds, self.project.settings.object_scale_km
        )
        return EndpointGrid.for_extent(frame.extent_km, self.project.settings.resolution_px)


@dataclass(frozen=True, slots=True)
class VerifiedTerrainParent:
    data: ParentTerrainData
    sampler: TerrainRegionSampler
    verified_ground_nodes: int
    verified_routing_nodes: int


def _freeze(value: object) -> None:
    """Seal owned arrays in the prepared dataclasses as well as the decoded snapshot."""
    if isinstance(value, np.ndarray):
        cast(NDArray[Any], value).setflags(write=False)
    elif is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            _freeze(getattr(value, item.name))
    elif isinstance(value, tuple):
        for item in cast(tuple[object, ...], value):
            _freeze(item)


def _equal(actual: NDArray[Any], expected: NDArray[Any], label: str) -> None:
    if (
        actual.dtype != expected.dtype
        or actual.shape != expected.shape
        or not np.array_equal(actual.view(np.uint8), expected.view(np.uint8))
    ):
        raise ValueError(f"Parent replay mismatch in {label}; rebuild with the current generator.")


def prepare_verified_parent(
    data: ParentTerrainData,
    progress: ProgressCallback | None = None,
) -> VerifiedTerrainParent:
    """Check every delivered node, water sample and reused canonical routing field."""
    project, grid = data.project, data.grid
    field = prepare_terrain_field(
        project.coastline, project.settings, project.constraints, progress,
        world_context=project.world_context,
    )
    _equal(data.x_km, np.linspace(grid.extent_km[0], grid.extent_km[2], grid.width), "x axis")
    _equal(data.y_km, np.linspace(grid.extent_km[1], grid.extent_km[3], grid.height), "y axis")
    count = grid.width * grid.height
    for start in range(0, count, REGIONAL_CHUNK_SAMPLES):
        stop = min(start + REGIONAL_CHUNK_SAMPLES, count)
        ids = np.arange(start, stop, dtype=np.int64)
        x, y = data.x_km[ids % grid.width], data.y_km[ids // grid.width]
        values, mask = field.evaluate(x, y)
        ground = np.where(mask, values, np.nan).astype(np.float32)
        water, labels = sampled_basin_water(ground, x, y, field.basins)
        for actual, saved, label in (
            (ground, data.elevation_m, "ground"),
            (mask, data.land_mask, "land mask"),
            (water, data.water_surface_m, "water surface"),
            (labels, data.basin_intent_ids, "basin identity"),
        ):
            _equal(actual, saved.ravel()[start:stop], label)
        if progress is not None:
            progress(0.1 + 0.8 * stop / count, "Verifying all saved parent samples")
    if progress is not None:
        progress(0.92, "Verifying inherited canonical routing")
    automatic, routing = field.automatic_valleys, data.routing
    for name in ("x_km", "y_km", "land_mask"):
        _equal(getattr(automatic, name), getattr(routing, name), f"canonical {name}")
    for name in (
        "source_elevation_m",
        "receivers",
        "channel_mask",
        "accumulation_km2",
        "incision_m",
        "incision_limit_m",
    ):
        _equal(getattr(automatic.drainage, name), getattr(routing, name), f"canonical {name}")
    rx, ry = np.meshgrid(automatic.x_km, automatic.y_km)
    final, _mask = field.evaluate(rx, ry)
    _equal(
        final.astype(np.float32).astype(np.float64),
        routing.final_elevation_m,
        "canonical finished ground",
    )
    _freeze(data)
    _freeze(field)
    if progress is not None:
        progress(1.0, "Parent replay verified")
    sampler = TerrainRegionSampler(data.build_id, grid, field)
    return VerifiedTerrainParent(data, sampler, count, rx.size)
