"""Research-only projection of finer terrain onto fixed parent-cell moments.

The all-land experiment preserves bilinear parent edges and trapezoidal cell
means. It has no authored-constraint, coastline, lake or drainage acceptance.
"""

from dataclasses import dataclass
from math import isfinite

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain.regional import REGIONAL_SAMPLE_LIMIT

PARENT_CELL_METHOD_ID = "parent-cell-bubble-projection@1"
PARENT_RESTRICTION_ID = "endpoint-bilinear-trapezoid@1"
MAX_CELL_REFINEMENT = 64

type FloatGrid = NDArray[np.float32] | NDArray[np.float64]


def _factor(value: int) -> None:
    if type(value) is not int or not 4 <= value <= MAX_CELL_REFINEMENT or value & (value - 1):
        raise ValueError("Parent-cell refinement must be a power of two from 4 through 64.")


def _finite_grid(values: FloatGrid) -> None:
    if (values.ndim != 2 or min(values.shape) < 2 or values.size > REGIONAL_SAMPLE_LIMIT
            or values.dtype not in (np.dtype("float32"), np.dtype("float64"))
            or not np.isfinite(values).all()
            or np.any(np.abs(values) > np.finfo(np.float32).max)):
        raise ValueError(
            "Parent-cell grids need finite Float32-range values within the sample limit.")


