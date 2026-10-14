"""Connect selected diagonal valley samples without moving the routing network."""

from dataclasses import dataclass
from typing import Self

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.hydrology import DrainageIncision
from map_maker.terrain.pipeline.reconstruction import BoundedBicubicGrid

type FloatArray = NDArray[np.float64]


def channel_diagonals(
    receivers: NDArray[np.int64], channels: NDArray[np.bool_],
) -> NDArray[np.int8]:
    """One selected diagonal per cell; leave ambiguous crossings unmodified."""
    if receivers.ndim != 2 or receivers.shape != channels.shape:
        raise ValueError("Channel and receiver arrays must share a two-dimensional grid.")
    if np.any((receivers < -1) | (receivers >= receivers.size)):
        raise ValueError("Channel receivers must be grid indices or -1.")
    indices = np.arange(receivers.size).reshape(receivers.shape)
    down = (((receivers[:-1, :-1] == indices[1:, 1:]) & channels[:-1, :-1])
            | ((receivers[1:, 1:] == indices[:-1, :-1]) & channels[1:, 1:]))
    up = (((receivers[:-1, 1:] == indices[1:, :-1]) & channels[:-1, 1:])
          | ((receivers[1:, :-1] == indices[:-1, 1:]) & channels[1:, :-1]))
    return np.where(down == up, 0, np.where(down, 1, -1)).astype(np.int8)


def smoothstep(value: FloatArray) -> FloatArray:
    value = np.clip(value, 0., 1.)
    return value*value*(3. - 2.*value)


def _connect(
    values: FloatArray, baseline: FloatArray, rows: NDArray[np.int64],
    columns: NDArray[np.int64], down: NDArray[np.bool_],
    position: FloatArray, weight: FloatArray,
) -> FloatArray:
    first = np.where(down, values[rows, columns], values[rows + 1, columns])
    last = np.where(down, values[rows + 1, columns + 1], values[rows, columns + 1])
    target = first*(1-position) + last*position
    gap = np.maximum(target - baseline, 0.)
    softness = .01 * np.maximum(np.maximum(first, last), 1e-8)
    # Smooth positive correction: zero derivative at gap=0, never greater than gap.
    corrected = baseline + weight*gap*(gap/(gap + softness))
    return np.minimum(corrected, np.maximum(baseline, target))


@dataclass(frozen=True, slots=True)
class ChannelReconstruction:
    """Bounded valley fields with compact, metric diagonal-connection corrections.

    Corrections and their first derivatives vanish on every cell boundary. They
    increase incision/suppression only toward interpolation of the connected
    endpoint values. The existing incision ceiling still has final authority.
    """

    incision: BoundedBicubicGrid
    suppression: BoundedBicubicGrid
    diagonals: NDArray[np.int8]

    def __post_init__(self) -> None:
        if (not np.array_equal(self.incision.x, self.suppression.x)
                or not np.array_equal(self.incision.y, self.suppression.y)
                or self.diagonals.shape != (self.incision.y.size - 1, self.incision.x.size - 1)
                or not np.all(np.isin(self.diagonals, [-1, 0, 1]))):
            raise ValueError("Channel reconstruction needs matching grids and valid diagonals.")
        if (self.incision.ceiling is None or np.any(self.incision.values < 0.)
                or np.any(self.suppression.values < 0.) or np.any(self.suppression.values > 1.)):
            raise ValueError("Valleys need nonnegative cuts, a ceiling and suppression in [0,1].")
        diagonals = self.diagonals.copy()
        diagonals.flags.writeable = False
        object.__setattr__(self, "diagonals", diagonals)

    @classmethod
    def prepare(cls, x: FloatArray, y: FloatArray, routing: DrainageIncision) -> Self:
        return cls(
            BoundedBicubicGrid(x, y, routing.incision_m, routing.incision_limit_m),
            BoundedBicubicGrid(x, y, routing.detail_suppression),
            channel_diagonals(routing.receivers, routing.channel_mask),
        )

    def sample(self, x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray]:
        incision = self.incision.sample(x, y)
        suppression = self.suppression.sample(x, y)
        axis_x, axis_y = self.incision.x, self.incision.y
        x, y = np.clip(x, axis_x[0], axis_x[-1]), np.clip(y, axis_y[0], axis_y[-1])
        columns = np.clip(np.searchsorted(axis_x, x, side="right") - 1, 0, axis_x.size - 2)
        rows = np.clip(np.searchsorted(axis_y, y, side="right") - 1, 0, axis_y.size - 2)
        active = self.diagonals[rows, columns] != 0
        if not np.any(active):
            return incision, suppression
        r, c = rows[active], columns[active]
        hx, hy = axis_x[c + 1] - axis_x[c], axis_y[r + 1] - axis_y[r]
        tx, ty = (x[active] - axis_x[c])/hx, (y[active] - axis_y[r])/hy
        down = self.diagonals[r, c] == 1
        along_y = np.where(down, ty, 1-ty)
        position = (tx*hx*hx + along_y*hy*hy)/(hx*hx + hy*hy)
        distance = np.abs(tx - along_y)*hx*hy/np.hypot(hx, hy)
        across = np.clip(distance/(.35*np.minimum(hx, hy)), 0., 1.)
        # A compact corridor, tapered over the outer fifth of each cell, leaves
        # all canonical samples/edges intact, including their existing derivatives.
        weight = ((1-across*across)**2
                  * smoothstep(np.minimum(tx, 1-tx)/.2)
                  * smoothstep(np.minimum(ty, 1-ty)/.2))
        revised = _connect(self.incision.values, incision[active], r, c, down, position, weight)
        limit = self.incision.ceiling
        assert limit is not None  # required during preparation
        top = limit[r, c]*(1-tx) + limit[r, c + 1]*tx
        bottom = limit[r + 1, c]*(1-tx) + limit[r + 1, c + 1]*tx
        incision[active] = np.minimum(revised, top*(1-ty) + bottom*ty)
        suppression[active] = _connect(
            self.suppression.values, suppression[active], r, c, down, position, weight,
        )
        return incision, suppression
