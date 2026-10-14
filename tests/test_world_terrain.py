# pyright: reportUnknownMemberType=false
"""Physical world land to ordinary local terrain, without coastline repair."""

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from map_maker.cli import main
from map_maker.terrain.adapters.project import load_terrain_project, save_terrain_project
from map_maker.terrain.adapters.svg import load_svg_coastline_source
from map_maker.terrain.adapters.world_project import write_world_project
from map_maker.terrain.adapters.world_projection import project_landmass
from map_maker.terrain.adapters.world_svg import parse_world_svg
from map_maker.terrain.adapters.world_terrain_source import source_document, source_svg
from map_maker.terrain.application.build import build_terrain_project
from map_maker.terrain.application.world import propose_group_assignments
from map_maker.terrain.application.world_terrain import create_world_terrain_project
from map_maker.terrain.domain import TerrainSettings
from map_maker.terrain.domain.world import WorldFrame, WorldProject
from map_maker.terrain.pipeline.control import CancellationToken, GenerationCancelled
from map_maker.terrain.pipeline.generate import generate_terrain
from map_maker.terrain.pipeline.world import prepare_world_map
from map_maker.terrain.pipeline.world_landmass import select_landmass

ROOT = Path(__file__).parents[1]


def make_world(body: str) -> WorldProject:
    source = parse_world_svg(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 180">'
        + body + '</svg>', "test.svg",
    )
    continents, assignments = propose_group_assignments(source)
    return WorldProject("Test world", source, WorldFrame((0, 0, 360, 180), 1000),
                        continents, assignments)


def compact_world() -> WorldProject:
    return make_world(
        '<g id="A"><path d="M160 75 H170 V85 H160 Z"/>'
        '<g id="islands"><path d="M162 92 H163 V93 H162 Z"/></g></g>'
        '<g id="B"><path d="M170 75 H180 V85 H170 Z"/>'
        '<g xmlns:affinity="https://www.affinity.studio/" id="offshore" affinity:id="islands">'
        '<path d="M230 100 H231 V101 H230 Z"/></g></g>'
    )


def continent(world: WorldProject, name: str = "A") -> str:
    return next(c.id for c in world.continents if c.name == name)


def test_connected_land_joins_borders_but_not_neighbours_distant_islands() -> None:
    world = compact_world()
    prepared = prepare_world_map(world)
    land = select_landmass(prepared, continent(world))
    assert set(land.continent_ids) == {c.id for c in world.continents}
    assert len(land.components) == 3
    source = project_landmass(prepared, land)
    assert source.coastline.component_count == 2
    assert len(source.feature_ids) == 3
    assert source.world == world


def test_source_roundtrip_retains_tiny_holes_and_gaps(tmp_path: Path) -> None:
    world = make_world(
        '<g id="A"><path fill-rule="evenodd" '
        'd="M160 75 H170 V85 H160 Z M165 80 H165.0001 V80.0001 H165 Z"/>'
        '<path d="M170.00001 75 H180 V85 H170.00001 Z"/></g>'
    )
    created = create_world_terrain_project(world, continent(world), tmp_path / "terrain")
    coast = created.source.coastline
    assert coast.component_count == 2
    assert sum(len(p.holes) for p in coast.components) == 1
    loaded = load_terrain_project(created.loaded.path)
    assert loaded.project == created.loaded.project
    assert loaded.coastline_source.world_terrain == created.source
    assert load_svg_coastline_source(created.loaded.coastline_source.path).coastline == coast
    assert created.loaded.coastline_source.path.read_bytes() == source_svg(created.source)


def test_fixed_metric_scale_and_portable_folder(tmp_path: Path) -> None:
    world = compact_world()
    created = create_world_terrain_project(world, continent(world), tmp_path / "original")
    scale = created.source.object_scale_km
    assert created.loaded.project.settings.object_scale_km == scale
    assert created.loaded.project.settings.resolution_px == 257
    changed = replace(created.loaded.project,
                      settings=replace(created.loaded.project.settings, object_scale_km=scale * 2))
    with pytest.raises(ValueError, match="scale"):
        save_terrain_project(changed, created.loaded.coastline_source, tmp_path / "bad.json")
    moved = tmp_path / "moved"
    shutil.move(str(created.loaded.path.parent), moved)
    loaded = load_terrain_project(moved / "terrain.terrain.json")
    assert loaded.coastline_source.world_terrain == created.source
    assert loaded.project == created.loaded.project
    document = json.loads(loaded.path.read_text())
    document["settings"]["object_scale_km"] *= 2
    loaded.path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="scale"):
        load_terrain_project(loaded.path)


