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
from dmtools.terrain.application.planet import build_planet, input_identity
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
    recipe = sample_recipe(world_path)
    assert manifest["inputs"] == input_identity(recipe.world, recipe)
    assert {"atlas.png", "relief.png", "precipitation.png", "temperature.png"} <= set(
        manifest["outputs"]
    )
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
    # Production meshes resolve the process area (2,500 km2 is ~4 cells at 800k
    # nodes). Keep that ratio here: at ~21,000 km2 per cell, a 2,500 km2 process
    # area would test coarse-mesh dependence instead of calibration transfer.
    settings = PlanetSettings(
        nodes=24_000, duration_myr=8.0, step_kyr=250.0, calibration_iterations=2,
        climate_passes=0, process_area_km2=90_000.0,
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


def test_lakes_overflow_when_humid_and_close_when_arid() -> None:
    from dmtools.terrain.pipeline.planet_lakes import balance_lakes

    mesh = build_mesh(30_000, RADIUS, 5)
    lat, lon = np.rad2deg(mesh.lat), np.rad2deg(mesh.lon)
    land = (np.abs(lat) < 30) & (np.abs(lon) < 30)
    coast = coast_distance(mesh, land)
    # A 500 m plateau behind a coastal ramp, with a 300 m deep central basin.
    pit = np.exp(-((lat / 5) ** 2 + (lon / 5) ** 2))
    plateau = 1 + 499 * np.clip(coast / 3e5, 0, 1)
    ground = np.where(land, plateau - 300 * pit, 0.0)
    humid = balance_lakes(mesh, land, ground, np.full(mesh.size, 1500.0), np.full(mesh.size, 900.0))
    arid = balance_lakes(mesh, land, ground, np.full(mesh.size, 15.0), np.full(mesh.size, 2200.0))
    centre = int(np.argmin(np.where(land, lat**2 + lon**2, np.inf)))
    for lakes in (humid, arid):
        assert lakes.lake[centre] >= 0
        assert np.all(lakes.lake[~land] == -1)
        sink = ~land | (lakes.lake >= 0)
        assert non_descending_receivers(lakes.surface_m, lakes.flow.receiver, sink) == 0
    wet, dry = humid.lake[centre], arid.lake[centre]
    assert not humid.endorheic[wet] and arid.endorheic[dry]
    assert arid.area_m2[dry] < humid.area_m2[wet]
    assert arid.level_m[dry] < humid.level_m[wet]
    # A closed lake balances its inflow with evaporation (to one node of area).
    evaporation = 2.2 * arid.area_m2[dry]
    inflow = 0.015 * mesh.area_m2[(arid.flow.receiver >= -1) & land].sum()
    assert evaporation <= inflow * 1.2
    # Its water never reaches the sea; the humid lake passes its surplus on.
    assert arid.discharge_m3_s[land & (arid.lake < 0)].max() < humid.discharge_m3_s[land].max()


def test_ice_sheets_hold_no_young_lakes() -> None:
    from dmtools.terrain.pipeline.planet_lakes import young_depressions

    mesh = build_mesh(8_000, RADIUS, 2)
    land = np.ones(mesh.size, dtype=bool)
    coast = np.full(mesh.size, 1e6)
    flat = np.full(mesh.size, 200.0)
    ice_free = young_depressions(mesh, land, coast, None, np.full(mesh.size, 10.0), flat, 1)
    ice = young_depressions(mesh, land, coast, None, np.full(mesh.size, -5.0), flat, 1)
    assert ice_free.max() > 0
    # Under permanent ice only non-glacial sags remain; scour adds nothing.
    no_scour = young_depressions(mesh, land, coast, None, None, flat, 1)
    assert np.all(ice <= no_scour + 1e-9)
    assert np.all(ice <= ice_free + 1e-9)


def test_fine_meshes_couple_climate_on_coarser_meshes(
    world_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dmtools.terrain.pipeline.planet as planet

    # Scaled-down stand-ins for the 200k climate and 800k coupling meshes.
    monkeypatch.setattr(planet, "CLIMATE_NODES", 3_000)
    monkeypatch.setattr(planet, "COUPLING_NODES", 6_000)
    settings = replace(FAST, nodes=12_000, climate_passes=2)
    result = generate_planet(open_world(world_path), settings)
    climate = result.climate
    assert climate is not None and result.runoff_weight is not None
    assert result.runoff_weight.shape == (result.mesh.size,)
    for field in (climate.temperature_c, climate.precipitation_mm, climate.runoff_mm):
        assert field.shape == (result.mesh.size,) and np.all(np.isfinite(field))
    land = result.land
    mean = np.average(climate.precipitation_mm[land], weights=result.mesh.area_m2[land])
    assert mean == pytest.approx(settings.climate.mean_land_precip_mm, rel=1e-6)
    # Temperature is recomputed on the full mesh, so it keeps the fine relief's lapse rate.
    high = land & (result.elevation_m > 1500)
    low = land & (result.elevation_m < 300)
    if high.any() and low.any():
        assert climate.temperature_c[high].mean() < climate.temperature_c[low].mean()
    assert result.metrics["non_descending_receivers"] == 0


def test_scale_metrics_measure_rivers_and_mountain_belts(world_path: Path) -> None:
    from benchmarks.planet.scale_metrics import Build, report

    result = generate_planet(open_world(world_path), replace(FAST, climate_passes=0))
    surface = np.where(result.land, result.lakes.surface_m, result.elevation_m)
    metrics = report(
        Build(result.mesh, result.land, surface, result.flow.receiver, result.flow.area_m2)
    )
    rivers = metrics["rivers"]
    assert isinstance(rivers, dict) and rivers["largest_basins"]
    for basin in rivers["largest_basins"]:
        # Main stems are at least as long as a compact basin is wide.
        assert basin["main_stem_km"] >= 0.5 * basin["area_km2"] ** 0.5
    mountains = metrics["mountains"]
    assert isinstance(mountains, dict) and 0 <= mountains["mountain_share_of_land"] <= 1


def test_flexural_basins_fill_to_well_drained_plains() -> None:
    from dmtools.terrain.pipeline.planet_forcing import fill_basins
    from dmtools.terrain.pipeline.planet_kernels import steepest_receivers
    from dmtools.terrain.pipeline.planet_mesh import build_mesh

    mesh = build_mesh(6_000, RADIUS, 4)
    water = mesh.xyz[:, 2] < -0.4
    rng = np.random.default_rng(2)
    h = np.where(water, 0.0, 200 + 1500 * (mesh.xyz[:, 2] + 0.4) + 50 * rng.random(mesh.size))
    centre = np.array([1.0, 0.0, 0.3]) / np.linalg.norm([1.0, 0.0, 0.3])
    depth = np.where(water, 0.0, 1200 * np.clip(1 - np.arccos(mesh.xyz @ centre) / 0.25, 0, 1))
    filled = fill_basins(mesh, water, h, depth)
    outside = ~water & (depth <= 0)
    receiver, _ = steepest_receivers(
        filled, water, mesh.ptr, mesh.nbr, mesh.length_m, np.full(mesh.size, -1, np.int64)
    )
    assert np.all(receiver[~water] >= 0)  # every land node drains (no pits)
    basin = depth > 600
    assert filled[basin].std() < h[basin].std()  # the basin floor is smoother
    # Outside basins the surface is only raised where closed pits are filled.
    assert np.all(filled[outside] >= h[outside] - 1e-9)


def test_sea_floor_deepens_with_age_away_from_ridges_between_continents() -> None:
    from dmtools.terrain.pipeline.planet_forcing import coast_distance, ocean_floor
    from dmtools.terrain.pipeline.planet_mesh import build_mesh

    mesh = build_mesh(20_000, RADIUS, 6)
    # Two large polar caps of land with an ocean between them.
    land = np.abs(mesh.xyz[:, 2]) > 0.6
    coast = coast_distance(mesh, land)
    depth = -ocean_floor(mesh, coast, ~land, 3)
    ocean = ~land
    equator = ocean & (np.abs(mesh.xyz[:, 2]) < 0.05)  # the ridge, midway between them
    flank = ocean & (np.abs(np.abs(mesh.xyz[:, 2]) - 0.3) < 0.05)
    assert np.median(depth[equator]) < np.median(depth[flank]) - 400
    assert np.all(depth[ocean] > 0) and np.all(depth[land] == 0)


def test_plates_classify_boundaries_and_leading_edges_deterministically() -> None:
    from dmtools.terrain.pipeline.planet_forcing import coast_distance
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_tectonics import PLATE_COUNT, plate_tectonics

    mesh = build_mesh(20_000, RADIUS, 7)
    land = mesh.xyz[:, 0] > 0.3
    coast = coast_distance(mesh, land)
    first = plate_tectonics(mesh, land, coast, 11)
    second = plate_tectonics(mesh, land, coast, 11)
    assert np.array_equal(first.plate, second.plate)
    assert np.array_equal(first.convergence, second.convergence)
    assert 1 < len(np.unique(first.plate)) <= PLATE_COUNT
    # Plates move at Earth-like rates (cm/yr), boundaries both open and close.
    speed = np.hypot(first.velocity_east, first.velocity_north)
    assert 0.001 < np.median(speed) < 0.15
    near = first.boundary_m < 2 * mesh.spacing_m
    assert first.convergence[near].max() > 0 > first.convergence[near].min()
    # The signed across-strike distance flips sign across each boundary.
    assert np.allclose(np.abs(first.across_m), first.boundary_m)
    assert np.all((first.leading >= 0) & (first.leading <= 1))
