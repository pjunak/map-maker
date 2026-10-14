"""Numeric diagnostics for experimental detail; no cartographic acceptance thresholds."""

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.pipeline.detail import DetailedRegion


def _power(values: NDArray[np.float64], factor: int) -> tuple[float, float]:
    # Drop duplicate final endpoint, remove DC, and taper the finite crop.
    a = values[:-1, :-1]
    taper = np.hanning(a.shape[0])[:, None] * np.hanning(a.shape[1])[None, :]
    spectrum = np.abs(np.fft.fft2((a - a.mean()) * taper)) ** 2
    fy = np.fft.fftfreq(a.shape[0], d=1 / factor)[:, None]
    fx = np.fft.fftfreq(a.shape[1], d=1 / factor)[None, :]
    coarse = (fx * fx + fy * fy <= 0.5**2) & ((fx != 0) | (fy != 0))
    return float(spectrum.sum()), float(spectrum[coarse].sum())


def measure_detail(detail: DetailedRegion) -> dict[str, float | None]:
    """Compare delivered Float32 fields on whole-cell windows with no output halo."""
    request = detail.samples.request
    factor = request.refinement
    if request.halo_cells or any(value % factor for value in request.window):
        raise ValueError("Detail metrics require whole parent cells and no output halo.")
    reference = np.nan_to_num(detail.reference_elevation_m.astype(np.float64))
    ground = np.nan_to_num(detail.samples.elevation_m.astype(np.float64))
    added = ground - reference
    yy, xx = np.indices(added.shape)
    edges = ((xx % factor == 0) | (yy % factor == 0))
    edges &= ~((xx % factor == 0) & (yy % factor == 0))
    interior = (xx % factor != 0) & (yy % factor != 0)
    edge_rms = float(np.sqrt(np.mean(added[edges] ** 2)))
    interior_rms = float(np.sqrt(np.mean(added[interior] ** 2)))
    slopes: list[NDArray[np.float64]] = []
    for axis, coordinates in ((1, detail.samples.x_km), (0, detail.samples.y_km)):
        oriented = added if axis == 1 else added.T
        indices: NDArray[np.int64] = np.arange(factor, oriented.shape[1] - 1, factor,
                                                dtype=np.int64)
        left = (oriented[:, indices] - oriented[:, indices - 1]) / (
            coordinates[indices] - coordinates[indices - 1])
        right = (oriented[:, indices + 1] - oriented[:, indices]) / (
            coordinates[indices + 1] - coordinates[indices])
        slopes.append(np.abs(right - left).ravel())
    jumps = np.concatenate(slopes)
    total, coarse = _power(added, factor)
    _total_reference, coarse_reference = _power(reference, factor)
    _total_ground, coarse_ground = _power(ground, factor)
    return {
        "edge_rms_m": edge_rms,
        "interior_rms_m": interior_rms,
        "edge_to_interior_rms": edge_rms / interior_rms if interior_rms else None,
        "added_coarse_power_fraction": coarse / total if total else None,
        "coarse_ground_power_change_fraction": (
            coarse_ground / coarse_reference - 1 if coarse_reference else None),
        "maximum_added_edge_secant_jump_m_per_km": float(jumps.max(initial=0)),
        "p95_added_edge_secant_jump_m_per_km": float(np.percentile(jumps, 95)),
        "maximum_outer_crop_added_height_m": float(np.max(np.abs(np.concatenate((
            added[0, :], added[-1, :], added[:, 0], added[:, -1]))))),
    }
