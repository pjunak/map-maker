"""Generate a separate regional artifact from a completed, verified parent build."""

from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Self

from map_maker.terrain.adapters.build import runtime_identity
from map_maker.terrain.adapters.parent import (
    LoadedTerrainParent,
    ParentLoadPlan,
    load_terrain_parent,
)
from map_maker.terrain.adapters.parent_region import (
    publish_parent_region_manifest,
    write_parent_region_products,
)
from map_maker.terrain.application.region_cache import (
    DEFAULT_RESULT_CACHE_BYTES,
    ParentRegionResult,
    RegionResultCache,
    RegionResultCacheInfo,
)
from map_maker.terrain.application.region_memory import (
    DEFAULT_REGIONAL_MEMORY_BUDGET,
    MIB,
    MemoryReservation,
    ParentSessionMemoryInfo,
    RegionalJobEstimate,
    RegionalMemoryBudget,
    estimate_parent_memory,
    estimate_regional_job,
)
from map_maker.terrain.domain.coordinates import Bounds
from map_maker.terrain.domain.regional import (
    RegionalDetailSettings,
    RegionalSamplingRequest,
    detail_cell_window,
)
from map_maker.terrain.pipeline.control import (
    CancellationToken,
    cancellable_progress,
    check_cancelled,
)
from map_maker.terrain.pipeline.detail import PreparedRegionalDetail, prepare_regional_detail
from map_maker.terrain.pipeline.generate import ProgressCallback
from map_maker.terrain.pipeline.parent import VerifiedTerrainParent, prepare_verified_parent


def _destination(source: Path, destination: Path) -> Path:
    target = destination.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Regional destination already exists: {target}")
    if target.resolve().is_relative_to(source.resolve()):
        raise ValueError("Regional output must be outside the immutable parent build directory.")
    return target


