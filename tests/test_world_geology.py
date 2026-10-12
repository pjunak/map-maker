# pyright: reportUnknownMemberType=false
"""Geology identity, exact land partitions and explicit authored time semantics."""

import json
from dataclasses import replace
from math import pi
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from dmtools.cli import main
from dmtools.terrain.adapters import world_geology as files
from dmtools.terrain.adapters.build import canonical_json
from dmtools.terrain.adapters.world_geology_render import render_geology
from dmtools.terrain.adapters.world_svg import parse_world_svg
from dmtools.terrain.application.world_geology import open_geology, save_geology
from dmtools.terrain.domain.world import WorldAssignment, WorldContinent, WorldFrame, WorldProject
from dmtools.terrain.domain.world_geology import (
    GeologyProfile,
    GeologyProvince,
    WorldGeologyRecipe,
    blank_geology,
)
from dmtools.terrain.pipeline.control import CancellationToken, GenerationCancelled
from dmtools.terrain.pipeline.world import WorldMap, prepare_world_map
from dmtools.terrain.pipeline.world_geology import resolve_geology
from dmtools.terrain.viewport import MapViewport

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/world/four-shores.dmgeology.json"


def world(scale: float = 1, offset: float = 0) -> WorldMap:
    source = parse_world_svg(
        f'<svg viewBox="{offset} {offset} {360 * scale} {180 * scale}">'
        f'<g transform="translate({offset},{offset}) scale({scale})">'
        '<path id="west" d="M0 30 H180 V150 H0 Z"/>'
        '<path id="east" d="M180 30 H360 V150 H180 Z"/></g></svg>',
        "bands.svg",
    )
    project = WorldProject(
        "Bands",
        source,
        WorldFrame((offset, offset, offset + 360 * scale, offset + 180 * scale), 1000),
        (WorldContinent("west", "West"), WorldContinent("east", "East")),
        tuple(WorldAssignment(f.id, f.id, "mainland") for f in source.features),
    )
    return prepare_world_map(project)


