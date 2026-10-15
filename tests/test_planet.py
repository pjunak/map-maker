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
from map_maker.terrain.adapters.build import file_sha256
from map_maker.terrain.adapters.planet_load import read_planet_parent
from map_maker.terrain.adapters.world_geology import write_geology
from map_maker.terrain.application.planet import build_planet, input_identity
from map_maker.terrain.application.world import open_world
from map_maker.terrain.domain.planet import PlanetClimateSettings, PlanetSettings
from map_maker.terrain.domain.wonders import WonderSettings
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled
from map_maker.terrain.pipeline.planet import generate_planet
from map_maker.terrain.pipeline.planet_climate import simulate_climate
from map_maker.terrain.pipeline.planet_evolution import calibrated_relief, route
from map_maker.terrain.pipeline.planet_forcing import (
    coast_distance,
    geology_regions,
    land_on_mesh,
)
from map_maker.terrain.pipeline.planet_kernels import accumulate, laplacian, priority_flood
from map_maker.terrain.pipeline.planet_mesh import SphereMesh, build_mesh
from map_maker.terrain.pipeline.planet_metrics import compass_share, non_descending_receivers
from map_maker.terrain.pipeline.planet_scarps import Tepuis
from map_maker.terrain.pipeline.planet_wonders import Chasms

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
    for wrong in (
        {"random": True},
        {"random": ["crater"]},
        {"random": ("crater", "crater")},
        {"random": ("dragon",)},
        {"age_myr": -1.0},
        {"age_myr": 1e6},
        {"age_myr": True},
    ):
        with pytest.raises(ValueError):
            WonderSettings(**wrong)  # type: ignore[arg-type]


def test_wonder_kinds_are_chosen_by_name_or_all() -> None:
    from map_maker.terrain.domain.wonders import WONDER_KINDS, wonder_kinds

    assert wonder_kinds("all") == WONDER_KINDS
    assert wonder_kinds(" Chasm, crater ") == ("crater", "chasm")  # catalog order
    assert wonder_kinds("") == ()
    with pytest.raises(ValueError, match="dragon"):
        wonder_kinds("crater,dragon")
    # The public schemas list exactly the catalog's kinds.
    root = Path(__file__).parents[1] / "schemas/world"
    placed = json.loads((root / "wonders-v2.schema.json").read_text(encoding="utf-8"))
    build = json.loads((root / "planet-build-v2.schema.json").read_text(encoding="utf-8"))
    kind = placed["properties"]["wonders"]["items"]["properties"]["kind"]
    assert tuple(kind["enum"]) == WONDER_KINDS
    random = build["properties"]["wonder_settings"]["properties"]["random"]
    assert tuple(random["items"]["enum"]) == WONDER_KINDS


def test_planet_build_publishes_verified_world_aligned_products(
    world_path: Path, tmp_path: Path
) -> None:
    geology = tmp_path / "w.geology.json"
    write_geology(sample_recipe(world_path), geology, None)
    manifest_path = build_planet(world_path, tmp_path / "planet", geology, FAST, width=256)
    target = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas/world/planet-build-v2.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    for name, record in manifest["outputs"].items():
        assert file_sha256(target / name) == record["sha256"]
    assert {"atlas.png", "precipitation.png", "temperature.png", "input.geology.json"} <= set(
        manifest["outputs"]
    )
    recipe = sample_recipe(world_path)
    assert manifest["inputs"] == {**input_identity(recipe.world, recipe), "wonders_sha256": None}
    assert manifest["wonder_settings"] == {"random": [], "age_myr": 0.0}
    assert {"atlas.png", "relief.png", "precipitation.png", "temperature.png"} <= set(
        manifest["outputs"]
    )
    assert not (target / "manifest.pending").exists()
    with np.load(target / "planet.npz", allow_pickle=False) as archive:
        land = archive["land"]
        assert np.all(archive["elevation_m"][land] >= 1.0)
        assert set(np.unique(archive["biome"][land]).tolist()) <= set(range(1, 14))
        assert archive["xyz"].shape == (FAST.nodes, 3)
        ice, balance = archive["ice_m"], archive["ice_balance_m"]
        assert np.all(np.isfinite(ice)) and np.all(ice >= 0) and not ice[~land].any()
        assert np.all(np.isfinite(balance))
    assert 0.0 <= manifest["climate"]["ice_sheet_share"] <= 1.0
    reopened = read_planet_parent(target)
    loaded = reopened.parent
    assert loaded.ice is not None
    assert np.allclose(loaded.ice.thickness_m, ice)
    # Without wonders the planet is its own base, and tiles start from it.
    assert reopened.base_sha256 == manifest["base_sha256"] != manifest["build_sha256"]
    assert np.array_equal(reopened.tiles.surface_m, loaded.surface_m)
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
    from map_maker.terrain.adapters.map_projection import MapProjection
    from map_maker.terrain.application.planet_views import export_view

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
    from map_maker.terrain.adapters.map_thematic import (
        PROVINCES,
        drainage_roots,
        geology_provinces,
    )
    from map_maker.terrain.adapters.map_views import THEME_BY_ID
    from map_maker.terrain.adapters.planet_natural import render_previews

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
    import map_maker.terrain.pipeline.planet as planet

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
    from map_maker.terrain.pipeline.planet_lakes import balance_lakes

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
    from map_maker.terrain.pipeline.planet_lakes import young_depressions

    mesh = build_mesh(8_000, RADIUS, 2)
    land = np.ones(mesh.size, dtype=bool)
    coast = np.full(mesh.size, 1e6)
    flat = np.full(mesh.size, 200.0)
    cool = np.full(mesh.size, 10.0)
    ice_free = young_depressions(mesh, land, coast, None, cool, None, flat, 1)
    assert ice_free.max() > 0
    # Under an ice sheet depressions hold ice, not lakes; beside it they stay.
    sheet = np.where(mesh.xyz[:, 2] > 0, 1500.0, 0.0)
    iced = young_depressions(mesh, land, coast, None, cool, sheet, flat, 1)
    assert not iced[sheet > 0].any()
    assert np.array_equal(iced[sheet == 0], ice_free[sheet == 0])


