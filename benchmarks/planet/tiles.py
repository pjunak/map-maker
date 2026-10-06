# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Research harness: window-independent regional detail from fixed blended tiles.

Independently generated windows disagree where they overlap, because erosion is
non-local. Here the planet is covered by a fixed set of tiles whose centres form
a Fibonacci lattice. Each tile is enriched once from the parent (see
``regional``), and a query point blends the tiles around it with compactly
supported weights normalised to one (a partition of unity). Every request over
the same place gets identical values, and blending removes seams.

    python -m benchmarks.planet.tiles WORLD [--geology G] --lon L --lat P --output DIR
"""

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from math import pi, sqrt
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from benchmarks.planet.regional import (
    RegionalResult,
    enrich,
    inverse_aeqd,
    plane_relief,
    regional_mesh,
)
from dmtools.terrain.adapters.world_geology import read_geology
from dmtools.terrain.application.world import open_world
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.domain.seeds import stage_seed
from dmtools.terrain.pipeline.planet import PlanetResult, generate_planet
from dmtools.terrain.pipeline.planet_kernels import interpolate_to_lonlat
from dmtools.terrain.pipeline.planet_mesh import fibonacci_nodes, vertex_triangles

type F64 = NDArray[np.float64]

SUPPORT_FACTOR = 0.8


@dataclass(frozen=True)
class TileGrid:
    centres: F64  # (t, 3) unit vectors
    spacing_m: float  # typical distance between neighbouring tile centres
    support_m: float  # blend support radius around a centre
    halo_m: float  # extra generated margin beyond the support

    @classmethod
    def for_planet(cls, radius_m: float, spacing_km: float, halo_km: float) -> TileGrid:
        spacing = spacing_km * 1e3
        count = max(12, round(4 * pi * radius_m**2 / spacing**2))
        centres = fibonacci_nodes(count, seed=0, jitter=0.0)
        actual = sqrt(4 * pi * radius_m**2 / count)
        return cls(centres, actual, SUPPORT_FACTOR * actual, halo_km * 1e3)

    def lonlat(self, tile: int) -> tuple[float, float]:
        x, y, z = self.centres[tile]
        return float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(z)))

    def weights(self, points: F64, radius_m: float) -> tuple[NDArray[np.int64], F64]:
        """For each point, the covering tiles and normalised Wendland C2 weights."""
        tree = KDTree(self.centres)
        chord = 2 * np.sin(self.support_m / radius_m / 2)
        lists = tree.query_ball_point(points, chord)
        width = max(len(item) for item in lists)
        tiles = np.full((len(points), width), -1, dtype=np.int64)
        w = np.zeros((len(points), width))
        for row, item in enumerate(lists):
            if not item:
                continue
            ids = np.asarray(item, dtype=np.int64)
            d = radius_m * np.arccos(np.clip(self.centres[ids] @ points[row], -1, 1))
            q = np.clip(d / self.support_m, 0, 1)
            k = (1 - q) ** 4 * (4 * q + 1)
            tiles[row, : len(ids)] = ids
            w[row, : len(ids)] = k
        total = w.sum(axis=1, keepdims=True)
        return tiles, np.divide(w, total, out=np.zeros_like(w), where=total > 0)


def tile_seed(master: int, tile: int) -> int:
    return stage_seed(master, f"planet.tile.{tile}")


def generate_tile(
    parent: PlanetResult, grid: TileGrid, tile: int, spacing_km: float, process_km2: float,
    iterations: int, master_seed: int,
) -> RegionalResult:
    lon, lat = grid.lonlat(tile)
    region = regional_mesh(
        lon, lat, (grid.support_m + grid.halo_m) / 1e3, spacing_km, parent.mesh.radius_m,
        tile_seed(master_seed, tile),
    )
    return enrich(
        parent, region, process_area_km2=process_km2, iterations=iterations,
        seed=tile_seed(master_seed, tile),
    )


type TileJob = tuple[PlanetResult, TileGrid, int, float, float, int, int]


def _tile_job(args: TileJob) -> tuple[int, RegionalResult]:
    parent, grid, tile, spacing, process, iterations, seed = args
    return tile, generate_tile(parent, grid, tile, spacing, process, iterations, seed)


def sample_tile(result: RegionalResult, values: F64, points: F64) -> F64:
    mesh = result.region.mesh
    nearest = np.asarray(KDTree(mesh.xyz).query(points, workers=-1)[1], dtype=np.int64)
    vt_ptr, vt_idx = vertex_triangles(mesh)
    return interpolate_to_lonlat(
        np.ascontiguousarray(values), mesh.xyz, mesh.triangles, vt_ptr, vt_idx, mesh.ptr,
        mesh.nbr, nearest, np.ascontiguousarray(points),
    )


def blend(tiles: dict[int, RegionalResult], grid: TileGrid, points: F64, radius_m: float) -> F64:
    ids, weights = grid.weights(points, radius_m)
    out = np.zeros(len(points))
    for tile, result in tiles.items():
        mask = ids == tile
        rows = np.flatnonzero(mask.any(axis=1))
        if not len(rows):
            continue
        values = sample_tile(result, np.where(result.land, result.elevation_m, 0.0), points[rows])
        out[rows] += weights[rows][mask[rows]] * values
    return out


def window_points(
    lon: float, lat: float, radius_km: float, pixels: int, planet_m: float
) -> tuple[F64, NDArray[np.bool_]]:
    r = radius_km * 1e3
    centres = (np.arange(pixels) + 0.5) / pixels * 2 * r - r
    gx, gy = np.meshgrid(centres, -centres)
    return inverse_aeqd(gx.ravel(), gy.ravel(), lon, lat, planet_m), (np.hypot(gx, gy) <= r)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("world", type=Path)
    parser.add_argument("--geology", type=Path)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--window-km", type=float, default=600.0)
    parser.add_argument("--tile-km", type=float, default=600.0)
    parser.add_argument("--halo-km", type=float, default=150.0)
    parser.add_argument("--spacing-km", type=float, default=5.0)
    parser.add_argument("--process-km2", type=float, default=600.0)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--parent-nodes", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=False)
    world = open_world(args.world)
    recipe = None if args.geology is None else read_geology(args.geology)[0]
    started = time.perf_counter()
    parent = generate_planet(world, PlanetSettings(seed=args.seed, nodes=args.parent_nodes), recipe)
    planet_m = parent.mesh.radius_m
    grid = TileGrid.for_planet(planet_m, args.tile_km, args.halo_km)
    pixels = 900
    # Two overlapping windows over the same place must agree exactly.
    degrees = args.window_km * 0.6 / (planet_m / 1e3) * 180 / pi
    shift = degrees / max(float(np.cos(np.radians(args.lat))), 0.2)
    windows = [(args.lon, args.lat), (args.lon + shift, args.lat)]
    samples = [window_points(lon, lat, args.window_km, pixels, planet_m) for lon, lat in windows]
    needed: set[int] = set()
    for points, inside in samples:
        ids, _ = grid.weights(points[inside.ravel()], planet_m)
        needed |= {int(t) for t in np.unique(ids) if t >= 0}
    parent_seconds = time.perf_counter() - started
    started = time.perf_counter()
    jobs = [
        (parent, grid, tile, args.spacing_km, args.process_km2, args.iterations, args.seed)
        for tile in sorted(needed)
    ]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tiles = dict(pool.map(_tile_job, jobs))
    tile_seconds = time.perf_counter() - started
    fields = []
    for (points, inside), (lon, _lat) in zip(samples, windows, strict=True):
        z = blend(tiles, grid, points, planet_m).reshape(pixels, pixels)
        fields.append((z, inside, points))
        land = inside & (z > 0.5)
        plane_relief(np.where(land, z, -200.0), land, 2 * args.window_km * 1e3 / pixels).save(
            out / f"window-{lon:.2f}.png"
        )
    # Window independence: a tile depends only on (parent, tile id, settings), so
    # regenerating any tile in a fresh process reproduces it exactly.
    first = sorted(tiles)[0]
    again = generate_tile(
        parent, grid, first, args.spacing_km, args.process_km2, args.iterations, args.seed
    )
    agreement = float(np.max(np.abs(again.elevation_m - tiles[first].elevation_m)))
    # Seam diagnostic: disagreement between neighbouring tiles where both are valid.
    seam: list[float] = []
    ids = sorted(tiles)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            ca, cb = grid.centres[a], grid.centres[b]
            if planet_m * np.arccos(np.clip(ca @ cb, -1, 1)) > 1.5 * grid.spacing_m:
                continue
            mid = (ca + cb) / np.linalg.norm(ca + cb)
            mid_lon = float(np.degrees(np.arctan2(mid[1], mid[0])))
            mid_lat = float(np.degrees(np.arcsin(mid[2])))
            pts, ok = window_points(mid_lon, mid_lat, 100, 40, planet_m)
            pts = pts[ok.ravel()]
            va = sample_tile(tiles[a], np.where(tiles[a].land, tiles[a].elevation_m, 0), pts)
            vb = sample_tile(tiles[b], np.where(tiles[b].land, tiles[b].elevation_m, 0), pts)
            seam.append(float(np.sqrt(np.mean((va - vb) ** 2))))
    report = {
        "tiles": len(tiles),
        "tile_spacing_km": grid.spacing_m / 1e3,
        "support_km": grid.support_m / 1e3,
        "tile_nodes_mean": float(np.mean([t.region.mesh.size for t in tiles.values()])),
        "seconds": {"parent": parent_seconds, "tiles": tile_seconds},
        "tile_regeneration_max_abs_difference_m": agreement,
        "neighbour_tile_rms_m": (
            {"median": float(np.median(seam)), "max": float(np.max(seam))} if seam else None
        ),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
