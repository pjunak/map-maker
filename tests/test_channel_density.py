"""Drainage density controls initiation while preserving routing and incision limits."""

from dataclasses import replace

import numpy as np
import pytest

from benchmarks.terrain import fixture
from map_maker.terrain.domain import TerrainSettings
from map_maker.terrain.pipeline.generate import generate_terrain
from map_maker.terrain.pipeline.hydrology import drainage_incision


@pytest.mark.parametrize("density", [0., .249, 2.001, float("nan"), float("inf")])
def test_density_requires_finite_supported_range(density: float) -> None:
    with pytest.raises(ValueError, match="Drainage density"):
        TerrainSettings(drainage_density=density)


def test_density_adds_connected_paths_without_changing_receivers_or_capture() -> None:
    rows, columns = np.indices((65, 65), dtype=np.float64)
    source = 2000.-12.*columns+1.1*(rows-32.)**2+30.*np.sin(rows/3.)
    land = np.ones(source.shape, dtype=np.bool_)
    coast = np.minimum.reduce((rows, columns, 64.-rows, 64.-columns))
    budgets = np.where(rows < 30, 35., 90.)
    terminals = np.zeros_like(land)
    terminals[32, 32] = True
    routings = [drainage_incision(
        source, land, coast, x_spacing_km=2., y_spacing_km=3.,
        maximum_elevation_m=4000., variability=.7, drainage_density=density,
        incision_budget_m=budgets, retention_terminal_mask=terminals,
    ) for density in (.25, .75, 1., 2.)]
    previous = np.zeros_like(land)
    for routing in routings:
        np.testing.assert_array_equal(routing.receivers, routings[0].receivers)
        np.testing.assert_array_equal(routing.accumulation_km2, routings[0].accumulation_km2)
        assert np.all(~previous | routing.channel_mask)
        assert np.count_nonzero(previous) < np.count_nonzero(routing.channel_mask)
        assert np.all(routing.incision_m <= budgets+1e-10)
        assert routing.incision_m[32, 32] == 0.
        assert routing.receivers[32, 32] == -1
        selected = routing.channel_mask & (routing.receivers >= 0)
        assert np.all(routing.channel_mask.ravel()[routing.receivers[selected]])
        previous = routing.channel_mask


@pytest.mark.parametrize("density", [.25, 2.])
def test_density_is_deterministic_across_output_resolutions(density: float) -> None:
    coast, settings, constraints = fixture("square", 65, 42)
    settings = replace(settings, drainage_density=density)
    first = generate_terrain(coast, settings, constraints=constraints)
    second = generate_terrain(coast, replace(settings, resolution_px=129), constraints=constraints)
    np.testing.assert_array_equal(first.elevation_m, second.elevation_m[::2, ::2])
    np.testing.assert_array_equal(first.routing.channel_mask, second.routing.channel_mask)
    np.testing.assert_array_equal(first.routing.receivers, second.routing.receivers)