def test_fine_meshes_couple_climate_on_coarser_meshes(
    world_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import map_maker.terrain.pipeline.planet as planet

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
    from map_maker.terrain.pipeline.planet_forcing import fill_basins
    from map_maker.terrain.pipeline.planet_kernels import steepest_receivers
    from map_maker.terrain.pipeline.planet_mesh import build_mesh

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
    from map_maker.terrain.pipeline.planet_forcing import (
        coast_distance,
        ocean_floor,
        plate_sea_floor_age_myr,
        sea_floor_age_myr,
    )
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_tectonics import plate_tectonics

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
    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_tectonics import PLATE_COUNT, plate_tectonics

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
    from map_maker.terrain.pipeline.planet_forcing import delta_shelf_width
    from map_maker.terrain.pipeline.planet_mesh import build_mesh

    mesh = build_mesh(20_000, RADIUS, 8)
    mouths = np.array([0, 5_000], dtype=np.int64)
    width = delta_shelf_width(mesh, mouths, np.array([4e8, 2e6]))
    big, small = width[mouths]
    assert 250e3 < big <= 350e3 and 10e3 < small < 40e3
    distance = np.arccos(np.clip(mesh.xyz @ mesh.xyz[mouths].T, -1, 1)) * RADIUS
    assert np.all(width[np.all(distance > 800e3, axis=1)] == 0)


def test_pit_catchments_are_found_from_receivers() -> None:
    from map_maker.terrain.pipeline.planet_kernels import draining_to

    # 0 <- 1 <- 2 (pit chain), 3 -> 4 -> sea (5)
    receiver = np.array([-1, 0, 1, 4, 5, -1], dtype=np.int64)
    water = np.array([False, False, False, False, False, True])
    trapped = draining_to(receiver, water, np.array([0], dtype=np.int64))
    assert trapped.tolist() == [True, True, True, False, False, False]


def test_volcanoes_follow_tectonic_settings_and_stay_below_sea_level_offshore() -> None:
    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_tectonics import plate_tectonics
    from map_maker.terrain.pipeline.planet_volcanism import (
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
    from map_maker.terrain.pipeline.planet_forcing import TRAP_RADIUS_M, flood_basalts
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_tectonics import plate_tectonics

    mesh = build_mesh(20_000, RADIUS, 10)
    land = np.ones(mesh.size, dtype=bool)
    land[np.argmin(mesh.xyz[:, 2])] = False  # one ocean node so coasts exist
    from map_maker.terrain.pipeline.planet_forcing import coast_distance

    coast = coast_distance(mesh, land)
    plates = plate_tectonics(mesh, land, coast, 3)
    cover = flood_basalts(mesh, land, coast, plates)
    assert np.all((cover >= 0) & (cover <= 1))
    # Each province is at most a few times the nominal radius across.
    assert mesh.area_m2[cover > 0.5].sum() < len(plates.plumes) * np.pi * (1.5 * TRAP_RADIUS_M) ** 2


def test_mountain_belts_vary_along_strike() -> None:
    from map_maker.terrain.pipeline.planet_forcing import (
        MASSIF_FLOOR,
        orogen_profile,
        strike_variation,
    )
    from map_maker.terrain.pipeline.planet_mesh import build_mesh

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
    from map_maker.terrain.pipeline.planet_koppen import KOPPEN, classify_koppen

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
    from map_maker.terrain.domain.planet import PlanetClimateSettings
    from map_maker.terrain.pipeline.planet_climate import simulate_climate
    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh

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
    from map_maker.terrain.domain.planet import PlanetClimateSettings
    from map_maker.terrain.pipeline.planet_climate import monsoon_shift
    from map_maker.terrain.pipeline.planet_mesh import build_mesh

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
    from map_maker.terrain.pipeline.planet_climate import mass_elevation_warming
    from map_maker.terrain.pipeline.planet_ice import equilibrium_line_c
    from map_maker.terrain.pipeline.planet_mesh import build_mesh

    ela = equilibrium_line_c(np.array([100.0, 1000.0, 2000.0]))
    assert ela[0] < ela[1] < ela[2]
    assert -2.5 < ela[0] < -1.5 and 0.5 < ela[1] < 1.5 and 3.5 < ela[2] < 4.5
    mesh = build_mesh(20_000, RADIUS, 13)
    plateau = np.where(mesh.xyz[:, 2] > 0.8, 4500.0, 200.0)
    warming = mass_elevation_warming(mesh, plateau)
    assert warming[mesh.xyz[:, 2] > 0.95].mean() > 3.0
    assert np.all(warming[mesh.xyz[:, 2] < 0.0] == 0.0)


def test_planned_islands_emerge_while_other_seamounts_stay_drowned() -> None:
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_volcanism import (
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


def test_placed_wonder_settings_fix_what_they_name() -> None:
    from scipy.spatial import KDTree

    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_scarps import authored_tepuis, tepui_height_m
    from map_maker.terrain.pipeline.planet_volcanism import placed_volcano
    from map_maker.terrain.pipeline.planet_wonders import authored_craters, chasm_with_canyons
    from map_maker.terrain.pipeline.wonder_geometry import destination

    mesh = build_mesh(20_000, RADIUS, 13)
    land = np.ones(mesh.size, dtype=bool)
    ground = np.full(mesh.size, 2000.0)
    site = np.array([1.0, 0.0, 0.0])
    # A fixed height replaces the one from the size; the rest of the shape stays.
    for kind, radius, height in (
        ("titan", 280e3, 12000.0), ("shattered", 35e3, 3000.0), ("active", 60e3, 8000.0)
    ):
        free = placed_volcano(kind, site, radius, 7)
        fixed = placed_volcano(kind, site, radius, 7, height)
        assert fixed.height_m[0] == height != free.height_m[0]
        assert fixed.radius_m[0] == free.radius_m[0]
    # Tepuis: values left blank are drawn as they would be without the others.

    def tepui(fixed: tuple[float | None, float | None, float | None] | None) -> Tepuis:
        return authored_tepuis(
            mesh, land, site[None], np.array([30e3]), ("T",), (np.random.default_rng(3),),
            None if fixed is None else (fixed,),
        )

    free_tepui, fixed_tepui = tepui(None), tepui((2500.0, 1.5, 60.0))
    assert free_tepui.height_m[0] == tepui_height_m(30e3)
    assert (fixed_tepui.height_m[0], fixed_tepui.aspect[0]) == (2500.0, 1.5)
    assert fixed_tepui.azimuth[0] == pytest.approx(np.radians(60.0))
    assert tepui((None, 1.5, None)).azimuth[0] == free_tepui.azimuth[0]
    # Craters: a fixed depth, or an error where the ground cannot hold it.
    craters = authored_craters(
        mesh, land, ground, site[None], np.array([100e3]), ("The Eye",), (1500.0,)
    )
    assert craters.depth_m[0] == 1500.0
    with pytest.raises(ValueError, match="The Eye: the ground there holds a crater at most"):
        authored_craters(mesh, land, ground, site[None], np.array([100e3]), ("The Eye",), (5e3,))
    # Chasms: counts of side canyons and troughs, and a cap on the depth.
    tree = KDTree(mesh.xyz)
    end = destination(site, 0.5, 800e3 / RADIUS)

    def chasm(depth: float = 3000.0, **counts: float) -> Chasms:
        return chasm_with_canyons(
            site, end, 40e3, depth, ground, tree, RADIUS, np.random.default_rng(5), **counts
        )

    bare, rich, free_chasm = chasm(side_canyons=0, parallel_troughs=0), chasm(
        side_canyons=8, parallel_troughs=3
    ), chasm()
    assert len(bare) <= 1 + 4 < len(rich)  # only the splays at its two ends remain
    assert np.array_equal(bare.paths[0], free_chasm.paths[0])
    assert np.array_equal(rich.paths[0], free_chasm.paths[0])
    shallow = chasm(800.0)
    assert shallow.depth_m[0].max() <= 800.0 < free_chasm.depth_m[0].max()


def test_titan_is_a_giant_inland_shield_with_a_basal_cliff() -> None:
    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_tectonics import plate_tectonics
    from map_maker.terrain.pipeline.planet_volcanism import (
        MAX_SUMMIT_M,
        TITAN,
        TITAN_MIN_COAST_M,
        edifice_height,
        place_volcanoes,
        wonder_volcanoes,
    )

    mesh = build_mesh(20_000, RADIUS, 13)
    land = mesh.xyz[:, 2] > -0.2
    coast = coast_distance(mesh, land)
    plates = plate_tectonics(mesh, land, coast, 4)
    ground = np.where(land, 300.0, -4000.0)
    plain = place_volcanoes(mesh, land, coast, plates, 4, ground)
    assert not (plain.setting == TITAN).any()
    volcanoes = wonder_volcanoes(mesh, land, coast, 4, ("titan",))
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
    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_wonders import (
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
    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_scarps import place_cliff, tepui_group
    from map_maker.terrain.pipeline.planet_wonders import place_chasm, place_craters

    centres, axes, scarps, mesas = [], [], [], []
    for nodes in (30_000, 120_000):
        mesh = build_mesh(nodes, RADIUS, 15)
        land = mesh.xyz[:, 2] > -0.3
        coast = coast_distance(mesh, land)
        ground = np.where(land, 1500.0 + 1000.0 * mesh.xyz[:, 0], 0.0)
        centres.append(place_craters(mesh, land, coast, ground, np.random.default_rng(5)).xyz)
        axes.append(place_chasm(mesh, land, coast, ground, np.random.default_rng(5)).paths[0])
        scarps.append(place_cliff(mesh, land, coast, ground, np.random.default_rng(5)).paths[0])
        mesas.append(tepui_group(mesh, land, coast, np.random.default_rng(5)).xyz)
    coarse, fine = centres
    assert len(coarse) == len(fine) >= 1
    assert np.allclose(coarse, fine)
    assert np.allclose(*axes)
    assert np.allclose(*scarps)
    assert len(mesas[0]) == len(mesas[1]) >= 1 and np.allclose(*mesas)


def straight_chasm(depth: float) -> tuple[np.ndarray, Chasms]:
    from map_maker.terrain.pipeline.planet_wonders import Chasms
    from map_maker.terrain.pipeline.wonder_geometry import destination, rift_axis

    start = np.array([1.0, 0.0, 0.0])
    end = destination(start, np.pi / 2, 1500e3 / RADIUS)
    axis = rift_axis(start, end, 60e3, RADIUS, np.random.default_rng(4))
    return axis, Chasms((axis,), np.array([60e3]), (np.full(len(axis), depth),))


def test_chasms_have_floors_ragged_walls_shoulders_and_headwalls() -> None:
    from map_maker.terrain.pipeline.planet_wonders import chasm_relief

    axis, chasms = straight_chasm(2000.0)
    assert len(axis) > 100
    # Cross-sections every few vertices along the middle of the chasm, out to
    # seven half widths (30 km) on either side.
    rows = np.arange(len(axis) // 5, 4 * len(axis) // 5, 4)
    tangent = axis[rows + 1] - axis[rows - 1]
    tangent -= np.sum(tangent * axis[rows], axis=1)[:, None] * axis[rows]
    normal = np.cross(axis[rows], tangent / np.linalg.norm(tangent, axis=1)[:, None])
    offsets = np.linspace(-7.0, 7.0, 141)
    angle = (offsets * 30e3 / RADIUS)[None, :, None]
    points = np.cos(angle) * axis[rows][:, None] + np.sin(angle) * normal[:, None]
    height = chasm_relief(points.reshape(-1, 3), RADIUS, chasms).reshape(len(rows), -1)
    centre = height[:, 70]
    assert np.median(centre) == pytest.approx(-2000.0, rel=0.05)  # floor, slightly hummocky
    assert np.all(height[:, [0, -1]] == 0)  # nothing beyond the reach
    assert np.median(height[:, np.abs(offsets - 2.5).argmin()]) > 0.1 * 2000  # shoulders
    # Each wall's rim (where the cut ends) wanders on its own: ragged, and
    # not mirrored by the opposite wall.
    inside = height < -0.1 * 2000
    left = offsets[np.argmax(inside, axis=1)]
    right = offsets[len(offsets) - 1 - np.argmax(inside[:, ::-1], axis=1)]
    assert np.std(right) > 0.1 * np.mean(right) and np.std(left) > 0.1 * np.mean(-left)
    assert abs(np.corrcoef(right, -left)[0, 1]) < 0.6
    # The ends stop at rounded headwalls rather than pinching out.
    ends = chasm_relief(axis[[0, -1]], RADIUS, chasms)
    assert np.all(ends < -0.5 * 2000)
    # A finer map adds detail to the same large shapes.
    fine = chasm_relief(points.reshape(-1, 3), RADIUS, chasms, 500.0).reshape(height.shape)
    assert not np.allclose(fine, height)
    assert np.corrcoef(fine.ravel(), height.ravel())[0, 1] > 0.9


def test_cliffs_raise_a_tilted_block_behind_a_steep_face() -> None:
    from map_maker.terrain.pipeline.planet_scarps import CLIFF_BACK, Cliffs, cliff_relief
    from map_maker.terrain.pipeline.wonder_geometry import destination, rift_axis

    start = np.array([1.0, 0.0, 0.0])
    end = destination(start, np.pi / 2, 600e3 / RADIUS)
    axis = rift_axis(start, end, 30e3, RADIUS, np.random.default_rng(5), wander=0.4)
    height = 2500.0
    cliffs = Cliffs((axis,), np.array([height]), (np.full(len(axis), 200.0),))
    # Cross-sections along the middle third, from 40 km on the low side to
    # 120 km on the high side (left of the path).
    rows = np.arange(len(axis) // 3, 2 * len(axis) // 3, 3)
    tangent = axis[rows + 1] - axis[rows - 1]
    tangent -= np.sum(tangent * axis[rows], axis=1)[:, None] * axis[rows]
    left = np.cross(axis[rows], tangent / np.linalg.norm(tangent, axis=1)[:, None])
    offsets_km = np.arange(-40.0, 120.5, 0.5)
    angle = (offsets_km * 1e3 / RADIUS)[None, :, None]
    points = np.cos(angle) * axis[rows][:, None] + np.sin(angle) * left[:, None]
    h = cliff_relief(points.reshape(-1, 3), RADIUS, cliffs).reshape(len(rows), -1)

    def at(km: float) -> float:
        return float(np.median(h[:, np.abs(offsets_km - km).argmin()]))

    assert at(20.0) > 0.8 * height  # the raised block behind the edge
    back_km = CLIFF_BACK * height / 1e3
    assert 0.2 * height < at(0.5 * back_km) < 0.8 * height  # tilting back
    assert abs(at(-30.0)) < 0.05 * height  # the plain below
    # A steep face: each section climbs most of the height within a few km.
    steepest = np.max(np.diff(h, axis=1), axis=1) / 500.0
    assert np.median(steepest) > 0.3
    # The scarp dies out at its ends.
    ends = cliff_relief(
        np.stack([np.cos(10e3 / RADIUS) * axis[k] + np.sin(10e3 / RADIUS) * left[0]
                  for k in (0, -1)]), RADIUS, cliffs,
    )
    assert np.all(ends < 0.3 * height)


def test_tepuis_stand_flat_topped_behind_sheer_walls() -> None:
    from map_maker.terrain.pipeline.planet_scarps import Tepuis, tepui_relief

    centre = np.array([1.0, 0.0, 0.0])
    tepuis = Tepuis(centre[None], np.array([30e3]), np.array([1800.0]), np.ones(1), np.zeros(1))
    side = np.linspace(-90e3, 90e3, 181) / RADIUS
    y, z = np.meshgrid(side, side)
    points = np.stack([np.ones(y.size), y.ravel(), z.ravel()], axis=1)
    points /= np.linalg.norm(points, axis=1)[:, None]
    h = tepui_relief(points, RADIUS, tepuis)
    assert h[np.argmax(points @ centre)] == pytest.approx(1800.0, rel=0.1)
    top = h > 0.8 * 1800.0
    walls = (h > 0.25 * 1800.0) & ~top
    assert top.sum() > 2000  # a broad summit (km^2 on this 1 km grid)
    assert walls.sum() < 0.15 * top.sum()  # with sheer sides
    assert np.all(h[points @ centre < np.cos(80e3 / RADIUS)] == 0)


def test_random_cliffs_and_tepuis_stand_inland() -> None:
    from scipy.spatial import KDTree

    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_scarps import (
        CLIFF_BACK,
        CLIFF_COAST_M,
        TEPUI_COAST_M,
        place_cliff,
        tepui_group,
    )
    from map_maker.terrain.pipeline.wonder_geometry import path_normals

    mesh = build_mesh(60_000, RADIUS, 14)
    land = mesh.xyz[:, 2] > -0.3
    coast = coast_distance(mesh, land)
    # Ground rising towards +x: the cliff's high side faces up that slope.
    ground = np.where(land, 1500.0 + 1000.0 * mesh.xyz[:, 0], 0.0)
    cliffs = place_cliff(mesh, land, coast, ground, np.random.default_rng(3))
    assert len(cliffs) == 1
    axis, height = cliffs.paths[0], float(cliffs.height_m[0])
    tree = KDTree(mesh.xyz)
    nodes = tree.query(axis)[1]
    assert np.all(land[nodes] & (coast[nodes] > CLIFF_COAST_M))
    reach = 0.5 * CLIFF_BACK * height / RADIUS
    normals = path_normals(axis)
    high, low = (
        ground[tree.query(np.cos(reach) * axis + sign * np.sin(reach) * normals)[1]].mean()
        for sign in (1, -1)
    )
    assert high > low - 50.0  # never raised on the clearly lower side
    tepuis = tepui_group(mesh, land, coast, np.random.default_rng(3))
    assert len(tepuis) >= 1
    sites = tree.query(tepuis.xyz)[1]
    assert np.all(land[sites] & (coast[sites] > TEPUI_COAST_M))
    apart = np.arccos(np.clip(tepuis.xyz @ tepuis.xyz.T, -1, 1)) * RADIUS
    np.fill_diagonal(apart, np.inf)
    assert np.all(apart > 2 * tepuis.radius_m.min())


def test_a_random_chasm_lies_inland_with_shallower_side_canyons() -> None:
    from scipy.spatial import KDTree

    from map_maker.terrain.pipeline.planet_forcing import coast_distance
    from map_maker.terrain.pipeline.planet_mesh import build_mesh
    from map_maker.terrain.pipeline.planet_wonders import (
        CHASM_DEPTH_M,
        CHASM_LENGTH_M,
        CHASM_MIN_DEPTH_M,
        CHASM_WIDTH_M,
        place_chasm,
    )
    from map_maker.terrain.pipeline.wonder_geometry import FLOOR_M, footprint

    mesh = build_mesh(60_000, RADIUS, 14)
    land = mesh.xyz[:, 2] > -0.3
    coast = coast_distance(mesh, land)
    ground = np.where(land, 1500.0 + 1000.0 * mesh.xyz[:, 0], 0.0)
    chasms = place_chasm(mesh, land, coast, ground, np.random.default_rng(3))
    assert len(chasms) >= 4  # the chasm and its side canyons
    axis, depth = chasms.paths[0], chasms.depth_m[0]
    nodes = KDTree(mesh.xyz).query(axis)[1]
    assert np.all(land[nodes] & (coast[nodes] > 2 * CHASM_WIDTH_M))
    length = np.arccos(np.clip(axis[0] @ axis[-1], -1, 1)) * RADIUS
    assert CHASM_LENGTH_M[0] <= length <= CHASM_LENGTH_M[1]
    assert depth.mean() >= CHASM_MIN_DEPTH_M and depth.max() <= CHASM_DEPTH_M
    # The floor stays above the sea where the ground is low.
    assert np.all(ground[nodes] - depth > 0.9 * FLOOR_M)
    assert np.all(chasms.width_m[1:] < chasms.width_m[0])
    assert all(d.max() < depth.max() for d in chasms.depth_m[1:])
    # Kept off other landmarks.
    away = place_chasm(
        mesh, land, coast, ground, np.random.default_rng(3),
        footprint(mesh, axis[len(axis) // 2][None], np.array([600e3])),
    )
    gap = np.arccos(np.clip(away.paths[0] @ axis[len(axis) // 2], -1, 1)) * RADIUS
    assert gap.min() > 600e3


def test_a_shattered_volcano_opens_towards_its_breach_over_a_debris_field() -> None:
    from map_maker.terrain.pipeline.planet_volcanism import (
        breach_azimuth,
        edifice_height,
        shattered_volcano,
    )
    from map_maker.terrain.pipeline.wonder_geometry import destination

    site = np.array([1.0, 0.0, 0.0])
    volcano = shattered_volcano(site, 35e3, np.random.default_rng(4))
    breach = float(breach_azimuth(site[None])[0])

    def at(azimuth: float, radii: float) -> float:
        point = destination(site, azimuth, radii * 35e3 / RADIUS)
        return float(edifice_height(point[None], RADIUS, volcano)[0])

    # The amphitheatre: the flank towards the breach is far lower than opposite.
    assert at(breach, 0.5) < 0.6 * at(breach + np.pi, 0.5)
    # A debris field beyond the base towards the breach, nothing on the far side.
    assert at(breach, 1.6) > 50.0
    assert at(breach + np.pi, 1.6) == 0.0


def test_the_giant_active_volcano_erupts_lava_ash_and_a_glowing_vent() -> None:
    from map_maker.terrain.pipeline.planet_eruptions import erupt, eruption_cover
    from map_maker.terrain.pipeline.planet_volcanism import fire_mountain
    from map_maker.terrain.pipeline.wonder_geometry import destination

    site = np.array([1.0, 0.0, 0.0])
    volcano = fire_mountain(site, None, np.random.default_rng(4))
    assert 6500.0 <= volcano.height_m[0] <= 8500.0 and volcano.active[0]
    radius = float(volcano.radius_m[0])
    # The wind blows towards the east.
    eruptions = erupt(volcano.xyz, volcano.radius_m, np.ones(1), np.zeros(1), RADIUS,
                      np.random.default_rng(4))
    assert len(eruptions.flows) >= 5
    downwind = destination(site, np.pi / 2, 1.2 * radius / RADIUS)
    upwind = destination(site, -np.pi / 2, 1.2 * radius / RADIUS)
    middles = np.stack([flow[len(flow) // 2] for flow in eruptions.flows])
    lava, ash, glow = eruption_cover(
        np.vstack([site, downwind, upwind, middles]), RADIUS, eruptions
    )
    assert glow[0] == pytest.approx(1.0)
    assert ash[1] > 0.5 and ash[2] == 0.0
    assert np.median(lava[3:]) > 0.4


def test_wonder_overlays_paint_lava_black_and_vents_glowing() -> None:
    from map_maker.terrain.adapters.planet_natural import PixelClimate, land_colour
    from map_maker.terrain.pipeline.planet_wonders import WonderCover

    shape = (1, 3)
    points = np.tile([1.0, 0.0, 0.0], (3, 1))

    def fill(value: float) -> np.ndarray:
        return np.full(shape, value)

    climate = PixelClimate(fill(15.0), fill(22.0), fill(900.0), fill(800.0), None)
    overlay = WonderCover(
        np.array([[0.0, 1.0, 0.0]]), np.zeros(shape), np.array([[0.0, 0.0, 1.0]]),
        np.zeros(shape), np.zeros(shape),
    )
    rgb = land_colour(points, RADIUS, climate, fill(200.0), fill(0.0), fill(1.0),
                      overlay=overlay)[0]
    plain, lava, vent = rgb
    assert lava.sum() < 0.5 * plain.sum()  # fresh lava is black
    assert vent[0] > 200 and vent[0] > 2 * vent[2]  # the vent glows orange


def test_an_oasis_greens_the_desert_around_a_spring_pond() -> None:
    from map_maker.terrain.pipeline.planet_waters import Oases, oasis_cover, oasis_relief
    from map_maker.terrain.pipeline.wonder_geometry import destination

    centre = np.array([1.0, 0.0, 0.0])
    oases = Oases(centre[None], np.array([10e3]))
    points = np.stack([destination(centre, 0.3, d / RADIUS) for d in (0.0, 5e3, 30e3)])
    green, pond = oasis_cover(points, RADIUS, oases)
    relief = oasis_relief(points, RADIUS, oases)
    assert pond[0] == pytest.approx(1.0) and green[0] > 0.6
    assert green[2] == 0.0 and pond[2] == 0.0 and relief[2] == 0.0
    assert relief[0] < -10.0  # the spring pond lies in a hollow


def test_a_river_splits_across_a_low_divide_and_reaches_the_sea_twice(
    world_path: Path,
) -> None:
    from map_maker.terrain.pipeline.planet_waters import (
        FORK_INLAND_M,
        FORK_MOUTHS_APART_M,
        find_fork,
        split_river,
    )

    result = generate_planet(open_world(world_path), replace(FAST, climate_passes=0))
    lakes = result.lakes
    found = find_fork(
        result.mesh, result.land, result.coast_m, result.elevation_m, lakes,
        np.random.default_rng(1),
    )
    assert found is not None
    split, branch = found
    receiver = lakes.flow.receiver
    after, forks = split_river(result.mesh, lakes, split, branch, 0.4)
    moved = float(forks.discharge_m3_s[0])
    assert moved == pytest.approx(0.4 * lakes.discharge_m3_s[split])
    below = int(receiver[split])
    assert after.discharge_m3_s[below] == pytest.approx(lakes.discharge_m3_s[below] - moved)
    assert after.discharge_m3_s[branch] == pytest.approx(lakes.discharge_m3_s[branch] + moved)
    assert after.flow.area_m2[branch] > lakes.flow.area_m2[branch]
    # The two courses end in different places.
    def mouth(node: int) -> int:
        while receiver[node] >= 0:
            node = int(receiver[node])
        return node

    assert mouth(below) != mouth(branch)
    # Well inland, and the two courses reach the sea far apart: not a delta.
    assert result.coast_m[split] > FORK_INLAND_M
    apart = np.arccos(np.clip(
        result.mesh.xyz[mouth(below)] @ result.mesh.xyz[mouth(branch)], -1, 1
    )) * RADIUS
    assert apart > FORK_MOUTHS_APART_M


def test_aging_rounds_a_crater_fills_its_floor_and_cuts_gullies() -> None:
    from map_maker.terrain.pipeline.planet_aging import Aging, age_wonder
    from map_maker.terrain.pipeline.planet_wonders import (
        Craters,
        Wonders,
        crater_relief,
        wonder_relief,
    )
    from map_maker.terrain.pipeline.wonder_geometry import destination

    centre = np.array([1.0, 0.0, 0.0])
    craters = Craters(centre[None], np.array([60e3]), np.array([900.0]))
    patch = age_wonder(
        centre, 160e3, RADIUS, lambda p, d: crater_relief(p, RADIUS, craters, d),
        lambda p: np.full(len(p), 1500.0), lambda p: np.full(len(p), 5e-6), None,
        age_myr=20.0, area_exponent=0.45, seed=3, kind="crater", members=(0,),
    )
    fresh = replace(Wonders.empty(), craters=craters)
    aged = replace(fresh, aging=Aging((patch,)))

    def change(points: np.ndarray) -> np.ndarray:
        return wonder_relief(points, RADIUS, aged) - wonder_relief(points, RADIUS, fresh)

    def ring(distance: float, count: int = 24) -> np.ndarray:
        return np.stack([
            destination(centre, a, distance / RADIUS) for a in np.linspace(0, 6.2, count)
        ])

    rim = ring(60e3)
    assert np.median(wonder_relief(rim, RADIUS, aged)) < np.median(
        wonder_relief(rim, RADIUS, fresh)
    ) - 10.0  # the rim wears down
    assert np.median(change(ring(28e3))) > 0.0  # the trough fills
    assert np.all(np.abs(change(ring(158e3))) < 1.0)  # nothing changes beyond the patch
    # Gullies: the outer flank is cut unevenly around the crater.
    assert np.std(change(ring(80e3, 200))) > 2.0


def test_aged_wonders_are_built_saved_and_listed(world_path: Path, tmp_path: Path) -> None:
    from map_maker.terrain.adapters.planet_load import read_planet_parent
    from map_maker.terrain.application.planet import export_planet, generate_planet_run

    run = generate_planet_run(
        open_world(world_path).project, None, replace(FAST, climate_passes=0),
        wonder_settings=WonderSettings(("crater",), 15.0), preview_width=0,
    )
    aging = run.result.wonders.aging
    assert len(aging) == len(run.result.wonders.craters) >= 1
    assert all(patch.age_myr == 15.0 for patch in aging.patches)
    loaded = read_planet_parent(export_planet(run, tmp_path / "planet", width=128).parent)
    reloaded = loaded.parent.wonders
    assert reloaded is not None and len(reloaded.aging) == len(aging)
    first, again = aging.patches[0], reloaded.aging.patches[0]
    assert np.allclose(again.relief_m, first.relief_m, atol=0.01)
    assert (again.kind, again.members) == (first.kind, first.members) == ("crater", (0,))


def test_crater_rims_are_scalloped_rather_than_circular() -> None:
    from map_maker.terrain.pipeline.planet_wonders import Craters, crater_relief
    from map_maker.terrain.pipeline.wonder_geometry import destination

    centre = np.array([1.0, 0.0, 0.0])
    craters = Craters(centre[None], np.array([100e3]), np.array([1000.0]))
    azimuths = np.linspace(0, 2 * np.pi, 90, endpoint=False)
    distances = np.linspace(60e3, 140e3, 161)
    points = np.stack([
        destination(centre, a, d / RADIUS) for a in azimuths for d in distances
    ])
    h = crater_relief(points, RADIUS, craters).reshape(len(azimuths), -1)
    rim = distances[np.argmax(h, axis=1)]  # the rim crest along each azimuth
    assert np.std(rim) > 3e3  # it wanders by kilometres around the crater


def test_waterfalls_mark_rivers_only_where_they_drop_over_steep_ground() -> None:
    from map_maker.terrain.adapters.planet_natural import paint_falls

    rivers = np.zeros((20, 20))
    rivers[10, :] = 1.0
    slope = np.full((20, 20), 0.02)
    slope[:, 12:14] = 0.8  # a cliff across the river
    rgb = np.full((20, 20, 3), 80.0)
    painted = paint_falls(rgb, rivers, slope, 0.2)
    assert painted[10, 12:14].mean() > 150  # white spray at the fall
    assert np.allclose(painted[10, :8], 80.0)  # the river elsewhere is untouched
    assert np.allclose(painted[2, 12:14], 80.0)  # and so is the cliff away from it


def test_the_map_hover_names_wonders() -> None:
    from map_maker.terrain.pipeline.planet_waters import Oases
    from map_maker.terrain.pipeline.planet_wonders import Craters, Wonders, wonder_at
    from map_maker.terrain.pipeline.wonder_geometry import destination

    centre = np.array([1.0, 0.0, 0.0])
    wonders = replace(
        Wonders.empty(),
        craters=Craters(centre[None], np.array([100e3]), np.array([1000.0])),
        oases=Oases(np.array([[0.0, 1.0, 0.0]]), np.array([10e3])),
    )
    assert wonder_at(destination(centre, 1.0, 50e3 / RADIUS), RADIUS, wonders) == "Impact crater"
    assert wonder_at(np.array([0.0, 1.0, 0.0]), RADIUS, wonders) == "Oasis"
    assert wonder_at(np.array([0.0, 0.0, 1.0]), RADIUS, wonders) is None


def test_wonders_are_a_pass_on_the_base_planet(world_path: Path) -> None:
    from map_maker.terrain.application.planet import (
        apply_wonders,
        base_identity,
        generate_planet_run,
        planet_identity,
    )
    from map_maker.terrain.pipeline.planet import finish_planet

    project = open_world(world_path).project
    settings = replace(FAST, climate_passes=0)
    run = generate_planet_run(
        project, None, settings, wonder_settings=WonderSettings(("crater", "chasm")),
        preview_width=0,
    )
    base, result = run.base.planet, run.result
    # The base planet has no wonders; the planet adds them on top of it.
    assert len(base.wonders) == 0 and not np.any(base.wonder_m) and not np.any(base.crater_floor_m)
    assert len(result.wonders.craters) >= 1 and len(result.wonders.chasms) >= 1
    assert np.any(result.crater_floor_m != 0) and np.any(result.wonder_m < 0)
    assert np.array_equal(result.forcing.erodibility, base.forcing.erodibility)
    # Without wonders the pass gives the base planet back.
    kept = base.elevation_m.copy()
    plain = finish_planet(run.base)
    assert np.array_equal(plain.elevation_m, kept) and np.array_equal(base.elevation_m, kept)
    # The same pass again gives the same planet, as one generation would.
    again = generate_planet(
        open_world(world_path), settings, wonder_settings=WonderSettings(("crater", "chasm"))
    )
    assert np.array_equal(again.elevation_m, result.elevation_m)
    # Identities: the base outlasts wonder changes; the planet's does not.
    assert run.base_sha256 == base_identity(project, None, settings, run.runtime)
    other = apply_wonders(run, WonderSettings(("tepui",)), None, preview_width=0)
    assert other.base_sha256 == run.base_sha256 and other.base is run.base
    assert planet_identity(other) != planet_identity(run)
    assert len(other.result.wonders.tepuis) >= 1 and len(other.result.wonders.craters) == 0


def test_placed_wonders_replace_random_ones_and_keep_their_own_shapes(world_path: Path) -> None:
    from map_maker.terrain.domain.world_wonders import WorldWonder, WorldWonders
    from map_maker.terrain.pipeline.planet import finish_planet, generate_base
    from map_maker.terrain.pipeline.planet_volcanism import SHATTERED, STRATO, TITAN, WONDER

    world = open_world(world_path)
    base = generate_base(world, replace(FAST, climate_passes=0), sample_recipe(world_path))
    plain = base.planet
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

    # A chasm between two inland sites 300-600 km apart, away from both.
    reach = np.arccos(np.clip(plain.mesh.xyz @ plain.mesh.xyz[far], -1, 1)) * RADIUS
    rift = next(
        int(k) for k in inland
        if reach[k] > 900e3 and plain.mesh.xyz[k] @ plain.mesh.xyz[first] < np.cos(900e3 / RADIUS)
    )
    span = np.arccos(np.clip(plain.mesh.xyz @ plain.mesh.xyz[rift], -1, 1)) * RADIUS
    rift_end = next(int(k) for k in inland if 300e3 < span[k] < 600e3)
    # A cliff and a tepui near the crater; hand-placed wonders may overlap.
    scarp_end = next(int(k) for k in inland if 300e3 < reach[k] < 700e3)
    mesa = next(int(k) for k in inland if 200e3 < reach[k] < 600e3 and k != scarp_end)
    blast = next(int(k) for k in inland if 700e3 < reach[k] < 1100e3)
    the_rift = WorldWonder(
        "wonder-rift", "The Rift", "chasm", source(rift), 5, 40.0, source(rift_end)
    )
    placed = WorldWonders(world.project, (
        WorldWonder("wonder-sky", "Skyfather", "titan", source(first), 1, 400.0),
        WorldWonder("wonder-eye", "The Eye", "crater", source(far), 2, 200.0),
        the_rift,
        WorldWonder("wonder-wall", "The Wall", "cliff", source(far), 3, 1.5, source(scarp_end)),
        WorldWonder("wonder-mesa", "High Table", "tepui", source(mesa), 4, 80.0),
        WorldWonder("wonder-blast", "The Ruin", "shattered", source(blast), 6, 60.0),
        WorldWonder("wonder-fire", "Firemount", "active", source(rift_end), 7, 120.0),
    ))
    # Random craters and titans are asked for too; the placed ones replace them.
    result = finish_planet(base, WonderSettings(("titan", "crater")), placed)
    titans = result.volcanoes.subset(result.volcanoes.setting == TITAN)
    assert len(titans) == 1
    assert titans.xyz[0] @ plain.mesh.xyz[first] > np.cos(0.5 * plain.mesh.spacing_m / RADIUS)
    assert titans.radius_m[0] == pytest.approx(200e3)
    craters = result.wonders.craters
    assert len(craters) == 1
    assert craters.xyz[0] @ plain.mesh.xyz[far] > np.cos(0.5 * plain.mesh.spacing_m / RADIUS)
    assert craters.radius_m[0] == pytest.approx(100e3)
    chasms = result.wonders.chasms
    assert len(chasms) >= 4 and chasms.width_m[0] == pytest.approx(40e3)
    near = np.cos(0.5 * plain.mesh.spacing_m / RADIUS)
    assert chasms.paths[0][0] @ plain.mesh.xyz[rift] > near
    assert chasms.paths[0][-1] @ plain.mesh.xyz[rift_end] > near
    cliffs, tepuis = result.wonders.cliffs, result.wonders.tepuis
    assert len(cliffs) == 1 and cliffs.height_m[0] == pytest.approx(1500.0)
    assert cliffs.paths[0][0] @ plain.mesh.xyz[far] > near
    assert len(tepuis) == 1 and tepuis.radius_m[0] == pytest.approx(40e3)
    wonder = result.volcanoes.subset(result.volcanoes.setting == WONDER)
    assert sorted(wonder.kind.tolist()) == [STRATO, SHATTERED]
    assert wonder.radius_m[wonder.kind == SHATTERED][0] == pytest.approx(30e3)
    assert wonder.active[wonder.kind == STRATO].all()
    assert len(result.wonders.eruptions) == 1 and len(result.wonders.eruptions.flows) >= 5
    assert np.any(result.wonder_m != 0)
    assert result.placed == placed
    # Each wonder draws its shape from its own seed: another chasm placed before
    # it changes nothing, and a new seed gives it a new shape.
    gorge = WorldWonder("wonder-gorge", "The Gorge", "chasm", source(far), 8, 30.0,
                        source(scarp_end))
    alone = finish_planet(base, wonders=WorldWonders(world.project, (the_rift,))).wonders.chasms
    pair = finish_planet(
        base, wonders=WorldWonders(world.project, (gorge, the_rift))
    ).wonders.chasms
    start = next(i for i, path in enumerate(pair.paths) if path[0] @ alone.paths[0][0] > 1 - 1e-12)
    assert start > 0
    for a, b in zip(pair.paths[start:], alone.paths, strict=True):
        assert np.array_equal(a, b)
    reseeded = finish_planet(
        base, wonders=WorldWonders(world.project, (replace(the_rift, seed=9),))
    ).wonders.chasms
    assert not np.array_equal(reseeded.paths[0], alone.paths[0])
    # A wonder in the sea is reported, not moved.
    sea = int(np.argmax(np.where(plain.land, -1.0, -plain.elevation_m)))
    shore = int(np.argmin(np.where(plain.land, np.inf, span)))
    for wet in (
        WorldWonder("wonder-wet", "Wet", "crater", source(sea), 1),
        WorldWonder("wonder-wet", "Wet", "chasm", source(rift), 1, None, source(shore)),
        WorldWonder("wonder-wet", "Wet", "cliff", source(rift), 1, None, source(shore)),
        WorldWonder("wonder-wet", "Wet", "tepui", source(sea), 1),
        WorldWonder("wonder-wet", "Wet", "active", source(sea), 1),
        WorldWonder("wonder-wet", "Wet", "oasis", source(sea), 1),
    ):
        with pytest.raises(ValueError, match=r"Wet.*sea"):
            finish_planet(base, wonders=WorldWonders(world.project, (wet,)))
    # A splitting river must be placed near a large river.
    dry = WorldWonders(world.project, (WorldWonder("wonder-dry", "Dry", "fork", source(sea), 1),))
    with pytest.raises(ValueError, match=r"Dry: no large river"):
        finish_planet(base, wonders=dry)
    # Where one fits, it sends the share of water it is given down the other basin.
    from map_maker.terrain.pipeline.planet_waters import find_fork

    found = find_fork(
        plain.mesh, plain.land, plain.coast_m, plain.elevation_m, plain.lakes,
        np.random.default_rng(1),
    )
    assert found is not None
    fork = WorldWonder("wonder-fork", "Two Ways", "fork", source(found[0]), 9,
                       options=(("share_pct", 40.0),))
    forks = finish_planet(base, wonders=WorldWonders(world.project, (fork,))).wonders.forks
    split = int(np.argmax(plain.mesh.xyz @ forks.split_xyz[0]))
    assert forks.discharge_m3_s[0] == pytest.approx(0.4 * plain.lakes.discharge_m3_s[split])


def test_volcanic_islands_are_off_by_default(world_path: Path) -> None:
    result = generate_planet(open_world(world_path), replace(FAST, climate_passes=0))
    assert not result.settings.volcanic_islands
    assert not result.volcanoes.emergent.any() and not result.islands.any()
