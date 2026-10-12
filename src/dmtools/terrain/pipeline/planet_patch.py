# pyright: reportMissingTypeStubs=false
"""Local patches of sphere mesh: a jittered hexagonal lattice around a centre.

Regional tiles and wonder aging both work on such patches; plane coordinates
are an azimuthal equidistant projection about the centre.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, radians, sin

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import Delaunay

from dmtools.terrain.pipeline.planet_mesh import SphereMesh, mesh_from_triangles

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]


def inverse_aeqd(x: F64, y: F64, lon0: float, lat0: float, radius_m: float) -> F64:
    """Plane metres (x east, y north) about (lon0, lat0) to unit vectors on the sphere."""
    rho = np.hypot(x, y)
    c = rho / radius_m
    phi0, lam0 = radians(lat0), radians(lon0)
    safe = np.where(rho > 0, rho, 1.0)
    lat = np.arcsin(
        np.clip(
            np.cos(c) * sin(phi0) + np.where(rho > 0, y * np.sin(c) * cos(phi0) / safe, 0.0),
            -1,
            1,
        )
    )
    lon = lam0 + np.arctan2(x * np.sin(c), rho * cos(phi0) * np.cos(c) - y * sin(phi0) * np.sin(c))
    return np.stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=1)


@dataclass(frozen=True)
class Region:
    mesh: SphereMesh
    plane_m: F64
    boundary: B
    centre: tuple[float, float]
    radius_m: float
    spacing_m: float  # nominal lattice spacing (the mesh's own estimate varies at its rim)


def regional_mesh(
    lon0: float, lat0: float, radius_km: float, spacing_km: float, planet_m: float, seed: int
) -> Region:
    s, r = spacing_km * 1e3, radius_km * 1e3
    rows = int(np.ceil(r / (s * np.sqrt(3) / 2))) + 1
    columns = int(np.ceil(r / s)) + 1
    jy, jx = np.mgrid[-rows : rows + 1, -columns : columns + 1]
    rng = np.random.default_rng(seed)
    x = (jx + 0.5 * (jy % 2)) * s + rng.normal(scale=0.2 * s, size=jx.shape)
    y = jy * s * np.sqrt(3) / 2 + rng.normal(scale=0.2 * s, size=jy.shape)
    interior = np.hypot(x, y) <= r - 0.6 * s
    ring = int(np.ceil(2 * pi * r / s))
    angle = np.arange(ring) * 2 * pi / ring
    px = np.concatenate([x[interior], r * np.cos(angle)])
    py = np.concatenate([y[interior], r * np.sin(angle)])
    plane = np.stack((px, py), axis=1)
    triangles = Delaunay(plane).simplices.astype(np.int64)
    mesh = mesh_from_triangles(inverse_aeqd(px, py, lon0, lat0, planet_m), triangles, planet_m)
    boundary = np.zeros(len(px), dtype=bool)
    boundary[-ring:] = True
    return Region(mesh, plane, boundary, (lon0, lat0), r, s)
