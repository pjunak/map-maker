# pyright: reportPrivateUsage=false
"""Line-owned peak/pass/floor intent, isolation and portable regeneration."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from jsonschema import validate
from shapely.geometry import LineString

from map_maker.terrain.adapters import (
    load_svg_coastline_source,
    load_terrain_project,
    save_terrain_project,
)
from map_maker.terrain.adapters.project import project_snapshot_from_json, project_snapshot_to_json
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LandformSettings,
    TerrainProject,
    TerrainRegion,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.domain import (
    StructureProfileKnot as Knot,
)
from map_maker.terrain.pipeline.generate import (
    _structure_profile,
    generate_terrain,
    prepare_terrain_field,
)
from map_maker.terrain.workbench import InstructionHistory, move_instruction

COAST = Coastline(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.)), "profile-square")
SETTINGS = TerrainSettings(seed=42, object_scale_km=1000., resolution_px=65, coastal_rise_km=5.)
PLAIN = TerrainRegion(COAST.points, LandformSettings("plain", 450., 0., 150., 50.))
PROFILE = tuple(Knot(p, h) for p, h in ((0., 700.), (.25, 2800.), (.5, 1400.),
                                     (.75, 2400.), (1., 600.)))
RIDGE = TerrainStructure("ridge", ((.1, .5), (.9, .5)), 1800., 40., profile=PROFILE)


@pytest.mark.parametrize("knots", [
    (Knot(0., 100.),), (Knot(.1, 100.), Knot(1., 100.)),
    (Knot(0., 100.), Knot(.9, 100.)),
    (Knot(0., 100.), Knot(.5, 200.), Knot(.5, 300.), Knot(1., 100.)),
    (Knot(0., 100.), Knot(.8, 200.), Knot(.4, 300.), Knot(1., 100.)),
    tuple(Knot(float(p), 100.) for p in np.linspace(0., 1., 65)),
])
def test_invalid_profile_shape_is_rejected(knots: tuple[Knot, ...]) -> None:
    with pytest.raises(ValueError, match=r"profile|Profile"):
        replace(RIDGE, profile=knots)


@pytest.mark.parametrize("position,height", [(float("nan"), 1.), (.5, float("inf")),
                                           (-.1, 1.), (1.1, 1.), (.5, -1.), (True, 1.)])
def test_invalid_profile_numbers_are_rejected(position: float, height: float) -> None:
    with pytest.raises(ValueError):
        Knot(position, height)


def test_profile_is_bound_to_its_line_and_preserves_peaks_pass_and_cross_sections() -> None:
    near = ElevationPoint((.5, .53), 3500., 2.)
    field = prepare_terrain_field(COAST, SETTINGS, (PLAIN, RIDGE, near), None)
    ridge = next(c for c in field.constraints if c.kind == "ridge")
    positions = np.linspace(0., 800., 401)
    target, influence = _structure_profile(ridge, positions)
    np.testing.assert_array_equal(
        target[[0, 100, 200, 300, 400]], [700., 2800., 1400., 2400., 600.])
    np.testing.assert_array_equal(influence, 1.)
    assert target.min() >= 600. and target.max() <= 2800.
    assert not next(c for c in field.constraints if c.kind == "point").attached_to_structure
    # Check delivered ground without the separate final hard-point influence.
    clean = prepare_terrain_field(COAST, SETTINGS, (PLAIN, RIDGE), None)
    heights = clean.sample_ground(np.array([300., 500., 700.]), np.full(3, 500.))
    np.testing.assert_allclose(heights, [2800., 1400., 2400.], atol=.002)
    cross = clean.sample_ground(np.full(3, 500.), np.array([400., 500., 600.]))
    assert cross[1] > max(cross[0], cross[2]) + 500.
    assert heights[1] < min(heights[0], heights[2]) - 900.


def test_profile_uses_smoothed_metric_arc_length_and_reverses_with_the_line() -> None:
    ridge = replace(RIDGE, points=((.1, .3), (.3, .65), (.6, .6), (.9, .3)))
    reverse = replace(ridge, points=tuple(reversed(ridge.points)),
                      profile=tuple(Knot(1-k.position, k.elevation_m) for k in reversed(PROFILE)))
    first = prepare_terrain_field(COAST, SETTINGS, (PLAIN, ridge), None)
    second = prepare_terrain_field(COAST, SETTINGS, (PLAIN, reverse), None)
    line = next(c.geometry for c in first.constraints if c.kind == "ridge")
    assert isinstance(line, LineString)
    points = np.array([line.interpolate(k.position, normalized=True).coords[0] for k in PROFILE])
    expected = np.array([k.elevation_m for k in PROFILE])
    np.testing.assert_allclose(first.sample_ground(points[:, 0], points[:, 1]), expected, atol=.002)
    np.testing.assert_allclose(
        second.sample_ground(points[:, 0], points[:, 1]), expected, atol=.002)


def test_valley_profile_rejects_uphill_absolute_floors_and_preserves_relative_depth() -> None:
    with pytest.raises(ValueError, match="downstream"):
        replace(RIDGE, kind="valley")
    profile = tuple(Knot(p, h) for p, h in ((0., 400.), (.4, 200.), (1., 50.)))
    valley = replace(RIDGE, kind="valley", profile=profile, elevation_m=50.)
    field = prepare_terrain_field(COAST, SETTINGS, (PLAIN, valley), None)
    values = field.sample_ground(np.linspace(100., 900., 201), np.full(201, 500.))
    assert np.all(np.diff(values) <= .002)
    np.testing.assert_allclose(values[[0, 80, 200]], [400., 200., 50.], atol=.002)
    relative = replace(valley, elevation_mode="relative", profile=(Knot(0., 50.), Knot(1., 250.)))
    field = prepare_terrain_field(COAST, SETTINGS, (PLAIN, relative), None)
    np.testing.assert_allclose(field.sample_ground(np.array([100., 900.]), np.full(2, 500.)),
                               [400., 200.], atol=.002)


def test_hard_points_coast_ceiling_order_and_shared_samples_remain_authoritative() -> None:
    point = ElevationPoint((.5, .5), 1200., 10.)
    a = generate_terrain(COAST, SETTINGS, constraints=(PLAIN, RIDGE, point))
    b = generate_terrain(COAST, replace(SETTINGS, resolution_px=129),
                         constraints=(point, RIDGE, PLAIN))
    np.testing.assert_array_equal(a.elevation_m, b.elevation_m[::2, ::2])
    np.testing.assert_array_equal(a.routing.receivers, b.routing.receivers)
    assert a.elevation_m[32, 32] == 1200.
    np.testing.assert_array_equal(a.elevation_m[[0, -1]], 0.)
    assert np.all(a.routing.incision_m <= a.routing.incision_limit_m)
    bad = replace(RIDGE, profile=(Knot(0., 6001.), Knot(1., 700.)))
    with pytest.raises(ValueError, match="ceiling"):
        prepare_terrain_field(COAST, replace(SETTINGS, maximum_elevation_m=6000.), (bad,), None)


def test_profile_roundtrip_snapshot_schema_and_history(tmp_path: Path) -> None:
    source = load_svg_coastline_source(Path(__file__).parent / "fixtures/terrain/closed-coast.svg")
    project = TerrainProject(source.coastline, SETTINGS, (RIDGE,))
    path = tmp_path / "range.terrain.json"
    save_terrain_project(project, source, path)
    assert load_terrain_project(path).project == project
    snapshot = json.loads(json.dumps(project_snapshot_to_json(project)))
    assert project_snapshot_from_json(snapshot) == project
    document = json.loads(path.read_text())
    schema_path = Path(__file__).parents[1] / "schemas/terrain/project-v9.schema.json"
    schema = json.loads(schema_path.read_text())
    validate(document, schema)
    assert document["constraints"][0]["profile"][2] == {"position": .5, "elevation_m": 1400.}
    history = InstructionHistory((replace(RIDGE, profile=()),))
    history.replace(0, RIDGE)
    history.undo()
    assert history.constraints[0] == replace(RIDGE, profile=())
    history.redo()
    assert history.constraints[0] == RIDGE
    moved = move_instruction(RIDGE, (.01, -.01), vertex=0)
    assert isinstance(moved, TerrainStructure) and moved.profile == PROFILE


def test_narrow_pass_informs_longitudinal_water_sampling() -> None:
    from shapely.geometry import Point

    from map_maker.terrain.pipeline.generate import _water_sampling_guides
    from map_maker.terrain.pipeline.water_sampling import SamplingDensity, plan_ground_profile
    narrow = replace(RIDGE, profile=(Knot(0., 2000.), Knot(.5, 1000.),
                                    Knot(.5005, 2000.), Knot(1., 2000.)))
    field = prepare_terrain_field(COAST, SETTINGS, (PLAIN, narrow), None)
    guides = _water_sampling_guides(field.constraints, field.regions, SETTINGS)
    fine = [g for g in guides if isinstance(g, SamplingDensity) and g.spacing_km < .11]
    assert len(fine) == 1 and fine[0].geometry is not None
    assert fine[0].geometry.covers(Point(500., 500.))
    assert not fine[0].geometry.covers(Point(500., 5000.))
    plan = plan_ground_profile(((490., 500.), (510., 500.)), 1., guides)
    assert plan.feature_spacing_limit_km is not None
    assert plan.feature_spacing_limit_km <= .100001


@pytest.mark.parametrize("example_name, middle_height", [
    ("range-lowland", 1400.), ("connected-crests", 2400.),
])
def test_profile_build_reopens_as_a_verified_parent_with_identical_ground(
    tmp_path: Path, example_name: str, middle_height: float,
) -> None:
    from map_maker.terrain.adapters.build import runtime_identity
    from map_maker.terrain.adapters.parent import load_terrain_parent
    from map_maker.terrain.application.build import build_terrain_project
    from map_maker.terrain.pipeline.parent import prepare_verified_parent
    example = Path(__file__).parents[1] / f"examples/terrain/{example_name}.terrain.json"
    loaded = load_terrain_project(example)
    project = replace(loaded.project, settings=replace(loaded.project.settings, resolution_px=65))
    source = tmp_path / "profile.terrain.json"
    save_terrain_project(project, loaded.coastline_source, source)
    output = tmp_path / "build"
    build_terrain_project(source, output)
    saved = load_terrain_parent(output, runtime_identity())
    parent = prepare_verified_parent(saved.data)
    field = prepare_terrain_field(project.coastline, project.settings, project.constraints, None)
    x, y = np.meshgrid(np.linspace(150., 850., 65), np.linspace(250., 750., 49))
    replayed = parent.sampler.prepared_field
    np.testing.assert_array_equal(field.sample_ground(x, y), replayed.sample_ground(x, y))
    document = json.loads((output / "inputs.json").read_text())
    assert document["schema_version"] == 4
    assert document["constraints"][1]["profile"][2] == {
        "position": .5, "elevation_m": middle_height}
