"""Shared admission of regional memory estimates; this is not a process RSS limit."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Self
from weakref import finalize

import numpy as np

from map_maker.terrain.adapters.parent import LoadedTerrainParent, ParentLoadPlan
from map_maker.terrain.adapters.regional_review import comparison_layout
from map_maker.terrain.adapters.render import GROUND_RENDER_TILE_EDGE
from map_maker.terrain.domain.models import ElevationPoint
from map_maker.terrain.domain.regional import (
    DETAIL_CELL_LIMIT,
    DETAIL_PROBE_INTERVALS,
    RegionalSamplingRequest,
    detail_support_window,
)
from map_maker.terrain.pipeline.detail import DETAIL_CELL_BATCH
from map_maker.terrain.pipeline.regional import REGIONAL_CHUNK_SAMPLES

MIB = 1024 * 1024
DEFAULT_REGIONAL_MEMORY_BYTES = 1024 * MIB


class RegionalMemoryAdmissionError(ValueError):
    """The requested estimate cannot fit alongside existing reservations."""


@dataclass(frozen=True, slots=True)
class RegionalMemoryInfo:
    budget_bytes: int
    reserved_bytes: int
    peak_reserved_bytes: int
    reservations: int


class RegionalMemoryBudget:
    """Nonblocking, thread-safe reservations shared by explicitly related sessions.

    No jobs are queued, cancelled or degraded to make room. Callers must use the
    same pool to enforce an aggregate policy; other processes are outside it.
    """

    def __init__(self, budget_bytes: int = DEFAULT_REGIONAL_MEMORY_BYTES) -> None:
        if type(budget_bytes) is not int or budget_bytes <= 0:
            raise ValueError("Regional memory budget must be a positive integer byte count.")
        self._budget = budget_bytes
        self._lock = Lock()
        self._entries: dict[object, int] = {}
        self._bytes = self._peak = 0

    def reserve(self, size: int, label: str) -> MemoryReservation:
        token = object()
        with self._lock:
            self._entries[token] = 0
        reservation = MemoryReservation(
            lambda size: self._resize(token, size, label), lambda: self._release(token),
        )
        try:
            reservation.resize(size)
        except BaseException:
            reservation.close()
            raise
        return reservation

    def _resize(self, token: object, size: int, label: str) -> None:
        if type(size) is not int or size < 0:
            raise ValueError("Memory reservation must be a nonnegative integer byte count.")
        with self._lock:
            if token not in self._entries:
                raise RuntimeError("Memory reservation is closed.")
            other = self._bytes - self._entries[token]
            if other + size > self._budget:
                raise RegionalMemoryAdmissionError(
                    f"Regional memory admission rejected {label}: estimated {size:,} bytes "
                    f"needs {other + size:,} with other reservations; budget {self._budget:,}. "
                    "Close another session, reduce the requested region/refinement or result "
                    "cache capacity, or explicitly choose a larger shared budget. "
                    "This policy estimates allocations; it is not a process memory limit."
                )
            self._entries[token] = size
            self._bytes = other + size
            self._peak = max(self._peak, self._bytes)

    def _release(self, token: object) -> None:
        with self._lock:
            self._bytes -= self._entries.pop(token, 0)

    def info(self) -> RegionalMemoryInfo:
        with self._lock:
            return RegionalMemoryInfo(self._budget, self._bytes, self._peak, len(self._entries))


class MemoryReservation:
    """An owned reservation, released on context exit or eventual garbage collection."""

    def __init__(self, resize: Callable[[int], None], release: Callable[[], None]) -> None:
        self._resize = resize
        self._finalizer = finalize(self, release)

    def resize(self, size: int) -> None:
        self._resize(size)

    def close(self) -> None:
        self._finalizer()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


DEFAULT_REGIONAL_MEMORY_BUDGET = RegionalMemoryBudget()


@dataclass(frozen=True, slots=True)
class ParentMemoryEstimate:
    loaded_array_bytes: int
    input_allowance_bytes: int
    prepared_array_allowance_bytes: int
    geometry_allowance_bytes: int
    detail_context_allowance_bytes: int
    result_cache_capacity_bytes: int
    metadata_allowance_bytes: int
    protection_count: int

    @property
    def total_bytes(self) -> int:
        return (self.loaded_array_bytes + self.input_allowance_bytes
                + self.prepared_array_allowance_bytes + self.geometry_allowance_bytes
                + self.detail_context_allowance_bytes + self.result_cache_capacity_bytes
                + self.metadata_allowance_bytes)


@dataclass(frozen=True, slots=True)
class RegionalJobEstimate:
    result_array_bytes: int
    sampling_allowance_bytes: int
    preparation_allowance_bytes: int
    rendering_allowance_bytes: int
    io_allowance_bytes: int

    @property
    def total_bytes(self) -> int:
        # These stages are serial. Reserve a new complete result even on a cache
        # hit: the estimate and acceptance do not depend on cache request history.
        return self.result_array_bytes + self.io_allowance_bytes + max(
            self.sampling_allowance_bytes, self.preparation_allowance_bytes,
            self.rendering_allowance_bytes,
        )


@dataclass(frozen=True, slots=True)
class ParentSessionMemoryInfo:
    retained: ParentMemoryEstimate | None
    active_job_bytes: int
    shared: RegionalMemoryInfo


def estimate_parent_memory(loaded: LoadedTerrainParent, cache_bytes: int) -> ParentMemoryEstimate:
    data, project = loaded.data, loaded.data.project
    grid = data.grid
    routing = data.routing.land_mask.size
    inputs = next(size for name, size, _digest in loaded.products if name == "inputs.json")
    coast = project.coastline
    rings = sum(1 + len(c.holes) for c in coast.components)
    points = sum(len(c.exterior) + sum(map(len, c.holes)) for c in coast.components)
    authored_points = sum(
        1 if isinstance(c, ElevationPoint) else len(c.points) for c in project.constraints
    )
    features = len(project.constraints)
    protections = features + int(np.count_nonzero(data.routing.channel_mask))
    return ParentMemoryEstimate(
        13 * grid.width * grid.height + 8 * (grid.width + grid.height)
        + 50 * routing + 8 * (data.routing.x_km.size + data.routing.y_km.size),
        ParentLoadPlan(inputs).input_allowance_bytes,
        512 * routing + MIB,
        2048 * (points + authored_points) + 65_536 * features + 4096 * rings,
        4096 * max(1, protections) + 2048 * authored_points + 512 * DETAIL_CELL_LIMIT,
        cache_bytes, MIB, protections,
    )


def estimate_regional_job(
    request: RegionalSamplingRequest, parent: ParentMemoryEstimate, *,
    detail: bool, needs_preparation: bool,
) -> RegionalJobEstimate:
    height, width = request.sample_shape
    count = height * width
    cells = 0
    if detail:
        left, top, right, bottom = detail_support_window(request)
        cells = (right - left + 1) * (bottom - top + 1)
    arrays = (21 if detail else 13) * count + 8 * (height + width) + 40 * cells
    probes = DETAIL_CELL_BATCH * (DETAIL_PROBE_INTERVALS + 1) ** 2 if detail else 0
    # Allow 256 float64-equivalent buffers/native point overhead per evaluated
    # sample. Detail STRtree intersections contain two int64 indices per pair.
    sampling = 2048 * max(min(count, REGIONAL_CHUNK_SAMPLES), probes)
    if detail:
        sampling += 16 * min(cells, DETAIL_CELL_BATCH) * max(1, parent.protection_count)
        sampling += (2048 + 4 * (DETAIL_PROBE_INTERVALS + 1) ** 2) * cells
    # Canonical preparation and parent replay have larger simultaneous fields.
    preparation = 4096 * 257**2 + parent.geometry_allowance_bytes if needs_preparation else 0
    tile_samples = (min(height, GROUND_RENDER_TILE_EDGE + 2)
                    * min(width, GROUND_RENDER_TILE_EDGE + 2))
    rendering = (32 if detail else 8) * count + 256 * tile_samples
    if detail:
        rows, columns = request.core_slices
        layout = comparison_layout(columns.stop - columns.start, rows.stop - rows.start)
        canvas_width, canvas_height = layout.canvas_size
        rendering += 4 * canvas_width * canvas_height
    return RegionalJobEstimate(arrays, sampling, preparation, rendering, 16 * MIB)
