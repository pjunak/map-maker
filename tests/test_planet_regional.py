# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Regional planet detail: parent consistency, window independence, builds and cache."""

from pathlib import Path

import numpy as np
import pytest

from benchmarks.planet.synthetic_world import WorldSpec, build_world
from dmtools.terrain.adapters.planet_region import RegionWindow
from dmtools.terrain.application.world import open_world
from dmtools.terrain.domain.planet import PlanetSettings, RegionalSettings
from dmtools.terrain.pipeline.planet import PlanetResult, generate_planet
from dmtools.terrain.pipeline.planet_metrics import non_descending_receivers
from dmtools.terrain.pipeline.planet_regional import (
    RegionalParent,
    enrich,
    inverse_aeqd,
    regional_mesh,
)
from dmtools.terrain.pipeline.planet_tiles import TileGrid, TileSurface, blend, generate_tile


@pytest.fixture(scope="module")
def parent(tmp_path_factory: pytest.TempPathFactory) -> PlanetResult:
    folder = tmp_path_factory.mktemp("w")
    world = open_world(build_world(WorldSpec(seed=7, columns=512), folder, "w"))
    settings = PlanetSettings(nodes=20_000, duration_myr=6.0, step_kyr=250.0, climate_passes=0)
    return generate_planet(world, settings)


def _land_centre(parent: PlanetResult) -> tuple[float, float]:
    deepest = int(np.argmax(np.where(parent.land, parent.coast_m, -1)))
    x, y, z = parent.mesh.xyz[deepest]
    return float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(z)))


def test_inverse_aeqd_preserves_distance_from_the_centre() -> None:
    radius = 6.371e6
    x = np.array([0.0, 300e3, -200e3, 0.0])
    y = np.array([0.0, 0.0, 400e3, -800e3])
    xyz = inverse_aeqd(x, y, 30.0, -40.0, radius)
    centre = xyz[0]
    distance = radius * np.arccos(np.clip(xyz @ centre, -1, 1))
    assert distance == pytest.approx(np.hypot(x, y), abs=1e-3)


def test_regional_relief_matches_its_parent_at_parent_scale(parent: PlanetResult) -> None:
    lon, lat = _land_centre(parent)
    region = regional_mesh(lon, lat, 600, 20, parent.mesh.radius_m, 1)
    assert region.boundary.sum() > 50 and np.all(np.hypot(*region.plane_m.T) <= 600e3 + 1)
    # Multi-scale parent forcing starts the coarse (20k-node) fixture further from
    # its parent; it still converges (394 -> 163 -> 102 -> 68 m over 6 iterations).
    result = enrich(
        RegionalParent.from_result(parent), region, process_area_km2=2_000, iterations=4, seed=1
    )
    first, last = result.history[0], result.history[-1]
    assert last["rms_vs_parent_m"] < first["rms_vs_parent_m"]
    assert abs(last["mean_bias_m"]) < 0.1 * max(last["mean_m"], 1.0)
    assert last["rms_vs_parent_m"] < 0.4 * first["rms_vs_parent_m"]
    fixed = ~result.land | region.boundary
    assert non_descending_receivers(result.elevation_m, result.run.flow.receiver, fixed) == 0
    # Boundary land stays at the parent's surface.
    edge = region.boundary & result.land
    assert np.allclose(result.elevation_m[edge], np.maximum(result.target_m[edge], 1.0))


