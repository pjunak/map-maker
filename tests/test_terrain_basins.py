"""Analytical depression geometry, escape routes and boundary semantics."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray

from map_maker.terrain.domain import Coastline, TerrainSettings
from map_maker.terrain.pipeline.basins import (
    ENCLOSED_BOUNDARY,
    ENCLOSED_WATER,
    EXTERIOR_BOUNDARY,
    EXTERIOR_WATER,
    boundary_context,
)
from map_maker.terrain.pipeline.diagnostics import DrainageAnalysis, analyze_drainage
from map_maker.terrain.pipeline.generate import generate_terrain


def _analyze(surface: NDArray[np.float64]) -> DrainageAnalysis:
    return analyze_drainage(surface, np.isfinite(surface), x_spacing_km=2, y_spacing_km=3)


def _bowl() -> NDArray[np.float64]:
    surface = np.zeros((9, 9), dtype=np.float64)
    surface[1:-1, 1:-1] = 10
    surface[3:6, 3:6] = -5
    surface[2, 4], surface[1, 4] = 4, 3
    return surface


def test_bowl_extent_and_spill_match_known_saddle_without_mutating_terrain() -> None:
    surface = _bowl()
    original = surface.copy()
    result = _analyze(surface)
    summary = result.summary
    assert summary.basin_candidate_count == 1
    basin = summary.basin_candidates[0]
    expected = np.zeros(surface.shape, dtype=np.uint32)
    expected[3:6, 3:6] = 1
    np.testing.assert_array_equal(result.basin_labels, expected)
    np.testing.assert_array_equal(surface, original)
    assert basin.basin_id == 1
    assert basin.cell_count == 9
    assert basin.area_km2 == 54
    assert basin.maximum_fill_depth_m == pytest.approx(9)
    assert basin.fill_volume_km3 == pytest.approx(0.486)
    assert basin.outlet.spill_flat_index == 2 * 9 + 4
    assert basin.outlet.spill_elevation_m == 4
    assert basin.floor_elevation_m == -5
    assert result.basin_labels.flat[basin.outlet.source_flat_index] == 1
    assert result.basin_labels.flat[basin.outlet.receiver_flat_index] == 0
    assert result.receivers.flat[basin.outlet.source_flat_index] == (
        basin.outlet.receiver_flat_index
    )


def test_equal_saddles_are_deterministic_and_multiple_extent_exits_are_counted() -> None:
    surface = _bowl()
    surface[2, 4] = 10
    surface[2, 2], surface[2, 6] = 4, 4
    surface[1, 1], surface[1, 7] = 3, 3
    first, second = _analyze(surface), _analyze(surface.copy())
    assert first.summary == second.summary
    np.testing.assert_array_equal(first.basin_labels, second.basin_labels)
    np.testing.assert_array_equal(first.receivers, second.receivers)
    basin = first.summary.basin_candidates[0]
    assert basin.outlet.spill_elevation_m == 4
    assert basin.exit_edge_count >= 2
    component = np.flatnonzero(first.basin_labels == basin.basin_id)
    targets = first.receivers.ravel()[component]
    assert basin.exit_edge_count == np.count_nonzero(
        first.basin_labels.ravel()[targets] != basin.basin_id
    )


def test_escape_routes_are_strict_and_report_actual_path_peaks_and_terminals() -> None:
    # Irregular terrain catches disconnected extents, ranking and multi-step escapes.
    surface = np.random.default_rng(918).uniform(-30, 30, size=(21, 27))
    result = _analyze(surface)
    assert result.summary.basin_candidate_count > 5
    assert result.basin_labels.dtype == np.uint32
    assert set(np.unique(result.basin_labels)) == set(
        range(result.summary.basin_candidate_count + 1)
    )
    for basin in result.summary.basin_candidates:
        index = basin.deepest_flat_index
        path = [index]
        while result.receivers.flat[index] >= 0:
            receiver = int(result.receivers.flat[index])
            assert result.filled_elevation_m.flat[receiver] < result.filled_elevation_m.flat[index]
            assert receiver not in path
            path.append(receiver)
            index = receiver
        outlet = basin.outlet
        assert path[-1] == outlet.terminal_flat_index
        assert outlet.boundary_flags == result.boundary_flags.flat[path[-1]] != 0
        assert outlet.source_flat_index in path
        assert outlet.spill_flat_index in path
        escape = path[path.index(outlet.source_flat_index):]
        assert outlet.spill_elevation_m == max(surface.flat[node] for node in escape)
        # Choose the nearest exact maximum on the representative route.
        assert outlet.spill_flat_index == next(
            node for node in escape if surface.flat[node] == outlet.spill_elevation_m
        )
        component = result.basin_labels == basin.basin_id
        assert basin.cell_count == np.count_nonzero(component)
        assert basin.floor_elevation_m == surface[component].min()
        assert surface.flat[basin.floor_flat_index] == basin.floor_elevation_m


def test_enclosed_water_is_identified_without_inventing_a_lake_level() -> None:
    surface = np.full((11, 11), 20., dtype=np.float64)
    surface[5, 5] = np.nan
    surface[5, 3], surface[5, 4] = 0, 5
    result = _analyze(surface)
    assert result.nonland_class[5, 5] == ENCLOSED_WATER
    basin = result.summary.basin_candidates[0]
    assert basin.outlet.terminal_flat_index == 5 * 11 + 4
    assert basin.outlet.boundary_flags == ENCLOSED_BOUNDARY
    assert basin.outlet.spill_elevation_m == 5
    assert result.basin_labels[5, 5] == result.fill_depth_m[5, 5] == 0
    assert result.receivers[5, 5] == -1
    assert np.isnan(surface[5, 5])


def test_water_classification_uses_d8_connectivity_and_overlapping_boundary_flags() -> None:
    land = np.ones((7, 7), dtype=np.bool_)
    land[0, 0] = land[1, 1] = land[2, 2] = land[4, 4] = False
    original = land.copy()
    water, flags = boundary_context(land)
    assert water[2, 2] == EXTERIOR_WATER
    assert water[4, 4] == ENCLOSED_WATER
    assert flags[3, 3] == EXTERIOR_BOUNDARY | ENCLOSED_BOUNDARY
    np.testing.assert_array_equal(flags[~land], 0)
    np.testing.assert_array_equal(water[land], 0)
    np.testing.assert_array_equal(land, original)


@pytest.mark.parametrize("height", [0., -0.005])
def test_flat_or_subtolerance_land_does_not_become_a_lake_candidate(height: float) -> None:
    surface = np.zeros((7, 7), dtype=np.float64)
    surface[3, 3] = height
    result = _analyze(surface)
    assert result.summary.basin_candidate_count == 0
    np.testing.assert_array_equal(result.basin_labels, 0)


def test_no_land_has_no_basins_and_preserves_nodata() -> None:
    surface = np.full((4, 5), np.nan, dtype=np.float64)
    result = _analyze(surface)
    assert result.summary.land_cell_count == result.summary.basin_candidate_count == 0
    np.testing.assert_array_equal(result.nonland_class, EXTERIOR_WATER)
    np.testing.assert_array_equal(result.boundary_flags, 0)
    np.testing.assert_array_equal(result.receivers, -1)


@pytest.mark.parametrize("name,value", [
    ("x_spacing_km", 0), ("y_spacing_km", np.nan), ("x_spacing_km", np.inf),
    ("fill_tolerance_m", np.nan), ("fill_tolerance_m", -1),
])
def test_analysis_rejects_invalid_metric_inputs(name: str, value: float) -> None:
    args = {"x_spacing_km": 1., "y_spacing_km": 1., "fill_tolerance_m": .01, name: value}
    with pytest.raises(ValueError, match="finite"):
        analyze_drainage(np.zeros((3, 3)), np.ones((3, 3), bool), **args)


def test_generated_basins_share_the_routing_grid_and_survive_output_resolution_changes() -> None:
    coast = Coastline(((0., 0.), (100., 0.), (100., 100.), (0., 100.), (0., 0.)), "square.svg")
    settings = TerrainSettings(seed=42, resolution_px=65)
    first = generate_terrain(coast, settings)
    second = generate_terrain(coast, replace(settings, resolution_px=129))
    assert first.drainage.summary == second.drainage.summary
    assert first.drainage.basin_labels.shape == first.routing_grid_shape == (257, 257)
    assert first.drainage.summary.grid_width == first.routing_grid.width
    assert first.drainage.summary.grid_height == first.routing_grid.height
    for name in ("basin_labels", "filled_elevation_m", "receivers", "fill_depth_m",
                 "nonland_class", "boundary_flags"):
        np.testing.assert_array_equal(getattr(first.drainage, name), getattr(second.drainage, name))
    np.testing.assert_array_equal(first.drainage.fill_depth_m,
                                  first.routing_conflicts.final_fill_depth_m)
