# pyright: reportPrivateUsage=false
"""Reconstruction must soften grid seams without inventing out-of-range terrain cuts."""

import numpy as np
import pytest
from numpy.typing import NDArray

from benchmarks.terrain import fixture
from map_maker.terrain.pipeline import generate as generation
from map_maker.terrain.pipeline.reconstruction import BoundedBicubicGrid

type FloatArray = NDArray[np.float64]


def _axes() -> tuple[FloatArray, FloatArray]:
    return np.array([0., .2, 1., 2.3, 5., 8.]), np.array([-4., -2., -.7, 0., 3.])


def _queries(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray]:
    rng = np.random.default_rng(42)
    return rng.uniform(x[0], x[-1], 4096), rng.uniform(y[0], y[-1], 4096)


@pytest.mark.parametrize("kind", ["constant", "affine", "bilinear"])
def test_reconstruction_reproduces_analytic_fields(kind: str) -> None:
    x, y = _axes()

    def analytic(a: FloatArray, b: FloatArray) -> FloatArray:
        if kind == "constant":
            return np.full_like(a, 37.)
        return 37. + 2.*a - 3.*b + (a*b if kind == "bilinear" else 0.)

    xx, yy = np.meshgrid(x, y)
    surface = BoundedBicubicGrid(x, y, analytic(xx, yy))
    qx, qy = _queries(x, y)
    np.testing.assert_allclose(surface.sample(qx, qy), analytic(qx, qy), atol=5e-13, rtol=0.)


@pytest.mark.parametrize("capped", [False, True])
def test_reconstruction_preserves_nodes_and_cell_ranges(capped: bool) -> None:
    x, y = _axes()
    rng = np.random.default_rng(173)
    values = rng.lognormal(2., 3., (len(y), len(x)))
    values[1:3, 1:4] = 0.  # sharp valley beside positive peaks and a flat zero patch
    ceiling = values + rng.uniform(0., 2., values.shape) if capped else None
    surface = BoundedBicubicGrid(x, y, values, ceiling)
    xx, yy = np.meshgrid(x, y)
    np.testing.assert_array_equal(surface.sample(xx, yy), values)
    fractions = np.linspace(0., 1., 33)
    a, b = np.meshgrid(fractions, fractions)
    for row in range(len(y) - 1):
        for column in range(len(x) - 1):
            qx = x[column] + a*(x[column + 1] - x[column])
            qy = y[row] + b*(y[row + 1] - y[row])
            samples = surface.sample(qx, qy)
            corners = values[row:row + 2, column:column + 2]
            assert samples.min() >= corners.min() - 1e-10
            assert samples.max() <= corners.max() + 1e-10
            if ceiling is not None:
                c = ceiling[row:row + 2, column:column + 2]
                limit = (c[0, 0]*(1-a) + c[0, 1]*a)*(1-b) + (c[1, 0]*(1-a) + c[1, 1]*a)*b
                assert np.all(samples <= limit + 1e-10)


def test_active_ceiling_remains_authoritative_between_nodes() -> None:
    x, y = np.arange(4, dtype=np.float64), np.array([0., 1.])
    values = np.tile(np.array([0., 1., 1., 0.]), (2, 1))
    qx = np.array([.5, 2.5])
    qy = np.array([.5, .5])
    uncapped = BoundedBicubicGrid(x, y, values).sample(qx, qy)
    capped = BoundedBicubicGrid(x, y, values, values).sample(qx, qy)
    assert np.all(uncapped > .5)
    np.testing.assert_array_equal(capped, [.5, .5])


def test_shared_edge_slopes_converge_without_grid_creases() -> None:
    x, y = _axes()
    values = np.random.default_rng(73).normal(10., 3., (len(y), len(x)))
    surface = BoundedBicubicGrid(x, y, values)
    for axis in (0, 1):
        if axis == 0:
            qx, qy = np.meshgrid(x[1:-1], y[:-1] + .37*np.diff(y))
        else:
            qx, qy = np.meshgrid(x[:-1] + .37*np.diff(x), y[1:-1])
        jumps: list[float] = []
        for h in (1e-4, 1e-5):
            dx, dy = (h, 0.) if axis == 0 else (0., h)
            before = (surface.sample(qx, qy) - surface.sample(qx-dx, qy-dy)) / h
            after = (surface.sample(qx+dx, qy+dy) - surface.sample(qx, qy)) / h
            jumps.append(float(np.max(np.abs(before - after))))
        assert jumps[1] < jumps[0] * .11
        assert jumps[1] < .01


