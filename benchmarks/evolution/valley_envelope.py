"""One-sided bilinear capacities for a rectangular divide's smooth cut limit.

This is a research delivery component, not a terrain-generation stage. The
cell-interior proof and limits are recorded in the accompanying research note.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.paths import FloatArray
from map_maker.terrain.domain.evolution import EvolutionGrid

ENVELOPE_MODEL_ID = "curvature-bounded-bilinear-cap@1"
CORNERS = (
    (slice(None, -1), slice(None, -1)),
    (slice(1, None), slice(None, -1)),
    (slice(None, -1), slice(1, None)),
    (slice(1, None), slice(1, None)),
)


def rectangle_cap(
    x: FloatArray,
    y: FloatArray,
    bounds_m: tuple[float, float, float, float],
    limit_m: float,
    transition_m: float,
) -> FloatArray:
    x0, y0, x1, y1 = bounds_m
    dx = np.maximum(np.maximum(x0 - x, x - x1), 0.0)
    dy = np.maximum(np.maximum(y0 - y, y - y1), 0.0)
    q = np.minimum(np.hypot(dx, dy) / transition_m, 1.0)
    return limit_m * q * q * (3.0 - 2.0 * q)


@dataclass(frozen=True, slots=True)
class CellEnvelope:
    capacities_m: FloatArray
    cell_error_m: FloatArray
    constant_cells: NDArray[np.bool_]

    def __post_init__(self) -> None:
        for name in ("capacities_m", "cell_error_m", "constant_cells"):
            value = getattr(self, name).copy()
            value.flags.writeable = False
            object.__setattr__(self, name, value)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "model_id": ENVELOPE_MODEL_ID,
            "cell_count": self.cell_error_m.size,
            "constant_cell_count": int(np.count_nonzero(self.constant_cells)),
            "maximum_interpolation_allowance_m": float(self.cell_error_m.max()),
            "interior_bound": "one-sided curvature allowance; constant on inadmissible cells",
        }


def cell_safe_capacities(
    grid: EvolutionGrid,
    bounds_m: tuple[float, float, float, float],
    *,
    limit_m: float,
    transition_m: float,
) -> CellEnvelope:
    if (
        len(bounds_m) != 4
        or not all(isfinite(v) for v in bounds_m)
        or bounds_m[0] >= bounds_m[2]
        or bounds_m[1] >= bounds_m[3]
        or any(isinstance(v, bool) or not isfinite(v) or v <= 0 for v in (limit_m, transition_m))
    ):
        raise ValueError("Envelope requires a finite rectangle and positive physical scales.")
    if grid.shape[0] * grid.shape[1] > 16384:
        raise ValueError("Envelope construction is limited to 16,384 process nodes.")
    step = grid.spacing_m
    y, x = np.indices(grid.shape, dtype=np.float64) * step
    nodal = rectangle_cap(x, y, bounds_m, limit_m, transition_m)
    cx, cy = x[:-1, :-1], y[:-1, :-1]
    x0, y0, x1, y1 = bounds_m
    dx = np.maximum(np.maximum(x0 - cx - step, cx - x1), 0.0)
    dy = np.maximum(np.maximum(y0 - cy - step, cy - y1), 0.0)
    q = np.minimum(np.hypot(dx, dy) / transition_m, 1.0)
    inside_x = (cx >= x0) & (cx + step <= x1)
    inside_y = (cy >= y0) & (cy + step <= y1)
    # The positive radial/tangential curvature bounds, divided by 6L/R^2,
    # are max(1-2q, 0) and max(1-q, 0). Inside a coordinate slab that
    # coordinate is constant; if the other slab contains the cell, use the
    # sharper one-dimensional radial bound. They hold across the C1 joins.
    bx = np.where(inside_x, 0.0, np.maximum(1 - np.where(inside_y, 2.0, 1.0) * q, 0.0))
    by = np.where(inside_y, 0.0, np.maximum(1 - np.where(inside_x, 2.0, 1.0) * q, 0.0))
    with np.errstate(over="ignore", invalid="ignore"):
        error = (0.75 * limit_m) * np.square(np.float64(step) / transition_m) * (bx + by)
    if not np.all(np.isfinite(error)) or not np.all(np.isfinite(nodal)):
        raise ValueError("Envelope physical scales exceed finite numeric bounds.")
    # Subtract E >= h^2 (sup C_xx+ + sup C_yy+) / 8 at all four corners.
    # If any resulting capacity is negative, do NOT clip it to zero: that
    # raises the interpolant and destroys the proof near a quadratic zero.
    # A constant equal to the cell's true minimum is safe instead.
    constant_cells: NDArray[np.bool_] = np.minimum.reduce([nodal[s] for s in CORNERS]) < error
    constant = limit_m * q * q * (3.0 - 2.0 * q)
    capacities = nodal.copy()
    for corner in CORNERS:
        candidate = np.asarray(nodal[corner], dtype=np.float64) - error
        candidate[constant_cells] = constant[constant_cells]
        capacities[corner] = np.minimum(capacities[corner], candidate)
    return CellEnvelope(capacities, error, constant_cells)


def audit_capacities(
    grid: EvolutionGrid,
    capacities_m: FloatArray,
    bounds_m: tuple[float, float, float, float],
    *,
    limit_m: float,
    transition_m: float,
) -> dict[str, Any]:
    """Independent dense sampling evidence, not a replacement for the bound proof."""
    if (
        capacities_m.shape != grid.shape
        or not np.all(np.isfinite(capacities_m))
        or np.any(capacities_m < 0)
        or capacities_m.size > 16384
    ):
        raise ValueError("Capacity audit requires a bounded finite nonnegative grid.")
    # Include very near boundary samples: endpoint/midpoint checks miss the
    # linear-cut versus quadratic-cap failure beside a protected footprint.
    fractions = np.unique(np.r_[np.linspace(0.0, 1.0, 17), 1e-8, 1 - 1e-8])
    y, x = np.indices((grid.shape[0] - 1, grid.shape[1] - 1), dtype=np.float64)
    x, y = x * grid.spacing_m, y * grid.spacing_m
    a, b, c, d = (capacities_m[s] for s in CORNERS)
    worst, violations = 0.0, 0
    for u in fractions:
        for v in fractions:
            interpolated = (1 - u) * (1 - v) * a + (1 - u) * v * b + u * (1 - v) * c + u * v * d
            exact = rectangle_cap(
                x + u * grid.spacing_m,
                y + v * grid.spacing_m,
                bounds_m,
                limit_m,
                transition_m,
            )
            excess = interpolated - exact
            worst = max(worst, float(excess.max()))
            violations += int(np.count_nonzero(excess > 1e-9))
    return {
        "sample_count": x.size * len(fractions) ** 2,
        "fractions_per_axis": len(fractions),
        "violation_count": violations,
        "maximum_excess_m": worst,
        "roundoff_tolerance_m": 1e-9,
        "scope": "Float64 bilinear capacities; sample guard supplements analytic bound",
    }
