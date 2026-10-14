# pyright: reportUnknownMemberType=false
"""Experimental additive cell detail on a verified, unchanged reference field.

The added smooth basis has zero analytic integral per parent cell. Preparation
uses a fixed lattice, never the output density. This is a bounded experiment,
not accepted local hydrology or a certified bound on unseen terrain extrema.
"""

from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import Any, cast

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

from map_maker.terrain.domain.regional import (
    DETAIL_CELL_LIMIT,
    DETAIL_PROBE_INTERVALS,
    RegionalDetailSettings,
    RegionalSamplingRequest,
    detail_cell_window,
    detail_support_window,
)
from map_maker.terrain.domain.seeds import LOCAL_DETAIL_STAGE_ID, stage_seed
from map_maker.terrain.pipeline.detail_basis import (
    edge_coefficients,
    residual_basis,
    terrain_x_weight,
)
from map_maker.terrain.pipeline.detail_cache import (
    CellDetailSupport,
    DetailCacheInfo,
    DetailSupportCache,
)
from map_maker.terrain.pipeline.generate import ProgressCallback
from map_maker.terrain.pipeline.parent import VerifiedTerrainParent
from map_maker.terrain.pipeline.regional import RegionalTerrainSamples

DETAIL_CELL_BATCH = 64

LOCAL_DETAIL_ALGORITHM_ID = "terrain-weighted-edge-residual-experiment@2"


@dataclass(frozen=True, slots=True)
class DetailEvidence:
    parent_cells: int
    support_cells: int
    protected_cells: int
    active_cells: int
    probe_samples: int
    maximum_cell_mean_error_m: float
    maximum_added_height_m: float
    changed_samples: int


@dataclass(frozen=True, slots=True)
class DetailedRegion:
    samples: RegionalTerrainSamples
    reference_elevation_m: NDArray[np.float32]
    added_detail_m: NDArray[np.float32]
    cell_columns: NDArray[np.int64]
    cell_rows: NDArray[np.int64]
    cell_amplitude_m: NDArray[np.float64]
    reference_cell_mean_m: NDArray[np.float64]
    detailed_cell_mean_m: NDArray[np.float64]
    evidence: DetailEvidence


