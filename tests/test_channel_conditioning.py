"""Network floor feasibility, confluences and bounded cut recovery."""

import numpy as np
import pytest
from numpy.typing import NDArray

from map_maker.terrain.pipeline.hydrology import condition_channel_floors


def test_downstream_limits_recover_cuts_across_the_complete_chain() -> None:
    source = np.array([[100., 95., 90.]])
    incision = np.array([[30., 0., 0.]])
    ceiling = np.array([[30., 5., 0.]])
    result, correction, unresolved = condition_channel_floors(
        source, incision, ceiling, np.ones((1, 3), dtype=np.bool_),
        np.array([[1, 2, -1]], dtype=np.int64), np.array([[3., 2., 1.]]), minimum_drop_m=1.)
    np.testing.assert_array_equal(source-result, [[92., 91., 90.]])
    np.testing.assert_array_equal(correction, [[-22., 4., 0.]])
    np.testing.assert_array_equal(incision+correction, result)
    assert unresolved == 0
    np.testing.assert_array_equal(incision, [[30., 0., 0.]])
    np.testing.assert_array_equal(ceiling, [[30., 5., 0.]])


def test_confluence_constraints_are_independent_of_tributary_storage_order() -> None:
    source = np.array([[140., 120., 130., 100.]])
    incision = np.array([[70., 40., 0., 0.]])
    ceiling = np.array([[70., 40., 40., 0.]])
    receivers = np.array([[2, 2, 3, -1]], dtype=np.int64)
    routing = np.array([[4., 4., 2., 1.]])
    channels = np.ones((1, 4), dtype=np.bool_)
    result, _, unresolved = condition_channel_floors(
        source, incision, ceiling, channels, receivers, routing, minimum_drop_m=1.)
    np.testing.assert_array_equal(source-result, [[102., 102., 101., 100.]])
    assert unresolved == 0
    permutation = np.array([3, 1, 0, 2])
    inverse = np.argsort(permutation)
    reordered_receivers = receivers[:, permutation].copy()
    linked = reordered_receivers >= 0
    reordered_receivers[linked] = inverse[reordered_receivers[linked]]
    reordered, _, _ = condition_channel_floors(
        source[:, permutation], incision[:, permutation], ceiling[:, permutation], channels,
        reordered_receivers, routing[:, permutation], minimum_drop_m=1.)
    np.testing.assert_array_equal(reordered[:, inverse], result)


def test_uncut_source_pit_limits_downstream_floor_without_being_filled() -> None:
    source = np.array([[120., 75., 100., 40.]])
    result, _, unresolved = condition_channel_floors(
        source, np.zeros((1, 4)), np.array([[100., 60., 40., 0.]]),
        np.ones((1, 4), dtype=np.bool_), np.array([[1, 2, 3, -1]], dtype=np.int64),
        np.array([[4., 3., 2., 1.]]), minimum_drop_m=1.)
    np.testing.assert_array_equal(source-result, [[120., 75., 74., 40.]])
    assert unresolved == 0


def test_infeasible_network_reports_conflict_and_retains_source_and_cut_limits() -> None:
    source = np.array([[80., 120., 70., 500.]])
    incision = np.array([[20., 10., 0., 50.]])
    result, correction, unresolved = condition_channel_floors(
        source, incision, np.array([[20., 10., 0., 60.]]),
        np.array([[True, True, True, False]]), np.array([[1, 2, -1, -1]], dtype=np.int64),
        np.array([[3., 2., 1., 0.]]), minimum_drop_m=1.)
    np.testing.assert_array_equal(source-result, [[80., 110., 70., 450.]])
    np.testing.assert_array_equal(correction, [[-20., 0., 0., 0.]])
    assert unresolved == 1