def test_tiles_are_window_independent_and_blend_to_a_partition_of_unity(
    parent: PlanetResult,
) -> None:
    radius = parent.mesh.radius_m
    settings = RegionalSettings(
        spacing_km=30, process_area_km2=3_000, calibration_iterations=1, tile_km=1500,
        halo_km=200,
    )
    grid = TileGrid.for_planet(radius, settings)
    source = RegionalParent.from_result(parent)
    lon, lat = _land_centre(parent)
    points = inverse_aeqd(np.linspace(-500e3, 500e3, 30), np.zeros(30), lon, lat, radius)
    ids, weights = grid.weights(points)
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert set(grid.tiles_for(points)) <= set(grid.tiles_near((lon, lat), 500e3))
    tile = int(ids[0, np.argmax(weights[0])])
    a = generate_tile(source, grid, tile, settings)
    b = generate_tile(source, grid, tile, settings)
    assert np.array_equal(a.elevation_m, b.elevation_m)
    tiles = {
        t: TileSurface.from_result(generate_tile(source, grid, t, settings))
        for t in grid.tiles_for(points)
    }
    values = blend(grid, tiles, points)
    assert np.all(np.isfinite(values))
    # Any subset of points reproduces exactly the same blended values.
    assert np.array_equal(blend(grid, tiles, points[5:12]), values[5:12])
    with pytest.raises(ValueError, match="not available"):
        blend(grid, {}, points)


def test_region_build_reuses_cached_tiles_and_publishes_a_manifest(
    parent: PlanetResult, tmp_path: Path
) -> None:
    import json

    from dmtools.terrain.application.planet import export_planet, generate_planet_run
    from dmtools.terrain.application.planet_region import build_region

    run = generate_planet_run(
        parent.world.project, None, parent.settings, preview_width=0
    )
    planet = export_planet(run, tmp_path / "planet", width=256).parent
    settings = RegionalSettings(
        spacing_km=30, process_area_km2=3_000, calibration_iterations=1, tile_km=1500,
        halo_km=200,
    )
    lon, lat = _land_centre(parent)
    cache = tmp_path / "tiles"
    first = build_region(
        planet, tmp_path / "a", (lon, lat), 400, settings, cache=cache, pixels=128, workers=1
    )
    stored = sorted(cache.rglob("tile-*.npz"))
    stamps = [p.stat().st_mtime_ns for p in stored]
    second = build_region(
        planet, tmp_path / "b", (lon, lat), 400, settings, cache=cache, pixels=128, workers=1
    )
    assert [p.stat().st_mtime_ns for p in sorted(cache.rglob("tile-*.npz"))] == stamps
    a = json.loads(first.read_text(encoding="utf-8"))
    b = json.loads(second.read_text(encoding="utf-8"))
    assert a["region_sha256"] == b["region_sha256"]
    assert a["tiles"] and set(a["outputs"]) >= {"elevation.tif", "relief.png"}
    from jsonschema import Draft202012Validator

    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/world/planet-region-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(a)
    with pytest.raises(FileExistsError):
        build_region(planet, tmp_path / "a", (lon, lat), 400, settings, cache=cache)


