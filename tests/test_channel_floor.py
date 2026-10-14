# pyright: reportPrivateUsage=false
"""Sampled-source floor fitting must preserve budgets, topology and authored authority."""

import numpy as np
import pytest
from numpy.typing import NDArray

from benchmarks.channel_profiles import measure_channels
from benchmarks.terrain import fixture
from map_maker.terrain.pipeline import generate as generation
from map_maker.terrain.pipeline.channel_floor import ChannelFloorReconstruction
from map_maker.terrain.pipeline.reconstruction import BoundedBicubicGrid


def _floor(
    source: int = 3, target: int = 4, *, cap: float = 100.,
    land: NDArray[np.bool_] | None = None,
) -> ChannelFloorReconstruction:
    x = np.arange(3, dtype=np.float64)
    xx, _yy = np.meshgrid(x, x)
    receivers = np.full((3, 3), -1, dtype=np.int64)
    receivers.ravel()[source] = target
    return ChannelFloorReconstruction.prepare(
        BoundedBicubicGrid(x, x, np.full((3, 3), 40.), np.full((3, 3), cap)),
        160.-20.*xx, receivers, receivers >= 0,
        np.ones((3, 3), dtype=np.bool_) if land is None else land,
    )


@pytest.mark.parametrize("source,target", [(3, 4), (4, 3), (1, 4), (4, 1), (0, 4), (4, 0),
                                          (1, 3), (3, 1)])
