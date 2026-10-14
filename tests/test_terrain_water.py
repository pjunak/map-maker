"""Authored lake levels, retention and inspectable water conflicts."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Polygon

from map_maker.terrain.adapters import load_terrain_project, save_terrain_project
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    LakeToolSettings,
    TerrainAuthoringState,
    TerrainBasin,
    TerrainConstraint,
    TerrainSettings,
)
from map_maker.terrain.pipeline import generate_terrain
from map_maker.terrain.pipeline.hydrology import drainage_incision
from map_maker.terrain.pipeline.water import (
    WaterReview,
    basin_intent_ids,
    prepare_basins,
    review_water,
    water_products,
)
from map_maker.terrain.pipeline.water_sampling import review_shorelines

POINTS = ((.2, .2), (.8, .2), (.8, .8), (.2, .8), (.2, .2))
LAND = Polygon(((0, 0), (6, 0), (6, 6), (0, 6)))


def _review(
    surface: NDArray[np.float64], basin: TerrainBasin,
    anchors: tuple[TerrainConstraint, ...] = (), outlet_height: float | None = None,
) -> WaterReview:
    basins = prepare_basins((basin,), 6, 6, LAND, 100)
    x, y = np.meshgrid(np.arange(7, dtype=np.float64), np.arange(7, dtype=np.float64))
    ids = basin_intent_ids(x, y, basins)
    routing = drainage_incision(surface, np.ones_like(surface, bool), np.ones_like(surface),
        x_spacing_km=1, y_spacing_km=1, maximum_elevation_m=100, variability=.5,
        retention_terminal_mask=ids > 0)
    # These grid fixtures isolate the coarse review; a separate rim closes the exact boundary.
    def sample_rim(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.full(x.shape, 100., dtype=np.float32)
    shorelines = review_shorelines(basins, .25, float(np.sqrt(2)), sample_rim)
    return review_water(basins, ids, surface, routing, anchors,
                        (outlet_height,), (None,), shorelines)


def _bowl() -> NDArray[np.float64]:
    surface = np.full((7, 7), 20., dtype=np.float64)
    surface[2:5, 2:5] = 2
    return surface


def test_lake_water_is_separate_from_bathymetry_and_closed_flow_is_retained() -> None:
    surface = _bowl()
    original = surface.copy()
    basin = TerrainBasin(POINTS, "lake", 10)
    review = _review(surface, basin)
    record = review.basins[0]
    assert record.wet_cell_count == 9
    assert record.wet_component_count == 1
    assert record.low_boundary_cell_count == record.dry_cell_count == 0
    assert record.planned_exit_edge_count == 0
    assert record.retained_contributing_area_km2 >= 9
    assert record.issues == ()
    axis = np.arange(7, dtype=np.float64)
    basins = prepare_basins((basin,), 6, 6, LAND, 100)
    products = water_products(surface.astype(np.float32), axis, axis, basins,
                              np.zeros(surface.shape, dtype=np.uint32), review)
    np.testing.assert_array_equal(products.surface_m[2:5, 2:5], 10)
    assert np.isfinite(products.surface_m).sum() == 9
    np.testing.assert_array_equal(surface, original)
    assert products.surface_m.dtype == np.float32
    assert products.intent_ids.dtype == np.uint32


def test_review_distinguishes_low_boundary_exposed_anchors_and_high_outlet() -> None:
    surface = _bowl()
    surface[1, 3] = 2
    surface[3, 3] = 15
    lake = TerrainBasin(POINTS, "lake", 10, POINTS[0])
    review = _review(surface, lake, (ElevationPoint((.5, .5), 15, 1),), 20)
    record = review.basins[0]
    assert record.low_boundary_cell_count > 0
    assert record.exposed_height_anchor_count == 1
    assert record.dry_cell_count == 1
    assert set(record.issues) == {
        "low_boundary", "exposed_height_anchor", "outlet_above_water", "outlet_route_blocked",
    }


@pytest.mark.parametrize("level", [1., 10.])
@pytest.mark.parametrize(("offset", "issue"), [
    (.02, "outlet_above_water"), (-.02, "outlet_below_water"),
    (0., None), (.005, None), (-.005, None), (.01, None), (-.01, None), (None, None),
])
def test_outlet_ground_difference_is_signed_and_uses_water_tolerance(
    level: float, offset: float | None, issue: str | None,
) -> None:
    height = level + offset if offset is not None else None
    record = _review(_bowl(), TerrainBasin(POINTS, "lake", level, POINTS[0]),
                     outlet_height=height).basins[0]
    if height is None:
        assert record.outlet_ground_minus_water_m is None
    else:
        assert record.outlet_ground_minus_water_m == pytest.approx(height - level)
    level_issues = {"outlet_above_water", "outlet_below_water"} & set(record.issues)
    assert level_issues == ({issue} if issue is not None else set())


def test_dry_basin_has_no_water_and_retains_planned_flow() -> None:
    record = _review(_bowl(), TerrainBasin(POINTS, "dry_basin")).basins[0]
    assert record.wet_cell_count == 0
    assert record.dry_cell_count == 9
    assert record.planned_exit_edge_count == 0
    assert record.retained_contributing_area_km2 >= 9
    assert record.issues == ()


def test_no_water_and_disconnected_pools_remain_explicit() -> None:
    surface = _bowl()
    assert "no_water_at_level" in _review(surface, TerrainBasin(POINTS, "lake", 0)).basins[0].issues
    surface[2:5, 3] = 20
    record = _review(surface, TerrainBasin(POINTS, "lake", 10)).basins[0]
    assert record.wet_component_count == 2
    assert "disconnected_water" in record.issues


@pytest.mark.parametrize("level", [float("nan"), float("inf"), -1, None])
def test_lake_requires_a_valid_level(level: float | None) -> None:
    with pytest.raises(ValueError, match="Lake water level"):
        TerrainBasin(POINTS, "lake", level)


def test_dry_basin_rejects_water_or_an_outlet() -> None:
    with pytest.raises(ValueError, match="dry basin"):
        TerrainBasin(POINTS, "dry_basin", 0)
    with pytest.raises(ValueError, match="dry basin"):
        TerrainBasin(POINTS, "dry_basin", outlet=POINTS[0])


def test_ambiguous_invalid_or_external_footprints_and_outlets_are_rejected() -> None:
    lake = TerrainBasin(POINTS, "lake", 10)
    for basin, message in (
        (replace(lake, outlet=(.5, .5)), "boundary"),
        (replace(lake, water_level_m=101), "ceiling"),
        (replace(lake, points=(POINTS[0], POINTS[2], POINTS[1], POINTS[3], POINTS[0])), "simple"),
    ):
        with pytest.raises(ValueError, match=message):
            prepare_basins((basin,), 6, 6, LAND, 100)
    with pytest.raises(ValueError, match="overlap or touch"):
        prepare_basins((lake, replace(lake, water_level_m=11)), 6, 6, LAND, 100)
    holed = Polygon(LAND.exterior, holes=[((2, 2), (3, 2), (3, 3), (2, 3))])
    with pytest.raises(ValueError, match="exclude SVG"):
        prepare_basins((lake,), 6, 6, holed, 100)


def test_retention_excludes_automatic_cut_preserves_anchors_and_nested_samples() -> None:
    coast = Coastline(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)), "square")
    settings = TerrainSettings(seed=42, resolution_px=65, object_scale_km=1000)
    lake = TerrainBasin(POINTS, "lake", 1000)
    anchor = ElevationPoint((.5, .5), 300, 60)
    first = generate_terrain(coast, settings, constraints=(lake, anchor))
    second = generate_terrain(coast, replace(settings, resolution_px=129),
                              constraints=(anchor, lake))
    retained = first.water.routing_intent_ids > 0
    assert retained.any()
    np.testing.assert_array_equal(first.routing.retention_terminal_mask, retained)
    np.testing.assert_array_equal(first.routing.receivers[retained], -1)
    np.testing.assert_array_equal(first.routing.detail_suppression[retained], 0)
    area = first.routing_grid.x_spacing_km * first.routing_grid.y_spacing_km
    assert first.routing.accumulation_km2[first.routing.outlet_mask].sum() == pytest.approx(
        first.routing_land_mask.sum() * area)
    assert all(record.planned_exit_edge_count == 0 for record in first.water.review.basins)
    np.testing.assert_array_equal(first.routing.incision_limit_m[retained], 0)
    np.testing.assert_array_equal(first.routing.incision_m[retained], 0)
    assert first.elevation_m[32, 32] == second.elevation_m[64, 64] == 300
    np.testing.assert_array_equal(first.elevation_m, second.elevation_m[::2, ::2])
    np.testing.assert_array_equal(first.water.surface_m, second.water.surface_m[::2, ::2])
    np.testing.assert_array_equal(first.water.intent_ids, second.water.intent_ids[::2, ::2])
    assert first.water.review == second.water.review
    outlet_variant = generate_terrain(
        coast, settings, constraints=(replace(lake, outlet=(.8, .5)), anchor))
    np.testing.assert_array_equal(first.elevation_m, outlet_variant.elevation_m)
    np.testing.assert_array_equal(first.routing.receivers, outlet_variant.routing.receivers)
    assert outlet_variant.water.review.basins[0].outlet_route is not None
    assert "outlet_route_blocked" in outlet_variant.water.review.basins[0].issues
    changed = generate_terrain(
        coast, settings, constraints=(replace(lake, water_level_m=1500), anchor))
    np.testing.assert_array_equal(first.elevation_m, changed.elevation_m)
    assert np.isfinite(changed.water.surface_m).sum() >= np.isfinite(first.water.surface_m).sum()


def test_water_project_round_trip_preserves_intent_and_tool_controls(tmp_path: Path) -> None:
    example = Path(__file__).parents[1] / "examples/terrain/example.terrain.json"
    loaded = load_terrain_project(example)
    project = replace(loaded.project,
        constraints=(TerrainBasin(POINTS, "lake", 700, POINTS[0]),),
        authoring=TerrainAuthoringState(active_tool="lake", lake=LakeToolSettings(700, True)))
    path = tmp_path / "water.terrain.json"
    save_terrain_project(project, loaded.coastline_source, path)
    assert load_terrain_project(path).project == project
