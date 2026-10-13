# pyright: reportUnknownMemberType=false
"""Landform transfer preserves physical geography, priority and editable provenance."""

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

from dmtools.cli import main
from dmtools.terrain.adapters.build import canonical_json
from dmtools.terrain.adapters.project import load_terrain_project, save_terrain_project
from dmtools.terrain.adapters.world_geology import (
    geology_document,
    geology_from_bytes,
    read_geology,
    write_geology,
)
from dmtools.terrain.adapters.world_project import write_world_project
from dmtools.terrain.adapters.world_svg import parse_world_svg
from dmtools.terrain.adapters.world_terrain_source import source_document
from dmtools.terrain.application.world import propose_group_assignments
from dmtools.terrain.application.world_terrain import (
    WorldTerrainCreated,
    create_world_terrain_project,
)
from dmtools.terrain.domain import LandformKind, TerrainRegion, TerrainSettings, landform_preset
from dmtools.terrain.domain.world import WorldFrame, WorldProject
from dmtools.terrain.domain.world_geology import (
    GeologyProfile,
    GeologyProvince,
    WorldGeologyRecipe,
    blank_geology,
)
from dmtools.terrain.pipeline.control import CancellationToken, GenerationCancelled
from dmtools.terrain.pipeline.generate import generate_terrain

ROOT = Path(__file__).parents[1]
SETTINGS = TerrainSettings(seed=42, resolution_px=65, coastal_rise_km=5)
OUTLINE = ((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.))


def world(*, split: bool = False, seam: bool = False) -> WorldProject:
    body = (
        '<g id="A"><path d="M0 55 H20 V95 H0 Z"/></g>'
        '<g id="B"><path d="M340 55 H360 V95 H340 Z"/></g>'
        if seam else
        '<g id="A"><path d="M160 55 H180 V95 H160 Z"/></g>'
        '<g id="B"><path d="M180 55 H200 V95 H180 Z"/></g>'
        if split else '<g id="A"><path d="M160 55 H200 V95 H160 Z"/></g>'
    )
    source = parse_world_svg(
        '<svg viewBox="0 0 360 180">' + body + '</svg>', "landforms.svg",
    )
    owners, assignments = propose_group_assignments(source)
    return WorldProject("Landforms", source, WorldFrame((0, 0, 360, 180), 1000),
                        owners, assignments)


def recipe(source: WorldProject, kind: LandformKind = "plain") -> WorldGeologyRecipe:
    controls = landform_preset(kind)
    empty = blank_geology(source)
    return replace(empty, defaults=tuple(
        replace(d, profile=GeologyProfile("stable-interior", 1000. + i, landform=controls))
        for i, d in enumerate(empty.defaults)
    ))


def create(tmp_path: Path, value: WorldGeologyRecipe, name: str = "terrain") -> WorldTerrainCreated:
    path = tmp_path / (name + ".dmgeology.json")
    write_geology(value, path, None)
    return create_world_terrain_project(
        value.world, value.world.continents[0].id, tmp_path / name,
        settings=SETTINGS, geology=read_geology(path)[0],
    )


def regions(created: WorldTerrainCreated) -> tuple[TerrainRegion, ...]:
    return tuple(c for c in created.loaded.project.constraints if isinstance(c, TerrainRegion))


def test_identical_guidance_has_no_administrative_border_or_age_seam(tmp_path: Path) -> None:
    whole = create(tmp_path, recipe(world()), "whole")
    split = create(tmp_path, recipe(world(split=True)), "split")
    assert regions(whole) == regions(split)
    assert len(regions(split)) == 1
    assert split.source.coastline == whole.source.coastline
    assert split.source.projection == whole.source.projection
    first, second = [
        generate_terrain(c.loaded.project.coastline, c.loaded.project.settings,
                         constraints=c.loaded.project.constraints)
        for c in (whole, split)
    ]
    np.testing.assert_array_equal(first.elevation_m, second.elevation_m)
    np.testing.assert_array_equal(first.land_mask, second.land_mask)
    assert 200 < float(first.elevation_m[32, 32]) < 350


def test_landforms_change_relief_but_preserve_coast_mask_and_determinism(tmp_path: Path) -> None:
    plain = create(tmp_path, recipe(world()), "plain")
    plateau = create(tmp_path, recipe(world(), "plateau"), "plateau")
    assert plain.source.coastline == plateau.source.coastline
    outputs = [
        generate_terrain(c.loaded.project.coastline, c.loaded.project.settings,
                         constraints=c.loaded.project.constraints)
        for c in (plain, plateau, plateau)
    ]
    np.testing.assert_array_equal(outputs[0].land_mask, outputs[1].land_mask)
    np.testing.assert_array_equal(outputs[1].elevation_m, outputs[2].elevation_m)
    assert float(outputs[1].elevation_m[24:41, 24:41].mean()) > 2000
    assert float(outputs[0].elevation_m[24:41, 24:41].mean()) < 350
    assert all(np.isfinite(o.elevation_m[o.land_mask]).all() for o in outputs)


def test_priority_enclave_and_blank_override_retain_holes(tmp_path: Path) -> None:
    source = world(split=True)
    base = recipe(source, "mountains")
    plateau = GeologyProvince(
        "province-plateau", "Plateau", ((170, 65), (190, 65), (190, 85), (170, 85)), 5,
        GeologyProfile("stable-interior", landform=landform_preset("plateau")),
    )
    blank = GeologyProvince(
        "province-background", "Background", ((176, 71), (184, 71), (184, 79), (176, 79)),
        10, GeologyProfile(),
    )
    made = create(tmp_path, replace(base, provinces=(plateau, blank)))
    transferred = regions(made)
    assert len(transferred) == 2 and all(len(r.holes) == 1 for r in transferred)
    polygons = [Polygon(r.points, r.holes) for r in transferred]
    assert all(p.is_valid for p in polygons)
    assert polygons[0].intersection(polygons[1]).area < 1e-12
    assert all(not p.covers(Point(.5, .5)) for p in polygons)
    assert .7 < unary_union(polygons).area < 1
    # A blank override retains background generation instead of inheriting the
    # surrounding mountains or averaging them with the plateau.
    assert made.source.geology is not None
    assert made.source.geology.provinces == (blank, plateau)


