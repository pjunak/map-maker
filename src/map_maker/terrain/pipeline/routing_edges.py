"""Finite mountain-crest probes for the canonical drainage graph."""

from collections.abc import Callable
from math import sqrt

import numpy as np
import shapely
from numpy.typing import NDArray

from map_maker.terrain.domain import LandformSettings
from map_maker.terrain.domain.seeds import LANDFORM_STAGE_ID, stage_seed
from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS
from map_maker.terrain.pipeline.landforms import MetricRegion, regional_noise_basis

type FloatArray = NDArray[np.float64]
type IndexArray = NDArray[np.int64]
type MacroSampler = Callable[[FloatArray, FloatArray], FloatArray]


def _crest_locations(
    x0: FloatArray, y0: FloatArray, x1: FloatArray, y1: FloatArray,
    first: FloatArray, last: FloatArray, controls: LandformSettings, seed: int,
) -> tuple[NDArray[np.bool_], IndexArray, FloatArray]:
    """Refine observed zero brackets and same-sign local minima of |carrier|.

    Fixed work limits keep allocation independent of feature scale. The nine
    stations can miss several extrema in one interval; refinement is evidence,
    not a root-isolation or complete blended-height certificate.
    """
    fractions = np.arange(1, 8, dtype=np.float64)[None, :]/8.
    _, _, interior = regional_noise_basis(
        x0[:, None]*(1-fractions) + x1[:, None]*fractions,
        y0[:, None]*(1-fractions) + y1[:, None]*fractions, controls, seed)
    carrier = np.column_stack((first, interior, last))
    signs = np.signbit(carrier)
    crossings = ((signs[:, :-1] != signs[:, 1:])
                 & (carrier[:, :-1] != 0.) & (carrier[:, 1:] != 0.))
    absolute = np.abs(carrier)
    minima = ((absolute[:, 1:-1] < absolute[:, :-2])
              & (absolute[:, 1:-1] <= absolute[:, 2:])
              & (absolute[:, 1:-1] > 0.)
              & (signs[:, :-2] == signs[:, 1:-1])
              & (signs[:, 1:-1] == signs[:, 2:]))
    observed = (np.any(crossings, axis=1) | np.any(carrier == 0., axis=1)
                | np.any(minima, axis=1))

    def evaluate(edge: IndexArray, t: FloatArray) -> FloatArray:
        _, _, value = regional_noise_basis(
            x0[edge]*(1-t) + x1[edge]*t, y0[edge]*(1-t) + y1[edge]*t,
            controls, seed)
        return value

    roots, columns = np.nonzero(crossings)
    lo, hi = columns/8., (columns+1)/8.
    left_sign = signs[roots, columns]
    # Every observed sign change receives the same twelve complete rounds.
    if roots.size:
        for _ in range(12):
            mid = (lo+hi)*.5
            value = evaluate(roots, mid)
            same = np.signbit(value) == left_sign
            lo = np.where(same | (value == 0.), mid, lo)
            hi = np.where(~same | (value == 0.), mid, hi)
    root_positions = (lo+hi)*.5

    dips, columns = np.nonzero(minima)
    lo, hi = columns/8., (columns+2)/8.
    # Same-sign approaches can be tangent crests or hide paired crossings.
    # Retain the best observation; unimodality and full-field maxima are unproven.
    if dips.size:
        ratio = (sqrt(5.)-1.)/2.
        left, right = hi-ratio*(hi-lo), lo+ratio*(hi-lo)
        left_value, right_value = np.abs(evaluate(dips, left)), np.abs(evaluate(dips, right))
        best = (columns+1)/8.
        best_value = absolute[dips, columns+1].copy()
        for _ in range(16):
            for position, value in ((left, left_value), (right, right_value)):
                better = value < best_value
                best = np.where(better, position, best)
                best_value = np.minimum(best_value, value)
            keep_left = left_value <= right_value
            lo, hi = np.where(keep_left, lo, left), np.where(keep_left, right, hi)
            retained_position = np.where(keep_left, left, right)
            retained_value = np.where(keep_left, left_value, right_value)
            fresh = np.where(keep_left, hi-ratio*(hi-lo), lo+ratio*(hi-lo))
            fresh_value = np.abs(evaluate(dips, fresh))
            left, right = (np.where(keep_left, fresh, retained_position),
                           np.where(keep_left, retained_position, fresh))
            left_value, right_value = (np.where(keep_left, fresh_value, retained_value),
                                       np.where(keep_left, retained_value, fresh_value))
        # Include the final new evaluation as well as every preceding round.
        for position, value in ((left, left_value), (right, right_value)):
            better = value < best_value
            best = np.where(better, position, best)
            best_value = np.minimum(best_value, value)
    else:
        best = np.empty(0, dtype=np.float64)
    return observed, np.concatenate((roots, dips)), np.concatenate((root_positions, best))


def _sample_peaks(sample_macro: MacroSampler, x: FloatArray, y: FloatArray) -> FloatArray:
    samples = sample_macro(x, y)
    if samples.shape != x.shape or not np.all(np.isfinite(samples)):
        raise ValueError("Crest sampler returned non-finite heights or the wrong shape.")
    return np.max(samples, axis=1)