@pytest.mark.parametrize("empty", [False, True])
def test_satisfied_or_empty_network_needs_no_correction(empty: bool) -> None:
    incision = np.array([[5., 7., 12.]])
    result, correction, unresolved = condition_channel_floors(
        np.array([[120., 100., 80.]]), incision, np.array([[60., 30., 20.]]),
        np.full((1, 3), not empty, dtype=np.bool_), np.array([[1, 2, -1]], dtype=np.int64),
        np.array([[3., 2., 1.]]))
    np.testing.assert_array_equal(result, incision)
    assert not np.any(correction) and unresolved == 0
    assert not np.shares_memory(result, incision)


def test_feasible_branching_networks_satisfy_every_nodal_interval_and_edge() -> None:
    rng = np.random.default_rng(28101)
    shape = (4, 8)
    for _ in range(30):
        known_floor = (200.-2.*np.arange(32)).reshape(shape)
        source = known_floor+rng.uniform(0., 60., shape)
        ceiling = source-known_floor+rng.uniform(0., 30., shape)
        source[-1, -1] = known_floor[-1, -1]
        ceiling[-1, -1] = 0.
        incision = rng.uniform(0., 1., shape)*ceiling
        receivers = np.full(shape, -1, dtype=np.int64)
        for index in range(31):
            receivers.ravel()[index] = rng.integers(index+1, 32)
        routing = np.arange(32., 0., -1).reshape(shape)
        originals = [a.copy() for a in (source, incision, ceiling, receivers, routing)]
        result, correction, unresolved = condition_channel_floors(
            source, incision, ceiling, np.ones(shape, dtype=np.bool_), receivers, routing,
            minimum_drop_m=1.)
        floor = (source-result).ravel()
        assert unresolved == 0
        assert np.all(floor[:-1] >= floor[receivers.ravel()[:-1]]+1.-1e-10)
        assert np.all((result >= 0.) & (result <= ceiling))
        assert result[-1, -1] == 0.
        np.testing.assert_allclose(incision+correction, result, atol=1e-12)
        for actual, original in zip((source, incision, ceiling, receivers, routing),
                                    originals, strict=True):
            np.testing.assert_array_equal(actual, original)


@pytest.mark.parametrize("fault", [
    "shape", "nan_source", "nan_route", "negative_cut", "over_cap", "negative_cap",
    "receiver_range", "receiver_negative", "self", "cycle", "flat_rank",
])
def test_invalid_intervals_or_graphs_cannot_be_reported_as_feasible(fault: str) -> None:
    source = np.array([[100., 90., 80.]])
    incision = np.array([[10., 10., 0.]])
    ceiling = np.array([[20., 20., 0.]])
    routing = np.array([[3., 2., 1.]])
    receivers = np.array([[1, 2, -1]], dtype=np.int64)
    if fault == "shape":
        ceiling = ceiling[:, :2]
    elif fault == "nan_source":
        source[0, 0] = np.nan
    elif fault == "nan_route":
        routing[0, 0] = np.nan
    elif fault in ("negative_cut", "over_cap"):
        incision[0, 0] = -1. if fault == "negative_cut" else 21.
    elif fault == "negative_cap":
        ceiling[0, 0] = -1.
    elif fault in ("receiver_range", "receiver_negative", "self"):
        receivers[0, 0] = {"receiver_range": 3, "receiver_negative": -2, "self": 0}[fault]
    elif fault == "cycle":
        receivers[0, 1] = 0
    elif fault == "flat_rank":
        routing[0, 0] = routing[0, 1]
    with pytest.raises(ValueError):
        condition_channel_floors(source, incision, ceiling, np.ones((1, 3), dtype=np.bool_),
                                 receivers, routing)


@pytest.mark.parametrize("drop", [-1., np.inf, np.nan])
def test_drop_must_be_finite_and_nonnegative(drop: float) -> None:
    values: NDArray[np.float64] = np.ones((1, 1))
    with pytest.raises(ValueError, match="downstream drop"):
        condition_channel_floors(values, values*0, values, values.astype(np.bool_),
                                 np.full((1, 1), -1, dtype=np.int64), values, minimum_drop_m=drop)