def test_projection_is_deterministic_and_scales_with_planet_radius() -> None:
    world = compact_world()
    prepared = prepare_world_map(world)
    land = select_landmass(prepared, continent(world))
    first = project_landmass(prepared, land)
    assert source_svg(first) == source_svg(project_landmass(prepared, land))
    twice = prepare_world_map(replace(world, frame=replace(world.frame, radius_km=2000)))
    second = project_landmass(twice, select_landmass(twice, continent(world)))
    assert second.object_scale_km == pytest.approx(first.object_scale_km * 2)
    assert first.projection.maximum_transverse_scale < 1.02
    assert np.all(np.isfinite(np.asarray(first.coastline.points)))


def test_periodic_land_is_connected_without_a_seam_coastline() -> None:
    world = make_world(
        '<g id="A"><path d="M0 75 H8 V85 H0 Z"/></g>'
        '<g id="B"><path d="M352 75 H360 V85 H352 Z"/></g>'
    )
    prepared = prepare_world_map(world)
    land = select_landmass(prepared, continent(world))
    assert len(land.continent_ids) == 2
    result = project_landmass(prepared, land)
    assert result.coastline.component_count == 1
    assert abs(result.projection.longitude_deg) > 179
    assert result.object_scale_km < 300
    polygon = Polygon(result.coastline.points)
    assert polygon.contains(Point(0, 0))


def test_polar_land_projects_without_pole_spikes() -> None:
    world = make_world('<g id="A"><path d="M0 0 H360 V20 H0 Z"/></g>')
    prepared = prepare_world_map(world)
    result = project_landmass(prepared, select_landmass(prepared, continent(world)))
    polygons = [Polygon(p.exterior, p.holes) for p in result.coastline.components]
    assert all(p.is_valid for p in polygons)
    assert unary_union(polygons).area > 0
    assert result.projection.maximum_angle_deg < 35


def test_oversized_domain_is_rejected_without_rescaling_or_output(tmp_path: Path) -> None:
    world = make_world('<g id="A"><path d="M10 60 H350 V120 H10 Z"/></g>')
    with pytest.raises(ValueError, match=r"regional|80-degree"):
        create_world_terrain_project(world, continent(world), tmp_path / "terrain")
    assert not (tmp_path / "terrain").exists()


def test_cancellation_does_not_publish_and_existing_output_is_preserved(tmp_path: Path) -> None:
    world = compact_world()
    token = CancellationToken()

    def cancel(fraction: float, _message: str) -> None:
        if fraction >= .95:
            token.cancel()

    target = tmp_path / "terrain"
    with pytest.raises(GenerationCancelled):
        create_world_terrain_project(world, continent(world), target,
                                     cancellation=token, progress=cancel)
    assert (target / "coastline.svg").exists()
    assert not (target / "terrain.terrain.json").exists()
    original = (target / "coastline.svg").read_bytes()
    with pytest.raises(FileExistsError):
        create_world_terrain_project(world, continent(world), target)
    assert (target / "coastline.svg").read_bytes() == original


def test_visible_svg_and_metadata_cannot_silently_disagree(tmp_path: Path) -> None:
    world = compact_world()
    created = create_world_terrain_project(world, continent(world), tmp_path / "terrain")
    path = created.loaded.coastline_source.path
    path.write_bytes(path.read_bytes().replace(b'id="land-0"', b'id="edited"'))
    with pytest.raises(ValueError, match="changed"):
        load_svg_coastline_source(path)


