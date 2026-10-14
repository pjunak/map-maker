"""Analytical edge contexts stay separate from changes to authored terrain."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray

from map_maker.terrain.pipeline.diagnostics import (
    CUT_LIMIT,
    DEPRESSION,
    FINAL_ADJUSTMENT,
    REGION_TRANSITION,
    UPHILL,
    review_drainage_routing,
)
from map_maker.terrain.pipeline.hydrology import DrainageIncision, drainage_incision


def _edge(source: NDArray[np.float64], allowance: float = 100) -> DrainageIncision:
    land = np.ones(source.shape, dtype=np.bool_)
    routing = drainage_incision(source, land, np.ones_like(source),
        x_spacing_km=1, y_spacing_km=1, maximum_elevation_m=1000, variability=0.5)
    receivers = np.full(source.shape, -1, dtype=np.int64)
    receivers[2, 2] = 13  # (2, 2) -> (2, 3), independent of alternative downhill paths.
    return replace(routing, receivers=receivers, channel_mask=receivers >= 0,
                   incision_m=np.zeros_like(source),
                   incision_limit_m=np.full_like(source, allowance))


def test_depression_context_uses_finished_unfilled_terrain_without_mutation() -> None:
    surface = np.full((5, 5), 100., dtype=np.float64)
    surface[2, 2:4] = [10, 20]
    original = surface.copy()
    routing = _edge(surface)
    receivers = routing.receivers.copy()
    review = review_drainage_routing(routing, surface, np.ones_like(surface, bool),
                                               x_spacing_km=1, y_spacing_km=1)
    (agreement, context) = review.agreement, review.conflicts
    assert context.flags[2, 2] == UPHILL | DEPRESSION
    assert context.final_fill_depth_m[2, 2] == pytest.approx(90)
    assert context.summary.depression_edge_count == agreement.uphill_channel_edge_count == 1
    assert context.summary.insufficient_cut_edge_count == 0
    assert context.summary.final_adjustment_edge_count == 0
    np.testing.assert_array_equal(surface, original)
    np.testing.assert_array_equal(routing.receivers, receivers)
    np.testing.assert_array_equal(routing.incision_m, 0)


def test_cut_deficit_uses_receiver_allowance_and_contexts_overlap() -> None:
    surface = np.zeros((5, 5), dtype=np.float64)
    surface[2, 2:4] = [10, 30]
    routing = _edge(surface)
    limits = routing.incision_limit_m.copy()
    limits[2, 3] = 7
    routing = replace(routing, incision_limit_m=limits)
    transition = np.zeros_like(surface, dtype=np.bool_)
    transition[2, 3] = True
    review = review_drainage_routing(routing, surface, np.ones_like(surface, bool),
        x_spacing_km=1, y_spacing_km=1, region_transition_mask=transition)
    (_, context) = review.agreement, review.conflicts
    assert context.flags[2, 2] == UPHILL | CUT_LIMIT | REGION_TRANSITION
    assert context.receiver_cut_deficit_m[2, 2] == 13
    assert context.summary.maximum_cut_deficit_m == 13
    assert context.summary.depression_edge_count == 0
    assert context.summary.insufficient_cut_edge_count == 1
    assert context.summary.region_transition_edge_count == 1
    assert context.summary.uphill_edge_count == 1


def test_final_adjustment_measures_edge_slope_change_not_receiver_height_alone() -> None:
    source = np.zeros((5, 5), dtype=np.float64)
    source[2, 2:4] = [30, 10]
    routing = _edge(source)
    final = source.copy()
    final[2, 2:4] = [20, 40]
    review = review_drainage_routing(routing, final, np.ones_like(final, bool),
                                       x_spacing_km=1, y_spacing_km=1)
    (_, context) = review.agreement, review.conflicts
    assert context.flags[2, 2] == UPHILL | FINAL_ADJUSTMENT
    assert context.final_adjustment_rise_m[2, 2] == 40
    assert context.rise_m[2, 2] == 20
    assert context.summary.final_adjustment_edge_count == 1


def test_unclassified_rise_remains_visible_instead_of_forcing_a_cause() -> None:
    surface = np.zeros((5, 5), dtype=np.float64)
    surface[2, 2:4] = [10, 20]
    review = review_drainage_routing(_edge(surface), surface, np.ones_like(surface, bool),
                                       x_spacing_km=1, y_spacing_km=1)
    (_, context) = review.agreement, review.conflicts
    assert context.flags[2, 2] == UPHILL
    assert context.summary.unclassified_edge_count == 1


@pytest.mark.parametrize("receiver_height", [5., 10., 10.0005])
def test_downhill_flat_and_subtolerance_edges_do_not_get_conflict_flags(
    receiver_height: float,
) -> None:
    surface = np.zeros((5, 5), dtype=np.float64)
    surface[2, 2:4] = [10, receiver_height]
    review = review_drainage_routing(_edge(surface, 0), surface, np.ones_like(surface, bool),
                                       x_spacing_km=1, y_spacing_km=1)
    (_, context) = review.agreement, review.conflicts
    np.testing.assert_array_equal(context.flags, 0)
    np.testing.assert_array_equal(context.receiver_cut_deficit_m, 0)
    assert context.summary.uphill_edge_count == 0


def test_review_masks_ocean_nodata_and_has_no_terminal_conflicts() -> None:
    surface = np.zeros((5, 5), dtype=np.float64)
    routing = _edge(surface)
    routing = replace(routing, receivers=np.full((5, 5), -1, dtype=np.int64))
    land = np.ones((5, 5), dtype=np.bool_)
    land[0] = False
    surface[0] = np.nan
    review = review_drainage_routing(routing, surface, land,
                                       x_spacing_km=1, y_spacing_km=1)
    (_, context) = review.agreement, review.conflicts
    assert np.isfinite(context.final_fill_depth_m).all()
    np.testing.assert_array_equal(context.flags, 0)
    np.testing.assert_array_equal(context.final_fill_depth_m[~land], 0)


def test_review_rejects_invalid_receivers_and_nonfinite_land() -> None:
    surface = np.zeros((5, 5), dtype=np.float64)
    routing = _edge(surface)
    land = np.ones_like(surface, dtype=np.bool_)
    bad = routing.receivers.copy()
    bad[2, 2] = 25
    with pytest.raises(ValueError, match="valid flat indices"):
        review_drainage_routing(replace(routing, receivers=bad), surface, land,
                               x_spacing_km=1, y_spacing_km=1)
    surface[2, 2] = np.nan
    with pytest.raises(ValueError, match="finite"):
        review_drainage_routing(routing, surface, land, x_spacing_km=1, y_spacing_km=1)
