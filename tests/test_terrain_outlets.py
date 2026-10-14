"""Outlet evidence must inspect the unfilled ground and vector route geometry."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Polygon

from map_maker.terrain.domain import TerrainBasin
from map_maker.terrain.pipeline.outlets import review_outlet_routes
from map_maker.terrain.pipeline.water import basin_intent_ids, prepare_basins


@pytest.mark.parametrize("case,expected", [
    ("clear", None),
    ("offgrid", None),
    ("unresolved", "outlet_attachment_unresolved"),
    ("uphill", "outlet_route_uphill"),
    ("cumulative", "outlet_downstream_uphill"),
    ("tolerated", None),
    ("downstream_budget", "outlet_downstream_unresolved"),
    ("high_outlet", "outlet_above_water"),
    ("no_water", "outlet_without_sampled_water"),
    ("reentry", "outlet_route_enters_basin"),
    ("cycle", "outlet_route_cycle"),
    ("invalid", "outlet_route_invalid_receiver"),
    ("interior", "outlet_route_interior_terminal"),
    ("hole_terminal", "outlet_terminal_level_unknown"),
    ("raster_terminal", "outlet_terminal_level_unknown"),
    ("vector_hole", "outlet_route_crosses_nonland"),
    ("tiny_basin", "outlet_route_enters_basin"),
])
def test_outlet_route_evidence(
    case: str, expected: str | None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if case == "downstream_budget":
        monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.MAX_PROFILE_SAMPLES", 8)
    axis = np.arange(9, dtype=np.float64)
    x, y = np.meshgrid(axis, axis)
    land_geometry = Polygon(((1, 1), (7, 1), (7, 7), (1, 7)))
    lake = TerrainBasin(((.25, .25), (.5, .25), (.5, .75), (.25, .75), (.25, .25)),
                        "lake", 10, (.5, .5))
    if case == "offgrid":
        lake = replace(lake, outlet=(.5, .55))
    elif case == "unresolved":
        lake = replace(lake,
            points=((.125, .125), (.875, .125), (.875, .875), (.125, .875), (.125, .125)),
            outlet=(.875, .5))
    tiny = TerrainBasin(((.67, .49), (.70, .49), (.70, .51), (.67, .51), (.67, .49)),
                        "dry_basin")
    if case == "vector_hole":
        land_geometry = Polygon(land_geometry.exterior,
            holes=[((5.4, 3.9), (5.6, 3.9), (5.6, 4.1), (5.4, 4.1))])
    basins = prepare_basins((lake, tiny) if case == "tiny_basin" else (lake,),
                            8, 8, land_geometry, 100)
    ids = basin_intent_ids(x, y, basins)
    land = (x >= 1) & (x <= 7) & (y >= 1) & (y <= 7)
    ground = np.full((9, 9), 20., dtype=np.float64)
    ground[ids > 0] = 2
    ground[4, 5:8] = [9, 8, 7]
    receivers = np.full((9, 9), -1, dtype=np.int64)
    receivers[4, 5:7] = [4 * 9 + 6, 4 * 9 + 7]
    flags = np.zeros((9, 9), dtype=np.uint8)
    flags[4, 7] = 2
    outlet_height = 10.
    if case == "uphill":
        ground[4, 6] = 15
    elif case in ("cumulative", "tolerated"):
        ground[4, 6] = 8.008 if case == "cumulative" else 8.0045
    elif case == "high_outlet":
        outlet_height = 20
    elif case == "no_water":
        ground[ids > 0] = 20
    elif case == "reentry":
        receivers[4, 5] = 4 * 9 + 4
    elif case == "cycle":
        receivers[4, 6] = 4 * 9 + 5
    elif case == "invalid":
        receivers[4, 6] = 90
    elif case == "interior":
        receivers[4, 6] = -1
    elif case in ("hole_terminal", "raster_terminal"):
        flags[4, 7] = 4 if case == "hole_terminal" else 1
    def sample_ground(xx: NDArray[np.float64], yy: NDArray[np.float64]) -> NDArray[np.float32]:
        # Explicit continuous downstream ground agrees with its canonical samples.
        values = np.full(xx.shape, 2., dtype=np.float32)
        downstream = (xx >= 5) & (yy == 4)
        values[downstream] = np.interp(xx[downstream], axis[5:8], ground[4, 5:8])
        if case in ("cumulative", "tolerated"):
            peak = 8.016 if case == "cumulative" else 8.009
            values[downstream] = np.interp(xx[downstream], (5., 5.5, 6.5, 7.), (9., 8., peak, 7.))
        assert basins[-1].outlet_km is not None
        ox, oy = basins[-1].outlet_km
        values[(xx == ox) & (yy == oy)] = outlet_height
        return values

    original = ground.copy()
    heights = tuple(outlet_height if item.outlet_km is not None else None for item in basins)
    results = review_outlet_routes(basins, ids, ground, land, receivers, flags,
                                   axis, axis, land_geometry, heights, sample_ground)
    result = results[-1]
    assert result is not None
    if expected is None:
        assert result.status == "sampled_clear"
        assert result.path_flat_indices == (41, 42, 43)
        expected_length = np.hypot(1, .4) + 2 if case == "offgrid" else 3
        assert result.length_km == pytest.approx(expected_length)
        assert result.uphill_edge_count == 0
        assert result.terminal_flat_index == 43
        assert result.issues == ()
    else:
        assert result.status == ("unresolved" if case == "unresolved" else "blocked")
        assert expected in result.issues
    if case == "uphill":
        assert result.maximum_rise_m == 6
        assert result.maximum_height_above_water_m == 5
        assert result.uphill_edge_count == 1
    if result.downstream is not None:
        evidence = result.downstream
        assert evidence.reaches_terminal == (result.terminal_flat_index is not None)
        if case == "downstream_budget":
            assert result.connection_profile is not None
            assert result.connection_profile.status == "sampled"
            assert evidence.profile.status == "budget_exceeded"
            assert evidence.profile.requested_sample_count == 9
            assert evidence.profile.positions_km == evidence.path_vertex_sample_indices == ()
            assert evidence.maximum_uphill_excursion_m is None
        else:
            assert evidence.profile.status == "sampled"
        for node, sample in zip(result.path_flat_indices if case != "downstream_budget" else (),
                                evidence.path_vertex_sample_indices, strict=True):
            assert evidence.profile.ground_m[sample] == np.float32(ground.ravel()[node])
    if case == "cumulative":
        assert result.uphill_edge_count == 0
        assert result.downstream is not None
        assert result.downstream.maximum_uphill_excursion_m == pytest.approx(.016, abs=1e-6)
        assert np.max(np.diff(result.downstream.profile.ground_m)) < .01
    np.testing.assert_array_equal(ground, original)
    assert results == review_outlet_routes(basins, ids, ground, land, receivers, flags,
                                           axis, axis, land_geometry, heights, sample_ground)
    # A closed lake supplies no outlet route, regardless of the candidate graph.
    closed = (replace(basins[-1], source=replace(lake, outlet=None), outlet_km=None),)
    assert review_outlet_routes(closed, ids, ground, land, receivers, flags,
                                axis, axis, land_geometry, (None,), sample_ground) == (None,)
