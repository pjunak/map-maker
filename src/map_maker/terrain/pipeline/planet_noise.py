# pyright: reportArgumentType=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Coordinate-hashed 3D value noise on unit vectors (resolution- and order-independent).

Compiled with Numba and parallel over points; each point's value depends only on
its coordinates and the seed, so results do not depend on threading.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

type F64 = NDArray[np.float64]

if TYPE_CHECKING:
    prange = range

    def njit[T: Callable[..., Any]](*_args: object, **_kwargs: object) -> Callable[[T], T]:
        return lambda function: function
else:
    from numba import njit, prange

_MASK = 0xFFFFFFFFFFFFFFFF


@njit(cache=True, inline="always")
def _hash01(seed: np.uint64, x: np.int64, y: np.int64, z: np.int64) -> float:
    """Stateless lattice hash in [0, 1) using splitmix64 finalisation per axis."""
    h = seed * np.uint64(0x9E3779B97F4A7C15)
    for axis in range(3):
        coordinate = x if axis == 0 else (y if axis == 1 else z)
        salt = np.uint64(0xBF58476D1CE4E5B9) + np.uint64(0x94D049BB133111EB) * np.uint64(axis)
        h = h ^ (np.uint64(coordinate) * salt)
        h = (h ^ (h >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        h = h ^ (h >> np.uint64(31))
    return float(h >> np.uint64(11)) / 9007199254740992.0


@njit(cache=True, inline="always")
def _value(seed: np.uint64, px: float, py: float, pz: float) -> float:
    bx, by, bz = np.floor(px), np.floor(py), np.floor(pz)
    fx, fy, fz = px - bx, py - by, pz - bz
    ix, iy, iz = np.int64(bx), np.int64(by), np.int64(bz)
    ux = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
    uy = fy * fy * fy * (fy * (fy * 6 - 15) + 10)
    uz = fz * fz * fz * (fz * (fz * 6 - 15) + 10)
    out = 0.0
    for dx in range(2):
        wx = ux if dx else 1 - ux
        for dy in range(2):
            wy = uy if dy else 1 - uy
            for dz in range(2):
                wz = uz if dz else 1 - uz
                v = _hash01(seed, ix + dx, iy + dy, iz + dz)
                out += wx * wy * wz * (2 * v - 1)
    return out


@njit(cache=True, parallel=True)
def _fbm3(p: F64, seeds: NDArray[np.uint64], frequency: float, gain: float) -> F64:
    n = p.shape[0]
    out = np.empty(n)
    for i in prange(n):
        total = 0.0
        amplitude = 1.0
        norm = 0.0
        for octave in range(seeds.size):
            scale = frequency * 2.0**octave
            total += amplitude * _value(
                seeds[octave], p[i, 0] * scale, p[i, 1] * scale, p[i, 2] * scale
            )
            norm += amplitude
            amplitude *= gain
        out[i] = total / norm
    return out


def value_noise3(p: F64, seed: int) -> F64:
    """Quintic-interpolated value noise in [-1, 1]; ``p`` has shape (n, 3)."""
    return _fbm3(
        np.ascontiguousarray(p, dtype=np.float64), np.array([seed & _MASK], np.uint64), 1.0, 1.0
    )


def fbm3(p: F64, seed: int, octaves: int, frequency: float, gain: float = 0.5) -> F64:
    """Normalised fractal sum; frequency is in cycles per planet radius."""
    seeds = np.array([(seed + 1013 * octave) & _MASK for octave in range(octaves)], np.uint64)
    return _fbm3(np.ascontiguousarray(p, dtype=np.float64), seeds, float(frequency), float(gain))
