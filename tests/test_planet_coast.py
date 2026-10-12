# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Regional coast detail: bounded, nested, deterministic and joined at the seam."""

from math import sqrt

import numpy as np
import pytest
import shapely
from scipy.ndimage import gaussian_filter
from shapely.geometry import Polygon
from shapely.ops import unary_union

from benchmarks.planet.synthetic_world import WorldSpec, build_world
from dmtools.terrain.application.world import open_world
from dmtools.terrain.pipeline.planet_coast import Coastline, coastline
from dmtools.terrain.pipeline.planet_forcing import source_xy
from dmtools.terrain.pipeline.planet_patch import inverse_aeqd
from dmtools.terrain.pipeline.world import WorldMap

SEED = 20261006


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> WorldMap:
    folder = tmp_path_factory.mktemp("w")
    return open_world(build_world(WorldSpec(seed=7, columns=512), folder, "w"))


def _drawn(world: WorldMap, xyz: np.ndarray) -> np.ndarray:
    land = unary_union([Polygon(c.exterior, c.holes) for v in world.land for c in v.components])
    x, y = source_xy(world.project.frame, xyz)
    return np.asarray(shapely.contains_xy(land, x, y), dtype=bool)


def _reach_m(coast: Coastline, finest_m: float, coarsest_m: float = np.inf) -> float:
    """Largest displacement the octaves between the two wavelengths can make."""
    return sqrt(3) * sum(a for w, a in coast.octaves(finest_m) if w < coarsest_m)


def _sphere(count: int, seed: int) -> np.ndarray:
    p = np.random.default_rng(seed).normal(size=(count, 3))
    return p / np.linalg.norm(p, axis=1, keepdims=True)


def _coast_point(world: WorldMap) -> tuple[float, float]:
    frame = world.project.frame
    ring = max((c.exterior for v in world.land for c in v.components), key=len)
    x, y = ring[len(ring) // 3]
    lon = (x - frame.bounds[0]) / frame.width * 360 - 180 + frame.central_meridian_deg
    return lon, 90 - (y - frame.bounds[1]) / frame.height * 180


def test_detail_stays_within_reach_of_the_drawn_coast(world: WorldMap) -> None:
    coast = coastline(world)
    finest = 2_000.0
    xyz = _sphere(40_000, 1)
    xyz = xyz[np.abs(xyz[:, 2]) < 0.85]  # keep the frame's x scale within 2x of y
    moved = coast.displaced(xyz, finest, 5)
    radius = world.project.frame.radius_km * 1e3
    assert np.all(radius * np.arccos(np.clip(np.sum(moved * xyz, 1), -1, 1)) <= _reach_m(
        coast, finest) + 1e-6)
    # Beyond the reach and the smoothing, land is exactly the drawn land.
    x, y = source_xy(world.project.frame, xyz)
    edge = shapely.boundary(
        unary_union([Polygon(c.exterior, c.holes) for v in world.land for c in v.components])
    )
    units = shapely.distance(edge, shapely.points(x, y))
    far = units > 2 * _reach_m(coast, finest) / coast.unit_m + 1.0
    assert far.mean() > 0.5
    refined = coast.contains(xyz, finest, SEED)
    assert np.array_equal(refined[far], _drawn(world, xyz)[far])


def test_finer_levels_only_add_detail_to_the_coast_above(world: WorldMap) -> None:
    coast = coastline(world)
    radius = world.project.frame.radius_km * 1e3
    xyz = _sphere(20_000, 2)
    coarse, fine = coast.displaced(xyz, 10_000.0, 9), coast.displaced(xyz, 400.0, 9)
    shift = radius * np.arccos(np.clip(np.sum(coarse * fine, 1), -1, 1))
    assert shift.max() <= _reach_m(coast, 400.0, coarsest_m=10_000.0) + 1e-6
    assert _reach_m(coast, 400.0, coarsest_m=10_000.0) < 0.2 * _reach_m(coast, 10_000.0)


def _roughness(mask: np.ndarray) -> int:
    """Cells a 4-pixel blur and re-threshold would flip: few for a smooth curve."""
    grid = mask.reshape(200, 200).astype(float)
    return int((grid != (gaussian_filter(grid, 4) > 0.5)).sum())


def test_coast_is_deterministic_and_rugged_at_every_zoom(world: WorldMap) -> None:
    coast = coastline(world)
    radius = world.project.frame.radius_km * 1e3
    lon, lat = _coast_point(world)
    for half_m in (20e3, 60e3):
        side = np.linspace(-half_m, half_m, 200)
        gx, gy = np.meshgrid(side, side)
        xyz = inverse_aeqd(gx.ravel(), gy.ravel(), lon, lat, radius)
        finest = 3 * 2 * half_m / 200
        refined = coast.contains(xyz, finest, SEED)
        assert np.array_equal(refined, coast.contains(xyz, finest, SEED))
        assert not np.array_equal(refined, coast.contains(xyz, finest, SEED + 1))
        drawn = _drawn(world, xyz)
        assert 0 < drawn.mean() < 1 and 0 < refined.mean() < 1
        assert _roughness(refined) > 3 * _roughness(drawn)


def test_land_cut_by_the_frame_stays_joined_across_the_seam(world: WorldMap) -> None:
    coast = coastline(world)
    seam = np.radians(world.project.frame.central_meridian_deg + 180)
    lat = np.radians(np.linspace(-80, 80, 2_000))
    sides = [
        np.stack([np.cos(lat) * np.cos(seam + d), np.cos(lat) * np.sin(seam + d), np.sin(lat)], 1)
        for d in (-1e-7, 1e-7)
    ]
    west, east = (coast.contains(side, 1_000.0, SEED) for side in sides)
    assert west.any()
    assert (west == east).mean() > 0.995
