"""Finite attainable-floor profiles for selected canonical channel segments."""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.profile import monotone_grid_slopes
from map_maker.terrain.pipeline.reconstruction import BoundedBicubicGrid

CHANNEL_PROFILE_STATIONS = 17

type FloatArray = NDArray[np.float64]
type SourceSampler = Callable[
    [FloatArray, FloatArray], tuple[FloatArray, FloatArray, NDArray[np.bool_]]]


def attainable_targets(lower: FloatArray, upper: FloatArray, desired: FloatArray) -> FloatArray:
    """Carry downstream obstacles upstream and unfillable pits downstream.

    Rows run downstream. Feasible intervals yield nonincreasing targets when
    desired is nonincreasing. Conflicts retain the obstacle envelope; the actual
    pointwise source/cut bounds still win. No source filling is authorized.
    """
    downstream = np.maximum.accumulate(lower[:, ::-1], axis=1)[:, ::-1]
    upstream = np.minimum.accumulate(upper, axis=1)
    return np.maximum(downstream, np.minimum(desired, upstream))


@dataclass(frozen=True, slots=True)
class ChannelProfiles:
    """Sparse immutable cubic targets, indexed by four undirected grid edges."""

    edge_ids: NDArray[np.int32]
    targets_m: FloatArray
    _slopes: FloatArray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (self.edge_ids.ndim != 3 or self.edge_ids.shape[0] != 4
                or self.targets_m.ndim != 2 or self.targets_m.shape[1] != CHANNEL_PROFILE_STATIONS
                or not np.all(np.isfinite(self.targets_m)) or np.any(self.targets_m < 0.)
                or np.any(self.edge_ids < -1) or np.any(self.edge_ids >= len(self.targets_m))):
            raise ValueError("Channel profiles need finite targets and valid sparse edge IDs.")
        for name in ("edge_ids", "targets_m"):
            values = getattr(self, name).copy()
            values.flags.writeable = False
            object.__setattr__(self, name, values)
        slopes = monotone_grid_slopes(
            self.targets_m, np.linspace(0., 1., CHANNEL_PROFILE_STATIONS), axis=1)
        slopes.flags.writeable = False
        object.__setattr__(self, "_slopes", slopes)

    def sample(
        self, direction: int, row: NDArray[np.int64], column: NDArray[np.int64],
        position: FloatArray, baseline: FloatArray,
    ) -> FloatArray:
        ids = self.edge_ids[direction, row, column]
        active = ids >= 0
        if not np.any(active):
            return baseline
        ids = ids[active]
        intervals = CHANNEL_PROFILE_STATIONS-1
        station = np.clip(position[active], 0., 1.)*intervals
        segment = np.minimum(station.astype(np.int64), intervals-1)
        t = station-segment
        t2, t3 = t*t, t*t*t
        first, last = self.targets_m[ids, segment], self.targets_m[ids, segment+1]
        values = ((2*t3-3*t2+1)*first + (-2*t3+3*t2)*last
                  + ((t3-2*t2+t)*self._slopes[ids, segment]
                     + (t3-t2)*self._slopes[ids, segment+1])/intervals)
        result = baseline.copy()
        result[active] = np.clip(values, np.minimum(first, last), np.maximum(first, last))
        return result


def prepare_channel_profiles(
    incision: BoundedBicubicGrid, floors: FloatArray, receivers: NDArray[np.int64],
    horizontal: NDArray[np.bool_], vertical: NDArray[np.bool_], diagonals: NDArray[np.int8],
    sample_source: SourceSampler, *, batch_edges: int = 256,
) -> ChannelProfiles:
    """Observe 17 stations per selected edge; omit incomplete/non-descending edges."""
    if not 1 <= batch_edges <= 256:
        raise ValueError("Channel profile preparation needs batches of 1-256 edges.")
    cap = incision.ceiling
    assert cap is not None
    x, y = incision.x, incision.y
    ny, nx = floors.shape
    ids = np.full((4, ny, nx), -1, dtype=np.int32)
    parts: list[FloatArray] = []
    count = 0
    fractions = np.linspace(0., 1., CHANNEL_PROFILE_STATIONS)[None, :]
    for direction, mask, dy, dx in (
        (0, horizontal, 0, 1), (1, vertical, 1, 0),
        (2, diagonals == 1, 1, 1), (3, diagonals == -1, -1, 1),
    ):
        rows, columns = np.nonzero(mask)
        if direction == 3:
            rows = rows+1
        for start in range(0, rows.size, batch_edges):
            r, c = rows[start:start+batch_edges], columns[start:start+batch_edges]
            a, b = r+dy, c+dx
            reverse = receivers[r, c] != a*nx+b
            first, last = floors[r, c], floors[a, b]
            descending = np.where(reverse, last >= first, first >= last)
            r, c, a, b, reverse = (value[descending] for value in (r, c, a, b, reverse))
            if not r.size:
                continue
            qx = x[c, None]*(1-fractions)+x[b, None]*fractions
            qy = y[r, None]*(1-fractions)+y[a, None]*fractions
            macro, detail, land = sample_source(qx, qy)
            if (macro.shape != qx.shape or detail.shape != qx.shape or land.shape != qx.shape
                    or not np.all(np.isfinite(macro[land]))
                    or not np.all(np.isfinite(detail[land])) or np.any(macro[land] < 0.)):
                raise ValueError(
                    "Channel sampler needs finite nonnegative macro and shared shapes.")
            valid = np.all(land, axis=1)
            r, c, a, b, reverse = (value[valid] for value in (r, c, a, b, reverse))
            if not r.size:
                continue
            qx, qy, macro, detail = (value[valid] for value in (qx, qy, macro, detail))
            rr = np.clip(np.searchsorted(y, qy, side="right")-1, 0, ny-2)
            cc = np.clip(np.searchsorted(x, qx, side="right")-1, 0, nx-2)
            tx, ty = (qx-x[cc])/(x[cc+1]-x[cc]), (qy-y[rr])/(y[rr+1]-y[rr])
            ceiling = ((cap[rr, cc]*(1-tx)+cap[rr, cc+1]*tx)*(1-ty)
                       + (cap[rr+1, cc]*(1-tx)+cap[rr+1, cc+1]*tx)*ty)
            upper = np.maximum(macro+detail, 0.)
            lower = np.maximum(macro-np.minimum(ceiling, macro)+detail, 0.)
            desired = floors[r, c, None]*(1-fractions)+floors[a, b, None]*fractions
            # Canonical floors are fixed pins, including local incision and detail.
            lower[:, [0, -1]] = upper[:, [0, -1]] = desired[:, [0, -1]]
            lower, upper, desired = (np.where(reverse[:, None], v[:, ::-1], v)
                                     for v in (lower, upper, desired))
            targets = attainable_targets(lower, upper, desired)
            changed = np.any(targets != desired, axis=1)
            targets = np.where(reverse[:, None], targets[:, ::-1], targets)[changed]
            if targets.size:
                ids[direction, r[changed], c[changed]] = np.arange(count, count+len(targets))
                parts.append(targets)
                count += len(targets)
    values = np.concatenate(parts) if parts else np.empty((0, CHANNEL_PROFILE_STATIONS))
    return ChannelProfiles(ids, values)
