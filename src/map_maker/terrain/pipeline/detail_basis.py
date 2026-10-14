"""Shared-edge, zero-cell-mean residuals on an unchanged prepared parent field."""

from hashlib import sha256

import numpy as np
from numpy.typing import NDArray


def edge_coefficients(
    columns: NDArray[np.int64], rows: NDArray[np.int64], seed: int,
) -> NDArray[np.float64]:
    """Left/right/top/bottom edges share keys across cells, windows and densities."""
    coefficients = np.empty((columns.size, 4, 2), dtype=np.float64)
    for i, (column, row) in enumerate(zip(columns.flat, rows.flat, strict=True)):
        for edge, (axis, c, r) in enumerate((
            (0, column, row), (0, column + 1, row),
            (1, column, row), (1, column, row + 1),
        )):
            payload = (b"dmtools.local-detail-edge@1\0" + seed.to_bytes(4, "big")
                       + bytes([axis]) + int(c).to_bytes(8, "big") + int(r).to_bytes(8, "big"))
            digest = sha256(payload).digest()
            for mode in range(2):
                unit = int.from_bytes(digest[mode * 4:mode * 4 + 4], "big") / 0xFFFFFFFF
                coefficients[i, edge, mode] = unit - 0.5
    return coefficients


def edge_wave(t: NDArray[np.float64], coefficients: NDArray[np.float64]) -> NDArray[np.float64]:
    """Two unit-bounded modes: zero integral and zero endpoint values/derivatives.

    The even mode removes the forced midpoint zero of the odd mode. Both have
    exact zero composite-trapezoid sums at the fixed 16-interval probe density
    in real arithmetic. Neither the phase nor normalization uses output samples.
    """
    bubble = np.sin(np.pi * t) ** 4
    odd = (np.sqrt(6) / 2) * (6 / 5) ** 2.5 * bubble * np.sin(2 * np.pi * t)
    even = bubble * (2 + 3 * np.cos(2 * np.pi * t))
    values = coefficients[..., 0] * odd + coefficients[..., 1] * even
    return np.where((t == 0) | (t == 1), 0.0, values)


def residual_basis(
    u: NDArray[np.float64], v: NDArray[np.float64],
    coefficients: NDArray[np.float64], edge_amplitudes_m: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Blend shared edges through the cell; do not force its interior edges to zero.

    Each summand integrates to zero along its tangential axis. The quintic normal
    weights have zero first/second derivatives at both ends; neighbors meet C2 in
    real arithmetic. Quantized output secants still require separate measurement.
    """
    hu = u**3 * (10 + u * (-15 + 6 * u))
    hv = v**3 * (10 + v * (-15 + 6 * v))
    left = edge_wave(v, coefficients[..., 0, :]) * edge_amplitudes_m[..., 0]
    right = edge_wave(v, coefficients[..., 1, :]) * edge_amplitudes_m[..., 1]
    top = edge_wave(u, coefficients[..., 2, :]) * edge_amplitudes_m[..., 2]
    bottom = edge_wave(u, coefficients[..., 3, :]) * edge_amplitudes_m[..., 3]
    # Each axis is a convex blend. Edge orientation weights are <= 3/4;
    # 2/3 bounds their combined contribution by the cell's own height budget.
    return (2 / 3) * ((1 - hu) * left + hu * right + (1 - hv) * top + hv * bottom)


def terrain_x_weight(reference: NDArray[np.float32], dx: float, dy: float) -> NDArray[np.float64]:
    """Terrain-gradient energy biases the two axes; flat cells remain isotropic.

    The input is a fixed probe lattice, with physical spacing in km. This is a
    bounded cardinal-direction preference, not an obliquely oriented ridge model.
    """
    z = reference.astype(np.float64)
    gx = (z[:, 1:-1, 2:] - z[:, 1:-1, :-2]) / (2 * dx)
    gy = (z[:, 2:, 1:-1] - z[:, :-2, 1:-1]) / (2 * dy)
    ex, ey = np.mean(gx * gx, axis=(1, 2)), np.mean(gy * gy, axis=(1, 2))
    fraction = np.divide(ex, ex + ey, out=np.full_like(ex, 0.5), where=ex + ey > 0)
    return 0.25 + 0.5 * fraction
