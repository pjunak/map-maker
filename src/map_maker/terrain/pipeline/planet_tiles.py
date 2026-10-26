# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Window-independent regional detail: fixed tiles blended by a partition of unity.

Independently generated windows disagree where they overlap (erosion is
non-local). Tiles centred on a fixed Fibonacci lattice are each enriched once
from the parent, and any point blends the tiles around it with normalised
Wendland weights. Every request over a place therefore sees the same values.
Each level samples its blend at points moved by a shared flow (``ReliefWarp``),
so valleys wind below the tile mesh spacing.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import inf, pi, sqrt

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from map_maker.terrain.domain.planet import RegionalSettings, tile_stage_prefix
from map_maker.terrain.domain.seeds import stage_seed
from map_maker.terrain.pipeline.control import CancellationToken
from map_maker.terrain.pipeline.planet_coast import level_finest_m, swirl
from map_maker.terrain.pipeline.planet_mesh import SphereMesh, fibonacci_nodes, sample_field
from map_maker.terrain.pipeline.planet_patch import regional_mesh
from map_maker.terrain.pipeline.planet_regional import (
    RegionalParent,
    RegionalResult,
    enrich,
)

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]

RELIEF_WARP_STAGE = "planet.relief-warp"
RELIEF_WARP_TOP_SPACINGS = 2.0
RELIEF_WARP_STEEPNESS = 0.15


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
        """Covering tiles per point and their normalised Wendland C2 weights.

        Each row lists its tiles in ascending order, padded with -1 and weight 0.
        """
        chord = 2 * np.sin(self.support_m / self.radius_m / 2)
        tree = KDTree(self.centres)
        count = np.asarray(tree.query_ball_point(points, chord, workers=-1, return_length=True))
        width = max(1, int(count.max(initial=0)))
        found = np.asarray(
            tree.query(points, k=width, distance_upper_bound=chord * (1 + 1e-12), workers=-1)[1],
            dtype=np.int64,
        ).reshape(len(points), width)
        # Missing neighbours come back as the number of tiles, which sorts last.
        found.sort(axis=1)
        valid = found < len(self.centres)
        tiles = np.where(valid, found, -1)
        cos = np.einsum("ijk,ik->ij", self.centres[np.where(valid, found, 0)], points)
        q = np.clip(self.radius_m * np.arccos(np.clip(cos, -1, 1)) / self.support_m, 0, 1)
        w = np.where(valid, (1 - q) ** 4 * (4 * q + 1), 0.0)
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
        return sample_field(self.mesh, points, self.elevation_m)


@dataclass(frozen=True)
class ReliefWarp:
    """Where a level's blended relief is sampled: valley courses below its mesh spacing.

    A tile interpolates linearly between its nodes, so a valley there is a
    straight crease, and a planet river segment the tiles inherit a straight
    trough; routed pixel by pixel, rivers ran down them in straight lines.
    Like coasts, lake shores and basin fronts, relief is refined below the mesh
    by moving the points it is sampled at, here along an area-preserving flow
    (``swirl``): valleys and ridges bend, while heights, the area at each height
    and closed depressions are kept.

    All levels share one sequence of octaves, from RELIEF_WARP_TOP_SPACINGS
    level-1 spacings down, each RELIEF_WARP_STEEPNESS of its wavelength. A
    level takes the octaves its tiles cannot carry, those shorter than twice
    the coarser level's spacing (what the coarser mesh resolves, which reaches
    the level through its parent), down to ``finest_m``.
    """

    top_m: float
    coarsest_m: float  # only octaves shorter than this; inf at level 1
    finest_m: float
    seed: int
    # The warp the relief sampled here was itself sampled through, down to
    # level 1, which is enriched from the planet in place (``planet_points``).
    coarser: ReliefWarp | None = None

    @classmethod
    def of_level(
        cls, levels: Sequence[RegionalSettings], level: int, master_seed: int, finest_m: float
    ) -> ReliefWarp:
        """The warp of level ``level``'s relief, down to octaves of ``finest_m``."""
        return cls(
            RELIEF_WARP_TOP_SPACINGS * levels[0].spacing_km * 1e3,
            inf if level == 1 else level_finest_m(levels[level - 2].spacing_km * 1e3),
            finest_m,
            stage_seed(master_seed, RELIEF_WARP_STAGE),
        )

    @classmethod
    def for_window(
        cls, levels: Sequence[RegionalSettings], level: int, master_seed: int
    ) -> ReliefWarp:
        """A level-``level`` window's warp: down to the level's own spacing."""
        return cls.of_level(levels, level, master_seed, levels[level - 1].spacing_km * 1e3)

    @classmethod
    def for_parent(
        cls, levels: Sequence[RegionalSettings], level: int, master_seed: int
    ) -> ReliefWarp:
        """The warp of the coarser relief a level-``level`` parent samples.

        It stops where the parent's mesh stops resolving (twice its spacing);
        level ``level`` itself takes the finer octaves.
        """
        coarse = levels[level - 2].spacing_km * 1e3
        own = cls.of_level(levels, level - 1, master_seed, level_finest_m(coarse))
        return replace(
            own, coarser=cls.for_parent(levels, level - 1, master_seed) if level > 2 else None
        )

    def octaves(self) -> tuple[int, list[tuple[float, float]]]:
        """The index of this warp's first octave in the shared sequence, and its octaves."""
        sequence: list[tuple[float, float]] = []
        wavelength = self.top_m
        while wavelength >= self.finest_m:
            sequence.append((wavelength, RELIEF_WARP_STEEPNESS * wavelength))
            wavelength /= 2
        first = sum(1 for w, _ in sequence if w >= self.coarsest_m)
        return first, sequence[first:]

    @property
    def reach_m(self) -> float:
        """No point moves further than this (value noise slopes stay below 6.5)."""
        return 6.5 * sum(amplitude for _, amplitude in self.octaves()[1])

    def __call__(self, xyz: F64, radius_m: float) -> F64:
        first, octaves = self.octaves()
        return swirl(xyz, radius_m, octaves, self.seed, first)

    def planet_points(self, xyz: F64, radius_m: float) -> F64:
        """Where ``xyz`` lies in the planet's relief, through this warp and the coarser ones.

        A level parent samples the coarser level's blend through its warp, and
        that level's tiles stood on a parent that sampled the level above
        through the coarser warp, down to level 1. A river that level 1 cuts
        along a planet link therefore lies, at a finer level, where these warps
        carry points onto that link.
        """
        moved = self(xyz, radius_m)
        return moved if self.coarser is None else self.coarser.planet_points(moved, radius_m)


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
