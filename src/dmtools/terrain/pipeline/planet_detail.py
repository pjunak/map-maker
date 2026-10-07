# pyright: reportArgumentType=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Sub-mesh relief detail for display: derivative-damped ("eroded") fractal noise.

The planet mesh resolves landforms down to its process scale (tens of km). A map
drawn at a few km per pixel needs texture below that scale, or slopes between
rivers look like smooth ramps. This noise is a *display* field:

* coordinate-hashed on unit vectors, so it is resolution- and window-independent;
* damped by its own accumulated gradient (as in derivative fBm), which leaves
  sharp ridges and smooth valley floors, the look of eroded terrain;
* blended from soft rolling noise in lowlands to ridged noise in mountains.

It never changes the authoritative mesh relief.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from dmtools.terrain.pipeline.planet_kernels import (
    accumulate,
    priority_flood,
    steepest_receivers,
    stream_power_implicit,
)

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

if TYPE_CHECKING:
    prange = range

    def njit[T: Callable[..., Any]](*_args: object, **_kwargs: object) -> Callable[[T], T]:
        return lambda function: function
else:
    from numba import njit, prange


@njit(cache=True, inline="always")
def _hash(seed: int, x: int, y: int, z: int) -> float:
    h = np.uint64(seed) * np.uint64(0x9E3779B97F4A7C15)
    for c in (x, y, z):
        h ^= np.uint64(c & 0xFFFFFFFF) * np.uint64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        h ^= h >> np.uint64(31)
    return float(h >> np.uint64(11)) / 9007199254740992.0 * 2.0 - 1.0


@njit(cache=True, inline="always")
def _noise(seed: int, x: float, y: float, z: float) -> tuple[float, float, float, float]:
    """Value noise in [-1, 1] and its gradient (quintic interpolation)."""
    ix, iy, iz = int(np.floor(x)), int(np.floor(y)), int(np.floor(z))
    fx, fy, fz = x - ix, y - iy, z - iz
    ux = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
    uy = fy * fy * fy * (fy * (fy * 6 - 15) + 10)
    uz = fz * fz * fz * (fz * (fz * 6 - 15) + 10)
    dux = 30 * fx * fx * (fx * (fx - 2) + 1)
    duy = 30 * fy * fy * (fy * (fy - 2) + 1)
    duz = 30 * fz * fz * (fz * (fz - 2) + 1)
    a = _hash(seed, ix, iy, iz)
    b = _hash(seed, ix + 1, iy, iz)
    c = _hash(seed, ix, iy + 1, iz)
    d = _hash(seed, ix + 1, iy + 1, iz)
    e = _hash(seed, ix, iy, iz + 1)
    f = _hash(seed, ix + 1, iy, iz + 1)
    g = _hash(seed, ix, iy + 1, iz + 1)
    h = _hash(seed, ix + 1, iy + 1, iz + 1)
    k1, k2, k3 = b - a, c - a, e - a
    k4, k5, k6 = a - b - c + d, a - c - e + g, a - b - e + f
    k7 = -a + b + c - d + e - f - g + h
    value = (
        a
        + k1 * ux
        + k2 * uy
        + k3 * uz
        + k4 * ux * uy
        + k5 * uy * uz
        + k6 * uz * ux
        + k7 * ux * uy * uz
    )
    gx = dux * (k1 + k4 * uy + k6 * uz + k7 * uy * uz)
    gy = duy * (k2 + k5 * uz + k4 * ux + k7 * uz * ux)
    gz = duz * (k3 + k6 * ux + k5 * uy + k7 * ux * uy)
    return value, gx, gy, gz