def test_periodic_guidance_dissolves_the_longitude_seam(tmp_path: Path) -> None:
    made = create(tmp_path, recipe(world(seam=True)))
    assert len(regions(made)) == 1
    polygon = Polygon(regions(made)[0].points)
    assert polygon.contains(Point(.5, .5))
    assert not regions(made)[0].holes
    assert made.source.coastline.component_count == 1


def test_no_landform_means_no_inferred_relief_from_setting_or_age(tmp_path: Path) -> None:
    source = world()
    value = blank_geology(source)
    value = replace(value, defaults=tuple(
        replace(d, profile=GeologyProfile("active-belt", 1000, 2, 20)) for d in value.defaults
    ))
    made = create(tmp_path, value)
    assert not regions(made)
    assert made.source.geology == value


def test_recipe_snapshot_survives_relocation_and_later_region_edits(tmp_path: Path) -> None:
    value = recipe(world())
    made = create(tmp_path, value)
    old = regions(made)[0]
    edited = replace(
        made.loaded.project, constraints=(replace(old, settings=landform_preset("hills")),),
    )
    save_terrain_project(edited, made.loaded.coastline_source, made.loaded.path)
    target = tmp_path / "moved"
    shutil.move(str(made.loaded.path.parent), target)
    (tmp_path / "terrain.dmgeology.json").unlink()
    loaded = load_terrain_project(target / "terrain.dmterrain.json")
    assert loaded.project == edited
    assert loaded.coastline_source.world_terrain is not None
    assert loaded.coastline_source.world_terrain.geology == value


@pytest.mark.parametrize("reason", ["wrong-world", "height", "cancel"])
def test_invalid_or_cancelled_transfer_never_publishes(tmp_path: Path, reason: str) -> None:
    source = world()
    value = recipe(source)
    if reason == "wrong-world":
        value = recipe(replace(source, name="Different world"))
    elif reason == "height":
        value = replace(value, defaults=tuple(replace(d, profile=replace(
            d.profile, landform=replace(landform_preset("plateau"), elevation_m=99999),
        )) for d in value.defaults))
    path = tmp_path / "recipe.dmgeology.json"
    write_geology(value, path, None)
    token = CancellationToken()

    def progress(fraction: float, _label: str) -> None:
        if reason == "cancel" and fraction >= .65:
            token.cancel()

    with pytest.raises((ValueError, GenerationCancelled)):
        create_world_terrain_project(
            source, source.continents[0].id, tmp_path / "terrain", settings=SETTINGS,
            geology=read_geology(path)[0], cancellation=token, progress=progress,
        )
    assert not (tmp_path / "terrain").exists()


def test_geology_and_prepared_metadata_match_current_schemas(tmp_path: Path) -> None:
    value = recipe(world())
    assert geology_from_bytes(canonical_json(geology_document(value))) == value
    made = create(tmp_path, value)
    schemas = [
        json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "schemas").rglob("*.json")
    ]
    registry = Registry[Any]().with_resources(
        (d["$id"], Resource.from_contents(d)) for d in schemas
    )
    for schema_name, document in (
        ("geology-v2.schema.json", geology_document(value)),
        ("terrain-source-v2.schema.json", source_document(made.source)),
    ):
        schema = next(d for d in schemas if d["$id"].endswith(schema_name))
        Draft202012Validator(schema, registry=registry).validate(json.loads(json.dumps(document)))


@pytest.mark.parametrize("field,bad", [
    ("relief_m", True), ("feature_size_km", 0), ("elevation_m", -1),
    ("orientation_deg", 180), ("transition_km", "10"), ("character", "desert"),
])
def test_landform_input_is_strict(field: str, bad: object) -> None:
    document = json.loads(canonical_json(geology_document(recipe(world()))))
    document["defaults"][0]["profile"]["landform"][field] = bad
    with pytest.raises(ValueError):
        geology_from_bytes(canonical_json(document))


def test_cli_applies_explicit_recipe(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = world()
    value = recipe(source, "mountains")
    project, guidance = tmp_path / "world.dmworld.json", tmp_path / "world.dmgeology.json"
    write_world_project(source, project)
    write_geology(value, guidance, None)
    assert main(["world", "terrain", str(project), "--continent", "A",
                 "--geology", str(guidance), "--output", str(tmp_path / "terrain")]) == 0
    assert "Landform regions: 1" in capsys.readouterr().out
    loaded = load_terrain_project(tmp_path / "terrain/terrain.dmterrain.json")
    assert isinstance(loaded.project.constraints[0], TerrainRegion)
    assert loaded.project.constraints[0].settings.character == "mountains"


def test_reordered_world_records_reuse_the_same_canonical_recipe(tmp_path: Path) -> None:
    source = world(split=True)
    value = recipe(source)
    path = tmp_path / "recipe.dmgeology.json"
    write_geology(value, path, None)
    reordered = replace(source, continents=tuple(reversed(source.continents)),
                        assignments=tuple(reversed(source.assignments)))
    made = create_world_terrain_project(
        reordered, source.continents[0].id, tmp_path / "terrain", geology=read_geology(path)[0],
    )
    assert len(regions(made)) == 1