def province(
    name: str = "belt",
    *,
    priority: int = 0,
    x0: float = 150,
    x1: float = 210,
    y0: float = 60,
    y1: float = 120,
) -> GeologyProvince:
    return GeologyProvince(
        "province-" + name,
        name,
        ((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
        priority,
        GeologyProfile("active-belt", 2500, 12, 2),
    )


@pytest.mark.parametrize("scale,offset", [(1, 0), (0.01, -20), (100, 25000)])
def test_cross_continent_belt_conserves_spherical_area_and_distinct_ages(
    scale: float,
    offset: float,
) -> None:
    source = world(scale, offset)
    belt = province()
    belt = replace(
        belt, vertices=tuple((x * scale + offset, y * scale + offset) for x, y in belt.vertices)
    )
    recipe = replace(blank_geology(source.project), provinces=(belt,))
    result = resolve_geology(source, recipe)
    region = result.regions[0]
    assert region.area_km2 == pytest.approx(1000**2 * pi / 3)
    assert sum(r.area_km2 for r in result.regions) == pytest.approx(source.land_area_km2)
    assert result.at((170 * scale + offset, 90 * scale + offset)) is region
    assert result.at((190 * scale + offset, 90 * scale + offset)) is region
    assert region.profile == GeologyProfile("active-belt", 2500, 12, 2)
    assert result.at((180 * scale + offset, 10 * scale + offset)) is None


def test_higher_priority_replaces_whole_profile_and_ties_fail() -> None:
    source = world()
    recipe = replace(blank_geology(source.project), provinces=(province(), province("young")))
    with pytest.raises(ValueError, match="overlap on land at priority 0"):
        resolve_geology(source, recipe)
    higher = replace(recipe.provinces[1], priority=1, profile=GeologyProfile("rift"))
    result = resolve_geology(source, replace(recipe, provinces=(recipe.provinces[0], higher)))
    assert result.regions[0].name == "young"
    assert result.regions[0].profile.crust_age_ma is None
    assert result.regions[1].area_km2 == 0
    assert (
        resolve_geology(source, replace(recipe, provinces=(higher, recipe.provinces[0]))).regions
        == result.regions
    )


def test_masked_tie_is_allowed_but_removing_higher_override_reveals_conflict() -> None:
    source = world()
    provinces = (province("a"), province("b"), province("mask", priority=2))
    recipe = replace(blank_geology(source.project), provinces=provinces)
    assert resolve_geology(source, recipe).regions[0].name == "mask"
    with pytest.raises(ValueError, match="overlap"):
        resolve_geology(source, replace(recipe, provinces=provinces[:2]))


def test_water_overlap_is_not_a_land_conflict_and_shared_edges_are_allowed() -> None:
    source = world()
    recipe = replace(
        blank_geology(source.project),
        provinces=(
            province("ocean-a", y0=0, y1=20),
            province("ocean-b", y0=0, y1=20),
            province("left", x0=150, x1=180),
            province("right", x0=180, x1=210),
        ),
    )
    result = resolve_geology(source, recipe)
    assert sum(r.area_km2 for r in result.regions if r.province) == pytest.approx(1000**2 * pi / 3)
    assert all(r.area_km2 == 0 for r in result.regions if r.name.startswith("ocean"))
    assert result.at((180, 90)) is result.regions[0]


@pytest.mark.parametrize("x0,x1", [(350, 370), (10, -10)])
def test_longitude_seam_wraps_coverage_without_duplication(x0: float, x1: float) -> None:
    source = world()
    recipe = replace(blank_geology(source.project), provinces=(province(x0=x0, x1=x1),))
    result = resolve_geology(source, recipe)
    assert result.regions[0].area_km2 == pytest.approx(1000**2 * pi / 9)
    assert result.at((355, 90)) is result.regions[0]
    assert result.at((5, 90)) is result.regions[0]
    assert result.at((365, 90)) is result.regions[0]
    assert result.at((180, 90)) is not result.regions[0]


def test_public_example_preserves_inland_water_and_has_two_inspectable_overrides() -> None:
    result = open_geology(EXAMPLE).coverage
    assert result.at((95, 75)) is None
    assert len(result.recipe.provinces) == 2
    west, east = result.at((170, 90)), result.at((190, 90))
    assert west is not None and west.name == "Cross-border belt"
    assert east is not None and east.name == "Cross-border belt"
    with render_geology(result, MapViewport(), (720, 400)) as image:
        assert image.mode == "RGB" and image.getbbox()


@pytest.mark.parametrize(
    "vertices",
    [
        ((150, 60), (210, 120), (150, 120), (210, 60)),
        ((150, 60), (180, 60), (210, 60)),
    ],
)
def test_invalid_polygons_fail_without_repair(vertices: tuple[tuple[float, float], ...]) -> None:
    source = world()
    recipe = replace(
        blank_geology(source.project), provinces=(replace(province(), vertices=vertices),)
    )
    with pytest.raises(ValueError, match="invalid polygon"):
        resolve_geology(source, recipe)


@pytest.mark.parametrize(
    "vertices,match",
    [
        (((0, 60), (240, 60), (240, 100)), "half the world"),
        (((0, -1), (20, 60), (0, 100)), "outside"),
        (((-10, 60), (20, 60), (0, 100)), "outside"),
        (((0, 60), (400, 60), (0, 100)), "one world width"),
        (((0, 60), (20, 60), (0, 60)), "distinct"),
    ],
)
def test_ambiguous_or_outside_rings_are_rejected(
    vertices: tuple[tuple[float, float], ...],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        replace(blank_geology(world().project), provinces=(replace(province(), vertices=vertices),))


@pytest.mark.parametrize("age", [True, -1, float("nan"), float("inf"), 1_000_001, "old"])
def test_invalid_ages_are_not_coerced(age: object) -> None:
    with pytest.raises(ValueError, match="Crust age"):
        GeologyProfile(crust_age_ma=cast(float, age))


def test_cancellation_keeps_authored_recipe_unchanged() -> None:
    source = world()
    recipe = replace(blank_geology(source.project), provinces=(province(),))
    token = CancellationToken()
    token.cancel()
    with pytest.raises(GenerationCancelled):
        resolve_geology(source, recipe, token)
    assert recipe.provinces == (province(),)


def test_retained_identity_includes_frame_names_and_assignments(tmp_path: Path) -> None:
    source = world()
    recipe = blank_geology(source.project)
    path = tmp_path / "inputs.dmgeology.json"
    saved = save_geology(resolve_geology(source, recipe), path)
    for project in (
        replace(source.project, name="Renamed"),
        replace(source.project, frame=replace(source.project.frame, radius_km=900)),
        replace(
            source.project,
            assignments=tuple(
                replace(a, continent_id="east" if a.continent_id == "west" else "west")
                for a in source.project.assignments
            ),
        ),
    ):
        with pytest.raises(ValueError, match="different world"):
            open_geology(path, prepare_world_map(project))
        assert files.world_fingerprint(project) != files.world_fingerprint(source.project)
    reordered = replace(
        source.project,
        continents=tuple(reversed(source.project.continents)),
        assignments=tuple(reversed(source.project.assignments)),
    )
    assert files.world_fingerprint(reordered) == files.world_fingerprint(source.project)
    assert open_geology(path, prepare_world_map(reordered)).sha256 == saved.sha256


def test_atomic_roundtrip_external_edit_guard_and_extension(tmp_path: Path) -> None:
    source = world()
    recipe = replace(blank_geology(source.project), provinces=(province(),))
    result = resolve_geology(source, recipe)
    path = tmp_path / "inputs.dmgeology.json"
    saved = save_geology(result, path)
    reopened = open_geology(path)
    assert reopened.coverage.recipe.provinces == recipe.provinces
    assert reopened.sha256 == saved.sha256
    assert save_geology(reopened.coverage, path, reopened.sha256).sha256 == reopened.sha256
    with pytest.raises(ValueError, match="changed outside"):
        save_geology(result, path)
    path.write_text("external edit", encoding="utf-8")
    with pytest.raises(ValueError, match="changed outside"):
        save_geology(result, path, saved.sha256)
    assert path.read_text(encoding="utf-8") == "external edit"
    assert not list(tmp_path.glob(".dmgeology-*"))
    with pytest.raises(ValueError, match="extension"):
        save_geology(result, tmp_path / "source.dmworld.json")
    assert not (tmp_path / "source.dmworld.json").exists()


def test_failed_replace_preserves_existing_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = resolve_geology(world(), blank_geology(world().project))
    path = tmp_path / "inputs.dmgeology.json"
    saved = save_geology(result, path)
    before = path.read_bytes()

    def fail(*_args: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(files.os, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        save_geology(result, path, saved.sha256)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".dmgeology-*"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 0),
        ("time_reference", "local-present"),
        ("world_sha256", "0" * 64),
        ("extra", 1),
        ("provinces", None),
        ("defaults", []),
    ],
)
def test_strict_current_recipe_fields(field: str, value: object) -> None:
    document = files.geology_document(blank_geology(world().project))
    document[field] = value
    with pytest.raises(ValueError):
        files.geology_from_bytes(canonical_json(document))


def test_duplicate_json_fields_and_size_limit_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        files.geology_from_bytes(b'{"version":1,"version":1}')
    monkeypatch.setattr(files, "MAX_GEOLOGY_BYTES", 8)
    with pytest.raises(ValueError, match="exceeds"):
        files.geology_from_bytes(b" " * 9)


def geology_validator() -> Draft202012Validator:
    schemas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (
            ROOT / "schemas/world/project-v1.schema.json",
            ROOT / "schemas/world/geology-v2.schema.json",
        )
    ]
    registry = Registry[Any]().with_resources(
        [(schema["$id"], Resource.from_contents(schema)) for schema in schemas]
    )
    Draft202012Validator.check_schema(schemas[1])
    return Draft202012Validator(schemas[1], registry=registry)


def test_schema_example_and_cli(capsys: pytest.CaptureFixture[str]) -> None:
    geology_validator().validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    assert main(["world", "inspect-geology", str(EXAMPLE)]) == 0
    text = capsys.readouterr().out
    assert "Cross-border belt" in text and "Hypotheses and explicit guidance" in text
    assert main(["world", "inspect-geology", str(ROOT / "absent.dmgeology.json")]) == 1


def test_duplicate_defaults_and_provinces_cannot_silently_replace_each_other() -> None:
    recipe = blank_geology(world().project)
    with pytest.raises(ValueError, match="exactly one default"):
        WorldGeologyRecipe(recipe.world, (recipe.defaults[0], recipe.defaults[0]))
    with pytest.raises(ValueError, match="IDs must be unique"):
        replace(recipe, provinces=(province(), province()))
    with pytest.raises(ValueError, match="names must be unique"):
        replace(recipe, provinces=(province(), replace(province(), id="province-other")))


def test_landmarks_round_trip_and_stay_optional() -> None:
    from dmtools.terrain.domain.world_geology import GeologyLandmark

    recipe = blank_geology(world().project)
    x0, y0, x1, y1 = recipe.world.frame.bounds
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    placed = replace(
        recipe,
        landmarks=(
            GeologyLandmark("landmark-sky", "Skyfather", "titan", centre),
            GeologyLandmark("landmark-eye", "The Eye", "crater", (x0 + 1, y0 + 1), 180.0),
            GeologyLandmark(
                "landmark-rift", "The Rift", "chasm", centre, None,
                (centre[0] + 0.1 * (x1 - x0), centre[1]), 20.0,
            ),
        ),
    )
    document = files.geology_document(placed)
    geology_validator().validate(document)
    reopened = files.geology_from_bytes(canonical_json(document))
    assert reopened.landmarks == tuple(sorted(placed.landmarks, key=lambda m: m.id))
    assert reopened.landmarks[1].effective_size_km == 60.0  # chasm default width
    assert reopened.landmarks[2].effective_size_km == 560.0  # titan default diameter
    # Recipes saved before landmarks existed still open, with none.
    del document["landmarks"]
    assert files.geology_from_bytes(canonical_json(document)).landmarks == ()
    for bad in (
        {"kind": "volcano"},
        {"size_km": 5.0},
        {"id": "eye"},
        {"end": (x0 + 1, y0 + 1)},  # only a chasm has an end
        {"kind": "chasm"},  # without one
        {"kind": "chasm", "end": centre},
        {"age_myr": -1.0},
        {"kind": "titan", "age_myr": 5.0},  # volcanoes stay young
    ):
        with pytest.raises(ValueError):
            GeologyLandmark(**({"id": "landmark-a", "name": "A", "kind": "crater",
                               "position": centre} | bad))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="outside the world frame"):
        replace(recipe, landmarks=(GeologyLandmark("landmark-a", "A", "crater", (x1 + 5, y0)),))
    with pytest.raises(ValueError, match="outside the world frame"):
        replace(
            recipe,
            landmarks=(GeologyLandmark("landmark-a", "A", "chasm", centre, None, (x1 + 5, y0)),),
        )
    with pytest.raises(ValueError, match="km long"):
        replace(
            recipe,
            landmarks=(
                GeologyLandmark(
                    "landmark-a", "A", "chasm", centre, None, (centre[0] + 1e-6, centre[1])
                ),
            ),
        )
    with pytest.raises(ValueError, match="names must be unique"):
        replace(
            recipe,
            landmarks=(
                GeologyLandmark("landmark-a", "Same", "crater", centre),
                GeologyLandmark("landmark-b", "same", "titan", centre),
            ),
        )