class ParentRegionSession:
    """Serial artifact generation with one parent, one detail context and bounded results.

    Loading validates files immediately; numerical replay waits for the first valid
    request. File/runtime drift closes the session. Cache arrays stay private.
    """

    def __init__(
        self, source: Path, *, result_cache_bytes: int = DEFAULT_RESULT_CACHE_BYTES,
        memory_budget: RegionalMemoryBudget | None = None,
    ) -> None:
        self._results = RegionResultCache(result_cache_bytes)
        self._budget = (memory_budget if memory_budget is not None
                        else DEFAULT_REGIONAL_MEMORY_BUDGET)
        self._memory = self._budget.reserve(8 * MIB + result_cache_bytes, "parent session")
        self._loaded: LoadedTerrainParent | None = None
        self._parent: VerifiedTerrainParent | None = None
        self._detail: PreparedRegionalDetail | None = None
        self._writing = False
        self._operation = Lock()
        self._active_bytes = 0

        def admit(plan: ParentLoadPlan) -> None:
            self._memory.resize(plan.estimated_peak_bytes + result_cache_bytes)

        try:
            self._runtime = runtime_identity()
            self._loaded = load_terrain_parent(source, self._runtime, admit=admit)
            self._estimate = estimate_parent_memory(self._loaded, result_cache_bytes)
            self._memory.resize(self._estimate.total_bytes)
        except BaseException:
            self._release()
            raise

    def _require_open(self) -> LoadedTerrainParent:
        if self._loaded is None:
            raise RuntimeError("Parent regional session is closed; open a new session.")
        return self._loaded

    def _verify_current(self) -> None:
        loaded = self._require_open()
        try:
            if runtime_identity() != self._runtime:
                raise ValueError("Generator source or runtime changed during regional generation.")
            loaded.verify_unchanged()
        except Exception:
            # Missing distribution metadata and unexpected verification errors
            # also make the saved runtime unsuitable for reuse.
            self._release()
            raise

    def cache_info(self) -> RegionResultCacheInfo:
        """Inspect retained numeric bytes and entries; excludes parent/geometry and scratch."""
        return self._results.info()

    def memory_info(self) -> ParentSessionMemoryInfo:
        """Reserved estimates, separately from exact cached-array bytes and process RSS."""
        return ParentSessionMemoryInfo(
            self._estimate if self._loaded is not None else None,
            self._active_bytes, self._budget.info(),
        )

    def estimate_write(
        self, bounds_km: Bounds, refinement: int, *,
        detail_settings: RegionalDetailSettings | None = None,
    ) -> RegionalJobEstimate:
        """Estimate active work without preparing terrain, mutating caches or creating files."""
        loaded = self._require_open()
        request = RegionalSamplingRequest.for_bounds(
            loaded.data.build_id, loaded.data.grid, bounds_km, refinement
        )
        return estimate_regional_job(
            request, self._estimate, detail=detail_settings is not None,
            needs_preparation=self._parent is None,
        )

    def clear_cache(self) -> None:
        """Discard results and cell support while retaining the verified parent."""
        if not self._operation.acquire(blocking=False):
            raise RuntimeError("Cannot clear a parent regional session during generation.")
        try:
            self._results.clear()
            if self._detail is not None:
                self._detail.clear_cache()
        finally:
            self._operation.release()

    def _release(self) -> None:
        self._results.clear()
        self._detail = None
        self._parent = None
        self._loaded = None
        if not self._writing:
            self._memory.close()

    def close(self) -> None:
        if not self._operation.acquire(blocking=False):
            raise RuntimeError("Cannot close a parent regional session during generation.")
        try:
            self._release()
        finally:
            self._operation.release()

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def write(
        self, destination: Path, bounds_km: Bounds, refinement: int, *,
        detail_settings: RegionalDetailSettings | None = None,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Path:
        """Publish a new artifact, reusing exact requests only after freshness checks."""
        if not self._operation.acquire(blocking=False):
            raise RuntimeError("Parent regional session is already generating; use it serially.")
        reservation: MemoryReservation | None = None
        self._writing = True
        try:
            check_cancelled(cancellation)
            progress = cancellable_progress(progress, cancellation)
            loaded = self._require_open()
            target = _destination(loaded.directory, destination)
            request = RegionalSamplingRequest.for_bounds(
                loaded.data.build_id, loaded.data.grid, bounds_km, refinement
            )
            if detail_settings is not None:
                detail_cell_window(request)
            estimate = self.estimate_write(bounds_km, refinement, detail_settings=detail_settings)
            reservation = self._budget.reserve(estimate.total_bytes, "regional generation/export")
            self._active_bytes = estimate.total_bytes
            self._verify_current()
            check_cancelled(cancellation)
            if self._parent is None:
                self._parent = prepare_verified_parent(loaded.data, progress)
            check_cancelled(cancellation)
            parent = self._parent
            key = request, detail_settings
            result = self._results.get(key)
            if result is None:
                if detail_settings is None:
                    result = ParentRegionResult(parent.sampler.sample(request, progress))
                else:
                    if self._detail is None:
                        self._detail = prepare_regional_detail(
                            parent, detail_settings, progress=progress
                        )
                    elif self._detail.settings != detail_settings:
                        self._detail = replace(self._detail, settings=detail_settings)
                    detail = self._detail.sample(request, progress)
                    result = ParentRegionResult(detail.samples, detail)
                self._verify_current()
                check_cancelled(cancellation)
                self._results.put(key, result)
            else:
                if progress is not None:
                    progress(1.0, "Reusing verified regional samples")
                # A callback can change files even on a cache hit.
                self._verify_current()
            check_cancelled(cancellation)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.mkdir()
            outputs = write_parent_region_products(
                result.samples, parent, target, result.detail, cancellation=cancellation
            )
            self._verify_current()
            check_cancelled(cancellation)
            return publish_parent_region_manifest(
                result.samples, loaded, parent, target, bounds_km=bounds_km,
                runtime=self._runtime, outputs=outputs, detail_settings=detail_settings,
                detail=result.detail,
            )
        finally:
            if reservation is not None:
                reservation.close()
            self._active_bytes = 0
            self._writing = False
            if self._loaded is None:
                self._memory.close()
            self._operation.release()


def sample_parent_region(
    source: Path,
    destination: Path,
    bounds_km: Bounds,
    refinement: int,
    *,
    detail_settings: RegionalDetailSettings | None = None,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
    memory_budget: RegionalMemoryBudget | None = None,
) -> Path:
    check_cancelled(cancellation)
    target = _destination(source, destination)
    with ParentRegionSession(source, result_cache_bytes=0, memory_budget=memory_budget) as session:
        return session.write(
            target, bounds_km, refinement, detail_settings=detail_settings, progress=progress,
            cancellation=cancellation,
        )
