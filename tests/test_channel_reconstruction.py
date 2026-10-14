# pyright: reportPrivateUsage=false
"""Connected reconstruction must improve diagonal floors within existing authority."""

import numpy as np
import pytest
from numpy.typing import NDArray

from benchmarks.channel_profiles import measure_channels
from benchmarks.terrain import fixture
from map_maker.terrain.pipeline import generate as generation
from map_maker.terrain.pipeline.channel_floor import ChannelFloorReconstruction
from map_maker.terrain.pipeline.channel_reconstruction import (
    ChannelReconstruction,
    channel_diagonals,
)
from map_maker.terrain.pipeline.reconstruction import BoundedBicubicGrid


def _field(
    values: NDArray[np.float64], diagonals: NDArray[np.int8],
    *, cap: NDArray[np.float64] | None = None,
    x: NDArray[np.float64] | None = None, y: NDArray[np.float64] | None = None,
) -> ChannelReconstruction:
    x = np.arange(values.shape[1], dtype=np.float64) if x is None else x
    y = np.arange(values.shape[0], dtype=np.float64) if y is None else y
    limit = np.full_like(values, 100.) if cap is None else cap
    return ChannelReconstruction(BoundedBicubicGrid(x, y, values, limit),
                                 BoundedBicubicGrid(x, y, values/100.), diagonals)


@pytest.mark.parametrize("direction", [1, -1])
def test_diagonal_floor_scalloping_reduces_without_changing_nodes(direction: int) -> None:
    values = np.array([[100., 0.], [0., 100.]])
    if direction == -1:
        values = values[:, ::-1].copy()
    field = _field(values, np.array([[direction]], dtype=np.int8))
    x = np.linspace(0., 1., 257)
    y = x if direction == 1 else 1-x
    baseline = field.incision.sample(x, y)
    cut, suppression = field.sample(x, y)
    # Retaining endpoint derivatives leaves a short shoulder at each end.
    assert np.max(100.-cut) < np.max(100.-baseline) * .4
    assert np.all(cut >= baseline)
    assert np.all(cut <= 100.)
    assert np.all(suppression >= field.suppression.sample(x, y))
    assert np.all(suppression <= 1.)
    xx, yy = np.meshgrid(np.array([0., 1.]), np.array([0., 1.]))
    np.testing.assert_array_equal(field.sample(xx, yy)[0], values)
    np.testing.assert_array_equal(field.sample(xx, yy)[1], values/100.)


def test_original_cut_ceiling_still_limits_connected_floor() -> None:
    values = np.array([[100., 0.], [0., 100.]])
    field = _field(values, np.ones((1, 1), dtype=np.int8), cap=values)
    t = np.linspace(0., 1., 129)
    x, y = np.meshgrid(t, t)
    cut, suppression = field.sample(x, y)
    expected_limit = 100.*((1-x)*(1-y) + x*y)
    assert np.all(cut <= expected_limit + 1e-12)
    assert suppression[64, 64] > .99
    assert cut[64, 64] == 50.


def test_no_connection_does_not_cut_divides_or_change_unrelated_cells() -> None:
    values = np.array([[90., 0., 0.], [0., 90., 0.], [0., 0., 0.]])
    diagonals = np.array([[1, 0], [0, 0]], dtype=np.int8)
    field = _field(values, diagonals)
    x, y = np.meshgrid(np.linspace(1., 2., 50), np.linspace(0., 2., 50))
    cut, suppression = field.sample(x, y)
    np.testing.assert_array_equal(cut, field.incision.sample(x, y))
    np.testing.assert_array_equal(suppression, field.suppression.sample(x, y))
    assert np.all(field.sample(np.full(25, 2.), np.linspace(0., 2., 25))[0] == 0.)


def test_connection_never_fills_an_already_deeper_cut() -> None:
    values = np.array([[0., 100.], [100., 0.]])
    field = _field(values, np.ones((1, 1), dtype=np.int8))
    t = np.linspace(0., 1., 31)
    np.testing.assert_array_equal(field.sample(t, t)[0], field.incision.sample(t, t))


def test_cell_edges_and_first_derivatives_remain_unchanged() -> None:
    values = np.array([[80., 5., 12.], [3., 60., 8.], [6., 7., 90.]])
    field = _field(values, np.array([[1, 0], [0, 1]], dtype=np.int8))
    t = np.linspace(.01, 1.99, 101)
    for axis in (0, 1):
        x, y = (np.ones_like(t), t) if axis == 0 else (t, np.ones_like(t))
        for actual, expected in zip(field.sample(x, y),
                                    (field.incision.sample(x, y), field.suppression.sample(x, y)),
                                    strict=True):
            np.testing.assert_array_equal(actual, expected)
        corrections: list[float] = []
        for h in (1e-4, 1e-5):
            dx, dy = (h, 0.) if axis == 0 else (0., h)
            revised = field.sample(x+dx, y+dy)[0]
            baseline = field.incision.sample(x+dx, y+dy)
            corrections.append(float(np.max(np.abs(revised-baseline)))/h)
        assert corrections[1] <= corrections[0] * .11 + 1e-8