def sample_mountain_barriers(
    x: FloatArray, y: FloatArray, elevation_m: FloatArray, land: NDArray[np.bool_],
    regions: tuple[MetricRegion, ...], master_seed: int, sample_macro: MacroSampler,
    *, batch_edges: int = 4096,
) -> FloatArray | None:
    """Observe refined carrier crests plus seven regular interiors per selected edge.

    A source-scale variation screen admits same-sign endpoint pairs. Cheap
    carrier probes refine observed crossings and tangent approaches before
    evaluating the full authored macro. Other extrema remain uncertified.
    Opposite D8 directions share exactly the same sampled barrier.
    """
    if (x.ndim != 1 or y.ndim != 1 or min(x.size, y.size) < 2
            or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))
            or np.any(np.diff(x) <= 0.) or np.any(np.diff(y) <= 0.)
            or elevation_m.shape != (y.size, x.size) or land.shape != elevation_m.shape
            or np.any(~np.isfinite(elevation_m[land])) or not 1 <= batch_edges <= 4096):
        raise ValueError("Crest sampling needs finite axes, a shared grid and bounded batches.")
    mountains = tuple(region for region in regions
                      if region.settings.character == "mountains"
                      and region.settings.relief_m > 0.)
    if not mountains or not np.any(land):
        return None
    xx, yy = np.meshgrid(x, y)
    radius = float(np.hypot(np.max(np.diff(x)), np.max(np.diff(y))))
    ny, nx = land.shape
    candidates = np.zeros((4, ny, nx), dtype=np.bool_)
    barriers = np.full((8, ny, nx), np.inf)
    for index in range(4, 8):
        dy, dx = D8_NEIGHBOURS[index]
        source = (slice(0, ny-dy), slice(max(0, -dx), nx-max(0, dx)))
        target = (slice(dy, ny), slice(max(0, dx), nx-max(0, -dx)))
        endpoints = np.where(land[source] & land[target],
                             np.maximum(elevation_m[source], elevation_m[target]), np.inf)
        barriers[index][source] = endpoints
        barriers[7-index][target] = endpoints
    seed = stage_seed(master_seed, LANDFORM_STAGE_ID)
    seen: set[tuple[bytes, bytes, float, float, float]] = set()
    # Stream regions into shared grid storage, including refined observations.
    for region in mountains:
        controls = region.settings
        identity = (region.geometry.wkb, region.coverage.wkb, controls.transition_km,
                    controls.feature_size_km, controls.orientation_deg)
        if identity in seen:
            continue
        seen.add(identity)
        u, v, broad = regional_noise_basis(xx, yy, controls, seed)
        nearby = np.asarray(shapely.intersects_xy(region.sampling_support().buffer(radius), xx, yy),
                            dtype=np.bool_)
        for index in range(4, 8):
            dy, dx = D8_NEIGHBOURS[index]
            source = (slice(0, ny-dy), slice(max(0, -dx), nx-max(0, dx)))
            target = (slice(dy, ny), slice(max(0, dx), nx-max(0, -dx)))
            first, last = broad[source], broad[target]
            crossing = ((np.signbit(first) != np.signbit(last)) | (first == 0.) | (last == 0.))
            # fade' <= 15/8, lattice differences <= 2; two normalized octaves
            # with weights 1, 1/2 give |df| <= 5/F * (|du|+|dv|). This screen
            # has a floating-point margin, not a rounded full-field certificate.
            variation = 5./controls.feature_size_km * (
                np.abs(u[target]-u[source]) + np.abs(v[target]-v[source]))
            margin = 64*np.finfo(np.float64).eps * (1. + (
                np.abs(u[source])+np.abs(u[target])+np.abs(v[source])+np.abs(v[target])
            )/controls.feature_size_km)
            eligible = ((crossing | (np.abs(first)+np.abs(last) <= variation+margin))
                        & (nearby[source] | nearby[target]) & land[source] & land[target])
            r, c = np.nonzero(eligible)
            c = c + max(0, -dx)
            for start in range(0, r.size, batch_edges):
                a, b = r[start:start+batch_edges], c[start:start+batch_edges]
                d, e = a+dy, b+dx
                observed, edge, fraction = _crest_locations(
                    x[b], y[a], x[e], y[d], broad[a, b], broad[d, e], controls, seed)
                # Retain every old crossing even if its zero is an endpoint.
                candidates[index-4, a, b] |= observed
                if edge.size:
                    for offset in range(0, edge.size, 7*batch_edges):
                        part = slice(offset, offset+7*batch_edges)
                        selected, t = edge[part], fraction[part]
                        qx = (x[b[selected]]*(1-t)+x[e[selected]]*t)[:, None]
                        qy = (y[a[selected]]*(1-t)+y[d[selected]]*t)[:, None]
                        peaks = _sample_peaks(sample_macro, qx, qy)
                        np.maximum.at(barriers[index], (a[selected], b[selected]), peaks)
                    barriers[7-index, d, e] = barriers[index, a, b]
            del first, last
        del broad, nearby, u, v
    fractions = np.arange(1, 8, dtype=np.float64)[None, :]/8.
    raised = False
    # Shared regular probes retain the baseline evidence and observe height terms
    # whose maxima need not coincide with a regional carrier zero.
    for index in range(4, 8):
        dy, dx = D8_NEIGHBOURS[index]
        r, c = np.nonzero(candidates[index-4])
        for start in range(0, r.size, batch_edges):
            a, b = r[start:start+batch_edges], c[start:start+batch_edges]
            d, e = a+dy, b+dx
            qx = x[b, None]*(1-fractions) + x[e, None]*fractions
            qy = y[a, None]*(1-fractions) + y[d, None]*fractions
            peaks = np.maximum(barriers[index, a, b], _sample_peaks(sample_macro, qx, qy))
            raised |= bool(np.any(peaks > np.maximum(elevation_m[a, b], elevation_m[d, e])))
            barriers[index, a, b] = peaks
            barriers[7-index, d, e] = peaks
    if not raised:
        return None
    barriers.flags.writeable = False
    return barriers
