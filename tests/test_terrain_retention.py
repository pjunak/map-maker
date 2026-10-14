"""Absorbing authored footprints conserve area without modifying ground."""

import numpy as np
import pytest

from map_maker.terrain.pipeline.hydrology import (
    drainage_incision,
    multiple_flow_accumulation,
    priority_flood_surface,
    steepest_flow_accumulation,
    steepest_flow_receivers,
)


@pytest.mark.parametrize("flat", [False, True])
def test_retention_seeds_stop_both_flow_models_and_conserve_area(flat: bool) -> None:
    y, x = np.mgrid[:11, :13]
    ground = (np.zeros_like(x) if flat else (x - 6)**2 + (y - 5)**2).astype(np.float64)
    original = ground.copy()
    land = np.ones_like(ground, dtype=bool)
    terminal = np.zeros_like(land)
    terminal[4:7, 5:8] = True
    routed = priority_flood_surface(ground, land, terminal_mask=terminal)
    receivers, _ = steepest_flow_receivers(routed, land, x_spacing_km=2, y_spacing_km=3,
                                          terminal_mask=terminal)
    sinks = land & (receivers < 0)
    np.testing.assert_array_equal(receivers[terminal], -1)
    np.testing.assert_array_equal(routed[terminal], ground[terminal])
    for accumulate in (multiple_flow_accumulation, steepest_flow_accumulation):
        area, slope = accumulate(routed, land, x_spacing_km=2, y_spacing_km=3,
                                 terminal_mask=terminal)
        assert area[sinks].sum() == pytest.approx(land.sum() * 6)
        assert area[terminal].sum() >= terminal.sum() * 6
        np.testing.assert_array_equal(slope[terminal], 0)
    np.testing.assert_array_equal(ground, original)


def test_retention_stops_preexisting_downhill_flow_in_both_models() -> None:
    ground = np.tile(np.arange(9, 0, -1, dtype=np.float64), (5, 1))
    land = np.ones_like(ground, dtype=bool)
    terminals = np.zeros_like(land)
    terminals[:, 4] = True
    for accumulate in (multiple_flow_accumulation, steepest_flow_accumulation):
        area, _ = accumulate(ground, land, x_spacing_km=1, y_spacing_km=1,
                             terminal_mask=terminals)
        assert area[terminals].sum() == pytest.approx(25)
        assert area[:, -1].sum() == pytest.approx(20)


def test_retention_is_terminal_even_with_no_cut_budget_supplied() -> None:
    ground = np.full((9, 9), 1000., dtype=np.float64)
    land = np.ones_like(ground, dtype=bool)
    terminals = np.zeros_like(land)
    terminals[3:6, 3:6] = True
    result = drainage_incision(ground, land, np.full_like(ground, 100), x_spacing_km=1,
                              y_spacing_km=1, maximum_elevation_m=6000, variability=.5,
                              retention_terminal_mask=terminals)
    for values in (result.incision_m, result.incision_limit_m, result.detail_suppression):
        np.testing.assert_array_equal(values[terminals], 0)
    np.testing.assert_array_equal(result.receivers[terminals], -1)
    assert np.all(result.outlet_mask[terminals])


@pytest.mark.parametrize("off_land", [False, True])
def test_invalid_retention_grids_are_rejected(off_land: bool) -> None:
    ground = np.ones((3, 3), dtype=np.float64)
    land = np.ones_like(ground, dtype=bool)
    land[0, 0] = False
    terminals = np.ones((3, 3) if off_land else (2, 2), dtype=bool)
    with pytest.raises(ValueError, match="Retention terminals"):
        priority_flood_surface(ground, land, terminal_mask=terminals)