def test_cli_creates_buildable_world_terrain(tmp_path: Path,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    world = compact_world()
    source = tmp_path / "input.world.json"
    write_world_project(world, source)
    target = tmp_path / "terrain"
    assert main(["world", "terrain", str(source), "--continent", "A", "--output", str(target),
                 "--resolution", "65", "--seed", "42"]) == 0
    assert "Terrain project ready" in capsys.readouterr().out
    project = target / "terrain.terrain.json"
    manifest = build_terrain_project(project, tmp_path / "build")
    data = json.loads(manifest.read_text())
    assert data["inputs"]["svg_sha256"] == load_terrain_project(project).coastline_source.sha256
    assert (manifest.parent / "elevation.tif").is_file()
    assert main(["world", "terrain", str(source), "--continent", "missing",
                 "--output", str(tmp_path / "invalid")]) == 1
    assert "Choose one continent" in capsys.readouterr().err


def test_metadata_matches_public_schema(tmp_path: Path) -> None:
    world = compact_world()
    result = create_world_terrain_project(world, continent(world), tmp_path / "terrain")
    schemas = [json.loads((ROOT / "schemas" / path).read_text()) for path in (
        "world/project-v1.schema.json", "world/terrain-source-v2.schema.json",
        "terrain/input-snapshot-v4.schema.json",
    )]
    registry = Registry[Any]().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    Draft202012Validator.check_schema(schemas[1])
    # JSON roundtrip normalizes the dataclass tuple coordinates to arrays.
    document = json.loads(json.dumps(source_document(result.source)))
    Draft202012Validator(schemas[1], registry=registry).validate(document)


@pytest.mark.parametrize("radius", [6000, 60000])
def test_continental_area_roundoff_is_not_reported_as_overlapping_land(
    tmp_path: Path, radius: float,
) -> None:
    paths = "".join(
        f'<path d="M{x} {y} h12.345 v12.345 h-12.345 Z"/>'
        for x in (135.123, 150.123, 165.123, 180.123)
        for y in (45.321, 60.321, 75.321, 90.321, 105.321)
    )
    world = make_world('<g id="A">' + paths + '</g>')
    world = replace(world, frame=replace(world.frame, radius_km=radius))
    created = create_world_terrain_project(world, continent(world), tmp_path / "terrain")
    assert created.source.coastline.component_count == 20
    assert load_terrain_project(created.loaded.path).project == created.loaded.project


def test_internal_continent_border_cannot_move_projection_or_become_coast() -> None:
    whole = make_world('<g id="A"><path d="M160 55 H200 V95 H160 Z"/></g>')
    split = make_world(
        '<g id="A"><path d="M160 55 H180 V95 H160 Z"/></g>'
        '<g id="B"><path d="M180 55 H200 V95 H180 Z"/></g>'
    )
    prepared_whole, prepared_split = prepare_world_map(whole), prepare_world_map(split)
    one = project_landmass(prepared_whole, select_landmass(prepared_whole, continent(whole)))
    two = project_landmass(prepared_split, select_landmass(prepared_split, continent(split)))
    assert one.projection == two.projection
    assert one.coastline == two.coastline
    assert len(two.included_continent_ids) == 2
    # The midpoint of the ownership border is deep inland, not a zero coast.
    assert two.projection.longitude_deg == pytest.approx(0)
    assert two.projection.latitude_deg == pytest.approx(15)
    point = Point(0, 0)
    polygon = Polygon(two.coastline.points)
    assert polygon.contains(point)
    assert polygon.boundary.distance(point) > 200_000
    settings = TerrainSettings(seed=42, resolution_px=65, object_scale_km=one.object_scale_km)
    before = generate_terrain(one.coastline, settings)
    after = generate_terrain(two.coastline, settings)
    np.testing.assert_array_equal(before.land_mask, after.land_mask)
    np.testing.assert_array_equal(before.elevation_m, after.elevation_m)


def test_connected_land_collection_follows_three_continents_transitively() -> None:
    world = make_world(
        '<g id="A"><path d="M160 75 H170 V85 H160 Z"/></g>'
        '<g id="B"><path d="M170 75 H180 V85 H170 Z"/></g>'
        '<g id="C"><path d="M180 75 H190 V85 H180 Z"/></g>'
    )
    prepared = prepare_world_map(world)
    sources = [project_landmass(prepared, select_landmass(prepared, c.id))
               for c in world.continents]
    assert all(len(s.included_continent_ids) == 3 for s in sources)
    assert all(s.coastline.component_count == 1 for s in sources)
    assert all(s.coastline.points == sources[0].coastline.points for s in sources)
    assert all(s.projection == sources[0].projection for s in sources)


def test_a_narrow_strait_is_not_silently_closed_between_continent_owners() -> None:
    world = make_world(
        '<g id="A"><path d="M160 75 H170 V85 H160 Z"/></g>'
        '<g id="B"><path d="M170.00001 75 H180 V85 H170.00001 Z"/></g>'
    )
    prepared = prepare_world_map(world)
    selected = select_landmass(prepared, continent(world))
    assert selected.continent_ids == (continent(world),)
    assert len(selected.components) == 1
