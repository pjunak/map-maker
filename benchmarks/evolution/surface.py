"""Experimental ground reconstruction with explicit required drainage edges.

Selected diagonals become edges of piecewise-linear triangles. Other cells keep
bilinear interpolation. This changes the sampled surface, never a completed map.
It preserves grid heights and a declared graph, not arbitrary authored targets.
"""

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.metrics import sample_grid, terminal_labels
from benchmarks.evolution.scenarios import FloatArray, frozen
from map_maker.terrain.domain.evolution import EvolutionGrid
from map_maker.terrain.pipeline.channel_reconstruction import channel_diagonals

FLOW_SURFACE_ID = "required-d8-triangle-surface@1"


class SurfaceTopologyConflict(ValueError):
    """A required crossing cannot be represented as separate planar river beds."""

    def __init__(self, cells: NDArray[np.int64]) -> None:
        self.cells = tuple(int(v) for v in cells)
        super().__init__(f"Required river diagonals cross in {len(self.cells)} cells.")


def validate_graph(receivers: NDArray[np.int64], shape: tuple[int, int]) -> None:
    if receivers.shape != shape or receivers.dtype.kind not in "iu":
        raise ValueError("Receivers must be integer indices matching the ground grid.")
    terminal_labels(receivers)
    sources = np.flatnonzero(receivers.ravel() >= 0)
    targets = receivers.ravel()[sources]
    sy, sx = np.divmod(sources, shape[1])
    ty, tx = np.divmod(targets, shape[1])
    if np.any(np.maximum(np.abs(sy - ty), np.abs(sx - tx)) != 1):
        raise ValueError("Receiver links must connect D8 neighbours.")


@dataclass(frozen=True, slots=True)
class FlowAlignedSurface:
    grid: EvolutionGrid
    ground_m: FloatArray
    receivers: NDArray[np.int64]
    required: NDArray[np.bool_]
    diagonals: NDArray[np.int8] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            self.ground_m.shape != self.grid.shape
            or not np.all(np.isfinite(self.ground_m))
            or np.any(np.abs(self.ground_m) > np.finfo(np.float32).max)
        ):
            raise ValueError("Ground must be finite, Float32-representable and match the grid.")
        validate_graph(self.receivers, self.grid.shape)
        if self.required.shape != self.grid.shape or self.required.dtype != np.bool_:
            raise ValueError("Required edges must be a Boolean mask matching the grid.")
        if np.any(self.required & (self.receivers < 0)):
            raise ValueError("Only linked source nodes can require an edge.")
        diagonals = channel_diagonals(self.receivers, self.required)
        sources = np.flatnonzero(self.required)
        targets = self.receivers.ravel()[sources]
        sy, sx = np.divmod(sources, self.grid.shape[1])
        ty, tx = np.divmod(targets, self.grid.shape[1])
        diagonal = (sy != ty) & (sx != tx)
        cells = np.unique(
            np.minimum(sy[diagonal], ty[diagonal]) * (self.grid.shape[1] - 1)
            + np.minimum(sx[diagonal], tx[diagonal])
        )
        conflicts = cells[diagonals.ravel()[cells] == 0]
        if conflicts.size:
            raise SurfaceTopologyConflict(conflicts)
        object.__setattr__(self, "ground_m", frozen(self.ground_m))
        for name, original in (
            ("receivers", self.receivers),
            ("required", self.required),
            ("diagonals", diagonals),
        ):
            owned = original.copy()
            owned.flags.writeable = False
            object.__setattr__(self, name, owned)

    def bilinear(self, x_m: FloatArray, y_m: FloatArray) -> NDArray[np.float32]:
        return sample_grid(self.ground_m, self.grid, x_m, y_m)

    def sample(self, x_m: FloatArray, y_m: FloatArray) -> NDArray[np.float32]:
        x, y = np.broadcast_arrays(x_m / self.grid.spacing_m, y_m / self.grid.spacing_m)
        if (
            not np.all(np.isfinite(x))
            or not np.all(np.isfinite(y))
            or np.any(x < 0)
            or np.any(y < 0)
            or np.any(x > self.grid.shape[1] - 1)
            or np.any(y > self.grid.shape[0] - 1)
        ):
            raise ValueError("Surface samples must lie inside the process grid.")
        c = np.minimum(x.astype(np.int64), self.grid.shape[1] - 2)
        r = np.minimum(y.astype(np.int64), self.grid.shape[0] - 2)
        u, v = x - c, y - r
        a, b = self.ground_m[r, c], self.ground_m[r, c + 1]
        d, e = self.ground_m[r + 1, c], self.ground_m[r + 1, c + 1]
        # Barycentric weights are nonnegative and sum to one in each triangle.
        # Along its required diagonal, this is exactly the endpoint line in
        # real arithmetic. No carved floor, new random field or range clamp.
        down = np.where(
            u >= v, (1 - u) * a + (u - v) * b + v * e, (1 - v) * a + (v - u) * d + u * e
        )
        up = np.where(
            u + v <= 1, (1 - u - v) * a + u * b + v * d, (1 - v) * b + (1 - u) * d + (u + v - 1) * e
        )
        bilinear = (1 - v) * ((1 - u) * a + u * b) + v * ((1 - u) * d + u * e)
        value = np.where(
            self.diagonals[r, c] == 1, down, np.where(self.diagonals[r, c] == -1, up, bilinear)
        )
        return np.asarray(value, dtype=np.float32)

    def composition(self) -> dict[str, float | int | str]:
        """Exact unquantized geometric integral over the full bounding rectangle.

        This is a reconstruction difference, not erosion or the solver's interior
        control-volume ledger. The latter has a different boundary-area policy.
        """
        z = self.ground_m
        twist = z[:-1, :-1] + z[1:, 1:] - z[:-1, 1:] - z[1:, :-1]
        delta = self.diagonals * twist / 12.0
        area = self.grid.spacing_m**2
        return {
            "triangulated_cells": int(np.count_nonzero(self.diagonals)),
            "signed_volume_change_m3": float(np.sum(delta) * area),
            "absolute_volume_change_m3": float(np.sum(np.abs(delta)) * area),
            "mean_height_change_m": float(np.mean(delta)),
            "maximum_absolute_point_change_bound_m": float(
                np.max(np.where(self.diagonals != 0, np.abs(twist) / 4.0, 0.0))
            ),
            "integral_domain": "full rectangle, not the solver's core-node control area",
            "integral_precision": "Float64 geometric integral before output quantization",
        }
