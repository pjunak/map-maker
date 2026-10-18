# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Regional planet detail: parent consistency, window independence, builds and cache."""

from pathlib import Path

import numpy as np
import pytest

from benchmarks.planet.synthetic_world import WorldSpec, build_world
from map_maker.terrain.adapters.planet_region import RegionWindow, WindowFlow
from map_maker.terrain.application.world import open_world
from map_maker.terrain.domain.planet import PlanetSettings, RegionalSettings
from map_maker.terrain.pipeline.planet import PlanetResult, generate_planet
from map_maker.terrain.pipeline.planet_metrics import non_descending_receivers
from map_maker.terrain.pipeline.planet_patch import inverse_aeqd, regional_mesh
from map_maker.terrain.pipeline.planet_regional import RegionalParent, enrich
from map_maker.terrain.pipeline.planet_tiles import (
    ReliefWarp,
    TileGrid,
    TileSurface,
    blend,
    generate_tile,
)


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

    from map_maker.terrain.application.planet import export_planet, generate_planet_run
    from map_maker.terrain.application.planet_region import build_region

    run = generate_planet_run(
        parent.world.project, None, parent.settings
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
    from map_maker.terrain.adapters.planet_load import read_planet_parent
    from map_maker.terrain.application.planet import export_planet, generate_planet_run
    from map_maker.terrain.domain.wonders import WONDER_KINDS, WonderSettings

    run = generate_planet_run(
        parent.world.project, None, parent.settings,
        wonder_settings=WonderSettings(WONDER_KINDS),
    )
    result = run.result
    regional = RegionalParent.from_result(result)
    young = regional.young_m()
    # Regional erosion starts from the surface without volcanoes and wonders, which
    # windows draw back sharply (erosion would fill a crater or a chasm).
    assert np.allclose(young, np.where(
        result.land, result.volcanic_m + result.wonder_m + result.crater_floor_m, 0.0
    ))
    # Tiles come from the planet without wonders (ADR-0097).
    tiles = RegionalParent.tiles_from(run.base.planet)
    base = run.base.planet
    assert tiles.ice is None and not np.any(tiles.young_m() - np.where(
        base.land, base.volcanic_m, 0.0
    ))
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
    assert len(reloaded.oases) == len(wonders.oases)
    assert np.allclose(reloaded.oases.xyz, wonders.oases.xyz)
    assert len(wonders.forks) == 1
    assert np.allclose(reloaded.forks.branch_xyz, wonders.forks.branch_xyz)
    assert np.allclose(reloaded.forks.area_m2, wonders.forks.area_m2)
    assert np.allclose(loaded.parent.young_m(), young, atol=0.1)
    # The build keeps the base fields that tiles are enriched from.
    assert loaded.base_sha256 == run.base_sha256
    assert loaded.tiles.wonders is None and loaded.tiles.crater_floor_m is None
    assert np.allclose(loaded.tiles.surface_m, tiles.surface_m, atol=0.1)
    assert np.array_equal(loaded.tiles.receiver, tiles.receiver)
    assert np.allclose(loaded.tiles.young_m(), tiles.young_m(), atol=0.1)


def test_world_path_fixture_is_reusable(tmp_path: Path) -> None:
    assert build_world(WorldSpec(seed=3, columns=256), tmp_path, "x").exists()


def test_display_valley_carving_only_lowers_land_and_keeps_outlets() -> None:
    from map_maker.terrain.pipeline.planet_detail import carve_valleys

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
    from map_maker.terrain.pipeline.planet_detail import carve_valleys
    from map_maker.terrain.pipeline.planet_kernels import (
        accumulate,
        priority_flood,
        steepest_receivers,
        stream_power_implicit,
    )

    rows = columns = 24
    cell = 500.0
    rng = np.random.default_rng(1)
    # Ground without depressions, where the grid and mesh routings agree (the
    # grid routes filled hollows along their thalweg; see the test below).
    z = rng.random((rows, columns)) * 20 + np.arange(columns)[None, :] * 30
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
    on_lake = lakes.lake >= 0
    assert on_lake.any()
    # Without outline detail the cover is the parent's triangle-linear one.
    cover, level, closed = regional.lakes_at(parent.mesh.xyz, np.inf)
    assert np.all(cover[on_lake] > 0.99)
    assert np.allclose(level[on_lake], lakes.level_m[lakes.lake[on_lake]])
    assert np.array_equal(closed[on_lake], lakes.endorheic[lakes.lake[on_lake]])
    assert np.all(cover[~on_lake & parent.land] < 1.0 + 1e-9)
    # Outline detail moves shores by a fraction of the spacing, and finer detail
    # only adds smaller moves, so each level refines the outline of the one above.
    node = parent.mesh.xyz[np.flatnonzero(on_lake)[0]]
    lon, lat = np.degrees(np.arctan2(node[1], node[0])), np.degrees(np.arcsin(node[2]))
    x, y = np.meshgrid(*(np.linspace(-1.5, 1.5, 61) * parent.mesh.spacing_m,) * 2)
    points = inverse_aeqd(x.ravel(), y.ravel(), float(lon), float(lat), parent.mesh.radius_m)
    exact = regional.lakes_at(points, np.inf)[0] > 0.5
    coarse = regional.lakes_at(points, 0.5 * parent.mesh.spacing_m)[0] > 0.5
    fine = regional.lakes_at(points, 0.05 * parent.mesh.spacing_m)[0] > 0.5
    assert 0 < np.mean(coarse != exact) < 0.25
    assert np.mean(fine != coarse) < np.mean(coarse != exact)


def test_world_maps_draw_lakes_with_the_refined_outlines(parent: PlanetResult) -> None:
    from map_maker.terrain.adapters.planet_render import (
        LAKE_REACH_SPACINGS,
        FrameRaster,
        lake_raster,
    )
    from map_maker.terrain.pipeline.planet_lakes import refined_lake_cover

    raster = FrameRaster.build(parent.mesh, parent.world.project.frame, 1024)
    land = np.ones(raster.shape, dtype=bool)
    ids = lake_raster(parent, raster, land)
    straight = raster.interpolate(parent.mesh, (parent.lakes.lake >= 0).astype(np.float64)) > 0.5
    on_lake = ids >= 0
    # The outlines leave the straight triangle contours only near shores...
    changed = on_lake != straight
    assert 0 < changed.sum() < 0.5 * straight.sum()
    nodes = parent.mesh.xyz[parent.lakes.lake >= 0]
    distance = np.min(
        np.linalg.norm(raster.queries[changed.ravel()][:, None] - nodes[None], axis=2), axis=1
    )
    assert np.all(distance < LAKE_REACH_SPACINGS * parent.mesh.spacing_m / parent.mesh.radius_m)
    # ...and are the regional outline at the map's own detail, so zooming refines it.
    detail_m = 2 * 2 * np.pi * parent.mesh.radius_m / raster.shape[1]
    cover, _ = refined_lake_cover(
        parent.mesh, parent.lakes.lake, parent.settings.seed, raster.queries, detail_m
    )
    near = on_lake | changed
    assert np.array_equal(on_lake[near], (cover.reshape(raster.shape) > 0.5)[near])
    assert np.array_equal(lake_raster(parent, raster, land), ids)


def test_regional_rivers_are_as_wide_as_their_channels() -> None:
    from map_maker.terrain.adapters.planet_region import (
        CHANNEL_WIDTH_PER_ROOT_Q,
        MEAN_RUNOFF_M_YR,
        WindowFlow,
        window_rivers,
    )

    n = 200
    rows, columns = np.mgrid[0:n, 0:n].astype(np.float64)
    area = 1e12  # a million square kilometres entering at the top of the valley

    def width(pixel_m: float, bigger: bool = False) -> float:
        # Steep valleys (no meanders) running down the map at columns 60 and 150.
        z = 5000.0 - rows * 10.0 + np.minimum(np.abs(columns - 60), np.abs(columns - 150))
        inflow = np.zeros((n, n))
        inflow[0, 60] = area
        if bigger:
            inflow[0, 150] = 30 * area
        flow = WindowFlow.route(z, rows == n - 1, pixel_m, inflow)
        cover = window_rivers(flow, np.zeros((n, n), dtype=bool), 2_000.0)
        return float(cover[n // 2, 20:85].sum())

    channel_m = CHANNEL_WIDTH_PER_ROOT_Q * np.sqrt(area * MEAN_RUNOFF_M_YR / 3.156e7)
    fine = width(20.0)
    assert abs(fine - channel_m / 20.0) < 2.0  # about 23 pixels: the channel itself
    assert 0.3 < width(2_000.0) < 1.5  # a visible line where the channel is sub-pixel
    # A larger river elsewhere in the window does not narrow this one.
    assert width(20.0, bigger=True) == pytest.approx(fine, abs=0.5)


def _winding_valley() -> tuple[WindowFlow, float, float, list[int]]:
    """A big river routed down a gently sloping, winding valley with a noisy floor.

    Returns the window flow, the channel width and the valley length (pixels),
    and the river's pixel path. The noise gives the pixel path the zigzags and
    filled hollows of real regional relief.
    """
    from map_maker.terrain.adapters.planet_region import (
        CHANNEL_WIDTH_PER_ROOT_Q,
        MEAN_RUNOFF_M_YR,
    )

    n, pixel_m, area = 400, 40.0, 2.6e11
    rows, columns = np.mgrid[0:n, 0:n].astype(np.float64)
    axis = 200.0 + 60.0 * np.sin(2 * np.pi * rows / 300.0)
    z = (
        500.0 - 2e-4 * pixel_m * rows + 0.01 * pixel_m * np.abs(columns - axis)
        + np.random.default_rng(5).random((n, n)) * 0.5
    )
    inflow = np.zeros((n, n))
    start = round(axis[0, 0])
    inflow[0, start] = area
    flow = WindowFlow.route(z, rows == n - 1, pixel_m, inflow)
    width = CHANNEL_WIDTH_PER_ROOT_Q * np.sqrt(area * MEAN_RUNOFF_M_YR / 3.156e7) / pixel_m
    valley = float(np.hypot(1.0, np.diff(axis[:, 0])).sum())
    node, chain = start, [start]
    while flow.receiver[node] >= 0:
        node = int(flow.receiver[node])
        chain.append(node)
    return flow, width, valley, chain


def test_meanders_follow_the_valley_without_crossing_themselves() -> None:
    from scipy.spatial import KDTree

    from map_maker.terrain.adapters.planet_natural import meander

    flow, width, valley, chain = _winding_valley()
    n = flow.z.shape[0]
    steps = np.stack((np.array(chain) % n + 0.5, np.array(chain) // n + 0.5), axis=1)
    wavelength = 11 * width
    wound = meander(steps, np.full(len(steps), wavelength), 3)
    assert np.allclose(wound[0], steps[0]) and np.allclose(wound[-1], steps[-1])
    along = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(wound, axis=0).T))))
    # No two stretches of channel more than three widths apart along the river
    # come within a width of each other: the channel never crosses or touches itself.
    pairs = KDTree(wound).query_pairs(width, output_type="ndarray")
    assert not np.any(np.abs(along[pairs[:, 0]] - along[pairs[:, 1]]) > 3 * width)
    # It meanders (longer than its valley) but stays in the valley.
    assert 1.15 < along[-1] / valley < 2.5
    gap, _ = KDTree(steps).query(wound)
    assert gap.max() < 0.6 * wavelength


def test_wide_regional_rivers_draw_one_channel_as_wide_as_itself() -> None:
    from scipy.ndimage import label

    from map_maker.terrain.adapters.map_parchment import distance_transform_edt
    from map_maker.terrain.adapters.planet_region import window_rivers

    flow, width, valley, _ = _winding_valley()
    n = flow.z.shape[0]
    cover = window_rivers(flow, np.zeros((n, n), dtype=bool), 2_000.0)
    drawn = cover > 0.5
    # One channel, nowhere much wider than itself: tangled bends merged into
    # blobs many widths across.
    parts = np.zeros((n, n), dtype=np.int32)
    label(drawn, structure=np.ones((3, 3)), output=parts)
    assert parts.max() == 1
    assert 2 * float(distance_transform_edt(np.pad(drawn, 1)).max()) < 1.6 * width
    # Its area is a channel longer than the valley, not a self-overlapping one.
    assert 1.15 < float(cover.sum()) / (width * valley) < 2.5


def test_meanders_keep_river_ends_and_wind_the_middle() -> None:
    from map_maker.terrain.adapters.planet_natural import meander

    path = np.stack((np.linspace(0, 400, 50), np.full(50, 100.0)), axis=1)
    wound = meander(path, np.full(50, 40.0), 3, np.array([0.5]))
    assert np.allclose(wound[0], path[0]) and np.allclose(wound[-1], path[-1], atol=1.5)
    middle = int(0.5 * len(wound))
    assert abs(wound[middle, 1] - 100.0) < 6.0  # pinned at the junction
    length = np.hypot(*np.diff(wound, axis=0).T).sum()
    assert 1.15 < length / 400 < 3.0  # sinuosity of a meandering river


def test_grid_flow_drains_every_cell_and_counts_inflow() -> None:
    from map_maker.terrain.pipeline.planet_detail import grid_flow

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


def _straight_channel_share(receiver: np.ndarray, area: np.ndarray, min_area: float) -> float:
    """Share of channel cells whose next eight steps keep one grid direction."""
    channel = np.flatnonzero((area >= min_area) & (receiver >= 0))
    step = receiver[channel] - channel
    here, straight = channel, np.ones(len(channel), dtype=bool)
    for _ in range(8):
        nxt = receiver[here]
        straight &= (nxt >= 0) & (nxt - here == step)
        here = np.where(nxt >= 0, nxt, here)
    return float(straight.mean())


def test_grid_routing_follows_the_ground_through_filled_hollows() -> None:
    """Flow across a filled depression follows its thalweg, not straight grid lines.

    Steepest descent on the 1 mm fill gradient ran straight across every filled
    hollow from its spill point, and display carving cut those lines into plains
    as straight 0, 45 and 90 degree grooves.
    """
    from scipy.ndimage import gaussian_filter

    from map_maker.terrain.pipeline.planet_detail import grid_flow

    n, cell = 96, 500.0
    rng = np.random.default_rng(5)
    y, x = np.mgrid[0:n, 0:n] - (n - 1) / 2
    texture = gaussian_filter(rng.normal(size=(n, n)), 3.0)
    # A closed basin of rough ground: everything below its lowest rim point fills.
    z = 500.0 + 6.0 * np.hypot(x, y) + 25.0 * texture / texture.std()
    outlet = np.zeros((n, n), dtype=bool)
    outlet[[0, -1], :] = True
    outlet[:, [0, -1]] = True
    receiver, area, filled = grid_flow(z, outlet, cell, np.zeros((n, n)))
    land = ~outlet.ravel()
    assert np.mean((filled - z)[~outlet] > 0.01) > 0.5
    assert np.all(receiver[land] >= 0)
    into_outlet = land & outlet.ravel()[np.maximum(receiver, 0)]
    assert area[into_outlet].sum() == pytest.approx(land.sum() * cell**2, rel=1e-9)
    # Rough ground bends channels within a few cells; fill rings drew long
    # straight ones (about 60 % of channel cells here).
    assert _straight_channel_share(receiver, area, 50 * cell**2) < 0.2


def test_ridged_display_detail_is_continuous() -> None:
    """Ridged detail has sharp crests but no steps.

    Damping by the ridged gradient, which flips sign at every zero crossing,
    stepped all finer octaves there: sharp scarps along the value-noise lattice,
    seen as straight north-south and east-west lines on plains.
    """
    from map_maker.terrain.pipeline.planet_detail import eroded_fbm

    def largest_step(samples: int, ridged: float) -> float:
        # An arc of about 300 km on a 6,000 km planet, crossing many zero lines
        # of the coarse octaves (30 km wavelength).
        t = np.linspace(0.0, 0.05, samples)
        points = np.stack((np.cos(t), np.sin(t), np.full_like(t, 0.3)), axis=1)
        points /= np.linalg.norm(points, axis=1)[:, None]
        values = eroded_fbm(points, np.full(samples, ridged), 17, 5, 200.0, 0.5, 0.1)
        return float(np.abs(np.diff(values)).max())

    for ridged in (0.15, 0.5, 1.0):
        # A continuous field changes ten times less over ten times shorter steps.
        assert largest_step(200_001, ridged) < 0.3 * largest_step(20_001, ridged)


def test_sand_seas_need_dry_flat_low_ground() -> None:
    from map_maker.terrain.adapters.planet_natural import PixelClimate, erg_cover

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
    from map_maker.terrain.domain.planet import REGION_LEVELS, tile_stage_prefix
    from map_maker.terrain.domain.seeds import stage_seed
    from map_maker.terrain.pipeline.planet_tiles import tile_seed

    assert tile_stage_prefix(1) == "planet.tile."
    assert len({tile_stage_prefix(level) for level in (1, 2, 3)}) == 3
    assert len({tile_seed(7, 5, level) for level in (1, 2, 3)}) == 3
    assert tile_seed(7, 5) == stage_seed(7, "planet.tile.5")
    spacings = [settings.spacing_km for settings in REGION_LEVELS]
    assert spacings == sorted(spacings, reverse=True)


def test_tile_processes_match_one_process_and_leave_no_job_file(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from map_maker.terrain.application.planet_region import ensure_level_tiles

    planet = RegionalParent.from_result(parent)
    grid = TileGrid.for_planet(parent.mesh.radius_m, TINY_LEVELS[0])
    needed = grid.tiles_near(_land_centre(parent), 200e3)[:2]
    assert len(needed) == 2
    # Workers read the job (with its whole parent planet) from a file, not a pipe.
    _, pooled = ensure_level_tiles(
        planet, "p" * 64, tmp_path / "pool", 1, needed, TINY_LEVELS, workers=2
    )
    _, single = ensure_level_tiles(
        planet, "p" * 64, tmp_path / "one", 1, needed, TINY_LEVELS, workers=1
    )
    for tile in needed:
        assert np.array_equal(pooled[tile].elevation_m, single[tile].elevation_m)
    assert not list((tmp_path / "pool").rglob(".job-*"))


def test_level_parent_carries_the_coarser_relief_and_drains(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from dataclasses import replace

    from map_maker.terrain.application.planet_region import ensure_level_tiles
    from map_maker.terrain.pipeline.planet_levels import level_parent, level_parent_radius

    planet = RegionalParent.from_result(parent)
    centre = _land_centre(parent)
    grid = TileGrid.for_planet(parent.mesh.radius_m, TINY_LEVELS[0])
    relief = ReliefWarp.for_parent(TINY_LEVELS, 2, parent.settings.seed)
    needed = grid.tiles_near(
        centre, level_parent_radius(planet, 300e3, 30.0) + relief.reach_m
    )
    grid, tiles = ensure_level_tiles(
        planet, "p" * 64, tmp_path, 1, needed, TINY_LEVELS, workers=1
    )

    def uplift(xyz: np.ndarray) -> np.ndarray:
        return 1e-3 * (1 + np.sin(4.0 * xyz[:, 0]) * np.cos(3.0 * xyz[:, 1]))

    # A smooth uplift field, to see how planet forcing reaches the patch.
    forced = replace(planet, steady_uplift=uplift(parent.mesh.xyz))
    patch = level_parent(forced, grid, tiles, centre, 300e3, 30.0, 11, relief)
    land = patch.land
    assert land.any()
    coarse = blend(grid, tiles, relief(patch.mesh.xyz, parent.mesh.radius_m))
    # Tiles leave out young landforms; the patch carries them on top, as the planet
    # does, so its relief without them is the coarser level's.
    young = np.where(land, planet.sample(patch.mesh.xyz, planet.young_m()), 0.0)
    assert np.allclose(patch.young_m(), young)
    assert np.allclose(patch.surface_m - young, np.where(land, np.maximum(coarse, 1.0), 0.0))
    # Every land node drains except the rim ring, which is the patch's outlet.
    descending = patch.receiver[land] >= 0
    assert descending.mean() > 0.75
    assert np.all(patch.area_m2[land & (patch.receiver >= 0)] > 0)
    # Forcing comes onto the patch smoothly, as level 1 takes it: triangle-linear
    # sampling carried the planet's triangles down every level as straight creases.
    t = np.linspace(-3, 3, 1201) * parent.mesh.spacing_m
    line = inverse_aeqd(t, 0.3 * t, *centre, parent.mesh.radius_m)
    on_patch = patch.sample(line, patch.steady_uplift)
    linear = forced.sample(line, forced.steady_uplift)
    assert np.abs(on_patch - uplift(line)).mean() < 0.5 * np.abs(linear - uplift(line)).mean()
    # Basins stay on the planet mesh, so every level refines the same margins.
    points = patch.mesh.xyz[land]
    on_patch, on_planet = patch.basin_at(points, 20e3), planet.basin_at(points, 20e3)
    assert on_patch is not None and on_planet is not None
    assert np.array_equal(on_patch, on_planet)


def test_level_parents_are_as_warm_as_the_planet_at_every_height(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from dataclasses import replace

    from map_maker.terrain.application.planet_region import ensure_level_tiles
    from map_maker.terrain.pipeline.planet_levels import level_parent, level_parent_radius

    planet = RegionalParent.from_result(parent)
    # A climate that cools at the lapse rate with height, held at the planet
    # surface as a simulated climate is.
    lapse = planet.settings.climate.lapse_c_per_km
    ground = planet.surface_m - planet.young_m()
    planet = replace(
        planet,
        temperature_c=15.0 - lapse * ground / 1000,
        warm_season_c=25.0 - lapse * ground / 1000,
    )
    centre = _land_centre(parent)
    grid = TileGrid.for_planet(parent.mesh.radius_m, TINY_LEVELS[0])
    relief = ReliefWarp.for_parent(TINY_LEVELS, 2, parent.settings.seed)
    needed = grid.tiles_near(
        centre, level_parent_radius(planet, 300e3, 30.0) + relief.reach_m
    )
    grid, tiles = ensure_level_tiles(
        planet, "p" * 64, tmp_path, 1, needed, TINY_LEVELS, workers=1
    )
    patch = level_parent(planet, grid, tiles, centre, 300e3, 30.0, 11, relief)
    points = patch.mesh.xyz[patch.land]
    # The coarser tiles the patch stands on depart from the planet surface...
    coarse = (patch.surface_m - patch.young_m())[patch.land]
    assert np.sqrt(np.mean((coarse - planet.sample(points, ground)) ** 2)) > 100.0
    # ...yet at any height a finer level is as warm as the planet there.
    heights = np.linspace(0.0, 3000.0, len(points))
    for source in (planet, patch):
        found = source.temperatures_at(points, heights)
        assert found is not None
        assert np.allclose(found[0], 15.0 - lapse * heights / 1000, atol=0.01)
        assert np.allclose(found[1], 25.0 - lapse * heights / 1000, atol=0.01)


def _river_step(parent: PlanetResult) -> int:
    """The planet node with the largest drainage whose step runs between inland land."""
    receiver = parent.flow.receiver
    inland = parent.land & (parent.coast_m > 300e3) & (parent.lakes.lake < 0)
    steps = inland & (receiver >= 0) & inland[np.maximum(receiver, 0)]
    return int(np.argmax(np.where(steps, parent.flow.area_m2, 0.0)))


def _lonlat(xyz: np.ndarray) -> tuple[float, float]:
    unit = xyz / np.linalg.norm(xyz)
    return float(np.degrees(np.arctan2(unit[1], unit[0]))), float(np.degrees(np.arcsin(unit[2])))


def test_level_parents_bring_planet_rivers_in_across_the_area_they_serve(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from map_maker.terrain.application.planet_region import ensure_level_tiles
    from map_maker.terrain.pipeline.planet_levels import level_parent, level_parent_radius

    planet = RegionalParent.from_result(parent)
    # A small area served, centred where a big planet river step ends: one planet
    # step is longer than a quarter of the radius, so a patch reaching only that
    # far started the river at its receiver, inside the area served.
    node = _river_step(parent)
    centre = _lonlat(parent.mesh.xyz[parent.flow.receiver[node]])
    radius_m = 75e3
    grid = TileGrid.for_planet(parent.mesh.radius_m, TINY_LEVELS[0])
    relief = ReliefWarp.for_parent(TINY_LEVELS, 2, parent.settings.seed)
    needed = grid.tiles_near(
        centre, level_parent_radius(planet, radius_m, 30.0) + relief.reach_m
    )
    grid, tiles = ensure_level_tiles(
        planet, "p" * 64, tmp_path, 1, needed, TINY_LEVELS, workers=1
    )
    patch = level_parent(planet, grid, tiles, centre, radius_m, 30.0, 11, relief)
    mesh, receiver, area = patch.mesh, patch.receiver, patch.area_m2
    middle = parent.mesh.xyz[parent.flow.receiver[node]]
    served = mesh.radius_m * np.arccos(np.clip(mesh.xyz @ middle, -1, 1)) <= radius_m
    # Water in the area served fell there or crossed its rim.
    entering = ~served & (receiver >= 0) & served[np.maximum(receiver, 0)]
    runoff = 1.0 if patch.runoff_weight is None else patch.runoff_weight
    fell = float(np.sum((mesh.area_m2 * runoff)[served & patch.land]))
    assert area[served].max() <= 1.001 * (area[entering].sum() + fell)


def test_level_two_windows_repeat_exactly_and_agree_with_level_one(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from map_maker.terrain.application.planet_region import region_window

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

    from map_maker.terrain.adapters.planet_region import detail_offset, display_relief
    from map_maker.terrain.application.planet_region import region_window
    from map_maker.terrain.pipeline.planet_detail import eroded_fbm
    from map_maker.terrain.pipeline.planet_mesh import fibonacci_nodes

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


def test_nested_windows_colour_and_shade_the_same_slopes(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from map_maker.terrain.adapters.planet_region import display_relief, window_shading
    from map_maker.terrain.application.planet_region import region_window

    planet = RegionalParent.from_result(parent)
    centre = _land_centre(parent)

    def slopes(level: int, radius_km: float) -> tuple[float, float]:
        """Median measured slope and median slope that colour and hillshade see."""
        window = region_window(
            planet, "p" * 64, tmp_path, centre, radius_km, level=level, levels=TINY_LEVELS,
            pixels=96, workers=1,
        ).window
        relief = display_relief(window)
        offset = (np.arange(window.pixels) + 0.5 - window.pixels / 2) * window.pixel_m
        # The ground both windows show: the inner 90 km of the 100 km window.
        shared = window.land & (np.hypot(*np.meshgrid(offset, offset)) <= 90e3)
        north, east = np.gradient(relief, window.pixel_m)
        measured = np.hypot(east, north)
        seen, _ = window_shading(window, relief)
        return float(np.median(measured[shared])), float(np.median(seen[shared]))

    coarse, fine = slopes(1, 300.0), slopes(2, 100.0)
    # The finer level resolves steeper slopes on the same ground...
    assert fine[0] > 1.3 * coarse[0]
    # ...but its rock, vegetation and hillshade see them as the coarser level does.
    assert 0.75 < fine[1] / coarse[1] < 1.33


def test_terrain_position_ignores_ground_outside_the_window() -> None:
    from map_maker.terrain.adapters.planet_region import window_position

    # A 30 km plain at 800 m, with a 300 m hill at its centre; outside the window
    # disc the relief holds a placeholder depth, as display relief does.
    pixels, pixel_m = 120, 250.0
    offset = np.arange(pixels) + 0.5 - pixels / 2
    distance = np.hypot(*np.meshgrid(offset, offset)) * pixel_m
    inside = distance <= 15e3
    plain = np.where(inside, 800.0, -200.0)
    # The 15 km mean reaches across the whole window, yet a plain is no ridge.
    assert np.abs(window_position(plain, pixel_m, inside)[inside]).max() < 1e-6
    hill = plain + np.where(inside, 300.0 * np.exp(-((distance / 2e3) ** 2)), 0.0)
    position = window_position(hill, pixel_m, inside)
    assert position[pixels // 2, pixels // 2] > 0.5
    assert np.abs(position[inside & (distance > 12e3)]).max() < 0.1


def test_colour_lapse_corrects_display_relief_about_its_own_mean() -> None:
    from map_maker.terrain.adapters.planet_region import display_lift

    # A mountain front on a 5 km mesh at 500 m pixels, by the sea. Valley carving
    # lowers its display relief 700 m below the tiles; ridges and gullies 2 km
    # apart stand 200 m above and below that.
    pixels, pixel_m = 160, 500.0
    rows, columns = np.mgrid[0:pixels, 0:pixels] * pixel_m
    land = columns < 60e3
    tile = np.where(land, 500.0 + 0.05 * columns, -200.0)
    texture = 200.0 * np.sin(2 * np.pi * rows / 2e3)
    display = np.where(land, tile - 700.0 + texture, tile)
    lift = display_lift(display, tile, land, 5e3 / pixel_m)
    # Carving's lowering is no height, even beside the sea; the ridges are. (Rows
    # near the array's ends see the ridges mirrored; windows are wider than that.)
    inner = land & (rows > 20e3) & (rows < 60e3)
    assert np.allclose(lift[inner], texture[inner], atol=1.0)
    assert np.all(lift[~land] == 0.0)


def test_overlapping_windows_draw_the_same_rivers(parent: PlanetResult, tmp_path: Path) -> None:
    from scipy.ndimage import binary_dilation

    from map_maker.terrain.application.planet_region import region_window
    from map_maker.terrain.pipeline.planet_patch import forward_aeqd

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
    # unpadded routing agrees on about 92 % of river pixels here, padded about 94 %.
    # One pair varies with the relief (82-100 % over six pairs, pooled 91 % with
    # tiles v10 and v11 alike). With valleys winding below the mesh (v12) this
    # pair agrees on 91.4 %; six pairs pool 89 % near the edges and 92 % inside
    # (v11: 90 % and 88 %).
    ra, rb = np.hypot(x, y) / a.radius_m, np.hypot(xb, yb) / b.radius_m
    edge = (ra < 0.98) & (rb < 0.98) & ((ra > 0.75) | (rb > 0.75))
    check = rivers_b.ravel() & edge
    assert check.sum() > 20
    near_a = binary_dilation(a.rivers > 0.5, iterations=2)
    assert near_a[row[check], column[check]].mean() > 0.9


def test_inherited_rivers_cross_small_windows(parent: PlanetResult, tmp_path: Path) -> None:
    from map_maker.terrain.application.planet_region import region_window
    from map_maker.terrain.pipeline.planet_patch import forward_aeqd

    # A window centred on a big planet river step, far smaller than the step.
    node = _river_step(parent)
    xyz = parent.mesh.xyz
    centre = _lonlat(xyz[node] + xyz[parent.flow.receiver[node]])
    radius_km = 60.0
    inherited_km2 = parent.flow.area_m2[node] / 1e6
    # The river can only come from the parent: the routed window holds far less.
    assert inherited_km2 > 10 * np.pi * (1.25 * radius_km) ** 2
    window = region_window(
        RegionalParent.from_result(parent), "p" * 64, tmp_path, centre, radius_km,
        levels=TINY_LEVELS, pixels=128, workers=1, river_km2=0.7 * inherited_km2,
    ).window
    # Most of the parent's river crosses the map. Windows drained their rim
    # straight out, inherited rivers included, so none was drawn.
    drawn = window.rivers.ravel() > 0.05
    assert drawn.sum() > 50
    x, y = forward_aeqd(window.points[drawn], *window.centre, window.planet_m).T
    assert np.ptp(x) ** 2 + np.ptp(y) ** 2 > (1.2 * window.radius_m) ** 2


def _shore(lakes: np.ndarray, dry: np.ndarray) -> np.ndarray:
    """Lake pixels next to dry land (not the edge of the map)."""
    from scipy.ndimage import binary_dilation

    return lakes & np.asarray(binary_dilation(dry), dtype=bool)


def _longest_straight_run(shore: np.ndarray, band: float = 1.5, gap: float = 2.0) -> float:
    """Length (pixels) of the longest run of ``shore`` pixels along one straight line.

    Pixels are binned into bands ``band`` pixels wide across each direction; a
    run continues along a band while consecutive pixels are at most ``gap`` apart.
    """
    rows, columns = np.nonzero(shore)
    best = 0.0
    for angle in np.radians(np.arange(0.0, 180.0, 1.0)):
        across = columns * np.cos(angle) + rows * np.sin(angle)
        along = rows * np.cos(angle) - columns * np.sin(angle)
        for offset in (0.0, band / 2):
            bands = np.floor((across + offset) / band).astype(np.int64)
            order = np.lexsort((along, bands))
            b, a = bands[order], along[order]
            breaks = np.flatnonzero((np.diff(b) != 0) | (np.diff(a) > gap)) + 1
            starts, ends = np.r_[0, breaks], np.r_[breaks, len(a)] - 1
            best = max(best, float(np.max(a[ends] - a[starts])))
    return best


def test_lake_shores_follow_the_fine_relief_not_the_parent_mesh() -> None:
    from scipy.ndimage import binary_dilation, gaussian_filter

    from map_maker.terrain.adapters.planet_region import LAKE_SHORE_M, lake_water
    from map_maker.terrain.pipeline.planet_detail import grid_flow

    n, edge, level = 200, 50.0, 500.0
    rows, columns = np.mgrid[0:n, 0:n] + 0.5 - n / 2
    # One parent lake node on a regular triangular parent mesh of ``edge`` pixels:
    # its triangle-linear cover is a hexagonal pyramid with straight contours.
    v = rows / (edge * np.sqrt(3) / 2)
    u = columns / edge - v / 2
    cover = np.clip(1 - np.maximum.reduce([np.abs(u), np.abs(v), np.abs(u + v)]), 0, 1)
    # A basin whose level contour, roughened by sub-parent relief, lies just
    # beyond the parent lake's 0.15 cover contour (0.74-0.85 edges out).
    rough = gaussian_filter(np.random.default_rng(3).normal(size=(n, n)), 4.0)
    z = level + 4.0 * (np.hypot(rows, columns) - 0.92 * edge) + 25.0 * rough / rough.std()
    outlet = np.zeros((n, n), dtype=bool)
    outlet[[0, -1], :] = outlet[:, [0, -1]] = True
    _, _, filled = grid_flow(z, outlet, 500.0, np.zeros((n, n)))
    lakes = lake_water(z, ~outlet, filled, cover > 0.5, np.full((n, n), level))
    # Gating the lake by the parent's cover cut it along straight triangle edges
    # (0.85 edges long); the relief's own contour bends within a few pixels.
    gated = (cover > 0.15) & (z <= level + LAKE_SHORE_M)
    assert _longest_straight_run(_shore(gated, ~gated)) > 0.75 * edge
    assert _longest_straight_run(_shore(lakes, ~lakes)) < 0.55 * edge
    # The shore is the relief's own level contour: water stops where ground rises.
    assert lakes.sum() > gated.sum()
    assert np.all(z[lakes] <= level + LAKE_SHORE_M)
    beyond = np.asarray(binary_dilation(lakes), dtype=bool) & ~lakes
    assert np.all(z[beyond] > level + LAKE_SHORE_M)


def test_open_lake_water_stops_at_its_outlet() -> None:
    from map_maker.terrain.adapters.planet_region import lake_water
    from map_maker.terrain.pipeline.planet_detail import grid_flow

    n, level = 120, 300.0
    rows, columns = np.mgrid[0:n, 0:n] + 0.5 - n / 2
    r = np.hypot(rows, columns)
    # A lake flat at its level in rising ground, a hollow beside it below the
    # level, and an outlet valley falling from the lake to the map's edge.
    z = level + 3.0 * np.maximum(r - 25.0, 0.0)
    hollow = np.hypot(rows + 26.0, columns) < 6.0
    z[hollow] = level - 15.0
    valley = (np.abs(rows) < 2) & (columns > 25)
    z[valley] = level - 2.0 * (columns[valley] - 25)
    outlet = np.zeros((n, n), dtype=bool)
    outlet[:, -1] = True
    _, _, filled = grid_flow(z, outlet, 500.0, np.zeros((n, n)))
    lakes = lake_water(z, ~outlet, filled, r < 10.0, np.full((n, n), level))
    assert np.all(lakes[r < 25.0])
    assert np.all(lakes[hollow])  # low ground beside the lake fills to its level
    assert not np.any(lakes[valley & (columns > 28)])  # water does not run downstream


def test_open_lakes_drain_their_window_basin_without_a_pond_ring() -> None:
    from scipy.ndimage import binary_dilation, label

    from map_maker.terrain.adapters.planet_region import (
        POND_DEPTH_M,
        WindowFlow,
        lake_flow,
        lake_water,
        window_rivers,
    )

    n, level, pixel_m = 120, 300.0, 500.0
    rows, columns = np.mgrid[0:n, 0:n] + 0.5 - n / 2
    r = np.hypot(rows, columns)
    # An open lake flat at its level in a bowl whose rim rises 60 m above it.
    # A valley rises from the shore to a pass 40 m above the lake, then falls
    # to the map's edge: the window basin spills well above the lake's level.
    z = level + 3.0 * np.clip(r - 25.0, 0.0, 20.0) - 3.0 * np.maximum(r - 45.0, 0.0)
    valley = (np.abs(rows) < 2) & (columns > 25)
    rise = level + 2.0 + 1.9 * (columns - 25.0)
    floor = np.where(columns < 45.0, rise, level + 40.0 - 2.0 * (columns - 45.0))
    z[valley] = np.minimum(z, floor)[valley]
    outlet = np.zeros((n, n), dtype=bool)
    outlet[[0, -1], :] = outlet[:, [0, -1]] = True
    # A river enters the bowl over its north rim, far from the pass.
    inflow = np.zeros((n, n))
    inflow[16, n // 2] = 2e9
    flow = WindowFlow.route(z, outlet, pixel_m, inflow)
    lakes = lake_water(z, ~outlet, flow.filled, r < 10.0, np.full((n, n), level))
    assert np.all(lakes[r < 25.0]) and not np.any(lakes[(r > 27.0) & ~valley])
    shore = (r > 27.0) & (r < 33.0) & ~valley
    assert np.all(flow.filled[shore] - z[shore] > POND_DEPTH_M)  # far below the basin's spill
    routed, depth = lake_flow(flow, lakes, np.zeros((n, n), dtype=bool), np.full((n, n), level))
    # The lake drains its basin: the ground between its shore and the spill
    # holds no pond (a pale playa ring in dry climates).
    ponds = ~outlet & ~lakes & (depth > POND_DEPTH_M)
    assert not ponds.any()
    # The river from the north runs down into the lake, not around it to the pass.
    node = 16 * n + n // 2
    while node >= 0 and not lakes.flat[node]:
        node = int(routed.receiver[node])
    assert node >= 0
    # Rivers route through the open lake: everything leaves down the valley,
    # in one river from the shore along the valley floor, not across the bowl.
    exit_area = routed.area_m2.reshape(n, n)[n // 2 - 2 : n // 2 + 2, -2].max()
    assert exit_area > 2e9 + 0.9 * np.pi * 45.0**2 * pixel_m**2
    coverage = window_rivers(routed, lakes | ponds, 500.0)
    drawn = (coverage > 0.3) & (r > 27.0) & (r < 44.0)
    north = (np.abs(columns) < 5) & (rows < 0)
    assert drawn[valley].any() and not np.any(drawn & ~north & (np.abs(rows) > 5))
    parts = np.zeros((n, n), dtype=np.int32)
    label(coverage > 0.3, structure=np.ones((3, 3)), output=parts)
    leaving = np.setdiff1d(parts[n // 2 - 2 : n // 2 + 2, -3], [0])
    near_shore = np.asarray(binary_dilation(lakes, iterations=2), dtype=bool)
    assert np.any(np.isin(parts, leaving) & near_shore)


def test_a_river_fills_the_hollow_it_enters_instead_of_leaving_past_its_entry() -> None:
    from scipy.ndimage import maximum_filter

    from map_maker.terrain.adapters.planet_region import ENTRY_WALL_M, WindowFlow, entry_walls

    n, pixel_m = 120, 100.0
    rows, columns = np.mgrid[0:n, 0:n] + 0.5
    inside = np.hypot(rows - n / 2, columns - n / 2) <= n / 2 - 1
    # A valley falling west across the window. Blending left its reach by the
    # east rim 4 m low behind a sill, so that reach drains back out past where
    # the river enters, 2 m below the sill.
    ground = 110.0 + 0.05 * columns + 0.1 * np.abs(rows - 60.5)
    valley = np.abs(rows - 60.5) < 2
    ground[valley] = 100.0 + 0.05 * columns[valley] - 4.0 * (columns[valley] > 73)
    ground[valley & (columns > 70) & (columns < 73)] = 104.0
    ground = np.where(inside, ground, -np.inf)
    wall = maximum_filter(ground, size=3)
    z = np.where(inside, ground, np.where(np.isfinite(wall), wall, 0.0))

    def exit_column(relief: np.ndarray) -> int:
        inflow = np.zeros((n, n))
        inflow[60, 118] = 1.6e11
        flow = WindowFlow.route(relief, ~inside, pixel_m, inflow)
        node = 60 * n + 118
        while flow.receiver[node] >= 0:
            node = int(flow.receiver[node])
        return node % n

    assert exit_column(z) > n / 2
    # The parent's river crosses the rim at (60.5, 119.5) and leaves at
    # (60.5, 0.5). Within a parent spacing of its entry no water leaves, so it
    # fills the reach and spills over the sill.
    entry, leaving = (np.array([60.5]), np.array([119.5])), (np.array([60.5]), np.array([0.5]))
    walls = entry_walls(entry, leaving, inside, 3.0)
    assert walls.any() and not np.any(walls & inside)
    assert exit_column(np.where(walls, ground.max() + ENTRY_WALL_M, z)) < 10
    # In a window smaller than the parent spacing the rim stays open nearer the
    # exit, where the parent's river leaves.
    wide = entry_walls(entry, leaving, inside, 1000.0)
    assert wide[:, n // 2 + 1 :].any() and not wide[:, : n // 2 - 1].any()


def test_big_rivers_cross_hollows_that_closed_basins_keep() -> None:
    from map_maker.terrain.adapters.planet_natural import PixelClimate
    from map_maker.terrain.adapters.planet_region import (
        POND_DEPTH_M,
        WindowFlow,
        lake_flow,
        window_ponds,
        window_rivers,
    )

    n, pixel_m = 160, 100.0
    rows, columns = np.mgrid[0:n, 0:n] + 0.5
    # A plain falling 1 m/km to the west edge. A hollow 40 m deep lies on the
    # course of a river that enters at the east edge; a caldera sits in a cone
    # to the north, its rim the divide of its own small catchment.
    z = 100.0 + 0.1 * columns
    z -= 40.0 * np.exp(-((rows - 110) ** 2 + (columns - 80) ** 2) / (2 * 8.0**2))
    r = np.hypot(rows - 35, columns - 80)
    z += np.where(r < 25, 120.0 - 4.8 * r, 0.0) - np.where(r < 8, 60.0 * (1 - (r / 8) ** 2), 0.0)
    hollow = np.hypot(rows - 110, columns - 80) < 4
    caldera = r < 3
    outlet = np.zeros((n, n), dtype=bool)
    outlet[:, 0] = True
    shape = (n, n)

    def ponds(inflow_m2: float, precipitation_mm: float, pet_mm: float):
        inflow = np.zeros(shape)
        inflow[110, -1] = inflow_m2
        flow = WindowFlow.route(z, outlet, pixel_m, inflow)
        flow, depth = lake_flow(flow, np.zeros(shape, dtype=bool), outlet, np.zeros(shape))
        assert depth[hollow].min() > POND_DEPTH_M and depth[caldera].min() > POND_DEPTH_M
        climate = PixelClimate(
            np.full(shape, 15.0), np.full(shape, 22.0), np.full(shape, precipitation_mm),
            np.full(shape, pet_mm),
        )
        return flow, *window_ponds(flow, depth, ~outlet, climate)

    # A 160,000 km2 river brings far more water than the hollow evaporates and
    # fills it with sediment within the Holocene: it flows on across a plain.
    flow, held, spills = ponds(1.6e11, 200.0, 1500.0)
    assert not held[hollow].any()
    coverage = window_rivers(flow, held, 2000.0)
    assert np.all(coverage[105:116, 70:91].max(axis=0) > 0.5)
    # The caldera drains only its crater, which evaporates more than it gathers
    # in a dry climate: a closed basin, a playa in the window.
    assert held[caldera].all() and not spills[caldera].any()
    # In a wet climate it overflows but gathers too little sediment to fill: an
    # open lake.
    _, held, spills = ponds(1.6e11, 1500.0, 800.0)
    assert held[caldera].all() and spills[caldera].all()
    # Without the river, the 56 km2 of plain draining to the hollow brings too
    # little sediment to fill it within the Holocene: it holds water.
    _, held, _ = ponds(0.0, 200.0, 1500.0)
    assert held[hollow].all()


def test_tiles_hold_a_lake_under_young_relief_at_its_level(parent: PlanetResult) -> None:
    from dataclasses import replace

    from map_maker.terrain.pipeline.planet_coast import level_finest_m
    from map_maker.terrain.pipeline.planet_regional import LAKE_CORE_COVER

    lakes = parent.lakes
    ids, counts = np.unique(lakes.lake[lakes.lake >= 0], return_counts=True)
    nodes = np.flatnonzero(lakes.lake == ids[np.argmax(counts)])
    centre = parent.mesh.xyz[nodes].mean(axis=0)
    lon = float(np.degrees(np.arctan2(centre[1], centre[0])))
    lat = float(np.degrees(np.arcsin(centre[2] / np.linalg.norm(centre))))
    # A young hollow 400 m deep under the whole land, as a crater is under its
    # lake: windows draw it back on top of the tiles.
    planet = RegionalParent.from_result(parent)
    hollow = replace(planet, wonder_m=np.where(parent.land, -400.0, 0.0))
    region = regional_mesh(lon, lat, 400, 40, parent.mesh.radius_m, 1)
    result = enrich(hollow, region, process_area_km2=3_000, iterations=0, seed=1)
    cover, level, _ = hollow.lakes_at(region.mesh.xyz, level_finest_m(region.spacing_m))
    held = result.land & (cover > LAKE_CORE_COVER)
    assert held.sum() > 10
    young = hollow.sample(region.mesh.xyz, hollow.young_m())
    # With the hollow added back, the lake stands at its level, not 400 m below it.
    assert np.allclose(result.elevation_m[held] + young[held], level[held])
    assert np.median(young[held]) < -390.0


def test_windows_draw_ice_sheets_over_the_relief_without_rivers_or_lakes(
    parent: PlanetResult, tmp_path: Path
) -> None:
    from dataclasses import replace

    from map_maker.terrain.adapters.planet_natural import PixelClimate
    from map_maker.terrain.adapters.planet_region import (
        display_climate,
        display_relief,
        window_ice_cover,
    )
    from map_maker.terrain.application.planet_region import region_window
    from map_maker.terrain.pipeline.planet_ice import IceSheets

    lon, lat = _land_centre(parent)
    centre = inverse_aeqd(np.zeros(1), np.zeros(1), lon, lat, 1.0)[0]
    distance = parent.mesh.radius_m * np.arccos(np.clip(parent.mesh.xyz @ centre, -1, 1))
    # A dome 2.5 km thick over the land within 600 km: snow piles up on top and
    # melts towards its margin.
    share = np.clip(1 - distance / 600e3, 0, 1)
    sheet = parent.land & (share > 0)
    ice = IceSheets(
        np.where(sheet, 2500.0 * np.sqrt(share), 0.0), np.where(parent.land, 0.6 * share - 0.4, 0.0)
    )
    planet = replace(RegionalParent.from_result(parent), ice=ice)
    window = region_window(
        planet, "i" * 64, tmp_path, (lon, lat), 300.0, levels=TINY_LEVELS, pixels=160,
        workers=1, river_km2=500.0,
    ).window
    assert window.ice_surface_m is not None and window.ice_balance_m is not None
    relief = display_relief(window)
    cover = window_ice_cover(window, relief) > 0.5
    middle = (slice(60, 100), slice(60, 100))
    assert cover[middle].all()
    # The ice buries the relief and holds no rivers or open water.
    iced = np.nan_to_num(window.ice_surface_m, nan=-1e9) > np.nan_to_num(window.elevation_m)
    assert iced[middle].all()
    assert not window.rivers[iced].any() and not window.lakes[iced].any()
    assert not window.playa[iced].any()
    # The shown relief stands on the ice surface wherever ice covers it.
    assert np.allclose(relief[cover & window.land], np.fmax(relief, window.ice_surface_m)[
        cover & window.land
    ])
    # That surface is real height, not display detail: colour sees the climate
    # cooled by the ice's whole thickness.
    zero = np.zeros(relief.shape)
    shown = display_climate(window, PixelClimate(zero, zero, zero, zero), relief)
    thickness = (window.ice_surface_m - window.elevation_m)[middle]
    assert thickness.min() > 500.0
    assert np.allclose(
        -shown.temperature_c[middle], window.lapse_c_per_km * thickness / 1000, atol=0.3
    )


def test_relief_warp_winds_straight_tile_valleys_and_keeps_their_drainage() -> None:
    """A valley between collinear tile nodes routes as a straight line unless warped.

    Tiles interpolate linearly, so a valley along their mesh edges is a straight
    crease, and pixel routing drew it as one straight run. Sampled where the
    relief warp moves each pixel, the valley winds; the warp is an
    area-preserving flow, so heights, the area at each height and the absence
    of closed hollows are kept, and the river stays near its valley.
    """
    from scipy.spatial import Delaunay

    from map_maker.terrain.domain.planet import REGION_LEVELS
    from map_maker.terrain.pipeline.planet_detail import grid_flow
    from map_maker.terrain.pipeline.planet_mesh import mesh_from_triangles

    radius_m, lon, lat, spacing = 6.0e6, 20.0, 10.0, 5e3
    # A regular tile lattice with a row of nodes on the valley axis (y = 0).
    j, i = np.mgrid[-14:15, -16:17]
    x = ((i + 0.5 * (j % 2)) * spacing).ravel().astype(np.float64)
    y = (j * spacing * np.sqrt(3) / 2).ravel().astype(np.float64)
    triangles = Delaunay(np.c_[x, y]).simplices.astype(np.int64)
    mesh = mesh_from_triangles(inverse_aeqd(x, y, lon, lat, radius_m), triangles, radius_m)
    # Planar valley sides falling 3 % to the axis, which falls 0.2 % to the west.
    tile = TileSurface(mesh, 500.0 + 0.03 * np.abs(y) + 0.002 * x)
    pixels, pixel_m = 200, 400.0
    centres = (np.arange(pixels) + 0.5 - pixels / 2) * pixel_m
    gx, gy = np.meshgrid(centres, -centres)
    points = inverse_aeqd(
        gx.ravel().astype(np.float64), gy.ravel().astype(np.float64), lon, lat, radius_m
    )
    outlet = np.zeros((pixels, pixels), dtype=bool)
    outlet[:, 0] = True
    warp = ReliefWarp.for_window(REGION_LEVELS, 1, 7)

    def route(at: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        z = tile.sample(at).reshape(pixels, pixels)
        receiver, area, filled = grid_flow(z, outlet, pixel_m, np.zeros_like(z))
        return z, receiver, area, filled

    straight, moved = route(points), route(warp(points, radius_m))
    river_m2 = 4000 * pixel_m**2  # the main river, not its side streams
    assert _straight_channel_share(straight[1], straight[2], river_m2) > 0.9
    assert _straight_channel_share(moved[1], moved[2], river_m2) < 0.3
    z, _, area, filled = moved
    # No new hollows. Pixels sample a winding V-crease off its floor, as at any
    # crease the grid does not follow, which leaves a few hollows no deeper than
    # the side slope across a pixel; a fold in the warp would dig deeper ones.
    depth = (filled - z)[~outlet]
    assert np.mean(depth > 0.01) < 0.01
    assert depth.max() < 0.03 * pixel_m * np.sqrt(2)
    # Heights and the area at each height are kept away from the edges.
    inner = (np.abs(gx) < 25e3) & (np.abs(gy) < 25e3)
    quantiles = np.linspace(0.05, 0.95, 19)
    shift = np.quantile(z[inner], quantiles) - np.quantile(straight[0][inner], quantiles)
    assert np.abs(shift).max() < 0.03 * np.ptp(straight[0][inner])
    # The river stays in its valley.
    river = (area >= river_m2).reshape(pixels, pixels) & ~outlet
    assert river[:, pixels // 2].sum() >= 1
    assert np.abs(gy[river]).max() < warp.reach_m
    assert np.median(np.abs(gy[river])) < 0.5 * spacing


def test_relief_warp_octaves_nest_across_levels() -> None:
    """Every level takes the octaves its tiles cannot carry, once, from one sequence."""
    from map_maker.terrain.domain.planet import REGION_LEVELS

    def octaves(warp: ReliefWarp) -> list[int]:
        first, found = warp.octaves()
        return list(range(first, first + len(found)))

    one = octaves(ReliefWarp.for_window(REGION_LEVELS, 1, 7))
    assert one[0] == 0 and len(one) >= 2
    carried: list[int] = []  # octaves that reach a level through its tiles
    for level in (2, 3):
        carried += octaves(ReliefWarp.for_parent(REGION_LEVELS, level, 7))
        shown = carried + octaves(ReliefWarp.for_window(REGION_LEVELS, level, 7))
        # Each octave once and none left out, and every level bends rivers
        # where level 1 does.
        assert shown == list(range(len(shown)))
        assert set(one) <= set(shown)


def test_smooth_parent_sampling_has_no_creases_at_parent_triangle_edges(
    parent: PlanetResult,
) -> None:
    from map_maker.terrain.pipeline.planet_patch import inverse_aeqd

    planet = RegionalParent.from_result(parent)
    mesh = parent.mesh
    lon, lat = _land_centre(parent)
    # A smooth field: equal to it at nodes, closer to it between them, and a
    # transect across many triangles curves smoothly instead of kinking at edges.
    field = 1000.0 * np.sin(4.0 * mesh.xyz[:, 0]) * np.cos(3.0 * mesh.xyz[:, 1])
    node = int(np.argmax(mesh.xyz @ inverse_aeqd(np.zeros(1), np.zeros(1), lon, lat, 1.0)[0]))
    near = mesh.xyz @ mesh.xyz[node] > np.cos(5 * mesh.spacing_m / mesh.radius_m)
    assert np.allclose(planet.smooth_sampler(mesh.xyz[near])(field), field[near], atol=1e-6)
    t = np.linspace(-6, 6, 2401) * mesh.spacing_m
    line = inverse_aeqd(t, 0.3 * t, lon, lat, mesh.radius_m)
    exact = 1000.0 * np.sin(4.0 * line[:, 0]) * np.cos(3.0 * line[:, 1])
    linear, smooth = planet.sample(line, field), planet.smooth_sampler(line)(field)
    assert np.abs(smooth - exact).mean() < 0.5 * np.abs(linear - exact).mean()
    # As smooth at any magnitude: uplift is metres a year.
    tiny = planet.smooth_sampler(line)(1e-7 * field)
    assert np.allclose(1e7 * tiny, smooth, rtol=0, atol=1e-6)

    def kinks(profile: np.ndarray) -> float:
        bend = np.abs(np.diff(profile, 2))
        return float(bend.max() / bend.mean())

    assert kinks(smooth) < 0.25 * kinks(linear)


def test_smooth_parent_sampling_stays_within_each_parent_triangle(
    parent: PlanetResult,
) -> None:
    from map_maker.terrain.pipeline.planet_patch import forward_aeqd

    planet = RegionalParent.from_result(parent)
    mesh = parent.mesh
    lon, lat = _land_centre(parent)
    # A plain at 160 m meets a range rising 1,000 m within one parent spacing,
    # as a sediment basin meets its mountains. Cubics fitted across the front
    # dipped 85 m below the plain here; a tile ring held at such a dip, at sea
    # level, drained a big river to it.
    east = forward_aeqd(mesh.xyz, lon, lat, mesh.radius_m)[:, 0] / mesh.spacing_m
    field = 160.0 + 1000.0 * np.clip(east, 0.0, 1.0)
    t = np.linspace(-4, 4, 1601) * mesh.spacing_m
    for slope in (0.0, 0.4, 1.3):
        line = inverse_aeqd(t, slope * t, lon, lat, mesh.radius_m)
        smooth = planet.smooth_sampler(line)(field)
        assert smooth.min() >= 160.0 - 1e-9 and smooth.max() <= 1160.0 + 1e-9


def test_basin_fronts_are_dissected_alike_at_every_level(parent: PlanetResult) -> None:
    from dataclasses import replace

    from scipy.ndimage import gaussian_filter1d

    from map_maker.terrain.pipeline.planet_coast import level_finest_m
    from map_maker.terrain.pipeline.planet_patch import forward_aeqd
    from map_maker.terrain.pipeline.planet_regional import BASIN_FULL_M

    mesh = parent.mesh
    spacing = mesh.spacing_m
    lon, lat = _land_centre(parent)
    # A basin deepening eastward. Unrefined, plain meets mountains along the
    # straight line x = 0 at every level.
    east = forward_aeqd(mesh.xyz, lon, lat, mesh.radius_m)[:, 0]
    planet = replace(
        RegionalParent.from_result(parent), basin_depth_m=BASIN_FULL_M * (0.5 + east / spacing)
    )

    def front(y: np.ndarray, step: float, detail_m: float) -> np.ndarray:
        """Where the plain begins along rows ``y``: the margin with its area east of it."""
        x = np.arange(-1.5 * spacing, 1.5 * spacing, step) + step / 2
        gx, gy = np.meshgrid(x, y)
        points = inverse_aeqd(gx.ravel(), gy.ravel(), lon, lat, mesh.radius_m)
        depth = planet.basin_at(points, detail_m)
        assert depth is not None
        plain = depth.reshape(gx.shape) > 0.5 * BASIN_FULL_M
        return x[0] - step / 2 + step * np.sum(~plain, axis=1)

    # Three nested levels, each five times finer, as the regional levels are.
    spacings = spacing / np.array([4.0, 20.0, 100.0])
    parents = np.array([spacing, *spacings[:-1]])
    roughness = []
    for n, (level_m, parent_m) in enumerate(zip(spacings, parents, strict=True)):
        step = level_m / 2
        y = np.arange(-24 * parent_m, 24 * parent_m, step)
        assert np.ptp(front(y, step, np.inf)) == 0
        margin = front(y, step, level_finest_m(level_m))
        # Bends below the parent spacing, which the coarser level cannot carry,
        # measured across the front where it runs at an angle to the rows.
        trend = gaussian_filter1d(margin, parent_m / 4 / step, mode="nearest")
        bends = (margin - trend) / np.hypot(1.0, np.gradient(trend, step))
        inner = slice(len(y) // 8, -(len(y) // 8))
        roughness.append(float(np.std(bends[inner])) / parent_m)
        if n:
            # A finer level refines the coarser level's front instead of moving it.
            coarser = front(y, step, level_finest_m(spacings[n - 1]))
            assert np.mean(np.abs(margin - coarser)) < 0.25 * parent_m
    # Every level dissects its front alike: roughness at its parent's scale is
    # self-similar, about 3-5 % of the parent spacing.
    assert min(roughness) > 0.02
    assert max(roughness) < 1.6 * min(roughness)
