# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Whole-planet relief: mesh geometry, erosion invariants, geology, climate and builds."""

import json
from dataclasses import replace
from math import pi
from pathlib import Path

import numpy as np
import pytest
import rasterio
from jsonschema import Draft202012Validator

from benchmarks.planet.sample_geology import sample_recipe
from benchmarks.planet.synthetic_world import WorldSpec, build_world
from dmtools.terrain.adapters.build import file_sha256
from dmtools.terrain.adapters.world_geology import write_geology
from dmtools.terrain.application.planet import build_planet
from dmtools.terrain.application.world import open_world
from dmtools.terrain.domain.planet import PlanetClimateSettings, PlanetSettings
from dmtools.terrain.pipeline.control import CancellationToken, GenerationCancelled
from dmtools.terrain.pipeline.planet import generate_planet
from dmtools.terrain.pipeline.planet_climate import simulate_climate
from dmtools.terrain.pipeline.planet_evolution import calibrated_relief, route
from dmtools.terrain.pipeline.planet_forcing import (
    coast_distance,
    geology_regions,
    land_on_mesh,
)
from dmtools.terrain.pipeline.planet_kernels import accumulate, laplacian, priority_flood
from dmtools.terrain.pipeline.planet_mesh import SphereMesh, build_mesh
from dmtools.terrain.pipeline.planet_metrics import compass_share, non_descending_receivers

ROOT = Path(__file__).resolve().parents[1]
RADIUS = 6.371e6
FAST = PlanetSettings(
    nodes=12_000, duration_myr=6.0, step_kyr=250.0, calibration_iterations=1, climate_passes=1
)


@pytest.fixture(scope="module")
def mesh() -> SphereMesh:
    return build_mesh(4000, RADIUS, 3)


@pytest.fixture(scope="module")
def world_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_world(WorldSpec(seed=7, columns=512), tmp_path_factory.mktemp("w"), "w")


def test_mesh_covers_the_sphere_with_symmetric_neighbours(mesh: SphereMesh) -> None:
    assert mesh.area_m2.sum() == pytest.approx(4 * pi * RADIUS**2, rel=1e-9)
    assert len(mesh.triangles) == 2 * mesh.size - 4  # Euler: closed triangulated sphere
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    forward = set(zip(src.tolist(), mesh.nbr.tolist(), strict=True))
    assert all((b, a) in forward for a, b in forward)
    assert np.all(mesh.length_m > 0)
    assert np.all(mesh.weight > -1e-9)  # Delaunay: opposite angles sum to at most pi
    water = np.zeros(mesh.size, dtype=bool)
    lap = laplacian(
        np.full(mesh.size, 7.0), water, mesh.ptr, mesh.nbr, mesh.weight, mesh.area_m2, 0.0
    )
    assert np.max(np.abs(lap)) < 1e-12
    assert np.array_equal(build_mesh(4000, RADIUS, 3).xyz, mesh.xyz)
    assert not np.array_equal(build_mesh(4000, RADIUS, 4).xyz, mesh.xyz)


def test_flooded_routing_drains_every_land_node_to_water(mesh: SphereMesh) -> None:
    rng = np.random.default_rng(1)
    water = mesh.xyz[:, 2] < -0.2
    h = np.where(water, 0.0, 100 * rng.random(mesh.size))
    filled, parent = priority_flood(h, water, mesh.ptr, mesh.nbr, 1e-3)
    assert np.all(filled >= h)
    assert np.all(parent[~water] >= 0)
    flow = route(mesh, h, water)
    assert non_descending_receivers(flow.filled, flow.receiver, water) == 0
    outlets = (~water) & water[np.maximum(flow.receiver, 0)]
    total = accumulate(flow.order, flow.receiver, water, np.where(water, 0.0, mesh.area_m2))
    assert total[outlets].sum() == pytest.approx(mesh.area_m2[~water].sum(), rel=1e-12)


def test_planet_keeps_the_coast_and_builds_descending_unbiased_rivers(world_path: Path) -> None:
    world = open_world(world_path)
    settings = PlanetSettings(nodes=20_000, duration_myr=5.0, step_kyr=250.0, climate_passes=0)
    result = generate_planet(world, settings)
    land = result.land
    assert np.all(result.elevation_m[land] >= 1.0)
    assert np.all(result.elevation_m[~land] < 0.0)
    assert result.metrics["non_descending_receivers"] == 0
    assert compass_share(result.mesh, result.flow.receiver, land) == pytest.approx(0.25, abs=0.04)
    assert result.climate is None
    again = generate_planet(world, settings)
    assert np.array_equal(result.elevation_m, again.elevation_m)
    other = generate_planet(world, replace(settings, seed=1))
    assert not np.array_equal(result.elevation_m, other.elevation_m)


def test_geology_intent_is_calibrated_while_erosion_shapes_the_relief(world_path: Path) -> None:
    world = open_world(world_path)
    recipe = sample_recipe(world_path)
    mesh = build_mesh(30_000, world.project.frame.radius_km * 1000, 2)
    land = land_on_mesh(world, mesh)
    coast = coast_distance(mesh, land)
    regions = geology_regions(world, recipe, mesh, land)
    assert np.all(regions.region[~land] == -1)
    relief = calibrated_relief(
        mesh, land, coast, regions, np.ones(mesh.size), seed=1, erodibility=4e-6, steps=40,
        step_yr=2.5e5, area_exponent=0.45, process_area_m2=1e10, iterations=2,
    )
    assert non_descending_receivers(relief.run.elevation, relief.run.flow.receiver, ~land) == 0
    final = {r.name: r for r in relief.iterations[-1]}
    errors = [
        abs(r.measured_m - r.target_m) / r.target_m
        for r in final.values()
        if r.target_m is not None and r.measured_m is not None
    ]
    assert np.median(errors) < 0.15
    young = [r.measured_m for n, r in final.items() if n.endswith("young belt")]
    worn = [r.measured_m for n, r in final.items() if n.endswith("worn belt")]
    assert all(v is not None for v in young + worn)
    assert min(v for v in young if v is not None) > max(v for v in worn if v is not None)


