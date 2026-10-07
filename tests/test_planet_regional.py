# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Regional planet detail: parent consistency, window independence, builds and cache."""

from pathlib import Path

import numpy as np
import pytest

from benchmarks.planet.synthetic_world import WorldSpec, build_world
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
    result = enrich(
        RegionalParent.from_result(parent), region, process_area_km2=2_000, iterations=3, seed=1
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
    carved = carve_valleys(z, outlet, 500.0, 0.4, 0.5, 3)
    again = carve_valleys(z, outlet, 500.0, 0.4, 0.5, 3)
    assert np.array_equal(carved, again)
    assert np.all(np.isfinite(carved))
    assert np.array_equal(carved[outlet], z[outlet])
    # Depressions are filled before carving, so a cell may rise to its spill level
    # but never above the highest original cell; incision lowers most of the land.
    assert carved.max() <= z.max() + 1e-6
    assert np.mean(carved[~outlet] < z[~outlet]) > 0.5
