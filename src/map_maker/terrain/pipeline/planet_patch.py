# pyright: reportMissingTypeStubs=false
"""Local patches of sphere mesh around a centre, with a ring of nodes at the rim.

Regional tiles and their level parents take the world-fixed nodes of their
level's spacing (``world_patch``), so overlapping patches hold the same nodes.
Wonder aging works on a strongly jittered hexagonal lattice of its own
(``regional_mesh``). Plane coordinates are an azimuthal equidistant projection
about the centre.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, radians, sin, sqrt

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import Delaunay

from map_maker.terrain.domain.seeds import stage_seed
from map_maker.terrain.pipeline.planet_grid import (
    SPACING_PER_RADIUS,
    WorldGrid,
    delaunay,
    stereographic,
)
from map_maker.terrain.pipeline.planet_mesh import SphereMesh, mesh_from_triangles

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

# Node jitter in lattice spacings. At 0.2 steepest descent still followed the
# lattice's three axes (six-fold flow-azimuth grain 0.20, flow pulled up to 6 deg
# towards them on a tilted plane); from 0.35, as on the planet mesh, it is 0.02.
REGIONAL_JITTER_SPACINGS = 0.35
TILE_NODES_STAGE = "planet.tile-nodes"
# A world cell holds as much ground as a hexagonal lattice node of the same
# spacing, so patches keep the lattice's node count.
LATTICE_CELL = sqrt(sqrt(3) / 2)
# Tile nodes lie anywhere in their cells. Within 0.4 of a cell from its centre, as
# routing cells are, steepest descent on a tilted plane ran up to 5 deg off the
# slope, towards the grid's axes; anywhere in the cell, 1.4 deg (lattice: 0.5).
TILE_NODE_JITTER = 0.5


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


def forward_aeqd(xyz: F64, lon0: float, lat0: float, radius_m: float) -> F64:
    """Unit vectors to local plane metres (x east, y north) about (lon0, lat0)."""
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), lon0, lat0, 1.0)[0]
    east = np.cross([0.0, 0.0, 1.0], centre)
    east = (
        east / np.linalg.norm(east) if np.linalg.norm(east) > 1e-12 else np.array([0.0, 1.0, 0.0])
    )
    north = np.cross(centre, east)
    distance = radius_m * np.arccos(np.clip(xyz @ centre, -1, 1))
    tangent = xyz - np.outer(xyz @ centre, centre)
    norm = np.linalg.norm(tangent, axis=1)
    norm = np.where(norm > 1e-15, norm, 1.0)
    return np.stack(
        (distance * (tangent @ east) / norm, distance * (tangent @ north) / norm), axis=1
    )


@dataclass(frozen=True)
class Region:
    mesh: SphereMesh
    plane_m: F64
    boundary: B
    centre: tuple[float, float]
    radius_m: float
    spacing_m: float  # nominal lattice spacing (the mesh's own estimate varies at its rim)
    cell: I64 | None = None  # world-fixed cell id of each node (-1 on the ring)


def regional_mesh(
    lon0: float, lat0: float, radius_km: float, spacing_km: float, planet_m: float, seed: int
) -> Region:
    s, r = spacing_km * 1e3, radius_km * 1e3
    rows = int(np.ceil(r / (s * np.sqrt(3) / 2))) + 1
    columns = int(np.ceil(r / s)) + 1
    jy, jx = np.mgrid[-rows : rows + 1, -columns : columns + 1]
    rng = np.random.default_rng(seed)
    jitter = REGIONAL_JITTER_SPACINGS * s
    x = (jx + 0.5 * (jy % 2)) * s + rng.normal(scale=jitter, size=jx.shape)
    y = jy * s * np.sqrt(3) / 2 + rng.normal(scale=jitter, size=jy.shape)
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


def world_patch(
    lon0: float, lat0: float, radius_km: float, spacing_km: float, planet_m: float, seed: int
) -> Region:
    """The world-fixed nodes of a level's spacing within ``radius_km``, and a ring at the rim.

    Nodes are those of the ``WorldGrid`` whose cells hold as much ground as a
    lattice node of ``spacing_km`` (the master ``seed`` jitters them), joined
    by Delaunay in their stereographic plane, which is the triangulation on the
    sphere: away from their rims, overlapping patches share nodes and triangles.
    """
    s, r = spacing_km * 1e3, radius_km * 1e3
    grid = WorldGrid(
        max(1, round(SPACING_PER_RADIUS * planet_m / (LATTICE_CELL * s))), planet_m,
        stage_seed(seed, TILE_NODES_STAGE), TILE_NODE_JITTER,
    )
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), lon0, lat0, planet_m)[0]
    face, i, j, inner = grid.within(centre, (r - 0.6 * s) / planet_m)
    ring = int(np.ceil(2 * pi * r / s))
    angle = np.arange(ring) * 2 * pi / ring
    xyz = np.vstack(
        (inner, inverse_aeqd(r * np.cos(angle), r * np.sin(angle), lon0, lat0, planet_m))
    )
    triangles = delaunay(stereographic(xyz, centre), 1.1 * grid.cell_m / planet_m)
    mesh = mesh_from_triangles(xyz, triangles, planet_m)
    boundary = np.zeros(len(xyz), dtype=bool)
    boundary[-ring:] = True
    cell = np.concatenate((grid.ids(face, i, j), np.full(ring, -1, dtype=np.int64)))
    return Region(
        mesh, forward_aeqd(xyz, lon0, lat0, planet_m), boundary, (lon0, lat0), r, s, cell
    )