def test_reconstruction_is_axis_symmetric_and_reflection_invariant() -> None:
    x, y = _axes()
    values = np.random.default_rng(92).uniform(-100., 100., (len(y), len(x)))
    qx, qy = _queries(x, y)
    expected = BoundedBicubicGrid(x, y, values).sample(qx, qy)
    transposed = BoundedBicubicGrid(y, x, values.T).sample(qy, qx)
    reflected = BoundedBicubicGrid(-x[::-1], y, values[:, ::-1]).sample(-qx, qy)
    np.testing.assert_allclose(transposed, expected, atol=1e-12, rtol=0.)
    np.testing.assert_allclose(reflected, expected, atol=1e-12, rtol=0.)


def test_prepared_inputs_are_owned_and_pointwise_sampling_is_order_independent() -> None:
    x, y = _axes()
    values = np.random.default_rng(32).uniform(0., 10., (len(y), len(x)))
    ceiling = values + 2.
    qx, qy = _queries(x, y)
    surface = BoundedBicubicGrid(x, y, values, ceiling)
    expected = surface.sample(qx, qy)
    x[:] = -1.
    y[:] = -1.
    values[:] = -1.
    ceiling[:] = -1.
    np.testing.assert_array_equal(surface.sample(qx, qy), expected)
    actual = np.concatenate([surface.sample(qx[a:a+73], qy[a:a+73])
                             for a in range(0, len(qx), 73)])
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(surface.sample(qx[::-1], qy[::-1]), expected[::-1])
    assert not surface.values.flags.writeable
    assert surface.ceiling is not None and not surface.ceiling.flags.writeable


def test_two_node_axes_and_outside_queries_clamp_to_frame() -> None:
    surface = BoundedBicubicGrid(np.array([2., 4.]), np.array([7., 8.]),
                                np.array([[0., 2.], [1., 3.]]))
    qx, qy = np.array([-1., 3., 9.]), np.array([2., 7.5, 11.])
    np.testing.assert_allclose(surface.sample(qx, qy), [0., 1.5, 3.], atol=0.)
    assert surface.sample(np.array([], dtype=np.float64),
                          np.array([], dtype=np.float64)).size == 0


@pytest.mark.parametrize("invalid", ["axis", "shape", "values", "ceiling"])
def test_invalid_preparation_is_rejected(invalid: str) -> None:
    x, y = _axes()
    values = np.zeros((len(y), len(x)))
    ceiling = values + 1.
    if invalid == "axis":
        x[1] = x[0]
    elif invalid == "shape":
        values = values[:-1]
    elif invalid == "values":
        values[0, 0] = np.nan
    else:
        ceiling[0, 0] = -1.
    with pytest.raises(ValueError):
        BoundedBicubicGrid(x, y, values, ceiling)


def test_invalid_queries_are_rejected() -> None:
    x, y = _axes()
    surface = BoundedBicubicGrid(x, y, np.zeros((len(y), len(x))))
    with pytest.raises(ValueError, match="finite and equally shaped"):
        surface.sample(np.array([np.nan]), np.array([0.]))
    with pytest.raises(ValueError, match="finite and equally shaped"):
        surface.sample(np.array([0., 1.]), np.array([0.]))


@pytest.mark.parametrize("case", ["regional", "outlet"])
def test_automatic_valleys_keep_routing_nodes_and_seamless_sampling(case: str) -> None:
    coast, settings, constraints = fixture(case, 65, 42)
    field = generation.prepare_terrain_field(coast, settings, constraints, None)
    valleys = field.automatic_valleys
    xx, yy = np.meshgrid(valleys.x_km, valleys.y_km)
    np.testing.assert_array_equal(valleys.sample_shaping(xx, yy)[0], valleys.drainage.incision_m)
    np.testing.assert_array_equal(valleys.sample_shaping(xx, yy)[1],
                                  valleys.drainage.detail_suppression)
    # Suppression has no ceiling: its shared derivatives should remove seams even
    # where generated channels or regional cut limits change abruptly.
    xx, yy = np.meshgrid(valleys.x_km[1:-1:8], valleys.y_km[1:-1:8])
    yy += .371 * (valleys.y_km[1] - valleys.y_km[0])
    h = (valleys.x_km[1] - valleys.x_km[0]) * 1e-4
    centre = valleys.sample_shaping(xx, yy)[1]
    jump = (valleys.sample_shaping(xx+h, yy)[1] - 2*centre
            + valleys.sample_shaping(xx-h, yy)[1]) / h
    assert float(np.max(np.abs(jump))) < 1e-4