def test_climate_controls_windward_rain_shadow_and_water_budget() -> None:
    mesh = build_mesh(40_000, RADIUS, 9)
    lon, lat = np.rad2deg(mesh.lon), np.rad2deg(mesh.lat)
    # A mid-latitude continent in the westerlies with a north-south range at 0 degrees.
    land = (np.abs(lat - 47) < 15) & (np.abs(lon) < 35)
    ridge = 3000 * np.exp(-((lon / 4) ** 2))
    coast = coast_distance(mesh, land)
    band = land & (np.abs(lat - 47) < 7)
    west, east = band & (lon > -12) & (lon < -3), band & (lon > 3) & (lon < 12)
    with_range = simulate_climate(mesh, np.where(land, 200 + ridge, 0.0), land, coast)
    flat = simulate_climate(mesh, np.where(land, 200.0, 0.0), land, coast)
    rain = with_range.precipitation_mm
    assert rain[west].mean() > 1.3 * rain[east].mean()
    assert rain[east].mean() < flat.precipitation_mm[east].mean()
    weight = mesh.area_m2 * land
    assert float(np.sum(rain * weight) / weight.sum()) == pytest.approx(800.0)
    assert np.all((with_range.runoff_mm >= 0) & (with_range.runoff_mm <= rain + 1e-9))
    top = band & (np.abs(lon) < 1.5)
    assert with_range.temperature_c[top].mean() < flat.temperature_c[top].mean() - 15
    # Retrograde rotation reverses the zonal winds and therefore the rain shadow.
    mirrored = simulate_climate(
        mesh, np.where(land, 200 + ridge, 0.0), land, coast,
        PlanetClimateSettings(prograde_rotation=False),
    )
    assert mirrored.precipitation_mm[east].mean() > mirrored.precipitation_mm[west].mean()


def test_settings_reject_unsupported_requests() -> None:
    for bad in (
        {"nodes": 10},
        {"seed": -1},
        {"duration_myr": 0.0},
        {"step_kyr": 5000.0, "duration_myr": 1.0},
        {"climate_passes": 9},
        {"erodibility": float("nan")},
    ):
        with pytest.raises(ValueError):
            PlanetSettings(**bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        PlanetClimateSettings(pole_sst_c=40.0)


def test_planet_build_publishes_verified_world_aligned_products(
    world_path: Path, tmp_path: Path
) -> None:
    geology = tmp_path / "w.dmgeology.json"
    write_geology(sample_recipe(world_path), geology, None)
    manifest_path = build_planet(world_path, tmp_path / "planet", geology, FAST, width=256)
    target = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas/world/planet-build-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    for name, record in manifest["outputs"].items():
        assert file_sha256(target / name) == record["sha256"]
    assert {"atlas.png", "precipitation.png", "temperature.png", "geology.dmgeology.json"} <= set(
        manifest["outputs"]
    )
    assert manifest["inputs"]["world_sha256"] == file_sha256(world_path)
    assert not (target / "manifest.pending").exists()
    with np.load(target / "planet.npz", allow_pickle=False) as archive:
        land = archive["land"]
        assert np.all(archive["elevation_m"][land] >= 1.0)
        assert set(np.unique(archive["biome"][land]).tolist()) <= set(range(1, 14))
        assert archive["xyz"].shape == (FAST.nodes, 3)
    with rasterio.open(target / "elevation.tif") as tif:
        assert (tif.width, tif.height) == (256, 128)
        assert tif.crs is not None and "6371000" in tif.crs.to_wkt()
        assert tif.transform.c == pytest.approx(-180.0)
        values = tif.read(1)
        assert np.isfinite(values).all() and values.max() > 0 > values.min()
    rivers = json.loads((target / "rivers.geojson").read_text(encoding="utf-8"))
    assert rivers["type"] == "FeatureCollection"
    assert len(rivers["features"]) == manifest["rivers"]["features"] > 0
    with pytest.raises(FileExistsError):
        build_planet(world_path, target, geology, FAST, width=256)


def test_cancelled_planet_build_never_looks_complete(world_path: Path, tmp_path: Path) -> None:
    token = CancellationToken()
    seen: list[str] = []

    def progress(fraction: float, message: str) -> None:
        seen.append(message)
        if fraction > 0.2:
            token.cancel()

    with pytest.raises(GenerationCancelled):
        build_planet(
            world_path, tmp_path / "cancelled", None, FAST, width=256, progress=progress,
            cancellation=token,
        )
    assert seen and not (tmp_path / "cancelled" / "manifest.json").exists()


def test_large_meshes_calibrate_on_a_coarse_mesh_then_run_once(
    world_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dmtools.terrain.pipeline.planet as planet

    monkeypatch.setattr(planet, "CALIBRATION_NODES", 6000)
    settings = PlanetSettings(
        nodes=24_000, duration_myr=8.0, step_kyr=250.0, calibration_iterations=2,
        climate_passes=0,
    )
    result = generate_planet(open_world(world_path), settings, sample_recipe(world_path))
    # Two coarse corrections then one full-resolution measurement.
    assert len(result.calibration) == 3
    errors = [
        abs(r.measured_m - r.target_m) / r.target_m
        for r in result.calibration[-1]
        if r.target_m is not None and r.measured_m is not None
    ]
    assert np.median(errors) < 0.2
    assert result.metrics["non_descending_receivers"] == 0
