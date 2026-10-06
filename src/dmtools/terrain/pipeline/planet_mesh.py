# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Irregular spherical process mesh: jittered Fibonacci nodes + spherical Delaunay.

A whole-planet grid without poles, seams or eight preferred flow directions.
The convex hull of points on a sphere is their spherical Delaunay triangulation.
"""

from dataclasses import dataclass
from math import pi, sqrt

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import ConvexHull

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]

GOLDEN_ANGLE = pi * (3 - sqrt(5))


@dataclass(frozen=True, slots=True)
class SphereMesh:
    radius_m: float
    xyz: F64  # (n, 3) unit vectors
    triangles: I64  # (t, 3), counter-clockwise seen from outside
    ptr: I64  # CSR neighbour offsets, (n + 1,)
    nbr: I64  # CSR neighbour indices
    length_m: F64  # great-circle edge length for each CSR entry
    weight: F64  # cotangent Laplacian weight for each CSR entry (dimensionless)
    area_m2: F64  # barycentric dual area per node

    @property
    def size(self) -> int:
        return len(self.xyz)

    @property
    def spacing_m(self) -> float:
        """Typical node spacing: square root of the mean node area."""
        return sqrt(float(self.area_m2.sum()) / self.size)

    @property
    def lon(self) -> F64:
        return np.arctan2(self.xyz[:, 1], self.xyz[:, 0])

    @property
    def lat(self) -> F64:
        return np.arcsin(np.clip(self.xyz[:, 2], -1, 1))


def fibonacci_nodes(count: int, seed: int, jitter: float = 0.35) -> F64:
    """Near-uniform nodes; tangent jitter (in node spacings) breaks the spiral lattice."""
    i = np.arange(count, dtype=np.float64)
    z = 1 - (2 * i + 1) / count
    r = np.sqrt(np.maximum(0.0, 1 - z * z))
    phi = i * GOLDEN_ANGLE
    p = np.stack((r * np.cos(phi), r * np.sin(phi), z), axis=1)
    if jitter > 0:
        rng = np.random.default_rng(seed)
        step = jitter * sqrt(4 * pi / count)
        offset = rng.normal(size=p.shape) * step / sqrt(2)
        offset -= np.sum(offset * p, axis=1, keepdims=True) * p
        p = p + offset
        p /= np.linalg.norm(p, axis=1, keepdims=True)
    return p


def _spherical_triangle_area(a: F64, b: F64, c: F64) -> F64:
    triple = np.abs(np.einsum("ij,ij->i", a, np.cross(b, c)))
    denominator = 1 + np.einsum("ij,ij->i", a, b) + np.einsum("ij,ij->i", b, c) + np.einsum(
        "ij,ij->i", c, a
    )
    return 2 * np.arctan2(triple, denominator)


def _cot(u: F64, v: F64) -> F64:
    return np.einsum("ij,ij->i", u, v) / np.linalg.norm(np.cross(u, v), axis=1)


def build_mesh(count: int, radius_m: float, seed: int, jitter: float = 0.35) -> SphereMesh:
    """Deterministic mesh: ``seed`` is the ``planet.mesh`` stage seed."""
    xyz = fibonacci_nodes(count, seed, jitter)
    return mesh_from_triangles(xyz, ConvexHull(xyz).simplices.astype(np.int64), radius_m)


def mesh_from_triangles(xyz: F64, triangles: I64, radius_m: float) -> SphereMesh:
    """Assemble neighbours, lengths, areas and Laplacian weights for any spherical
    triangulation of unit vectors (whole sphere or a region with a boundary)."""
    count = len(xyz)
    triangles = triangles.copy()
    a, b, c = xyz[triangles[:, 0]], xyz[triangles[:, 1]], xyz[triangles[:, 2]]
    outward = np.einsum("ij,ij->i", np.cross(b - a, c - a), a) > 0
    triangles[~outward] = triangles[~outward][:, [0, 2, 1]]
    a, b, c = xyz[triangles[:, 0]], xyz[triangles[:, 1]], xyz[triangles[:, 2]]

    area = _spherical_triangle_area(a, b, c) * radius_m**2
    node_area = np.zeros(count)
    for k in range(3):
        np.add.at(node_area, triangles[:, k], area / 3)

    # Directed half-edges with the cotangent of the opposite (chordal) angle.
    cot_c = _cot(a - c, b - c)  # opposite edge a-b
    cot_a = _cot(b - a, c - a)  # opposite edge b-c
    cot_b = _cot(c - b, a - b)  # opposite edge c-a
    src = np.concatenate([triangles[:, 0], triangles[:, 1], triangles[:, 2]])
    dst = np.concatenate([triangles[:, 1], triangles[:, 2], triangles[:, 0]])
    cot = np.concatenate([cot_c, cot_a, cot_b]) / 2
    # Symmetrize: each undirected edge appears once per adjacent triangle.
    s = np.concatenate([src, dst])
    d = np.concatenate([dst, src])
    w = np.concatenate([cot, cot])
    key = s * count + d
    order = np.argsort(key, kind="stable")
    key, s, d, w = key[order], s[order], d[order], w[order]
    unique, start = np.unique(key, return_index=True)
    weight = np.add.reduceat(w, start)
    s, d = s[start], d[start]
    ptr = np.zeros(count + 1, dtype=np.int64)
    np.add.at(ptr, s + 1, 1)
    ptr = np.cumsum(ptr)
    dot = np.clip(np.einsum("ij,ij->i", xyz[s], xyz[d]), -1, 1)
    length = radius_m * np.arctan2(np.linalg.norm(np.cross(xyz[s], xyz[d]), axis=1), dot)
    del unique
    return SphereMesh(radius_m, xyz, triangles, ptr, d, length, weight, node_area)


def vertex_triangles(mesh: SphereMesh) -> tuple[I64, I64]:
    """CSR mapping from node to incident triangles."""
    flat = mesh.triangles.ravel()
    owner = np.repeat(np.arange(len(mesh.triangles)), 3)
    order = np.argsort(flat, kind="stable")
    ptr = np.zeros(mesh.size + 1, dtype=np.int64)
    np.add.at(ptr, flat + 1, 1)
    return np.cumsum(ptr), owner[order]