@njit(cache=True, parallel=True)
def eroded_fbm(
    xyz: F64,
    ridged: F64,
    seed: int,
    octaves: int,
    base_frequency: float,
    gain: float,
    damping: float,
) -> F64:
    """Derivative-damped fBm on unit vectors; ``ridged`` (0..1) blends in ridged noise.

    ``base_frequency`` is in cycles per planet radius. Output is roughly zero-mean
    and within [-1, 1].
    """
    n = xyz.shape[0]
    out = np.empty(n)
    for i in prange(n):
        px, py, pz = xyz[i, 0], xyz[i, 1], xyz[i, 2]
        total, norm, amplitude, frequency = 0.0, 0.0, 1.0, base_frequency
        sx, sy, sz = 0.0, 0.0, 0.0
        r = ridged[i]
        for octave in range(octaves):
            v, gx, gy, gz = _noise(
                seed + 1013 * octave, px * frequency, py * frequency, pz * frequency
            )
            # Ridged variant: sharp crests where the noise crosses zero.
            sign = 1.0 if v >= 0 else -1.0
            ridge = 1.0 - 2.0 * abs(v)
            value = (1.0 - r) * v + r * (ridge - 0.0)
            dx = (1.0 - r) * gx - r * 2.0 * sign * gx
            dy = (1.0 - r) * gy - r * 2.0 * sign * gy
            dz = (1.0 - r) * gz - r * 2.0 * sign * gz
            sx += dx * amplitude
            sy += dy * amplitude
            sz += dz * amplitude
            total += amplitude * value / (1.0 + damping * (sx * sx + sy * sy + sz * sz))
            norm += amplitude
            amplitude *= gain
            frequency *= 2.03
        out[i] = total / norm
    return out


def grid_adjacency(rows: int, columns: int, cell_m: float) -> tuple[I64, I64, F64]:
    """CSR 8-neighbour adjacency and edge lengths (m) of a square-cell grid."""
    index = np.arange(rows * columns, dtype=np.int64).reshape(rows, columns)
    sources, targets, lengths = [], [], []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            r0, r1 = max(0, -dr), rows - max(0, dr)
            c0, c1 = max(0, -dc), columns - max(0, dc)
            here = index[r0:r1, c0:c1].ravel()
            sources.append(here)
            targets.append(index[r0 + dr : r1 + dr, c0 + dc : c1 + dc].ravel())
            lengths.append(np.full(here.size, cell_m * (2**0.5 if dr and dc else 1.0)))
    source = np.concatenate(sources)
    order = np.argsort(source, kind="stable")
    ptr = np.zeros(rows * columns + 1, dtype=np.int64)
    np.add.at(ptr, source + 1, 1)
    return np.cumsum(ptr), np.concatenate(targets)[order], np.concatenate(lengths)[order]


def carve_valleys(
    z: F64, outlet: B, cell_m: float, erodibility: float, area_exponent: float, steps: int
) -> F64:
    """Display-only valley carving: implicit stream power over a pixel grid.

    Fractal detail has the right roughness but no drainage network. A few
    implicit stream-power steps (Braun and Willett 2013, n = 1) routed over the
    detailed surface itself turn its hollows into connected, branching valleys
    with concave long profiles. ``outlet`` cells (sea, outside the map) are the
    base level. ``erodibility`` is K * dt in m^(1 - 2m).
    """
    rows, columns = z.shape
    ptr, nbr, length = grid_adjacency(rows, columns, cell_m)
    fixed = outlet.ravel()
    h = z.ravel().copy()
    cell_area = np.full(h.size, cell_m * cell_m)
    zero = np.zeros(h.size)
    k = np.full(h.size, erodibility)
    land = np.flatnonzero(~fixed)
    for _ in range(steps):
        filled, parent = priority_flood(h, fixed, ptr, nbr, 1e-3)
        receiver, distance = steepest_receivers(filled, fixed, ptr, nbr, length, parent)
        order = land[np.argsort(filled[land], kind="stable")]
        area = accumulate(order, receiver, fixed, cell_area)
        h = stream_power_implicit(
            filled, order, receiver, distance, fixed, area, k, area_exponent, zero, 1.0
        )
    return h.reshape(rows, columns)
