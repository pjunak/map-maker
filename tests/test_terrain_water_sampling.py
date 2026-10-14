"""Finer water evidence is deterministic, bounded and based on unmodified ground."""

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import NDArray
from shapely.geometry import Polygon

from map_maker.terrain.domain import TerrainBasin
from map_maker.terrain.pipeline.water import prepare_basins
from map_maker.terrain.pipeline.water_sampling import (
    review_shorelines,
    sample_ground_positions,
    sample_ground_profile,
)


def test_profile_includes_corners_and_midpoints_with_bounded_spacing_and_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.SAMPLE_BATCH_SIZE", 2)
    batches: list[int] = []

    def sample(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        batches.append(x.size)
        return (x + 2 * y).astype(np.float32)

    vertices = ((0., 0.), (0., 0.), (.1, 0.), (1., 2.))
    profile = sample_ground_profile(vertices, .5, sample)
    assert profile.status == "sampled"
    assert profile.requested_sample_count == len(profile.positions_km) == len(profile.ground_m)
    assert set(vertices) <= set(profile.positions_km)
    assert (.05, 0.) in profile.positions_km
    assert max(batches) <= 2
    points = np.asarray(profile.positions_km)
    assert np.all(np.linalg.norm(np.diff(points, axis=0), axis=1) <= .5 + 1e-12)
    assert profile.minimum_ground_m == 0
    assert profile.maximum_ground_m == 5
    assert profile.maximum_position_km == (1., 2.)
    assert sample_ground_profile(vertices, .5, sample) == profile


def test_budget_exceeded_does_not_evaluate_or_return_partial_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.MAX_PROFILE_SAMPLES", 10)

    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("Budget must be checked before evaluation.")

    profile = sample_ground_profile(((0., 0.), (20., 0.)), .25, unexpected)
    assert profile.status == "budget_exceeded"
    assert profile.requested_sample_count == 81
    assert profile.positions_km == profile.ground_m == ()
    assert profile.minimum_ground_m is profile.maximum_ground_m is None


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_ground_cannot_be_reported_clear(value: float) -> None:
    def sample(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.full(x.shape, value, dtype=np.float32)
    with pytest.raises(ValueError, match="finite ground"):
        sample_ground_profile(((0., 0.), (1., 0.)), .25, sample)


@pytest.mark.parametrize("spacing", [0., -.1, float("nan"), float("inf")])
def test_invalid_spacing_is_rejected(spacing: float) -> None:
    def sample(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.zeros(x.shape, dtype=np.float32)
    with pytest.raises(ValueError, match="positive spacing"):
        sample_ground_profile(((0., 0.), (1., 0.)), spacing, sample)


def test_shoreline_finds_a_subgrid_opening_and_is_independent_of_ring_direction() -> None:
    lake = TerrainBasin(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.)),
                        "lake", 10, (1., .5))
    land = Polygon(((-1, -1), (5, -1), (5, 5), (-1, 5)))
    basins = prepare_basins((lake,), 4, 4, land, 100)

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        # Integer grid samples miss the narrow opening centered between them.
        notch = np.maximum(0., 1 - np.abs(x - .5) / .1) * (y == 0)
        return (20 - 15 * notch).astype(np.float32)

    x, y = np.meshgrid(np.arange(5, dtype=np.float64), np.arange(5, dtype=np.float64))
    np.testing.assert_array_equal(ground(x, y), 20)
    review = review_shorelines(basins, .25, 1., ground)[0]
    assert review is not None
    assert review.profile.minimum_ground_m == 5
    assert review.low_sample_count == review.uncontrolled_low_sample_count == 1
    reverse = prepare_basins((replace(lake, points=tuple(reversed(lake.points))),),
                              4, 4, land, 100)
    assert review_shorelines(reverse, .25, 1., ground)[0] == review


def test_only_the_declared_bounded_opening_is_allowed() -> None:
    lake = TerrainBasin(((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.)),
                        "lake", 10, (1., .5))
    land = Polygon(((-1, -1), (5, -1), (5, 5), (-1, 5)))

    def ground(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        return np.where((x == 4) & (np.abs(y - 2) <= .5), 5., 20.).astype(np.float32)

    basins = prepare_basins((lake,), 4, 4, land, 100)
    review = review_shorelines(basins, .25, .5, ground)[0]
    assert review is not None
    assert review.low_sample_count == 5
    assert review.uncontrolled_low_sample_count == 0
    closed = prepare_basins((replace(lake, outlet=None),), 4, 4, land, 100)
    other = review_shorelines(closed, .25, .5, ground)[0]
    assert other is not None
    assert other.opening_radius_km == 0
    assert other.uncontrolled_low_sample_count == 5


@pytest.mark.parametrize("strided", [False, True])
def test_exact_coordinate_reuse_preserves_every_station_and_float_bits(
    monkeypatch: pytest.MonkeyPatch, strided: bool,
) -> None:
    positions = np.asarray(((0., 1.), (-0., 1.), (2., 3.), (2., 4.),
                            (np.nextafter(2., 3.), 3.), (0., 1.), (2., 3.), (-0., 1.)))
    if strided:
        positions = positions[::-1]
    original = positions.tobytes()
    monkeypatch.setattr("map_maker.terrain.pipeline.water_sampling.SAMPLE_BATCH_SIZE", 2)
    seen: list[bytes] = []
    batches: list[int] = []

    def sampler(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        batches.append(len(x))
        seen.extend(np.asarray((a, b)).tobytes() for a, b in zip(x, y, strict=True))
        return np.copysign(x + y, x).astype(np.float32)

    expected = np.copysign(positions[:, 0] + positions[:, 1], positions[:, 0]).astype(np.float32)
    ground = sample_ground_positions(positions, sampler)
    assert ground.tobytes() == expected.tobytes()
    assert len(ground) == len(positions) == 8
    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == {p.tobytes() for p in positions}
    assert max(batches) <= 2
    assert positions.tobytes() == original
    # Reuse is confined to one evaluation, with no stale values on regeneration.
    changed = sample_ground_positions(positions, lambda x, y: np.full(x.shape, 77., np.float32))
    np.testing.assert_array_equal(changed, 77.)


def test_empty_profile_positions_do_not_evaluate_ground() -> None:
    def unexpected(x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float32]:
        pytest.fail("An empty network needs no ground evaluations.")

    result = sample_ground_positions(np.empty((0, 2), dtype=np.float64), unexpected)
    assert result.shape == (0,) and result.dtype == np.float32
