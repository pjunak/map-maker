"""Coordinate-addressed deterministic noise functions."""

from math import isfinite

import numpy as np
from numpy.typing import NDArray

_UINT64_MASK = np.uint64(0xFFFFFFFFFFFFFFFF)
_X_MULTIPLIER = np.uint64(0x9E3779B185EBCA87)
_Y_MULTIPLIER = np.uint64(0xC2B2AE3D27D4EB4F)
_OCTAVE_MULTIPLIER = np.uint64(0x165667B19E3779F9)


def _fade(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return values * values * values * (values * (values * 6.0 - 15.0) + 10.0)


def _lattice_values(
    x_indices: NDArray[np.int64],
    y_indices: NDArray[np.int64],
    *,
    seed: int,
    octave: int,
) -> NDArray[np.float64]:
    """Map integer lattice coordinates to stable values in [-1, 1]."""

    x_bits = x_indices.astype(np.uint64, copy=False)
    y_bits = y_indices.astype(np.uint64, copy=False)
    # Integer mixing is modulo 2**64, including octaves that exceed uint64.
    octave_bits = np.uint64(((octave + 1) * int(_OCTAVE_MULTIPLIER)) & 0xFFFFFFFFFFFFFFFF)
    value = (
        np.uint64(seed)
        ^ (x_bits * _X_MULTIPLIER)
        ^ (y_bits * _Y_MULTIPLIER)
        ^ octave_bits
    ) & _UINT64_MASK
    value ^= value >> np.uint64(30)
    value *= np.uint64(0xBF58476D1CE4E5B9)
    value ^= value >> np.uint64(27)
    value *= np.uint64(0x94D049BB133111EB)
    value ^= value >> np.uint64(31)
    unit = (value >> np.uint64(11)).astype(np.float64) * (1.0 / float(1 << 53))
    return unit * 2.0 - 1.0


def noise_band_amplitudes(detail_levels: int, roughness: float) -> tuple[float, ...]:
    """Reserve a unit budget across the infinite geometric series of detail bands.

    Band k owns (1-r)*r**k irrespective of how many bands are evaluated. Missing
    bands keep their budget; evaluating more detail never renormalizes a prefix.
    Return the same rounded recurrence used by noise and component enclosures.
    """
    if type(detail_levels) is not int or not 1 <= detail_levels <= 12:
        raise ValueError("Noise detail levels must be an integer from 1 to 12.")
    if isinstance(roughness, bool) or not isfinite(roughness) or not 0 < roughness < 1:
        raise ValueError("Noise roughness must be finite and between zero and one.")
    weights: list[float] = []
    amplitude = 1.0 - roughness
    for _ in range(detail_levels):
        weights.append(amplitude)
        amplitude *= roughness
    return tuple(weights)


def fractal_value_noise(
    x_km: NDArray[np.float64],
    y_km: NDArray[np.float64],
    *,
    seed: int,
    largest_feature_km: float,
    detail_levels: int,
    roughness: float,
    start_band: int = 0,
) -> NDArray[np.float64]:
    """Evaluate stable multi-scale value noise at arbitrary world coordinates.

    The result depends on coordinates and settings, never on requested raster
    dimensions or evaluation order. Sampling the same coordinates at another
    resolution therefore produces exactly the same values. Each band has a fixed
    share of a unit amplitude budget, so adding bands preserves existing weights.
    The resulting terrain's nonlinear mapping/conditioning still needs separate
    parent-consistency checks. ``start_band`` selects a tail with the same
    coefficients and octave addresses; it never rescales the selected bands.
    """

    amplitudes = noise_band_amplitudes(detail_levels, roughness)
    if type(start_band) is not int or not 0 <= start_band <= detail_levels:
        raise ValueError("Noise start band must be an integer from zero through detail levels.")
    x_values = np.asarray(x_km, dtype=np.float64)
    y_values = np.asarray(y_km, dtype=np.float64)
    x_grid, y_grid = np.broadcast_arrays(x_values, y_values)
    result = np.zeros(x_grid.shape, dtype=np.float64)

    for octave in range(start_band, detail_levels):
        amplitude = amplitudes[octave]
        spacing = largest_feature_km / float(1 << octave)
        scaled_x = x_grid / spacing
        scaled_y = y_grid / spacing
        x0 = np.floor(scaled_x).astype(np.int64)
        y0 = np.floor(scaled_y).astype(np.int64)
        tx = _fade(scaled_x - x0)
        ty = _fade(scaled_y - y0)

        v00 = _lattice_values(x0, y0, seed=seed, octave=octave)
        v10 = _lattice_values(x0 + 1, y0, seed=seed, octave=octave)
        v01 = _lattice_values(x0, y0 + 1, seed=seed, octave=octave)
        v11 = _lattice_values(x0 + 1, y0 + 1, seed=seed, octave=octave)
        top = v00 + tx * (v10 - v00)
        bottom = v01 + tx * (v11 - v01)
        result += amplitude * (top + ty * (bottom - top))

    return result
