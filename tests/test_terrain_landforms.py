"""Regional shape, authoring authority, persistence and sampling contracts."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from jsonschema import validate
from numpy.typing import NDArray
from shapely.geometry import Polygon

from map_maker.terrain.adapters import (
    load_svg_coastline_source,
    load_terrain_project,
    save_terrain_project,
)
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LandformKind,
    LandformSettings,
    TerrainAuthoringState,
    TerrainProject,
    TerrainRegion,
    TerrainSettings,
    landform_preset,
)
from map_maker.terrain.pipeline.generate import generate_terrain
from map_maker.terrain.pipeline.landforms import (
    prepare_regions,
    regional_elevation_fields,
    regional_incision_budget,
    regional_transition_mask,
)

COAST = Coastline(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)), "regions")
RING = ((0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95), (0.05, 0.05))
SETTINGS = TerrainSettings(seed=42, object_scale_km=1000, resolution_px=65,
                           maximum_elevation_m=6000, coastal_rise_km=5)


def test_regional_recipes_have_distinct_elevations_and_local_relief() -> None:
    fields: dict[str, NDArray[np.float32]] = {}
    for kind in ("plain", "hills", "plateau", "mountains"):
        region = TerrainRegion(RING, landform_preset(kind))
        terrain = generate_terrain(COAST, SETTINGS, constraints=(region,))
        fields[kind] = terrain.elevation_m[16:49, 16:49]
        assert np.isfinite(terrain.elevation_m).all()
        assert np.max(terrain.elevation_m) <= SETTINGS.maximum_elevation_m
        np.testing.assert_array_equal(terrain.elevation_m[0], 0)
        cap = {"plain": 15, "hills": 360, "plateau": 50, "mountains": 875}[kind]
        assert np.max(terrain.routing.incision_m[64:193, 64:193]) <= cap
        assert np.all(terrain.routing.incision_m <= terrain.routing.incision_limit_m)
        assert np.all(terrain.routing.incision_limit_m[~terrain.routing_land_mask] == 0)
    assert fields["plain"].std() < fields["hills"].std() < fields["mountains"].std()
    assert fields["plain"].mean() < 350
    assert fields["plateau"].mean() > 2000
    assert fields["plateau"].std() < fields["hills"].std()


def test_regions_preserve_anchors_order_and_shared_samples() -> None:
    regions = (TerrainRegion(RING, landform_preset("plain")),
               TerrainRegion(RING, landform_preset("mountains")))
    anchor = ElevationPoint((0.5, 0.5), 1800, 35)
    first = generate_terrain(COAST, SETTINGS, constraints=(*regions, anchor))
    second = generate_terrain(COAST, replace(SETTINGS, resolution_px=129),
                              constraints=(anchor, *reversed(regions)))
    np.testing.assert_array_equal(first.elevation_m, second.elevation_m[::2, ::2])
    np.testing.assert_array_equal(first.routing.receivers, second.routing.receivers)
    assert first.elevation_m[32, 32] == 1800
    assert first.constraints == (*regions, anchor)
    assert first.routing_agreement == second.routing_agreement
    assert first.routing_conflicts.summary == second.routing_conflicts.summary
    np.testing.assert_array_equal(first.routing_conflicts.flags, second.routing_conflicts.flags)
    np.testing.assert_array_equal(first.routing.incision_limit_m,
                                  second.routing.incision_limit_m)


def test_regional_boundaries_are_continuous_and_do_not_change_distant_samples() -> None:
    land = Polygon(COAST.points)
    region = TerrainRegion(RING, landform_preset("plateau"))
    prepared = prepare_regions((region,), 1000, 1000, land.buffer(2000), 6000)
    x = np.array([0., 50., 50.000001, 50.001, 500.])
    y = np.full_like(x, 500)
    base = np.full_like(x, 800)
    full, macro = regional_elevation_fields(x, y, np.full_like(x, 500), base, base,
                                           SETTINGS, prepared)
    np.testing.assert_array_equal(full[:2], base[:2])
    assert abs(full[2] - full[1]) < 1e-8
    assert abs(full[3] - full[1]) < 1e-5
    assert macro[-1] > 2100


def test_mountain_orientation_changes_directional_relief() -> None:
    x, y = np.meshgrid(np.linspace(150, 850, 101), np.linspace(150, 850, 101))
    land = Polygon(((0, 0), (1000, 0), (1000, 1000), (0, 1000)))
    results: list[tuple[float, float]] = []
    for angle in (0, 90):
        region = TerrainRegion(RING, replace(landform_preset("mountains"),
                                            orientation_deg=angle))
        prepared = prepare_regions((region,), 1000, 1000, land, 6000)
        _, macro = regional_elevation_fields(x, y, np.full_like(x, 500),
                                             np.zeros_like(x), np.zeros_like(x), SETTINGS, prepared)
        results.append((float(np.mean(np.abs(np.diff(macro, axis=1)))),
                        float(np.mean(np.abs(np.diff(macro, axis=0))))))
    assert results[0][1] > 1.5 * results[0][0]
    assert results[1][0] > 1.5 * results[1][1]


def test_region_project_round_trip_and_invalid_geometry(tmp_path: Path) -> None:
    source = load_svg_coastline_source(Path(__file__).parent / "fixtures/terrain/closed-coast.svg")
    region = TerrainRegion(RING, landform_preset("hills"))
    project = TerrainProject(source.coastline, SETTINGS, (region,),
                             TerrainAuthoringState(active_tool="region", region=region.settings))
    path = tmp_path / "regions.terrain.json"
    save_terrain_project(project, source, path)
    assert load_terrain_project(path).project == project
    schema = Path(__file__).parents[1] / "schemas/terrain/project-v9.schema.json"
    validate(json.loads(path.read_text()), json.loads(schema.read_text()))
    crossed = TerrainRegion(((0, 0), (1, 1), (0, 1), (1, 0), (0, 0)))
    with pytest.raises(ValueError, match="simple polygon"):
        generate_terrain(COAST, SETTINGS, constraints=(crossed,))


@pytest.mark.parametrize("kind", ["plain", "hills", "plateau", "mountains"])
def test_regional_seed_changes_the_numeric_surface(kind: LandformKind) -> None:
    region = TerrainRegion(RING, landform_preset(kind))
    land = Polygon(((0, 0), (1000, 0), (1000, 1000), (0, 1000)))
    prepared = prepare_regions((region,), 1000, 1000, land, 6000)
    x = np.linspace(250, 750, 65)
    values = [regional_elevation_fields(x, x, np.full_like(x, 500), np.zeros_like(x),
              np.zeros_like(x), replace(SETTINGS, seed=seed), prepared)[0] for seed in (42, 43)]
    assert not np.array_equal(values[0], values[1])


@pytest.mark.parametrize("changes", [
    {"relief_m": -1.}, {"elevation_m": float("nan")}, {"transition_km": 0.},
    {"feature_size_km": float("inf")}, {"orientation_deg": 180.},
])
def test_invalid_regional_parameters_are_rejected(changes: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        replace(LandformSettings(), **changes)


def test_regional_incision_budget_blends_boundaries_and_overlaps() -> None:
    land = Polygon(((0, 0), (1000, 0), (1000, 1000), (0, 1000)))
    plain = TerrainRegion(RING, landform_preset("plain"))
    plateau = TerrainRegion(RING, replace(landform_preset("plateau"), transition_km=50))
    regions = prepare_regions((plain, plateau), 1000, 1000, land, 6000)
    x = np.array([0., 50., 50.000001, 50.001, 75., 500.])
    y = np.full_like(x, 500)
    budget = regional_incision_budget(x, y, 600, regions)
    np.testing.assert_array_equal(budget[:2], [600., 600.])
    assert abs(budget[2] - 600) < 1e-8
    assert abs(budget[3] - 600) < 1e-5
    # Coverage fades once, regardless of the number of overlapping recipes.
    np.testing.assert_allclose(budget[4:], [316.25, 32.5])
    np.testing.assert_array_equal(
        budget, regional_incision_budget(x, y, 600,
            prepare_regions((plateau, plain), 1000, 1000, land, 6000)),
    )
    np.testing.assert_array_equal(regional_incision_budget(x, y, 600, ()), 600)
    np.testing.assert_array_equal(regional_transition_mask(x, y, regions),
                                  [False, True, True, True, True, False])


def test_zero_relief_region_disables_automatic_cutting_but_preserves_anchor() -> None:
    region = TerrainRegion(RING, replace(landform_preset("plateau"), relief_m=0))
    terrain = generate_terrain(COAST, SETTINGS,
                               constraints=(region, ElevationPoint((0.5, 0.5), 1800, 35)))
    np.testing.assert_array_equal(terrain.routing.incision_m[64:193, 64:193], 0)
    np.testing.assert_array_equal(terrain.routing.incision_limit_m[64:193, 64:193], 0)
    assert terrain.elevation_m[32, 32] == 1800


def test_region_holes_exclude_guidance_and_remain_continuous_at_the_inner_edge() -> None:
    hole = ((.4, .4), (.6, .4), (.6, .6), (.4, .6), (.4, .4))
    region = TerrainRegion(RING, landform_preset("plateau"), (hole,))
    land = Polygon(((0, 0), (1000, 0), (1000, 1000), (0, 1000)))
    prepared = prepare_regions((region,), 1000, 1000, land, 6000)
    x = np.array([300., 399.999999, 400., 500., 600., 600.000001, 700.])
    y = np.full_like(x, 500.)
    background = np.full_like(x, 700.)
    full, _ = regional_elevation_fields(
        x, y, np.full_like(x, 500.), background, background, SETTINGS, prepared,
    )
    np.testing.assert_array_equal(full[2:5], background[2:5])
    assert abs(full[1] - 700.) < 1e-8 and abs(full[5] - 700.) < 1e-8
    assert min(full[0], full[-1]) > 2000.
    invalid = replace(region, holes=(RING,))
    with pytest.raises(ValueError, match="simple polygon"):
        prepare_regions((invalid,), 1000, 1000, land, 6000)
