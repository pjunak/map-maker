"""Independent scalar selection checks for the array-based D8 sweep."""

from math import hypot

import numpy as np
import pytest
from numpy.typing import NDArray

from map_maker.terrain.pipeline.hydrology import D8_NEIGHBOURS, steepest_flow_receivers

type FloatArray = NDArray[np.float64]


def _scalar_choices(
    ground: FloatArray, land: NDArray[np.bool_], terminal: NDArray[np.bool_],
    barriers: FloatArray | None,
) -> tuple[NDArray[np.int64], FloatArray]:
    receivers = np.full(land.shape, -1, dtype=np.int64)
    slopes = np.zeros_like(ground)
    for row, column in np.ndindex(ground.shape):
        if not land[row, column] or terminal[row, column]:
            continue
        candidates: list[tuple[int, float, float, float]] = []
        level = float(ground[row, column])
        for index, (dy, dx) in enumerate(D8_NEIGHBOURS):
            r, c = row+dy, column+dx
            if not (0 <= r < land.shape[0] and 0 <= c < land.shape[1] and land[r, c]):
                continue
            if barriers is not None and barriers[index, row, column] > level:
                continue
            drop, distance = level-float(ground[r, c]), hypot(dx*3., dy*5.)
            if drop > 0.:
                candidates.append((r*land.shape[1]+c, drop/(1000.*distance), drop, distance))
        if not candidates:
            continue
        # Rank the full candidate list; max retains its first item on ties.
        chosen = max(candidates, key=lambda item: item[1])
        if chosen[1] == 0.:
            scale = max(item[2] for item in candidates)
            chosen = max(candidates, key=lambda item: (item[2]/scale)/item[3])
        receivers[row, column], slopes[row, column] = chosen[:2]
    return receivers, slopes


@pytest.mark.parametrize("layout", ["dense", "strided", "reversed"])
@pytest.mark.parametrize("subnormal", [False, True])
@pytest.mark.parametrize("observed", [False, True])
def test_d8_sweep_matches_scalar_ranking_with_masks_ties_and_tiny_grades(
    layout: str, subnormal: bool, observed: bool,
) -> None:
    rng = np.random.default_rng(731)
    scale = float(np.nextafter(0., 1.)) if subnormal else 1.
    ground = rng.integers(0, 32, size=(13, 17)).astype(np.float64)*scale
    land = rng.random(ground.shape) > .2
    terminal = land & (rng.random(ground.shape) > .93)
    ground[~land] = np.nan
    view = ((slice(None, None, 2), slice(None, None, 2)) if layout == "strided" else
            (slice(None, None, -1), slice(None, None, -1)) if layout == "reversed" else
            (slice(None), slice(None)))
    ground, land, terminal = ground[view], land[view], terminal[view]
    barriers: FloatArray | None = None
    if observed:
        barriers = np.full((8, *ground.shape), np.inf)
        for row, column in np.ndindex(ground.shape):
            for index in range(4, 8):
                dy, dx = D8_NEIGHBOURS[index]
                r, c = row+dy, column+dx
                if not (r < land.shape[0] and 0 <= c < land.shape[1]
                        and land[row, column] and land[r, c]):
                    continue
                height = max(ground[row, column], ground[r, c])
                if (row+column+index) % 3 == 0:
                    height += 4.*scale
                barriers[index, row, column] = barriers[7-index, r, c] = height
    original = ground.copy()
    actual = steepest_flow_receivers(ground, land, x_spacing_km=3., y_spacing_km=5.,
                                     terminal_mask=terminal, edge_barriers_m=barriers)
    expected = _scalar_choices(ground, land, terminal, barriers)
    for measured, reference in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(measured, reference)
    np.testing.assert_array_equal(ground, original)
    assert np.all(actual[0][terminal | ~land] == -1)


@pytest.mark.parametrize("shape", [(1, 9), (9, 1), (1, 1), (0, 0)])
def test_d8_sweep_handles_singleton_axes_and_empty_grids(shape: tuple[int, int]) -> None:
    ground = np.arange(shape[0]*shape[1], dtype=np.float64).reshape(shape)
    land, terminal = np.ones(shape, dtype=np.bool_), np.zeros(shape, dtype=np.bool_)
    actual = steepest_flow_receivers(ground, land, x_spacing_km=3., y_spacing_km=5.)
    expected = _scalar_choices(ground, land, terminal, None)
    for measured, reference in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(measured, reference)