def test_young_landforms_are_lifted_off_the_eroded_surface_and_saved(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from dataclasses import replace

    from dmtools.terrain.adapters.planet_load import read_planet_parent
    from dmtools.terrain.application.planet import export_planet, generate_planet_run
    from dmtools.terrain.domain.wonders import WONDER_KINDS

    settings = replace(parent.settings, wonders=WONDER_KINDS)
    run = generate_planet_run(parent.world.project, None, settings, preview_width=0)
    result = run.result
    regional = RegionalParent.from_result(result)
    young = regional.young_m()
    # Regional erosion starts from the surface without volcanoes and wonders, which
    # windows draw back sharply (erosion would fill a crater or a chasm).
    assert np.allclose(young, np.where(result.land, result.volcanic_m + result.wonder_m, 0.0))
    wonders = result.wonders
    assert len(wonders.craters) >= 1 and len(wonders.chasms) >= 1
    assert np.any(result.wonder_m < 0)
    loaded = read_planet_parent(export_planet(run, tmp_path / "planet", width=128).parent)
    reloaded = loaded.parent.wonders
    assert reloaded is not None
    assert np.allclose(reloaded.craters.xyz, wonders.craters.xyz)
    assert len(reloaded.chasms) == len(wonders.chasms)
    for a, b, c, d in zip(
        reloaded.chasms.paths, wonders.chasms.paths,
        reloaded.chasms.depth_m, wonders.chasms.depth_m, strict=True,
    ):
        assert np.allclose(a, b) and np.allclose(c, d)
    assert len(wonders.cliffs) == 1 and len(wonders.tepuis) >= 1
    for a, b in zip(reloaded.cliffs.paths, wonders.cliffs.paths, strict=True):
        assert np.allclose(a, b)
    assert np.allclose(reloaded.cliffs.height_m, wonders.cliffs.height_m)
    assert np.allclose(reloaded.tepuis.xyz, wonders.tepuis.xyz)
    assert np.allclose(reloaded.tepuis.aspect, wonders.tepuis.aspect)
    assert len(wonders.eruptions) == 1
    assert len(reloaded.eruptions.flows) == len(wonders.eruptions.flows)
    assert np.allclose(reloaded.eruptions.vent_xyz, wonders.eruptions.vent_xyz)
    assert np.allclose(reloaded.eruptions.flow_fresh, wonders.eruptions.flow_fresh)
    assert np.allclose(loaded.parent.young_m(), young, atol=0.1)


def test_world_path_fixture_is_reusable(tmp_path: Path) -> None:
    assert build_world(WorldSpec(seed=3, columns=256), tmp_path, "x").exists()


def test_display_valley_carving_only_lowers_land_and_keeps_outlets() -> None:
    from dmtools.terrain.pipeline.planet_detail import carve_valleys

    rows = columns = 64
    rng = np.random.default_rng(3)
    _, x = np.mgrid[0:rows, 0:columns]
    z = 20.0 * x + 150.0 * rng.random((rows, columns))
    outlet = np.zeros((rows, columns), dtype=bool)
    outlet[:, 0] = True
    z[outlet] = 0.0
    dx = np.full(rows, 500.0)
    carved = carve_valleys(z, outlet, 500.0, dx, 0.4, 0.5, 3)
    again = carve_valleys(z, outlet, 500.0, dx, 0.4, 0.5, 3)
    assert np.array_equal(carved, again)
    assert np.all(np.isfinite(carved))
    assert np.array_equal(carved[outlet], z[outlet])
    # Depressions are filled before carving, so a cell may rise to its spill level
    # but never above the highest original cell; incision lowers most of the land.
    assert carved.max() <= z.max() + 1e-6
    assert np.mean(carved[~outlet] < z[~outlet]) > 0.5


def test_grid_carving_matches_the_mesh_kernels_and_wraps_longitude() -> None:
    from dmtools.terrain.pipeline.planet_detail import carve_valleys
    from dmtools.terrain.pipeline.planet_kernels import (
        accumulate,
        priority_flood,
        steepest_receivers,
        stream_power_implicit,
    )

    rows = columns = 24
    cell = 500.0
    rng = np.random.default_rng(1)
    z = rng.random((rows, columns)) * 300 + np.arange(columns)[None, :] * 30
    outlet = np.zeros((rows, columns), dtype=bool)
    outlet[:, 0] = True
    z[outlet] = 0.0
    # Reference: the same steps on an explicit 8-neighbour CSR graph.
    index = np.arange(rows * columns).reshape(rows, columns)
    edges: list[tuple[int, int, float]] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                r0, r1 = max(0, -dr), rows - max(0, dr)
                c0, c1 = max(0, -dc), columns - max(0, dc)
                here = index[r0:r1, c0:c1].ravel()
                there = index[r0 + dr : r1 + dr, c0 + dc : c1 + dc].ravel()
                edges += [
                    (int(a), int(b), cell * float(np.hypot(dr, dc)))
                    for a, b in zip(here, there, strict=True)
                ]
    edges.sort(key=lambda edge: edge[0])
    ptr = np.searchsorted([e[0] for e in edges], np.arange(rows * columns + 1)).astype(np.int64)
    nbr = np.array([e[1] for e in edges], dtype=np.int64)
    length = np.array([e[2] for e in edges])
    fixed = outlet.ravel()
    land = np.flatnonzero(~fixed)
    h = z.ravel().copy()
    for _ in range(3):
        filled, parent = priority_flood(h, fixed, ptr, nbr, 1e-3)
        receiver, distance = steepest_receivers(filled, fixed, ptr, nbr, length, parent)
        order = land[np.argsort(filled[land], kind="stable")]
        area = accumulate(order, receiver, fixed, np.full(h.size, cell * cell))
        h = stream_power_implicit(
            filled, order, receiver, distance, fixed, area, np.full(h.size, 0.4), 0.5,
            np.zeros(h.size), 1.0,
        )
    carved = carve_valleys(z, outlet, cell, np.full(rows, cell), 0.4, 0.5, 3)
    np.testing.assert_allclose(carved, h.reshape(rows, columns), atol=1e-9)
    # With wrapping, shifting the map in longitude shifts the result unchanged.
    shifted = carve_valleys(
        np.roll(z, 7, axis=1), np.roll(outlet, 7, axis=1), cell, np.full(rows, cell), 0.4, 0.5,
        3, wrap=True,
    )
    wrapped = carve_valleys(z, outlet, cell, np.full(rows, cell), 0.4, 0.5, 3, wrap=True)
    np.testing.assert_allclose(shifted, np.roll(wrapped, 7, axis=1), atol=1e-9)


def test_regional_parent_reports_lake_cover_and_level(parent: PlanetResult) -> None:
    regional = RegionalParent.from_result(parent)
    lakes = parent.lakes
    cover, level, closed = regional.lakes_at(parent.mesh.xyz)
    on_lake = lakes.lake >= 0
    if on_lake.any():
        assert np.all(cover[on_lake] > 0.99)
        assert np.allclose(level[on_lake], lakes.level_m[lakes.lake[on_lake]])
        assert np.array_equal(closed[on_lake], lakes.endorheic[lakes.lake[on_lake]])
    assert np.all(cover[~on_lake & parent.land] < 1.0 + 1e-9)


def test_meanders_keep_river_ends_and_wind_the_middle() -> None:
    from dmtools.terrain.adapters.planet_natural import meander

    path = np.stack((np.linspace(0, 400, 50), np.full(50, 100.0)), axis=1)
    wound = meander(path, np.full(50, 40.0), 3, np.array([0.5]))
    assert np.allclose(wound[0], path[0]) and np.allclose(wound[-1], path[-1], atol=1.5)
    middle = int(0.5 * len(wound))
    assert abs(wound[middle, 1] - 100.0) < 6.0  # pinned at the junction
    length = np.hypot(*np.diff(wound, axis=0).T).sum()
    assert 1.15 < length / 400 < 3.0  # sinuosity of a meandering river


def test_grid_flow_drains_every_cell_and_counts_inflow() -> None:
    from dmtools.terrain.pipeline.planet_detail import grid_flow

    rows = columns = 30
    _, x = np.mgrid[0:rows, 0:columns]
    z = 10.0 * x + np.random.default_rng(4).random((rows, columns))
    outlet = np.zeros((rows, columns), dtype=bool)
    outlet[:, 0] = True
    inflow = np.zeros((rows, columns))
    inflow[15, -1] = 1e9
    receiver, area, filled = grid_flow(z, outlet, 100.0, inflow)
    assert np.all(filled >= z - 1e-9)
    land = ~outlet.ravel()
    assert np.all(receiver[land] >= 0)
    # Everything (cells plus inflow) reaches the outlets.
    into_outlet = land & outlet.ravel()[np.maximum(receiver, 0)]
    assert area[into_outlet].sum() == pytest.approx(land.sum() * 100.0**2 + 1e9, rel=1e-9)


def test_sand_seas_need_dry_flat_low_ground() -> None:
    from dmtools.terrain.adapters.planet_natural import PixelClimate, erg_cover

    rng = np.random.default_rng(5)
    points = rng.normal(size=(400, 3))
    points /= np.linalg.norm(points, axis=1)[:, None]
    shape = (20, 20)
    flat, steep = np.zeros(shape), np.full(shape, 0.2)
    low = np.full(shape, -0.8)

    def climate(precipitation: float) -> PixelClimate:
        full = np.full(shape, 1.0)
        return PixelClimate(25 * full, 32 * full, precipitation * full, 1800 * full)

    dry = erg_cover(points, 6.0e6, climate(30.0), flat, low)
    assert dry.max() > 0.5
    assert np.all(erg_cover(points, 6.0e6, climate(30.0), steep, low) < 1e-9)
    assert np.all(erg_cover(points, 6.0e6, climate(900.0), flat, low) < 1e-9)


TINY_LEVELS = (
    RegionalSettings(
        spacing_km=30, process_area_km2=3_000, calibration_iterations=1, tile_km=1500,
        halo_km=200,
    ),
    RegionalSettings(
        spacing_km=10, process_area_km2=300, calibration_iterations=2, tile_km=300,
        halo_km=60,
    ),
)


def test_detail_levels_have_their_own_seeds() -> None:
    from dmtools.terrain.domain.planet import REGION_LEVELS, tile_stage_prefix
    from dmtools.terrain.domain.seeds import stage_seed
    from dmtools.terrain.pipeline.planet_tiles import tile_seed

    assert tile_stage_prefix(1) == "planet.tile."
    assert len({tile_stage_prefix(level) for level in (1, 2, 3)}) == 3
    assert len({tile_seed(7, 5, level) for level in (1, 2, 3)}) == 3
    assert tile_seed(7, 5) == stage_seed(7, "planet.tile.5")
    spacings = [settings.spacing_km for settings in REGION_LEVELS]
    assert spacings == sorted(spacings, reverse=True)


def test_level_parent_carries_the_coarser_relief_and_drains(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from dmtools.terrain.application.planet_region import ensure_level_tiles
    from dmtools.terrain.pipeline.planet_levels import level_parent

    planet = RegionalParent.from_result(parent)
    centre = _land_centre(parent)
    grid = TileGrid.for_planet(parent.mesh.radius_m, TINY_LEVELS[0])
    needed = grid.tiles_near(centre, 500e3)
    grid, tiles = ensure_level_tiles(
        planet, "p" * 64, tmp_path, 1, needed, TINY_LEVELS, workers=1
    )
    patch = level_parent(planet, grid, tiles, centre, 300e3, 30.0, 11)
    land = patch.land
    assert land.any()
    coarse = blend(grid, tiles, patch.mesh.xyz)
    assert np.allclose(patch.surface_m[land], np.maximum(coarse[land], 1.0))
    assert np.all(patch.young_m() == 0.0)
    # Every land node drains except the rim ring, which is the patch's outlet.
    descending = patch.receiver[land] >= 0
    assert descending.mean() > 0.75
    assert np.all(patch.area_m2[land & (patch.receiver >= 0)] > 0)


def test_level_two_windows_repeat_exactly_and_agree_with_level_one(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from dmtools.terrain.application.planet_region import region_window

    planet = RegionalParent.from_result(parent)
    centre = _land_centre(parent)

    def window(level: int) -> np.ndarray:
        run = region_window(
            planet, "p" * 64, tmp_path, centre, 200.0, level=level, levels=TINY_LEVELS,
            pixels=96, workers=1,
        )
        assert run.level == level
        return run.window.elevation_m

    fine, again = window(2), window(2)
    assert np.array_equal(fine, again, equal_nan=True)
    coarse = window(1)
    inside = np.isfinite(fine) & np.isfinite(coarse) & (coarse > 0)
    assert inside.mean() > 0.3
    # The finer level adds detail but keeps the coarser level's broad relief.
    from scipy.ndimage import gaussian_filter

    def smooth(values: np.ndarray) -> np.ndarray:
        # At the coarse level's own scale (its 30 km spacing is about 7 pixels).
        return gaussian_filter(np.where(inside, values, 0.0), 8) / np.maximum(
            gaussian_filter(inside * 1.0, 8), 1e-6
        )

    error = (smooth(fine) - smooth(coarse))[inside]
    assert np.sqrt(np.mean(error**2)) < 0.35 * np.std(coarse[inside]) + 50.0


def test_display_detail_is_world_anchored_and_shrinks_with_finer_levels(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from dataclasses import replace

    from dmtools.terrain.adapters.planet_region import detail_offset, display_relief
    from dmtools.terrain.application.planet_region import region_window
    from dmtools.terrain.pipeline.planet_detail import eroded_fbm
    from dmtools.terrain.pipeline.planet_mesh import fibonacci_nodes

    # The detail is zero-mean over the whole sphere, not re-centred per window.
    points = fibonacci_nodes(5_000, seed=3, jitter=0.5)
    for ridged in (0.0, 1.0):
        values = eroded_fbm(points, np.full(len(points), ridged), 99, 5, 200.0, 0.5, 0.1)
        offset = detail_offset(99, 200.0, np.full(len(points), ridged))
        assert abs(float(np.mean(values - offset))) < 0.03
    run = region_window(
        RegionalParent.from_result(parent), "p" * 64, tmp_path, _land_centre(parent), 200.0,
        levels=TINY_LEVELS, pixels=96, workers=1,
    )
    window = run.window
    land = window.land & np.isfinite(window.elevation_m)

    def added(spacing_m: float) -> float:
        relief = display_relief(replace(window, detail_spacing_m=spacing_m))
        return float(np.std((relief - window.elevation_m)[land]))

    assert added(1_000.0) < 0.5 * added(5_000.0)


def test_overlapping_windows_draw_the_same_rivers(parent: PlanetResult, tmp_path: Path) -> None:
    from scipy.ndimage import binary_dilation

    from dmtools.terrain.adapters.planet_region import forward_aeqd
    from dmtools.terrain.application.planet_region import region_window

    planet = RegionalParent.from_result(parent)
    lon, lat = _land_centre(parent)
    shifted = (lon + np.degrees(120e3 / (parent.mesh.radius_m * np.cos(np.radians(lat)))), lat)

    def window(centre: tuple[float, float]) -> RegionWindow:
        return region_window(
            planet, "p" * 64, tmp_path, centre, 300.0, levels=TINY_LEVELS, pixels=160,
            workers=1, river_km2=500.0,
        ).window

    a, b = window((lon, lat)), window(shifted)
    rivers_b = b.rivers > 0.5
    # B's river pixels in A's grid, away from both windows' edges.
    x, y = forward_aeqd(b.points, *a.centre, a.planet_m).T
    column = np.round((x + a.radius_m) / a.pixel_m - 0.5).astype(int)
    row = np.round((a.radius_m - y) / a.pixel_m - 0.5).astype(int)
    xb, yb = forward_aeqd(b.points, *b.centre, b.planet_m).T
    # Where they overlap near either window's edge, where routing used to start:
    # unpadded routing agreed on about 92 % of river pixels here, padded about 96 %.
    ra, rb = np.hypot(x, y) / a.radius_m, np.hypot(xb, yb) / b.radius_m
    edge = (ra < 0.98) & (rb < 0.98) & ((ra > 0.75) | (rb > 0.75))
    check = rivers_b.ravel() & edge
    assert check.sum() > 20
    near_a = binary_dilation(a.rivers > 0.5, iterations=2)
    assert near_a[row[check], column[check]].mean() > 0.94
