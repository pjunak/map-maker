from dataclasses import replace
from math import inf, nan
from typing import Any

import numpy as np
import pytest

from map_maker.terrain.adapters.render import render_height_map
from map_maker.terrain.domain import (
    Coastline,
    ElevationPoint,
    EndpointGrid,
    LocalMetricFrame,
    TerrainSettings,
)
from map_maker.terrain.pipeline.generate import generate_terrain
from map_maker.terrain.pipeline.grid import grid_coordinates


def test_source_frame_uses_longest_dimension_and_retains_inverse_origin() -> None:
    frame = LocalMetricFrame((100.0, 200.0, 110.0, 220.0), 4000.0)
    assert frame.km_per_source_unit == 200.0
    assert frame.extent_km == (0.0, 0.0, 2000.0, 4000.0)
    assert frame.source_to_local((105.0, 215.0)) == (1000.0, 3000.0)
    assert frame.local_to_source((1000.0, 3000.0)) == (105.0, 215.0)
    # A future halo can lie outside the input bounds; conversion must not clip it.
    assert frame.local_to_source((-200.0, 4200.0)) == (99.0, 221.0)
    assert frame.source_to_local((99.0, 221.0)) == (-200.0, 4200.0)


@pytest.mark.parametrize(
    "bounds,scale",
    [
        ((0.0, 0.0, 0.0, 1.0), 100.0),
        ((0.0, 2.0, 1.0, 1.0), 100.0),
        ((0.0, 0.0, inf, 1.0), 100.0),
        ((0.0, 0.0, nan, 1.0), 100.0),
        ((-1e308, 0.0, 1e308, 1.0), 100.0),
        ((0.0, 0.0, 1.0, 1.0), 0.0),
        ((0.0, 0.0, 1.0, 1.0), inf),
        ((0.0, 0.0, 1e308, 1.0), 1e-308),
    ],
)
def test_source_frame_rejects_unusable_extents(bounds: Any, scale: float) -> None:
    with pytest.raises(ValueError):
        LocalMetricFrame(bounds, scale)


def test_source_frame_rejects_nonfinite_points() -> None:
    frame = LocalMetricFrame((0.0, 0.0, 10.0, 10.0), 1000.0)
    with pytest.raises(ValueError, match="finite"):
        frame.source_to_local((nan, 0.0))
    with pytest.raises(ValueError, match="finite"):
        frame.local_to_source((0.0, inf))


def test_grid_extents_are_endpoint_positions_with_offset_independent_spacing() -> None:
    grid = EndpointGrid((-10.0, 20.0, 10.0, 30.0), 5, 3)
    x, y = grid_coordinates(grid)
    assert grid.shape == (3, 5)
    assert grid.registration == "endpoint-nodes"
    assert grid.x_spacing_km == 5.0
    assert grid.y_spacing_km == 5.0
    np.testing.assert_array_equal(x, [-10.0, -5.0, 0.0, 5.0, 10.0])
    np.testing.assert_array_equal(y, [20.0, 25.0, 30.0])


def test_grid_shape_uses_ties_to_even_rounding_and_stage_minimums() -> None:
    assert EndpointGrid.for_extent((0.0, 0.0, 5.0, 10.0), 5).shape == (5, 2)
    assert EndpointGrid.for_extent((0.0, 0.0, 7.0, 10.0), 5).shape == (5, 4)
    thin = (0.0, 0.0, 1000.0, 0.1)
    assert EndpointGrid.for_extent(thin, 768).shape == (2, 768)
    routed = EndpointGrid.for_extent(thin, 257, minimum_samples=3)
    assert routed.shape == (3, 257)
    assert routed.y_spacing_km == 0.05


@pytest.mark.parametrize("width,height", [(1, 2), (2, 0), (2.5, 3), (True, 3)])
def test_grid_rejects_invalid_sample_counts(width: Any, height: Any) -> None:
    with pytest.raises(ValueError, match="integer"):
        EndpointGrid((0.0, 0.0, 1.0, 1.0), width, height)


@pytest.mark.parametrize(
    "bounds",
    [
        (0.0, 0.0, 1.0, 0.0),
        (1.0, 0.0, 0.0, 1.0),
        (nan, 0.0, 1.0, 1.0),
    ],
)
def test_grid_rejects_invalid_extents(bounds: Any) -> None:
    with pytest.raises(ValueError):
        EndpointGrid(bounds, 3, 3)


def test_refinement_subdivides_intervals_without_moving_endpoints() -> None:
    coarse = EndpointGrid((-40.0, 120.0, 40.0, 160.0), 65, 33)
    fine = coarse.refined(2)
    assert fine.shape == (65, 129)
    assert fine.extent_km == coarse.extent_km
    assert fine.x_spacing_km == coarse.x_spacing_km / 2.0
    for parent_axis, child_axis in zip(
        grid_coordinates(coarse), grid_coordinates(fine), strict=True
    ):
        np.testing.assert_array_equal(parent_axis, child_axis[::2])
    assert coarse.refined(1) == coarse
    assert coarse.refined(3).shape == (97, 193)
    with pytest.raises(ValueError):
        coarse.refined(0)


def test_source_translation_preserves_local_terrain_and_constraints() -> None:
    points = ((0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0), (0.0, 0.0))
    source = Coastline(points, "original")
    moved = Coastline(tuple((x + 17.0, y + 720.0) for x, y in points), "translated")
    settings = TerrainSettings(resolution_px=65, seed=42)
    constraints = (ElevationPoint((0.5, 0.5), 1000.0, 100.0),)
    before = generate_terrain(source, settings, constraints=constraints)
    after = generate_terrain(moved, settings, constraints=constraints)
    assert before.elevation_m.tobytes() == after.elevation_m.tobytes()
    assert before.drainage.summary == after.drainage.summary
    assert before.grid == after.grid
    assert before.routing_grid == after.routing_grid


def test_shifted_grid_origin_preserves_rendered_slopes() -> None:
    coastline = Coastline(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)), "square")
    terrain = generate_terrain(coastline, TerrainSettings(resolution_px=65, seed=17))
    shifted = replace(terrain, x_km=terrain.x_km + 10000.0, y_km=terrain.y_km - 8000.0)
    assert shifted.grid.extent_km == (10000.0, -8000.0, 14000.0, -4000.0)
    assert shifted.grid.x_spacing_km == terrain.grid.x_spacing_km
    assert shifted.routing_grid.x_spacing_km == terrain.routing_grid.x_spacing_km
    for style in ("cartographic", "scientific"):
        with (
            render_height_map(terrain, style=style) as first,
            render_height_map(shifted, style=style) as second,
        ):
            assert first.tobytes() == second.tobytes()