@pytest.mark.parametrize("relief", [-30., 30.])
def test_source_humps_and_cut_pits_move_toward_connected_floor(
    source: int, target: int, relief: float,
) -> None:
    floor = _floor(source, target)
    t = np.linspace(0., 1., 129)
    x, y = (source % 3)*(1-t)+(target % 3)*t, (source // 3)*(1-t)+(target // 3)*t
    macro = 200.-20.*x + relief*np.sin(np.pi*t)**2
    original = np.full_like(t, 40.)
    cut = floor.refine(x, y, original, macro, np.zeros_like(t))
    ground = macro-cut
    assert abs(ground[64]-(160.-20.*x[64])) < 1e-10
    assert np.max(np.abs(ground-(160.-20.*x))) < abs(relief)*.2
    np.testing.assert_array_equal(cut[[0, -1]], original[[0, -1]])
    np.testing.assert_array_equal(original, np.full_like(t, 40.))
    assert np.all((cut >= 0.) & (cut <= 100.))


def test_budget_and_uncut_source_bound_large_demands() -> None:
    floor = _floor(cap=50.)
    x, y = np.array([.5, .5]), np.ones(2)
    macro = np.array([400., 50.])
    cut = floor.refine(x, y, np.full(2, 40.), macro, np.zeros(2))
    np.testing.assert_array_equal(cut, [50., 0.])
    assert macro[0]-cut[0] > 150.  # impossible crest stays an unresolved obstacle
    assert macro[1]-cut[1] == macro[1]  # never fill above the uncut source


def test_missing_land_or_unselected_connection_cannot_supply_a_floor() -> None:
    land = np.ones((3, 3), dtype=np.bool_)
    land[1, 1] = False
    floor = _floor(land=land)
    x, y = np.array([.5]), np.array([1.])
    cut = np.array([40.])
    np.testing.assert_array_equal(floor.refine(x, y, cut, np.array([400.]), x*0), cut)
    floor = _floor()
    x, y = np.array([.5, 1., 1.5]), np.array([0., 1., 1.])
    cut = np.full(3, 40.)
    np.testing.assert_array_equal(floor.refine(x, y, cut, np.full(3, 400.), x*0), cut)


def test_shared_cardinal_edge_is_continuous_with_matching_normal_derivatives() -> None:
    floor = _floor()
    x = np.linspace(.1, .9, 53)
    def sample(offset: float) -> NDArray[np.float64]:
        return floor.refine(x, np.full_like(x, 1.+offset), np.full_like(x, 40.),
                            200.-20.*x+30.*np.sin(np.pi*x)**2, np.zeros_like(x))
    centre = sample(0.)
    errors: list[float] = []
    for h in (1e-4, 1e-5):
        np.testing.assert_allclose(sample(h), sample(-h), atol=1e-12)
        errors.append(float(np.max(np.abs(sample(h)-centre)))/h)
    assert errors[1] < errors[0]*.11


def test_metric_symmetry_chunk_independence_ownership_and_dense_ceiling() -> None:
    x, y = np.array([0., 2., 7.]), np.array([-3., 1., 2.])
    values = np.full((3, 3), 40.)
    cap = np.array([[50., 75., 100.], [40., 100., 90.], [85., 80., 60.]])
    floors = np.array([[100., 120., 140.], [110., 130., 150.], [120., 140., 160.]])
    horizontal = np.ones((3, 2), dtype=np.bool_)
    vertical = np.ones((2, 3), dtype=np.bool_)
    diagonals = np.array([[1, -1], [0, 1]], dtype=np.int8)
    field = ChannelFloorReconstruction(BoundedBicubicGrid(x, y, values, cap),
                                       floors, horizontal, vertical, diagonals)
    transpose = ChannelFloorReconstruction(BoundedBicubicGrid(y, x, values.T, cap.T),
                                           floors.T, vertical.T, horizontal.T, diagonals.T)
    reflected = ChannelFloorReconstruction(
        BoundedBicubicGrid(-x[::-1], y, values[:, ::-1], cap[:, ::-1]),
        floors[:, ::-1], horizontal[:, ::-1], vertical[:, ::-1], -diagonals[:, ::-1])
    floors[:] = 0.
    horizontal[:] = False
    assert not field.floor_m.flags.writeable and not field.horizontal.flags.writeable
    rng = np.random.default_rng(78)
    qx, qy = rng.uniform(0., 7., 2000), rng.uniform(-3., 2., 2000)
    cut, macro, detail = np.full_like(qx, 40.), 180.+50.*np.sin(qx+qy), 10.*np.cos(qx)
    expected = field.refine(qx, qy, cut, macro, detail)
    np.testing.assert_allclose(transpose.refine(qy, qx, cut, macro, detail), expected, atol=1e-12)
    np.testing.assert_allclose(reflected.refine(-qx, qy, cut, macro, detail), expected, atol=1e-12)
    np.testing.assert_array_equal(field.refine(qx[::-1], qy[::-1], cut[::-1], macro[::-1],
                                             detail[::-1]), expected[::-1])
    chunks = [field.refine(qx[a:a+31], qy[a:a+31], cut[a:a+31], macro[a:a+31], detail[a:a+31])
              for a in range(0, len(qx), 31)]
    np.testing.assert_array_equal(np.concatenate(chunks), expected)
    r = np.clip(np.searchsorted(y, qy)-1, 0, 1)
    c = np.clip(np.searchsorted(x, qx)-1, 0, 1)
    tx, ty = (qx-x[c])/(x[c+1]-x[c]), (qy-y[r])/(y[r+1]-y[r])
    ceiling = ((cap[r, c]*(1-tx)+cap[r, c+1]*tx)*(1-ty)
               + (cap[r+1, c]*(1-tx)+cap[r+1, c+1]*tx)*ty)
    assert np.all((expected >= 0.) & (expected <= ceiling))


@pytest.mark.parametrize("case", ["example", "regional", "authored"])
def test_public_floor_profiles_reduce_excursions_and_keep_canonical_ground(
    case: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coast, settings, constraints = fixture(case, 257, 42)
    field = generation.prepare_terrain_field(coast, settings, constraints, None)
    valley = field.automatic_valleys
    args = (valley.x_km, valley.y_km, valley.drainage.receivers,
            valley.drainage.channel_mask, field.sample_ground)
    xx, yy = np.meshgrid(valley.x_km, valley.y_km)
    canonical = field.sample_ground(xx, yy)
    revised = measure_channels(*args)
    def original(
        self: ChannelFloorReconstruction, x: NDArray[np.float64], y: NDArray[np.float64],
        incision: NDArray[np.float64], macro: NDArray[np.float64], detail: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        return incision
    with monkeypatch.context() as patch:
        patch.setattr(ChannelFloorReconstruction, "refine", original)
        baseline = measure_channels(*args)
        np.testing.assert_array_equal(canonical, field.sample_ground(xx, yy))
    assert revised["nonfinite_profile_count"] == baseline["nonfinite_profile_count"]
    assert revised["descending"]["edge_count"] == baseline["descending"]["edge_count"]
    # Regional composition changes the source terrain and selected edge set.
    # Require a substantial relative gain AND a physical residual bound; a
    # percentage alone can hide a worsening corrected surface as raw relief grows.
    cardinal = revised["cardinal_descending"]["mean_excursion_m"]
    assert cardinal < baseline["cardinal_descending"]["mean_excursion_m"] / 3.
    assert cardinal < .25
    assert (revised["descending"]["mean_excursion_m"]
            < baseline["descending"]["mean_excursion_m"]*.75)