def restrict_cell_means(values: FloatGrid, refinement: int) -> NDArray[np.float64]:
    """Average bilinear fine cells over complete uniform-grid parent cells.

    Trapezoidal quadrature is applied to node elevations. This is not a pixel
    mean, centre sample, solid-volume budget, or treatment of partial land cells.
    """
    _factor(refinement)
    _finite_grid(values)
    height, width = values.shape
    if (height - 1) % refinement or (width - 1) % refinement:
        raise ValueError("Restriction needs complete parent-cell intervals.")
    z = values.astype(np.float64)
    quads = .25 * (z[:-1, :-1] + z[1:, :-1] + z[:-1, 1:] + z[1:, 1:])
    return quads.reshape((height - 1) // refinement, refinement,
                         (width - 1) // refinement, refinement).mean(axis=(1, 3))


def parent_cell_means(parent: FloatGrid) -> NDArray[np.float64]:
    """The parent owns node heights; bilinear reconstruction defines its means."""
    _finite_grid(parent)
    z = parent.astype(np.float64)
    return .25 * (z[:-1, :-1] + z[1:, :-1] + z[:-1, 1:] + z[1:, 1:])


def _bilinear(corners: NDArray[np.float64], t: NDArray[np.float64]) -> NDArray[np.float64]:
    a, b, c, d = corners.ravel()
    top, bottom = a + (b-a)*t, c + (d-c)*t
    base = top[None, :] + (bottom-top)[None, :]*t[:, None]
    # Evaluate a shared edge in the same direction from either adjacent cell.
    base[0], base[-1] = top, bottom
    base[:, 0], base[:, -1] = a + (c-a)*t, b + (d-b)*t
    base[0, 0], base[0, -1], base[-1, 0], base[-1, -1] = a, b, c, d
    return base


def interpolate_parent(parent_m: NDArray[np.float32], refinement: int) -> NDArray[np.float32]:
    """Magnify a finite all-land parent with its explicitly chosen bilinear reference."""
    _factor(refinement)
    _finite_grid(parent_m)
    if parent_m.dtype != np.float32:
        raise ValueError("Authoritative parent heights must be Float32.")
    shape = tuple((n-1)*refinement+1 for n in parent_m.shape)
    if shape[0]*shape[1] > REGIONAL_SAMPLE_LIMIT:
        raise ValueError("Interpolated parent exceeds the sample limit.")
    result = np.empty(shape, dtype=np.float32)
    t = np.arange(refinement+1, dtype=np.float64)/refinement
    parent = parent_m.astype(np.float64)
    for row, col in np.ndindex(parent.shape[0]-1, parent.shape[1]-1):
        result[row*refinement:(row+1)*refinement+1, col*refinement:(col+1)*refinement+1] = (
            _bilinear(parent[row:row+2, col:col+2], t).astype(np.float32))
    result.setflags(write=False)
    return result


@dataclass(frozen=True, slots=True)
class ParentCellProjection:
    """Owned, read-only diagnostic result; no complete-child validity is implied."""

    elevation_m: NDArray[np.float32]
    detail_scale: NDArray[np.float64]
    weighted_bias_m: NDArray[np.float64]
    maximum_cell_mean_error_m: float
    quantization_tolerance_m: float


def project_parent_cells(
    parent_m: NDArray[np.float32], proposal_m: FloatGrid, refinement: int,
    *, maximum_elevation_m: float,
) -> ParentCellProjection:
    """Condition whole parent cells independently with an interior bubble.

    Given bilinear parent B, proposed ground P and bubble w, set
    D=w*((P-B)-sum(w*(P-B))/sum(w)). Its trapezoidal mean is zero because
    w vanishes on the cell boundary. A single scale per cell keeps B+scale*D
    within [0, ceiling] without clipping individual nodes or changing the mean.
    Final Float32 conversion allows an explicitly checked rounding tolerance.

    The quadrature is tied to refinement. This candidate must be compared at
    different densities before adopting it as a pointwise enrichment field.
    """
    _factor(refinement)
    _finite_grid(parent_m)
    _finite_grid(proposal_m)
    if parent_m.dtype != np.float32:
        raise ValueError("Authoritative parent heights must be Float32.")
    if (isinstance(maximum_elevation_m, bool) or not isfinite(maximum_elevation_m)
            or not 0 < maximum_elevation_m <= np.finfo(np.float32).max / 2):
        raise ValueError("Parent-cell ceiling must be finite, positive and within Float32 range.")
    expected = tuple((size - 1)*refinement + 1 for size in parent_m.shape)
    if proposal_m.shape != expected:
        raise ValueError("Proposal grid must subdivide every supplied parent interval.")
    if np.any(parent_m < 0) or np.any(parent_m.astype(np.float64) > maximum_elevation_m):
        raise ValueError("Parent ground must lie between zero and the elevation ceiling.")
    # Use an inward representable limit, so Float32 conversion cannot cross it.
    limit = np.float32(maximum_elevation_m)
    if float(limit) > maximum_elevation_m:
        limit = np.nextafter(limit, np.float32(-np.inf))
    parent = parent_m.astype(np.float64)
    result = np.empty(expected, dtype=np.float32)
    shape = (parent.shape[0] - 1, parent.shape[1] - 1)
    scales, biases = np.ones(shape), np.zeros(shape)
    t = np.arange(refinement + 1, dtype=np.float64) / refinement
    bubble = 16*t*t*(1-t)*(1-t)
    weight = bubble[:, None]*bubble[None, :]
    total = float(weight.sum())
    for row, column in np.ndindex(shape):
        ys = slice(row*refinement, (row+1)*refinement+1)
        xs = slice(column*refinement, (column+1)*refinement+1)
        base = _bilinear(parent[row:row+2, column:column+2], t)
        raw = proposal_m[ys, xs].astype(np.float64) - base
        bias = float(np.sum(weight*raw) / total)
        residual = weight*(raw-bias)
        # Whole-cell attenuation preserves the zero moment and edge pins. It
        # can discard a cell's detail entirely; a clipped result cannot do this.
        margins = np.where(residual > 0, float(limit)-base, base)
        allowed = np.divide(margins, np.abs(residual), out=np.ones_like(base),
                            where=residual != 0)
        scale = min(1., max(0., float(allowed.min())))
        if scale < 1:
            scale = float(np.nextafter(scale, 0.))
        result[ys, xs] = (base + scale*residual).astype(np.float32)
        scales[row, column], biases[row, column] = scale, bias
    error = float(np.max(np.abs(restrict_cell_means(result, refinement)-parent_cell_means(parent))))
    tolerance = float(2*np.finfo(np.float32).eps*max(1., maximum_elevation_m))
    if (not np.array_equal(result[::refinement, ::refinement], parent_m)
            or not np.isfinite(result).all() or np.any(result < 0) or np.any(result > limit)
            or error > tolerance):
        raise RuntimeError("Parent-cell projection exceeded its preservation or rounding bounds.")
    for array in (result, scales, biases):
        array.setflags(write=False)
    return ParentCellProjection(result, scales, biases, error, tolerance)
