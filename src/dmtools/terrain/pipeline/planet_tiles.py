# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Window-independent regional detail: fixed tiles blended by a partition of unity.

Independently generated windows disagree where they overlap (erosion is
non-local). Tiles centred on a fixed Fibonacci lattice are each enriched once
from the parent, and any point blends the tiles around it with normalised
Wendland weights. Every request over a place therefore sees the same values.
"""

from dataclasses import dataclass
from math import pi, sqrt

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from dmtools.terrain.domain.planet import RegionalSettings, tile_stage_prefix
from dmtools.terrain.domain.seeds import stage_seed
from dmtools.terrain.pipeline.control import CancellationToken
from dmtools.terrain.pipeline.planet_kernels import interpolate_to_lonlat
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, fibonacci_nodes, vertex_triangles
from dmtools.terrain.pipeline.planet_patch import regional_mesh
from dmtools.terrain.pipeline.planet_regional import (
    RegionalParent,
    RegionalResult,
    enrich,
)

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]


@dataclass(frozen=True)
class TileGrid:
    centres: F64
    radius_m: float
    spacing_m: float
    support_m: float
    halo_m: float

    @classmethod
    def for_planet(cls, radius_m: float, settings: RegionalSettings) -> TileGrid:
        spacing = settings.tile_km * 1e3
        count = max(12, round(4 * pi * radius_m**2 / spacing**2))
        actual = sqrt(4 * pi * radius_m**2 / count)
        return cls(
            fibonacci_nodes(count, seed=0, jitter=0.0), radius_m, actual,
            settings.support_factor * actual, settings.halo_km * 1e3,
        )

    def lonlat(self, tile: int) -> tuple[float, float]:
        x, y, z = self.centres[tile]
        return float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(z)))

    def weights(self, points: F64) -> tuple[I64, F64]:
        """Covering tiles per point and their normalised Wendland C2 weights."""
        chord = 2 * np.sin(self.support_m / self.radius_m / 2)
        lists = KDTree(self.centres).query_ball_point(points, chord)
        width = max(1, max(len(item) for item in lists))
        tiles = np.full((len(points), width), -1, dtype=np.int64)
        w = np.zeros((len(points), width))
        for row, item in enumerate(lists):
            if not item:
                continue
            ids = np.asarray(item, dtype=np.int64)
            d = self.radius_m * np.arccos(np.clip(self.centres[ids] @ points[row], -1, 1))
            q = np.clip(d / self.support_m, 0, 1)
            tiles[row, : len(ids)] = ids
            w[row, : len(ids)] = (1 - q) ** 4 * (4 * q + 1)
        total = w.sum(axis=1, keepdims=True)
        return tiles, np.divide(w, total, out=np.zeros_like(w), where=total > 0)

    def tiles_near(self, centre: tuple[float, float], radius_m: float) -> tuple[int, ...]:
        """Every tile that can contribute anywhere within ``radius_m`` of ``centre``."""
        lon, lat = np.radians(centre)
        point = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
        reach = (radius_m + self.support_m) / self.radius_m
        within = self.centres @ point >= np.cos(min(reach, np.pi))
        return tuple(int(t) for t in np.flatnonzero(within))

    def tiles_for(self, points: F64) -> tuple[int, ...]:
        ids, weights = self.weights(points)
        return tuple(sorted({int(t) for t in np.unique(ids[weights > 0])}))


def tile_seed(master: int, tile: int, level: int = 1) -> int:
    return stage_seed(master, f"{tile_stage_prefix(level)}{tile}")


def generate_tile(
    parent: RegionalParent,
    grid: TileGrid,
    tile: int,
    settings: RegionalSettings,
    *,
    level: int = 1,
    cancellation: CancellationToken | None = None,
) -> RegionalResult:
    lon, lat = grid.lonlat(tile)
    seed = tile_seed(parent.settings.seed, tile, level)
    region = regional_mesh(
        lon, lat, (grid.support_m + grid.halo_m) / 1e3, settings.spacing_km,
        parent.mesh.radius_m, seed,
    )
    return enrich(
        parent, region, process_area_km2=settings.process_area_km2,
        iterations=settings.calibration_iterations, seed=seed, cancellation=cancellation,
    )


@dataclass(frozen=True)
class TileSurface:
    """A finished tile's mesh and land relief (0 at sea), enough to sample and blend."""

    mesh: SphereMesh
    elevation_m: F64

    @classmethod
    def from_result(cls, result: RegionalResult) -> TileSurface:
        return cls(result.region.mesh, np.where(result.land, result.elevation_m, 0.0))

    def sample(self, points: F64) -> F64:
        mesh = self.mesh
        nearest = np.asarray(KDTree(mesh.xyz).query(points, workers=-1)[1], dtype=np.int64)
        vt_ptr, vt_idx = vertex_triangles(mesh)
        return interpolate_to_lonlat(
            np.ascontiguousarray(self.elevation_m), mesh.xyz, mesh.triangles, vt_ptr, vt_idx,
            mesh.ptr, mesh.nbr, nearest, np.ascontiguousarray(points),
        )


def blend(grid: TileGrid, tiles: dict[int, TileSurface], points: F64) -> F64:
    ids, weights = grid.weights(points)
    out = np.zeros(len(points))
    for tile, surface in tiles.items():
        mask = ids == tile
        rows = np.flatnonzero(mask.any(axis=1))
        if not len(rows):
            continue
        values = surface.sample(points[rows])
        out[rows] += weights[rows][mask[rows]] * values
    missing = set(np.unique(ids[weights > 0]).tolist()) - set(tiles)
    if missing:
        raise ValueError(f"Blending needs tiles that are not available: {sorted(missing)[:5]}")
    return out