def test_metric_reconstruction_is_symmetric_pointwise_and_owns_topology() -> None:
    x, y = np.array([0., 2., 7.]), np.array([-3., 1., 2.])
    values = np.array([[80., 5., 12.], [3., 60., 8.], [6., 7., 90.]])
    diagonals = np.array([[1, -1], [0, 1]], dtype=np.int8)
    field = _field(values, diagonals, x=x, y=y)
    transposed = _field(values.T, diagonals.T, x=y, y=x)
    reflected = _field(values[:, ::-1], -diagonals[:, ::-1], x=-x[::-1], y=y)
    diagonals[:] = 0
    rng = np.random.default_rng(78)
    qx, qy = rng.uniform(0., 7., 1024), rng.uniform(-3., 2., 1024)
    expected = field.sample(qx, qy)
    for index in (0, 1):
        np.testing.assert_allclose(transposed.sample(qy, qx)[index], expected[index], atol=1e-12)
        np.testing.assert_allclose(reflected.sample(-qx, qy)[index], expected[index], atol=1e-12)
        np.testing.assert_array_equal(field.sample(qx[::-1], qy[::-1])[index],
                                      expected[index][::-1])
        chunks = [field.sample(qx[a:a+31], qy[a:a+31])[index] for a in range(0, len(qx), 31)]
        np.testing.assert_array_equal(np.concatenate(chunks), expected[index])
    assert not field.diagonals.flags.writeable


def test_only_explicit_selected_diagonal_edges_receive_a_connection() -> None:
    receivers = np.array([[3, -1], [-1, -1]], dtype=np.int64)
    selected = np.array([[True, False], [False, False]])
    np.testing.assert_array_equal(channel_diagonals(receivers, selected), [[1]])
    np.testing.assert_array_equal(channel_diagonals(receivers, ~selected), [[0]])
    # A crossing pair has no unambiguous continuous topology in this cell.
    receivers[0, 1] = 2
    selected[0, 1] = True
    np.testing.assert_array_equal(channel_diagonals(receivers, selected), [[0]])
    receivers[0, 0] = 1  # cardinal source does not create a second diagonal
    np.testing.assert_array_equal(channel_diagonals(receivers, selected), [[-1]])
    receivers[0, 0] = 99
    with pytest.raises(ValueError, match="indices"):
        channel_diagonals(receivers, selected)


@pytest.mark.parametrize("case", ["example", "regional"])
def test_public_channel_profiles_improve_without_changing_cardinal_edges(
    case: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coast, settings, constraints = fixture(case, 257, 42)
    field = generation.prepare_terrain_field(coast, settings, constraints, None)
    valley = field.automatic_valleys
    args = (valley.x_km, valley.y_km, valley.drainage.receivers,
            valley.drainage.channel_mask, field.sample_ground)
    # Isolate the diagonal shaping stage from later source-aware floor fitting.
    def unchanged_floor(
        self: ChannelFloorReconstruction, x: NDArray[np.float64], y: NDArray[np.float64],
        incision: NDArray[np.float64], macro: NDArray[np.float64], detail: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        return incision

    monkeypatch.setattr(ChannelFloorReconstruction, "refine", unchanged_floor)
    connected = measure_channels(*args)

    def unconnected(
        self: ChannelReconstruction, x: NDArray[np.float64], y: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return self.incision.sample(x, y), self.suppression.sample(x, y)

    with monkeypatch.context() as patch:
        patch.setattr(ChannelReconstruction, "sample", unconnected)
        baseline = measure_channels(*args)
    assert connected["cardinal_descending"] == baseline["cardinal_descending"]
    assert connected["nonfinite_profile_count"] == baseline["nonfinite_profile_count"]
    assert connected["descending"]["edge_count"] == baseline["descending"]["edge_count"]
    # This stage only changes diagonals. Including unchanged cardinal channels
    # makes its relative improvement depend on the terrain's direction mixture.
    diagonal = connected["diagonal_descending"]
    reference = baseline["diagonal_descending"]
    assert diagonal["edge_count"] == reference["edge_count"]
    assert diagonal["mean_excursion_m"] < reference["mean_excursion_m"] * .4
    assert (connected["descending"]["mean_excursion_m"]
            < baseline["descending"]["mean_excursion_m"])
