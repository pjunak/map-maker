# pyright: reportPrivateUsage=false
"""Attainable profiles must respect fixed nodes, source bounds and cut budgets."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray

from benchmarks.terrain import fixture
from map_maker.terrain.pipeline import generate as generation
from map_maker.terrain.pipeline.channel_floor import ChannelFloorReconstruction
from map_maker.terrain.pipeline.channel_profiles import (
    ChannelProfiles,
    attainable_targets,
    prepare_channel_profiles,
)
from map_maker.terrain.pipeline.reconstruction import BoundedBicubicGrid

type FloatArray = NDArray[np.float64]


def test_obstacles_and_unfillable_pits_propagate_in_opposite_directions() -> None:
    lower = np.array([[100., 80., 95., 60.], [100., 30., 35., 30.]])
    upper = np.array([[100., 110., 115., 60.], [100., 55., 80., 30.]])
    desired = np.array([[100., 87., 74., 60.], [100., 80., 60., 30.]])
    originals = [v.copy() for v in (lower, upper, desired)]
    targets = attainable_targets(lower, upper, desired)
    np.testing.assert_array_equal(targets, [[100., 95., 95., 60.], [100., 55., 55., 30.]])
    assert np.all(np.diff(targets, axis=1) <= 0.)
    assert np.all((targets >= lower) & (targets <= upper))
    for old, new in zip(originals, (lower, upper, desired), strict=True):
        np.testing.assert_array_equal(old, new)


def test_infeasible_pins_do_not_authorize_filling_or_extra_cutting() -> None:
    lower = np.array([[90., 50., 110., 80.]])
    upper = np.array([[90., 90., 140., 80.]])
    desired = np.linspace(90., 80., 4)[None, :]
    targets = attainable_targets(lower, upper, desired)
    ground = np.clip(targets, lower, upper)
    np.testing.assert_array_equal(ground, [[90., 90., 110., 80.]])
    assert np.max(ground-np.minimum.accumulate(ground, axis=1)) == 20.


@pytest.mark.parametrize("source,target", [(3, 4), (4, 3), (1, 4), (4, 1), (0, 4), (4, 0),
                                          (1, 3), (3, 1)])
def test_profiles_avoid_unnecessary_dips_before_blocked_crests_in_every_direction(
    source: int, target: int,
) -> None:
    axis = np.arange(3, dtype=np.float64)
    cut = np.full((3, 3), 40.)
    cap = np.full_like(cut, 80.)
    floors = np.full_like(cut, 180.)
    floors.ravel()[target] = 140.
    receivers = np.full((3, 3), -1, dtype=np.int64)
    receivers.ravel()[source] = target
    start = np.array([source % 3, source // 3])
    vector = np.array([target % 3, target // 3])-start
    calls: list[int] = []
    def sample(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray, NDArray[np.bool_]]:
        calls.append(x.size)
        t = ((x-start[0])*vector[0]+(y-start[1])*vector[1])/np.sum(vector*vector)
        macro = 220.-40.*t+120.*np.sin(np.pi*t)**2
        return macro, np.zeros_like(x), np.ones_like(x, dtype=np.bool_)
    field = ChannelFloorReconstruction.prepare(
        BoundedBicubicGrid(axis, axis, cut, cap), floors, receivers, receivers >= 0,
        np.ones_like(cut, dtype=np.bool_), sample_source=sample)
    assert field.profiles is not None and len(field.profiles.targets_m) == 1
    assert calls == [17]
    t = np.linspace(0., 1., 1025)
    x, y = start[0]+t*vector[0], start[1]+t*vector[1]
    macro, detail, _ = sample(x, y)
    original = np.full_like(t, 40.)
    revised = field.refine(x, y, original, macro, detail)
    previous = replace(field, profiles=None).refine(x, y, original, macro, detail)
    old, new = macro-previous, macro-revised
    old_rise = np.max(old-np.minimum.accumulate(old))
    new_rise = np.max(new-np.minimum.accumulate(new))
    assert new_rise < old_rise-1.
    assert np.all((revised >= 0.) & (revised <= 80.))
    np.testing.assert_array_equal(revised[[0, -1]], original[[0, -1]])
    np.testing.assert_array_equal(original, np.full_like(t, 40.))


@pytest.mark.parametrize("fault", ["nan", "inf", "negative", "shape"])
def test_bad_land_samples_fail_instead_of_becoming_clear(fault: str) -> None:
    axis = np.arange(3, dtype=np.float64)
    receivers = np.full((3, 3), -1, dtype=np.int64)
    receivers[1, 0] = 4
    def sample(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray, NDArray[np.bool_]]:
        value = {"nan": np.nan, "inf": np.inf, "negative": -1., "shape": 200.}[fault]
        macro = np.full_like(x, value)
        return (macro[:, 0] if fault == "shape" else macro), x*0, np.ones_like(x, dtype=np.bool_)
    with pytest.raises(ValueError, match="Channel sampler"):
        ChannelFloorReconstruction.prepare(
            BoundedBicubicGrid(axis, axis, np.full((3, 3), 40.), np.full((3, 3), 80.)),
            np.full((3, 3), 160.), receivers, receivers >= 0,
            np.ones((3, 3), dtype=np.bool_), sample_source=sample)


def test_unavailable_interior_omits_the_complete_profile() -> None:
    axis = np.arange(3, dtype=np.float64)
    receivers = np.full((3, 3), -1, dtype=np.int64)
    receivers[1, 0] = 4
    def sample(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray, NDArray[np.bool_]]:
        available = np.ones_like(x, dtype=np.bool_)
        available[:, 8] = False
        return np.full_like(x, 300.), x*0, available
    field = ChannelFloorReconstruction.prepare(
        BoundedBicubicGrid(axis, axis, np.full((3, 3), 40.), np.full((3, 3), 80.)),
        np.full((3, 3), 160.), receivers, receivers >= 0,
        np.ones((3, 3), dtype=np.bool_), sample_source=sample)
    assert field.profiles is not None and field.profiles.targets_m.shape == (0, 17)
    assert np.all(field.profiles.edge_ids == -1)


def test_sparse_cubic_profiles_are_bounded_owned_and_query_order_independent() -> None:
    values = np.array([np.linspace(200., 100., 17), np.linspace(100., 200., 17)**1.1])
    ids = np.full((4, 3, 3), -1, dtype=np.int32)
    ids[0, 1, 0], ids[1, 0, 1] = 0, 1
    field = ChannelProfiles(ids, values)
    ids[:] = -1
    values[:] = 0.
    assert not field.targets_m.flags.writeable and not field.edge_ids.flags.writeable
    t = np.linspace(0., 1., 1025)
    rows, columns = np.ones_like(t, dtype=np.int64), np.zeros_like(t, dtype=np.int64)
    baseline = np.full_like(t, 50.)
    result = field.sample(0, rows, columns, t, baseline)
    np.testing.assert_allclose(result, 200.-100.*t, atol=1e-12)
    np.testing.assert_array_equal(field.sample(0, rows, columns, t[::-1], baseline), result[::-1])
    chunks = [field.sample(0, rows[a:a+19], columns[a:a+19], t[a:a+19], baseline[a:a+19])
              for a in range(0, len(t), 19)]
    np.testing.assert_array_equal(np.concatenate(chunks), result)
    np.testing.assert_array_equal(field.sample(3, rows, columns, t, baseline), baseline)
    increasing = field.sample(1, columns, rows, t, baseline)
    knots = field.targets_m[1]
    index = np.minimum((t*16).astype(np.int64), 15)
    assert np.all(np.diff(increasing) >= 0.)
    assert np.all((increasing >= knots[index]) & (increasing <= knots[index+1]))
    for knot in (.25, .5, .75):
        h = 1e-5
        positions = np.array([knot-h, knot, knot+h])
        samples = field.sample(1, np.zeros(3, dtype=np.int64), np.ones(3, dtype=np.int64),
                               positions, np.zeros(3))
        assert abs((samples[1]-samples[0])/h-(samples[2]-samples[1])/h) < .01


def test_regional_regression_keeps_canonical_ground_and_preparation_is_batch_independent() -> None:
    coast, settings, constraints = fixture("regional", 257, 7)
    field = generation.prepare_terrain_field(coast, settings, constraints, None)
    valley = field.automatic_valleys
    floor = valley.floor
    assert floor.profiles is not None
    x = np.linspace(float(valley.x_km[192]), float(valley.x_km[193]), 1025)
    y = np.linspace(float(valley.y_km[38]), float(valley.y_km[37]), 1025)
    heights = field.sample_ground(x, y).astype(np.float64)
    xx, yy = np.meshgrid(valley.x_km, valley.y_km)
    canonical = field.sample_ground(xx, yy)
    unprofiled = replace(valley, floor=replace(floor, profiles=None))
    original = replace(field, automatic_valleys=unprofiled)
    plain = original.sample_ground(x, y).astype(np.float64)
    # This cut-limited crest still climbs; its old 52 m baseline belonged to
    # the superseded normalized-noise field. Check the reconstruction contract
    # on the current source instead of granting an arbitrary larger tolerance.
    assert floor.profiles.edge_ids[3, 38, 192] >= 0
    assert np.max(heights - plain) > 1.
    assert (np.max(heights - np.minimum.accumulate(heights))
            <= np.max(plain - np.minimum.accumulate(plain)) + .01)
    np.testing.assert_array_equal(heights[[0, -1]], plain[[0, -1]])
    np.testing.assert_array_equal(canonical, original.sample_ground(xx, yy))
    calls: list[int] = []
    def sample(qx: FloatArray, qy: FloatArray) -> tuple[FloatArray, FloatArray, NDArray[np.bool_]]:
        calls.append(qx.size)
        return 1000.+200.*np.sin(qx/10), qx*0, np.ones_like(qx, dtype=np.bool_)
    args = (floor.incision, floor.floor_m, valley.drainage.receivers,
            floor.horizontal, floor.vertical, floor.diagonals, sample)
    small = prepare_channel_profiles(*args, batch_edges=7)
    assert max(calls) <= 7*17
    large = prepare_channel_profiles(*args)
    np.testing.assert_array_equal(small.edge_ids, large.edge_ids)
    np.testing.assert_array_equal(small.targets_m, large.targets_m)


@pytest.mark.parametrize("case", ["no_edges", "uphill"])
def test_unselected_or_uphill_pins_do_not_request_source_profiles(case: str) -> None:
    axis = np.arange(3, dtype=np.float64)
    receivers = np.full((3, 3), -1, dtype=np.int64)
    if case == "uphill":
        receivers[1, 0] = 4
    floors = np.full((3, 3), 160.)
    floors[1, 0] = 150.
    def unused(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray, NDArray[np.bool_]]:
        raise AssertionError("Unavailable or uphill edges should need no source observations")
    result = ChannelFloorReconstruction.prepare(
        BoundedBicubicGrid(axis, axis, np.full((3, 3), 40.), np.full((3, 3), 80.)),
        floors, receivers, receivers >= 0, np.ones((3, 3), dtype=np.bool_), sample_source=unused)
    assert result.profiles is not None and result.profiles.targets_m.size == 0
