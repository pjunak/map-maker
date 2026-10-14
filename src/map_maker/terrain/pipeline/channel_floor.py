"""Fit automatic cuts to the sampled source inside existing channel corridors."""

from dataclasses import dataclass
from typing import Self

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.channel_profiles import (
    ChannelProfiles,
    SourceSampler,
    prepare_channel_profiles,
)
from map_maker.terrain.pipeline.channel_reconstruction import channel_diagonals, smoothstep
from map_maker.terrain.pipeline.reconstruction import BoundedBicubicGrid

type FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ChannelFloorReconstruction:
    """Pre-constraint floor targets; canonical nodes and cut ceilings stay fixed.

    Cuts move toward linear or sampled attainable targets along selected edges.
    The result never fills above the uncut source with its retained detail.
    Fixed canonical pins and finite profiles do not certify complete rivers.
    """

    incision: BoundedBicubicGrid
    floor_m: FloatArray
    horizontal: NDArray[np.bool_]
    vertical: NDArray[np.bool_]
    diagonals: NDArray[np.int8]
    profiles: ChannelProfiles | None = None

    def __post_init__(self) -> None:
        ny, nx = self.incision.values.shape
        if (self.incision.ceiling is None or self.floor_m.shape != (ny, nx)
                or not np.all(np.isfinite(self.floor_m)) or np.any(self.floor_m < 0.)
                or self.horizontal.shape != (ny, nx-1)
                or self.vertical.shape != (ny-1, nx)
                or self.diagonals.shape != (ny-1, nx-1)
                or not np.all(np.isin(self.diagonals, [-1, 0, 1]))
                or (self.profiles is not None
                    and self.profiles.edge_ids.shape != (4, ny, nx))):
            raise ValueError("Channel floors need finite nonnegative heights and matching grids.")
        for name in ("floor_m", "horizontal", "vertical", "diagonals"):
            values = getattr(self, name).copy()
            values.flags.writeable = False
            object.__setattr__(self, name, values)

    @classmethod
    def prepare(
        cls, incision: BoundedBicubicGrid, floor_m: FloatArray,
        receivers: NDArray[np.int64], channels: NDArray[np.bool_],
        land: NDArray[np.bool_], *, sample_source: SourceSampler | None = None,
    ) -> Self:
        if receivers.shape != incision.values.shape or land.shape != receivers.shape:
            raise ValueError("Channel topology must match the incision grid.")
        # Both endpoints must be land; missing ground cannot become a zero floor.
        channel_diagonals(receivers, channels)  # validate receiver indices and shapes
        selected = channels & land & land.ravel()[np.maximum(receivers, 0)]
        indices = np.arange(receivers.size).reshape(receivers.shape)
        horizontal = (((receivers[:, :-1] == indices[:, 1:]) & selected[:, :-1])
                      | ((receivers[:, 1:] == indices[:, :-1]) & selected[:, 1:]))
        vertical = (((receivers[:-1] == indices[1:]) & selected[:-1])
                    | ((receivers[1:] == indices[:-1]) & selected[1:]))
        diagonals = channel_diagonals(receivers, selected)
        profiles = (None if sample_source is None else prepare_channel_profiles(
            incision, floor_m, receivers, horizontal, vertical, diagonals, sample_source))
        return cls(incision, floor_m, horizontal, vertical, diagonals, profiles)

    def refine(
        self, x: FloatArray, y: FloatArray, incision: FloatArray,
        macro: FloatArray, retained_detail: FloatArray,
    ) -> FloatArray:
        axis_x, axis_y = self.incision.x, self.incision.y
        x, y = np.clip(x, axis_x[0], axis_x[-1]), np.clip(y, axis_y[0], axis_y[-1])
        columns = np.clip(np.searchsorted(axis_x, x, side="right") - 1, 0, axis_x.size - 2)
        rows = np.clip(np.searchsorted(axis_y, y, side="right") - 1, 0, axis_y.size - 2)
        active = (self.horizontal[rows, columns] | self.horizontal[rows+1, columns]
                  | self.vertical[rows, columns] | self.vertical[rows, columns+1]
                  | (self.diagonals[rows, columns] != 0))
        if not np.any(active):
            return incision.copy()
        r, c = rows[active], columns[active]
        qx, qy = x[active], y[active]
        hx, hy = axis_x[c+1]-axis_x[c], axis_y[r+1]-axis_y[r]
        tx, ty = (qx-axis_x[c])/hx, (qy-axis_y[r])/hy
        local_macro = macro[active]
        source = local_macro + retained_detail[active]
        current = incision[active]
        correction, total, uncovered = np.zeros_like(qx), np.zeros_like(qx), np.ones_like(qx)
        # One radius shared across cell boundaries, including nonuniform grids.
        radius = .35 * min(float(np.min(np.diff(axis_x))), float(np.min(np.diff(axis_y))))
        edges = (
            (r, c, r, c+1, self.horizontal[r, c], False, 0),
            (r+1, c, r+1, c+1, self.horizontal[r+1, c], False, 0),
            (r, c, r+1, c, self.vertical[r, c], False, 1),
            (r, c+1, r+1, c+1, self.vertical[r, c+1], False, 1),
            (r, c, r+1, c+1, self.diagonals[r, c] == 1, True, 2),
            (r+1, c, r, c+1, self.diagonals[r, c] == -1, True, 3),
        )
        for row0, col0, row1, col1, selected, diagonal, direction in edges:
            if not np.any(selected):
                continue
            a, b, d, e = row0[selected], col0[selected], row1[selected], col1[selected]
            dx, dy = axis_x[e]-axis_x[b], axis_y[d]-axis_y[a]
            ox, oy = qx[selected]-axis_x[b], qy[selected]-axis_y[a]
            position = np.clip((ox*dx + oy*dy)/(dx*dx + dy*dy), 0., 1.)
            distance = np.abs(ox*dy - oy*dx)/np.hypot(dx, dy)
            across = np.clip(distance/radius, 0., 1.)
            weight = (1-across*across)**2 * smoothstep(np.minimum(position, 1-position)/.2)
            if diagonal:
                weight *= (smoothstep(np.minimum(tx[selected], 1-tx[selected])/.2)
                           * smoothstep(np.minimum(ty[selected], 1-ty[selected])/.2))
            target = self.floor_m[a, b]*(1-position) + self.floor_m[d, e]*position
            if self.profiles is not None:
                target = self.profiles.sample(direction, a, b, position, target)
            desired = np.clip(source[selected]-target, 0., local_macro[selected])
            correction[selected] += weight * (desired-current[selected])
            total[selected] += weight
            uncovered[selected] *= 1-weight
        # Smooth union coverage and a weighted mean keep overlapping corridors
        # bounded by their individual proposals, independent of query batching.
        np.divide(correction, total, out=correction, where=total > 0.)
        revised = current + (1-uncovered)*correction
        limit = self.incision.ceiling
        assert limit is not None
        top = limit[r, c]*(1-tx) + limit[r, c+1]*tx
        bottom = limit[r+1, c]*(1-tx) + limit[r+1, c+1]*tx
        result = incision.copy()
        result[active] = np.clip(revised, 0., top*(1-ty) + bottom*ty)
        return result
