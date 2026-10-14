# pyright: reportUnknownMemberType=false
"""Public controls for geographic context consumption, ownership and portable replay."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from map_maker.cli import main
from map_maker.terrain.adapters.build import runtime_identity
from map_maker.terrain.adapters.parent import load_terrain_parent
from map_maker.terrain.adapters.project import (
    load_terrain_project,
    project_snapshot_from_json,
    project_snapshot_to_json,
)
from map_maker.terrain.adapters.terrain_context import context_from_json, context_to_json
from map_maker.terrain.adapters.world_context_sampling import (
    bind_world_context,
    sample_geographic_context,
)
from map_maker.terrain.adapters.world_project import write_world_project
from map_maker.terrain.adapters.world_projection import project_landmass
from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.application.build import build_terrain_project
from map_maker.terrain.application.world import propose_group_assignments
from map_maker.terrain.application.world_context import (
    WorldContextRun,
    export_context,
    generate_context,
)
from map_maker.terrain.application.world_terrain import create_world_terrain_project
from map_maker.terrain.domain import ElevationPoint, TerrainProject, TerrainSettings
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.domain.terrain_context import TerrainWorldContext
from map_maker.terrain.domain.world import WorldFrame, WorldProject
from map_maker.terrain.domain.world_context import WorldContextSettings
from map_maker.terrain.domain.world_terrain import WorldTerrainSource
from map_maker.terrain.pipeline.generate import generate_terrain, prepare_terrain_field
from map_maker.terrain.pipeline.parent import prepare_verified_parent
from map_maker.terrain.pipeline.regional import prepare_regional_sampler, sampling_source_id
from map_maker.terrain.pipeline.terrain_context import PreparedWorldContext, context_arrays
from map_maker.terrain.pipeline.world_landmass import select_landmass

ROOT = Path(__file__).parents[1]
type Control = tuple[WorldContextRun, WorldTerrainSource, TerrainWorldContext]


def make_world(body: str, meridian: float = 0) -> WorldProject:
    source = parse_world_svg(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 180">'
        + body + '</svg>', 'public-context-control.svg',
    )
    continents, assignments = propose_group_assignments(source)
    return WorldProject('Public context control', source,
                        WorldFrame((0, 0, 360, 180), 1000, meridian), continents, assignments)


@pytest.fixture(scope="module")
def control() -> tuple[WorldContextRun, WorldTerrainSource, TerrainWorldContext]:
    world = make_world('<g id="A"><path d="M110 60 H250 V120 H110 Z"/></g>')
    run = generate_context(world, WorldContextSettings(72))
    source = project_landmass(run.context.world,
                             select_landmass(run.context.world, world.continents[0].id))
    return run, source, bind_world_context(source, run.context, run.runtime)


def test_geographic_intervals_bound_analytic_parallel_shore(control: Control) -> None:
    run, _source, bound = control
    lon, lat = np.array([-10., 0, 10]), np.array([-10., 0, 10])
    samples = sample_geographic_context(run.context, lon, lat)
    exact = np.radians(30-np.abs(lat))*1000
    assert np.all(samples["shore_lower_km"] <= exact)
    assert np.all(exact <= samples["shore_upper_km"])
    # The projected centre is geographically (0, 0), even on a down-positive grid.
    a, b, c, d = bound.grid.extent_km
    lower, upper = PreparedWorldContext(bound).shore_bounds(
        np.array([(a+c)/2]), np.array([(b+d)/2]),
    )
    assert lower[0] <= np.radians(30)*1000 <= upper[0]
    assert np.max(samples["shore_upper_km"]-samples["shore_lower_km"]) > (
        bound.source_shore_error_km
    )


def test_periodic_queries_and_central_meridian_are_consistent(control: Control) -> None:
    run, _source, _bound = control
    context = run.context
    lon, lat = np.array([-179.9, 180.1]), np.array([0., 0.])
    samples = sample_geographic_context(context, lon, lat)
    for field in samples.values():
        np.testing.assert_allclose(field[..., 0], field[..., 1], atol=1e-10)
    shifted_project = replace(context.world.project,
                              frame=replace(context.grid.frame, central_meridian_deg=37))
    shifted = generate_context(shifted_project, context.grid.settings)
    before = sample_geographic_context(context, np.array([0.]), np.array([10.]))
    after = sample_geographic_context(shifted.context, np.array([37.]), np.array([10.]))
    np.testing.assert_allclose(before["shore_upper_km"], after["shore_upper_km"], atol=1e-9)
    with pytest.raises(ValueError, match="polar"):
        sample_geographic_context(context, np.array([0.]), np.array([90.]))


def test_context_changes_relief_preserves_masks_and_hard_heights(control: Control) -> None:
    _run, source, bound = control
    settings = TerrainSettings(seed=42, resolution_px=65, object_scale_km=source.object_scale_km,
                               coastal_rise_km=400)
    off = generate_terrain(source.coastline, settings)
    on = generate_terrain(source.coastline, settings, world_context=bound)
    np.testing.assert_array_equal(on.land_mask, off.land_mask)
    assert np.isfinite(on.elevation_m[on.land_mask]).all()
    assert np.nanmax(np.abs(on.elevation_m-off.elevation_m)) > 10
    field = prepare_terrain_field(source.coastline, settings,
                                  (ElevationPoint((.5, .5), 1234, 25),), None,
                                  world_context=bound)
    centre = field.sample_ground(np.array([field.width_km/2]), np.array([field.height_km/2]))
    assert centre[0] == pytest.approx(1234, abs=.01)
    # Sample original projected vector vertices, not coarse context coast cells.
    points = np.asarray(source.coastline.points)
    x, y = (points[:, 0]-source.coastline.bounds[0])/1000, (
        points[:, 1]-source.coastline.bounds[1])/1000
    coast, mask = field.evaluate(x, y)
    assert np.max(np.abs(coast[mask])) < .001
    with pytest.raises(ValueError, match=r"frame|scale"):
        replace(TerrainProject(source.coastline, settings, world_context=bound),
                settings=replace(settings, object_scale_km=settings.object_scale_km*2))


def test_continent_split_cannot_change_context_or_terrain(control: Control) -> None:
    run, source, bound = control
    split = make_world('<g id="A"><path d="M110 60 H180 V120 H110 Z"/></g>'
                       '<g id="B"><path d="M180 60 H250 V120 H180 Z"/></g>')
    other = generate_context(split, run.context.grid.settings)
    other_source = project_landmass(other.context.world,
                                   select_landmass(other.context.world, split.continents[0].id))
    other_bound = bind_world_context(other_source, other.context, other.runtime)
    assert source.coastline == other_source.coastline
    assert bound.world_sha256 != other_bound.world_sha256
    np.testing.assert_array_equal(run.context.shore_distance_km, other.context.shore_distance_km)
    np.testing.assert_array_equal(context_arrays(bound)["shore_upper_km"],
                                  context_arrays(other_bound)["shore_upper_km"])
    settings = TerrainSettings(resolution_px=65, object_scale_km=source.object_scale_km,
                               coastal_rise_km=400)
    first = generate_terrain(source.coastline, settings, world_context=bound)
    second = generate_terrain(other_source.coastline, settings, world_context=other_bound)
    np.testing.assert_array_equal(first.elevation_m, second.elevation_m)


def test_payload_rejects_tampering_and_oversized_grid(control: Control) -> None:
    _run, _source, bound = control
    data = json.loads(json.dumps(context_to_json(bound)))
    decoded = context_from_json(data)
    assert decoded == bound
    assert decoded is not None
    assert not any(a.flags.writeable for a in context_arrays(decoded).values())
    data["source_shore_error_km"] += 1
    with pytest.raises(ValueError, match="identity"):
        context_from_json(data)
    data["grid"]["width"] = 100_000
    with pytest.raises(ValueError, match="sample budget"):
        context_from_json(data)


def test_mismatched_world_rejected_before_creating_files(control: Control, tmp_path: Path) -> None:
    run, source, _bound = control
    world = replace(source.world, frame=replace(source.world.frame, radius_km=2000))
    target = tmp_path / "bad"
    with pytest.raises(ValueError, match="same world"):
        create_world_terrain_project(world, world.continents[0].id, target, context=run)
    assert not target.exists()


def test_project_cli_build_and_parent_replay_are_self_contained(
    control: Control, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    run, source, bound = control
    world_file = tmp_path / "input.world.json"
    write_world_project(source.world, world_file)
    context_file = export_context(run, tmp_path / "context")
    target = tmp_path / "terrain"
    assert main(["world", "terrain", str(world_file), "--continent", "A", "--context",
                 str(context_file), "--output", str(target), "--resolution", "65"]) == 0
    assert "context" in capsys.readouterr().out.lower()
    path = target / "terrain.terrain.json"
    loaded = load_terrain_project(path)
    assert loaded.project.world_context == bound
    snapshot = json.loads(json.dumps(project_snapshot_to_json(loaded.project)))
    assert project_snapshot_from_json(snapshot) == loaded.project
    manifest = build_terrain_project(path, tmp_path / "build")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    report = document["world_context"]
    assert report["consumed"] == ["shore_upper_km", "metric_projection", "source_identity"]
    assert {"climate", "runoff", "aging"} <= set(report["unsupported"])
    schemas: list[dict[str, Any]] = [json.loads(p.read_text(encoding="utf-8"))
                                    for p in (ROOT / "schemas").rglob("*.schema.json")]
    registry = Registry[Any]().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas
    )
    for value, identity in (
        (json.loads(path.read_text(encoding="utf-8")), "terrain-project:9"),
        (snapshot, "terrain-input-snapshot:4"), (document, "terrain-build:20"),
    ):
        schema = next(s for s in schemas if s["$id"] == f"urn:map-maker:schema:{identity}")
        Draft202012Validator(schema, registry=registry).validate(value)
    # A completed parent must replay without the original world, context or project folder.
    world_file.rename(tmp_path / "world-moved.json")
    context_file.parent.rename(tmp_path / "context-moved")
    target.rename(tmp_path / "terrain-moved")
    parent = load_terrain_parent(manifest.parent, runtime_identity())
    assert parent.data.project.world_context == bound
    prepared = prepare_verified_parent(parent.data)
    assert prepared.verified_ground_nodes == parent.data.elevation_m.size
    assert prepared.sampler.prepared_field.world_context is not None


def test_regional_samples_share_context_and_identity(control: Control) -> None:
    _run, source, bound = control
    settings = TerrainSettings(resolution_px=65, object_scale_km=source.object_scale_km,
                               coastal_rise_km=400)
    sampler = prepare_regional_sampler(source.coastline, settings, world_context=bound)
    assert sampler.source_id != sampling_source_id(source.coastline, settings)
    grid = sampler.reference_grid
    whole = sampler.sample(RegionalSamplingRequest(sampler.source_id, grid, 1,
                                                    (0, 0, grid.width-1, grid.height-1)))
    window = sampler.sample(RegionalSamplingRequest(sampler.source_id, grid, 1, (10, 5, 20, 15)))
    np.testing.assert_array_equal(whole.elevation_m[4:17, 9:22], window.elevation_m)
    repeat = prepare_regional_sampler(source.coastline, settings, world_context=bound)
    again = repeat.sample(window.request)
    np.testing.assert_array_equal(window.elevation_m, again.elevation_m)


def test_distance_bounds_are_continuous_across_both_sampling_stencils(control: Control) -> None:
    run, _source, bound = control
    grid = bound.grid
    x, y = np.meshgrid(np.arange(1, grid.width-1, dtype=np.float64)*grid.x_spacing_km,
                       (np.arange(grid.height-1, dtype=np.float64)+.5)*grid.y_spacing_km)
    sampler = PreparedWorldContext(bound)
    for a, b in zip(sampler.shore_bounds(x-1e-6, y), sampler.shore_bounds(x+1e-6, y),
                    strict=True):
        assert np.max(np.abs(a-b)) < 1e-4
    x, y = np.meshgrid((np.arange(grid.width-1, dtype=np.float64)+.5)*grid.x_spacing_km,
                       np.arange(1, grid.height-1, dtype=np.float64)*grid.y_spacing_km)
    for a, b in zip(sampler.shore_bounds(x, y-1e-6), sampler.shore_bounds(x, y+1e-6),
                    strict=True):
        assert np.max(np.abs(a-b)) < 1e-4
    # Geographic stencils change at source cell centres (not at cell edges).
    lon = np.array([run.context.grid.longitude_deg(c) for c in range(144)])
    lat = np.full(lon.shape, 10.)
    left = sample_geographic_context(run.context, lon-1e-8, lat)
    right = sample_geographic_context(run.context, lon+1e-8, lat)
    for name in ("shore_lower_km", "shore_upper_km"):
        assert np.max(np.abs(left[name]-right[name])) < 1e-4


def test_matching_geology_is_bound_and_mismatched_geology_rejected(
    control: Control, tmp_path: Path,
) -> None:
    from map_maker.terrain.adapters.world_geology import read_geology, write_geology
    from map_maker.terrain.domain.world_geology import blank_geology

    run, source, _bound = control
    recipe = blank_geology(source.world)
    path = tmp_path / "recipe.geology.json"
    digest = write_geology(recipe, path, None)
    created = create_world_terrain_project(source.world, source.world.continents[0].id,
                                           tmp_path / "with-geology", context=run,
                                           geology=read_geology(path)[0])
    assert created.loaded.project.world_context is not None
    assert created.loaded.project.world_context.geology_sha256 is not None
    assert load_terrain_project(created.loaded.path).project == created.loaded.project
    mismatch = replace(source.world, name="A different retained world")
    write_geology(blank_geology(mismatch), path, digest)
    with pytest.raises(ValueError, match="world"):
        create_world_terrain_project(source.world, source.world.continents[0].id,
                                     tmp_path / "bad-geology", context=run,
                                     geology=read_geology(path)[0])
    assert not (tmp_path / "bad-geology").exists()
