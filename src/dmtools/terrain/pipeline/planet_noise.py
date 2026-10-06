"""Coordinate-hashed 3D value noise on unit vectors (resolution- and order-independent)."""

import numpy as np
from numpy.typing import NDArray

type F64 = NDArray[np.float64]

_MIX_A = np.uint64(0xBF58476D1CE4E5B9)
_MIX_B = np.uint64(0x94D049BB133111EB)
_GOLDEN = np.uint64(0x9E3779B97F4A7C15)
_MASK = 0xFFFFFFFFFFFFFFFF


def _hash01(seed: int, x: NDArray[np.int64], y: NDArray[np.int64], z: NDArray[np.int64]) -> F64:
    """Stateless lattice hash in [0, 1) using splitmix64 finalisation per axis."""
    with np.errstate(over="ignore"):
        h: NDArray[np.uint64] = np.full(x.shape, seed, dtype=np.uint64) * _GOLDEN
        for axis, coordinate in enumerate((x, y, z)):
            salt = np.uint64((0xBF58476D1CE4E5B9 + 0x94D049BB133111EB * axis) & _MASK)
            h = h ^ (coordinate.astype(np.uint64) * salt)
            h = (h ^ (h >> np.uint64(30))) * _MIX_A
            h = (h ^ (h >> np.uint64(27))) * _MIX_B
            h = h ^ (h >> np.uint64(31))
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def value_noise3(p: F64, seed: int) -> F64:
    """Quintic-interpolated value noise in [-1, 1]; ``p`` has shape (n, 3)."""
    base = np.floor(p)
    f = p - base
    i = base.astype(np.int64)
    u = f * f * f * (f * (f * 6 - 15) + 10)
    out = np.zeros(len(p))
    for dx in (0, 1):
        wx = u[:, 0] if dx else 1 - u[:, 0]
        for dy in (0, 1):
            wy = u[:, 1] if dy else 1 - u[:, 1]
            for dz in (0, 1):
                wz = u[:, 2] if dz else 1 - u[:, 2]
                v = _hash01(seed, i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz)
                out += wx * wy * wz * (2 * v - 1)
    return out


def fbm3(p: F64, seed: int, octaves: int, frequency: float, gain: float = 0.5) -> F64:
    """Normalised fractal sum; frequency is in cycles per planet radius."""
    total = np.zeros(len(p))
    amplitude, norm = 1.0, 0.0
    for octave in range(octaves):
        total += amplitude * value_noise3(p * frequency * 2**octave, (seed + 1013 * octave) & _MASK)
        norm += amplitude
        amplitude *= gain
    return total / norm
