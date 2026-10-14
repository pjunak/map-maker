"""Authored geography must participate in planning, with inspectable conflicts."""

from dataclasses import replace

import numpy as np
import pytest

from map_maker.terrain.adapters.render import render_drainage_overlay
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    TerrainBrushStroke,
    TerrainConstraint,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.pipeline.diagnostics import (
    review_drainage_routing,
)
from map_maker.terrain.pipeline.generate import GeneratedTerrain, generate_terrain
from map_maker.terrain.pipeline.hydrology import (
    drainage_incision,
)

COAST = Coastline(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)), "routing-square")
SETTINGS = TerrainSettings(resolution_px=65, object_scale_km=1000, maximum_elevation_m=6000)
RIDGE = TerrainStructure("ridge", ((0.5, 0.2), (0.5, 0.8)), 5500, 80)


@pytest.fixture(scope="module")
def baseline() -> GeneratedTerrain:
    return generate_terrain(COAST, SETTINGS)


@pytest.mark.parametrize("case,constraints", [
    ("ridge", (RIDGE,)),
    ("pass", (RIDGE, ElevationPoint((0.5, 0.5), 1500, 40))),
    ("valley", (TerrainStructure("valley", ((0.25, 0.5), (0.75, 0.5)), 300, 50),)),
    ("coastal-outlet", (TerrainStructure("valley", ((0.5, 0.5), (1.0, 0.5)), 300, 50),)),
    ("brush", (TerrainBrushStroke(((0.4, 0.5), (0.6, 0.5)), 400, 80, 1, "relative"),)),
])
def test_authored_features_change_planning_and_preserve_finished_field(
    baseline: GeneratedTerrain, case: str, constraints: tuple[TerrainConstraint, ...],
) -> None:
    terrain = generate_terrain(COAST, SETTINGS, constraints=constraints)
    source = terrain.routing.source_elevation_m
    if case == "ridge":
        assert source[128, 128] >= 5500
    elif case == "pass":
        assert source[128, 128] == pytest.approx(1500)
        assert terrain.elevation_m[32, 32] == 1500
    elif case in ("valley", "coastal-outlet"):
        assert source[128, 128] == pytest.approx(300)
        assert terrain.elevation_m[32, 32] <= 300
    else:
        assert source[128, 128] - baseline.routing.source_elevation_m[128, 128] == (
            pytest.approx(400)
        )
    assert np.any(terrain.routing.receivers != baseline.routing.receivers)
    assert np.any(terrain.routing.incision_m != baseline.routing.incision_m)
    np.testing.assert_array_equal(
        terrain.routing_final_elevation_m[::4, ::4], terrain.elevation_m,
    )
    np.testing.assert_array_equal(terrain.elevation_m[:, -1], 0)
    assert terrain.constraints == constraints
    assert terrain.routing_agreement.channel_edge_count > 0


def test_routing_products_are_deterministic_and_independent_of_display_resolution() -> None:
    constraints = (RIDGE, ElevationPoint((0.5, 0.5), 1500, 40))
    first = generate_terrain(COAST, SETTINGS, constraints=constraints)
    second = generate_terrain(COAST, replace(SETTINGS, resolution_px=129),
                              constraints=tuple(reversed(constraints)))
    np.testing.assert_array_equal(first.elevation_m, second.elevation_m[::2, ::2])
    np.testing.assert_array_equal(first.routing.receivers, second.routing.receivers)
    np.testing.assert_array_equal(first.routing.accumulation_km2, second.routing.accumulation_km2)
    np.testing.assert_array_equal(
        first.routing.source_elevation_m, second.routing.source_elevation_m,
    )
    assert first.routing_agreement == second.routing_agreement
    assert first.routing_conflicts.summary == second.routing_conflicts.summary
    np.testing.assert_array_equal(first.routing_conflicts.flags, second.routing_conflicts.flags)
    np.testing.assert_array_equal(first.routing_conflicts.final_fill_depth_m,
                                  second.routing_conflicts.final_fill_depth_m)
    receivers = first.routing.receivers
    edges = receivers >= 0
    filled = first.routing.routing_elevation_m
    assert np.all(filled.ravel()[receivers[edges]] < filled[edges])
    assert np.all(first.routing_land_mask.ravel()[receivers[edges]])
    np.testing.assert_array_equal(first.routing.outlet_mask, first.routing_land_mask & ~edges)


def test_routing_review_reports_uphill_edges_without_changing_terrain() -> None:
    source = np.tile(np.array([200., 100., 0.]), (3, 1))
    land = np.ones((3, 3), dtype=np.bool_)
    routing = drainage_incision(source, land, np.ones_like(source),
                               x_spacing_km=1, y_spacing_km=1,
                               maximum_elevation_m=300, variability=0.5)
    channel = np.zeros_like(land)
    channel[1, 1] = True
    routing = replace(routing, channel_mask=channel)
    final = source.copy()
    final[1, 2] = 150
    original = final.copy()
    review = review_drainage_routing(routing, final, land,
                                        x_spacing_km=1, y_spacing_km=1)
    (agreement, _conflicts) = review.agreement, review.conflicts
    assert agreement.channel_edge_count == 1
    assert agreement.uphill_channel_edge_count == 1
    assert agreement.changed_channel_receiver_count == 1
    assert agreement.maximum_channel_rise_m == 50
    np.testing.assert_array_equal(final, original)
    np.testing.assert_array_equal(routing.source_elevation_m, source)


def test_workbench_overlay_is_transparent_away_from_channels(baseline: GeneratedTerrain) -> None:
    with render_drainage_overlay(baseline) as overlay:
        rgba = np.asarray(overlay)
        assert overlay.size == (baseline.routing_grid.width, baseline.routing_grid.height)
        assert overlay.mode == "RGBA"
        assert np.count_nonzero(rgba[..., 3]) > 0
        assert np.count_nonzero(rgba[..., 3] == 0) > 0
        visible = rgba[rgba[..., 3] > 0]
        assert np.all(np.isin(visible[:, 0], [45, 255]))


def test_display_resolution_overlay_keeps_thin_lines(baseline: GeneratedTerrain) -> None:
    with render_drainage_overlay(baseline) as native:
        native_count = np.count_nonzero(np.asarray(native)[..., 3])
    size = (4 * (baseline.routing_grid.width - 1) + 1,
            4 * (baseline.routing_grid.height - 1) + 1)
    with render_drainage_overlay(baseline, size) as enlarged:
        assert enlarged.size == size
        # Line length grows with scale; raster cell blocks would grow with area.
        assert np.count_nonzero(np.asarray(enlarged)[..., 3]) < 6 * native_count