@dataclass(frozen=True, slots=True)
class PreparedRegionalDetail:
    """One immutable parent/settings context with a private, serial-use support cache."""

    parent: VerifiedTerrainParent
    settings: RegionalDetailSettings
    protections: STRtree
    cache_cells: int = DETAIL_CELL_LIMIT
    _cache: DetailSupportCache = dataclass_field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # init=False also gives dataclasses.replace a fresh cache when any context changes.
        object.__setattr__(self, "_cache", DetailSupportCache(self.cache_cells))

    def cache_info(self) -> DetailCacheInfo:
        """Operational counts only; never include request history in artifact identity."""
        return self._cache.info()

    def clear_cache(self) -> None:
        """Release retained support and reset operational counts, preserving the parent."""
        self._cache.clear()

    def sample(
        self, request: RegionalSamplingRequest, progress: ProgressCallback | None = None
    ) -> DetailedRegion:
        if progress is not None:
            progress(0.0, "Preparing regional detail cells")
        sampler = self.parent.sampler
        if (
            request.source_id != sampler.source_id
            or request.reference_grid != sampler.reference_grid
        ):
            raise ValueError("Detail request belongs to a different parent or grid.")
        left, top, right, bottom = detail_cell_window(request)
        sl, st, sr, sb = detail_support_window(request)
        cc, rr = np.meshgrid(
            np.arange(sl, sr + 1, dtype=np.int64), np.arange(st, sb + 1, dtype=np.int64)
        )
        sc, sy = cc.ravel(), rr.ravel()
        core = np.flatnonzero((sc >= left) & (sc <= right) & (sy >= top) & (sy <= bottom))
        columns, rows = sc[core], sy[core]
        core_slot = np.full(sc.size, -1, dtype=np.int64)
        core_slot[core] = np.arange(core.size)
        x, y = self.parent.data.x_km, self.parent.data.y_km
        field = sampler.prepared_field
        ceiling_m = float(np.float32(field.settings.maximum_elevation_m))
        if not np.isfinite(ceiling_m):
            raise ValueError("Local detail requires a finite Float32 terrain ceiling.")
        protected = np.zeros(sc.size, dtype=np.bool_)
        amplitude = np.zeros(sc.size, dtype=np.float64)
        x_weight = np.full(sc.size, 0.5, dtype=np.float64)
        reference_means = np.full(sc.size, np.nan, dtype=np.float64)
        detailed_means = reference_means.copy()
        missing: list[int] = []
        for index, (column, row) in enumerate(zip(sc, sy, strict=True)):
            support = self._cache.get(int(column), int(row))
            if support is None:
                missing.append(index)
            else:
                protected[index] = support.protected
                amplitude[index] = support.amplitude_m
                x_weight[index] = support.x_weight
                reference_means[index] = support.reference_mean_m
                detailed_means[index] = support.detailed_mean_m
        pending = np.asarray(missing, dtype=np.int64)
        if pending.size:
            pc, pr = sc[pending], sy[pending]
            cells = cast(Any, shapely.box(x[pc], y[pr], x[pc + 1], y[pr + 1]))
            guard = min(sampler.reference_grid.x_spacing_km, sampler.reference_grid.y_spacing_km)
            inland = cast(
                NDArray[np.bool_], np.asarray(cast(Any, shapely.covers(field.polygon, cells)))
            )
            inland &= np.asarray(cast(Any, shapely.distance(cells, field.boundary))) > guard
            protected[pending] = ~inland
            for start in range(0, pending.size, DETAIL_CELL_BATCH):
                intersections = self.protections.query(
                    cells[start:start + DETAIL_CELL_BATCH], predicate="intersects"
                )
                if intersections.size:
                    protected[pending[start + np.unique(intersections[0])]] = True
                del intersections
                if progress is not None:
                    progress(0.05, "Checking bounded detail-protection batches")
            for index in pending[protected[pending]]:
                self._cache.put(int(sc[index]), int(sy[index]),
                                CellDetailSupport(True, 0.0, float("nan"), float("nan"), 0.5))

        seed = stage_seed(field.settings.seed, LOCAL_DETAIL_STAGE_ID)
        coefficients = edge_coefficients(columns, rows, seed)
        n = DETAIL_PROBE_INTERVALS
        uv = np.linspace(0.0, 1.0, n + 1)
        u, v = np.meshgrid(uv, uv)
        u, v = u.ravel(), v.ravel()
        weights = np.ones((n + 1, n + 1), dtype=np.float64)
        weights[[0, -1], :] *= 0.5
        weights[:, [0, -1]] *= 0.5
        weights = weights.ravel() / (n * n)
        # Keep probes only during this call, avoiding a second terrain evaluation
        # after both adjacent cell budgets are known. The cache remains scalar.
        need_moments = core[~protected[core] & np.isnan(detailed_means[core])]
        probe_bank = np.empty((need_moments.size, (n + 1) ** 2), dtype=np.float32)
        moment_slot = np.full(sc.size, -1, dtype=np.int64)
        moment_slot[need_moments] = np.arange(need_moments.size)
        pending = np.union1d(pending[~protected[pending]], need_moments)

        def points(ids: NDArray[np.int64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
            px = x[sc[ids], None] + (x[sc[ids] + 1] - x[sc[ids]])[:, None] * u
            py = y[sy[ids], None] + (y[sy[ids] + 1] - y[sy[ids]])[:, None] * v
            return px, py

        def remember(index: int) -> None:
            self._cache.put(int(sc[index]), int(sy[index]), CellDetailSupport(
                bool(protected[index]), float(amplitude[index]), float(reference_means[index]),
                float(detailed_means[index]), float(x_weight[index]),
            ))

        for start in range(0, pending.size, DETAIL_CELL_BATCH):
            ids = pending[start:start + DETAIL_CELL_BATCH]
            px, py = points(ids)
            reference = field.sample_ground(px, py)
            if not np.isfinite(reference).all():
                raise RuntimeError("Detail preparation encountered invalid interior ground.")
            z = reference.astype(np.float64)
            margin = np.min(np.minimum(z, ceiling_m - z), axis=1)
            amplitude[ids] = np.minimum(self.settings.amplitude_m, np.maximum(margin, 0.0) * 0.5)
            x_weight[ids] = terrain_x_weight(
                reference.reshape(-1, n + 1, n + 1),
                sampler.reference_grid.x_spacing_km / n,
                sampler.reference_grid.y_spacing_km / n,
            )
            reference_means[ids] = np.sum(z * weights, axis=1)
            selected = moment_slot[ids] >= 0
            probe_bank[moment_slot[ids[selected]]] = reference[selected]
            for index in ids:
                remember(int(index))
            if progress is not None:
                progress(0.1 + 0.25 * min(start + DETAIL_CELL_BATCH, pending.size) / pending.size,
                         "Preparing fixed terrain-aware detail support")

        # Share the smaller of the two adjacent budgets. An excluded neighbor
        # suppresses this edge on both sides; crop boundaries never change it.
        stride = sr - sl + 1
        neighbors = core[:, None] + np.array([-1, 1, -stride, stride])
        neighbors = np.clip(neighbors, 0, sc.size - 1)
        valid = np.column_stack((columns > 0, columns < x.size - 2,
                                 rows > 0, rows < y.size - 2))
        orientation = (x_weight[core, None] + x_weight[neighbors]) * 0.5
        orientation[:, :2] = 1 - orientation[:, :2]
        edge_amplitudes = np.minimum(amplitude[core, None], amplitude[neighbors]) * orientation
        edge_amplitudes[~valid] = 0.0
        for start in range(0, need_moments.size, DETAIL_CELL_BATCH):
            ids = need_moments[start:start + DETAIL_CELL_BATCH]
            local = core_slot[ids]
            px, py = points(ids)
            pu = (px - x[sc[ids], None]) / (x[sc[ids] + 1] - x[sc[ids]])[:, None]
            pv = (py - y[sy[ids], None]) / (y[sy[ids] + 1] - y[sy[ids]])[:, None]
            residual = residual_basis(pu, pv, coefficients[local, None],
                                      edge_amplitudes[local, None])
            detailed = (probe_bank[moment_slot[ids]].astype(np.float64) + residual).astype(
                np.float32
            )
            detailed_means[ids] = np.sum(detailed.astype(np.float64) * weights, axis=1)
            for index in ids:
                remember(int(index))
            if progress is not None:
                progress(0.4, "Measuring fixed detail moments")
        del probe_bank
        support_probe_samples = int(np.count_nonzero(~protected) * (n + 1) ** 2)
        protected, amplitude = protected[core], amplitude[core]
        reference_means, detailed_means = reference_means[core], detailed_means[core]
        active = np.flatnonzero(~protected)
        if progress is not None:
            progress(0.5, "Sampling the reference for local detail")
        samples = sampler.sample(request, progress)
        elevation = samples.elevation_m.copy()
        _height, width = elevation.shape
        for start in range(0, elevation.size, 65_536):
            stop = min(start + 65_536, elevation.size)
            indices = np.arange(start, stop, dtype=np.int64)
            px, py = samples.x_km[indices % width], samples.y_km[indices // width]
            column = np.clip(np.searchsorted(x, px, side="right") - 1, left, right)
            row = np.clip(np.searchsorted(y, py, side="right") - 1, top, bottom)
            local = (row - top) * (right - left + 1) + column - left
            u = (px - x[column]) / (x[column + 1] - x[column])
            v = (py - y[row]) / (y[row + 1] - y[row])
            residual = residual_basis(u, v, coefficients[local], edge_amplitudes[local])
            ground = elevation.ravel()[start:stop].astype(np.float64) + residual
            mask = samples.land_mask.ravel()[start:stop]
            if (
                np.any(ground[mask] < 0)
                or np.any(ground[mask] > ceiling_m)
                or not np.isfinite(ground[mask]).all()
            ):
                raise ValueError(
                    "Detail exceeds terrain bounds between fixed probes; "
                    "reduce its amplitude or choose another region."
                )
            elevation.ravel()[start:stop] = ground.astype(np.float32)
            if progress is not None:
                progress(stop / elevation.size, "Applying experimental local detail")
        added = np.where(samples.land_mask, elevation - samples.elevation_m, 0.0).astype(np.float32)
        errors = np.abs(detailed_means[active] - reference_means[active])
        evidence = DetailEvidence(
            columns.size,
            sc.size,
            int(protected.sum()),
            int(np.count_nonzero(amplitude)),
            support_probe_samples,
            float(errors.max(initial=0)),
            float(np.abs(added).max(initial=0)),
            int(np.count_nonzero(added)),
        )
        for array in (elevation, added, columns, rows, amplitude, reference_means, detailed_means):
            array.setflags(write=False)
        return DetailedRegion(
            replace(samples, elevation_m=elevation),
            samples.elevation_m,
            added,
            columns,
            rows,
            amplitude,
            reference_means,
            detailed_means,
            evidence,
        )


def prepare_regional_detail(
    parent: VerifiedTerrainParent, settings: RegionalDetailSettings, *,
    cache_cells: int = DETAIL_CELL_LIMIT,
    progress: ProgressCallback | None = None,
) -> PreparedRegionalDetail:
    """Protect complete cells intersecting authored cores, basins and planned channel corridors."""
    if progress is not None:
        progress(0.0, "Preparing local-detail protections")
    field = parent.sampler.prepared_field
    grid = parent.sampler.reference_grid
    guard = min(grid.x_spacing_km, grid.y_spacing_km)
    geometries: list[Any] = [basin.geometry.buffer(guard) for basin in field.basins]
    for constraint in field.constraints:
        geometries.append(constraint.geometry.buffer(max(guard, constraint.influence_radius_km)))
    routing = parent.data.routing
    width = routing.x_km.size
    sources = np.flatnonzero(routing.channel_mask & routing.land_mask)
    radius = max(guard, np.diff(routing.x_km).max(), np.diff(routing.y_km).max())
    for index, source in enumerate(sources):
        if progress is not None and index % 64 == 0:
            progress(0.05 * index / sources.size, "Protecting inherited channel corridors")
        row, column = divmod(int(source), width)
        start = (routing.x_km[column], routing.y_km[row])
        target = int(routing.receivers.flat[source])
        if target >= 0:
            tr, tc = divmod(target, width)
            geometry = LineString([start, (routing.x_km[tc], routing.y_km[tr])])
        else:
            geometry = Point(start)
        geometries.append(geometry.buffer(float(radius)))
    # An empty tree is supported, but keep a harmless outside-frame box explicit.
    if not geometries:
        geometries.append(box(-2 * guard, -2 * guard, -guard, -guard))
    if progress is not None:
        progress(0.05, "Local-detail protections prepared")
    return PreparedRegionalDetail(parent, settings, STRtree(geometries), cache_cells)
