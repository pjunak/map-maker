"""Shape-preserving profiles for authored structures and generated terrain."""

import numpy as np
from numpy.typing import NDArray


def _endpoint_slope(
    first_span: float,
    second_span: float,
    first_gradient: float,
    second_gradient: float,
) -> float:
    """Return a shape-preserving PCHIP endpoint derivative."""

    slope = (
        (2.0 * first_span + second_span) * first_gradient
        - first_span * second_gradient
    ) / (first_span + second_span)
    if np.sign(slope) != np.sign(first_gradient):
        return 0.0
    if np.sign(first_gradient) != np.sign(second_gradient) and abs(slope) > abs(
        3.0 * first_gradient
    ):
        return 3.0 * first_gradient
    return float(slope)


def shape_preserving_profile(
    positions_km: NDArray[np.float64],
    elevations_m: NDArray[np.float64],
    queries_km: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Evaluate a monotone piecewise cubic without overshooting its knots."""

    count = len(positions_km)
    if count < 2:
        raise ValueError("A structure profile needs at least two positions.")
    spans = np.diff(positions_km)
    if np.any(spans <= 0.0):
        raise ValueError("Structure profile positions must increase.")
    gradients = np.diff(elevations_m) / spans
    slopes = np.zeros_like(elevations_m)
    if count == 2:
        slopes[:] = gradients[0]
    else:
        slopes[0] = _endpoint_slope(
            float(spans[0]),
            float(spans[1]),
            float(gradients[0]),
            float(gradients[1]),
        )
        slopes[-1] = _endpoint_slope(
            float(spans[-1]),
            float(spans[-2]),
            float(gradients[-1]),
            float(gradients[-2]),
        )
        for index in range(1, count - 1):
            before = float(gradients[index - 1])
            after = float(gradients[index])
            if before == 0.0 or after == 0.0 or np.sign(before) != np.sign(after):
                slopes[index] = 0.0
                continue
            before_weight = 2.0 * spans[index] + spans[index - 1]
            after_weight = spans[index] + 2.0 * spans[index - 1]
            slopes[index] = (before_weight + after_weight) / (
                before_weight / before + after_weight / after
            )

    flat_queries = queries_km.reshape(-1)
    segment_indices = np.searchsorted(positions_km, flat_queries, side="right") - 1
    segment_indices = np.clip(segment_indices, 0, count - 2)
    left_positions = positions_km[segment_indices]
    segment_spans = spans[segment_indices]
    progress = (flat_queries - left_positions) / segment_spans
    progress_squared = progress * progress
    progress_cubed = progress_squared * progress
    left_basis = 2.0 * progress_cubed - 3.0 * progress_squared + 1.0
    left_slope_basis = progress_cubed - 2.0 * progress_squared + progress
    right_basis = -2.0 * progress_cubed + 3.0 * progress_squared
    right_slope_basis = progress_cubed - progress_squared
    result = (
        left_basis * elevations_m[segment_indices]
        + left_slope_basis * segment_spans * slopes[segment_indices]
        + right_basis * elevations_m[segment_indices + 1]
        + right_slope_basis * segment_spans * slopes[segment_indices + 1]
    )
    return result.reshape(queries_km.shape)


type FloatArray = NDArray[np.float64]


def monotone_grid_slopes(values: FloatArray, positions: FloatArray, axis: int) -> FloatArray:
    """Shared PCHIP derivatives for rows or columns of a two-dimensional field."""
    data = np.moveaxis(values, axis, 0)
    spans = np.diff(positions).reshape((-1, 1))
    gradients = np.diff(data, axis=0) / spans
    slopes = np.zeros_like(data)
    if data.shape[0] == 2:
        slopes[:] = gradients[0]
    else:
        before, after = gradients[:-1], gradients[1:]
        same_sign = (np.sign(before) == np.sign(after)) & (before != 0) & (after != 0)
        # Fritsch-Butland harmonic slopes, evaluated without dividing by zero.
        w1, w2 = 2 * spans[1:] + spans[:-1], spans[1:] + 2 * spans[:-1]
        numerator = (w1 + w2) * before * after
        denominator = w1 * after + w2 * before
        np.divide(numerator, denominator, out=slopes[1:-1], where=same_sign)
        for index, first, second, h0, h1 in (
            (0, gradients[0], gradients[1], spans[0], spans[1]),
            (-1, gradients[-1], gradients[-2], spans[-1], spans[-2]),
        ):
            end = ((2 * h0 + h1) * first - h0 * second) / (h0 + h1)
            end = np.where(np.sign(end) == np.sign(first), end, 0.)
            slopes[index] = np.sign(end) * np.minimum(np.abs(end), 3 * np.abs(first))
    return np.moveaxis(slopes, 0, axis)
