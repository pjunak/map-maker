# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Regional enrichment research harness: parent consistency and window independence."""

from pathlib import Path

import numpy as np
import pytest

from benchmarks.planet.regional import enrich, inverse_aeqd, regional_mesh
from benchmarks.planet.synthetic_world import WorldSpec, build_world
from benchmarks.planet.tiles import TileGrid, blend, generate_tile
from dmtools.terrain.application.world import open_world
from dmtools.terrain.domain.planet import PlanetSettings
from dmtools.terrain.pipeline.planet import PlanetResult, generate_planet
from dmtools.terrain.pipeline.planet_metrics import non_descending_receivers


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
    result = enrich(parent, region, process_area_km2=2_000, iterations=3, seed=1)
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
    grid = TileGrid.for_planet(radius, 1500, 200)
    lon, lat = _land_centre(parent)
    points = inverse_aeqd(np.linspace(-500e3, 500e3, 30), np.zeros(30), lon, lat, radius)
    ids, weights = grid.weights(points, radius)
    assert np.allclose(weights.sum(axis=1), 1.0)
    tile = int(ids[0, np.argmax(weights[0])])
    a = generate_tile(parent, grid, tile, 30, 3_000, 1, 7)
    b = generate_tile(parent, grid, tile, 30, 3_000, 1, 7)
    assert np.array_equal(a.elevation_m, b.elevation_m)
    tiles = {
        int(t): generate_tile(parent, grid, int(t), 30, 3_000, 1, 7)
        for t in np.unique(ids[ids >= 0])
    }
    values = blend(tiles, grid, points, radius)
    assert np.all(np.isfinite(values))
    # Any subset of points reproduces exactly the same blended values.
    assert np.array_equal(blend(tiles, grid, points[5:12], radius), values[5:12])


def test_world_path_fixture_is_reusable(tmp_path: Path) -> None:
    assert build_world(WorldSpec(seed=3, columns=256), tmp_path, "x").exists()
