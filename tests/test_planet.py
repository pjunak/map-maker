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
from PIL import Image

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
    # Saved themes can be shown in other projections; changed files are refused.
    from dmtools.terrain.adapters.map_projection import MapProjection
    from dmtools.terrain.application.planet_views import export_view

    view = export_view(
        target, tmp_path / "globe.png", "relief", MapProjection("globe", 10.0, 20.0), 128,
        graticule=True,
    )
    with Image.open(view) as image:
        assert image.size == (128, 128)
    with pytest.raises(FileExistsError):
        export_view(target, view, "relief", MapProjection("globe"), 128)
    with pytest.raises(ValueError, match="Unknown view"):
        export_view(target, tmp_path / "x.png", "political", MapProjection("globe"), 128)
    (target / "relief.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        export_view(target, tmp_path / "y.png", "relief", MapProjection("globe"), 128)


def test_thematic_maps_cover_plates_basins_geology_and_sea_floor(world_path: Path) -> None:
    from dmtools.terrain.adapters.map_thematic import (
        PROVINCES,
        drainage_roots,
        geology_provinces,
    )
    from dmtools.terrain.adapters.map_views import THEME_BY_ID
    from dmtools.terrain.adapters.planet_natural import render_previews

    # Drainage roots follow receivers to the sea or to a closed-basin sink.
    receiver = np.array([-1, 0, 1, 3, 3, 2])
    assert drainage_roots(receiver).tolist() == [0, 0, 0, 3, 3, 0]
    result = generate_planet(open_world(world_path), FAST)
    province = geology_provinces(result)
    assert np.all(province[~result.land] == -1)
    assert set(np.unique(province[result.land]).tolist()) <= set(range(len(PROVINCES)))
    previews = render_previews(result, 256, 25_000.0)
    for theme in ("plates", "seafloor", "basins", "geology"):
        assert previews[THEME_BY_ID[theme].label].size == (256, 128)


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


def test_sea_floor_ages_away_from_spreading_ridges() -> None:
    from dmtools.terrain.pipeline.planet_forcing import (
        coast_distance,
        ocean_floor,
        plate_sea_floor_age_myr,
        sea_floor_age_myr,
    )
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_tectonics import plate_tectonics

    mesh = build_mesh(20_000, RADIUS, 6)
    # Two large polar caps of land with an ocean between them.
    land = np.abs(mesh.xyz[:, 2]) > 0.6
    coast = coast_distance(mesh, land)
    ocean = ~land
    # Without plates, the ridge runs midway between the continents.
    age = sea_floor_age_myr(mesh, land)
    equator = ocean & (np.abs(mesh.xyz[:, 2]) < 0.05)
    flank = ocean & (np.abs(np.abs(mesh.xyz[:, 2]) - 0.3) < 0.05)
    assert np.median(age[equator]) < np.median(age[flank])
    # With plates, crust is youngest on opening boundaries and ages away from them.
    plates = plate_tectonics(mesh, land, coast, 3)
    spreading = plate_sea_floor_age_myr(mesh, ocean, coast, plates, 3)
    if spreading is not None:
        plate_age, fracture = spreading
        ridge = ocean & (plates.boundary_m < mesh.spacing_m) & (plates.convergence < -0.005)
        assert np.median(plate_age[ridge]) < np.median(plate_age[ocean])
        # Transform faults cut the ridges; their fracture zones lie only at sea.
        assert fracture[ocean].any() and not fracture[land].any()
    depth = -ocean_floor(mesh, coast, ocean, 3, None, plates)
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


def test_big_river_mouths_build_wider_shelves() -> None:
    from dmtools.terrain.pipeline.planet_forcing import delta_shelf_width
    from dmtools.terrain.pipeline.planet_mesh import build_mesh

    mesh = build_mesh(20_000, RADIUS, 8)
    mouths = np.array([0, 5_000], dtype=np.int64)
    width = delta_shelf_width(mesh, mouths, np.array([4e8, 2e6]))
    big, small = width[mouths]
    assert 250e3 < big <= 350e3 and 10e3 < small < 40e3
    distance = np.arccos(np.clip(mesh.xyz @ mesh.xyz[mouths].T, -1, 1)) * RADIUS
    assert np.all(width[np.all(distance > 800e3, axis=1)] == 0)


def test_pit_catchments_are_found_from_receivers() -> None:
    from dmtools.terrain.pipeline.planet_kernels import draining_to

    # 0 <- 1 <- 2 (pit chain), 3 -> 4 -> sea (5)
    receiver = np.array([-1, 0, 1, 4, 5, -1], dtype=np.int64)
    water = np.array([False, False, False, False, False, True])
    trapped = draining_to(receiver, water, np.array([0], dtype=np.int64))
    assert trapped.tolist() == [True, True, True, False, False, False]


def test_volcanoes_follow_tectonic_settings_and_stay_below_sea_level_offshore() -> None:
    from dmtools.terrain.pipeline.planet_forcing import coast_distance
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_tectonics import plate_tectonics
    from dmtools.terrain.pipeline.planet_volcanism import (
        ARC,
        CALDERA,
        GUYOT_DEPTH_M,
        SEAMOUNT,
        Volcanoes,
        edifice_height,
        place_volcanoes,
    )

    mesh = build_mesh(40_000, RADIUS, 9)
    land = mesh.xyz[:, 0] > 0.2
    coast = coast_distance(mesh, land)
    plates = plate_tectonics(mesh, land, coast, 5)
    ground = np.where(land, 500.0, -4000.0)
    first = place_volcanoes(mesh, land, coast, plates, 21, ground)
    second = place_volcanoes(mesh, land, coast, plates, 21, ground)
    assert len(first) > 0 and np.array_equal(first.xyz, second.xyz)
    nearest = np.argmax(first.xyz @ mesh.xyz.T, axis=1)
    arc = first.setting == ARC
    # Arc volcanoes stand inland on leading-edge coasts.
    assert np.all(land[nearest[arc]]) and np.all(plates.leading[nearest[arc]] > 0.4)
    assert np.all(first.height_m[first.kind != SEAMOUNT] <= 6600 * 1.05)
    # A lone caldera has a floor below its rim.
    one = Volcanoes(
        np.array([[1.0, 0.0, 0.0]]), np.array([2000.0]), np.array([20e3]),
        np.array([CALDERA]), np.array([ARC]), np.array([True]), np.array([0.0]),
        np.array([6e3]), np.array([500.0]), np.array([np.nan]), np.array([False]),
    )
    angles = np.array([0.0, 5.5e3, 30e3]) / RADIUS
    points = np.stack([np.cos(angles), np.sin(angles), np.zeros(3)], axis=1)
    centre, rim, outside = edifice_height(points, RADIUS, one)
    assert centre < rim and outside == 0.0
    assert GUYOT_DEPTH_M < 0


def test_flood_basalts_cover_land_at_the_old_end_of_a_hotspot_track() -> None:
    from dmtools.terrain.pipeline.planet_forcing import TRAP_RADIUS_M, flood_basalts
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_tectonics import plate_tectonics

    mesh = build_mesh(20_000, RADIUS, 10)
    land = np.ones(mesh.size, dtype=bool)
    land[np.argmin(mesh.xyz[:, 2])] = False  # one ocean node so coasts exist
    from dmtools.terrain.pipeline.planet_forcing import coast_distance

    coast = coast_distance(mesh, land)
    plates = plate_tectonics(mesh, land, coast, 3)
    cover = flood_basalts(mesh, land, coast, plates)
    assert np.all((cover >= 0) & (cover <= 1))
    # Each province is at most a few times the nominal radius across.
    assert mesh.area_m2[cover > 0.5].sum() < len(plates.plumes) * np.pi * (1.5 * TRAP_RADIUS_M) ** 2


def test_mountain_belts_vary_along_strike() -> None:
    from dmtools.terrain.pipeline.planet_forcing import (
        MASSIF_FLOOR,
        orogen_profile,
        strike_variation,
    )
    from dmtools.terrain.pipeline.planet_mesh import build_mesh

    mesh = build_mesh(40_000, RADIUS, 12)
    p = mesh.xyz
    # A straight belt along the equator, 100 km half-width.
    across_m = p[:, 2] * RADIUS
    half_width = np.full(mesh.size, 100e3)
    across, half, massif = strike_variation(p, 5, across_m, half_width)
    assert np.all(np.abs(across - across_m) <= 1.7 * half_width + 1)
    assert np.all((half >= 0.6 * half_width - 1) & (half <= 1.4 * half_width + 1))
    assert np.all((massif >= 0) & (massif <= 1))
    # Along the crest the height rises into massifs and falls to saddles and gaps
    # instead of running at one even height for thousands of kilometres.
    crest = orogen_profile(across, half, p, 5) * massif
    on_axis = np.abs(across) < 0.2 * half
    heights = crest[on_axis]
    assert heights.max() > 0.8
    assert (heights < MASSIF_FLOOR).mean() > 0.1


def test_koppen_classes_follow_the_standard_rules() -> None:
    from dmtools.terrain.pipeline.planet_koppen import KOPPEN, classify_koppen

    def one(mean: float, warm: float, cold: float, p_warm: float, p_cold: float) -> str:
        def a(v: float) -> np.ndarray:
            return np.array([v])

        classes = classify_koppen(a(mean), a(warm), a(cold), a(p_warm), a(p_cold), np.array([True]))
        return KOPPEN[int(classes[0])]

    assert one(26, 28, 24, 2600, 2400) == "Af"  # rainforest
    assert one(27, 32, 20, 2200, 100) == "Aw"  # savanna, dry winter
    assert one(24, 34, 12, 60, 40) == "BWh"  # hot desert
    assert one(16, 24, 9, 60, 1100) == "Csa"  # Mediterranean, dry summer
    assert one(9, 17, 2, 900, 800) == "Cfb"  # oceanic
    assert one(-4, 16, -24, 700, 300) == "Dfc"  # boreal
    assert one(-12, 4, -28, 300, 200) == "ET"  # tundra
    assert one(-30, -8, -45, 100, 100) == "EF"  # ice cap


def test_air_is_more_continental_downwind_of_land() -> None:
    from dmtools.terrain.domain.planet import PlanetClimateSettings
    from dmtools.terrain.pipeline.planet_climate import simulate_climate
    from dmtools.terrain.pipeline.planet_forcing import coast_distance
    from dmtools.terrain.pipeline.planet_mesh import build_mesh

    mesh = build_mesh(20_000, RADIUS, 11)
    lon = np.degrees(np.arctan2(mesh.xyz[:, 1], mesh.xyz[:, 0]))
    lat = np.degrees(np.arcsin(mesh.xyz[:, 2]))
    # A mid-latitude continent under the westerlies.
    land = (np.abs(lon) < 40) & (lat > 35) & (lat < 60)
    coast = coast_distance(mesh, land)
    climate = simulate_climate(
        mesh, np.where(land, 200.0, 0.0), land, coast, PlanetClimateSettings(), steps=200
    )
    near_coast = land & (coast < 400e3) & (lat > 42) & (lat < 53)
    west = near_coast & (lon < -25)
    east = near_coast & (lon > 25)
    assert climate.continentality[east].mean() > climate.continentality[west].mean()
    span = climate.warm_c - climate.cold_c
    assert span[east].mean() > span[west].mean()


def test_summer_rain_belts_reach_further_over_heated_subtropical_land() -> None:
    from dmtools.terrain.domain.planet import PlanetClimateSettings
    from dmtools.terrain.pipeline.planet_climate import monsoon_shift
    from dmtools.terrain.pipeline.planet_mesh import build_mesh

    mesh = build_mesh(20_000, RADIUS, 12)
    lon = np.degrees(np.arctan2(mesh.xyz[:, 1], mesh.xyz[:, 0]))
    lat = np.degrees(np.arcsin(mesh.xyz[:, 2]))
    land = (np.abs(lon) < 50) & (lat > 5) & (lat < 40)  # a northern subtropical continent
    south, north = monsoon_shift(mesh, land, PlanetClimateSettings())
    over_land = land & (lat > 15) & (lat < 30)
    open_ocean = (np.abs(lon) > 120) & (lat > 15) & (lat < 30)
    assert north[over_land].mean() > north[open_ocean].mean() + 5
    assert np.all(south <= 0) and np.all(north >= 0)


def test_snowline_rises_with_dryness_and_massifs_warm_in_summer() -> None:
    from dmtools.terrain.adapters.planet_natural import equilibrium_line_c
    from dmtools.terrain.pipeline.planet_climate import mass_elevation_warming
    from dmtools.terrain.pipeline.planet_mesh import build_mesh

    ela = equilibrium_line_c(np.array([100.0, 1000.0, 2000.0]))
    assert ela[0] < ela[1] < ela[2]
    assert -2.5 < ela[0] < -1.5 and 0.5 < ela[1] < 1.5 and 3.5 < ela[2] < 4.5
    mesh = build_mesh(20_000, RADIUS, 13)
    plateau = np.where(mesh.xyz[:, 2] > 0.8, 4500.0, 200.0)
    warming = mass_elevation_warming(mesh, plateau)
    assert warming[mesh.xyz[:, 2] > 0.95].mean() > 3.0
    assert np.all(warming[mesh.xyz[:, 2] < 0.0] == 0.0)


def test_planned_islands_emerge_while_other_seamounts_stay_drowned() -> None:
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_volcanism import (
        GUYOT_DEPTH_M,
        HOTSPOT,
        INTRAPLATE,
        SEAMOUNT,
        Volcanoes,
        emerge,
        sea_floor_with_volcanoes,
    )

    mesh = build_mesh(20_000, RADIUS, 14)
    water = np.ones(mesh.size, dtype=bool)
    floor = np.full(mesh.size, -4500.0)
    a = mesh.xyz[100]
    b = mesh.xyz[int(np.argmin(mesh.xyz @ a))]  # the far side of the planet
    volcanoes = Volcanoes(
        np.stack((a, b)), np.array([3000.0, 3000.0]), np.array([25e3, 25e3]),
        np.array([SEAMOUNT, SEAMOUNT]), np.array([HOTSPOT, INTRAPLATE]),
        np.array([True, False]), np.array([0.0, 50.0]), np.zeros(2), np.zeros(2),
        np.array([3500.0, np.nan]), np.array([False, False]),
    )
    risen = emerge(volcanoes, mesh, water, floor)
    assert risen.emergent.tolist() == [True, False]
    assert risen.height_m[0] == pytest.approx(8000.0)
    surface = sea_floor_with_volcanoes(np.stack((a, b)), RADIUS, risen, np.full(2, -4500.0))
    assert surface[0] == pytest.approx(3500.0, rel=0.02)
    assert surface[1] <= GUYOT_DEPTH_M


def test_titan_is_a_giant_inland_shield_with_a_basal_cliff() -> None:
    from dmtools.terrain.pipeline.planet_forcing import coast_distance
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_tectonics import plate_tectonics
    from dmtools.terrain.pipeline.planet_volcanism import (
        MAX_SUMMIT_M,
        TITAN,
        TITAN_MIN_COAST_M,
        edifice_height,
        place_volcanoes,
    )

    mesh = build_mesh(20_000, RADIUS, 13)
    land = mesh.xyz[:, 2] > -0.2
    coast = coast_distance(mesh, land)
    plates = plate_tectonics(mesh, land, coast, 4)
    ground = np.where(land, 300.0, -4000.0)
    plain = place_volcanoes(mesh, land, coast, plates, 4, ground)
    assert not (plain.setting == TITAN).any()
    volcanoes = place_volcanoes(mesh, land, coast, plates, 4, ground, titan=True)
    titan = volcanoes.subset(volcanoes.setting == TITAN)
    assert len(titan) == 1 and titan.height_m[0] > MAX_SUMMIT_M
    site = int(np.argmax(mesh.xyz @ titan.xyz[0]))
    assert land[site] and coast[site] >= TITAN_MIN_COAST_M
    # Radial profiles: the caldera floor sits below its rim, and the flank
    # ends in a cliff much steeper than the shield's slopes.
    east = np.cross([0.0, 0.0, 1.0], titan.xyz[0])
    east /= np.linalg.norm(east)
    north = np.cross(titan.xyz[0], east)
    azimuth = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    radius = float(titan.radius_m[0])
    distance = np.arange(0.0, 1.5 * radius, 2e3)
    tangent = np.cos(azimuth)[:, None] * east + np.sin(azimuth)[:, None] * north
    angle = (distance / RADIUS)[None, :, None]
    points = (np.cos(angle) * titan.xyz[0] + np.sin(angle) * tangent[:, None, :]).reshape(-1, 3)
    height = edifice_height(points, RADIUS, titan).reshape(len(azimuth), len(distance))
    assert np.median(height[:, 0]) < np.median(height[:, 20])  # caldera floor below rim
    drop = -np.diff(height, axis=1) / 2e3
    mid = (distance[1:] > 0.3 * radius) & (distance[1:] < 0.6 * radius)
    flank = np.median(drop[:, mid])
    cliff = np.median(drop.max(axis=1))
    assert cliff > 3 * flank


def test_craters_have_level_troughs_central_plateaus_and_raised_rims() -> None:
    from dmtools.terrain.pipeline.planet_forcing import coast_distance
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_wonders import (
        crater_relief,
        level_crater_floors,
        place_craters,
    )

    mesh = build_mesh(60_000, RADIUS, 14)
    land = mesh.xyz[:, 2] > -0.3
    coast = coast_distance(mesh, land)
    # Land sloping by ~2 km across a hemisphere.
    ground = np.where(land, 1500.0 + 1000.0 * mesh.xyz[:, 0], 0.0)
    craters = place_craters(mesh, land, coast, ground, np.random.default_rng(3))
    assert len(craters) >= 1
    for xyz, radius in zip(craters.xyz, craters.radius_m, strict=True):
        site = int(np.argmax(mesh.xyz @ xyz))
        assert land[site] and coast[site] > 2 * radius
    xyz, radius, depth = craters.xyz[0], craters.radius_m[0], craters.depth_m[0]
    s = np.arccos(np.clip(mesh.xyz @ xyz, -1, 1)) * RADIUS / radius
    levelled = level_crater_floors(mesh, ground, craters)
    assert np.ptp(levelled[s < 0.8]) < 1e-6 < np.ptp(ground[s < 0.8])
    east = np.cross([0.0, 0.0, 1.0], xyz)
    east /= np.linalg.norm(east)
    north = np.cross(xyz, east)
    azimuth = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    tangent = np.cos(azimuth)[:, None] * east + np.sin(azimuth)[:, None] * north

    def ring(share: float) -> float:
        angle = share * radius / RADIUS
        points = np.cos(angle) * xyz + np.sin(angle) * tangent
        return float(np.median(crater_relief(points, RADIUS, craters)))

    trough = ring(0.47)
    assert trough < -0.5 * depth
    assert ring(0.0) > trough + 0.6 * depth  # central plateau
    assert ring(1.0) > 0  # raised rim
    assert ring(2.6) == 0


def test_wonders_land_in_the_same_place_at_any_mesh_resolution() -> None:
    from dmtools.terrain.pipeline.planet_forcing import coast_distance
    from dmtools.terrain.pipeline.planet_mesh import build_mesh
    from dmtools.terrain.pipeline.planet_wonders import place_craters

    centres = []
    for nodes in (30_000, 120_000):
        mesh = build_mesh(nodes, RADIUS, 15)
        land = mesh.xyz[:, 2] > -0.3
        coast = coast_distance(mesh, land)
        ground = np.where(land, 1500.0 + 1000.0 * mesh.xyz[:, 0], 0.0)
        centres.append(place_craters(mesh, land, coast, ground, np.random.default_rng(5)).xyz)
    coarse, fine = centres
    assert len(coarse) == len(fine) >= 1
    assert np.allclose(coarse, fine)


def test_hand_placed_landmarks_replace_random_wonders(world_path: Path) -> None:
    from dataclasses import replace as replace_recipe

    from dmtools.terrain.domain.world_geology import GeologyLandmark
    from dmtools.terrain.pipeline.planet_volcanism import TITAN

    world = open_world(world_path)
    recipe = sample_recipe(world_path)
    plain = generate_planet(world, replace(FAST, climate_passes=0), recipe)
    frame = world.project.frame
    inland = np.argsort(np.where(plain.land, plain.coast_m, -1.0))[::-1]
    first = int(inland[0])
    # A second inland site well away from the first.
    far = next(
        int(k) for k in inland[1:]
        if plain.mesh.xyz[k] @ plain.mesh.xyz[first] < np.cos(1500e3 / plain.mesh.radius_m)
    )

    def source(node: int) -> tuple[float, float]:
        x, y, z = plain.mesh.xyz[node]
        lonlat = (float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(z))))
        return frame.lonlat_to_source(lonlat)

    placed = replace_recipe(
        recipe,
        landmarks=(
            GeologyLandmark("landmark-sky", "Skyfather", "titan", source(first), 400.0),
            GeologyLandmark("landmark-eye", "The Eye", "crater", source(far), 200.0),
        ),
    )
    result = generate_planet(world, replace(FAST, climate_passes=0), placed)
    titans = result.volcanoes.subset(result.volcanoes.setting == TITAN)
    assert len(titans) == 1
    assert titans.xyz[0] @ plain.mesh.xyz[first] > np.cos(0.5 * plain.mesh.spacing_m / RADIUS)
    assert titans.radius_m[0] == pytest.approx(200e3)
    assert len(result.craters) == 1
    assert result.craters.xyz[0] @ plain.mesh.xyz[far] > np.cos(
        0.5 * plain.mesh.spacing_m / RADIUS
    )
    assert result.craters.radius_m[0] == pytest.approx(100e3)
    # A crater in the sea is reported, not moved.
    sea = int(np.argmax(np.where(plain.land, -1.0, -plain.elevation_m)))
    wet = replace_recipe(
        recipe, landmarks=(GeologyLandmark("landmark-wet", "Wet", "crater", source(sea)),)
    )
    with pytest.raises(ValueError, match=r"Wet.*sea"):
        generate_planet(world, replace(FAST, climate_passes=0), wet)


def test_volcanic_islands_are_off_by_default(world_path: Path) -> None:
    result = generate_planet(open_world(world_path), replace(FAST, climate_passes=0))
    assert not result.settings.volcanic_islands
    assert not result.volcanoes.emergent.any() and not result.islands.any()
